#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".v105_changed_paths"
changed = {line.strip() for line in MANIFEST.read_text().splitlines() if line.strip()}


def p(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return p(rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    p(rel).parent.mkdir(parents=True, exist_ok=True)
    p(rel).write_text(text, encoding="utf-8")
    changed.add(rel)


def delete(rel: str) -> None:
    if p(rel).exists():
        p(rel).unlink()
    changed.add(rel)


def remove_top_function(rel: str, name: str) -> None:
    text = read(rel)
    tree = ast.parse(text)
    node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if node is None:
        return
    lines = text.splitlines(keepends=True)
    start = node.lineno - 1
    while start > 0 and lines[start - 1].lstrip().startswith("@"):
        start -= 1
    end = node.end_lineno
    while end < len(lines) and not lines[end].strip():
        end += 1
    write(rel, "".join(lines[:start] + lines[end:]))


# Restore the provider-ready helper that the first AST deletion pass swallowed.
manager_rel = "backend/services/manager_v2.py"
manager = read(manager_rel)
if "async def _fetch_ready_files(" not in manager:
    marker = "    async def _engine_download("
    if marker not in manager:
        raise RuntimeError("_engine_download marker missing")
    helper = '''    async def _fetch_ready_files(self, ad_id: str) -> List[dict]:
        last_error = None
        last_summary = ""
        for attempt in range(1, READY_FILE_RETRIES + 1):
            try:
                status = await self.ad().get_magnet_status(ad_id)
                if not isinstance(status, dict):
                    raise TransientAllDebridStateError(
                        f"magnet/status returned {type(status).__name__}, expected object"
                    )

                status_code = int(status.get("statusCode", 0) or 0)
                nested = flatten_files(status.get("files", []))
                status_links = status.get("links", [])
                nested_summary = [
                    {
                        "name": str(item.get("name", ""))[:120],
                        "size": int(item.get("size", 0) or 0),
                        "has_link": bool(item.get("link")),
                    }
                    for item in nested[:8]
                ]
                last_summary = (
                    f"statusCode={status_code}, nested_files={len(nested)}, "
                    f"top_level_links={len(status_links) if isinstance(status_links, list) else 0}, "
                    f"sample={nested_summary}"
                )

                if status_code != READY_CODE:
                    raise TransientAllDebridStateError(
                        f"AllDebrid returned transient statusCode={status_code}"
                    )

                file_infos = [
                    {"name": f["name"], "size": int(f.get("size", 0) or 0), "link": f["link"]}
                    for f in nested
                    if f.get("link")
                ]

                if not file_infos and isinstance(status_links, list):
                    fallback = []
                    for idx, entry in enumerate(status_links, start=1):
                        if isinstance(entry, str):
                            link = entry
                            name = PurePosixPath(urlparse(entry).path).name or f"file_{idx}"
                            fallback.append({"name": name, "size": 0, "link": link})
                        elif isinstance(entry, dict):
                            link = entry.get("link") or entry.get("url")
                            if link:
                                fallback.append({
                                    "name": entry.get("name")
                                    or PurePosixPath(urlparse(link).path).name
                                    or f"file_{idx}",
                                    "size": int(entry.get("size", 0) or 0),
                                    "link": link,
                                })
                    file_infos = fallback

                if file_infos:
                    return file_infos
                raise TransientAllDebridStateError(
                    "AllDebrid reported ready but returned no downloadable links"
                )
            except TransientAllDebridStateError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

            if attempt < READY_FILE_RETRIES:
                delay = min(1.0 * attempt, 3.0)
                logger.warning(
                    "Transient ready-state inconsistency for %s (attempt %s/%s, %s): %s",
                    ad_id, attempt, READY_FILE_RETRIES,
                    last_summary or "no status payload", last_error,
                )
                await asyncio.sleep(delay)

        raise TransientAllDebridStateError(
            f"Ready torrent {ad_id} did not expose downloadable links after "
            f"{READY_FILE_RETRIES} attempts ({last_summary or 'no usable status payload'}): "
            f"{last_error}"
        )

'''
    manager = manager.replace(marker, helper + marker, 1)

# Explicit notification boundary.
write("backend/services/notification_service.py", '''"""Application notification boundary for DebridPulse."""
from __future__ import annotations

from typing import Optional

from core.config import get_settings
from services.notifications import NotificationService as DiscordNotificationClient


class NotificationService:
    def client(self) -> Optional[DiscordNotificationClient]:
        cfg = get_settings()
        if not cfg.discord_webhook_url:
            return None
        return DiscordNotificationClient(cfg.discord_webhook_url)
''')
if "    def _engine_notify(self)" not in manager:
    manager = manager.replace("    def notify(self)", "    def _engine_notify(self)", 1)
if "return self._architecture.notifications.client()" not in manager:
    marker = "    def reset_services(self):"
    manager = manager.replace(
        marker,
        '''    def notify(self):
        if self._architecture is not None:
            return self._architecture.notifications.client()
        return self._engine_notify()

''' + marker,
        1,
    )
write(manager_rel, manager)

service_rel = "backend/services/transfer_service.py"
service = read(service_rel)
if "from services.notification_service import NotificationService" not in service:
    service = service.replace(
        "from services.extraction_service import ExtractionService\n",
        "from services.extraction_service import ExtractionService\nfrom services.notification_service import NotificationService\n",
    )
if "self.notifications = NotificationService()" not in service:
    service = service.replace(
        "        self.extraction = ExtractionService()\n",
        "        self.extraction = ExtractionService()\n        self.notifications = NotificationService()\n",
    )
write(service_rel, service)

# Frontend: aria2-only delivery and SQLite-only database management.
app_rel = "frontend/static/app.js"
app = read(app_rel)
app = re.sub(r"\nfunction toggleSymlinkSettings\(val\) \{.*?\n\}\n", "\n", app, count=1, flags=re.S)
app = re.sub(
    r'<select class="input" id="s-download_client".*?</div>\s*(?=<details class="info-details">)',
    '<input class="input" id="s-download_client" value="aria2" disabled/>\n'
    '          <span class="form-hint">DebridPulse delivers unlocked provider links through aria2.</span>\n          ',
    app,
    count=1,
    flags=re.S,
)
app = re.sub(
    r'(<div class="stab-panel" id="tab-database">\s*).*?(?=    <div class="scard">\s*<div class="scard-header">🛠️ Database Maintenance</div>)',
    r'''\1<div class="scard">
      <div class="scard-header">🗄️ Database</div>
      <div class="scard-body">
        <div class="form-group">
          <label class="form-label">Runtime Database</label>
          <input class="input" value="SQLite (internal, WAL)" disabled/>
          <span class="form-hint">SQLite is the authoritative and only runtime database in DebridPulse 1.0.5.</span>
        </div>
      </div>
    </div>

''',
    app,
    count=1,
    flags=re.S,
)
app = re.sub(
    r"\n\s*db_type: t\('db_type'\),.*?postgres_application_name: t\('postgres_application_name'\),",
    "",
    app,
    count=1,
    flags=re.S,
)
app = re.sub(r"\n\s*symlink_path: t\('symlink_path'\),", "", app, count=1)
app = re.sub(r"\nasync function testPostgres\(button\) \{.*?\n\}\n", "\n", app, count=1, flags=re.S)
app = re.sub(
    r"\n\s*if \(button\.id === 'btn-test-postgres'\) \{.*?\n\s*\}",
    "",
    app,
    count=1,
    flags=re.S,
)
# Remove any single-line footer button left for the deleted PostgreSQL test.
app = "\n".join(line for line in app.splitlines() if "btn-test-postgres" not in line) + "\n"
app = re.sub(
    r"setDot\('db',\s*s\.db_type === 'sqlite_fallback'.*?'DB: SQLite'\s*\);",
    "setDot('db', 'ok', 'DB: SQLite');",
    app,
    count=1,
    flags=re.S,
)
write(app_rel, app)

# Route tests now patch the lower-level engine explicitly through TransferService.
direct_rel = "backend/tests/test_direct_links.py"
if p(direct_rel).exists():
    write(direct_rel, read(direct_rel).replace(
        "services.manager_v2.manager",
        "services.transfer_service.transfer_service.engine",
    ))

# SQLite-only schema contract.
schema_rel = "backend/tests/test_database_schema.py"
remove_top_function(schema_rel, "test_postgres_schema_parity")
schema = read(schema_rel)
if "test_runtime_database_is_sqlite_only" not in schema:
    if "from pathlib import Path" not in schema:
        schema = "from pathlib import Path\n" + schema
    schema += '''\n\ndef test_runtime_database_is_sqlite_only():
    source = (Path(__file__).resolve().parents[1] / "db" / "database.py").read_text().lower()
    assert "asyncpg" not in source
    assert "postgres" not in source
'''
write(schema_rel, schema)

# Settings tests now validate the single-store/single-delivery contract.
write("backend/tests/test_settings_semantics.py", '''import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import AppSettings
from core.scheduler import _coerce_int_setting, _stats_report_window_hours
from services import manager_v2


class SchedulerSettingsTests(unittest.TestCase):
    def test_coerce_int_setting_preserves_zero(self):
        self.assertEqual(_coerce_int_setting(0, 10), 0)

    def test_coerce_int_setting_uses_default_for_none(self):
        self.assertEqual(_coerce_int_setting(None, 10), 10)

    def test_coerce_int_setting_uses_default_for_invalid(self):
        self.assertEqual(_coerce_int_setting("invalid", 10), 10)

    def test_stats_report_window_uses_configured_value(self):
        self.assertEqual(_stats_report_window_hours(types.SimpleNamespace(stats_report_window_hours=168)), 168)

    def test_stats_report_window_falls_back_to_default(self):
        self.assertEqual(_stats_report_window_hours(types.SimpleNamespace(stats_report_window_hours=None)), 24)


class AllDebridRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        manager_v2._ad_rate_limiter = manager_v2._TokenBucketRateLimiter(rate=60, window=60.0)

    async def test_rate_limit_zero_means_effectively_unlimited(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=0)
        with patch("services.manager_v2.get_settings", return_value=cfg):
            limiter = await manager_v2._get_ad_rate_limiter()
        self.assertGreaterEqual(limiter._rate, 1_000_000)

    async def test_rate_limit_positive_value_is_respected(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=12)
        with patch("services.manager_v2.get_settings", return_value=cfg):
            limiter = await manager_v2._get_ad_rate_limiter()
        self.assertEqual(limiter._rate, 12)


class SQLiteOnlySettingsTests(unittest.TestCase):
    def test_server_database_fields_are_removed(self):
        cfg = AppSettings()
        for field in ("db_type", "postgres_host", "postgres_port", "postgres_db",
                      "postgres_user", "postgres_password", "postgres_schema",
                      "postgres_ssl", "postgres_application_name"):
            self.assertFalse(hasattr(cfg, field), field)

    def test_delivery_is_aria2_only(self):
        cfg = AppSettings()
        self.assertEqual(cfg.download_client, "aria2")
        self.assertFalse(hasattr(cfg, "symlink_path"))


class SettingsFrontendContractTests(unittest.TestCase):
    def test_active_settings_tab_lookup_is_scoped(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        self.assertIn("document.querySelector('#settings-tabs .stab.active')?.dataset.tab", js)
        self.assertNotIn("document.querySelector('.stab.active')?.dataset.tab", js)

    def test_database_tab_is_sqlite_only(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        self.assertIn("SQLite (internal, WAL)", js)
        for stale in ("s-postgres_host", "s-postgres_password", "btn-test-postgres",
                      "PostgreSQL (external)", "docs/postgresql.md"):
            self.assertNotIn(stale, js)

    def test_stalled_download_recovery_remains_download_scoped(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        general = js.split('id="tab-general"', 1)[1].split('id="tab-download"', 1)[0]
        download = js.split('id="tab-download"', 1)[1].split('id="tab-extract"', 1)[0]
        self.assertNotIn('id="s-stuck_download_timeout_hours"', general)
        self.assertIn('id="s-stuck_download_timeout_hours"', download)
        self.assertIn("Auto-Recover Stalled Downloads", download)
        self.assertIn("regardless of transfer source", download)


if __name__ == "__main__":
    unittest.main()
''')

# Replace v1.0.4 architecture assertions tied to PostgreSQL and runtime patching.
delete("backend/tests/test_v104_performance_architecture.py")
write("backend/tests/test_v105_performance_architecture.py", '''from pathlib import Path

from services.aria2 import Aria2Service

ROOT = Path(__file__).resolve().parents[2]


def source(rel):
    return (ROOT / rel).read_text()


def test_v105_version_and_instrumentation():
    assert (ROOT / "VERSION").read_text().strip() == "1.0.5"
    perf = source("backend/core/performance.py")
    assert "def snapshot()" in perf and "def observe(" in perf


def test_aria2_multicall_and_auth_are_preserved():
    aria2 = source("backend/services/aria2.py")
    assert '"system.multicall"' in aria2
    assert "async def _multicall(" in aria2
    svc = Aria2Service("http://localhost:6800/jsonrpc", secret="secret-value")
    assert svc._authorized_params(["gid"]) == ["token:secret-value", "gid"]


def test_sqlite_hot_indexes_are_preserved():
    db = source("backend/db/database.py")
    for idx in ("idx_dlfiles_queue", "idx_dlfiles_download_id", "idx_torrents_status_priority"):
        assert idx in db
    assert "asyncpg" not in db.lower()


def test_reconciliation_keeps_snapshot_reuse_and_negative_cache():
    src = source("backend/services/reconciliation_service.py")
    for token in ("aria2.scheduler_snapshot_reuse", "confirmed_missing", "aria2.confirm_gid_cache_hits", "_cycle_snapshot"):
        assert token in src


def test_provider_poll_does_not_nest_download_reconciliation():
    manager = source("backend/services/manager_v2.py")
    sync = manager.split("async def sync_alldebrid_status(self):", 1)[1].split("async def deep_sync_aria2_finished", 1)[0]
    assert "sync_download_clients" not in sync


def test_external_aria2_ownership_cache_remains_durable():
    manager = source("backend/services/manager_v2.py")
    assert "self._aria2_owned_gid_cache: Set[str] = set()" in manager
    assert "self._aria2_owned_gid_cache.add(gid)" in manager
    owned = manager.split("async def _aria2_owned_gids", 1)[1].split("async def _aria2_owned_downloads", 1)[0]
    assert "return set(self._aria2_owned_gid_cache)" in owned
    assert "SELECT gid" not in owned


def test_explicit_architecture_replaces_patch_bootstrap():
    manager = source("backend/services/manager_v2.py")
    service = source("backend/services/transfer_service.py")
    control = source("backend/services/transfer_control.py")
    for name in ("TransferControlService", "ReconciliationService", "NotificationService"):
        assert name in service
    assert "bind_architecture" in manager
    assert "_install_transfer_control(manager)" not in manager
    assert "self.manager.pause_torrent =" not in control
''')

# Fix every forgotten async SSE invocation.
routes_rel = "backend/api/routes.py"
routes = read(routes_rel)
routes = re.sub(r"(?m)^(\s*)_sse_broadcast\(", r"\1await _sse_broadcast(", routes)
write(routes_rel, routes)

# Architecture contract includes notification and removed UI scope.
arch_rel = "backend/tests/test_v105_architecture.py"
arch = read(arch_rel)
arch = arch.replace(
    '"TransferControlService", "ReconciliationService", "ExtractionService",',
    '"TransferControlService", "ReconciliationService", "ExtractionService", "NotificationService",',
)
if "test_removed_runtime_scope_is_not_exposed_in_frontend" not in arch:
    arch += '''\n\ndef test_removed_runtime_scope_is_not_exposed_in_frontend():
    js = text("frontend/static/app.js")
    for stale in ("PostgreSQL (external)", "s-postgres_host", "btn-test-postgres", "symlink-settings"):
        assert stale not in js
'''
write(arch_rel, arch)

changed.update({
    manager_rel, service_rel, "backend/services/notification_service.py", app_rel,
    direct_rel, schema_rel, "backend/tests/test_settings_semantics.py",
    "backend/tests/test_v104_performance_architecture.py",
    "backend/tests/test_v105_performance_architecture.py", routes_rel, arch_rel,
})
MANIFEST.write_text("\n".join(sorted(changed)) + "\n", encoding="utf-8")
print("v1.0.5 source-safe seam corrections applied")
