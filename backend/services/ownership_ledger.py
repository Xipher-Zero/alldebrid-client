"""Authoritative DebridPulse ownership boundary for aria2 GIDs."""
from __future__ import annotations

from services.aria2_runtime import is_builtin_mode


class OwnershipLedger:
    def __init__(self, engine):
        self.engine = engine

    async def owned_gids(self) -> set[str]:
        if is_builtin_mode():
            snapshot = await self.engine._engine_aria2_get_all()
            return {str(item.gid) for item in snapshot}
        return await self.engine._aria2_owned_gids()

    async def filter_owned(self, downloads):
        if is_builtin_mode():
            return list(downloads)
        owned = await self.engine._aria2_owned_gids()
        return [item for item in downloads if str(item.gid) in owned]

    async def owns(self, gid: str) -> bool:
        if is_builtin_mode():
            return True
        return str(gid) in await self.engine._aria2_owned_gids()

    async def record(self, gid: str, *, download_file_id=None, transfer_id=None):
        await self.engine._record_aria2_owned_gid(
            gid,
            download_file_id=download_file_id,
            torrent_id=transfer_id,
        )
