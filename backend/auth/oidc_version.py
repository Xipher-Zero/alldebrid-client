from __future__ import annotations

import hashlib
import json
from typing import Any


def oidc_configuration_version_from_config(config: Any) -> str:
    """Fingerprint security-critical OIDC configuration without retaining secrets."""
    payload = {
        "issuer": str(getattr(config, "issuer", "") or ""),
        "client_id": str(getattr(config, "client_id", "") or ""),
        "client_secret": str(getattr(config, "client_secret", "") or ""),
        "scopes": list(getattr(config, "scopes", ()) or ()),
        "callback_url": str(getattr(config, "callback_url", "") or ""),
        "allow_all": bool(getattr(config, "allow_all", False)),
        "allowed_subjects": sorted(str(item) for item in (getattr(config, "allowed_subjects", ()) or ())),
        "allowed_emails": sorted(str(item).casefold() for item in (getattr(config, "allowed_emails", ()) or ())),
        "allowed_groups": sorted(str(item) for item in (getattr(config, "allowed_groups", ()) or ())),
        "group_claim": str(getattr(config, "group_claim", "") or ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def oidc_configuration_version(settings: Any) -> str:
    """Return the effective critical OIDC configuration fingerprint, or empty if unusable."""
    from auth.oidc import OidcConfigurationError, oidc_configuration

    try:
        config = oidc_configuration(settings)
    except OidcConfigurationError:
        return ""
    return oidc_configuration_version_from_config(config)
