from __future__ import annotations

import base64
import secrets
from collections.abc import Awaitable, Callable, Iterable

from fastapi import Request, Response

from auth.models import Principal
from auth.policy import (
    MUTATING_HTTP_METHODS,
    configured_origin_hosts,
    is_public_path,
    normalized_origin_host,
    password_auth_configured,
)
from core.branding import APP_SHORT_NAME
from core.config import get_settings


CallNext = Callable[[Request], Awaitable[Response]]


def _attach_principal(request: Request, principal: Principal) -> None:
    request.state.principal = principal


def _decode_basic_credentials(header: str) -> tuple[str, str] | None:
    if not str(header or "").startswith("Basic "):
        return None
    token = str(header)[6:].strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


async def enforce_general_web_security(
    request: Request,
    call_next: CallNext,
    *,
    allowed_origins: Iterable[str] = (),
) -> Response:
    """Reject explicit cross-site browser mutations independently of authentication.

    Machine clients normally send neither Origin nor Fetch Metadata headers and
    therefore continue to work in open/no-auth deployments.
    """
    if request.method.upper() not in MUTATING_HTTP_METHODS:
        return await call_next(request)

    fetch_site = str(request.headers.get("Sec-Fetch-Site", "") or "").strip().casefold()
    if fetch_site == "cross-site":
        return Response(content="Forbidden request context", status_code=403)

    origin = str(request.headers.get("Origin", "") or "").strip()
    if not origin:
        return await call_next(request)

    origin_host = normalized_origin_host(origin)
    request_host = str(request.headers.get("Host", "") or "").strip().casefold()
    configured = configured_origin_hosts(allowed_origins)
    if not origin_host or (origin_host != request_host and origin_host not in configured):
        return Response(content="Forbidden origin", status_code=403)

    return await call_next(request)


async def enforce_legacy_basic_auth(request: Request, call_next: CallNext) -> Response:
    """Phase-1 adapter for inherited Basic auth using the common Principal model.

    Password hashing, application sessions and explicit auth enable state replace
    this legacy verifier in later phases. Keeping it isolated here lets phase 1
    preserve current behavior while removing auth responsibility from main.py.
    """
    _attach_principal(request, Principal.anonymous())
    cfg = get_settings()
    if not password_auth_configured(cfg):
        return await call_next(request)

    if is_public_path(request.url.path):
        return await call_next(request)

    credentials = _decode_basic_credentials(request.headers.get("Authorization", ""))
    if credentials is not None:
        provided_user, provided_pass = credentials
        username = str(getattr(cfg, "auth_username", "") or "").strip()
        password = str(getattr(cfg, "auth_password", "") or "").strip()
        user_ok = secrets.compare_digest(provided_user.encode(), username.encode())
        pass_ok = secrets.compare_digest(provided_pass.encode(), password.encode())
        if user_ok and pass_ok:
            _attach_principal(request, Principal.http_basic(username))
            return await call_next(request)

    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{APP_SHORT_NAME}"'},
    )
