from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


manager = ROOT / "backend/services/manager_v2.py"
services_init = ROOT / "backend/services/__init__.py"
v103_contract = ROOT / "backend/tests/test_v103_release_contract.py"
v104_contract = ROOT / "backend/tests/test_v104_performance_architecture.py"

# Keep a process-local copy of the durable ownership ledger. External aria2
# ownership checks occur throughout the 1-second reconciliation path; querying
# the same UNION from SQLite on every check is unnecessary once bootstrapped.
replace_once(
    manager,
    """        self._aria2_ownership_lock = asyncio.Lock()\n        self._aria2_ownership_ready = False\n""",
    """        self._aria2_ownership_lock = asyncio.Lock()\n        self._aria2_ownership_ready = False\n        self._aria2_owned_gid_cache: Set[str] = set()\n""",
)
replace_once(
    manager,
    """    def reset_services(self):\n        self._ad = None\n        self._aria2 = None\n        self._sem = None\n""",
    """    def reset_services(self):\n        self._ad = None\n        self._aria2 = None\n        self._sem = None\n        # A settings/database transition may change the durable ownership\n        # source. Rebuild the cache lazily on the next external aria2 access.\n        self._aria2_ownership_ready = False\n        self._aria2_owned_gid_cache.clear()\n""",
)
replace_once(
    manager,
    """                await db.execute(\n                    \"\"\"INSERT INTO adc_aria2_owned_gids\n                           (gid, download_file_id, torrent_id)\n                       SELECT download_id, id, torrent_id\n                         FROM download_files\n                        WHERE download_client='aria2'\n                          AND download_id IS NOT NULL\n                       ON CONFLICT(gid) DO NOTHING\"\"\"\n                )\n                await db.commit()\n            self._aria2_ownership_ready = True\n""",
    """                await db.execute(\n                    \"\"\"INSERT INTO adc_aria2_owned_gids\n                           (gid, download_file_id, torrent_id)\n                       SELECT download_id, id, torrent_id\n                         FROM download_files\n                        WHERE download_client='aria2'\n                          AND download_id IS NOT NULL\n                       ON CONFLICT(gid) DO NOTHING\"\"\"\n                )\n                rows = await db.fetchall(\n                    \"\"\"SELECT gid\n                         FROM adc_aria2_owned_gids\n                        WHERE gid IS NOT NULL\n                       UNION\n                       SELECT download_id AS gid\n                         FROM download_files\n                        WHERE download_client='aria2'\n                          AND download_id IS NOT NULL\"\"\"\n                )\n                await db.commit()\n            self._aria2_owned_gid_cache = {\n                str(row[\"gid\"]).strip()\n                for row in rows\n                if str(row.get(\"gid\") or \"\").strip()\n            }\n            self._aria2_ownership_ready = True\n""",
)
replace_once(
    manager,
    """            await db.commit()\n\n    async def _aria2_owned_gids(self) -> Set[str]:\n        \"\"\"Return every GID ADC has recorded, including current legacy rows.\"\"\"\n        await self._ensure_aria2_ownership_table()\n        async with get_db() as db:\n            rows = await (\n                await db.execute(\n                    \"\"\"SELECT gid\n                         FROM adc_aria2_owned_gids\n                        WHERE gid IS NOT NULL\n                       UNION\n                       SELECT download_id AS gid\n                         FROM download_files\n                        WHERE download_client='aria2'\n                          AND download_id IS NOT NULL\"\"\"\n                )\n            ).fetchall()\n        return {\n            str(row[\"gid\"]).strip()\n            for row in rows\n            if str(row[\"gid\"] or \"\").strip()\n        }\n""",
    """            await db.commit()\n        self._aria2_owned_gid_cache.add(gid)\n\n    async def _aria2_owned_gids(self) -> Set[str]:\n        \"\"\"Return a copy of the durable DebridPulse aria2 ownership cache.\"\"\"\n        await self._ensure_aria2_ownership_table()\n        return set(self._aria2_owned_gid_cache)\n""",
)

# The dispatcher already has one authoritative snapshot at the top of the
# serialized dispatch pass. Reuse the ownership-filtered snapshot rather than
# asking aria2 for the same state again immediately before addUri calls.
replace_once(
    manager,
    """                for dl in excess:\n                    await self._remove_owned_aria2_gid(dl.gid)\n                in_flight = in_flight[:limit]\n""",
    """                for dl in excess:\n                    await self._remove_owned_aria2_gid(dl.gid)\n                owned_downloads = [\n                    dl for dl in owned_downloads if dl.gid not in excess_gids\n                ]\n                in_flight = in_flight[:limit]\n""",
)
replace_once(
    manager,
    """            # Snapshot of aria2 state for the whole dispatch batch.\n            # Passing this to ensure_download() avoids one get_all() call per\n            # file, which would cause a burst of rapid RPC requests that aria2\n            # may drop or answer inconsistently.\n            dispatch_snapshot = await self._aria2_get_all()\n            if not is_builtin_mode():\n                owned_gids = await self._aria2_owned_gids()\n                dispatch_snapshot = [\n                    dl for dl in dispatch_snapshot\n                    if str(dl.gid) in owned_gids\n                ]\n""",
    """            # Reuse the authoritative ownership-filtered snapshot from the\n            # start of this serialized dispatch pass. ensure_download() receives\n            # the same view used for slot accounting, eliminating a redundant\n            # active/waiting/stopped snapshot immediately before addUri.\n            dispatch_snapshot = list(owned_downloads)\n""",
)

# Replace the hidden import hook with explicit, ordered installation once the
# singleton exists. The behavior remains identical, but the dependency is now
# visible in the manager module and no longer modifies sys.meta_path.
replace_once(
    manager,
    "\n\nmanager = TorrentManager()\n",
    """\n\nmanager = TorrentManager()\n\n# Install singleton-only reliability coordinators explicitly after construction.\n# TorrentManager instances created by unit tests or future backend adapters remain\n# unmodified unless they opt into these coordinators themselves.\nfrom services.transfer_control import install_transfer_control as _install_transfer_control\nfrom services.pause_parent_status import install_parent_progress_guard as _install_parent_progress_guard\nfrom services.global_pause_semantics import install_global_pause_semantics as _install_global_pause_semantics\n\n_install_transfer_control(manager)\n_install_parent_progress_guard(manager)\n_install_global_pause_semantics(manager)\n\ndel _install_transfer_control\ndel _install_parent_progress_guard\ndel _install_global_pause_semantics\n""",
)
services_init.write_text(
    '"""DebridPulse service package.\n\nRuntime coordinators are installed explicitly after the shared manager singleton\nis constructed; importing this package has no process-wide import side effects.\n"""\n'
)

# Forward compatibility contract: retain the external aria2 policy guarantee,
# but require the now-explicit bootstrap rather than the temporary import hook.
v103_contract.write_text('''from pathlib import Path\n\n\nREPO_ROOT = Path(__file__).resolve().parents[2]\n\n\ndef test_v103_staging_candidate_preserves_external_aria2_global_policy():\n    version = tuple(\n        int(part)\n        for part in (REPO_ROOT / "VERSION").read_text().strip().split(".")\n    )\n    assert version >= (1, 0, 3)\n\n    control = (REPO_ROOT / "backend/services/transfer_control.py").read_text()\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n\n    assert "_install_transfer_control(manager)" in manager\n    assert "_install_parent_progress_guard(manager)" in manager\n    assert "_install_global_pause_semantics(manager)" in manager\n    assert not (REPO_ROOT / "backend/services/_control_bootstrap.py").exists()\n    assert "max-overall-download-limit" not in control\n    assert "change_global_options" not in control\n    assert "_aria2_owned_gids" in control\n    assert "Blocked attempt to remove foreign aria2 GID" not in control\n''')

with v104_contract.open("a") as f:
    f.write('''\n\ndef test_external_aria2_ownership_is_cached_after_durable_bootstrap():\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n    assert "self._aria2_owned_gid_cache: Set[str] = set()" in manager\n    assert "self._aria2_owned_gid_cache.add(gid)" in manager\n    owned = manager.split("async def _aria2_owned_gids", 1)[1].split(\n        "async def _aria2_owned_downloads", 1\n    )[0]\n    assert "return set(self._aria2_owned_gid_cache)" in owned\n    assert "SELECT gid" not in owned\n\n\ndef test_dispatch_reuses_initial_owned_aria2_snapshot():\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n    dispatch = manager.split("async def _dispatch_pending_aria2_queue", 1)[1].split(\n        "async def _schedule_ready_aria2_parents", 1\n    )[0]\n    assert "dispatch_snapshot = list(owned_downloads)" in dispatch\n    assert dispatch.count("await self._aria2_get_all()") == 1\n\n\ndef test_manager_control_bootstrap_is_explicit_not_import_hooked():\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n    services_init = (REPO_ROOT / "backend/services/__init__.py").read_text()\n    assert "_install_transfer_control(manager)" in manager\n    assert "_install_parent_progress_guard(manager)" in manager\n    assert "_install_global_pause_semantics(manager)" in manager\n    assert "install_import_hook" not in services_init\n''')

print("v1.0.4 phase-2 architecture refactor applied")
