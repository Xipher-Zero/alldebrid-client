"""DebridPulse application service root.

FastAPI and scheduler code depend on this object. The inherited TorrentManager is
retained only as a provider/materialization engine while orchestration lives in
explicit services with normal dependency injection.
"""
from __future__ import annotations

from services.manager_v2 import manager as engine
from services.provider_gateway import ProviderGateway
from services.transfer_repository import TransferRepository
from services.aria2_gateway import Aria2Gateway
from services.ownership_ledger import OwnershipLedger
from services.transfer_state_machine import TransferStateMachine
from services.transfer_control_service import TransferControlService
from services.dispatch_coordinator import DispatchCoordinator
from services.reconciliation_service import ReconciliationService
from services.extraction_service import ExtractionService
from services.notification_service import NotificationService


class TransferService:
    def __init__(self, materialization_engine):
        self.engine = materialization_engine
        self.repository = TransferRepository()
        self.provider = ProviderGateway(materialization_engine)
        self.aria2 = Aria2Gateway(materialization_engine)
        self.ownership = OwnershipLedger(materialization_engine)
        self.state_machine = TransferStateMachine(materialization_engine)
        self.control = TransferControlService(materialization_engine, self.repository, self.state_machine)
        self.state_machine.bind_control(self.control)
        self.dispatch = DispatchCoordinator(materialization_engine, self.control, self.ownership)
        self.reconciliation = ReconciliationService(
            materialization_engine, self.repository, self.control, self.dispatch, self.ownership
        )
        self.extraction = ExtractionService()
        self.notifications = NotificationService()
        materialization_engine.bind_architecture(self)

    def __getattr__(self, name):
        # Compatibility while provider/materialization methods are progressively
        # moved out of the inherited engine. Orchestration methods below are explicit.
        return getattr(self.engine, name)

    async def pause_torrent(self, transfer_id: int):
        return await self.control.pause_transfer(transfer_id)

    async def resume_torrent(self, transfer_id: int):
        return await self.control.resume_transfer(transfer_id)

    async def pause_all_downloads(self):
        return await self.control.pause_all()

    async def resume_all_downloads(self):
        return await self.control.resume_all()

    async def control_aria2_gid(self, *args, **kwargs):
        return await self.control.control_gid(*args, **kwargs)

    async def owned_aria2_downloads(self, downloads):
        return await self.ownership.filter_owned(downloads)

    async def advance_aria2_queue(self):
        return await self.engine.advance_aria2_queue()

    async def apply_aria2_memory_tuning(self):
        return await self.engine.apply_aria2_memory_tuning()

    def reset_services(self):
        return self.engine.reset_services()

    async def sync_alldebrid_status(self):
        return await self.provider.sync_status()

    async def reconcile_provider_inventory(self):
        return await self.provider.reconcile_inventory()

    async def import_existing_magnets(self):
        return await self.provider.import_existing()


transfer_service = TransferService(engine)
