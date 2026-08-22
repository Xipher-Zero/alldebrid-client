from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from core.config import CONFIG_PATH
from core.secure_files import atomic_write_json


API_TOKEN_PREFIX = "dp_"
API_TOKEN_RANDOM_BYTES = 32


@dataclass(frozen=True, slots=True)
class ApiTokenState:
    enabled: bool = False
    verifier: str = ""

    @property
    def configured(self) -> bool:
        value = str(self.verifier or "").strip().casefold()
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


class ApiTokenStore:
    """Persistent machine credential store that never retains the raw token."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._state = self._load()

    def _load(self) -> ApiTokenState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ApiTokenState()
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ApiTokenState()
        if not isinstance(data, dict):
            return ApiTokenState()
        state = ApiTokenState(
            enabled=bool(data.get("enabled", False)),
            verifier=str(data.get("verifier") or "").strip().casefold(),
        )
        # Malformed persisted credentials fail closed rather than becoming a
        # partially enabled authentication path.
        if state.enabled and not state.configured:
            return ApiTokenState(enabled=False, verifier=state.verifier)
        return state

    def _persist(self, state: ApiTokenState) -> None:
        atomic_write_json(
            self.path,
            {"enabled": bool(state.enabled), "verifier": str(state.verifier)},
            separators=(",", ":"),
        )
        self._state = state

    @staticmethod
    def verifier_for(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8", errors="surrogatepass")).hexdigest()

    @property
    def enabled(self) -> bool:
        return bool(self._state.enabled)

    @property
    def configured(self) -> bool:
        return self._state.configured

    def status(self) -> dict[str, bool]:
        return {"enabled": self.enabled, "configured": self.configured}

    def generate(self) -> str:
        raw = API_TOKEN_PREFIX + secrets.token_urlsafe(API_TOKEN_RANDOM_BYTES)
        state = ApiTokenState(enabled=True, verifier=self.verifier_for(raw))
        self._persist(state)
        return raw

    def set_enabled(self, enabled: bool) -> None:
        desired = bool(enabled)
        if desired and not self.configured:
            raise ValueError("API token has not been generated")
        self._persist(ApiTokenState(enabled=desired, verifier=self._state.verifier))

    def clear(self) -> None:
        # Remove the verifier from disk entirely. Missing state means disabled.
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._state = ApiTokenState()

    def verify(self, candidate: str) -> bool:
        if not self.enabled or not self.configured:
            return False
        candidate_verifier = self.verifier_for(candidate)
        return secrets.compare_digest(candidate_verifier, self._state.verifier)


api_token_store = ApiTokenStore(CONFIG_PATH.parent / "api-token.json")
