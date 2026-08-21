from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected >= {minimum} matches, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new))


# 1) Canonical UTC API timestamps + configured-TZ presentation/statistics.
replace_once(
    "backend/api/serializers.py",
    "from collections.abc import Mapping, Sequence\nfrom typing import Any\n",
    "from collections.abc import Mapping, Sequence\nfrom datetime import datetime, timezone\nimport re\nfrom typing import Any\n",
)
replace_once(
    "backend/api/serializers.py",
    '''_CAPABILITY_FIELDS = _TORRENT_PRIVATE_FIELDS | _FILE_PRIVATE_FIELDS\n\n\ndef _without_fields(value: Mapping[str, Any], private_fields: frozenset[str]) -> dict[str, Any]:\n    return {key: item for key, item in dict(value).items() if key not in private_fields}\n''',
    '''_CAPABILITY_FIELDS = _TORRENT_PRIVATE_FIELDS | _FILE_PRIVATE_FIELDS\n_NAIVE_UTC_RE = re.compile(r"^\\d{4}-\\d{2}-\\d{2}[ T]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?$")\n\n\ndef _public_timestamp(value: Any) -> Any:\n    """Serialize SQLite UTC timestamp values with an explicit UTC designator."""\n    if isinstance(value, datetime):\n        if value.tzinfo is None:\n            value = value.replace(tzinfo=timezone.utc)\n        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")\n    if isinstance(value, str):\n        stripped = value.strip()\n        if _NAIVE_UTC_RE.fullmatch(stripped):\n            return stripped.replace(" ", "T") + "Z"\n    return value\n\n\ndef _public_field(key: str, value: Any) -> Any:\n    return _public_timestamp(value) if key.endswith("_at") else value\n\n\ndef _without_fields(value: Mapping[str, Any], private_fields: frozenset[str]) -> dict[str, Any]:\n    return {\n        key: _public_field(key, item)\n        for key, item in dict(value).items()\n        if key not in private_fields\n    }\n''',
)
replace_once(
    "backend/api/serializers.py",
    '''        return {\n            key: public_payload(item)\n            for key, item in value.items()\n            if key not in _CAPABILITY_FIELDS\n        }\n''',
    '''        return {\n            key: _public_field(key, public_payload(item))\n            for key, item in value.items()\n            if key not in _CAPABILITY_FIELDS\n        }\n''',
)
replace_once(
    "backend/api/routes.py",
    '''def _sql_strftime(fmt: str, field: str) -> str:\n    return f"strftime('{fmt}', {field})"\n\n\ndef _sql_date(field: str) -> str:\n    return f"DATE({field})"\n''',
    '''def _sql_strftime(fmt: str, field: str) -> str:\n    # SQLite stores canonical UTC clock values; calendar buckets are operator-local.\n    return f"strftime('{fmt}', {field}, 'localtime')"\n\n\ndef _sql_date(field: str) -> str:\n    return f"DATE({field}, 'localtime')"\n''',
)
replace_once(
    "backend/api/routes.py",
    '    data["database_backend"] = "sqlite"\n    return data\n',
    '    data["database_backend"] = "sqlite"\n    data["timezone"] = (os.getenv("TZ", "UTC") or "UTC").strip() or "UTC"\n    return data\n',
)
replace_all(
    "backend/services/stats.py",
    "SELECT DATE(completed_at) AS date, COUNT(*) AS cnt,",
    "SELECT DATE(completed_at, 'localtime') AS date, COUNT(*) AS cnt,",
)
replace_all(
    "backend/services/stats.py",
    "GROUP BY DATE(completed_at)",
    "GROUP BY DATE(completed_at, 'localtime')",
)
replace_once(
    "frontend/static/app.js",
    "/* DebridPulse — Multi-provider Debrid Download Manager */",
    "/* DebridPulse — AllDebrid + aria2 download manager */",
)
replace_once(
    "frontend/static/app.js",
    '''function fmtDate(d) {\n  if (!d) return '—';\n  const x = new Date(d);\n  // Use en-GB for consistent DD.MM HH:MM format regardless of browser locale\n  const dateStr = x.toLocaleDateString('en-GB',{day:'2-digit',month:'2-digit'}).replace('/','.').replace('/','.');\n  const timeStr = x.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false});\n  return dateStr + ' ' + timeStr;\n}\n''',
    '''function parseApiDate(d) {\n  if (!d) return null;\n  let value = d;\n  // SQLite CURRENT_TIMESTAMP is canonical UTC but historically serialized as a\n  // naive "YYYY-MM-DD HH:MM:SS" string. Treat that legacy form as UTC.\n  if (typeof value === 'string' && /^\\d{4}-\\d{2}-\\d{2}[ T]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?$/.test(value.trim())) {\n    value = value.trim().replace(' ', 'T') + 'Z';\n  }\n  const parsed = new Date(value);\n  return Number.isNaN(parsed.getTime()) ? null : parsed;\n}\nfunction fmtDate(d) {\n  const x = parseApiDate(d);\n  if (!x) return '—';\n  const timeZone = String((settingsData && settingsData.timezone) || '').trim() || undefined;\n  const dateOptions = {day:'2-digit',month:'2-digit'};\n  const timeOptions = {hour:'2-digit',minute:'2-digit',hour12:false};\n  if (timeZone) {\n    dateOptions.timeZone = timeZone;\n    timeOptions.timeZone = timeZone;\n  }\n  // Use en-GB for consistent DD.MM HH:MM format regardless of browser locale.\n  const dateStr = x.toLocaleDateString('en-GB',dateOptions).replace('/','.').replace('/','.');\n  const timeStr = x.toLocaleTimeString('en-GB',timeOptions);\n  return dateStr + ' ' + timeStr;\n}\n''',
)

# 2) Capability-safe aria2 failure handling + bounded keyed locks.
replace_once(
    "backend/services/aria2.py",
    "from dataclasses import dataclass\n",
    "from contextlib import asynccontextmanager\nfrom dataclasses import dataclass\n",
)
replace_once(
    "backend/services/aria2.py",
    '''@dataclass\nclass Aria2DownloadStatus:\n    gid: str\n    status: str\n    total_length: int\n    completed_length: int\n    download_speed: int\n    error_code: str = ""\n    error_message: str = ""\n    files: Optional[List[Dict[str, Any]]] = None\n\n\ndef aria2_download_to_dict''',
    '''@dataclass\nclass Aria2DownloadStatus:\n    gid: str\n    status: str\n    total_length: int\n    completed_length: int\n    download_speed: int\n    error_code: str = ""\n    error_message: str = ""\n    files: Optional[List[Dict[str, Any]]] = None\n\n\n@dataclass\nclass _UriLockEntry:\n    lock: asyncio.Lock\n    users: int = 0\n\n\ndef aria2_download_to_dict''',
)
replace_once(
    "backend/services/aria2.py",
    "        self._uri_locks: Dict[str, asyncio.Lock] = {}\n",
    "        self._uri_locks: Dict[str, _UriLockEntry] = {}\n",
)
replace_once(
    "backend/services/aria2.py",
    "        async with self._lock_for_uri(normalized_uri):\n",
    "        async with self._uri_lock(normalized_uri):\n",
)
replace_once(
    "backend/services/aria2.py",
    '''                    logger.warning("Error queuing download (attempt %s/%s) for %s, retrying in %ss: %s", attempt, max_retries, normalized_uri, delay, exc)\n                    await asyncio.sleep(delay)\n\n        raise Aria2RPCError(f"Unable to queue aria2 download for {normalized_uri}: {last_error}")\n''',
    '''                    logger.warning(\n                        "Error queuing download (attempt %s/%s) for %s, retrying in %ss: %s",\n                        attempt,\n                        max_retries,\n                        sanitize_log_value(normalized_uri, max_length=120),\n                        delay,\n                        sanitize_log_value(exc, max_length=200),\n                    )\n                    await asyncio.sleep(delay)\n\n        safe_error = sanitize_log_value(last_error, max_length=200)\n        raise Aria2RPCError(\n            f"Unable to queue aria2 download after retries: {safe_error or 'unknown aria2 error'}"\n        )\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''    def _lock_for_uri(self, uri: str) -> asyncio.Lock:\n        lock = self._uri_locks.get(uri)\n        if lock is None:\n            lock = asyncio.Lock()\n            self._uri_locks[uri] = lock\n        return lock\n''',
    '''    @asynccontextmanager\n    async def _uri_lock(self, uri: str):\n        """Serialize one URI while dropping the high-cardinality key after use."""\n        entry = self._uri_locks.get(uri)\n        if entry is None:\n            entry = _UriLockEntry(lock=asyncio.Lock())\n            self._uri_locks[uri] = entry\n        entry.users += 1\n        try:\n            async with entry.lock:\n                yield\n        finally:\n            entry.users = max(0, entry.users - 1)\n            if entry.users == 0 and not entry.lock.locked() and self._uri_locks.get(uri) is entry:\n                self._uri_locks.pop(uri, None)\n''',
)
replace_once(
    "backend/services/manager_v2.py",
    '''def _terminal_torrent_status(status: str) -> bool:\n    return status in {"completed", "deleted", "error"}\n\n\ndef _aria2_status_rank''',
    '''def _terminal_torrent_status(status: str) -> bool:\n    return status in {"completed", "deleted", "error"}\n\n\ndef _safe_persisted_error(exc: BaseException) -> str:\n    """Never persist provider/download capability material from an exception."""\n    return sanitize_exception(exc, max_length=300)\n\n\ndef _aria2_status_rank''',
)
replace_once(
    "backend/services/manager_v2.py",
    '''                except Exception as exc:\n                    logger.error("aria2 dispatch failed [%s]: %s", row["filename"], exc)\n                    await self._update_file_state(row["file_id"], "error", row["local_path"], reason=str(exc))\n                    await self._finalize_aria2_torrent(row["torrent_id"])\n''',
    '''                except Exception as exc:\n                    safe_error = _safe_persisted_error(exc)\n                    logger.error("aria2 dispatch failed [%s]: %s", row["filename"], safe_error)\n                    await self._update_file_state(\n                        row["file_id"], "error", row["local_path"], reason=safe_error\n                    )\n                    await self._finalize_aria2_torrent(row["torrent_id"])\n''',
)

# 3) Cancellation-safe maintenance/provider/scheduler acquisition and rollback.
replace_once(
    "backend/services/maintenance_gate.py",
    '''    @asynccontextmanager\n    async def maintenance(self):\n        current = asyncio.current_task()\n        if current is None:\n            raise RuntimeError("Application maintenance requires an asyncio task")\n        async with self._condition:\n            if self._maintenance_active:\n                raise ApplicationMaintenanceActive("Application maintenance is already in progress")\n            self._maintenance_active = True\n            self._owner = current\n            while self._active_operations:\n                await self._condition.wait()\n        try:\n            yield\n        finally:\n            async with self._condition:\n                self._owner = None\n                self._maintenance_active = False\n                self._condition.notify_all()\n''',
    '''    @asynccontextmanager\n    async def maintenance(self):\n        current = asyncio.current_task()\n        if current is None:\n            raise RuntimeError("Application maintenance requires an asyncio task")\n        claimed = False\n        try:\n            async with self._condition:\n                if self._maintenance_active:\n                    raise ApplicationMaintenanceActive("Application maintenance is already in progress")\n                self._maintenance_active = True\n                self._owner = current\n                claimed = True\n                while self._active_operations:\n                    await self._condition.wait()\n            yield\n        finally:\n            if claimed:\n                async with self._condition:\n                    if self._owner is current:\n                        self._owner = None\n                        self._maintenance_active = False\n                        self._condition.notify_all()\n''',
)
replace_once(
    "backend/db/database.py",
    '''    @asynccontextmanager\n    async def maintenance(self):\n        current = asyncio.current_task()\n        async with self._condition:\n            if self._maintenance_active:\n                raise DatabaseMaintenanceActive("Database maintenance is already in progress")\n            self._maintenance_active = True\n            self._owner = current\n            while self._active_sessions:\n                await self._condition.wait()\n        try:\n            yield\n        finally:\n            async with self._condition:\n                self._owner = None\n                self._maintenance_active = False\n                self._condition.notify_all()\n''',
    '''    @asynccontextmanager\n    async def maintenance(self):\n        current = asyncio.current_task()\n        claimed = False\n        try:\n            async with self._condition:\n                if self._maintenance_active:\n                    raise DatabaseMaintenanceActive("Database maintenance is already in progress")\n                self._maintenance_active = True\n                self._owner = current\n                claimed = True\n                while self._active_sessions:\n                    await self._condition.wait()\n            yield\n        finally:\n            if claimed:\n                async with self._condition:\n                    if self._owner is current:\n                        self._owner = None\n                        self._maintenance_active = False\n                        self._condition.notify_all()\n''',
)
replace_once(
    "backend/services/provider_gateway.py",
    '''    async def begin_quiescence(self) -> None:\n        """Block new provider operations and wait for existing operations to drain."""\n        async with self._activity:\n            self._quiescing = True\n            while self._active_operations:\n                await self._activity.wait()\n''',
    '''    async def begin_quiescence(self) -> None:\n        """Block new provider operations and wait for existing operations to drain."""\n        claimed = False\n        try:\n            async with self._activity:\n                if self._quiescing:\n                    raise RuntimeError("Provider quiescence is already active")\n                self._quiescing = True\n                claimed = True\n                while self._active_operations:\n                    await self._activity.wait()\n        except BaseException:\n            if claimed:\n                async with self._activity:\n                    self._quiescing = False\n                    self._activity.notify_all()\n            raise\n''',
)
replace_once(
    "backend/services/transfer_service.py",
    '''        except Exception:\n            if provider_quiesced:\n                await self.provider.end_quiescence()\n            self._engine.set_materialization_quiescing(False)\n            raise\n''',
    '''        except BaseException:\n            if provider_quiesced:\n                await self.provider.end_quiescence()\n            self._engine.set_materialization_quiescing(False)\n            raise\n''',
)
replace_once(
    "backend/api/routes.py",
    '''        scheduler_was_running = scheduler_runtime.scheduler_running()\n        scheduler_stopped = False\n        quiesced = False\n''',
    '''        scheduler_was_running = scheduler_runtime.scheduler_running()\n        # Mark intent before the interruptible stop: stop_scheduler clears/cancels\n        # its task list before awaiting task completion.\n        scheduler_stopped = scheduler_was_running\n        quiesced = False\n''',
)
replace_once(
    "backend/api/routes.py",
    '''                if scheduler_was_running:\n                    await scheduler_runtime.stop_scheduler()\n                    scheduler_stopped = True\n''',
    '''                if scheduler_stopped:\n                    await scheduler_runtime.stop_scheduler()\n''',
)
replace_once(
    "backend/core/scheduler.py",
    '''async def stop_scheduler():\n    tasks = list(_tasks)\n    _tasks.clear()\n    for task in tasks:\n        task.cancel()\n    if tasks:\n        await asyncio.gather(*tasks, return_exceptions=True)\n''',
    '''async def stop_scheduler():\n    tasks = list(_tasks)\n    _tasks.clear()\n    for task in tasks:\n        task.cancel()\n    if tasks:\n        waiter = asyncio.gather(*tasks, return_exceptions=True)\n        try:\n            await asyncio.shield(waiter)\n        except asyncio.CancelledError:\n            # Finish draining cancelled scheduler tasks before propagating caller\n            # cancellation; the wipe route can then safely restart the scheduler.\n            await waiter\n            raise\n''',
)

# 4) Transactional built-in aria2 startup.
replace_once(
    "backend/services/aria2_runtime.py",
    '''            except Exception as exc:\n                self._last_error = str(exc)\n                logger.warning("Built-in aria2 start failed: %s", exc)\n            return await self.status()\n''',
    '''            except BaseException as exc:\n                self._last_error = str(exc).strip() or exc.__class__.__name__\n                await self._cleanup_failed_start()\n                if isinstance(exc, asyncio.CancelledError):\n                    raise\n                logger.warning("Built-in aria2 start failed: %s", exc)\n            return await self.status()\n''',
)
replace_once(
    "backend/services/aria2_runtime.py",
    '''    async def _cancel_drain_tasks(self) -> None:\n        tasks = [task for task in (self._stdout_task, self._stderr_task) if task]\n        for task in tasks:\n            task.cancel()\n        if tasks:\n            await asyncio.gather(*tasks, return_exceptions=True)\n        self._stdout_task = None\n        self._stderr_task = None\n\n    def _startup_error''',
    '''    async def _cancel_drain_tasks(self) -> None:\n        tasks = [task for task in (self._stdout_task, self._stderr_task) if task]\n        for task in tasks:\n            task.cancel()\n        if tasks:\n            await asyncio.gather(*tasks, return_exceptions=True)\n        self._stdout_task = None\n        self._stderr_task = None\n\n    async def _cleanup_failed_start(self) -> None:\n        """Roll back every resource allocated by an unsuccessful start attempt."""\n        process = self._process\n        if process is not None and process.returncode is None:\n            try:\n                process.terminate()\n            except ProcessLookupError:\n                pass\n            try:\n                await asyncio.wait_for(process.wait(), timeout=5)\n            except asyncio.TimeoutError:\n                try:\n                    process.kill()\n                except ProcessLookupError:\n                    pass\n                await process.wait()\n        await self._cancel_drain_tasks()\n        self._process = None\n        self._started_at = 0.0\n\n    def _startup_error''',
)

# 5) Serialized, collision-proof backup runs while retaining old managed dirs.
replace_once(
    "backend/services/backup.py",
    "import sqlite3\nfrom datetime import datetime, timezone\n",
    "import sqlite3\nimport uuid\nfrom datetime import datetime, timezone\n",
)
replace_once(
    "backend/services/backup.py",
    '_BACKUP_DIR_RE = re.compile(r"^\\d{8}_\\d{6}$")\n',
    '_BACKUP_DIR_RE = re.compile(r"^\\d{8}_\\d{6}(?:_[0-9a-f]{8})?$")\n_BACKUP_RUN_LOCK = asyncio.Lock()\n',
)
replace_once(
    "backend/services/backup.py",
    "async def run_backup() -> dict:\n",
    "async def run_backup() -> dict:\n    async with _BACKUP_RUN_LOCK:\n        return await _run_backup_locked()\n\n\nasync def _run_backup_locked() -> dict:\n",
)
replace_once(
    "backend/services/backup.py",
    '    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")\n',
    '    ts = f"{datetime.now(timezone.utc).strftime(\'%Y%m%d_%H%M%S\')}_{uuid.uuid4().hex[:8]}"\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    "import base64\nimport json\n",
    "import asyncio\nimport base64\nimport json\n",
)
replace_once(
    "backend/services/db_maintenance.py",
    "import shutil\nfrom datetime import date, datetime, time, timezone\n",
    "import shutil\nimport uuid\nfrom datetime import date, datetime, time, timezone\n",
)
replace_once(
    "backend/services/db_maintenance.py",
    '_BACKUP_DIR_RE = re.compile(r"^\\d{8}_\\d{6}$")\n',
    '_BACKUP_DIR_RE = re.compile(r"^\\d{8}_\\d{6}(?:_[0-9a-f]{8})?$")\n_BACKUP_RUN_LOCK = asyncio.Lock()\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    "async def run_database_backup() -> dict:\n",
    "async def run_database_backup() -> dict:\n    async with _BACKUP_RUN_LOCK:\n        return await _run_database_backup_locked()\n\n\nasync def _run_database_backup_locked() -> dict:\n",
)
replace_once(
    "backend/services/db_maintenance.py",
    '    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")\n',
    '    ts = f"{datetime.now(timezone.utc).strftime(\'%Y%m%d_%H%M%S\')}_{uuid.uuid4().hex[:8]}"\n',
)

# 7) V1 metadata says what 1.0.6 actually ships.
replace_once(
    "backend/core/branding.py",
    'APP_METADATA_TITLE = "DebridPulse — Multi-provider Debrid Download Manager"',
    'APP_METADATA_TITLE = "DebridPulse — AllDebrid + aria2 Download Manager"',
)
replace_all(
    ".github/workflows/fork-image.yml",
    "DebridPulse — Multi-provider Debrid Download Manager",
    "DebridPulse — AllDebrid + aria2 Download Manager",
    minimum=4,
)
replace_all(
    ".github/workflows/fork-image.yml",
    "Multi-provider debrid download manager for direct links, magnets, and torrent files",
    "AllDebrid-backed download manager for direct links, magnets, and torrent files via aria2",
    minimum=2,
)
replace_once(
    "NOTICE",
    "DebridPulse — Multi-provider Debrid Download Manager",
    "DebridPulse — AllDebrid + aria2 Download Manager",
)

# 8) Disk-guard contract comment matches behavior.
replace_once(
    "backend/core/config.py",
    '''    # When free space drops below this threshold:\n    #   - New downloads are blocked (deferred, not errored)\n    #   - Active aria2 downloads are PAUSED automatically\n    #\n    # When free space rises back above threshold + 0.5 GB hysteresis:\n    #   - Paused-by-guard downloads are RESUMED automatically\n''',
    '''    # When free space drops below this threshold:\n    #   - New aria2 dispatches are deferred (not errored)\n    #   - Transfers already active in aria2 are allowed to finish\n    #\n    # When free space rises back above threshold + 0.5 GB hysteresis:\n    #   - Deferred dispatch resumes automatically\n''',
)

print("Applied v1.0.6 final-audit corrective pass")
