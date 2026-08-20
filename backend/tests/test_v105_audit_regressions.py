import asyncio
import base64
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response


def test_notification_boundary_preserves_null_object_and_added_webhook(monkeypatch):
    import services.notification_service as boundary

    monkeypatch.setattr(
        boundary,
        "get_settings",
        lambda: SimpleNamespace(discord_webhook_url="", discord_webhook_added=""),
    )
    client = boundary.NotificationService().client()
    assert client is not None
    assert client.webhook_url == ""
    assert client.added_webhook_url == ""
    asyncio.run(client.send_added("no-webhook submission"))

    monkeypatch.setattr(
        boundary,
        "get_settings",
        lambda: SimpleNamespace(
            discord_webhook_url="https://example.invalid/main",
            discord_webhook_added="https://example.invalid/added",
        ),
    )
    client = boundary.NotificationService().client()
    assert client.webhook_url.endswith("/main")
    assert client.added_webhook_url.endswith("/added")


@pytest.mark.asyncio
async def test_notification_requeue_and_update_paths_have_resolved_symbols(monkeypatch):
    import core.config
    from services.notifications import NotificationService

    client = NotificationService("https://example.invalid/main")
    client._send = AsyncMock(return_value=True)
    await client.send_requeue("x", 1, 3, reason="retry")

    monkeypatch.setattr(
        core.config,
        "get_settings",
        lambda: SimpleNamespace(discord_notify_update=True),
    )
    await client.send_update("1.0.4", "1.0.5")
    assert client._send.await_count == 2


@pytest.mark.asyncio
async def test_scheduler_download_cycle_uses_service_root(monkeypatch):
    import core.scheduler as scheduler

    monkeypatch.setattr(scheduler, "_jitter_sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(aria2_poll_interval_seconds=2),
    )

    seen = []

    async def one_cycle(service):
        seen.append(service)
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduler, "reconcile_download_client_cycle", one_cycle)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.sync_download_clients_loop()
    assert seen == [scheduler.transfer_service]


def test_scheduler_update_notifications_use_service_boundary():
    source = (Path(__file__).resolve().parents[1] / "core" / "scheduler.py").read_text()
    assert "from services.notifications import notifier" not in source
    assert "transfer_service.notifications.client().send_update" in source


@pytest.mark.asyncio
async def test_external_aria2_gateway_cannot_change_global_options(monkeypatch):
    import services.aria2_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "is_builtin_mode", lambda: False)
    aria2 = SimpleNamespace(change_global_options=AsyncMock())
    engine = SimpleNamespace(aria2=lambda: aria2)
    ownership = SimpleNamespace(owns=AsyncMock(return_value=True), filter_owned=AsyncMock())
    gateway = gateway_module.Aria2Gateway(engine, ownership)
    with pytest.raises(PermissionError):
        await gateway.change_global_options({"max-overall-download-limit": "1M"})
    aria2.change_global_options.assert_not_awaited()


@pytest.mark.asyncio
async def test_builtin_aria2_gateway_can_change_global_options(monkeypatch):
    import services.aria2_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "is_builtin_mode", lambda: True)
    aria2 = SimpleNamespace(change_global_options=AsyncMock(return_value={"ok": True}))
    engine = SimpleNamespace(aria2=lambda: aria2)
    ownership = SimpleNamespace(owns=AsyncMock(return_value=True), filter_owned=AsyncMock())
    gateway = gateway_module.Aria2Gateway(engine, ownership)
    result = await gateway.change_global_options({"max-overall-download-limit": "1M"})
    assert result == {"ok": True}
    aria2.change_global_options.assert_awaited_once()


@pytest.mark.asyncio
async def test_operational_tables_are_first_class_and_wipe_resets_runtime(tmp_path, monkeypatch):
    import db.database as database
    import services.db_maintenance as maintenance
    from services.transfer_service import transfer_service

    db_path = tmp_path / "state.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    await database.init_db()

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "transfer_pause_intents" in tables
    assert "debridpulse_aria2_owned_gids" in tables
    assert set(maintenance.TABLES) >= {"transfer_pause_intents", "debridpulse_aria2_owned_gids"}

    async with database.get_db() as db:
        await db.execute("INSERT INTO torrents(hash, name, status) VALUES(?, ?, ?)", ("abc", "x", "paused"))
        await db.execute("INSERT INTO transfer_pause_intents(torrent_id, paused) VALUES(1, 1)")
        await db.execute("INSERT INTO debridpulse_aria2_owned_gids(gid, torrent_id) VALUES('gid1', 1)")
        await db.commit()

    transfer_service.control.coordinator._pause_intents = {1}
    transfer_service.control.coordinator._initialized = True
    result = await maintenance.wipe_database(verified_quiesced=True)
    assert set(result["wiped_tables"]) >= {"transfer_pause_intents", "debridpulse_aria2_owned_gids"}
    assert transfer_service.control.coordinator._pause_intents == set()
    assert transfer_service.control.coordinator._initialized is False

    async with database.get_db() as db:
        for table in maintenance.TABLES:
            row = await db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")
            assert row["n"] == 0


@pytest.mark.asyncio
async def test_database_json_backup_includes_operational_tables(tmp_path, monkeypatch):
    import db.database as database
    import services.db_maintenance as maintenance

    db_path = tmp_path / "state.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    await database.init_db()
    backup_root = tmp_path / "db-backups"
    monkeypatch.setattr(
        maintenance,
        "get_settings",
        lambda: SimpleNamespace(
            db_backup_enabled=True,
            db_backup_folder=str(backup_root),
            db_backup_keep_days=7,
        ),
    )
    result = await maintenance.run_database_backup()
    assert result["errors"] == []
    assert "transfer_pause_intents" in result["tables"]
    assert "debridpulse_aria2_owned_gids" in result["tables"]


@pytest.mark.asyncio
async def test_online_backup_captures_committed_wal_state(tmp_path, monkeypatch):
    import db.database as database
    import services.backup as backup

    db_path = tmp_path / "live.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    await database.init_db()
    async with database.get_db() as db:
        await db.execute("INSERT INTO torrents(hash, name) VALUES(?, ?)", ("wal-hash", "wal-row"))
        await db.commit()

    backup_root = tmp_path / "backups"
    monkeypatch.setattr(
        backup,
        "_cfg",
        lambda: SimpleNamespace(backup_enabled=True, backup_folder=str(backup_root), backup_keep_days=7),
    )
    result = await backup.run_backup()
    assert result["errors"] == []
    copied = Path(result["backup_dir"]) / db_path.name
    with sqlite3.connect(copied) as conn:
        assert conn.execute("SELECT name FROM torrents WHERE hash='wal-hash'").fetchone()[0] == "wal-row"


def test_mediainfo_service_uses_real_path_ancestry(tmp_path, monkeypatch):
    import services.mediainfo as mediainfo

    root = tmp_path / "download"
    sibling = tmp_path / "download_evil"
    root.mkdir()
    sibling.mkdir()
    inside = root / "inside.mkv"
    outside = sibling / "outside.mkv"
    inside.write_bytes(b"x")
    outside.write_bytes(b"x")

    monkeypatch.setattr(
        mediainfo,
        "get_settings",
        lambda: SimpleNamespace(download_folder=str(root)),
    )
    assert mediainfo.resolve_media_path(str(inside)) == inside.resolve()
    with pytest.raises(PermissionError):
        mediainfo.resolve_media_path(str(outside))


@pytest.mark.asyncio
async def test_service_permission_error_maps_to_http_403():
    import main

    response = await main.permission_error_handler(None, PermissionError("secret detail"))
    assert response.status_code == 403
    assert response.body == b"Forbidden"


def _request(method: str, path: str, headers: dict[str, str]) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.asyncio
async def test_basic_auth_rejects_cross_origin_mutation(monkeypatch):
    import core.config
    import main

    monkeypatch.setattr(
        core.config,
        "get_settings",
        lambda: SimpleNamespace(auth_username="user", auth_password="pass"),
    )
    token = base64.b64encode(b"user:pass").decode()
    request = _request(
        "POST",
        "/api/does-not-exist",
        {
            "Authorization": f"Basic {token}",
            "Origin": "https://evil.invalid",
            "Host": "testserver",
        },
    )
    call_next = AsyncMock(return_value=Response(status_code=204))
    response = await main.basic_auth_middleware(request, call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_basic_auth_allows_same_origin_and_nonbrowser_clients(monkeypatch):
    import core.config
    import main

    monkeypatch.setattr(
        core.config,
        "get_settings",
        lambda: SimpleNamespace(auth_username="user", auth_password="pass"),
    )
    token = base64.b64encode(b"user:pass").decode()
    auth = f"Basic {token}"

    same_origin = _request(
        "POST",
        "/api/test",
        {"Authorization": auth, "Origin": "http://testserver", "Host": "testserver"},
    )
    call_next = AsyncMock(return_value=Response(status_code=204))
    assert (await main.basic_auth_middleware(same_origin, call_next)).status_code == 204

    script_client = _request(
        "POST",
        "/api/test",
        {"Authorization": auth, "Host": "testserver"},
    )
    call_next = AsyncMock(return_value=Response(status_code=204))
    assert (await main.basic_auth_middleware(script_client, call_next)).status_code == 204


def test_readme_describes_sqlite_only_runtime():
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text()
    assert "SQLite or PostgreSQL" not in readme
    assert "external PostgreSQL" not in readme
    assert "SQLite/WAL" in readme
