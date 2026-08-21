import json
from types import SimpleNamespace

import pytest
from fastapi import Request

from auth.models import Principal
from auth.transitions import settings_transition_rejection


def _settings(**updates):
    values = {
        "auth_password_enabled": False,
        "auth_username": "",
        "auth_password_hash": "",
        "auth_oidc_enabled": False,
        "oidc_provider_name": "OpenID Connect",
        "oidc_issuer_url": "",
        "oidc_client_id": "",
        "oidc_client_secret": "",
        "oidc_scopes": ["openid", "profile", "email"],
        "oidc_allow_all": False,
        "oidc_allowed_subjects": [],
        "oidc_allowed_emails": [],
        "oidc_allowed_groups": [],
        "oidc_group_claim": "groups",
        "public_base_url": "",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _request(payload, path="/api/settings"):
    body = json.dumps(payload).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("pulse.example", 443),
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_legacy_settings_cannot_enable_incomplete_password_as_only_auth():
    response = await settings_transition_rejection(
        _request({"auth_password_enabled": True, "auth_username": "operator"}),
        Principal.anonymous(),
        _settings(),
    )
    assert response is not None
    assert response.status_code == 409
    assert b"locally usable" in response.body


@pytest.mark.asyncio
async def test_dedicated_settings_cannot_enable_deny_everyone_oidc_as_only_auth():
    payload = {
        "auth_oidc_enabled": True,
        "oidc_issuer_url": "https://id.example/application/o/debridpulse",
        "oidc_client_id": "debridpulse-client",
        "public_base_url": "https://pulse.example",
        "oidc_allow_all": False,
        "oidc_allowed_subjects": [],
        "oidc_allowed_emails": [],
        "oidc_allowed_groups": [],
    }
    response = await settings_transition_rejection(
        _request(payload, path="/api/auth/config"),
        Principal.anonymous(),
        _settings(),
    )
    assert response is not None
    assert response.status_code == 409
    assert b"locally usable" in response.body


@pytest.mark.asyncio
async def test_open_mode_can_enable_locally_usable_oidc_as_only_auth():
    payload = {
        "auth_oidc_enabled": True,
        "oidc_issuer_url": "https://id.example/application/o/debridpulse",
        "oidc_client_id": "debridpulse-client",
        "public_base_url": "https://pulse.example",
        "oidc_allowed_groups": ["debridpulse-operators"],
    }
    response = await settings_transition_rejection(
        _request(payload),
        Principal.anonymous(),
        _settings(),
    )
    assert response is None


@pytest.mark.asyncio
async def test_broken_supplemental_oidc_does_not_disable_working_password():
    current = _settings(
        auth_password_enabled=True,
        auth_username="operator",
        auth_password_hash="$argon2id$configured",
    )
    response = await settings_transition_rejection(
        _request({"auth_oidc_enabled": True, "oidc_issuer_url": "not-https"}),
        Principal.password_session("operator"),
        current,
    )
    assert response is None
