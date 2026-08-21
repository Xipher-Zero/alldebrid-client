from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def replace_count(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new)


# ---------------------------------------------------------------------------
# Frontend: make every known server/persistence-backed HTML sink safe.
# ---------------------------------------------------------------------------
path = "frontend/static/app.js"
text = read(path)

old = r'''function esc(s) {
  // Escape HTML special chars to prevent XSS when inserting user-controlled
  // content (torrent names, filenames, labels) into innerHTML.
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function sourceLabel(source) {'''
new = r'''function esc(s) {
  // Escape HTML special chars to prevent XSS when inserting user-controlled
  // content (torrent names, filenames, labels) into innerHTML.
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function escapeHtmlStrings(value) {
  // Settings and other API payloads are plain data. Escape string leaves
  // before interpolating those payloads into HTML templates; numbers and
  // booleans retain their native types for control-flow and form logic.
  if (Array.isArray(value)) return value.map(escapeHtmlStrings);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, escapeHtmlStrings(item)])
    );
  }
  return typeof value === 'string' ? esc(value) : value;
}

function sourceLabel(source) {'''
text = replace_once(text, old, new, "frontend escapeHtmlStrings helper")
text = replace_once(
    text,
    "  return labels[key] || key || '—';",
    "  return labels[key] || esc(key) || '—';",
    "sourceLabel fallback escape",
)

old = r'''function renderKvMap(arr, formatter) {
  // arr is an array of {status/level, count} objects from the API
  if (!arr || !arr.length) return '<div class="empty">No data available.</div>';
  const entries = Array.isArray(arr)
    ? arr.map(item => {
        const key = item.status ?? item.level ?? item.source ?? Object.keys(item).find(k => k !== 'count') ?? '?';
        return [key, item];
      })
    : Object.entries(arr);
  return `<div class="kv-list">${entries.map(([key, value]) => `
    <div class="kv-row">
      <span>${key}</span>
      <strong>${formatter ? formatter(value, key) : (value && typeof value === 'object' ? value.count ?? '—' : value)}</strong>
    </div>
  `).join('')}</div>`;
}'''
new = r'''function renderKvMap(arr, formatter) {
  // arr is an array of {status/level, count} objects from the API
  if (!arr || !arr.length) return '<div class="empty">No data available.</div>';
  const entries = Array.isArray(arr)
    ? arr.map(item => {
        const key = item.status ?? item.level ?? item.source ?? Object.keys(item).find(k => k !== 'count') ?? '?';
        return [key, item];
      })
    : Object.entries(arr);
  return `<div class="kv-list">${entries.map(([key, value]) => {
    const rendered = formatter
      ? formatter(value, key)
      : (value && typeof value === 'object' ? value.count ?? '—' : value);
    return `
    <div class="kv-row">
      <span>${esc(key)}</span>
      <strong>${esc(rendered)}</strong>
    </div>`;
  }).join('')}</div>`;
}'''
text = replace_once(text, old, new, "renderKvMap escaping")

old = r'''function badge(s) {
  const m = {pending:'⏳ Pending',uploading:'⬆ Uploading',processing:'⚙ Processing',
    queued:'🕓 Queued',paused:'⏸ Paused',downloading:'⬇ Downloading',ready:'✓ Ready',completed:'✅ Done',
    downloading_with_errors:'⬇ Downloading',
    completed_with_errors:'⚠ Completed with errors',
    error:'❌ Error',missing:'❌ Missing file',provider_failed:'❌ Provider download failed',
    provider_missing:'❌ Removed from provider',failed:'❌ Provider download failed',
    deleted:'🗑 Deleted',imported:'📋 Imported',partial:'⚠ Partial'};
  const cls = s === 'missing' || s === 'provider_failed' || s === 'provider_missing' || s === 'failed'
    ? 'error'
    : s === 'completed_with_errors' || s === 'downloading_with_errors'
      ? 'partial'
      : s;
  return `<span class="badge badge-${cls}">${m[s]||s}</span>`;
}'''
new = r'''function badge(s) {
  const m = {pending:'⏳ Pending',uploading:'⬆ Uploading',processing:'⚙ Processing',
    queued:'🕓 Queued',paused:'⏸ Paused',downloading:'⬇ Downloading',ready:'✓ Ready',completed:'✅ Done',
    downloading_with_errors:'⬇ Downloading',
    completed_with_errors:'⚠ Completed with errors',
    error:'❌ Error',missing:'❌ Missing file',provider_failed:'❌ Provider download failed',
    provider_missing:'❌ Removed from provider',failed:'❌ Provider download failed',
    deleted:'🗑 Deleted',imported:'📋 Imported',partial:'⚠ Partial'};
  const key = String(s || '');
  const requestedCls = key === 'missing' || key === 'provider_failed' || key === 'provider_missing' || key === 'failed'
    ? 'error'
    : key === 'completed_with_errors' || key === 'downloading_with_errors'
      ? 'partial'
      : key;
  const cls = /^[a-z0-9_-]+$/i.test(requestedCls) ? requestedCls : 'unknown';
  return `<span class="badge badge-${cls}">${esc(m[key] || key || 'Unknown')}</span>`;
}'''
text = replace_once(text, old, new, "badge escaping")
text = replace_once(
    text,
    "  const s = settingsData;",
    "  const s = escapeHtmlStrings(settingsData || {});",
    "settings render escape boundary",
)

for old, new, label in (
    ("${t.download_client||'aria2'}", "${esc(t.download_client||'aria2')}", "detail download client"),
    ("${t.alldebrid_id||'—'}", "${esc(t.alldebrid_id||'—')}", "detail alldebrid id"),
    ("${t.hash||'—'}", "${esc(t.hash||'—')}", "detail hash"),
    ("${t.local_path}", "${esc(t.local_path)}", "detail local path"),
    ("Failed to load details: ${sanitizeErrorMsg(e.message)}", "Failed to load details: ${esc(sanitizeErrorMsg(e.message))}", "detail error"),
):
    text = replace_once(text, old, new, label)
text = replace_count(
    text,
    'class="elevel ${ev.level}"',
    'class="elevel ${esc(ev.level)}"',
    2,
    "event level class escaping",
)

old = r'''  function dbg(msg) {
    const el = document.getElementById('debug-status');
    if (!el) return;
    el.style.display = 'block';
    el.innerHTML += '<div>' + new Date().toLocaleTimeString() + ' — ' + msg + '</div>';
  }'''
new = r'''  function dbg(msg) {
    const el = document.getElementById('debug-status');
    if (!el) return;
    el.style.display = 'block';
    const row = document.createElement('div');
    row.textContent = new Date().toLocaleTimeString() + ' — ' + String(msg ?? '');
    el.appendChild(row);
  }'''
text = replace_once(text, old, new, "debug output DOM safety")

text = replace_count(text, "<span>${b.name}</span>", "<span>${esc(b.name)}</span>", 2, "backup name escaping")
text = replace_count(
    text,
    "${b.files.join(', ')} — ${Math.round(b.size_bytes/1024)} KB",
    "${esc((b.files||[]).join(', '))} — ${Math.round(Number(b.size_bytes||0)/1024)} KB",
    2,
    "backup file list escaping",
)
text = replace_once(
    text,
    "${r.daily_trend.map(d=>`${d.date}: ${d.cnt}`).join(' · ')}",
    "${r.daily_trend.map(d=>`${esc(d.date)}: ${Number(d.cnt)||0}`).join(' · ')}",
    "daily trend escaping",
)
text = replace_once(
    text,
    "${Object.entries(t.sources||{}).map(([k,v])=>`${k}: ${v}`).join(', ')}",
    "${Object.entries(t.sources||{}).map(([k,v])=>`${esc(k)}: ${Number(v)||0}`).join(', ')}",
    "stats source escaping",
)
text = replace_once(
    text,
    'el.innerHTML = `<span style="color:var(--red)">✗ ${e.message}</span>`;',
    'el.innerHTML = `<span style="color:var(--red)">✗ ${esc(e.message)}</span>`;',
    "comprehensive stats error escape",
)
text = replace_once(
    text,
    "`max-download-result: ${opts['max-download-result'] || 'n/a'} · keep-unfinished-download-result: ${opts['keep-unfinished-download-result'] || 'n/a'}<br>` +",
    "`max-download-result: ${esc(opts['max-download-result'] || 'n/a')} · keep-unfinished-download-result: ${esc(opts['keep-unfinished-download-result'] || 'n/a')}<br>` +",
    "aria2 diagnostic option escaping",
)
text = replace_once(
    text,
    '  return `<span class="badge badge-${cls}">${map[status] || status || \'Unknown\'}</span>`;',
    '  return `<span class="badge badge-${cls}">${esc(map[status] || status || \'Unknown\')}</span>`;',
    "aria2 status fallback escaping",
)
text = replace_once(
    text,
    "    var hour = item.hour ? item.hour.substring(11, 16) : '';",
    "    var hour = esc(item.hour ? item.hour.substring(11, 16) : '');",
    "hourly chart label escaping",
)
text = replace_once(
    text,
    "'<b style=\"color:var(--green)\">&#10003; ' + d.message + '</b><br>' +",
    "'<b style=\"color:var(--green)\">&#10003; ' + esc(d.message) + '</b><br>' +",
    "page-cache message escaping",
)

for forbidden in (
    "const s = settingsData;",
    "innerHTML += '<div>' + new Date().toLocaleTimeString()",
    "Failed to load details: ${sanitizeErrorMsg(e.message)}",
    "<span>${b.name}</span>",
    "${b.files.join(', ')}",
    "✗ ${e.message}</span>",
    "${t.local_path}",
):
    if forbidden in text:
        raise SystemExit(f"frontend unsafe pattern remains: {forbidden}")

write(path, text)


# ---------------------------------------------------------------------------
# DB-wide maintenance admission gate. Existing sessions drain; new sessions
# fail closed so stale work cannot queue behind a wipe and repopulate tables.
# ---------------------------------------------------------------------------
path = "backend/db/database.py"
text = read(path)
text = replace_once(
    text,
    "import logging\nimport os\nimport time\nfrom contextlib import asynccontextmanager",
    "import asyncio\nimport logging\nimport os\nimport time\nfrom contextlib import asynccontextmanager",
    "database asyncio import",
)

marker = "DB_PATH = _default_sqlite_path()\n\n\nclass _CursorWrapper:"
insert = '''DB_PATH = _default_sqlite_path()


class DatabaseMaintenanceActive(RuntimeError):
    """Raised when a non-maintenance task attempts DB access during maintenance."""


class DatabaseMaintenanceGate:
    """Exclusive destructive-maintenance gate for SQLite sessions.

    Maintenance flips admission closed before waiting for existing get_db()
    sessions to drain. New sessions from other tasks fail immediately instead
    of waiting and later replaying stale pre-wipe work after the database has
    been cleared. The maintenance owner itself may open DB sessions for the
    verified backup and wipe transaction.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_sessions = 0
        self._maintenance_active = False
        self._owner: asyncio.Task | None = None

    @property
    def active(self) -> bool:
        return self._maintenance_active

    @asynccontextmanager
    async def session(self):
        current = asyncio.current_task()
        counted = False
        async with self._condition:
            if self._maintenance_active and current is not self._owner:
                raise DatabaseMaintenanceActive("Database maintenance is in progress")
            if current is not self._owner:
                self._active_sessions += 1
                counted = True
        try:
            yield
        finally:
            if counted:
                async with self._condition:
                    self._active_sessions = max(0, self._active_sessions - 1)
                    if self._active_sessions == 0:
                        self._condition.notify_all()

    @asynccontextmanager
    async def maintenance(self):
        current = asyncio.current_task()
        async with self._condition:
            if self._maintenance_active:
                raise DatabaseMaintenanceActive("Database maintenance is already in progress")
            self._maintenance_active = True
            self._owner = current
            while self._active_sessions:
                await self._condition.wait()
        try:
            yield
        finally:
            async with self._condition:
                self._owner = None
                self._maintenance_active = False
                self._condition.notify_all()


database_maintenance_gate = DatabaseMaintenanceGate()


def database_maintenance():
    return database_maintenance_gate.maintenance()


class _CursorWrapper:'''
text = replace_once(text, marker, insert, "database maintenance gate insertion")

old = '''@asynccontextmanager
async def get_db() -> AsyncIterator[_DbConnection]:
    started = time.monotonic()
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await _configure_sqlite_connection(conn)
        _db_metrics["sqlite_acquires"] += 1
        _db_metrics["wait_seconds"] += max(0.0, time.monotonic() - started)
        yield _DbConnection(conn)'''
new = '''@asynccontextmanager
async def get_db() -> AsyncIterator[_DbConnection]:
    async with database_maintenance_gate.session():
        started = time.monotonic()
        async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
            await _configure_sqlite_connection(conn)
            _db_metrics["sqlite_acquires"] += 1
            _db_metrics["wait_seconds"] += max(0.0, time.monotonic() - started)
            yield _DbConnection(conn)'''
text = replace_once(text, old, new, "get_db maintenance gate")
text = replace_once(text, "source TEXT DEFAULT 'watch',", "source TEXT DEFAULT '',", "safe unknown source default")
write(path, text)


# Scheduler lifecycle helper.
path = "backend/core/scheduler.py"
text = read(path)
old = '''async def start_scheduler():
    if any(not task.done() for task in _tasks):
        logger.debug("Scheduler already running")
        return'''
new = '''def scheduler_running() -> bool:
    return any(not task.done() for task in _tasks)


async def start_scheduler():
    if scheduler_running():
        logger.debug("Scheduler already running")
        return'''
text = replace_once(text, old, new, "scheduler running helper")
write(path, text)


# Wipe route: stop scheduler, drain provider/materialization, then hold DB gate.
path = "backend/api/routes.py"
text = read(path)
text = replace_once(text, "from db.database import DB_PATH, get_db", "from db.database import DB_PATH, database_maintenance, get_db", "routes database maintenance import")
text = replace_once(
    text,
    "from core.version import normalize_version_tag, read_version\nfrom db.database",
    "from core.version import normalize_version_tag, read_version\nfrom core import scheduler as scheduler_runtime\nfrom db.database",
    "routes scheduler import",
)
text = replace_once(
    text,
    '@router.post("/admin/database/wipe")\nasync def wipe_database_admin(body: dict | None = None):',
    '_database_wipe_lock = asyncio.Lock()\n\n\n@router.post("/admin/database/wipe")\nasync def wipe_database_admin(body: dict | None = None):',
    "database wipe lock",
)
old = '''    quiesced = False
    try:
        try:
            quiesce_result = await transfer_service.quiesce_for_database_wipe()
            quiesced = True
        except Exception as exc:
            raise HTTPException(409, _sanitize_error(exc))

        backup_result = None
        if getattr(cfg, "db_backup_before_wipe", True):
            from services.db_maintenance import run_database_backup
            backup_result = await run_database_backup()
            if backup_result.get("skipped"):
                raise HTTPException(409, "Pre-wipe database backup is required but disabled")
            if backup_result.get("errors"):
                raise HTTPException(500, "Pre-wipe database backup failed; wipe aborted")

        from services.db_maintenance import wipe_database
        result = await wipe_database(verified_quiesced=True)
        return {**result, "backup": backup_result, "quiesced": quiesce_result}
    finally:
        if quiesced:
            await transfer_service.release_database_wipe_quiescence()'''
new = '''    if _database_wipe_lock.locked():
        raise HTTPException(409, "Database wipe is already in progress")

    async with _database_wipe_lock:
        scheduler_was_running = scheduler_runtime.scheduler_running()
        quiesced = False
        try:
            if scheduler_was_running:
                await scheduler_runtime.stop_scheduler()

            try:
                quiesce_result = await transfer_service.quiesce_for_database_wipe()
                quiesced = True
            except Exception as exc:
                raise HTTPException(409, _sanitize_error(exc))

            # Provider/materialization work is drained and scheduler admission is
            # stopped before this point. The DB gate now drains request-side
            # sessions already open and rejects new non-owner sessions. Stale
            # work therefore cannot wait through the wipe and repopulate it.
            async with database_maintenance():
                backup_result = None
                if getattr(cfg, "db_backup_before_wipe", True):
                    from services.db_maintenance import run_database_backup
                    backup_result = await run_database_backup()
                    if backup_result.get("skipped"):
                        raise HTTPException(409, "Pre-wipe database backup is required but disabled")
                    if backup_result.get("errors"):
                        raise HTTPException(500, "Pre-wipe database backup failed; wipe aborted")

                from services.db_maintenance import wipe_database
                result = await wipe_database(verified_quiesced=True)

            return {**result, "backup": backup_result, "quiesced": quiesce_result}
        finally:
            if quiesced:
                await transfer_service.release_database_wipe_quiescence()
            if scheduler_was_running:
                await scheduler_runtime.start_scheduler()'''
text = replace_once(text, old, new, "database wipe DB-wide quiescence")
write(path, text)


# Clean HTTP behavior for requests rejected during exclusive maintenance.
path = "backend/main.py"
text = read(path)
text = replace_once(text, "from db.database import init_db, DB_PATH", "from db.database import DatabaseMaintenanceActive, init_db, DB_PATH", "main maintenance exception import")
old = '''@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, _exc: PermissionError):
    """Do not turn service-layer authorization failures into HTTP 500 responses."""
    return Response(content="Forbidden", status_code=403)


app.add_middleware'''
new = '''@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, _exc: PermissionError):
    """Do not turn service-layer authorization failures into HTTP 500 responses."""
    return Response(content="Forbidden", status_code=403)


@app.exception_handler(DatabaseMaintenanceActive)
async def database_maintenance_handler(_request: Request, _exc: DatabaseMaintenanceActive):
    """Fail closed rather than queue stale request work behind a destructive wipe."""
    return Response(
        content="Database maintenance in progress",
        status_code=503,
        headers={"Retry-After": "2"},
    )


app.add_middleware'''
text = replace_once(text, old, new, "main maintenance exception handler")
write(path, text)


# Provider deletion ownership: explicit whitelist rather than a denylist.
path = "backend/services/manager_v2.py"
text = read(path)
text = replace_once(
    text,
    'DIRECT_LINK_SOURCE = "direct_link"\nDEFERRED_PROVIDER_STATUS = "deferred"',
    'DIRECT_LINK_SOURCE = "direct_link"\n_PROVIDER_DELETE_OWNED_SOURCES = frozenset({"manual", "manual_file", "api"})\nDEFERRED_PROVIDER_STATUS = "deferred"',
    "owned provider source set",
)
old = '''    @staticmethod
    def _provider_delete_authorized(source: object) -> bool:
        """Automatic provider deletion requires positive local ownership evidence."""
        normalized = str(source or "").strip()
        return bool(normalized) and normalized not in {"alldebrid_existing", "import_existing"}'''
new = '''    @staticmethod
    def _provider_delete_authorized(source: object) -> bool:
        """Automatic provider deletion requires explicit local-creation provenance."""
        normalized = str(source or "").strip()
        return normalized in _PROVIDER_DELETE_OWNED_SOURCES'''
text = replace_once(text, old, new, "provider ownership whitelist")
text = text.replace(
    "self._disk_guard_active: bool = False          # True = guard triggered, downloads paused",
    "self._disk_guard_active: bool = False          # True = guard triggered, new dispatches deferred",
)
text = text.replace(
    "          - Pauses all active aria2 downloads (stores GIDs in _disk_guard_paused)\n          - Blocks new downloads until space recovers",
    "          - Allows active aria2 downloads to finish normally\n          - Blocks new downloads until space recovers",
)
text = text.replace("          - Resumes all previously paused GIDs", "          - Allows deferred dispatch to resume")
write(path, text)


path = "backend/services/extractor.py"
text = read(path)
text = replace_once(
    text,
    "  3. System binary `unrar-free` as last-resort RAR fallback",
    "  3. RAR extraction fails closed unless a 7z-compatible binary is available",
    "extractor stale unrar documentation",
)
write(path, text)


path = "CHANGELOG.md"
text = read(path)
text = replace_once(
    text,
    "- Hardened database wipe with verified transfer quiescence and fail-closed pre-wipe backup requirements.",
    "- Hardened database wipe with provider/materialization drain, scheduler suspension, an exclusive fail-closed database maintenance gate, and required pre-wipe backup verification.",
    "changelog database wipe wording",
)
write(path, text)


path = "SECURITY.md"
text = read(path)
text = replace_once(
    text,
    "Database wipe requires verified transfer quiescence and fails closed if a required pre-wipe backup fails. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.",
    "Database wipe drains provider/materialization work, suspends scheduler writers, then holds an exclusive database-maintenance gate that rejects concurrent non-owner DB sessions; it also fails closed if a required pre-wipe backup fails. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.",
    "security database maintenance wording",
)
write(path, text)


# Regression coverage for both blockers plus the ownership hardening note.
path = "backend/tests/test_v106_corrective_regressions.py"
text = read(path)
text = replace_once(
    text,
    "import asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\nfrom unittest.mock import AsyncMock\n\nimport pytest",
    "import asyncio\nfrom contextlib import asynccontextmanager\nfrom pathlib import Path\nimport shutil\nimport subprocess\nfrom types import SimpleNamespace\nfrom unittest.mock import AsyncMock\n\nimport pytest",
    "corrective test imports",
)
text = replace_once(
    text,
    '''    assert TorrentManager._provider_delete_authorized("alldebrid_existing") is False
    assert TorrentManager._provider_delete_authorized("import_existing") is False
    assert TorrentManager._provider_delete_authorized("") is False
    assert TorrentManager._provider_delete_authorized(None) is False''',
    '''    assert TorrentManager._provider_delete_authorized("api") is True
    assert TorrentManager._provider_delete_authorized("alldebrid_existing") is False
    assert TorrentManager._provider_delete_authorized("import_existing") is False
    assert TorrentManager._provider_delete_authorized("watch") is False
    assert TorrentManager._provider_delete_authorized("future-arbitrary-source") is False
    assert TorrentManager._provider_delete_authorized("") is False
    assert TorrentManager._provider_delete_authorized(None) is False''',
    "provider whitelist regression",
)
old = '''def test_database_wipe_route_releases_quiescence_in_finally():
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text()
    block = routes.split('async def wipe_database_admin', 1)[1].split('# ── Statistics & Reporting', 1)[0]
    assert "quiesce_for_database_wipe" in block
    assert "finally:" in block
    assert "release_database_wipe_quiescence" in block
'''
new = '''@pytest.mark.asyncio
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
'''
text = replace_once(text, old, new, "database wipe regression tests")

old = '''def test_frontend_xss_and_secret_contracts():
    root = Path(__file__).resolve().parents[2]
    js = (root / "frontend/static/app.js").read_text()
    html = (root / "frontend/static/index.html").read_text()
    toast = js.split("function toast", 1)[1].split("function setButtonPending", 1)[0]
    assert "innerHTML" not in toast
    assert "text.textContent = String(msg ?? '')" in toast
    assert "${esc(ev.torrent_name)}" in js
    assert "auth_username: t('auth_username')" in js
    assert "auth_password: t('auth_password')" in js
    assert "clear_secrets: clearSecrets" in js
    assert "alldebrid_api_key_configured" in js
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js" not in html
    assert '/vendor/chart.umd.min.js?v=4.4.1' in html
'''
new = '''def test_frontend_xss_and_secret_contracts():
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
const payload = '\"><img src=x onerror=globalThis.__xss=1>';
const escaped = esc(payload);
if (escaped.includes('<img') || escaped.includes('\">')) {
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
  if (value.includes('<img') || value.includes('\">')) {
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
'''
text = replace_once(text, old, new, "frontend XSS regression expansion")
text += '''\n\ndef test_sqlite_default_source_is_not_legacy_watch_authority():\n    database = (Path(__file__).resolve().parents[1] / "db" / "database.py").read_text()\n    assert "source TEXT DEFAULT 'watch'" not in database\n    assert "source TEXT DEFAULT ''" in database\n'''
write(path, text)

print("v1.0.6 follow-up corrective patch applied")
