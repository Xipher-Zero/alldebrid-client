from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _TrackedLock:
    def __init__(self):
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.entered = False


@pytest.mark.asyncio
async def test_reconcile_reads_global_pause_only_after_state_lock(monkeypatch):
    import services.reconciliation_service as module

    lock = _TrackedLock()
    engine = SimpleNamespace(
        _aria2_state_lock=lock,
        download_client_name=lambda: "aria2",
        _engine_aria2_get_all=AsyncMock(return_value=[]),
        sync_aria2_downloads=AsyncMock(return_value=None),
        _schedule_ready_aria2_parents=AsyncMock(return_value=None),
        _aria2_slot_limit=lambda: 3,
        _cleanup_aria2_orphans=AsyncMock(return_value=None),
    )
    repository = SimpleNamespace(
        has_unintended_paused_children=AsyncMock(return_value=False),
    )
    control = SimpleNamespace(
        pause_intents=set(),
        ensure_initialized=AsyncMock(return_value=None),
        enforce_global_pause=AsyncMock(return_value=None),
        enforce_selective_pauses=AsyncMock(return_value=None),
        resume_unintended_paused=AsyncMock(return_value=0),
    )
    dispatch = SimpleNamespace(dispatch_queue=AsyncMock(return_value=None))
    ownership = SimpleNamespace(filter_owned=AsyncMock(return_value=[]))

    settings_reads = []

    def settings():
        settings_reads.append(lock.entered)
        if not lock.entered:
            raise AssertionError("global pause was sampled before acquiring aria2 state lock")
        return SimpleNamespace(paused=True)

    monkeypatch.setattr(module, "get_settings", settings)
    monkeypatch.setattr(module, "is_builtin_mode", lambda: False)

    service = module.ReconciliationService(engine, repository, control, dispatch, ownership)
    await service.reconcile()

    assert settings_reads == [True]
    control.enforce_global_pause.assert_awaited_once()
    dispatch.dispatch_queue.assert_not_awaited()
    engine._schedule_ready_aria2_parents.assert_not_awaited()
