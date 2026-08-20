"""Compatibility entry point; recovery is authoritative reconciliation in v1.0.5."""
from __future__ import annotations


async def run_recovery_checks() -> dict:
    from services.transfer_service import transfer_service
    return await transfer_service.reconciliation.recover()
