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


def test_state_machine_uses_repository_instead_of_database_layer():
    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_state_machine.py").read_text()
    assert "from db.database" not in source
    assert "get_db(" not in source
    assert "self.repository.parent_progress_rows()" in source
    assert "self.repository.persist_parent_progress(updates)" in source


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


def test_zip_preflight_rejects_file_count_budget(tmp_path, monkeypatch):
    import zipfile
    import services.extraction_safety as safety
    from services.extractor import _extract_zip

    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("one.txt", b"1")
        zf.writestr("two.txt", b"2")
    monkeypatch.setattr(
        safety, "get_settings",
        lambda: SimpleNamespace(
            extract_max_files=1,
            extract_max_expanded_gb=1,
            extract_max_compression_ratio=1000,
        ),
    )
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="files"):
        _extract_zip(archive, dest)
    assert list(dest.iterdir()) == []


def test_external_staging_rejects_symlink_output(tmp_path, monkeypatch):
    import services.extraction_safety as safety

    archive = tmp_path / "archive.7z"
    archive.write_bytes(b"archive")
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(
        safety, "get_settings",
        lambda: SimpleNamespace(
            extract_max_files=100,
            extract_max_expanded_gb=1,
            extract_max_compression_ratio=1000,
        ),
    )

    def malicious(stage):
        (stage / "escape").symlink_to(tmp_path / "outside")

    with pytest.raises(ValueError, match="symlink"):
        safety.staged_external_extract(archive, dest, malicious)
    assert list(dest.iterdir()) == []


def test_7z_listing_budget_is_validated_before_extraction(tmp_path, monkeypatch):
    import services.extraction_safety as safety

    archive = tmp_path / "archive.7z"
    archive.write_bytes(b"x" * 100)
    monkeypatch.setattr(
        safety, "get_settings",
        lambda: SimpleNamespace(
            extract_max_files=1,
            extract_max_expanded_gb=1,
            extract_max_compression_ratio=1000,
        ),
    )
    listing = "Header\n----------\nPath = one\nSize = 1\nAttributes = A\n\nPath = two\nSize = 1\nAttributes = A\n"
    with pytest.raises(ValueError, match="files"):
        safety.validate_7z_listing(archive, listing)


def test_alldebrid_client_rate_limits_multipart_uploads():
    source = (Path(__file__).resolve().parents[1] / "services" / "alldebrid.py").read_text()
    multipart = source.split("async def _multipart", 1)[1].split("# ── User", 1)[0]
    assert "await acquire_alldebrid_request_slot()" in multipart
    assert "services.manager_v2" not in source

def test_materialization_engine_publishes_without_importing_http_layer():
    source = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()
    assert "from api.routes" not in source
    assert "from services.event_bus import publish" in source
    direct = source.split("async def _broadcast_direct_link_update", 1)[1].split("@staticmethod", 1)[0]
    assert 'await publish(' in direct


def test_rar_extraction_fails_closed_without_preflight_capable_7z():
    source = (Path(__file__).resolve().parents[1] / "services" / "extractor.py").read_text()
    rar = source.split("def _extract_rar_to", 1)[1].split("def _extract_rar(", 1)[0]
    assert "_preflight_7z" in rar
    assert '"unrar"' not in rar
    assert '"unrar-free"' not in rar
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    assert "p7zip-full" in dockerfile
    assert "unrar-free" not in dockerfile
