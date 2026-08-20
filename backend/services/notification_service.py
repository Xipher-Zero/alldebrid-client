"""Application notification boundary for DebridPulse."""
from __future__ import annotations

from core.config import get_settings
from services.notifications import NotificationService as DiscordNotificationClient


class NotificationService:
    def client(self) -> DiscordNotificationClient:
        """Return a concrete client; empty URLs intentionally no-op in the client."""
        cfg = get_settings()
        return DiscordNotificationClient(
            webhook_url=str(getattr(cfg, "discord_webhook_url", "") or ""),
            added_webhook_url=str(getattr(cfg, "discord_webhook_added", "") or ""),
        )
