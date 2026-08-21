from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from auth.oidc_version import oidc_configuration_version_from_config


@dataclass(frozen=True, slots=True)
class PendingOidcConfiguration:
    settings: Any
    configuration_version: str
    created_at: float
    expires_at: float


class PendingOidcConfigurationStore:
    """Bounded ephemeral proposed OIDC settings awaiting a full OIDC proof."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        max_entries: int = 32,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._entries: OrderedDict[bytes, PendingOidcConfiguration] = OrderedDict()

    def _fingerprint(self, state: str) -> bytes:
        return hmac.new(
            self._key,
            str(state or "").encode("utf-8", errors="surrogatepass"),
            hashlib.sha256,
        ).digest()

    def stage(self, state: str, settings: Any, *, configuration_version: str) -> None:
        now = self._clock()
        self.cleanup()
        key = self._fingerprint(state)
        self._entries[key] = PendingOidcConfiguration(
            settings=settings,
            configuration_version=str(configuration_version),
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def consume_verified(self, state: str, transaction_config: Any) -> PendingOidcConfiguration | None:
        if not state:
            return None
        item = self._entries.pop(self._fingerprint(state), None)
        if item is None:
            return None
        if item.expires_at <= self._clock():
            return None
        actual = oidc_configuration_version_from_config(transaction_config)
        if not secrets.compare_digest(item.configuration_version, actual):
            return None
        return item

    def discard(self, state: str) -> bool:
        if not state:
            return False
        return self._entries.pop(self._fingerprint(state), None) is not None

    def cleanup(self) -> int:
        now = self._clock()
        expired = [key for key, item in self._entries.items() if item.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        self.cleanup()
        return len(self._entries)


def commit_verified_pending_oidc(state: str, transaction_config: Any) -> bool:
    """Commit a staged config only after the matching full OIDC login succeeds."""
    item = pending_oidc_store.consume_verified(state, transaction_config)
    if item is None:
        return False

    from auth.models import AuthMechanism
    from auth.sessions import session_store
    from core.config import apply_settings, save_settings

    # Persist first; if persistence fails, the current in-memory configuration
    # remains authoritative and no successful pending transition is reported.
    save_settings(item.settings)
    apply_settings(item.settings)
    # Critical OIDC policy/config changed. Existing OIDC sessions were proven
    # under the previous policy and must not remain usable indefinitely.
    session_store.revoke_mechanism(AuthMechanism.OIDC_SESSION)
    return True


pending_oidc_store = PendingOidcConfigurationStore()
