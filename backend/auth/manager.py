from __future__ import annotations

import asyncio
import secrets

from fastapi import Request

from auth.passwords import basic_verification_cache, verify_password_candidate_async
from auth.policy import password_auth_ready
from auth.throttle import password_failure_throttle
from core.config import get_settings


def peer_key(request: Request) -> str:
    """Use the transport peer, not untrusted forwarding headers, for throttling."""
    client = request.client
    return str(client.host if client else "unknown")


async def verify_local_credentials(
    request: Request,
    provided_user: str,
    provided_password: str,
    *,
    allow_basic_success_cache: bool = False,
) -> bool:
    """Verify the single local credential with shared throttling/timing behavior."""
    cfg = get_settings()
    if not password_auth_ready(cfg):
        return False

    peer = peer_key(request)
    delay = password_failure_throttle.delay_for(peer)
    if delay:
        await asyncio.sleep(delay)

    username = str(getattr(cfg, "auth_username", "") or "").strip()
    password_hash = str(getattr(cfg, "auth_password_hash", "") or "").strip()
    candidate_user = str(provided_user or "")
    candidate_password = str(provided_password or "")
    user_ok = secrets.compare_digest(candidate_user.encode(), username.encode())

    verified = False
    if user_ok and allow_basic_success_cache:
        verified = basic_verification_cache.contains(
            username,
            candidate_password,
            password_hash,
        )

    if not verified:
        verified = await verify_password_candidate_async(
            password_hash,
            candidate_password,
            use_configured_hash=user_ok,
        )
        if verified and allow_basic_success_cache:
            basic_verification_cache.remember(
                username,
                candidate_password,
                password_hash,
            )

    if verified:
        password_failure_throttle.record_success(peer)
        return True

    password_failure_throttle.record_failure(peer)
    return False
