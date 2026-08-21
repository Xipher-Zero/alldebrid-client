from __future__ import annotations

import html
import os
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from auth.csrf import (
    clear_login_csrf_cookie,
    login_csrf_cookie_name,
    login_csrf_store,
    set_login_csrf_cookie,
)
from auth.manager import verify_local_credentials
from auth.models import AuthMechanism, Principal
from auth.oidc import (
    OIDC_CORRELATION_COOKIE,
    OIDC_TRANSACTION_TTL_SECONDS,
    OidcError,
    begin_oidc_login,
    complete_oidc_login,
    oidc_auth_ready,
    oidc_transaction_store,
)
from auth.oidc_version import oidc_configuration_version
from auth.passwords import password_credential_version
from auth.policy import (
    interactive_auth_enabled,
    oidc_auth_enabled,
    password_auth_enabled,
    password_auth_ready,
    safe_return_path,
)
from auth.sessions import (
    clear_session_cookie,
    session_cookie_token,
    session_store,
    set_session_cookie,
)
from core.config import get_settings


router = APIRouter()


def _session_lifetime_seconds(cfg) -> int:
    hours = int(getattr(cfg, "auth_session_lifetime_hours", 12) or 12)
    return max(3600, min(168 * 3600, hours * 3600))


def _session_record_current(record, cfg) -> bool:
    if record is None:
        return False
    mechanism = record.principal.mechanism
    if mechanism is AuthMechanism.PASSWORD_SESSION:
        if not password_auth_ready(cfg):
            return False
        current_version = password_credential_version(getattr(cfg, "auth_password_hash", ""))
        return bool(current_version and record.credential_version == current_version)
    if mechanism is AuthMechanism.OIDC_SESSION:
        if not oidc_auth_ready(cfg):
            return False
        current_version = oidc_configuration_version(cfg)
        return bool(current_version and record.credential_version == current_version)
    return False


def _static_asset(name: str) -> Path:
    candidates: list[Path] = []
    configured = os.getenv("STATIC_DIR", "").strip()
    if configured:
        candidates.append(Path(configured) / name)
    candidates.extend(
        (
            Path(__file__).resolve().parents[2] / "frontend" / "static" / name,
            Path("/app/frontend/static") / name,
            Path("/app/static") / name,
        )
    )
    asset = next((candidate for candidate in candidates if candidate.is_file()), None)
    if asset is None:
        raise RuntimeError(f"Frontend asset not found: {name}")
    return asset


def _login_page(
    request: Request,
    *,
    csrf_token: str,
    return_to: str,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    cfg = get_settings()
    password_enabled = password_auth_enabled(cfg)
    password_ready = password_auth_ready(cfg)
    oidc_enabled = oidc_auth_enabled(cfg)
    oidc_ready = oidc_auth_ready(cfg) if oidc_enabled else False
    provider_name = html.escape(
        str(getattr(cfg, "oidc_provider_name", "") or "OpenID Connect").strip()
        or "OpenID Connect"
    )
    error_html = (
        f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    )

    controls: list[str] = []
    if oidc_enabled and oidc_ready:
        controls.append(
            f'<a class="auth-action primary oidc" href="/auth/oidc/start?next={quote(return_to, safe="")}">'
            f"Continue with {provider_name}</a>"
        )
    elif oidc_enabled:
        controls.append(
            '<div class="error" role="alert">OpenID Connect is enabled but its local '
            "configuration is incomplete or invalid.</div>"
        )

    if password_enabled and password_ready:
        if oidc_ready:
            controls.append('<div class="divider"><span>or use local password</span></div>')
        password_button_class = "secondary" if oidc_ready else "primary"
        controls.append(
            f"""
            <form method="post" action="/login" autocomplete="on">
              <input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">
              <input type="hidden" name="next" value="{html.escape(return_to, quote=True)}">
              <label for="username">Username</label>
              <input id="username" name="username" type="text" maxlength="256" autocomplete="username" required>
              <label for="password">Password</label>
              <input id="password" name="password" type="password" maxlength="4096" autocomplete="current-password" required>
              <button class="auth-action {password_button_class}" type="submit">Sign In</button>
            </form>
            """
        )
    elif password_enabled:
        controls.append(
            '<div class="error" role="alert">Username &amp; Password authentication is enabled '
            "but is not fully configured. That mechanism is unavailable.</div>"
        )

    if not password_enabled and not oidc_enabled:
        controls.append('<p class="muted">Authentication is not currently required.</p>')

    interactive_controls = "\n".join(controls)
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · DebridPulse</title>
<style>
:root{{--bg:#0c0d10;--surface:#14161b;--surface2:#1b1e25;--border:#2a2e38;--text:#f2f3f5;--muted:#989daa;--accent:#f08a24;--danger:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 50% 20%,#1a1d24 0,var(--bg) 48%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px}}
.card{{width:min(420px,100%);background:rgba(20,22,27,.96);border:1px solid var(--border);border-radius:18px;padding:30px;box-shadow:0 24px 70px rgba(0,0,0,.38)}}
.brand{{font-size:28px;font-weight:800;letter-spacing:-.7px;margin-bottom:6px}}.brand span{{color:var(--accent)}}h1{{font-size:17px;margin:0 0 24px;color:#c8cbd2;font-weight:500}}
label{{display:block;font-size:12px;font-weight:700;color:#c4c7cf;margin:14px 0 7px}}input{{width:100%;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:9px;padding:11px 12px;font:inherit;outline:none}}input:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(240,138,36,.12)}}
.auth-action{{width:100%;margin-top:20px;border-radius:9px;padding:11px 14px;font-weight:800;font-size:14px;cursor:pointer;text-align:center;text-decoration:none;display:block}}button.auth-action{{font-family:inherit}}.auth-action:hover{{filter:brightness(1.06)}}.primary{{border:0;background:var(--accent);color:#17110a}}.secondary{{background:var(--surface2);color:var(--text);border:1px solid var(--border)}}
.divider{{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:11px;margin:22px 0 0}}.divider:before,.divider:after{{content:"";height:1px;background:var(--border);flex:1}}
.error{{border:1px solid rgba(255,107,107,.4);background:rgba(255,107,107,.08);color:#ffc0c0;padding:10px 12px;border-radius:9px;font-size:12px;line-height:1.45;margin:0 0 15px}}.muted{{color:var(--muted);font-size:13px;line-height:1.55}}
.foot{{margin-top:22px;padding-top:16px;border-top:1px solid var(--border);color:#747986;font-size:11px;line-height:1.5}}
</style>
</head>
<body>
<main class="card">
  <div class="brand">Debrid<span>Pulse</span></div>
  <h1>Sign in to continue</h1>
  {error_html}
  {interactive_controls}
  <div class="foot">Password-only LAN deployments may operate over HTTP. OpenID Connect requires a canonical HTTPS external URL.</div>
</main>
</body>
</html>"""
    response = HTMLResponse(content=body, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _issue_login_page(
    request: Request,
    *,
    return_to: str,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    browser_nonce, form_token = login_csrf_store.issue()
    response = _login_page(
        request,
        csrf_token=form_token,
        return_to=safe_return_path(return_to),
        error=error,
        status_code=status_code,
    )
    set_login_csrf_cookie(response, request, browser_nonce)
    return response


def _set_oidc_correlation_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=OIDC_CORRELATION_COOKIE,
        value=str(value),
        max_age=OIDC_TRANSACTION_TTL_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_oidc_correlation_cookie(response: Response) -> None:
    response.delete_cookie(
        key=OIDC_CORRELATION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


@router.get("/api/auth/status")
async def public_auth_status():
    """Minimal public bootstrap state needed to render the login experience."""
    cfg = get_settings()
    password_enabled = password_auth_enabled(cfg)
    oidc_enabled = oidc_auth_enabled(cfg)
    return {
        "authentication_required": interactive_auth_enabled(cfg),
        "password_enabled": password_enabled,
        "password_ready": password_auth_ready(cfg) if password_enabled else False,
        "oidc_enabled": oidc_enabled,
        "oidc_ready": oidc_auth_ready(cfg) if oidc_enabled else False,
        "oidc_provider_name": (
            str(getattr(cfg, "oidc_provider_name", "") or "OpenID Connect").strip()
            or "OpenID Connect"
        ),
    }


@router.get("/app.js", include_in_schema=False)
async def application_javascript_bundle():
    """Serve the protected browser bootstrap before the existing app script."""
    auth_js = _static_asset("auth.js").read_text(encoding="utf-8")
    app_js = _static_asset("app.js").read_text(encoding="utf-8")
    response = Response(
        content=f"{auth_js}\n;\n{app_js}",
        media_type="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    cfg = get_settings()
    return_to = safe_return_path(next)
    if not interactive_auth_enabled(cfg):
        return RedirectResponse(url=return_to, status_code=303)

    existing_token = session_cookie_token(request)
    existing = session_store.resolve(existing_token) if existing_token else None
    if _session_record_current(existing, cfg):
        return RedirectResponse(url=return_to, status_code=303)
    if existing_token:
        session_store.revoke(existing_token)

    response = _issue_login_page(request, return_to=return_to)
    if existing_token:
        clear_session_cookie(response, request)
    return response


@router.post("/login")
async def password_login(request: Request):
    cfg = get_settings()
    if not password_auth_enabled(cfg):
        return _issue_login_page(
            request,
            return_to="/",
            error="Username & Password authentication is disabled.",
            status_code=403,
        )
    if not password_auth_ready(cfg):
        return _issue_login_page(
            request,
            return_to="/",
            error="Username & Password authentication is unavailable because its configuration is incomplete.",
            status_code=503,
        )

    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    csrf_token = str(form.get("csrf_token") or "")
    return_to = safe_return_path(str(form.get("next") or "/"))

    if len(username) > 256 or len(password) > 4096 or len(csrf_token) > 256:
        return _issue_login_page(
            request,
            return_to=return_to,
            error="Invalid sign-in request.",
            status_code=400,
        )

    browser_nonce = str(request.cookies.get(login_csrf_cookie_name(request), "") or "")
    if not login_csrf_store.consume(browser_nonce, csrf_token):
        return _issue_login_page(
            request,
            return_to=return_to,
            error="The sign-in form expired. Try again.",
            status_code=403,
        )

    if not await verify_local_credentials(
        request,
        username,
        password,
        settings=cfg,
    ):
        return _issue_login_page(
            request,
            return_to=return_to,
            error="Invalid username or password.",
            status_code=401,
        )

    old_token = session_cookie_token(request)
    if old_token:
        session_store.revoke(old_token)

    configured_username = str(getattr(cfg, "auth_username", "") or "").strip()
    lifetime = _session_lifetime_seconds(cfg)
    token, _record = session_store.create(
        Principal.password_session(configured_username),
        lifetime_seconds=lifetime,
        credential_version=password_credential_version(getattr(cfg, "auth_password_hash", "")),
    )
    response = RedirectResponse(url=return_to, status_code=303)
    set_session_cookie(response, request, token, max_age=lifetime)
    clear_login_csrf_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/oidc/start")
async def oidc_start(request: Request, next: str = "/"):
    cfg = get_settings()
    return_to = safe_return_path(next)
    if not oidc_auth_enabled(cfg):
        return _issue_login_page(
            request,
            return_to=return_to,
            error="OpenID Connect authentication is disabled.",
            status_code=404,
        )
    try:
        authorization_url, correlation = await begin_oidc_login(cfg, return_to=return_to)
    except OidcError:
        return _issue_login_page(
            request,
            return_to=return_to,
            error="OpenID Connect is currently unavailable or misconfigured.",
            status_code=503,
        )
    response = RedirectResponse(url=authorization_url, status_code=303)
    _set_oidc_correlation_cookie(response, correlation)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/oidc/callback")
async def oidc_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
):
    correlation = str(request.cookies.get(OIDC_CORRELATION_COOKIE, "") or "")
    if error:
        oidc_transaction_store.consume(state, correlation)
        response = _issue_login_page(
            request,
            return_to="/",
            error="OpenID Connect sign-in was not completed.",
            status_code=401,
        )
        _clear_oidc_correlation_cookie(response)
        return response

    try:
        principal, return_to = await complete_oidc_login(
            state=state,
            code=code,
            correlation=correlation,
        )
    except OidcError:
        response = _issue_login_page(
            request,
            return_to="/",
            error="OpenID Connect sign-in could not be validated or authorized.",
            status_code=401,
        )
        _clear_oidc_correlation_cookie(response)
        return response

    old_token = session_cookie_token(request)
    if old_token:
        session_store.revoke(old_token)
    cfg = get_settings()
    lifetime = _session_lifetime_seconds(cfg)
    token, _record = session_store.create(
        principal,
        lifetime_seconds=lifetime,
    )
    response = RedirectResponse(url=safe_return_path(return_to), status_code=303)
    set_session_cookie(
        response,
        request,
        token,
        max_age=lifetime,
        force_secure=True,
    )
    clear_login_csrf_cookie(response, request)
    _clear_oidc_correlation_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/auth/session")
async def auth_session_status(request: Request):
    principal = getattr(request.state, "principal", Principal.anonymous())
    session_token = str(getattr(request.state, "auth_session_token", "") or "")
    record = session_store.resolve(session_token) if session_token else None
    return {
        "authenticated": bool(principal.authenticated),
        "mechanism": principal.mechanism.value if principal.mechanism else None,
        "subject": principal.subject,
        "display_name": principal.display_name,
        "csrf_token": session_store.csrf_token(session_token) if record is not None else "",
        "session_expires_in_seconds": (
            max(0, int(record.expires_at - time.monotonic())) if record is not None else None
        ),
    }


@router.post("/api/auth/logout")
async def logout(request: Request):
    principal = getattr(request.state, "principal", Principal.anonymous())
    if principal.mechanism not in {AuthMechanism.PASSWORD_SESSION, AuthMechanism.OIDC_SESSION}:
        return JSONResponse(
            content={"detail": "No browser application session"},
            status_code=400,
        )

    session_token = str(getattr(request.state, "auth_session_token", "") or "")
    if session_token:
        session_store.revoke(session_token)
    response = JSONResponse(content={"ok": True})
    clear_session_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
    return response
