from __future__ import annotations

import base64
import binascii
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from auth.manager import verify_local_credentials
from auth.models import AuthMechanism, Principal
from auth.passwords import password_credential_version
from auth.policy import (
    MUTATING_HTTP_METHODS,
    is_public_path,
    normalized_origin_host,
    password_auth_enabled,
    password_auth_ready,
    safe_return_path,
)
from auth.sessions import CSRF_HEADER, session_cookie_token, session_store
from core.branding import APP_SHORT_NAME
from core.config import get_settings


CallNext = Callable[[Request], Awaitable[Response]]


def _attach_principal(request: Request, principal: Principal) -> None:
    request.state.principal = principal


def _attach_session(request: Request, token: str) -> None:
    request.state.auth_session_token = token


def _has_basic_scheme(header: str) -> bool:
    scheme, separator, _token = str(header or "").strip().partition(" ")
    return bool(separator and scheme.casefold() == "basic")


def _decode_basic_credentials(header: str) -> tuple[str, str] | None:
    scheme, separator, token = str(header or "").strip().partition(" ")
    if not separator or scheme.casefold() != "basic":
        return None
    token = token.strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError, UnicodeError):
        return None
    username, credential_separator, password = decoded.partition(":")
    if not credential_separator:
        return None
    return username, password


def _unauthorized(*, basic_challenge: bool = False) -> Response:
    headers = {"WWW-Authenticate": f'Basic realm="{APP_SHORT_NAME}"'} if basic_challenge else None
    return JSONResponse(content={"detail": "Unauthorized"}, status_code=401, headers=headers)


def _is_browser_navigation(request: Request) -> bool:
    if request.method.upper() != "GET" or request.url.path.startswith("/api/"):
        return False
    accept = str(request.headers.get("Accept", "") or "").casefold()
    return "text/html" in accept


def _browser_login_redirect(request: Request) -> Response:
    target = request.url.path or "/"
    if request.url.query:
        target += "?" + request.url.query
    target = safe_return_path(target)
    return RedirectResponse(url=f"/login?next={quote(target, safe='')}", status_code=303)


def _password_session_still_valid(record, cfg) -> bool:
    if record.principal.mechanism is not AuthMechanism.PASSWORD_SESSION:
        return True
    if not password_auth_ready(cfg):
        return False
    current_version = password_credential_version(getattr(cfg, "auth_password_hash", ""))
    return bool(current_version and record.credential_version == current_version)


async def enforce_general_web_security(
    request: Request,
    call_next: CallNext,
    *,
    allowed_origins: Iterable[str] = (),
) -> Response:
    """Reject explicit cross-site browser mutations independently of authentication.

    Machine clients normally send neither Origin nor Fetch Metadata headers and
    therefore continue to work in open/no-auth deployments. Explicitly allowed
    CORS origins retain their configured mutation behavior.
    """
    if request.method.upper() not in MUTATING_HTTP_METHODS:
        return await call_next(request)

    origin = str(request.headers.get("Origin", "") or "").strip()
    origin_host = normalized_origin_host(origin) if origin else ""
    request_host = str(request.headers.get("Host", "") or "").strip().casefold()
    configured_origins = {
        str(item or "").strip().rstrip("/")
        for item in allowed_origins
        if str(item or "").strip()
    }
    configured_cross_origin = bool(origin and origin.rstrip("/") in configured_origins)

    fetch_site = str(request.headers.get("Sec-Fetch-Site", "") or "").strip().casefold()
    if fetch_site == "cross-site" and not configured_cross_origin:
        return Response(content="Forbidden request context", status_code=403)

    if not origin:
        return await call_next(request)

    if not origin_host or (origin_host != request_host and not configured_cross_origin):
        return Response(content="Forbidden origin", status_code=403)

    return await call_next(request)


async def enforce_authentication(request: Request, call_next: CallNext) -> Response:
    """Outer authentication boundary for open, browser-session and Basic access."""
    _attach_principal(request, Principal.anonymous())
    cfg = get_settings()

    if is_public_path(request.url.path):
        return await call_next(request)

    session_token = session_cookie_token(request)
    if session_token:
        record = session_store.resolve(session_token)
        if record is not None and _password_session_still_valid(record, cfg):
            _attach_principal(request, record.principal)
            _attach_session(request, session_token)
            if request.method.upper() in MUTATING_HTTP_METHODS:
                csrf = str(request.headers.get(CSRF_HEADER, "") or "")
                if not session_store.verify_csrf(session_token, csrf):
                    return JSONResponse(
                        content={"detail": "CSRF validation failed"},
                        status_code=403,
                    )
            return await call_next(request)
        session_store.revoke(session_token)

    auth_header = str(request.headers.get("Authorization", "") or "")
    if _has_basic_scheme(auth_header):
        if not password_auth_enabled(cfg):
            return await call_next(request)
        if not password_auth_ready(cfg):
            return JSONResponse(
                content={"detail": "Password authentication unavailable"},
                status_code=503,
            )
        credentials = _decode_basic_credentials(auth_header)
        if credentials is None:
            # Malformed Basic still pays the bounded dummy Argon2/throttle cost.
            await verify_local_credentials(request, "", "", settings=cfg)
            return _unauthorized(basic_challenge=True)
        provided_user, provided_pass = credentials
        if await verify_local_credentials(
            request,
            provided_user,
            provided_pass,
            allow_basic_success_cache=True,
            settings=cfg,
        ):
            username = str(getattr(cfg, "auth_username", "") or "").strip()
            _attach_principal(request, Principal.http_basic(username))
            return await call_next(request)
        return _unauthorized(basic_challenge=True)

    if not password_auth_enabled(cfg):
        return await call_next(request)

    if not password_auth_ready(cfg):
        return JSONResponse(
            content={"detail": "Password authentication unavailable"},
            status_code=503,
        )

    if _is_browser_navigation(request):
        return _browser_login_redirect(request)

    return _unauthorized()


# Compatibility name for phase-2 tests/downstream imports while the manager API
# settles. All requests now use the application-session-aware implementation.
enforce_password_http_auth = enforce_authentication
