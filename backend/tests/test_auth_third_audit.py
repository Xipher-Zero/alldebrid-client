import asyncio
import json
import os
import stat
import threading
from types import SimpleNamespace

import pytest
from fastapi import Request

from api.auth_config_routes import AuthenticationConfigUpdate
from auth import oidc, passwords, transitions
from auth.models import Principal
from auth.passwords import hash_password
from core import secure_files


def _request(body: bytes):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "PUT", "scheme": "https", "path": "/api/auth/config",
        "raw_path": b"/api/auth/config", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345), "server": ("pulse.example", 443),
    }, receive=receive)


def _password_only_settings():
    return SimpleNamespace(
        auth_password_enabled=True, auth_username="operator",
        auth_password_hash=hash_password("secret"), auth_oidc_enabled=False,
    )


@pytest.mark.asyncio
async def test_transition_guard_matches_pydantic_false_string_coercion_for_open_mode():
    body = json.dumps({"auth_password_enabled": "false", "auth_oidc_enabled": "false"}).encode()
    parsed = AuthenticationConfigUpdate.model_validate_json(body)
    assert parsed.auth_password_enabled is False
    assert parsed.auth_oidc_enabled is False
    rejection = await transitions.settings_transition_rejection(
        _request(body), Principal.password_session("operator"), _password_only_settings()
    )
    assert rejection is not None and rejection.status_code == 409


@pytest.mark.asyncio
async def test_transition_guard_matches_pydantic_true_string_for_password_clear():
    body = json.dumps({
        "auth_password_enabled": True, "auth_oidc_enabled": False, "clear_password": "true"
    }).encode()
    parsed = AuthenticationConfigUpdate.model_validate_json(body)
    assert parsed.clear_password is True
    rejection = await transitions.settings_transition_rejection(
        _request(body), Principal.password_session("operator"), _password_only_settings()
    )
    assert rejection is not None and rejection.status_code == 409


def test_oidc_email_allowlist_requires_verified_email_and_requests_userinfo_completion():
    cfg = oidc.OidcConfiguration(
        issuer="https://id.example/application/o/debridpulse", client_id="client",
        client_secret="", scopes=("openid", "email"),
        callback_url="https://pulse.example/auth/oidc/callback", provider_name="OIDC",
        allow_all=False, allowed_subjects=(), allowed_emails=("operator@example.com",),
        allowed_groups=(), group_claim="groups",
    )
    claims = {"iss": cfg.issuer, "sub": "user-1", "email": "operator@example.com"}
    assert oidc._claims_need_userinfo(cfg, claims) is True
    with pytest.raises(oidc.OidcAuthorizationError):
        oidc.authorize_oidc_claims(cfg, claims)
    verified = {**claims, "email_verified": True}
    assert oidc._claims_need_userinfo(cfg, verified) is False
    assert oidc.authorize_oidc_claims(cfg, verified).authenticated is True


@pytest.mark.asyncio
async def test_cancelled_password_request_does_not_release_live_worker_slot(monkeypatch):
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(passwords, "_PASSWORD_VERIFY_SLOTS", semaphore)
    release_first = threading.Event()
    release_second = threading.Event()
    first_started = threading.Event()
    second_started = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def blocking_verify(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_started.set()
            release_first.wait(timeout=5)
        else:
            second_started.set()
            release_second.wait(timeout=5)
        return False

    monkeypatch.setattr(passwords, "verify_password_candidate", blocking_verify)
    first = asyncio.create_task(passwords.verify_password_candidate_async("hash", "pw", use_configured_hash=False))
    assert await asyncio.to_thread(first_started.wait, 1.0) is True

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    # Repeated cancellation of the already-cancelled request must not affect
    # ownership of the still-running worker's semaphore slot.
    first.cancel()

    second = asyncio.create_task(passwords.verify_password_candidate_async("hash", "pw2", use_configured_hash=False))
    await asyncio.sleep(0.1)
    assert second_started.is_set() is False
    assert semaphore.locked() is True

    release_first.set()
    assert await asyncio.to_thread(second_started.wait, 1.0) is True
    release_second.set()
    assert await second is False


def test_sensitive_atomic_json_is_0600_before_payload_write_even_without_chmod(tmp_path, monkeypatch):
    target = tmp_path / "config" / "secret.json"
    observed_modes = []
    real_dump = secure_files.json.dump

    def inspect_dump(payload, handle, **kwargs):
        observed_modes.append(stat.S_IMODE(os.fstat(handle.fileno()).st_mode))
        return real_dump(payload, handle, **kwargs)

    def chmod_unavailable(*_args, **_kwargs):
        raise OSError("chmod unavailable")

    monkeypatch.setattr(secure_files.json, "dump", inspect_dump)
    monkeypatch.setattr(secure_files.os, "chmod", chmod_unavailable)
    monkeypatch.setattr(secure_files.os, "fchmod", chmod_unavailable)
    old_umask = os.umask(0)
    try:
        secure_files.atomic_write_json(target, {"secret": "value"}, indent=2)
    finally:
        os.umask(old_umask)
    assert observed_modes == [0o600]
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_sensitive_config_and_api_token_writers_use_secure_atomic_helper():
    root = os.path.dirname(os.path.dirname(__file__))
    config_source = open(os.path.join(root, "core", "config.py"), encoding="utf-8").read()
    token_source = open(os.path.join(root, "auth", "api_tokens.py"), encoding="utf-8").read()
    assert "atomic_write_json(CONFIG_PATH, data, indent=2)" in config_source
    assert "atomic_write_json(" in token_source and "self.path," in token_source


@pytest.mark.asyncio
async def test_transition_guard_matches_pydantic_true_string_for_open_mode_confirmation():
    body = json.dumps({
        "auth_password_enabled": "false",
        "auth_oidc_enabled": "false",
        "confirm_open_mode": "true",
    }).encode()
    parsed = AuthenticationConfigUpdate.model_validate_json(body)
    assert parsed.confirm_open_mode is True
    rejection = await transitions.settings_transition_rejection(
        _request(body),
        Principal.password_session("operator"),
        _password_only_settings(),
    )
    assert rejection is None


def test_prospective_oidc_readiness_does_not_treat_false_string_as_allow_all():
    current = SimpleNamespace(
        auth_oidc_enabled=False,
        oidc_provider_name="OIDC",
        oidc_issuer_url="https://id.example/application/o/debridpulse/",
        oidc_client_id="client",
        oidc_client_secret="",
        oidc_scopes=["openid", "email"],
        public_base_url="https://pulse.example",
        oidc_allow_all=False,
        oidc_allowed_subjects=[],
        oidc_allowed_emails=[],
        oidc_allowed_groups=[],
        oidc_group_claim="groups",
    )
    payload = {
        "auth_oidc_enabled": "true",
        "oidc_allow_all": "false",
    }
    assert transitions._prospective_oidc_ready(payload, current) is False


def test_api_token_clear_fsyncs_parent_directory(tmp_path, monkeypatch):
    from auth import api_tokens

    path = tmp_path / "api-token.json"
    store = api_tokens.ApiTokenStore(path)
    store.generate()
    calls = []
    monkeypatch.setattr(api_tokens, "fsync_parent_directory", lambda target: calls.append(target))
    store.clear()
    assert calls == [path]
    assert path.exists() is False
    assert store.configured is False
    assert store.enabled is False


def test_verified_email_requirement_is_documented_in_operator_surfaces():
    root = os.path.dirname(os.path.dirname(__file__))
    repo_root = os.path.dirname(root)
    docs = open(os.path.join(repo_root, "docs", "authentication.md"), encoding="utf-8").read()
    ui = open(os.path.join(repo_root, "frontend", "static", "auth-settings.js"), encoding="utf-8").read()
    assert "email_verified: true" in docs
    assert "email_verified=true" in ui
