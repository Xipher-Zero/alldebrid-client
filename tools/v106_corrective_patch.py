from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def replace_regex(path: str, pattern: str, new: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, new, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:100]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Provider boundary: maintenance quiescence is a writer barrier. New provider
# work cannot enter after maintenance starts and existing provider operations
# must drain before the database can be backed up/wiped.
# ---------------------------------------------------------------------------
write(
    "backend/services/provider_gateway.py",
    '''"""Provider boundary for the V1 AllDebrid implementation.

Provider-specific network/materialization behavior still lives in the inherited
engine, but every application-visible provider operation is enumerated here so
callers cannot bypass the provider boundary through a transparent fallback.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class ProviderGateway:
    def __init__(self, engine):
        self.engine = engine
        self._activity = asyncio.Condition()
        self._active_operations = 0
        self._quiescing = False

    @asynccontextmanager
    async def _operation(self):
        async with self._activity:
            if self._quiescing:
                raise RuntimeError("Provider operations are quiesced for database maintenance")
            self._active_operations += 1
        try:
            yield
        finally:
            async with self._activity:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._activity.notify_all()

    async def begin_quiescence(self) -> None:
        """Block new provider operations and wait for existing operations to drain."""
        async with self._activity:
            self._quiescing = True
            while self._active_operations:
                await self._activity.wait()

    async def end_quiescence(self) -> None:
        async with self._activity:
            self._quiescing = False
            self._activity.notify_all()

    @property
    def quiescing(self) -> bool:
        return self._quiescing

    def client(self):
        """Return the configured AllDebrid client for read-only/provider-only operations."""
        return self.engine.ad()

    async def sync_status(self):
        async with self._operation():
            return await self.engine.sync_alldebrid_status()

    async def reconcile_inventory(self):
        async with self._operation():
            return await self.engine.reconcile_provider_inventory()

    async def import_existing(self):
        async with self._operation():
            return await self.engine.import_existing_magnets()

    async def full_sync(self):
        async with self._operation():
            return await self.engine.full_alldebrid_sync()

    async def add_magnet(self, magnet: str, source: str = "manual"):
        async with self._operation():
            return await self.engine.add_magnet_direct(magnet, source=source)

    async def add_torrent_file(self, *args, **kwargs):
        async with self._operation():
            return await self.engine.add_torrent_file_direct(*args, **kwargs)

    async def add_direct_links(self, links):
        async with self._operation():
            return await self.engine.add_direct_links(links)

    async def retry_direct_link_collection(self, transfer_id: int):
        async with self._operation():
            return await self.engine.retry_direct_link_collection(int(transfer_id))

    async def cleanup_no_peer_errors(self):
        async with self._operation():
            return await self.engine.cleanup_no_peer_errors()

    async def cleanup_orphans(self):
        async with self._operation():
            return await self.engine.cleanup_alldebrid_orphans()

    async def cleanup_stuck(self):
        async with self._operation():
            return await self.engine.cleanup_stuck_downloads()

    async def test(self):
        async with self._operation():
            return await self.client().get_user()
''',
)

# ---------------------------------------------------------------------------
# Materialization engine: track all background work relevant to DB state and
# stop scheduling new work while destructive maintenance owns the barrier.
# ---------------------------------------------------------------------------
replace_once(
    "backend/services/manager_v2.py",
    """        self._ready_parent_tasks: Set[asyncio.Task] = set()\n        self._ready_parent_task_ids: Set[int] = set()\n        self._aria2_state_lock = asyncio.Lock()\n""",
    """        self._ready_parent_tasks: Set[asyncio.Task] = set()\n        self._ready_parent_task_ids: Set[int] = set()\n        self._maintenance_tasks: Set[asyncio.Task] = set()\n        self._materialization_quiescing = False\n        self._aria2_state_lock = asyncio.Lock()\n""",
)

replace_once(
    "backend/services/manager_v2.py",
    """    def is_paused(self) -> bool:\n        return bool(get_settings().paused)\n\n    def notify(self):\n""",
    """    def is_paused(self) -> bool:\n        return bool(get_settings().paused)\n\n    @staticmethod\n    def _provider_delete_authorized(source: object) -> bool:\n        \"\"\"Automatic provider deletion requires positive local ownership evidence.\"\"\"\n        normalized = str(source or \"\").strip()\n        return bool(normalized) and normalized not in {\"alldebrid_existing\", \"import_existing\"}\n\n    def set_materialization_quiescing(self, value: bool) -> None:\n        self._materialization_quiescing = bool(value)\n\n    def _track_maintenance_task(self, coro, *, label: str) -> asyncio.Task:\n        task = asyncio.create_task(coro)\n        self._maintenance_tasks.add(task)\n\n        def _finished(done: asyncio.Task) -> None:\n            self._maintenance_tasks.discard(done)\n            try:\n                done.result()\n            except asyncio.CancelledError:\n                pass\n            except Exception as exc:\n                logger.error(\n                    \"Background materialization task %s failed: %s\",\n                    label,\n                    sanitize_exception(exc, max_length=300),\n                )\n\n        task.add_done_callback(_finished)\n        return task\n\n    async def wait_for_materialization_idle(self) -> None:\n        \"\"\"Drain provider-triggered/materialization tasks before destructive maintenance.\"\"\"\n        while True:\n            tasks = [\n                task\n                for task in (\n                    *self._direct_link_tasks,\n                    *self._ready_parent_tasks,\n                    *self._maintenance_tasks,\n                )\n                if not task.done()\n            ]\n            if tasks:\n                await asyncio.gather(*tasks, return_exceptions=True)\n                continue\n            if self._active:\n                await asyncio.sleep(0.05)\n                continue\n            async with self._deferred_submission_lock:\n                pass\n            if not self._active and not any(\n                not task.done()\n                for task in (\n                    *self._direct_link_tasks,\n                    *self._ready_parent_tasks,\n                    *self._maintenance_tasks,\n                )\n            ):\n                return\n\n    def notify(self):\n""",
)

replace_once(
    "backend/services/manager_v2.py",
    """        if torrent_id in self._active or torrent_id in self._direct_link_task_ids:\n            return\n""",
    """        if self._materialization_quiescing:\n            return\n        if torrent_id in self._active or torrent_id in self._direct_link_task_ids:\n            return\n""",
)

# Ready-parent scheduler has the same duplicate guard pattern but a different set.
replace_once(
    "backend/services/manager_v2.py",
    """        if torrent_id in self._active or torrent_id in self._ready_parent_task_ids:\n            return\n""",
    """        if self._materialization_quiescing:\n            return\n        if torrent_id in self._active or torrent_id in self._ready_parent_task_ids:\n            return\n""",
)

replace_once(
    "backend/services/manager_v2.py",
    """    async def resume_deferred_provider_submissions(self) -> dict:\n        \"\"\"Start provider work that was durably accepted while Pause All was active.\"\"\"\n        if self.is_paused():\n""",
    """    async def resume_deferred_provider_submissions(self) -> dict:\n        \"\"\"Start provider work that was durably accepted while Pause All was active.\"\"\"\n        if self._materialization_quiescing:\n            return {\"started\": 0, \"failed\": 0}\n        if self.is_paused():\n""",
)

replace_once(
    "backend/services/manager_v2.py",
    """    async def _prepare_direct_link_collection(\n        self, torrent_id: int, links: List[str]\n    ) -> None:\n        if torrent_id in self._active:\n""",
    """    async def _prepare_direct_link_collection(\n        self, torrent_id: int, links: List[str]\n    ) -> None:\n        if self._materialization_quiescing:\n            return\n        if torrent_id in self._active:\n""",
)

# Track provider/error/extraction tasks that previously escaped the named task sets.
manager_path = "backend/services/manager_v2.py"
manager = read(manager_path)
manager = manager.replace(
    "asyncio.create_task(self._handle_upload_failed(row, error_message))",
    "self._track_maintenance_task(self._handle_upload_failed(row, error_message), label=f\"upload-failed-{row['id']}\")",
)
manager = manager.replace(
    "asyncio.create_task(self._handle_expired_reimport(row, magnet_link))",
    "self._track_maintenance_task(self._handle_expired_reimport(row, magnet_link), label=f\"expired-reimport-{row['id']}\")",
)
manager = manager.replace(
    """        asyncio.create_task(\n            self._extract_torrent(torrent_id, torrent_dict)\n        )\n""",
    """        self._track_maintenance_task(\n            self._extract_torrent(torrent_id, torrent_dict),\n            label=f\"extract-{torrent_id}\",\n        )\n""",
)
write(manager_path, manager)

# Imported/observed AllDebrid rows remain observation-only when revived.
replace_once(
    manager_path,
    """                        SET name=?, alldebrid_id=?, status=?,\n                            provider_status=?, provider_status_code=?,\n""",
    """                        SET name=?, alldebrid_id=?, status=?,\n                            source='alldebrid_existing',\n                            provider_status=?, provider_status_code=?,\n""",
)

# Completion cleanup must prove local ownership before mutating the provider.
replace_regex(
    manager_path,
    r"    async def _delete_magnet_after_completion\(self, torrent_id: int, ad_id: str\) -> bool:\n.*?\n    async def _mark_finished",
    '''    async def _delete_magnet_after_completion(self, torrent_id: int, ad_id: str) -> bool:\n        \"\"\"Delete a completed provider object only when this instance owns it.\"\"\"\n        ad_id = str(ad_id or \"\").strip()\n        async with get_db() as db:\n            row = await db.fetchone(\n                \"SELECT source FROM torrents WHERE id=?\", (torrent_id,)\n            )\n        source = row.get(\"source\") if row else None\n        if not self._provider_delete_authorized(source):\n            await self._log_event(\n                torrent_id,\n                \"info\",\n                \"Completed locally; observed AllDebrid object preserved (not owned by this instance)\",\n            )\n            return False\n        if not ad_id or ad_id.lower() in (\"none\", \"null\"):\n            logger.warning(\n                \"torrent %s: skipping AllDebrid deletion — no alldebrid_id\", torrent_id\n            )\n            await self._log_event(\n                torrent_id,\n                \"warn\",\n                \"Completed locally, but no AllDebrid ID — cannot remove from AllDebrid\",\n            )\n            return False\n\n        logger.info(\"torrent %s: removing owned AllDebrid object (id=%s)\", torrent_id, ad_id)\n        deleted = await self.ad().delete_magnet(ad_id)\n        msg = (\n            \"Removed owned object from AllDebrid after completion\"\n            if deleted\n            else f\"Completed, but AllDebrid removal failed (id={ad_id})\"\n        )\n        await self._log_event(torrent_id, \"info\" if deleted else \"warn\", msg)\n        return deleted\n\n    async def _mark_finished''',
)

# Rework automatic fatal/orphan cleanup around positive ownership. Unknown,
# imported and deliberately local-only-deleted provider objects are preserved.
replace_regex(
    manager_path,
    r"    async def cleanup_no_peer_errors\(self\):\n.*?\n    async def cleanup_alldebrid_orphans",
    '''    async def cleanup_no_peer_errors(self):\n        \"\"\"Clean fatal provider objects only when local provenance proves ownership.\"\"\"\n        async with get_db() as db:\n            rows = await db.fetchall(\n                \"\"\"SELECT id, name, alldebrid_id, source, error_message,\n                          provider_status_code\n                     FROM torrents\n                    WHERE status='error'\n                      AND alldebrid_id IS NOT NULL AND alldebrid_id != ''\n                      AND COALESCE(provider_status, '') != 'failed'\n                      AND (provider_status_code BETWEEN 5 AND 15\n                           OR LOWER(COALESCE(error_message,'')) LIKE '%no peer%'\n                           OR LOWER(COALESCE(error_message,'')) LIKE '%not available%')\"\"\"\n            )\n\n        for row in rows:\n            ad_id = str(row.get(\"alldebrid_id\") or \"\").strip()\n            if not ad_id:\n                continue\n            if not self._provider_delete_authorized(row.get(\"source\")):\n                await self._log_event(\n                    int(row[\"id\"]),\n                    \"info\",\n                    \"Provider error observed; AllDebrid object preserved because this instance does not own it\",\n                )\n                async with get_db() as db:\n                    await db.execute(\n                        \"UPDATE torrents SET provider_status='failed', updated_at=CURRENT_TIMESTAMP WHERE id=?\",\n                        (row[\"id\"],),\n                    )\n                    await db.commit()\n                continue\n            removed = False\n            try:\n                removed = bool(await self.ad().delete_magnet(ad_id))\n            except Exception as exc:\n                logger.warning(\n                    \"Could not delete owned failed AllDebrid object %s: %s\",\n                    ad_id,\n                    sanitize_exception(exc),\n                )\n            async with get_db() as db:\n                await db.execute(\n                    \"UPDATE torrents SET provider_status='failed', updated_at=CURRENT_TIMESTAMP WHERE id=?\",\n                    (row[\"id\"],),\n                )\n                await db.execute(\n                    \"INSERT INTO events (torrent_id, level, message) VALUES (?, ?, ?)\",\n                    (\n                        row[\"id\"],\n                        \"info\" if removed else \"warn\",\n                        \"Removed owned failed object from AllDebrid\"\n                        if removed\n                        else \"Owned failed AllDebrid object could not be removed\",\n                    ),\n                )\n                await db.commit()\n\n    async def cleanup_alldebrid_orphans''',
)

replace_regex(
    manager_path,
    r"    async def cleanup_alldebrid_orphans\(self\) -> int:\n.*?\n    async def _apply_provider_update",
    '''    async def cleanup_alldebrid_orphans(self) -> int:\n        \"\"\"Conservatively clean only locally owned error objects.\n\n        Absence from the local database is never deletion authority. Imported\n        objects and local-only deleted rows remain untouched.\n        \"\"\"\n        try:\n            magnets = await self.ad().get_magnet_status()\n        except Exception as exc:\n            logger.warning(\"cleanup_alldebrid_orphans: provider scan failed: %s\", exc)\n            return 0\n        async with get_db() as db:\n            rows = await db.fetchall(\n                \"SELECT alldebrid_id, status, source, provider_status FROM torrents WHERE alldebrid_id IS NOT NULL\"\n            )\n        known = {str(row[\"alldebrid_id\"]): row for row in rows if row.get(\"alldebrid_id\")}\n        deleted = 0\n        for magnet in magnets or []:\n            ad_id = str(magnet.get(\"id\") or \"\").strip()\n            status_code = int(magnet.get(\"statusCode\") or 0)\n            status_text = str(magnet.get(\"status\") or \"\").lower()\n            fatal = status_code in ERROR_CODES or \"no peer\" in status_text or \"not available\" in status_text\n            if not ad_id or not fatal:\n                continue\n            local = known.get(ad_id)\n            if (\n                local is None\n                or str(local.get(\"status\") or \"\") != \"error\"\n                or str(local.get(\"provider_status\") or \"\") == \"failed\"\n                or not self._provider_delete_authorized(local.get(\"source\"))\n            ):\n                logger.debug(\n                    \"cleanup_alldebrid_orphans: preserving unowned/unknown provider object %s\",\n                    ad_id,\n                )\n                continue\n            try:\n                if await self.ad().delete_magnet(ad_id):\n                    deleted += 1\n            except Exception as exc:\n                logger.warning(\"cleanup_alldebrid_orphans: delete %s failed: %s\", ad_id, exc)\n        return deleted\n\n    async def _apply_provider_update''',
)

# Automatic code-7/8 deletion inside provider update also honors ownership.
manager = read(manager_path)
manager = manager.replace(
    """                try:\n                    await self.ad().delete_magnet(str(row[\"alldebrid_id\"]))\n                    logger.info(\n                        \"Deleted AllDebrid magnet %s after terminal provider error\",\n                        row[\"alldebrid_id\"],\n                    )\n                except Exception as exc:\n""",
    """                try:\n                    if self._provider_delete_authorized(row.get(\"source\")):\n                        await self.ad().delete_magnet(str(row[\"alldebrid_id\"]))\n                        logger.info(\n                            \"Deleted owned AllDebrid magnet %s after terminal provider error\",\n                            row[\"alldebrid_id\"],\n                        )\n                    else:\n                        logger.info(\n                            \"Preserving observed AllDebrid magnet %s after terminal provider error\",\n                            row[\"alldebrid_id\"],\n                        )\n                except Exception as exc:\n""",
)
write(manager_path, manager)

# Upload-failure retry must not delete an observed/imported provider object.
manager = read(manager_path)
manager = manager.replace(
    """        if ad_id:\n            try:\n                await self.ad().delete_magnet(ad_id)\n""",
    """        if ad_id and self._provider_delete_authorized(row.get(\"source\")):\n            try:\n                await self.ad().delete_magnet(ad_id)\n""",
    1,
)
write(manager_path, manager)

# ---------------------------------------------------------------------------
# TransferService owns the maintenance lifecycle. The route will always release
# it in finally, including backup/wipe failures.
# ---------------------------------------------------------------------------
replace_regex(
    "backend/services/transfer_service.py",
    r"    async def quiesce_for_database_wipe\(self\):\n.*?\n    def reset_services",
    '''    async def quiesce_for_database_wipe(self):\n        \"\"\"Quiesce provider, materialization and owned aria2 work before DB wipe.\"\"\"\n        self._engine.set_materialization_quiescing(True)\n        provider_quiesced = False\n        try:\n            await self.provider.begin_quiescence()\n            provider_quiesced = True\n            pause_result = await self.pause_all_downloads()\n            failed = int((pause_result or {}).get(\"failed\") or 0)\n            if failed:\n                raise RuntimeError(f\"Could not confirm pause for {failed} transfer(s)\")\n            await self._engine.wait_for_materialization_idle()\n            await self.aria2.test()\n            owned = await self.aria2.get_owned()\n            live = [item for item in owned if item.status in {\"active\", \"waiting\"}]\n            if live:\n                raise RuntimeError(\n                    f\"Database wipe refused: {len(live)} owned aria2 job(s) are still live\"\n                )\n            return {\n                \"pause\": pause_result,\n                \"owned_checked\": len(owned),\n                \"provider_operations_drained\": True,\n                \"materialization_drained\": True,\n            }\n        except Exception:\n            if provider_quiesced:\n                await self.provider.end_quiescence()\n            self._engine.set_materialization_quiescing(False)\n            raise\n\n    async def release_database_wipe_quiescence(self):\n        await self.provider.end_quiescence()\n        self._engine.set_materialization_quiescing(False)\n\n    def reset_services''',
)

# ---------------------------------------------------------------------------
# Settings secrets: explicit clear intent + Basic Auth fields + bulk enum.
# ---------------------------------------------------------------------------
replace_once(
    "backend/api/routes.py",
    "from typing import Optional, AsyncGenerator\n",
    "from typing import Optional, AsyncGenerator, Literal\n",
)
replace_once(
    "backend/api/routes.py",
    "from pydantic import BaseModel\n",
    "from pydantic import BaseModel, Field\n",
)
replace_once(
    "backend/api/routes.py",
    """@router.put(\"/settings\")\nasync def update_settings(new: AppSettings):\n    previous = get_settings()\n    merged = new.model_dump()\n    for field in _SECRET_SETTINGS:\n        if field in merged and not str(merged.get(field) or \"\").strip():\n            merged[field] = getattr(previous, field, \"\")\n""",
    """class SettingsUpdate(AppSettings):\n    clear_secrets: list[str] = Field(default_factory=list)\n\n\ndef _merge_secret_settings(new: SettingsUpdate, previous: AppSettings) -> dict:\n    requested_clears = {str(field) for field in new.clear_secrets}\n    unknown = requested_clears - _SECRET_SETTINGS\n    if unknown:\n        raise HTTPException(400, f\"Unsupported secret field(s): {', '.join(sorted(unknown))}\")\n    merged = new.model_dump(exclude={\"clear_secrets\"})\n    for field in _SECRET_SETTINGS:\n        if field in requested_clears:\n            merged[field] = \"\"\n        elif not str(merged.get(field) or \"\").strip():\n            merged[field] = getattr(previous, field, \"\")\n    return merged\n\n\n@router.put(\"/settings\")\nasync def update_settings(new: SettingsUpdate):\n    previous = get_settings()\n    merged = _merge_secret_settings(new, previous)\n""",
)
replace_once(
    "backend/api/routes.py",
    """class BulkAction(BaseModel):\n    ids: list\n    action: str  # \"delete\" | \"retry\" | \"remove_label\"\n""",
    """class BulkAction(BaseModel):\n    ids: list\n    action: Literal[\"delete\", \"retry\", \"reset\", \"pause\", \"resume\", \"remove_label\"]\n""",
)

replace_regex(
    "backend/api/routes.py",
    r"    try:\n        quiesce_result = await transfer_service.quiesce_for_database_wipe\(\)\n    except Exception as exc:\n        raise HTTPException\(409, _sanitize_error\(exc\)\)\n\n    backup_result = None\n.*?    return \{\*\*result, \"backup\": backup_result, \"quiesced\": quiesce_result\}\n",
    '''    quiesced = False\n    try:\n        try:\n            quiesce_result = await transfer_service.quiesce_for_database_wipe()\n            quiesced = True\n        except Exception as exc:\n            raise HTTPException(409, _sanitize_error(exc))\n\n        backup_result = None\n        if getattr(cfg, \"db_backup_before_wipe\", True):\n            from services.db_maintenance import run_database_backup\n            backup_result = await run_database_backup()\n            if backup_result.get(\"skipped\"):\n                raise HTTPException(409, \"Pre-wipe database backup is required but disabled\")\n            if backup_result.get(\"errors\"):\n                raise HTTPException(500, \"Pre-wipe database backup failed; wipe aborted\")\n\n        from services.db_maintenance import wipe_database\n        result = await wipe_database(verified_quiesced=True)\n        return {**result, \"backup\": backup_result, \"quiesced\": quiesce_result}\n    finally:\n        if quiesced:\n            await transfer_service.release_database_wipe_quiescence()\n''',
)

replace_once(
    "backend/api/routes.py",
    """    Delete from AllDebrid any magnets with error/no-peer status that are not\n    tracked by the local DB (or already marked deleted locally).\n    Returns the number of magnets removed.\n""",
    """    Conservatively scan provider-side error/no-peer objects. Automatic deletion\n    is limited to objects with positive local ownership evidence; unknown, imported\n    and local-only-deleted provider objects are preserved.\n""",
)

# ---------------------------------------------------------------------------
# Frontend trust boundary + settings semantics + premium state.
# ---------------------------------------------------------------------------
replace_once(
    "frontend/static/app.js",
    """function sanitizeErrorMsg(message) {\n  const text = String(message || 'Request failed');\n  const limited = text.length > 500\n    ? text.slice(0, 497) + '...'\n    : text;\n  return esc(limited);\n}\n\nfunction toast(msg, type = 'info') {\n  const icons = {success:'✅',error:'❌',warn:'⚠️',info:'ℹ️'};\n  const el = document.createElement('div');\n  el.className = `toast ${type}`;\n  el.innerHTML = `<span>${icons[type]||'·'}</span><span>${msg}</span>`;\n  document.getElementById('toasts').appendChild(el);\n""",
    """function sanitizeErrorMsg(message) {\n  const text = String(message || 'Request failed');\n  return text.length > 500 ? text.slice(0, 497) + '...' : text;\n}\n\nfunction toast(msg, type = 'info') {\n  const icons = {success:'✅',error:'❌',warn:'⚠️',info:'ℹ️'};\n  const el = document.createElement('div');\n  el.className = `toast ${type}`;\n  const icon = document.createElement('span');\n  icon.textContent = icons[type] || '·';\n  const text = document.createElement('span');\n  text.textContent = String(msg ?? '');\n  el.append(icon, text);\n  document.getElementById('toasts').appendChild(el);\n""",
)
replace_once(
    "frontend/static/app.js",
    "${ev.torrent_name?`<div class=\"ename\">${ev.torrent_name}</div>`:''}",
    "${ev.torrent_name?`<div class=\"ename\">${esc(ev.torrent_name)}</div>`:''}",
)
replace_once(
    "frontend/static/app.js",
    "el.innerHTML = `<p style=\"color:#f87171\">Failed to load changelog: ${e.message}</p>`;",
    "el.innerHTML = `<p style=\"color:#f87171\">Failed to load changelog: ${esc(e.message)}</p>`;",
)
replace_once(
    "frontend/static/app.js",
    "if (!cfg || !cfg.alldebrid_api_key) return;",
    "if (!cfg || !cfg.alldebrid_api_key_configured) return;",
)

replace_once(
    "frontend/static/app.js",
    """      <p class=\"form-hint\" style=\"padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)\">Optional HTTP Basic Auth. Set both fields to enable; leave either empty to disable. The browser will prompt for credentials on next load.</p>\n""",
    """      <p class=\"form-hint\" style=\"padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)\">Optional HTTP Basic Auth. Username remains visible; the saved password is never returned. Enter a password to set or replace it, or explicitly clear it in Stored Secrets below.</p>\n""",
)
replace_once(
    "frontend/static/app.js",
    """          <input class=\"input\" type=\"password\" id=\"s-auth_password\" value=\"${s.auth_password||''}\" placeholder=\"Leave empty to disable auth\"/>\n          <span class=\"form-hint\">⚠️ Save settings and reload the page to activate. Keep both fields empty to disable.</span>\n""",
    """          <input class=\"input\" type=\"password\" id=\"s-auth_password\" value=\"\" placeholder=\"${s.auth_password_configured?'Stored password configured — leave blank to keep':'Enter password to enable auth'}\"/>\n          <span class=\"form-hint\">Save settings and reload the page after changing credentials. Use Stored Secrets below to explicitly clear the saved password.</span>\n""",
)

# Insert one explicit-clear panel covering every redacted secret.
replace_once(
    "frontend/static/app.js",
    """    </div>\n\n      <div class=\"scard\">\n        <div class=\"scard-header\">💾 Disk Space Guard</div>\n""",
    """    </div>\n\n      <div class=\"scard\">\n        <div class=\"scard-header\">🧹 Stored Secrets</div>\n        <p class=\"form-hint\" style=\"padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)\">Redacted secrets are preserved when their input is left blank. Check a configured item here to explicitly erase it on Save.</p>\n        <div class=\"scard-body\">\n          ${[\n            ['alldebrid_api_key','AllDebrid API key'],\n            ['aria2_secret','aria2 RPC secret'],\n            ['discord_webhook_url','Discord webhook'],\n            ['discord_webhook_added','Torrent-added webhook'],\n            ['stats_report_webhook_url','Reporting webhook'],\n            ['auth_password','Basic Auth password'],\n            ['extraction_password','Extraction password']\n          ].filter(([field])=>s[field+'_configured']).map(([field,label])=>`\n            <label class=\"toggle-row\" style=\"cursor:pointer\">\n              <div class=\"toggle-info\"><div class=\"tl\">${label}</div><div class=\"ts\">Erase the stored value on Save</div></div>\n              <input type=\"checkbox\" id=\"s-clear-${field}\">\n            </label>`).join('') || '<div class=\"form-hint\">No stored secrets are currently configured.</div>'}\n        </div>\n      </div>\n\n      <div class=\"scard\">\n        <div class=\"scard-header\">💾 Disk Space Guard</div>\n""",
)

replace_once(
    "frontend/static/app.js",
    """  const maxConcurrentDownloads = n(\n    'aria2_max_active_downloads',\n    Number(settingsData.max_concurrent_downloads ?? 3),\n  );\n  return {\n""",
    """  const maxConcurrentDownloads = n(\n    'aria2_max_active_downloads',\n    Number(settingsData.max_concurrent_downloads ?? 3),\n  );\n  const secretFields = [\n    'alldebrid_api_key', 'aria2_secret', 'discord_webhook_url',\n    'discord_webhook_added', 'stats_report_webhook_url',\n    'auth_password', 'extraction_password'\n  ];\n  const clearSecrets = secretFields.filter(field =>\n    document.getElementById(`s-clear-${field}`)?.checked\n  );\n  return {\n""",
)
replace_once(
    "frontend/static/app.js",
    """    ...settingsData,\n    alldebrid_api_key: t('alldebrid_api_key'),\n""",
    """    ...settingsData,\n    clear_secrets: clearSecrets,\n    alldebrid_api_key: t('alldebrid_api_key'),\n    auth_username: t('auth_username'),\n    auth_password: t('auth_password'),\n""",
)

# ---------------------------------------------------------------------------
# Vendored executable browser dependency and documentation drift.
# ---------------------------------------------------------------------------
replace_once(
    "frontend/static/index.html",
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>',
    '<script src="/vendor/chart.umd.min.js?v=4.4.1"></script>',
)
replace_once(
    "frontend/static/index.html",
    "Exempt paths: /api/stats, /api/version, /api/avatar (for health checks).",
    "Exempt paths: /api/health, /api/version, /api/avatar.",
)
replace_once(
    "frontend/static/index.html",
    "<b>Min Free Disk Space (GB)</b> — If less than this is available, the download is aborted with an error (torrent row kept). 0 = disabled.",
    "<b>Min Free Disk Space (GB)</b> — If less than this is available, active transfers are allowed to finish while new dispatches are deferred until space recovers. 0 = disabled.",
)
replace_once(
    "frontend/static/index.html",
    "Check the <code>min_free_disk_gb</code> setting — if the disk is full, downloads abort with an error.",
    "Check the <code>min_free_disk_gb</code> setting — when the guard is active, new downloads are deferred until free space recovers.",
)
replace_once(
    "frontend/static/index.html",
    "Edit <code>settings.json</code> in your data folder (default: <code>/app/data/settings.json</code>)",
    "Edit the configured settings file (documented container default: <code>/app/config/config.json</code>)",
)
replace_once(
    "frontend/static/app.js",
    "p7zip-full and unrar-free are included in the Docker image.",
    "p7zip-full (7-Zip) is included in the Docker image; RAR extraction uses the same preflight-capable 7z path.",
)

# Disk-guard Settings text had also drifted from the actual defer-new-work behavior.
app = read("frontend/static/app.js")
app = app.replace(
    "Automatically <b>pauses</b> active downloads and blocks new ones when free space drops below",
    "Allows active downloads to finish and <b>defers new dispatches</b> when free space drops below",
)
app = app.replace(
    "Downloads are <b>paused</b> (not errored) when free space drops below this. They resume automatically when space recovers.",
    "New dispatches are deferred when free space drops below this; active transfers continue. Deferred work starts automatically when space recovers.",
)
write("frontend/static/app.js", app)

# Runtime dependency inventory: remove stale packages and record vendored Chart.js.
docs = read("docs/DEPENDENCY_LICENSES.md")
docs = docs.replace("| asyncpg | 0.31.0 | Apache-2.0 |\n", "")
docs = docs.replace("| unrar-free | GPL-2.0-or-later |\n", "")
docs = docs.replace(
    """## Browser-loaded resources\n\nThese resources are requested by the browser from third-party CDNs and are not\ncopied into the repository or container image:\n\n| Resource | Version/source | License |\n|---|---|---|\n| Chart.js | 4.4.1 from cdnjs | MIT |\n""",
    """## Vendored browser resources\n\n| Resource | Version/source | License |\n|---|---|---|\n| Chart.js | 4.4.1, vendored at `frontend/static/vendor/chart.umd.min.js` | MIT ([bundled notice](../licenses/Chart.js-MIT.txt)) |\n\n## Browser-loaded resources\n\nThese font resources are requested by the browser from third-party CDNs and are not\ncopied into the repository or container image:\n\n| Resource | Version/source | License |\n|---|---|---|\n""",
)
write("docs/DEPENDENCY_LICENSES.md", docs)

write(
    "licenses/Chart.js-MIT.txt",
    '''The MIT License (MIT)\n\nCopyright (c) 2014-2022 Chart.js Contributors\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of\nthis software and associated documentation files (the \"Software\"), to deal in\nthe Software without restriction, including without limitation the rights to\nuse, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of\nthe Software, and to permit persons to whom the Software is furnished to do so,\nsubject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS\nFOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR\nCOPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER\nIN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN\nCONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n''',
)

# Permanent JS CodeQL coverage.
replace_once(
    ".github/workflows/codeql.yml",
    "# Scans Python backend and GitHub Actions workflow files.\n",
    "# Scans Python backend, browser JavaScript, and GitHub Actions workflow files.\n",
)
replace_once(
    ".github/workflows/codeql.yml",
    """          - language: python\n            build-mode: none\n          - language: actions\n""",
    """          - language: python\n            build-mode: none\n          - language: javascript-typescript\n            build-mode: none\n          - language: actions\n""",
)

# ---------------------------------------------------------------------------
# Corrective regression suite.
# ---------------------------------------------------------------------------
write(
    "backend/tests/test_v106_corrective_regressions.py",
    '''import asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\nfrom unittest.mock import AsyncMock\n\nimport pytest\n\n\n@pytest.mark.asyncio\nasync def test_provider_quiescence_waits_for_inflight_operation():\n    from services.provider_gateway import ProviderGateway\n\n    started = asyncio.Event()\n    release = asyncio.Event()\n\n    async def add_magnet_direct(magnet, source=\"manual\"):\n        started.set()\n        await release.wait()\n        return {\"ok\": True}\n\n    engine = SimpleNamespace(add_magnet_direct=add_magnet_direct)\n    gateway = ProviderGateway(engine)\n    operation = asyncio.create_task(gateway.add_magnet(\"magnet:?xt=urn:btih:test\"))\n    await started.wait()\n    quiesce = asyncio.create_task(gateway.begin_quiescence())\n    await asyncio.sleep(0)\n    assert not quiesce.done()\n    release.set()\n    await operation\n    await quiesce\n    with pytest.raises(RuntimeError, match=\"quiesced\"):\n        await gateway.add_magnet(\"magnet:?xt=urn:btih:blocked\")\n    await gateway.end_quiescence()\n\n\ndef test_provider_delete_requires_positive_local_ownership():\n    from services.manager_v2 import TorrentManager\n\n    assert TorrentManager._provider_delete_authorized(\"manual\") is True\n    assert TorrentManager._provider_delete_authorized(\"manual_file\") is True\n    assert TorrentManager._provider_delete_authorized(\"alldebrid_existing\") is False\n    assert TorrentManager._provider_delete_authorized(\"import_existing\") is False\n    assert TorrentManager._provider_delete_authorized(\"\") is False\n    assert TorrentManager._provider_delete_authorized(None) is False\n\n\ndef test_orphan_cleanup_never_treats_unknown_as_delete_authority():\n    source = (Path(__file__).resolve().parents[1] / \"services\" / \"manager_v2.py\").read_text()\n    block = source.split(\"async def cleanup_alldebrid_orphans\", 1)[1].split(\"async def _apply_provider_update\", 1)[0]\n    assert \"local is None\" in block\n    assert \"_provider_delete_authorized\" in block\n    assert \"status\\\") or \\\"\\\") != \\\"error\\\"\" not in block  # source-level sanity only\n    assert \"preserving unowned/unknown provider object\" in block\n\n\ndef test_database_wipe_route_releases_quiescence_in_finally():\n    routes = (Path(__file__).resolve().parents[1] / \"api\" / \"routes.py\").read_text()\n    block = routes.split('async def wipe_database_admin', 1)[1].split('# ── Statistics & Reporting', 1)[0]\n    assert \"quiesce_for_database_wipe\" in block\n    assert \"finally:\" in block\n    assert \"release_database_wipe_quiescence\" in block\n\n\ndef test_settings_secret_merge_preserve_replace_clear():\n    from api.routes import SettingsUpdate, _merge_secret_settings\n    from core.config import AppSettings\n\n    previous = AppSettings(alldebrid_api_key=\"old-key\", auth_username=\"old-user\", auth_password=\"old-pass\")\n\n    preserve = SettingsUpdate(**previous.model_dump(), alldebrid_api_key=\"\", auth_password=\"\")\n    merged = _merge_secret_settings(preserve, previous)\n    assert merged[\"alldebrid_api_key\"] == \"old-key\"\n    assert merged[\"auth_password\"] == \"old-pass\"\n\n    replace = SettingsUpdate(**previous.model_dump(), auth_username=\"new-user\", auth_password=\"new-pass\")\n    merged = _merge_secret_settings(replace, previous)\n    assert merged[\"auth_username\"] == \"new-user\"\n    assert merged[\"auth_password\"] == \"new-pass\"\n\n    clear = SettingsUpdate(**previous.model_dump(), auth_password=\"\", clear_secrets=[\"auth_password\"])\n    merged = _merge_secret_settings(clear, previous)\n    assert merged[\"auth_password\"] == \"\"\n\n    with pytest.raises(Exception):\n        bad = SettingsUpdate(**previous.model_dump(), clear_secrets=[\"not_a_secret\"])\n        _merge_secret_settings(bad, previous)\n\n\ndef test_frontend_xss_and_secret_contracts():\n    root = Path(__file__).resolve().parents[2]\n    js = (root / \"frontend/static/app.js\").read_text()\n    html = (root / \"frontend/static/index.html\").read_text()\n    toast = js.split(\"function toast\", 1)[1].split(\"function setButtonPending\", 1)[0]\n    assert \"innerHTML\" not in toast\n    assert \"text.textContent = String(msg ?? '')\" in toast\n    assert \"${esc(ev.torrent_name)}\" in js\n    assert \"auth_username: t('auth_username')\" in js\n    assert \"auth_password: t('auth_password')\" in js\n    assert \"clear_secrets: clearSecrets\" in js\n    assert \"alldebrid_api_key_configured\" in js\n    assert \"cdnjs.cloudflare.com/ajax/libs/Chart.js\" not in html\n    assert '/vendor/chart.umd.min.js?v=4.4.1' in html\n\n\ndef test_bulk_actions_are_schema_limited():\n    from api.routes import BulkAction\n    from pydantic import ValidationError\n\n    with pytest.raises(ValidationError):\n        BulkAction(ids=[1], action=\"nonsense\")\n\n\ndef test_codeql_covers_browser_javascript():\n    workflow = (Path(__file__).resolve().parents[2] / \".github/workflows/codeql.yml\").read_text()\n    assert \"javascript-typescript\" in workflow\n\n\ndef test_dependency_docs_match_removed_runtime_components():\n    root = Path(__file__).resolve().parents[2]\n    docs = (root / \"docs/DEPENDENCY_LICENSES.md\").read_text()\n    requirements = (root / \"backend/requirements.txt\").read_text().lower()\n    dockerfile = (root / \"Dockerfile\").read_text().lower()\n    assert \"asyncpg\" not in requirements\n    assert \"| asyncpg |\" not in docs\n    assert \"unrar-free\" not in dockerfile\n    assert \"| unrar-free |\" not in docs\n    assert \"Chart.js | 4.4.1, vendored\" in docs\n    assert (root / \"licenses/Chart.js-MIT.txt\").is_file()\n    assert (root / \"frontend/static/vendor/chart.umd.min.js\").is_file()\n''',
)

print("v1.0.6 corrective patch applied")
