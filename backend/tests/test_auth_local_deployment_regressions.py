from fastapi import Request, Response
import pytest
from api.auth_routes import _AUTH_PAGE_STYLE, _state_free_auth_page
from auth.middleware import enforce_general_web_security

def _request(*, scheme="http", host="debridpulse.local:8081", origin=None, fetch_site="same-origin"):
    headers=[(b"host",host.encode())]
    if origin is not None: headers.append((b"origin",origin.encode()))
    if fetch_site is not None: headers.append((b"sec-fetch-site",fetch_site.encode()))
    return Request({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"POST","scheme":scheme,"path":"/login","raw_path":b"/login","query_string":b"","headers":headers,"client":("192.168.226.10",54321),"server":("debridpulse.local",8081)})

async def _ok(_request): return Response(content="ok",status_code=200)

@pytest.mark.asyncio
async def test_direct_http_login_origin_is_not_reclassified_by_public_https_base(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL","https://debridpulse.local:8081")
    assert (await enforce_general_web_security(_request(origin="http://debridpulse.local:8081"),_ok)).status_code == 200

@pytest.mark.asyncio
async def test_trusted_proxy_https_scope_remains_same_origin():
    assert (await enforce_general_web_security(_request(scheme="https",host="debridpulse.example",origin="https://debridpulse.example"),_ok)).status_code == 200

@pytest.mark.asyncio
async def test_cross_site_login_mutation_is_still_rejected(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL","https://debridpulse.local:8081")
    assert (await enforce_general_web_security(_request(origin="https://evil.example",fetch_site="cross-site"),_ok)).status_code == 403

def test_auth_pages_use_debridpulse_dark_theme_palette():
    assert "--bg:#090812" in _AUTH_PAGE_STYLE
    assert "--accent:#a67cff" in _AUTH_PAGE_STYLE
    assert "#f08a24" not in _AUTH_PAGE_STYLE
    response=_state_free_auth_page(message="Try again shortly.",status_code=429,retry_after=60)
    assert 'class="card"' in response.body.decode()
    assert "style-src 'unsafe-inline'" in response.headers["Content-Security-Policy"]


@pytest.mark.asyncio
async def test_same_origin_fetch_metadata_survives_server_origin_reconstruction_mismatch():
    request = _request(
        scheme="https",
        host="container-internal:8080",
        origin="http://192.168.226.200:8081",
        fetch_site="same-origin",
    )
    assert (await enforce_general_web_security(request, _ok)).status_code == 200


@pytest.mark.asyncio
async def test_same_site_different_origin_does_not_bypass_exact_origin_check():
    request = _request(
        scheme="http",
        host="debridpulse.local:8081",
        origin="http://other.debridpulse.local:8081",
        fetch_site="same-site",
    )
    assert (await enforce_general_web_security(request, _ok)).status_code == 403


@pytest.mark.asyncio
async def test_malformed_origin_is_rejected_even_with_same_origin_fetch_metadata():
    request = _request(origin="null", fetch_site="same-origin")
    assert (await enforce_general_web_security(request, _ok)).status_code == 403
