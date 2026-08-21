from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class AuthMechanism(StrEnum):
    """Authentication mechanism that admitted the request."""

    PASSWORD_SESSION = "password_session"
    OIDC_SESSION = "oidc_session"
    HTTP_BASIC = "http_basic"
    API_TOKEN = "api_token"


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity attached to an admitted request at the authentication boundary."""

    authenticated: bool = False
    mechanism: AuthMechanism | None = None
    subject: str = ""
    display_name: str = ""
    claims: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "Principal":
        return cls()

    @classmethod
    def password_session(cls, username: str) -> "Principal":
        username = str(username or "")
        return cls(
            authenticated=True,
            mechanism=AuthMechanism.PASSWORD_SESSION,
            subject=username,
            display_name=username,
        )

    @classmethod
    def oidc_session(
        cls,
        subject: str,
        *,
        display_name: str = "",
        claims: Mapping[str, Any] | None = None,
    ) -> "Principal":
        return cls(
            authenticated=True,
            mechanism=AuthMechanism.OIDC_SESSION,
            subject=str(subject or ""),
            display_name=str(display_name or subject or ""),
            claims=dict(claims or {}),
        )

    @classmethod
    def http_basic(cls, username: str) -> "Principal":
        username = str(username or "")
        return cls(
            authenticated=True,
            mechanism=AuthMechanism.HTTP_BASIC,
            subject=username,
            display_name=username,
        )
