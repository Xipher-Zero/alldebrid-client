from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from api import auth_routes as interactive_routes
from auth.csrf import clear_login_csrf_cookie
from auth.oidc import (
    OIDC_CORRELATION_COOKIE,
    OIDC_TRANSACTION_TTL_SECONDS,
    OidcError,
    begin_oidc_login,
    complete_oidc_login,
    oidc_callback_url,
)
from auth.oidc_version import oidc_configuration_version
from auth.pending_oidc import commit_verified_pending_oidc, pending_oidc_store
from auth.policy import safe_return_path
from auth.sessions import session_cookie_token, session_store, set_session_cookie
from core.config import get_settings


router = APIRouter()


class OidcVerificationRequest(BaseModel):
    """Proposed OIDC settings staged only until a real login proves them."""

    auth_password_enabled: bool | None = None
    oidc_provider_name: str | None = None
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = Field(default=None, max_length=8192)
    clear_oidc_client_secret: bool = False
    oidc_scopes: list[str] | None = None
    oidc_allow_all: bool | None = None
    oidc_allowed_subjects: list[str] | None = None
    oidc_allowed_emails: list[str] | None = None
    oidc_allowed_groups: list[str] | None = None
    oidc_group_claim: str | None = None
    public_base_url: str | None = None
    return_to: str = "/settings"


def _build_proposed_settings(request: OidcVerificationRequest):
    current = get_settings()
    updates: dict[str, object] = {"auth_oidc_enabled": True}
    ordinary_fields = (
        "oidc_provider_name",
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_scopes",
        "oidc_allow_all",
        "oidc_allowed_subjects",
        "oidc_allowed_emails",
        "oidc_allowed_groups",
        "oidc_group_claim",
        "public_base_url",
    )
    for field in ordinary_fields:
        value = getattr(request, field)
        if value is not None:
            updates[field] = value

    if request.auth_password_enabled is not None:
        updates["auth_password_enabled"] = request.auth_password_enabled

    if request.clear_oidc_client_secret:
        updates["oidc_client_secret"] = ""
        updates["oidc_client_secret_clear"] = True
    elif request.oidc_client_secret is not None and request.oidc_client_secret.strip():
        updates["oidc_client_secret"] = request.oidc_client_secret
        updates["oidc_client_secret_clear"] = False
    else:
        updates["oidc_client_secret"] = str(getattr(current, "oidc_client_secret", "") or "")
        updates["oidc_client_secret_clear"] = False

    return current.model_copy(update=updates, deep=True)


def _set_pending_correlation_cookie(response: JSONResponse, correlation: str) -> None:
    response.set_cookie(
        key=OIDC_CORRELATION_COOKIE,
        value=str(correlation),
        max_age=OIDC_TRANSACTION_TTL_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_pending_correlation_cookie(response) -> None:
    response.delete_cookie(
        key=OIDC_CORRELATION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


@router.post("/api/auth/oidc/verify-config")
async def verify_pending_oidc_configuration(
    request: Request,
    proposed: OidcVerificationRequest,
):
    """Stage proposed OIDC settings and require a complete provider login.

    Nothing is persisted here. The current working configuration remains
    authoritative unless the matching OIDC callback authenticates and authorizes
    successfully under this exact proposed configuration.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None or not getattr(principal, "authenticated", False):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    candidate = _build_proposed_settings(proposed)
    return_to = safe_return_path(proposed.return_to, default="/settings")
    try:
        authorization_url, correlation = await begin_oidc_login(
            candidate,
            return_to=return_to,
        )
        version = oidc_configuration_version(candidate)
        if not version:
            raise ValueError("OIDC configuration is not usable")
        state_values = parse_qs(urlsplit(authorization_url).query).get("state", [])
        state = str(state_values[0]) if state_values else ""
        if not state:
            raise ValueError("OIDC authorization state is missing")
    except (OidcError, ValueError):
        return JSONResponse(
            {"detail": "Proposed OpenID Connect configuration could not start a verification login"},
            status_code=400,
        )

    pending_oidc_store.stage(
        state,
        candidate,
        configuration_version=version,
    )
    response = JSONResponse(
        {
            "ok": True,
            "authorization_url": authorization_url,
            "callback_url": oidc_callback_url(candidate),
            "pending": True,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    _set_pending_correlation_cookie(response, correlation)
    return response


@router.get("/auth/oidc/callback", include_in_schema=False)
async def pending_aware_oidc_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
):
    """Commit pending settings only after the matching complete OIDC flow passes."""
    if not pending_oidc_store.has(state):
        return await interactive_routes.oidc_callback(
            request,
            state=state,
            code=code,
            error=error,
        )

    correlation = str(request.cookies.get(OIDC_CORRELATION_COOKIE, "") or "")
    if error:
        pending_oidc_store.discard(state)
        return await interactive_routes.oidc_callback(
            request,
            state=state,
            code=code,
            error=error,
        )

    try:
        principal, return_to = await complete_oidc_login(
            state=state,
            code=code,
            correlation=correlation,
        )
    except OidcError:
        pending_oidc_store.discard(state)
        response = interactive_routes._issue_login_page(
            request,
            return_to="/settings",
            error="The proposed OpenID Connect configuration did not authenticate and authorize successfully. The current configuration was not changed.",
            status_code=401,
        )
        _clear_pending_correlation_cookie(response)
        return response

    try:
        committed = commit_verified_pending_oidc(state)
    except Exception:  # noqa: BLE001 - never expose persistence/config details at the callback boundary
        committed = False
    if not committed:
        response = interactive_routes._issue_login_page(
            request,
            return_to="/settings",
            error="OpenID Connect verification succeeded, but the pending configuration could not be committed. The current configuration remains authoritative.",
            status_code=500,
        )
        _clear_pending_correlation_cookie(response)
        return response

    # Commit happened before issuing the replacement application session, so
    # its credential version is derived from the newly authoritative OIDC config.
    old_token = session_cookie_token(request)
    if old_token:
        session_store.revoke(old_token)
    cfg = get_settings()
    lifetime = interactive_routes._session_lifetime_seconds(cfg)
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
    _clear_pending_correlation_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return response
