from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_between(path: Path, start: str, end: str, replacement: str) -> None:
    text = path.read_text()
    start_at = text.find(start)
    if start_at < 0:
        raise SystemExit(f"{path}: start marker not found: {start!r}")
    end_at = text.find(end, start_at + len(start))
    if end_at < 0:
        raise SystemExit(f"{path}: end marker not found: {end!r}")
    if text.find(start, start_at + 1) >= 0:
        raise SystemExit(f"{path}: start marker is not unique")
    path.write_text(text[:start_at] + replacement + text[end_at:])


manager = ROOT / "backend/services/manager_v2.py"
contract = ROOT / "backend/tests/test_v104_performance_architecture.py"
tests_workflow = ROOT / ".github/workflows/tests.yml"
helper = ROOT / ".github/scripts/v104_phase4_refactor.py"

# Magnet/torrent preparation already receives a complete provider manifest with
# per-file source links. Do not unlock every file eagerly and then unlock it a
# second time when a delivery slot opens. Materialize the manifest locally in
# one transaction and leave URL generation to the slot-aware dispatcher.
replace_once(
    manager,
    """        work_items: List[Dict] = []\n        for file_info in flat_files:\n""",
    """        work_items: List[Dict] = []\n        manifest_rows: List[tuple] = []\n        for file_info in flat_files:\n""",
)
replace_once(
    manager,
    '''            if blocked:
                blocked_items.append({"filename": display_name, "size_bytes": file_size, "reason": reason})
                await self._log_file(torrent_id, display_name, source_link, str(local_path), "blocked", reason, file_size)
                continue
''',
    '''            if blocked:
                blocked_items.append({"filename": display_name, "size_bytes": file_size, "reason": reason})
                manifest_rows.append(
                    (
                        torrent_id,
                        display_name,
                        file_size,
                        source_link,
                        source_link,
                        str(local_path),
                        "blocked",
                        client_name,
                        1,
                        reason,
                    )
                )
                continue
''',
)

unlock_start = "        # ── Unlock links in parallel (rate-limited) ──────────────────────────\n"
unlock_end = "        blocked_count = len(blocked_items)\n"
manifest_stage = '''        # ── Materialize the provider manifest without eager URL generation ───
        # The dispatcher owns direct-URL generation because it knows which files
        # actually have an aria2 slot. Eagerly unlocking every manifest entry here
        # doubled provider API calls and made large cached torrents slow to queue.
        for item in work_items:
            display_name = item["display_name"]
            file_size = item["file_size"]
            source_link = item["source_link"]
            local_path = item["local_path"]

            if local_path.exists() and (
                file_size <= 0
                or local_path.stat().st_size >= max(file_size - 1024, 0)
            ):
                transferred_items.append(
                    {"filename": display_name, "size_bytes": file_size}
                )
                manifest_rows.append(
                    (
                        torrent_id,
                        display_name,
                        file_size,
                        source_link,
                        source_link,
                        str(local_path),
                        "completed",
                        client_name,
                        0,
                        None,
                    )
                )
                continue

            queued_items.append({"filename": display_name, "size_bytes": file_size})
            manifest_rows.append(
                (
                    torrent_id,
                    display_name,
                    file_size,
                    source_link,
                    source_link,
                    str(local_path),
                    "pending",
                    "aria2",
                    0,
                    None,
                )
            )

        if manifest_rows:
            async with get_db() as db:
                await db.executemany(
                    """INSERT INTO download_files
                       (torrent_id, filename, size_bytes, source_url,
                        download_url, local_path, status, download_id,
                        download_client, blocked, block_reason, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    manifest_rows,
                )
                await db.commit()

'''
replace_between(manager, unlock_start, unlock_end, manifest_stage)

# Preserve the old LINK_HOST_NOT_SUPPORTED semantics at the later slot-aware
# unlock point: unsupported provider files are filtered/blocked, not hard errors.
replace_once(
    manager,
    '''                if row["_err"]:
                    logger.error("aria2 dispatch failed [%s]: %s", row["filename"], row["_err"])
                    await self._update_file_state(row["file_id"], "error", row["local_path"], reason=str(row["_err"]))
                    await self._finalize_aria2_torrent(row["torrent_id"])
                    continue
''',
    '''                if row["_err"]:
                    error = row["_err"]
                    error_text = str(error)
                    provider_code = str(getattr(error, "code", "") or "")
                    if (
                        provider_code == "LINK_HOST_NOT_SUPPORTED"
                        or "LINK_HOST_NOT_SUPPORTED" in error_text
                    ):
                        logger.warning(
                            "aria2 dispatch blocked unsupported provider file [%s]: %s",
                            row["filename"],
                            error_text,
                        )
                        async with get_db() as db:
                            await db.execute(
                                """UPDATE download_files
                                   SET status='blocked', blocked=1, block_reason=?,
                                       download_id=NULL, updated_at=CURRENT_TIMESTAMP
                                   WHERE id=?""",
                                (error_text, row["file_id"]),
                            )
                            await db.commit()
                    else:
                        logger.error(
                            "aria2 dispatch failed [%s]: %s",
                            row["filename"],
                            error,
                        )
                        await self._update_file_state(
                            row["file_id"],
                            "error",
                            row["local_path"],
                            reason=error_text,
                        )
                    await self._finalize_aria2_torrent(row["torrent_id"])
                    continue
''',
)

with contract.open("a") as f:
    f.write('''\n\ndef test_magnet_materialization_defers_unlock_until_a_delivery_slot_exists():\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n    download = manager.split("async def _download(self, torrent_id", 1)[1].split(\n        "async def _fetch_ready_files", 1\n    )[0]\n    assert "Materialize the provider manifest without eager URL generation" in download\n    assert "unlock_results = await asyncio.gather" not in download\n    assert "manifest_rows: List[tuple] = []" in download\n    assert "source_url," in download\n    assert download.count("await db.executemany(") >= 1\n\n    dispatcher = manager.split("async def _dispatch_pending_aria2_queue", 1)[1].split(\n        "async def _schedule_ready_aria2_parents", 1\n    )[0]\n    assert "await _retry_async(self.ad().unlock_link, sl)" in dispatcher\n    assert 'provider_code == "LINK_HOST_NOT_SUPPORTED"' in dispatcher\n    assert "SET status='blocked', blocked=1" in dispatcher\n''')

# Restore the ordinary read-only workflow in the validated commit and remove
# this helper before tests inspect the resulting release tree.
tests_workflow.write_text('''name: Tests\n\non:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\njobs:\n  test:\n    runs-on: ubuntu-latest\n    env:\n      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true\n\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v5\n\n      - name: Set up Python 3.12\n        uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n          cache: 'pip'\n          cache-dependency-path: |\n            backend/requirements.txt\n            backend/requirements-dev.txt\n\n      - name: Install dependencies\n        run: |\n          cd backend\n          pip install -r requirements-dev.txt\n\n      - name: Run all tests\n        run: |\n          cd backend\n          python -m pytest tests/ -v --tb=short\n\n      - name: Check Python syntax (all service files)\n        run: |\n          cd backend\n          python -m py_compile \\\n            api/routes.py \\\n            core/config.py \\\n            core/config_validator.py \\\n            core/scheduler.py \\\n            db/database.py \\\n            db/migration.py \\\n            main.py \\\n            services/alldebrid.py \\\n            services/aria2.py \\\n            services/backup.py \\\n            services/db_maintenance.py \\\n            services/manager_v2.py \\\n            services/notifications.py \\\n            services/stats.py\n          echo "All files syntax OK"\n\n      - name: Check frontend JavaScript syntax\n        run: node --check frontend/static/app.js\n\n  security:\n    runs-on: ubuntu-latest\n    env:\n      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true\n    needs: test\n\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v5\n\n      - name: Set up Python 3.12\n        uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n          cache: 'pip'\n          cache-dependency-path: backend/requirements.txt\n\n      - name: Install dependencies + audit tools\n        run: |\n          cd backend\n          pip install -r requirements.txt\n          pip install pip-audit bandit\n\n      - name: pip-audit (known CVEs in dependencies)\n        run: |\n          cd backend\n          pip-audit -r requirements.txt --progress-spinner off\n\n      - name: bandit (Python security linting)\n        run: |\n          cd backend\n          bandit -r . \\\n            --exclude ./tests \\\n            --severity-level medium \\\n            --confidence-level medium \\\n            -f txt \\\n            || true   # advisory only — does not fail the build\n''')
helper.unlink()

print("v1.0.4 slot-aware provider unlock refactor applied")
