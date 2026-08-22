from __future__ import annotations

from urllib.parse import urlparse, urlsplit

from auth.passwords import is_usable_password_hash


MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLIC_PATHS = frozenset(
    {
        "/api/health",
        "/api/version",
        "/api/avatar",
        "/api/auth/status",
        "/login",
        "/auth/oidc/start",
        "/auth/oidc/callback",
    }
)


def is_public_path(path: str) -> bool:
    return str(path or "") in PUBLIC_PATHS


def password_auth_enabled(settings) -> bool:
    return bool(getattr(settings, "auth_password_enabled", False))


def password_auth_ready(settings) -> bool:
    if not password_auth_enabled(settings):
        return False
    username = str(getattr(settings, "auth_username", "") or "").strip()
    password_hash = str(getattr(settings, "auth_password_hash", "") or "").strip()
    return bool(username and is_usable_password_hash(password_hash))


def password_auth_configured(settings) -> bool:
    """Compatibility name for callers asking whether password auth is usable."""
    return password_auth_ready(settings)


def oidc_auth_enabled(settings) -> bool:
    return bool(getattr(settings, "auth_oidc_enabled", False))


def interactive_auth_enabled(settings) -> bool:
    return password_auth_enabled(settings) or oidc_auth_enabled(settings)


def safe_return_path(value: str, *, default: str = "/") -> str:
    """Accept only a local absolute-path reference; never create an open redirect."""
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2048:
        return default
    # Reject every network-path reference before URL parsing. Python's urlsplit
    # normalizes some 3+ slash inputs in ways browsers subsequently reinterpret.
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    if any(ch in candidate for ch in ("\\", "\r", "\n", "\x00")):
        return default
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return default
    if parsed.scheme or parsed.netloc:
        return default
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default
    if parsed.path in {"/login", "/auth/oidc/start", "/auth/oidc/callback"}:
        return default
    return candidate


def normalized_origin(value: str) -> tuple[str, str, int] | None:
    """Return a canonical HTTP(S) origin tuple or ``None`` when malformed.

    Scheme is part of the browser origin. Treating ``http://host`` and
    ``https://host`` as equivalent would weaken the cross-site mutation boundary
    on deployments that expose both transports or have an HTTP downgrade path.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, parsed.hostname.casefold(), int(port)


def normalized_origin_host(origin: str) -> str:
    """Compatibility helper returning the case-folded origin authority."""
    try:
        return (urlparse(str(origin or "").strip()).netloc or "").casefold()
    except ValueError:
        return ""
