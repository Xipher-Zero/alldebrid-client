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
    """Accept only local relative return destinations; never create an open redirect."""
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2048:
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


def normalized_origin_host(origin: str) -> str:
    """Return a case-folded origin authority, or an empty string if malformed."""
    try:
        return (urlparse(str(origin or "").strip()).netloc or "").casefold()
    except ValueError:
        return ""
