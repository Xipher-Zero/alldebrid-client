"""Capability-oriented aria2 boundary."""
from __future__ import annotations

from services.aria2_runtime import is_builtin_mode


class Aria2Gateway:
    def __init__(self, engine):
        self.engine = engine

    async def raw_snapshot(self):
        return await self.engine._engine_aria2_get_all()

    async def get_global_stat(self):
        return await self.engine.aria2().get_global_stat()

    async def get_active(self):
        return await self.engine.aria2().get_active()

    async def get_all(self, *args, **kwargs):
        return await self.engine.aria2().get_all(*args, **kwargs)

    def rpc_metrics(self):
        return self.engine.aria2().rpc_metrics()

    async def get_global_options(self):
        return await self.engine.aria2().get_global_options()

    async def change_global_options(self, options):
        if not is_builtin_mode():
            raise PermissionError("Global aria2 options are read-only in external mode")
        return await self.engine.aria2().change_global_options(options)

    async def status(self, gid: str):
        return await self.engine.aria2().tell_status(gid)

    async def pause(self, gid: str):
        return await self.engine.aria2().pause(gid)

    async def resume(self, gid: str):
        return await self.engine.aria2().resume(gid)

    async def remove_owned(self, gid: str):
        return await self.engine._remove_owned_aria2_gid(gid)

    @property
    def exclusive(self) -> bool:
        return is_builtin_mode()
