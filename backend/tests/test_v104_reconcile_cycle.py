"""Regression coverage for v1.0.4 aria2 reconciliation snapshot reuse."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from core import scheduler
from services import reconcile_cycle


class _Download:
    def __init__(self, gid: str, status: str = "active") -> None:
        self.gid = gid
        self.status = status


class _Coordinator:
    def __init__(self) -> None:
        self._pause_intents = set()
        self.dispatch_snapshot = None
        self.initialized = False

    async def ensure_initialized(self) -> None:
        self.initialized = True

    async def _owned(self, downloads):
        return list(downloads)

    async def _enforce_selective_pauses(self) -> None:
        raise AssertionError("no selective pause exists in this test")

    async def _resume_unintended_paused(self) -> int:
        raise AssertionError("no slot is available, resume scan must be skipped")

    async def dispatch_queue(self, snapshot) -> int:
        self.dispatch_snapshot = list(snapshot)
        return 0


class _Manager:
    def __init__(self) -> None:
        self._aria2_state_lock = asyncio.Lock()
        self._dp_transfer_control = _Coordinator()
        self.raw_calls = 0
        self.sync_snapshot = None
        self.ready_scheduled = 0

    def download_client_name(self) -> str:
        return "aria2"

    async def _aria2_get_all(self):
        self.raw_calls += 1
        return [_Download("a"), _Download("b"), _Download("c")]

    async def sync_aria2_downloads(self) -> None:
        self.sync_snapshot = await self._aria2_get_all()

    def _aria2_slot_limit(self) -> int:
        return 3

    async def _schedule_ready_aria2_parents(self) -> int:
        self.ready_scheduled += 1
        return 0

    async def _cleanup_aria2_orphans(self) -> None:
        raise AssertionError("external aria2 cleanup must remain skipped")


@pytest.mark.asyncio
async def test_scheduler_cycle_reuses_one_snapshot_when_state_is_stable(monkeypatch):
    manager = _Manager()
    monkeypatch.setattr(
        reconcile_cycle,
        "get_settings",
        lambda: SimpleNamespace(paused=False),
    )
    monkeypatch.setattr(reconcile_cycle, "is_builtin_mode", lambda: False)

    await reconcile_cycle.reconcile_download_client_cycle(manager)

    assert manager._dp_transfer_control.initialized is True
    assert manager.raw_calls == 1
    assert [d.gid for d in manager.sync_snapshot] == ["a", "b", "c"]
    assert [d.gid for d in manager._dp_transfer_control.dispatch_snapshot] == [
        "a",
        "b",
        "c",
    ]
    assert manager.ready_scheduled == 1


@pytest.mark.asyncio
async def test_scheduler_snapshot_context_never_leaks_into_child_task():
    manager = _Manager()
    reconcile_cycle.install_scheduler_snapshot_reuse(manager)

    owner = asyncio.current_task()
    assert owner is not None
    cached = [_Download("cached")]
    token = reconcile_cycle._cycle_snapshot.set((owner, cached))
    try:
        same_task = await manager._aria2_get_all()
        child_task = await asyncio.create_task(manager._aria2_get_all())
    finally:
        reconcile_cycle._cycle_snapshot.reset(token)

    assert [d.gid for d in same_task] == ["cached"]
    assert [d.gid for d in child_task] == ["a", "b", "c"]
    assert manager.raw_calls == 1


def test_scheduler_uses_reconciliation_cycle_instead_of_legacy_sync_wrapper():
    source = inspect.getsource(scheduler.sync_download_clients_loop)
    assert "reconcile_download_client_cycle(manager)" in source
    assert "await manager.sync_download_clients()" not in source


def test_reconciliation_cycle_keeps_operator_confirmation_paths_out_of_scope():
    source = inspect.getsource(reconcile_cycle.reconcile_download_client_cycle)
    assert "dispatch_queue(snapshot)" in source
    assert "_strict_pause_gid" not in source
    assert "_strict_resume_gid" not in source
    assert "tell_status" not in source
