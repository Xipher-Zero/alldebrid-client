from pathlib import Path

from fastapi import Request, Response
import pytest

from api.auth_routes import _AUTH_PAGE_STYLE, _state_free_auth_page
from auth.middleware import enforce_general_web_security
from auth.sessions import request_is_secure


def _request(*, scheme="http", host="debridpulse.local:8081", origin=None, fetch_site="same-origin"):
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if fetch_site is not None:
        headers.append((b"sec-fetch-site", fetch_site.encode()))
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": scheme,
        "path": "/login",
        "raw_path": b"/login",
        "query_string": b"",
        "headers": headers,
        "client": ("192.168.226.10", 54321),
        "server": ("debridpulse.local", 8081),
    })


async def _ok(_request):
    return Response(content="ok", status_code=200)


@pytest.mark.asyncio
async def test_external_https_origin_is_accepted_behind_http_proxy(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://download.xipherzero.com")
    request = _request(
        scheme="http",
        host="download.xipherzero.com",
        origin="https://download.xipherzero.com",
        fetch_site="same-origin",
    )
    assert request_is_secure(request) is True
    assert (await enforce_general_web_security(request, _ok)).status_code == 200


@pytest.mark.asyncio
async def test_direct_lan_http_remains_same_origin_with_external_base_configured(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://download.xipherzero.com")
    request = _request(
        scheme="http",
        host="192.168.226.200:8081",
        origin="http://192.168.226.200:8081",
        fetch_site="same-origin",
    )
    assert request_is_secure(request) is False
    assert (await enforce_general_web_security(request, _ok)).status_code == 200


@pytest.mark.asyncio
async def test_same_origin_fetch_metadata_does_not_bypass_origin_mismatch(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://download.xipherzero.com")
    request = _request(
        scheme="http",
        host="internal.example:8080",
        origin="https://different.example",
        fetch_site="same-origin",
    )
    assert (await enforce_general_web_security(request, _ok)).status_code == 403


@pytest.mark.asyncio
async def test_cross_site_login_mutation_is_still_rejected(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://download.xipherzero.com")
    request = _request(
        host="download.xipherzero.com",
        origin="https://evil.example",
        fetch_site="cross-site",
    )
    assert (await enforce_general_web_security(request, _ok)).status_code == 403


def test_invalid_public_base_path_is_not_trusted_for_secure_classification(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://download.xipherzero.com/not-an-origin")
    request = _request(host="download.xipherzero.com")
    assert request_is_secure(request) is False


def test_auth_pages_use_debridpulse_dark_theme_palette():
    assert "--bg:#090812" in _AUTH_PAGE_STYLE
    assert "--accent:#a67cff" in _AUTH_PAGE_STYLE
    assert "#f08a24" not in _AUTH_PAGE_STYLE
    response = _state_free_auth_page(message="Try again shortly.", status_code=429, retry_after=60)
    assert 'class="card"' in response.body.decode()
    assert "style-src 'unsafe-inline'" in response.headers["Content-Security-Policy"]


def test_auth_settings_present_external_base_as_general_security_setting():
    source = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "auth-settings.js").read_text()
    assert "External Base URL (Canonical Origin)" in source
    assert "reverse-proxy origin validation" in source
    assert "PUBLIC_BASE_URL environment variable" in source
