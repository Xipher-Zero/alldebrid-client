"""Recovery is a compatibility entry point over authoritative reconciliation."""
from unittest.mock import AsyncMock, patch

import pytest

from services.reconciliation_service import ReconciliationService
from services.recovery import run_recovery_checks


@pytest.mark.asyncio
async def test_run_recovery_checks_delegates_to_authoritative_reconciliation():
    expected = {"reconciled": True}
    with patch("services.transfer_service.transfer_service.reconciliation.recover",
               AsyncMock(return_value=expected)) as recover:
        result = await run_recovery_checks()
    assert result == expected
    recover.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reconciliation_recover_runs_one_reconcile_pass():
    svc = object.__new__(ReconciliationService)
    svc.reconcile = AsyncMock()
    result = await ReconciliationService.recover(svc)
    svc.reconcile.assert_awaited_once_with()
    assert result == {"reconciled": True}


def test_recovery_module_contains_no_second_state_mutator():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "services" / "recovery.py").read_text()
    assert "_fix_orphaned_queued_files" not in source
    assert "_fix_queue_deadlock" not in source
    assert "transfer_service.reconciliation.recover" in source
