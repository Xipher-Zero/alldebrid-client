from __future__ import annotations

import asyncio
import base64
import binascii
import secrets
from collections.abc import Awaitable, Callable, Iterable

from fastapi import Request, Response

from auth.models import Principal
from auth.passwords import basic_verification_cache, verify_password
from auth.policy import (
    MUTATING_HTTP_METHODS,
    is_public_path,
    normalized_origin_host,
    password_auth_enabled,
    password_auth_ready,
)
from auth.throttle import password_failure_throttle
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
    except (binascii.Error, ValueError, UnicodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _peer_key(request: Request) -> str:
    client = request.client
    return str(client.host if client else "unknown")


def _unauthorized() -> Response:
    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{APP_SHORT_NAME}"'},
    )


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


async def enforce_password_http_auth(request: Request, call_next: CallNext) -> Response:
    """Admit open requests or authenticate explicit HTTP Basic credentials.

    Browser form sessions replace the native Basic challenge in phase 3. Phase 2
    keeps the existing interactive behavior while switching persistence and
    verification to the final Argon2id credential model.
    """
    _attach_principal(request, Principal.anonymous())
    cfg = get_settings()

    if not password_auth_enabled(cfg):
        return await call_next(request)

    if is_public_path(request.url.path):
        return await call_next(request)

    if not password_auth_ready(cfg):
        return Response(content="Password authentication unavailable", status_code=503)

    auth_header = str(request.headers.get("Authorization", "") or "")
    if not auth_header.startswith("Basic "):
        return _unauthorized()

    peer = _peer_key(request)
    delay = password_failure_throttle.delay_for(peer)
    if delay:
        await asyncio.sleep(delay)

    credentials = _decode_basic_credentials(auth_header)
    if credentials is None:
        password_failure_throttle.record_failure(peer)
        return _unauthorized()

    provided_user, provided_pass = credentials
    username = str(getattr(cfg, "auth_username", "") or "").strip()
    password_hash = str(getattr(cfg, "auth_password_hash", "") or "").strip()
    user_ok = secrets.compare_digest(provided_user.encode(), username.encode())

    verified = False
    if user_ok:
        verified = basic_verification_cache.contains(username, provided_pass, password_hash)
        if not verified:
            verified = verify_password(password_hash, provided_pass)
            if verified:
                basic_verification_cache.remember(username, provided_pass, password_hash)

    if verified:
        password_failure_throttle.record_success(peer)
        _attach_principal(request, Principal.http_basic(username))
        return await call_next(request)

    password_failure_throttle.record_failure(peer)
    return _unauthorized()
