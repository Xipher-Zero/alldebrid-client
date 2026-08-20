"""Provider boundary for the V1 AllDebrid implementation.

Provider-specific network/materialization behavior still lives in the inherited
engine, but every application-visible provider operation is enumerated here so
callers cannot bypass the provider boundary through a transparent fallback.
"""
from __future__ import annotations


class ProviderGateway:
    def __init__(self, engine):
        self.engine = engine

    def client(self):
        """Return the configured AllDebrid client for provider-only operations."""
        return self.engine.ad()

    async def sync_status(self):
        return await self.engine.sync_alldebrid_status()

    async def reconcile_inventory(self):
        return await self.engine.reconcile_provider_inventory()

    async def import_existing(self):
        return await self.engine.import_existing_magnets()

    async def full_sync(self):
        return await self.engine.full_alldebrid_sync()

    async def add_magnet(self, magnet: str, source: str = "manual"):
        return await self.engine.add_magnet_direct(magnet, source=source)

    async def add_torrent_file(self, *args, **kwargs):
        return await self.engine.add_torrent_file_direct(*args, **kwargs)

    async def add_direct_links(self, links):
        return await self.engine.add_direct_links(links)

    async def retry_direct_link_collection(self, transfer_id: int):
        return await self.engine.retry_direct_link_collection(int(transfer_id))

    async def cleanup_no_peer_errors(self):
        return await self.engine.cleanup_no_peer_errors()

    async def cleanup_orphans(self):
        return await self.engine.cleanup_alldebrid_orphans()

    async def cleanup_stuck(self):
        return await self.engine.cleanup_stuck_downloads()

    async def test(self):
        return await self.client().get_user()
