from __future__ import annotations

from urllib.parse import urlparse


MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLIC_PATHS = frozenset({"/api/health", "/api/version", "/api/avatar"})


def is_public_path(path: str) -> bool:
    return str(path or "") in PUBLIC_PATHS


def password_auth_enabled(settings) -> bool:
    return bool(getattr(settings, "auth_password_enabled", False))


def password_auth_ready(settings) -> bool:
    if not password_auth_enabled(settings):
        return False
    username = str(getattr(settings, "auth_username", "") or "").strip()
    password_hash = str(getattr(settings, "auth_password_hash", "") or "").strip()
    return bool(username and password_hash)


def password_auth_configured(settings) -> bool:
    """Compatibility name for callers asking whether password auth is usable."""
    return password_auth_ready(settings)


def normalized_origin_host(origin: str) -> str:
    """Return a case-folded origin authority, or an empty string if malformed."""
    try:
        return (urlparse(str(origin or "").strip()).netloc or "").casefold()
    except ValueError:
        return ""
