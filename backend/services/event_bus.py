"""Small process-local application event bridge.

Service/domain code publishes semantic events here. The HTTP/SSE adapter may
bind a delivery callback, but lower layers never import the API package.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Publisher = Callable[[str, dict[str, Any]], Awaitable[None]]
_publisher: Publisher | None = None


def bind_publisher(publisher: Publisher | None) -> None:
    global _publisher
    _publisher = publisher


async def publish(event_type: str, payload: dict[str, Any]) -> None:
    publisher = _publisher
    if publisher is not None:
        await publisher(str(event_type), dict(payload))
