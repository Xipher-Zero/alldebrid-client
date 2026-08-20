"""Application notification boundary for DebridPulse."""
from __future__ import annotations

from typing import Optional

from core.config import get_settings
from services.notifications import NotificationService as DiscordNotificationClient


class NotificationService:
    def client(self) -> Optional[DiscordNotificationClient]:
        cfg = get_settings()
        if not cfg.discord_webhook_url:
            return None
        return DiscordNotificationClient(cfg.discord_webhook_url)
