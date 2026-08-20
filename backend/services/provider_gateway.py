"""Provider boundary. V1 ships an AllDebrid implementation through the legacy materialization engine."""
from __future__ import annotations


class ProviderGateway:
    def __init__(self, engine):
        self.engine = engine

    async def sync_status(self):
        return await self.engine.sync_alldebrid_status()

    async def reconcile_inventory(self):
        return await self.engine.reconcile_provider_inventory()

    async def import_existing(self):
        return await self.engine.import_existing_magnets()

    async def add_magnet(self, magnet: str, source: str = "manual"):
        return await self.engine.add_magnet_direct(magnet, source=source)

    async def add_torrent_file(self, *args, **kwargs):
        return await self.engine.add_torrent_file_direct(*args, **kwargs)

    async def test(self):
        cfg = self.engine.ad()
        return await cfg.get_user()
