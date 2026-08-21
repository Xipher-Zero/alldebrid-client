import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_provider_quiescence_waits_for_inflight_operation():
    from services.provider_gateway import ProviderGateway

    started = asyncio.Event()
    release = asyncio.Event()

    async def add_magnet_direct(magnet, source="manual"):
        started.set()
        await release.wait()
        return {"ok": True}

    engine = SimpleNamespace(add_magnet_direct=add_magnet_direct)
    gateway = ProviderGateway(engine)
    operation = asyncio.create_task(gateway.add_magnet("magnet:?xt=urn:btih:test"))
    await started.wait()
    quiesce = asyncio.create_task(gateway.begin_quiescence())
    await asyncio.sleep(0)
    assert not quiesce.done()
    release.set()
    await operation
    await quiesce
    with pytest.raises(RuntimeError, match="quiesced"):
        await gateway.add_magnet("magnet:?xt=urn:btih:blocked")
    await gateway.end_quiescence()


def test_provider_delete_requires_positive_local_ownership():
    from services.manager_v2 import TorrentManager

    assert TorrentManager._provider_delete_authorized("manual") is True
    assert TorrentManager._provider_delete_authorized("manual_file") is True
    assert TorrentManager._provider_delete_authorized("api") is True
    assert TorrentManager._provider_delete_authorized("alldebrid_existing") is False
    assert TorrentManager._provider_delete_authorized("import_existing") is False
    assert TorrentManager._provider_delete_authorized("watch") is False
    assert TorrentManager._provider_delete_authorized("future-arbitrary-source") is False
    assert TorrentManager._provider_delete_authorized("") is False
    assert TorrentManager._provider_delete_authorized(None) is False


def test_orphan_cleanup_never_treats_unknown_as_delete_authority():
    source = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()
    block = source.split("async def cleanup_alldebrid_orphans", 1)[1].split("async def _apply_provider_update", 1)[0]
    assert "local is None" in block
    assert "_provider_delete_authorized" in block
    assert "local is None" in block
    assert "not self._provider_delete_authorized" in block
    assert block.index("local is None") < block.index("delete_magnet(ad_id)")
    assert "preserving unowned/unknown provider object" in block


@pytest.mark.asyncio
async def test_database_maintenance_gate_drains_existing_and_rejects_new_sessions():
    from db.database import DatabaseMaintenanceActive, DatabaseMaintenanceGate

    gate = DatabaseMaintenanceGate()
    reader_started = asyncio.Event()
    release_reader = asyncio.Event()
    maintenance_entered = asyncio.Event()
    release_maintenance = asyncio.Event()

    async def reader():
        async with gate.session():
            reader_started.set()
            await release_reader.wait()

    async def maintainer():
        async with gate.maintenance():
            maintenance_entered.set()
            await release_maintenance.wait()

    reader_task = asyncio.create_task(reader())
    await reader_started.wait()
    maintenance_task = asyncio.create_task(maintainer())
    await asyncio.sleep(0)
    assert not maintenance_entered.is_set()

    release_reader.set()
    await reader_task
    await maintenance_entered.wait()

    async def blocked_session():
        async with gate.session():
            return True

    with pytest.raises(DatabaseMaintenanceActive, match="maintenance"):
        await blocked_session()

    release_maintenance.set()
    await maintenance_task

    async with gate.session():
        pass


@pytest.mark.asyncio
async def test_database_wipe_suspends_scheduler_and_holds_exclusive_gate(monkeypatch):
    import api.routes as routes
    import services.db_maintenance as db_maintenance

    calls = []
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            db_wipe_enabled=True,
            paused=True,
            db_backup_before_wipe=False,
        ),
    )
    monkeypatch.setattr(routes.scheduler_runtime, "scheduler_running", lambda: True)

    async def stop_scheduler():
        calls.append("scheduler-stop")

    async def start_scheduler():
        calls.append("scheduler-start")

    async def quiesce():
        calls.append("transfer-quiesce")
        return {"ok": True}

    async def release():
        calls.append("transfer-release")

    @asynccontextmanager
    async def maintenance():
        calls.append("db-gate-enter")
        try:
            yield
        finally:
            calls.append("db-gate-exit")

    async def wipe_database(*, verified_quiesced=False):
        assert verified_quiesced is True
        calls.append("wipe")
        return {"ok": True, "wiped_tables": []}

    monkeypatch.setattr(routes.scheduler_runtime, "stop_scheduler", stop_scheduler)
    monkeypatch.setattr(routes.scheduler_runtime, "start_scheduler", start_scheduler)
    monkeypatch.setattr(routes.transfer_service, "quiesce_for_database_wipe", quiesce)
    monkeypatch.setattr(routes.transfer_service, "release_database_wipe_quiescence", release)
    monkeypatch.setattr(routes, "database_maintenance", maintenance)
    monkeypatch.setattr(db_maintenance, "wipe_database", wipe_database)

    result = await routes.wipe_database_admin({"confirm": True})
    assert result["ok"] is True
    assert calls == [
        "scheduler-stop",
        "transfer-quiesce",
        "db-gate-enter",
        "wipe",
        "db-gate-exit",
        "transfer-release",
        "scheduler-start",
    ]


def test_database_wipe_route_releases_quiescence_in_finally():
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text()
    block = routes.split('async def wipe_database_admin', 1)[1].split('# ── Statistics & Reporting', 1)[0]
    assert "scheduler_runtime.stop_scheduler" in block
    assert "database_maintenance()" in block
    assert "quiesce_for_database_wipe" in block
    assert "finally:" in block
    assert "release_database_wipe_quiescence" in block
    assert "scheduler_runtime.start_scheduler" in block


def test_settings_secret_merge_preserve_replace_clear():
    from api.routes import SettingsUpdate, _merge_secret_settings
    from core.config import AppSettings

    previous = AppSettings(alldebrid_api_key="old-key", auth_username="old-user", auth_password="old-pass")

    payload = previous.model_dump()
    payload.update(alldebrid_api_key="", auth_password="")
    preserve = SettingsUpdate(**payload)
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    payload = previous.model_dump()
    payload.update(auth_username="new-user", auth_password="new-pass")
    replace = SettingsUpdate(**payload)
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    payload = previous.model_dump()
    payload.update(auth_password="", clear_secrets=["auth_password"])
    clear = SettingsUpdate(**payload)
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    payload = previous.model_dump()
    payload.update(clear_secrets=["not_a_secret"])
    with pytest.raises(Exception):
        _merge_secret_settings(SettingsUpdate(**payload), previous)


def test_frontend_xss_and_secret_contracts():
    root = Path(__file__).resolve().parents[2]
    js = (root / "frontend/static/app.js").read_text()
    html = (root / "frontend/static/index.html").read_text()
    toast = js.split("function toast", 1)[1].split("function setButtonPending", 1)[0]
    settings = js.split("function renderSettings()", 1)[1].split("function switchSettingsTab", 1)[0]
    details = js.split("async function showDetail", 1)[1].split("function closeModal", 1)[0]
    assert "innerHTML" not in toast
    assert "text.textContent = String(msg ?? '')" in toast
    assert "const s = escapeHtmlStrings(settingsData || {});" in settings
    assert "const s = settingsData;" not in settings
    assert "${esc(ev.torrent_name)}" in js
    assert 'class="elevel ${esc(ev.level)}"' in js
    assert "Failed to load details: ${esc(sanitizeErrorMsg(e.message))}" in details
    assert "${esc(t.local_path)}" in details
    assert "${esc(t.hash||'—')}" in details
    assert "${esc(t.alldebrid_id||'—')}" in details
    assert "return labels[key] || esc(key) || '—';" in js
    assert "${esc(m[key] || key || 'Unknown')}" in js
    assert "<span>${esc(key)}</span>" in js
    assert "auth_username: t('auth_username')" in js
    assert "auth_password: t('auth_password')" in js
    assert "clear_secrets: clearSecrets" in js
    assert "alldebrid_api_key_configured" in js
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js" not in html
    assert '/vendor/chart.umd.min.js?v=4.4.1' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_frontend_escape_helpers_execute_against_malicious_payload():
    root = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('frontend/static/app.js', 'utf8');
const start = source.indexOf('function esc(s)');
const end = source.indexOf('function sanitizeErrorMsg', start);
if (start < 0 || end < 0) throw new Error('escape helper block not found');
eval(source.slice(start, end));
const payload = '"><img src=x onerror=globalThis.__xss=1>';
const escaped = esc(payload);
if (escaped.includes('<img') || escaped.includes('">')) {
  throw new Error('esc() left executable markup');
}
const settings = escapeHtmlStrings({
  auth_username: payload,
  nested: {path: payload},
  list: [payload],
  enabled: true,
  count: 7,
});
for (const value of [settings.auth_username, settings.nested.path, settings.list[0]]) {
  if (value.includes('<img') || value.includes('">')) {
    throw new Error('escapeHtmlStrings() left executable markup');
  }
}
if (settings.enabled !== true || settings.count !== 7) {
  throw new Error('escapeHtmlStrings() changed non-string types');
}
if (sourceLabel(payload).includes('<img')) {
  throw new Error('sourceLabel() returned raw unknown source');
}
"""
    subprocess.run(["node", "-e", script], cwd=root, check=True)


def test_bulk_actions_are_schema_limited():
    from api.routes import BulkAction
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BulkAction(ids=[1], action="nonsense")


def test_codeql_covers_browser_javascript():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/codeql.yml").read_text()
    assert "javascript-typescript" in workflow


def test_dependency_docs_match_removed_runtime_components():
    root = Path(__file__).resolve().parents[2]
    docs = (root / "docs/DEPENDENCY_LICENSES.md").read_text()
    requirements = (root / "backend/requirements.txt").read_text().lower()
    dockerfile = (root / "Dockerfile").read_text().lower()
    assert "asyncpg" not in requirements
    assert "| asyncpg |" not in docs
    assert "unrar-free" not in dockerfile
    assert "| unrar-free |" not in docs
    assert "Chart.js | 4.4.1, vendored" in docs
    assert (root / "licenses/Chart.js-MIT.txt").is_file()
    assert (root / "frontend/static/vendor/chart.umd.min.js").is_file()


def test_sqlite_default_source_is_not_legacy_watch_authority():
    database = (Path(__file__).resolve().parents[1] / "db" / "database.py").read_text()
    assert "source TEXT DEFAULT 'watch'" not in database
    assert "source TEXT DEFAULT ''" in database
