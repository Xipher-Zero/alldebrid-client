from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


manager = ROOT / "backend/services/manager_v2.py"
scheduler = ROOT / "backend/core/scheduler.py"
main = ROOT / "backend/main.py"
contract = ROOT / "backend/tests/test_v104_performance_architecture.py"
tests_workflow = ROOT / ".github/workflows/tests.yml"
helper = ROOT / ".github/scripts/v104_phase3_refactor.py"

# Let import/full reconciliation consume a caller-supplied provider snapshot.
replace_once(
    manager,
    "    async def import_existing_magnets(self) -> List[dict]:\n",
    "    async def import_existing_magnets(\n        self, all_magnets: Optional[List[Dict]] = None\n    ) -> List[dict]:\n",
)
replace_once(
    manager,
    '''        try:
            all_magnets = await self.ad().get_magnet_status()
        except Exception as exc:
            error = str(exc)
            if any(keyword in error for keyword in ("DISCONTINUED", "discontinued", "deprecated", "migrate")):
                raise Exception("AllDebrid has disabled 'list all magnets' for your account. Add magnets manually through the DebridPulse UI.")
            raise

        if not all_magnets:
''',
    '''        if all_magnets is None:
            try:
                all_magnets = await self.ad().get_magnet_status()
            except Exception as exc:
                error = str(exc)
                if any(keyword in error for keyword in ("DISCONTINUED", "discontinued", "deprecated", "migrate")):
                    raise Exception("AllDebrid has disabled 'list all magnets' for your account. Add magnets manually through the DebridPulse UI.")
                raise

        if not all_magnets:
''',
)
replace_once(
    manager,
    "    async def full_alldebrid_sync(self) -> int:\n",
    "    async def full_alldebrid_sync(\n        self, all_magnets: Optional[List[Dict]] = None\n    ) -> int:\n",
)
replace_once(
    manager,
    '''        try:
            all_magnets = await self.ad().get_magnet_status()
        except Exception as exc:
            logger.warning("full_alldebrid_sync: could not fetch magnets: %s", exc)
            return 0

        if not all_magnets:
''',
    '''        if all_magnets is None:
            try:
                all_magnets = await self.ad().get_magnet_status()
            except Exception as exc:
                logger.warning("full_alldebrid_sync: could not fetch magnets: %s", exc)
                return 0

        if not all_magnets:
''',
)

# One provider-inventory cycle now performs one provider bulk request and shares
# that immutable snapshot between import discovery and full reconciliation.
replace_once(
    manager,
    "    async def full_alldebrid_sync(\n        self, all_magnets: Optional[List[Dict]] = None\n    ) -> int:\n",
    '''    async def reconcile_provider_inventory(self) -> dict:
        """Run one provider inventory cycle from one authoritative bulk snapshot."""
        if self.is_paused() or not get_settings().alldebrid_api_key:
            return {"imported": 0, "updated": 0, "snapshot_count": 0}

        try:
            all_magnets = await self.ad().get_magnet_status()
        except Exception as exc:
            error = str(exc)
            if any(
                keyword in error
                for keyword in (
                    "DISCONTINUED",
                    "discontinued",
                    "deprecated",
                    "migrate",
                )
            ):
                raise Exception(
                    "AllDebrid has disabled 'list all magnets' for your account. "
                    "Add magnets manually through the DebridPulse UI."
                ) from exc
            raise

        imported = await self.import_existing_magnets(all_magnets=all_magnets)
        updated = await self.full_alldebrid_sync(all_magnets=all_magnets)
        return {
            "imported": len(imported),
            "updated": int(updated or 0),
            "snapshot_count": len(all_magnets or []),
        }

    async def full_alldebrid_sync(
        self, all_magnets: Optional[List[Dict]] = None
    ) -> int:
''',
)

# Instrument the actual high-frequency scheduler domains and make the full
# inventory loop call the new one-snapshot manager entry point.
replace_once(
    scheduler,
    "from core.logging_utils import sanitize_exception\n",
    "from core.logging_utils import sanitize_exception\nfrom core.performance import async_timer\n",
)
replace_once(
    scheduler,
    '''        try:
            await manager.sync_alldebrid_status()
        except Exception as e:
            logger.error(f"Status sync error: {e}")
''',
    '''        try:
            async with async_timer("scheduler.provider_poll"):
                await manager.sync_alldebrid_status()
        except Exception as e:
            logger.error(f"Status sync error: {e}")
''',
)
replace_once(
    scheduler,
    '''        try:
            await manager.import_existing_magnets()
        except Exception as e:
            logger.error("Existing magnet import failed: %s", sanitize_exception(e))
        try:
            await manager.full_alldebrid_sync()
        except Exception as e:
            logger.error(f"Full sync error: {e}")
''',
    '''        try:
            async with async_timer("scheduler.provider_inventory"):
                result = await manager.reconcile_provider_inventory()
            if result.get("imported") or result.get("updated"):
                logger.info(
                    "Provider inventory: %d imported, %d reconciled from %d item(s)",
                    int(result.get("imported") or 0),
                    int(result.get("updated") or 0),
                    int(result.get("snapshot_count") or 0),
                )
        except Exception as e:
            logger.error("Provider inventory sync failed: %s", sanitize_exception(e))
''',
)
replace_once(
    scheduler,
    '''        try:
            await manager.sync_download_clients()
        except Exception as e:
            logger.error(f"Download client sync error: {e}")
''',
    '''        try:
            async with async_timer("scheduler.download_client_sync"):
                await manager.sync_download_clients()
        except Exception as e:
            logger.error(f"Download client sync error: {e}")
''',
)

# Cleanly close the persistent PostgreSQL pool during application shutdown.
replace_once(
    main,
    '''    try:
        await aria2_runtime.stop()
    except Exception as e:
        logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(e))


app = FastAPI(
''',
    '''    try:
        await aria2_runtime.stop()
    except Exception as e:
        logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(e))
    try:
        from db.database import close_db_runtime
        await close_db_runtime()
    except Exception as e:
        logger.warning("Database runtime shutdown failed: %s", sanitize_exception(e))


app = FastAPI(
''',
)

with contract.open("a") as f:
    f.write('''\n\ndef test_full_provider_inventory_reuses_one_bulk_snapshot():\n    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()\n    reconcile = manager.split("async def reconcile_provider_inventory", 1)[1].split(\n        "async def full_alldebrid_sync", 1\n    )[0]\n    assert reconcile.count("get_magnet_status()") == 1\n    assert "import_existing_magnets(all_magnets=all_magnets)" in reconcile\n    assert "full_alldebrid_sync(all_magnets=all_magnets)" in reconcile\n\n    imported = manager.split("async def import_existing_magnets", 1)[1].split(\n        "async def delete_torrent", 1\n    )[0]\n    full = manager.split("async def full_alldebrid_sync", 1)[1].split(\n        "async def sync_alldebrid_status", 1\n    )[0]\n    assert "if all_magnets is None:" in imported\n    assert "if all_magnets is None:" in full\n\n\ndef test_scheduler_profiles_provider_and_download_domains():\n    scheduler = (REPO_ROOT / "backend/core/scheduler.py").read_text()\n    assert 'async_timer("scheduler.provider_poll")' in scheduler\n    assert 'async_timer("scheduler.provider_inventory")' in scheduler\n    assert 'async_timer("scheduler.download_client_sync")' in scheduler\n    assert "await manager.reconcile_provider_inventory()" in scheduler\n    full_loop = scheduler.split("async def full_sync_loop", 1)[1].split(\n        "async def sync_download_clients_loop", 1\n    )[0]\n    assert "import_existing_magnets" not in full_loop\n    assert "full_alldebrid_sync" not in full_loop\n\n\ndef test_lifespan_closes_database_runtime_pool():\n    main = (REPO_ROOT / "backend/main.py").read_text()\n    shutdown = main.split('logger.info("Shutting down %s...", APP_NAME)', 1)[1].split(\n        "app = FastAPI(", 1\n    )[0]\n    assert "from db.database import close_db_runtime" in shutdown\n    assert "await close_db_runtime()" in shutdown\n''')

# The temporary workflow is replaced with the normal read-only CI definition in
# the validated source commit, and the helper removes itself before tests run.
tests_workflow.write_text('''name: Tests\n\non:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\njobs:\n  test:\n    runs-on: ubuntu-latest\n    env:\n      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true\n\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v5\n\n      - name: Set up Python 3.12\n        uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n          cache: 'pip'\n          cache-dependency-path: |\n            backend/requirements.txt\n            backend/requirements-dev.txt\n\n      - name: Install dependencies\n        run: |\n          cd backend\n          pip install -r requirements-dev.txt\n\n      - name: Run all tests\n        run: |\n          cd backend\n          python -m pytest tests/ -v --tb=short\n\n      - name: Check Python syntax (all service files)\n        run: |\n          cd backend\n          python -m py_compile \\\n            api/routes.py \\\n            core/config.py \\\n            core/config_validator.py \\\n            core/scheduler.py \\\n            db/database.py \\\n            db/migration.py \\\n            main.py \\\n            services/alldebrid.py \\\n            services/aria2.py \\\n            services/backup.py \\\n            services/db_maintenance.py \\\n            services/manager_v2.py \\\n            services/notifications.py \\\n            services/stats.py\n          echo "All files syntax OK"\n\n      - name: Check frontend JavaScript syntax\n        run: node --check frontend/static/app.js\n\n  security:\n    runs-on: ubuntu-latest\n    env:\n      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true\n    needs: test\n\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v5\n\n      - name: Set up Python 3.12\n        uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n          cache: 'pip'\n          cache-dependency-path: backend/requirements.txt\n\n      - name: Install dependencies + audit tools\n        run: |\n          cd backend\n          pip install -r requirements.txt\n          pip install pip-audit bandit\n\n      - name: pip-audit (known CVEs in dependencies)\n        run: |\n          cd backend\n          pip-audit -r requirements.txt --progress-spinner off\n\n      - name: bandit (Python security linting)\n        run: |\n          cd backend\n          bandit -r . \\\n            --exclude ./tests \\\n            --severity-level medium \\\n            --confidence-level medium \\\n            -f txt \\\n            || true   # advisory only — does not fail the build\n''')
helper.unlink()

print("v1.0.4 provider/scheduler lifecycle refactor applied")
