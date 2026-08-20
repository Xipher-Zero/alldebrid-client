"""Explicit extraction boundary."""
from __future__ import annotations

from services.extractor import get_extractor


class ExtractionService:
    async def extract_archive(self, *args, **kwargs):
        return await get_extractor().extract_archive(*args, **kwargs)
