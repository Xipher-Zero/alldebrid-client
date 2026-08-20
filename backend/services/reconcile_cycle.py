"""Compatibility shim for callers migrating to ReconciliationService."""
from __future__ import annotations


async def reconcile_download_client_cycle(service=None) -> None:
    if service is None:
        from services.transfer_service import transfer_service
        service = transfer_service
    reconciliation = getattr(service, "reconciliation", None)
    if reconciliation is None:
        from services.transfer_service import transfer_service
        reconciliation = transfer_service.reconciliation
    await reconciliation.reconcile()
