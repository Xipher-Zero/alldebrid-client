from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}: {old[:120]!r}"
        )
    p.write_text(text.replace(old, new), encoding="utf-8")


def append_exact(path: str, marker: str, addition: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if addition.strip() in text:
        raise SystemExit(f"{path}: addition already present")
    if marker not in text:
        raise SystemExit(f"{path}: marker missing: {marker!r}")
    p.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


manager_path = "backend/services/manager_v2.py"
app_path = "frontend/static/app.js"
test_path = "backend/tests/test_ui_responsiveness.py"

# ---------------------------------------------------------------------------
# Backend: make freshness timestamps represent actual state/progress changes.
# ---------------------------------------------------------------------------

replace_exact(
    manager_path,
    'SELECT id, name, alldebrid_id, status, provider_status, provider_status_code, polling_failures, magnet, source',
    'SELECT id, name, alldebrid_id, status, provider_status, provider_status_code, polling_failures, progress, size_bytes, magnet, source',
    expected=2,
)

replace_exact(
    manager_path,
    'cur = await db.execute("SELECT id, status FROM torrents WHERE hash=?", (hash_value,))',
    'cur = await db.execute(\n'
    '                    "SELECT id, status, name, alldebrid_id, provider_status, "\n'
    '                    "provider_status_code, download_client FROM torrents WHERE hash=?",\n'
    '                    (hash_value,),\n'
    '                )',
)

replace_exact(
    manager_path,
    '''                if existing:\n                    torrent_id = existing["id"]\n                    local_status = existing["status"]\n                    if local_status == "completed":''',
    '''                if existing:\n                    torrent_id = existing["id"]\n                    local_status = existing["status"]\n                    current_download_client = self.download_client_name()\n                    current_provider_code = existing.get("provider_status_code")\n                    metadata_changed = (\n                        str(existing.get("name") or "") != str(name or "")\n                        or str(existing.get("alldebrid_id") or "") != ad_id\n                        or str(existing.get("provider_status") or "")\n                        != str(normalized["provider_status"] or "")\n                        or int(current_provider_code if current_provider_code is not None else -1)\n                        != int(normalized["status_code"])\n                        or str(existing.get("download_client") or "")\n                        != current_download_client\n                    )\n                    if local_status == "completed":''',
)

replace_exact(
    manager_path,
    '''                    elif local_status in ("queued", "downloading", "paused"):\n                        # Already actively downloading — do not re-dispatch;\n                        # sync_aria2_downloads / _dispatch_pending_aria2_queue handle it\n                        should_queue = False\n                        await db.execute(\n                            """UPDATE torrents\n                               SET name=?, alldebrid_id=?, provider_status=?, provider_status_code=?, download_client=?, updated_at=CURRENT_TIMESTAMP\n                               WHERE id=?""",\n                            (name, ad_id, normalized["provider_status"], normalized["status_code"], self.download_client_name(), torrent_id),\n                        )\n                    else:\n                        # Non-terminal, not actively downloading (uploading/processing/ready/error/pending)\n                        # → update and allow re-dispatch if AllDebrid says ready\n                        await db.execute(\n                            """UPDATE torrents\n                               SET name=?, alldebrid_id=?, provider_status=?, provider_status_code=?, download_client=?, updated_at=CURRENT_TIMESTAMP\n                               WHERE id=?""",\n                            (name, ad_id, normalized["provider_status"], normalized["status_code"], self.download_client_name(), torrent_id),\n                        )''',
    '''                    elif local_status in ("queued", "downloading", "paused"):\n                        # Already actively downloading — do not re-dispatch;\n                        # sync_aria2_downloads / _dispatch_pending_aria2_queue handle it.\n                        # A metadata no-op must not refresh updated_at because the\n                        # stuck-transfer watchdog uses that timestamp as real activity.\n                        should_queue = False\n                        if metadata_changed:\n                            await db.execute(\n                                """UPDATE torrents\n                                   SET name=?, alldebrid_id=?, provider_status=?, provider_status_code=?, download_client=?, updated_at=CURRENT_TIMESTAMP\n                                   WHERE id=?""",\n                                (name, ad_id, normalized["provider_status"], normalized["status_code"], current_download_client, torrent_id),\n                            )\n                    else:\n                        # Non-terminal, not actively downloading (uploading/processing/ready/error/pending)\n                        # → update metadata only when it actually changed. Stable provider\n                        # polling must not keep a stuck transfer artificially fresh.\n                        if metadata_changed:\n                            await db.execute(\n                                """UPDATE torrents\n                                   SET name=?, alldebrid_id=?, provider_status=?, provider_status_code=?, download_client=?, updated_at=CURRENT_TIMESTAMP\n                                   WHERE id=?""",\n                                (name, ad_id, normalized["provider_status"], normalized["status_code"], current_download_client, torrent_id),\n                            )''',
)

replace_exact(
    manager_path,
    '''                              f.id AS file_id, f.filename, f.local_path, f.download_url,\n                              f.download_id, f.status, f.blocked''',
    '''                              f.id AS file_id, f.filename, f.local_path, f.download_url,\n                              f.download_id, f.status, f.blocked, f.size_bytes''',
)

replace_exact(
    manager_path,
    '''            # Status sync from aria2\n            sz = dl.total_length if dl.total_length > 0 else None\n            if dl.status == "paused":\n                await self._update_file_state(row["file_id"], "paused", row["local_path"], size_bytes=sz)\n            elif dl.status == "waiting":\n                await self._update_file_state(row["file_id"], "queued", row["local_path"], size_bytes=sz)\n            elif dl.status == "active":\n                await self._update_file_state(row["file_id"], "downloading", row["local_path"], size_bytes=sz)\n            elif dl.status == "complete":''',
    '''            # Status sync from aria2. Avoid rewriting stable rows every poll;\n            # download_files.updated_at should advance only for a real state/size change.\n            sz = dl.total_length if dl.total_length > 0 else None\n            current_file_status = str(row["status"] or "")\n            current_file_size = int(row["size_bytes"] or 0)\n            size_changed = sz is not None and int(sz) != current_file_size\n\n            def file_state_needs_update(desired_status: str) -> bool:\n                return desired_status != current_file_status or size_changed\n\n            if dl.status == "paused":\n                if file_state_needs_update("paused"):\n                    await self._update_file_state(row["file_id"], "paused", row["local_path"], size_bytes=sz)\n            elif dl.status == "waiting":\n                if file_state_needs_update("queued"):\n                    await self._update_file_state(row["file_id"], "queued", row["local_path"], size_bytes=sz)\n            elif dl.status == "active":\n                if file_state_needs_update("downloading"):\n                    await self._update_file_state(row["file_id"], "downloading", row["local_path"], size_bytes=sz)\n            elif dl.status == "complete":''',
)

replace_exact(
    manager_path,
    '''            progress_changed = int(progress) != int(current_progress)\n            status_changed = parent_status != current_status\n\n            if progress_changed or status_changed:\n                broadcast_needed = True\n                changed_updates.append(\n                    {\n                        "id": int(torrent_id),\n                        "progress": progress,\n                        "status": parent_status,\n                        "status_changed": status_changed,\n                    }\n                )\n\n            updates.append((progress, parent_status, torrent_id))\n\n        if not updates:\n            return\n\n        async with get_db() as db:\n            for progress, parent_status, torrent_id in updates:\n                await db.execute(\n                    """UPDATE torrents\n                       SET progress=?, status=?, updated_at=CURRENT_TIMESTAMP\n                       WHERE id=?\n                         AND status IN ('queued', 'downloading', 'paused')""",\n                    (progress, parent_status, torrent_id),\n                )\n            await db.commit()''',
    '''            # Persist any real progress movement so updated_at continues to\n            # represent transfer activity. SSE remains integer-boundary based to\n            # avoid UI churn for sub-percent movement.\n            persist_progress_changed = progress != current_progress\n            broadcast_progress_changed = int(progress) != int(current_progress)\n            status_changed = parent_status != current_status\n\n            if persist_progress_changed or status_changed:\n                updates.append((progress, parent_status, torrent_id))\n\n            if broadcast_progress_changed or status_changed:\n                broadcast_needed = True\n                changed_updates.append(\n                    {\n                        "id": int(torrent_id),\n                        "progress": progress,\n                        "status": parent_status,\n                        "status_changed": status_changed,\n                    }\n                )\n\n        if not updates:\n            return\n\n        async with get_db() as db:\n            await db.executemany(\n                """UPDATE torrents\n                   SET progress=?, status=?, updated_at=CURRENT_TIMESTAMP\n                   WHERE id=?\n                     AND status IN ('queued', 'downloading', 'paused')""",\n                updates,\n            )\n            await db.commit()''',
)

provider_old = '''    async def _apply_provider_update(self, row: Dict, magnet: Dict, normalized: Dict[str, object]):\n        provider_status = str(normalized["provider_status"])\n        local_status    = str(normalized["local_status"])   # always a plain string from normalize_provider_state\n        status_code = int(normalized["status_code"])\n        progress = float(normalized["progress"])\n        size_bytes = int(normalized["size_bytes"])\n        provider_message = str(normalized["message"])\n        current_status = row["status"]\n        provider_state_changed = provider_status != (row["provider_status"] or "") or status_code != int(row["provider_status_code"] or -1)\n        persisted_status = current_status if current_status in {"queued", "downloading", "paused"} and provider_status == "ready" else local_status\n\n        async with get_db() as db:\n            if provider_state_changed:\n                await db.execute(\n                    "INSERT INTO events (torrent_id, level, message) VALUES (?, ?, ?)",\n                    (row["id"], "info", f"AllDebrid status -> {provider_status} [{status_code}] {provider_message}".strip()),\n                )\n            await db.execute(\n                """UPDATE torrents\n                   SET status=?, provider_status=?, provider_status_code=?, progress=?, size_bytes=?,\n                       polling_failures=0, updated_at=CURRENT_TIMESTAMP\n                   WHERE id=?""",\n                (persisted_status, provider_status, status_code, progress, size_bytes, row["id"]),\n            )\n            await db.commit()\n\n        # SSE: provider progress update\n        # The dashboard already listens for torrent_updated and reloads the\n        # Recent Activity row. Emit after every provider poll that was applied.\n        try:\n            from api.routes import _sse_broadcast\n            status_changed = persisted_status != current_status\n            progress_item = {\n                "id": row["id"],\n                "status": persisted_status,\n                "name": str(row["name"] or ""),\n                "progress": progress,\n                "status_changed": status_changed,\n            }\n            await _sse_broadcast(\n                "torrent_updated",\n                {\n                    **progress_item,\n                    "progress_only": not status_changed,\n                    "items": [progress_item],\n                },\n            )\n        except Exception as exc:\n            logger.debug(\n                "Provider progress SSE broadcast failed for torrent %s: %s",\n                row["id"],\n                exc,\n            )\n\n'''

provider_new = '''    async def _apply_provider_update(self, row: Dict, magnet: Dict, normalized: Dict[str, object]):\n        provider_status = str(normalized["provider_status"])\n        local_status    = str(normalized["local_status"])   # always a plain string from normalize_provider_state\n        status_code = int(normalized["status_code"])\n        progress = float(normalized["progress"])\n        size_bytes = int(normalized["size_bytes"])\n        provider_message = str(normalized["message"])\n        current_status = row["status"]\n        current_progress = float(row.get("progress") or 0.0)\n        current_size_bytes = int(row.get("size_bytes") or 0)\n        provider_state_changed = (\n            provider_status != (row["provider_status"] or "")\n            or status_code != int(row["provider_status_code"] or -1)\n        )\n        local_delivery_active = (\n            current_status in {"queued", "downloading", "paused"}\n            and provider_status == "ready"\n        )\n        persisted_status = current_status if local_delivery_active else local_status\n        # Once provider preparation is complete, aria2 owns local transfer\n        # progress/size. A full provider reconciliation must not overwrite that\n        # live local telemetry with AllDebrid's already-ready 100% state.\n        persisted_progress = current_progress if local_delivery_active else progress\n        persisted_size_bytes = (\n            current_size_bytes\n            if local_delivery_active and current_size_bytes > 0\n            else size_bytes\n        )\n        status_changed = persisted_status != current_status\n        progress_changed = abs(persisted_progress - current_progress) > 1e-6\n        size_changed = persisted_size_bytes != current_size_bytes\n        polling_failures_present = int(row.get("polling_failures") or 0) != 0\n        meaningful_changed = (\n            provider_state_changed\n            or status_changed\n            or progress_changed\n            or size_changed\n            or polling_failures_present\n        )\n\n        if meaningful_changed:\n            async with get_db() as db:\n                if provider_state_changed:\n                    await db.execute(\n                        "INSERT INTO events (torrent_id, level, message) VALUES (?, ?, ?)",\n                        (row["id"], "info", f"AllDebrid status -> {provider_status} [{status_code}] {provider_message}".strip()),\n                    )\n                await db.execute(\n                    """UPDATE torrents\n                       SET status=?, provider_status=?, provider_status_code=?, progress=?, size_bytes=?,\n                           polling_failures=0, updated_at=CURRENT_TIMESTAMP\n                       WHERE id=?""",\n                    (\n                        persisted_status,\n                        provider_status,\n                        status_code,\n                        persisted_progress,\n                        persisted_size_bytes,\n                        row["id"],\n                    ),\n                )\n                await db.commit()\n\n        visible_changed = (\n            provider_state_changed\n            or status_changed\n            or progress_changed\n            or size_changed\n        )\n\n        # SSE is emitted only for a visible change. Stable provider polling no\n        # longer generates a write + broadcast cycle merely to say nothing changed.\n        if visible_changed:\n            try:\n                from api.routes import _sse_broadcast\n                progress_item = {\n                    "id": row["id"],\n                    "status": persisted_status,\n                    "name": str(row["name"] or ""),\n                    "progress": persisted_progress,\n                    "status_changed": status_changed,\n                }\n                await _sse_broadcast(\n                    "torrent_updated",\n                    {\n                        **progress_item,\n                        "progress_only": not (\n                            status_changed\n                            or provider_state_changed\n                            or size_changed\n                        ),\n                        "items": [progress_item],\n                    },\n                )\n            except Exception as exc:\n                logger.debug(\n                    "Provider progress SSE broadcast failed for torrent %s: %s",\n                    row["id"],\n                    exc,\n                )\n\n'''
replace_exact(manager_path, provider_old, provider_new)

# ---------------------------------------------------------------------------
# Frontend: eliminate redundant queue fetches and reduce interaction churn.
# ---------------------------------------------------------------------------

replace_exact(
    app_path,
    '''let torrentTotal = 0;\nlet settingsData = {};''',
    '''let torrentTotal = 0;\nlet _torrentSearchTimer = null;\nlet settingsData = {};''',
)

replace_exact(
    app_path,
    '''function setFilter(el, status) {\n  document.querySelectorAll('.ftab').forEach(t=>t.classList.remove('active'));\n  el.classList.add('active');\n  currentFilter = status; torrentPage = 1;\n  loadTorrents();\n}\n\nfunction onTorrentSearchInput() {\n  currentTorrentSearch = (document.getElementById('torrent-search')?.value || '').trim();\n  torrentPage = 1; loadTorrents();\n}''',
    '''function setFilter(el, status) {\n  document.querySelectorAll('#view-torrents .filter-tabs .ftab').forEach(t=>t.classList.remove('active'));\n  el.classList.add('active');\n  currentFilter = status; torrentPage = 1;\n  if (_torrentSearchTimer) {\n    clearTimeout(_torrentSearchTimer);\n    _torrentSearchTimer = null;\n  }\n  loadTorrents();\n}\n\nfunction onTorrentSearchInput() {\n  currentTorrentSearch = (document.getElementById('torrent-search')?.value || '').trim();\n  torrentPage = 1;\n  if (_torrentSearchTimer) clearTimeout(_torrentSearchTimer);\n  _torrentSearchTimer = setTimeout(() => {\n    _torrentSearchTimer = null;\n    loadTorrents().catch(()=>{});\n  }, 250);\n}''',
)

replace_exact(
    app_path,
    '''  if (id === 'tab-download') {\n    loadAria2Runtime().catch(()=>{});\n    aria2DownloadsTimer = setInterval(() => {''',
    '''  if (id === 'tab-download') {\n    loadAria2Runtime().catch(()=>{});\n    loadAria2Downloads().catch(()=>{});\n    aria2DownloadsTimer = setInterval(() => {''',
)

replace_exact(
    app_path,
    '''async function loadAria2Runtime() {\n  try {\n    const data = await api('GET', '/aria2/runtime');\n    renderAria2Runtime(data);\n    loadAria2Downloads().catch(()=>{});\n    const badge = document.getElementById('aria2-speed-badge');''',
    '''async function loadAria2Runtime() {\n  try {\n    const data = await api('GET', '/aria2/runtime');\n    renderAria2Runtime(data);\n    const badge = document.getElementById('aria2-speed-badge');''',
)

# ---------------------------------------------------------------------------
# Regression coverage.
# ---------------------------------------------------------------------------

p = ROOT / test_path
tests = p.read_text(encoding="utf-8")
addition = r'''


def test_pass3_polling_noops_do_not_refresh_transfer_freshness():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()

    provider = manager.split(
        "async def _apply_provider_update", 1
    )[1].split(
        "async def _set_provider_missing", 1
    )[0]

    assert "meaningful_changed = (" in provider
    assert "if meaningful_changed:" in provider
    assert "if visible_changed:" in provider
    assert "persisted_progress = current_progress if local_delivery_active else progress" in provider
    assert "stable provider polling" in provider.lower()

    aggregate = manager.split(
        "async def _update_aria2_parent_progress", 1
    )[1].split(
        "async def _update_file_state", 1
    )[0]

    assert "persist_progress_changed = progress != current_progress" in aggregate
    assert "broadcast_progress_changed = int(progress) != int(current_progress)" in aggregate
    assert "await db.executemany(" in aggregate
    assert "updates.append((progress, parent_status, torrent_id))" in aggregate

    sync = manager.split(
        "async def sync_aria2_downloads", 1
    )[1].split(
        "async def _reset_torrent_for_redownload", 1
    )[0]

    assert "f.download_id, f.status, f.blocked, f.size_bytes" in sync
    assert "def file_state_needs_update(desired_status: str)" in sync


def test_pass3_import_reconciliation_does_not_touch_stable_rows():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    imported = manager.split(
        "async def import_existing_magnets", 1
    )[1].split(
        "async def delete_torrent", 1
    )[0]

    assert "metadata_changed = (" in imported
    assert imported.count("if metadata_changed:") == 2
    assert "stuck-transfer watchdog" in imported
    assert "Stable provider" in imported


def test_pass3_frontend_queue_requests_search_and_filter_scope():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    runtime = js.split(
        "async function loadAria2Runtime()", 1
    )[1].split(
        "async function aria2RuntimeAction", 1
    )[0]
    assert "loadAria2Downloads" not in runtime

    switcher = js.split(
        "function switchSettingsTab", 1
    )[1].split(
        "function updateSettingsFooterActions", 1
    )[0]
    assert "loadAria2Runtime().catch(()=>{});" in switcher
    assert "loadAria2Downloads().catch(()=>{});" in switcher

    search = js.split(
        "function onTorrentSearchInput()", 1
    )[1].split(
        "async function loadTorrents()", 1
    )[0]
    assert "_torrentSearchTimer" in search
    assert "}, 250);" in search

    filter_fn = js.split(
        "function setFilter(el, status)", 1
    )[1].split(
        "function onTorrentSearchInput", 1
    )[0]
    assert "#view-torrents .filter-tabs .ftab" in filter_fn
    assert "document.querySelectorAll('.ftab')" not in filter_fn
'''
if "test_pass3_polling_noops_do_not_refresh_transfer_freshness" in tests:
    raise SystemExit(f"{test_path}: pass3 tests already present")
p.write_text(tests.rstrip() + addition + "\n", encoding="utf-8")

# Changelog: record the pass under the existing 1.0.2 responsiveness section.
append_exact(
    "CHANGELOG.md",
    "- Added frontend cache-busting and regression coverage for the responsiveness contract.\n",
    "- Reduced no-op provider/aria2 database writes and SSE churn so transfer freshness reflects real progress.\n"
    "- Removed redundant aria2 queue fetches, debounced download search input, and scoped download filters to their own view.\n",
)

# ---------------------------------------------------------------------------
# Final static contracts before the workflow is allowed to commit anything.
# ---------------------------------------------------------------------------
manager = (ROOT / manager_path).read_text(encoding="utf-8")
js = (ROOT / app_path).read_text(encoding="utf-8")

checks = {
    "provider no-op guard": "if meaningful_changed:" in manager,
    "provider active progress preserved": "persisted_progress = current_progress if local_delivery_active else progress" in manager,
    "aggregate actual-change persistence": "persist_progress_changed = progress != current_progress" in manager,
    "aggregate batched writes": "await db.executemany(" in manager,
    "aria2 file no-op guard": "def file_state_needs_update(desired_status: str)" in manager,
    "import metadata no-op guard": manager.count("if metadata_changed:") >= 2,
    "search debounce": "}, 250);" in js and "_torrentSearchTimer" in js,
    "scoped download filters": "#view-torrents .filter-tabs .ftab" in js,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("pass3 contract failed: " + ", ".join(failed))

print("PASS3 PATCH CONTRACT: PASS")
for name in checks:
    print("  PASS", name)
