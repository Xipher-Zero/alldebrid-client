from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import OrderedDict
from dataclasses import dataclass

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


_PASSWORD_HASHER = PasswordHasher()
# A process-local, valid Argon2id verifier used only to equalize work when the
# supplied username is wrong. The source value is random and never persisted.
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash(os.urandom(32).hex())


def hash_password(password: str) -> str:
    value = str(password or "")
    if not value:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASHER.hash(value)


def verify_password(password_hash: str, password: str) -> bool:
    encoded = str(password_hash or "").strip()
    if not encoded:
        return False
    try:
        return bool(_PASSWORD_HASHER.verify(encoded, str(password or "")))
    except (InvalidHashError, VerificationError):
        return False


def verify_password_candidate(
    password_hash: str,
    password: str,
    *,
    use_configured_hash: bool,
) -> bool:
    """Verify a password while doing Argon2 work even for a wrong username."""
    target = str(password_hash or "").strip() if use_configured_hash else _DUMMY_PASSWORD_HASH
    verified = verify_password(target, password)
    return bool(use_configured_hash and verified)


def is_usable_password_hash(password_hash: str) -> bool:
    """True only for a parseable Argon2id verifier."""
    encoded = str(password_hash or "").strip()
    if not encoded:
        return False
    try:
        return extract_parameters(encoded).type is Type.ID
    except InvalidHashError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    encoded = str(password_hash or "").strip()
    if not encoded:
        return False
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(encoded))
    except InvalidHashError:
        return False


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float


class BasicVerificationCache:
    """Bounded, short-lived cache of successful HTTP Basic verifications.

    Cache keys are HMAC-SHA256 fingerprints under a process-random key. Raw
    credentials are never retained. The configured password hash participates in
    the fingerprint so a credential replacement cannot reuse an old cache entry.
    """

    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 30.0):
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._key = os.urandom(32)
        self._entries: OrderedDict[bytes, _CacheEntry] = OrderedDict()

    def _fingerprint(self, username: str, password: str, password_hash: str) -> bytes:
        message = b"\0".join(
            (
                str(username or "").encode("utf-8", errors="surrogatepass"),
                str(password or "").encode("utf-8", errors="surrogatepass"),
                str(password_hash or "").encode("utf-8", errors="surrogatepass"),
            )
        )
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def contains(self, username: str, password: str, password_hash: str) -> bool:
        now = time.monotonic()
        fingerprint = self._fingerprint(username, password, password_hash)
        entry = self._entries.get(fingerprint)
        if entry is None:
            return False
        if entry.expires_at <= now:
            self._entries.pop(fingerprint, None)
            return False
        self._entries.move_to_end(fingerprint)
        return True

    def remember(self, username: str, password: str, password_hash: str) -> None:
        now = time.monotonic()
        fingerprint = self._fingerprint(username, password, password_hash)
        self._entries[fingerprint] = _CacheEntry(expires_at=now + self.ttl_seconds)
        self._entries.move_to_end(fingerprint)
        self._prune(now)

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    @property
    def size(self) -> int:
        self._prune(time.monotonic())
        return len(self._entries)


basic_verification_cache = BasicVerificationCache()
