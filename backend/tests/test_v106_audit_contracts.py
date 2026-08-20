import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_transfer_service_has_no_transparent_legacy_fallback():
    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_service.py").read_text()
    assert "def __getattr__" not in source
    assert "return getattr(self._engine" not in source


def test_state_machine_does_not_import_http_layer():
    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_state_machine.py").read_text()
    assert "from api.routes" not in source
    assert "from services.event_bus import publish" in source


@pytest.mark.asyncio
async def test_external_gateway_rejects_foreign_gid(monkeypatch):
    import services.aria2_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "is_builtin_mode", lambda: False)
    aria2 = SimpleNamespace(pause=AsyncMock(), resume=AsyncMock())
    engine = SimpleNamespace(aria2=lambda: aria2)
    ownership = SimpleNamespace(owns=AsyncMock(return_value=False))
    gateway = gateway_module.Aria2Gateway(engine, ownership)

    with pytest.raises(PermissionError):
        await gateway.pause("foreign")
    with pytest.raises(PermissionError):
        await gateway.resume("foreign")
    aria2.pause.assert_not_awaited()
    aria2.resume.assert_not_awaited()


def test_public_serializers_strip_capability_urls():
    from api.serializers import public_download_file, public_payload, public_torrent

    torrent = public_torrent({"id": 1, "magnet": "magnet:?xt=secret", "download_url": "https://token", "name": "x"})
    assert torrent == {"id": 1, "name": "x"}
    file_row = public_download_file({"id": 2, "source_url": "https://source", "download_url": "https://unlocked", "filename": "x.mkv"})
    assert file_row == {"id": 2, "filename": "x.mkv"}
    nested = public_payload({"items": [{"magnet": "secret", "source_url": "secret", "id": 3}]})
    assert nested == {"items": [{"id": 3}]}


def test_backup_rotation_requires_ownership_manifest(tmp_path):
    from services import backup

    unrelated = tmp_path / "20000101_000000"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep")
    assert backup._rotate_backups(tmp_path, 1) == 0
    assert (unrelated / "keep.txt").exists()


def test_database_wipe_requires_verified_quiescence():
    import services.db_maintenance as maintenance

    with pytest.raises(RuntimeError, match="verified quiesced"):
        asyncio.run(maintenance.wipe_database())


def test_entrypoint_does_not_recursive_chown_downloads_by_default():
    source = (Path(__file__).resolve().parents[2] / "entrypoint.sh").read_text()
    assert "CHOWN_DOWNLOADS_RECURSIVE" in source
    assert "for DIR in /app/data /app/config /download" not in source


def test_scheduler_has_single_reconciliation_loop():
    source = (Path(__file__).resolve().parents[1] / "core" / "scheduler.py").read_text()
    assert "reconcile_download_client_cycle" not in source
    assert "async def recovery_loop" not in source
    assert "transfer_service.reconciliation.reconcile()" in source
