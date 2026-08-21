from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeAria2:
    def __init__(self):
        self.tell_status = AsyncMock()
        self._call = AsyncMock()


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["_strict_pause_gid", "_strict_resume_gid"])
async def test_external_foreign_gid_never_reaches_strict_transfer_control_rpc(monkeypatch, method_name):
    import services.transfer_control as control_module

    monkeypatch.setattr(control_module, "is_builtin_mode", lambda: False)
    aria2 = _FakeAria2()
    manager = SimpleNamespace(
        aria2=lambda: aria2,
        _aria2_owned_gids=AsyncMock(return_value={"owned-gid"}),
        _engine_dispatch_pending_aria2_queue=AsyncMock(),
        _engine_schedule_ready_parent_download=AsyncMock(),
        _engine_start_download=AsyncMock(),
        _engine_download=AsyncMock(),
        _engine_reset_torrent_for_redownload=AsyncMock(),
        _engine_update_aria2_parent_progress=AsyncMock(),
        _engine_sync_download_clients=AsyncMock(),
    )
    coordinator = control_module.TransferControlCoordinator(manager)

    with pytest.raises(PermissionError, match="not owned by DebridPulse"):
        await getattr(coordinator, method_name)("foreign-gid")

    manager._aria2_owned_gids.assert_awaited()
    aria2.tell_status.assert_not_awaited()
    aria2._call.assert_not_awaited()


def test_parent_pause_resume_mutations_use_strict_owned_helpers():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_control.py").read_text()
    pause_parent = source.split("async def _pause_parent", 1)[1].split("async def resume_torrent", 1)[0]
    resume_parent = source.split("async def _resume_parent", 1)[1].split("async def pause_all_downloads", 1)[0]

    assert "await self._strict_pause_gid(gid)" in pause_parent
    assert "await self._strict_resume_gid(gid)" in resume_parent
