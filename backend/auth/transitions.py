from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from auth.models import AuthMechanism, Principal
from auth.policy import interactive_auth_enabled, oidc_auth_enabled, password_auth_enabled


CRITICAL_OIDC_FIELDS = frozenset(
    {
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_scopes",
        "public_base_url",
        "oidc_allow_all",
        "oidc_allowed_subjects",
        "oidc_allowed_emails",
        "oidc_allowed_groups",
        "oidc_group_claim",
    }
)


def _normalized_list(value: Any, *, casefold: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    items = []
    for raw in value:
        item = str(raw or "").strip()
        if not item:
            continue
        items.append(item.casefold() if casefold else item)
    return tuple(sorted(set(items)))


def _normalized_critical(field: str, value: Any) -> Any:
    if field in {"oidc_allow_all"}:
        return bool(value)
    if field == "oidc_scopes":
        scopes = list(_normalized_list(value))
        if "openid" not in scopes:
            scopes.append("openid")
        return tuple(sorted(set(scopes)))
    if field == "oidc_allowed_emails":
        return _normalized_list(value, casefold=True)
    if field in {"oidc_allowed_subjects", "oidc_allowed_groups"}:
        return _normalized_list(value)
    if field in {"oidc_issuer_url", "public_base_url"}:
        return str(value or "").strip().rstrip("/")
    return str(value or "").strip()


def oidc_critical_change(payload: Mapping[str, Any], current) -> bool:
    clears = {str(item) for item in payload.get("clear_secrets", []) if str(item)}
    if "oidc_client_secret" in clears:
        return True
    for field in CRITICAL_OIDC_FIELDS:
        if field not in payload:
            continue
        proposed = payload[field]
        # Blank secret input is the preserve-existing sentinel. Any nonblank
        # replacement is critical even when it happens to equal the old value.
        if field == "oidc_client_secret":
            if str(proposed or "").strip():
                return True
            continue
        if _normalized_critical(field, proposed) != _normalized_critical(
            field,
            getattr(current, field, None),
        ):
            return True
    return False


def _prospective_password_ready(payload: Mapping[str, Any], current) -> bool:
    username = str(payload.get("auth_username", getattr(current, "auth_username", "")) or "").strip()
    plaintext = str(payload.get("auth_password", "") or "")
    stored_hash = str(getattr(current, "auth_password_hash", "") or "").strip()
    clears = {str(item) for item in payload.get("clear_secrets", []) if str(item)}
    if "auth_password" in clears:
        stored_hash = ""
    return bool(username and (plaintext or stored_hash))


async def settings_transition_rejection(
    request: Request,
    principal: Principal,
    current,
) -> Response | None:
    """Reject authentication transitions that can strand the appliance owner.

    This is intentionally enforced at the authentication boundary so the broad
    inherited Settings endpoint cannot accidentally bypass the security state
    machine while its UI is being migrated in later phases.
    """
    if request.method.upper() != "PUT" or request.url.path != "/api/settings":
        return None

    try:
        raw = await request.body()
        payload = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None  # Let FastAPI return its normal request-validation error.
    if not isinstance(payload, dict):
        return None

    current_password = password_auth_enabled(current)
    current_oidc = oidc_auth_enabled(current)
    proposed_password = bool(payload.get("auth_password_enabled", current_password))
    proposed_oidc = bool(payload.get("auth_oidc_enabled", current_oidc))
    critical_oidc_change = oidc_critical_change(payload, current)

    # Explicitly opening an installation is supported, but only as an
    # authenticated and deliberately confirmed transition. Already-open
    # installations do not need to confirm that they remain open.
    if not proposed_password and not proposed_oidc and interactive_auth_enabled(current):
        if not principal.authenticated:
            return JSONResponse({"detail": "Authentication is required for open-mode transition"}, status_code=401)
        if payload.get("confirm_open_mode") is not True:
            return JSONResponse(
                {"detail": "Explicit confirmation is required to disable all interactive authentication"},
                status_code=409,
            )
        return None

    # Leaving OIDC as the sole interactive mechanism is permitted only when
    # this exact request is made from a real OIDC application session. A local
    # password session, HTTP Basic, discovery check, or configuration test is
    # insufficient proof of end-to-end OIDC access.
    disabling_password_to_oidc_only = current_password and not proposed_password and proposed_oidc
    if disabling_password_to_oidc_only:
        if critical_oidc_change:
            return JSONResponse(
                {"detail": "Verify the proposed OIDC configuration with a real sign-in before disabling Password"},
                status_code=409,
            )
        if principal.mechanism is not AuthMechanism.OIDC_SESSION:
            return JSONResponse(
                {"detail": "A current OIDC-authenticated session is required before disabling Password"},
                status_code=403,
            )

    # In OIDC-only mode the currently working config remains authoritative.
    # Critical changes must be staged and proven through the pending-config
    # flow. Enabling a known-usable local password in the same update restores
    # a fallback and therefore removes this lockout constraint.
    if not current_password and current_oidc and proposed_oidc and critical_oidc_change:
        fallback_ready = proposed_password and _prospective_password_ready(payload, current)
        if not fallback_ready:
            return JSONResponse(
                {"detail": "Critical OIDC changes require pending configuration verification while OIDC is the sole interactive mechanism"},
                status_code=409,
            )

    return None
