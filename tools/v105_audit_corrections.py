from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


# 1. Scheduler must use the service root on the actual runtime path, not a removed global.
replace_once(
    "backend/core/scheduler.py",
    "await reconcile_download_client_cycle(manager)",
    "await reconcile_download_client_cycle(transfer_service)",
)
replace_once(
    "backend/core/scheduler.py",
    """                from services.notifications import notifier
                await notifier.send_update(
                    current_version=current,
                    latest_version=latest,
                    release_url=rel.get(\"html_url\", \"\"),
                    release_notes=(rel.get(\"body\") or \"\").strip(),
                )""",
    """                await transfer_service.notifications.client().send_update(
                    current_version=current,
                    latest_version=latest,
                    release_url=rel.get(\"html_url\", \"\"),
                    release_notes=(rel.get(\"body\") or \"\").strip(),
                )""",
)

# 2. Preserve the concrete notification client's null-object contract and dedicated added webhook.
write(
    "backend/services/notification_service.py",
    '''"""Application notification boundary for DebridPulse."""\nfrom __future__ import annotations\n\nfrom core.config import get_settings\nfrom services.notifications import NotificationService as DiscordNotificationClient\n\n\nclass NotificationService:\n    def client(self) -> DiscordNotificationClient:\n        """Return a concrete client; empty URLs intentionally no-op in the client."""\n        cfg = get_settings()\n        return DiscordNotificationClient(\n            webhook_url=str(getattr(cfg, "discord_webhook_url", "") or ""),\n            added_webhook_url=str(getattr(cfg, "discord_webhook_added", "") or ""),\n        )\n''',
)
replace_once("backend/services/notifications.py", "color=COLOR_WARN,", "color=COLOR_WARNING,")
replace_once(
    "backend/services/notifications.py",
    '''        cfg = get_settings()\n        if not getattr(cfg, "discord_notify_update", True):''',
    '''        from core.config import get_settings\n        cfg = get_settings()\n        if not getattr(cfg, "discord_notify_update", True):''',
)

# 3. Enforce shared-daemon safety at the gateway itself, not only at HTTP callers.
replace_once(
    "backend/services/aria2_gateway.py",
    '''    async def change_global_options(self, options):\n        return await self.engine.aria2().change_global_options(options)''',
    '''    async def change_global_options(self, options):\n        if not is_builtin_mode():\n            raise PermissionError("Global aria2 options are read-only in external mode")\n        return await self.engine.aria2().change_global_options(options)''',
)

# 4. Make operational state first-class SQLite schema.
replace_once(
    "backend/db/database.py",
    '''        await db.execute("""\n            CREATE TABLE IF NOT EXISTS stats_snapshots (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                snapshot_json TEXT NOT NULL,\n                created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n            )\n        """)''',
    '''        await db.execute("""\n            CREATE TABLE IF NOT EXISTS stats_snapshots (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                snapshot_json TEXT NOT NULL,\n                created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n            )\n        """)\n        await db.execute("""\n            CREATE TABLE IF NOT EXISTS transfer_pause_intents (\n                torrent_id INTEGER PRIMARY KEY,\n                paused INTEGER NOT NULL DEFAULT 1,\n                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n        """)\n        await db.execute("""\n            CREATE TABLE IF NOT EXISTS debridpulse_aria2_owned_gids (\n                gid TEXT PRIMARY KEY,\n                download_file_id INTEGER,\n                torrent_id INTEGER,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n        """)''',
)

# Reset in-memory durable-state mirrors whenever persistence/settings are reset.
replace_once(
    "backend/services/transfer_control_service.py",
    '''    async def ensure_initialized(self):\n        return await self.coordinator.ensure_initialized()\n''',
    '''    async def ensure_initialized(self):\n        return await self.coordinator.ensure_initialized()\n\n    def reset_runtime_state(self) -> None:\n        """Drop cached intent state so the next use reloads the authoritative DB."""\n        self.coordinator._pause_intents.clear()\n        self.coordinator._lost_strikes.clear()\n        self.coordinator._initialized = False\n''',
)
replace_once(
    "backend/services/transfer_service.py",
    '''    def reset_services(self):\n        return self.engine.reset_services()''',
    '''    def reset_services(self):\n        self.control.reset_runtime_state()\n        return self.engine.reset_services()''',
)

# Backup/wipe must cover operational tables, and wipe must invalidate service caches.
replace_once(
    "backend/services/db_maintenance.py",
    '''TABLES = [\n    "torrents",\n    "download_files",\n    "events",\n    "stats_snapshots",\n]''',
    '''TABLES = [\n    "torrents",\n    "download_files",\n    "events",\n    "stats_snapshots",\n    "transfer_pause_intents",\n    "debridpulse_aria2_owned_gids",\n]\n\n_TABLE_ORDER = {\n    "torrents": "id",\n    "download_files": "id",\n    "events": "id",\n    "stats_snapshots": "id",\n    "transfer_pause_intents": "torrent_id",\n    "debridpulse_aria2_owned_gids": "gid",\n}''',
)
replace_once(
    "backend/services/db_maintenance.py",
    '''            for table in TABLES:\n                rows = await db.fetchall(f"SELECT * FROM {table} ORDER BY id")\n                payload["tables"][table] = rows''',
    '''            for table in TABLES:\n                order_key = _TABLE_ORDER[table]\n                rows = await db.fetchall(f"SELECT * FROM {table} ORDER BY {order_key}")\n                payload["tables"][table] = rows''',
)
replace_once(
    "backend/services/db_maintenance.py",
    '''async def wipe_database() -> dict:\n    async with get_db() as db:\n        await db.execute("DELETE FROM download_files")\n        await db.execute("DELETE FROM events")\n        await db.execute("DELETE FROM stats_snapshots")\n        await db.execute("DELETE FROM torrents")\n        try:\n            await db.execute(\n                "DELETE FROM sqlite_sequence WHERE name IN ('torrents','download_files','events','stats_snapshots')"\n            )\n        except Exception as exc:\n            logger.debug("sqlite_sequence reset skipped: %s", exc)\n        await db.commit()\n\n    logger.warning("Database wipe completed")\n    return {"ok": True, "wiped_tables": TABLES}\n''',
    '''async def wipe_database() -> dict:\n    async with get_db() as db:\n        await db.execute("DELETE FROM debridpulse_aria2_owned_gids")\n        await db.execute("DELETE FROM transfer_pause_intents")\n        await db.execute("DELETE FROM download_files")\n        await db.execute("DELETE FROM events")\n        await db.execute("DELETE FROM stats_snapshots")\n        await db.execute("DELETE FROM torrents")\n        try:\n            await db.execute(\n                "DELETE FROM sqlite_sequence WHERE name IN ('torrents','download_files','events','stats_snapshots')"\n            )\n        except Exception as exc:\n            logger.debug("sqlite_sequence reset skipped: %s", exc)\n        await db.commit()\n\n    # Drop in-memory mirrors only after the durable wipe commits successfully.\n    from services.transfer_service import transfer_service\n    transfer_service.reset_services()\n    logger.warning("Database wipe completed")\n    return {"ok": True, "wiped_tables": TABLES}\n''',
)

# Use SQLite's online backup API so WAL state is captured consistently.
replace_once("backend/services/backup.py", "import shutil\n", "import shutil\nimport sqlite3\n")
replace_once(
    "backend/services/backup.py",
    '''logger = logging.getLogger("alldebrid.backup")\n\n\ndef _cfg():''',
    '''logger = logging.getLogger("alldebrid.backup")\n\n\ndef _sqlite_backup(source: Path, destination: Path) -> None:\n    with sqlite3.connect(str(source), timeout=30) as src:\n        with sqlite3.connect(str(destination), timeout=30) as dst:\n            src.backup(dst)\n\n\ndef _cfg():''',
)
replace_once(
    "backend/services/backup.py",
    '''        if DB_PATH.exists():\n            shutil.copy2(DB_PATH, backup_dir / DB_PATH.name)\n            backed_up.append(DB_PATH.name)''',
    '''        if DB_PATH.exists():\n            await asyncio.to_thread(_sqlite_backup, DB_PATH, backup_dir / DB_PATH.name)\n            backed_up.append(DB_PATH.name)''',
)

# 5. Correct path containment: string prefixes are not directory ancestry.
replace_once(
    "backend/api/routes.py",
    '''    dl_root = str(_Path(getattr(cfg, "download_folder", "/download")).resolve())\n    resolved = str(_Path(path).resolve())\n    if not resolved.startswith(dl_root):\n        raise HTTPException(403, "Path outside download folder")\n    if not _Path(resolved).is_file():\n        raise HTTPException(404, "File not found")\n    from services.mediainfo import get_mediainfo\n    return await get_mediainfo(resolved)''',
    '''    dl_root = _Path(getattr(cfg, "download_folder", "/download")).resolve()\n    resolved = _Path(path).resolve()\n    if not resolved.is_relative_to(dl_root):\n        raise HTTPException(403, "Path outside download folder")\n    if not resolved.is_file():\n        raise HTTPException(404, "File not found")\n    from services.mediainfo import get_mediainfo\n    return await get_mediainfo(str(resolved))''',
)

# 6. Basic-Auth CSRF hardening. Same-host browser origins remain valid; scripts with no Origin remain valid.
replace_once(
    "backend/main.py",
    '''            if user_ok and pass_ok:\n                return await call_next(request)''',
    '''            if user_ok and pass_ok:\n                if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:\n                    origin = str(request.headers.get("Origin", "") or "").strip()\n                    if origin:\n                        from urllib.parse import urlparse\n                        origin_host = (urlparse(origin).netloc or "").casefold()\n                        request_host = str(request.headers.get("Host", "") or "").casefold()\n                        configured = {\n                            urlparse(item).netloc.casefold()\n                            for item in _cors_origins\n                            if urlparse(item).netloc\n                        }\n                        if origin_host != request_host and origin_host not in configured:\n                            return Response(content="Forbidden origin", status_code=403)\n                return await call_next(request)''',
)

# 7. Documentation must describe the SQLite-only runtime actually shipped by v1.0.5.
replace_once(
    "README.md",
    "| **SQLite or PostgreSQL** | SQLite by default with optional external PostgreSQL |",
    "| **SQLite persistence** | SQLite/WAL is the authoritative application datastore |",
)
replace_once(
    "README.md",
    "### Database\n\nUse the default SQLite database or configure an external PostgreSQL instance.",
    "### Database\n\nDebridPulse uses a single authoritative SQLite/WAL database. Configure its persistent path through `DB_PATH` or the container data mount.",
)
index = read("index.html")
index = index.replace("SQLite / PostgreSQL", "SQLite / WAL")
index = index.replace("SQLite/PostgreSQL", "SQLite/WAL")
index = index.replace("PostgreSQL", "SQLite")
index = index.replace("/api/docs", "/docs")
write("index.html", index)

# 8. Add an undefined-name gate to CI: compilation alone cannot catch dangling globals.
replace_once(
    ".github/workflows/tests.yml",
    '''      - name: Install dependencies\n        run: |\n          cd backend\n          pip install -r requirements-dev.txt''',
    '''      - name: Install dependencies\n        run: |\n          cd backend\n          pip install -r requirements-dev.txt\n          pip install ruff''',
)
replace_once(
    ".github/workflows/tests.yml",
    '''      - name: Check Python syntax\n        run: |\n          cd backend\n          python -m compileall -q .\n          echo "All Python modules compile"''',
    '''      - name: Check undefined Python names\n        run: |\n          cd backend\n          ruff check api core db services main.py --select F821\n\n      - name: Check Python syntax\n        run: |\n          cd backend\n          python -m compileall -q .\n          echo "All Python modules compile"''',
)

# 9. Focused regressions for every runtime defect that escaped the previous green suite.
write(
    "backend/tests/test_v105_audit_regressions.py",
    r'''import asyncio
import base64
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


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
    gateway = gateway_module.Aria2Gateway(engine)
    with pytest.raises(PermissionError):
        await gateway.change_global_options({"max-overall-download-limit": "1M"})
    aria2.change_global_options.assert_not_awaited()


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

    async with database.get_db() as db:
        await db.execute("INSERT INTO torrents(hash, name, status) VALUES(?, ?, ?)", ("abc", "x", "paused"))
        await db.execute("INSERT INTO transfer_pause_intents(torrent_id, paused) VALUES(1, 1)")
        await db.execute("INSERT INTO debridpulse_aria2_owned_gids(gid, torrent_id) VALUES('gid1', 1)")
        await db.commit()

    transfer_service.control.coordinator._pause_intents = {1}
    transfer_service.control.coordinator._initialized = True
    result = await maintenance.wipe_database()
    assert set(result["wiped_tables"]) >= {"transfer_pause_intents", "debridpulse_aria2_owned_gids"}
    assert transfer_service.control.coordinator._pause_intents == set()
    assert transfer_service.control.coordinator._initialized is False

    async with database.get_db() as db:
        for table in maintenance.TABLES:
            row = await db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")
            assert row["n"] == 0


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


def test_mediainfo_uses_real_path_ancestry_check():
    source = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text()
    assert ".is_relative_to(dl_root)" in source
    assert "resolved.startswith(dl_root)" not in source


def test_readme_describes_sqlite_only_runtime():
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text()
    assert "SQLite or PostgreSQL" not in readme
    assert "external PostgreSQL" not in readme


def test_basic_auth_rejects_cross_origin_mutation(monkeypatch):
    import core.config
    import main
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        core.config,
        "get_settings",
        lambda: SimpleNamespace(auth_username="user", auth_password="pass"),
    )
    token = base64.b64encode(b"user:pass").decode()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/does-not-exist",
            headers={"Authorization": f"Basic {token}", "Origin": "https://evil.invalid"},
        )
        assert response.status_code == 403
''',
)

# Sanity assertions that the one-shot script actually removed every audited symbol/pattern.
checks = {
    "backend/core/scheduler.py": ["reconcile_download_client_cycle(manager)", "from services.notifications import notifier"],
    "backend/services/notifications.py": ["COLOR_WARN,"],
    "README.md": ["SQLite or PostgreSQL", "external PostgreSQL"],
}
for path, forbidden in checks.items():
    text = read(path)
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"{path}: audited residue remains: {token}")

print("v1.0.5 audit corrections applied")
