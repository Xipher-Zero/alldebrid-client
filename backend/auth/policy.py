from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse


MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLIC_PATHS = frozenset({"/api/health", "/api/version", "/api/avatar"})


def is_public_path(path: str) -> bool:
    return str(path or "") in PUBLIC_PATHS


def password_auth_configured(settings) -> bool:
    """Legacy phase-1 compatibility check; replaced by explicit enable state in phase 2."""
    username = str(getattr(settings, "auth_username", "") or "").strip()
    password = str(getattr(settings, "auth_password", "") or "").strip()
    return bool(username and password)


def normalized_origin_host(origin: str) -> str:
    """Return a case-folded origin authority, or an empty string if malformed."""
    try:
        return (urlparse(str(origin or "").strip()).netloc or "").casefold()
    except ValueError:
        return ""


def configured_origin_hosts(origins: Iterable[str]) -> frozenset[str]:
    return frozenset(
        host
        for host in (normalized_origin_host(origin) for origin in origins)
        if host
    )
