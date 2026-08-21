from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

from fastapi import Request, Response

from auth.models import Principal


HTTP_SESSION_COOKIE = "debridpulse-session"
HTTPS_SESSION_COOKIE = "__Host-debridpulse-session"
CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True, slots=True)
class SessionRecord:
    principal: Principal
    created_at: float
    expires_at: float
    credential_version: str = ""


class SessionStore:
    """Bounded, in-memory application sessions for the single-process appliance.

    Raw bearer session IDs are never retained server-side. The store is keyed by
    HMAC fingerprints under a process-random secret, so a process-memory dump of
    the mapping does not directly reveal reusable browser cookies.
    """

    def __init__(
        self,
        *,
        max_entries: int = 512,
        cleanup_interval_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.cleanup_interval_seconds = max(1.0, float(cleanup_interval_seconds))
        self._clock = clock
        self._session_key = secrets.token_bytes(32)
        self._csrf_key = secrets.token_bytes(32)
        self._entries: OrderedDict[bytes, SessionRecord] = OrderedDict()
        self._last_cleanup = self._clock()
        self._cleanup_task: asyncio.Task | None = None
        self._stop_cleanup: asyncio.Event | None = None

    def _fingerprint(self, token: str) -> bytes:
        return hmac.new(
            self._session_key,
            str(token or "").encode("utf-8", errors="surrogatepass"),
            hashlib.sha256,
        ).digest()

    def create(
        self,
        principal: Principal,
        *,
        lifetime_seconds: float,
        credential_version: str = "",
    ) -> tuple[str, SessionRecord]:
        now = self._clock()
        self.cleanup(force=True)
        lifetime = max(60.0, float(lifetime_seconds))
        while True:
            token = secrets.token_urlsafe(32)
            fingerprint = self._fingerprint(token)
            if fingerprint not in self._entries:
                break
        record = SessionRecord(
            principal=principal,
            created_at=now,
            expires_at=now + lifetime,
            credential_version=str(credential_version or ""),
        )
        self._entries[fingerprint] = record
        self._entries.move_to_end(fingerprint)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return token, record

    def resolve(self, token: str) -> SessionRecord | None:
        if not token:
            return None
        now = self._clock()
        self.cleanup()
        fingerprint = self._fingerprint(token)
        record = self._entries.get(fingerprint)
        if record is None:
            return None
        if record.expires_at <= now:
            self._entries.pop(fingerprint, None)
            return None
        return record

    def csrf_token(self, token: str) -> str:
        if not token:
            return ""
        return hmac.new(
            self._csrf_key,
            str(token).encode("utf-8", errors="surrogatepass"),
            hashlib.sha256,
        ).hexdigest()

    def verify_csrf(self, token: str, candidate: str) -> bool:
        if not token or not candidate:
            return False
        expected = self.csrf_token(token)
        return secrets.compare_digest(expected, str(candidate))

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        return self._entries.pop(self._fingerprint(token), None) is not None

    def clear(self) -> None:
        self._entries.clear()

    def cleanup(self, *, force: bool = False) -> int:
        now = self._clock()
        if not force and now - self._last_cleanup < self.cleanup_interval_seconds:
            return 0
        self._last_cleanup = now
        expired = [key for key, record in self._entries.items() if record.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    async def _cleanup_loop(self, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self.cleanup_interval_seconds,
                    )
                except TimeoutError:
                    self.cleanup(force=True)
        finally:
            self.cleanup(force=True)

    def start_cleanup(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            stop_event = asyncio.Event()
            self._stop_cleanup = stop_event
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(stop_event))

    async def stop_cleanup(self) -> None:
        task = self._cleanup_task
        stop_event = self._stop_cleanup
        if task is None:
            return
        if stop_event is not None:
            stop_event.set()
        try:
            await task
        finally:
            self._cleanup_task = None
            self._stop_cleanup = None

    @property
    def size(self) -> int:
        self.cleanup(force=True)
        return len(self._entries)


def request_is_secure(request: Request) -> bool:
    if str(request.url.scheme or "").casefold() == "https":
        return True
    forwarded = str(request.headers.get("X-Forwarded-Proto", "") or "")
    return forwarded.split(",", 1)[0].strip().casefold() == "https"


def session_cookie_name(request: Request) -> str:
    return HTTPS_SESSION_COOKIE if request_is_secure(request) else HTTP_SESSION_COOKIE


def session_cookie_token(request: Request) -> str:
    # Prefer the secure cookie regardless of proxy-internal request scheme. OIDC
    # always issues the __Host- cookie and callback/session admission must not
    # depend on trusting forwarded headers to locate it.
    return str(
        request.cookies.get(HTTPS_SESSION_COOKIE)
        or request.cookies.get(HTTP_SESSION_COOKIE)
        or ""
    )


def set_session_cookie(
    response: Response,
    request: Request,
    token: str,
    *,
    max_age: int,
    force_secure: bool = False,
) -> None:
    secure = bool(force_secure or request_is_secure(request))
    response.set_cookie(
        key=HTTPS_SESSION_COOKIE if secure else HTTP_SESSION_COOKIE,
        value=str(token),
        max_age=max(60, int(max_age)),
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    # Clear both names. A secure OIDC session may arrive through a proxy whose
    # internal hop is HTTP and must still be removable without scheme inference.
    response.delete_cookie(
        key=HTTPS_SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=HTTP_SESSION_COOKIE,
        path="/",
        secure=False,
        httponly=True,
        samesite="lax",
    )


session_store = SessionStore()
