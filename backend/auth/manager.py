from __future__ import annotations

import asyncio
import secrets
import threading

from fastapi import Request

from auth.passwords import basic_verification_cache, password_credential_version, verify_password_candidate_async
from auth.policy import password_auth_ready
from auth.throttle import password_failure_throttle
from core.config import get_settings


class PasswordAuthenticationBusy(Exception):
    """Password verification admission is saturated; fail fast instead of queueing."""


class PasswordAttemptAdmission:
    """Bound expensive password attempts globally and per transport peer.

    Argon2 verification is intentionally expensive. The lower-level verifier
    limits simultaneous Argon2 workers, while this admission boundary also caps
    requests waiting through throttling or for a worker slot. Without it, a
    parallel unauthenticated burst could create an unbounded coroutine queue.
    """

    def __init__(self, *, max_pending: int = 16, max_per_peer: int = 4) -> None:
        self.max_pending = max(1, int(max_pending))
        self.max_per_peer = max(1, min(int(max_per_peer), self.max_pending))
        self._lock = threading.Lock()
        self._pending = 0
        self._peers: dict[str, int] = {}

    def acquire(self, peer: str) -> bool:
        key = str(peer or "unknown")
        with self._lock:
            peer_pending = self._peers.get(key, 0)
            if self._pending >= self.max_pending or peer_pending >= self.max_per_peer:
                return False
            self._pending += 1
            self._peers[key] = peer_pending + 1
            return True

    def release(self, peer: str) -> None:
        key = str(peer or "unknown")
        with self._lock:
            peer_pending = self._peers.get(key, 0)
            if peer_pending <= 0:
                return
            self._pending = max(0, self._pending - 1)
            if peer_pending == 1:
                self._peers.pop(key, None)
            else:
                self._peers[key] = peer_pending - 1

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending


password_attempt_admission = PasswordAttemptAdmission()


def peer_key(request: Request) -> str:
    """Use the transport peer, not untrusted forwarding headers, for throttling."""
    client = request.client
    return str(client.host if client else "unknown")


def password_authentication_snapshot_current(proven, current) -> bool:
    """Return whether a completed password proof still matches live auth state."""
    if not password_auth_ready(current):
        return False
    proven_username = str(getattr(proven, "auth_username", "") or "").strip()
    current_username = str(getattr(current, "auth_username", "") or "").strip()
    if not proven_username or proven_username != current_username:
        return False
    proven_version = password_credential_version(getattr(proven, "auth_password_hash", ""))
    current_version = password_credential_version(getattr(current, "auth_password_hash", ""))
    return bool(
        proven_version
        and current_version
        and secrets.compare_digest(proven_version, current_version)
    )


async def verify_local_credentials(
    request: Request,
    provided_user: str,
    provided_password: str,
    *,
    allow_basic_success_cache: bool = False,
    settings=None,
) -> bool:
    """Verify the single local credential with shared throttling/timing behavior."""
    cfg = settings if settings is not None else get_settings()
    if not password_auth_ready(cfg):
        return False

    peer = peer_key(request)
    if not password_attempt_admission.acquire(peer):
        raise PasswordAuthenticationBusy
    try:
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
    finally:
        password_attempt_admission.release(peer)
