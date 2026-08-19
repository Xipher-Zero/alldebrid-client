"""Regression tests for DebridPulse v1.0.3 pause/resume reliability."""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.aria2 import Aria2DownloadStatus, Aria2RPCError
from services.manager_v2 import manager
from services.transfer_control import TransferControlCoordinator


def _status(gid: str, status: str) -> Aria2DownloadStatus:
    return Aria2DownloadStatus(
        gid=gid,
        status=status,
        total_length=100,
        completed_length=25,
        download_speed=1,
        files=[],
    )


def test_reliability_layer_installs_on_shared_manager_only():
    coordinator = getattr(manager, "_dp_transfer_control", None)
    assert isinstance(coordinator, TransferControlCoordinator)
    assert manager.pause_torrent == coordinator.pause_torrent
    assert manager.resume_torrent == coordinator.resume_torrent
    assert manager._dispatch_pending_aria2_queue == coordinator.dispatch_queue
    assert manager._advance_aria2_queue_locked == coordinator.advance_queue_locked


@pytest.mark.asyncio
async def test_pause_rpc_failure_is_not_reported_as_success():
    coordinator = manager._dp_transfer_control
    fake = SimpleNamespace(
        tell_status=AsyncMock(return_value=_status("g1", "active")),
        _call=AsyncMock(side_effect=Aria2RPCError("pause rejected")),
    )
    with patch.object(manager, "aria2", return_value=fake):
        with pytest.raises(Aria2RPCError, match="pause rejected"):
            await coordinator._strict_pause_gid("g1")
    fake._call.assert_awaited_once_with("aria2.pause", ["g1"])


@pytest.mark.asyncio
async def test_resume_rpc_failure_is_not_reported_as_success():
    coordinator = manager._dp_transfer_control
    fake = SimpleNamespace(
        tell_status=AsyncMock(return_value=_status("g2", "paused")),
        _call=AsyncMock(side_effect=Aria2RPCError("resume rejected")),
    )
    with patch.object(manager, "aria2", return_value=fake):
        with pytest.raises(Aria2RPCError, match="resume rejected"):
            await coordinator._strict_resume_gid("g2")
    fake._call.assert_awaited_once_with("aria2.unpause", ["g2"])


@pytest.mark.asyncio
async def test_missing_gid_requires_repeated_explicit_not_found():
    coordinator = manager._dp_transfer_control
    fake = SimpleNamespace(
        tell_status=AsyncMock(
            side_effect=[
                Aria2RPCError("aria2 [-1]: GID#g3 is not found"),
                Aria2RPCError("aria2 [-1]: GID#g3 is not found"),
                Aria2RPCError("aria2 [-1]: GID#g3 is not found"),
            ]
        )
    )
    with patch.object(manager, "aria2", return_value=fake), patch(
        "services.transfer_control.asyncio.sleep", new=AsyncMock()
    ) as sleep:
        result = await coordinator.confirm_gid("g3", attempts=3, delay=.01)
    assert result is None
    assert fake.tell_status.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_non_missing_rpc_error_never_becomes_missing_gid():
    coordinator = manager._dp_transfer_control
    fake = SimpleNamespace(
        tell_status=AsyncMock(
            side_effect=Aria2RPCError("aria2 [1]: unauthorized request")
        )
    )
    with patch.object(manager, "aria2", return_value=fake):
        with pytest.raises(Aria2RPCError, match="unauthorized"):
            await coordinator.confirm_gid("g-auth")
    assert fake.tell_status.await_count == 1


@pytest.mark.asyncio
async def test_unexpected_aria2_state_is_not_claimed_paused():
    coordinator = manager._dp_transfer_control
    fake = SimpleNamespace(
        tell_status=AsyncMock(return_value=_status("g4", "unknown")),
        _call=AsyncMock(),
    )
    with patch.object(manager, "aria2", return_value=fake):
        with pytest.raises(Aria2RPCError, match="cannot be paused"):
            await coordinator._strict_pause_gid("g4")
    fake._call.assert_not_awaited()


def test_selective_pause_blocks_provider_ready_scheduling_immediately():
    coordinator = manager._dp_transfer_control
    torrent_id = 987654321
    coordinator._pause_intents.add(torrent_id)
    try:
        assert coordinator.schedule_ready_parent(
            torrent_id, "ad-id", "item"
        ) is False
    finally:
        coordinator._pause_intents.discard(torrent_id)


@pytest.mark.asyncio
async def test_pause_arriving_during_magnet_materialization_is_reapplied():
    coordinator = manager._dp_transfer_control
    torrent_id = 987654322
    original = coordinator._orig_download

    async def materialize(*_args):
        coordinator._pause_intents.add(torrent_id)

    try:
        coordinator._pause_intents.discard(torrent_id)
        coordinator._orig_download = AsyncMock(side_effect=materialize)
        with patch.object(
            coordinator, "_pause_parent", new=AsyncMock(return_value={})
        ) as pause:
            await coordinator.download(torrent_id, "ad-id", "magnet item")
        pause.assert_awaited_once_with(torrent_id, strict=False)
    finally:
        coordinator._orig_download = original
        coordinator._pause_intents.discard(torrent_id)


@pytest.mark.asyncio
async def test_individual_resume_cannot_silently_disable_pause_all():
    coordinator = manager._dp_transfer_control
    old = coordinator._initialized
    coordinator._initialized = True
    try:
        with patch(
            "services.transfer_control.get_settings",
            return_value=SimpleNamespace(paused=True),
        ):
            with pytest.raises(ValueError, match="globally paused"):
                await coordinator.resume_torrent(123)
    finally:
        coordinator._initialized = old


def test_dispatcher_grandfathers_over_limit_jobs_instead_of_removing_gids():
    source = inspect.getsource(TransferControlCoordinator.dispatch_queue)
    assert "grandfathering them without removing GIDs" in source
    assert "_remove_owned_aria2_gid" not in source
    assert "_orig_dispatch(snapshot)" in source


def test_provider_source_is_preserved_before_generated_url_overwrite():
    source = inspect.getsource(TransferControlCoordinator._preserve_pending_sources)
    assert "SET source_url=download_url" in source
    assert "t.source!='direct_link'" in source
    assert "f.status='pending'" in source


def test_queue_refill_is_deferred_outside_operator_request_path():
    advance = inspect.getsource(TransferControlCoordinator.advance_queue_locked)
    sync = inspect.getsource(TransferControlCoordinator.sync_clients)
    assert "_schedule_queue()" in advance
    assert "_orig_dispatch" not in advance
    assert "await self.manager.sync_aria2_downloads()" in sync
    assert "self._schedule_queue()" in sync


def test_lost_gid_recovery_preserves_completed_siblings_when_source_known():
    source = inspect.getsource(TransferControlCoordinator.reset_for_redownload)
    assert "without rebuilding completed siblings" in source
    assert "download_id=NULL" in source
    assert "DELETE FROM download_files" not in source
    assert "strikes < 2" in source


def test_recovery_loop_confirms_gid_before_mutating_queue_state():
    from services import recovery
    source = inspect.getsource(recovery._fix_orphaned_queued_files)
    assert "confirm_gid" in source
    assert "Never clear a legacy GID here" in source


def test_pause_intent_table_keeps_resume_tombstone_for_restart_semantics():
    source = inspect.getsource(TransferControlCoordinator._set_intent)
    init = inspect.getsource(TransferControlCoordinator.ensure_initialized)
    assert "paused=excluded.paused" in source
    assert "p.torrent_id IS NULL" in init
    assert "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in init
