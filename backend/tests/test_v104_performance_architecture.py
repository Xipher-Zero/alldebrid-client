from pathlib import Path

from services.aria2 import Aria2Service


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v104_version_and_performance_instrumentation_are_present():
    assert (REPO_ROOT / "VERSION").read_text().strip() == "1.0.4"
    performance = (REPO_ROOT / "backend/core/performance.py").read_text()
    assert "def snapshot()" in performance
    assert "def observe(" in performance


def test_aria2_hot_state_snapshots_use_one_multicall_transport_path():
    aria2 = (REPO_ROOT / "backend/services/aria2.py").read_text()
    assert '"system.multicall"' in aria2
    assert "async def _multicall(" in aria2
    assert "self._rpc_multicall_requests" in aria2
    assert "method_call_weight=len(methods)" in aria2


def test_multicall_auth_token_is_applied_to_each_nested_method():
    service = Aria2Service(
        "http://localhost:6800/jsonrpc",
        secret="secret-value",
    )
    assert service._authorized_params(["gid"]) == ["token:secret-value", "gid"]


def test_database_runtime_pools_postgres_but_keeps_sqlite_transactions_local():
    database = (REPO_ROOT / "backend/db/database.py").read_text()
    assert "asyncpg.create_pool(" in database
    assert "async with pool.acquire() as conn:" in database
    assert "async with aiosqlite.connect(DB_PATH, timeout=30) as conn:" in database
    assert "await _configure_sqlite_connection(conn)" in database
    assert "class _SQLitePool" not in database


def test_hot_queue_indexes_cover_pending_dispatch_and_gid_lookup():
    database = (REPO_ROOT / "backend/db/database.py").read_text()
    assert "idx_dlfiles_queue" in database
    assert "idx_dlfiles_download_id" in database
    assert "idx_torrents_status_priority" in database


def test_provider_polling_no_longer_nests_download_client_reconciliation():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    sync = manager.split("async def sync_alldebrid_status(self):", 1)[1].split(
        "async def deep_sync_aria2_finished", 1
    )[0]
    assert "sync_download_clients" not in sync


def test_direct_link_generation_batches_result_persistence():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    direct = manager.split("async def _prepare_direct_link_collection", 1)[1].split(
        "async def retry_direct_link_collection", 1
    )[0]
    result_loop = direct.split(
        "for position, result in enumerate(results, start=1):", 1
    )[1].split("final_name = direct_link_collection_name", 1)[0]

    assert "failed_updates" in result_loop
    assert "success_updates" in result_loop
    assert "generation_events" in result_loop
    assert result_loop.count("await db.executemany(") == 3
    assert result_loop.count("await db.commit()") == 1


def test_stats_hot_path_uses_conditional_aggregation_and_timing():
    routes = (REPO_ROOT / "backend/api/routes.py").read_text()
    stats = routes.split("async def get_stats():", 1)[1].split(
        '@router.get("/stats/detail")', 1
    )[0]

    assert "SUM(CASE WHEN status='completed'" in stats
    assert "AS operator_active_progress_pct" in stats
    assert 'observe("api.stats"' in stats
    assert "SELECT COUNT(*) as c FROM torrents WHERE status='error'" not in stats


def test_progress_only_sse_throttles_aggregate_stats_refresh():
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    sse = frontend.split("var progressStatsTimer = null;", 1)[1].split(
        "es.addEventListener(\n          'ping'", 1
    )[0]

    assert "if (!patchedProgress)" in sse
    assert "else if (!progressStatsTimer)" in sse
    assert "progressStatsTimer = setTimeout(" in sse
    assert "1500" in sse


def test_performance_diagnostics_endpoint_exposes_only_runtime_counters():
    routes = (REPO_ROOT / "backend/api/routes.py").read_text()
    perf = routes.split(
        '@router.get("/admin/performance")', 1
    )[1].split("# ── Statistics", 1)[0]

    assert "performance_snapshot()" in perf
    assert "db_runtime_metrics()" in perf
    assert "manager.aria2().rpc_metrics()" in perf
    assert "get_settings()" not in perf


def test_temporary_refactor_scaffolding_is_not_shipped():
    assert not (REPO_ROOT / ".github/scripts/v104_surgical_refactor.py").exists()
    assert not (REPO_ROOT / ".github/workflows/v104-surgical-refactor.yml").exists()
    assert not (REPO_ROOT / ".github/scripts/v104_phase2_refactor.py").exists()
    assert not (REPO_ROOT / ".github/scripts/v104_phase3_refactor.py").exists()
    assert not (REPO_ROOT / ".github/scripts/v104_phase4_refactor.py").exists()
    assert not (REPO_ROOT / ".github/scripts/v104_phase4_testfix.py").exists()
    workflow = (REPO_ROOT / ".github/workflows/tests.yml").read_text()
    assert "v104-refactor" not in workflow
    assert "v104-phase2" not in workflow
    assert "provider-lifecycle-refactor" not in workflow
    assert "slot-aware-unlock-refactor" not in workflow
    assert "contents: write" not in workflow


def test_external_aria2_ownership_is_cached_after_durable_bootstrap():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    assert "self._aria2_owned_gid_cache: Set[str] = set()" in manager
    assert "self._aria2_owned_gid_cache.add(gid)" in manager
    owned = manager.split("async def _aria2_owned_gids", 1)[1].split(
        "async def _aria2_owned_downloads", 1
    )[0]
    assert "return set(self._aria2_owned_gid_cache)" in owned
    assert "SELECT gid" not in owned


def test_dispatch_reuses_initial_owned_aria2_snapshot():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    dispatch = manager.split("async def _dispatch_pending_aria2_queue", 1)[1].split(
        "async def _schedule_ready_aria2_parents", 1
    )[0]
    assert "dispatch_snapshot = list(owned_downloads)" in dispatch
    assert dispatch.count("await self._aria2_get_all()") == 1


def test_manager_control_bootstrap_is_explicit_not_import_hooked():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    services_init = (REPO_ROOT / "backend/services/__init__.py").read_text()
    assert "_install_transfer_control(manager)" in manager
    assert "_install_parent_progress_guard(manager)" in manager
    assert "_install_global_pause_semantics(manager)" in manager
    assert "install_import_hook" not in services_init
    assert not (REPO_ROOT / "backend/services/_control_bootstrap.py").exists()


def test_full_provider_inventory_reuses_one_bulk_snapshot():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    reconcile = manager.split("async def reconcile_provider_inventory", 1)[1].split(
        "async def full_alldebrid_sync", 1
    )[0]
    assert reconcile.count("get_magnet_status()") == 1
    assert "import_existing_magnets(all_magnets=all_magnets)" in reconcile
    assert "full_alldebrid_sync(all_magnets=all_magnets)" in reconcile

    imported = manager.split("async def import_existing_magnets", 1)[1].split(
        "async def delete_torrent", 1
    )[0]
    full = manager.split("async def full_alldebrid_sync", 1)[1].split(
        "async def sync_alldebrid_status", 1
    )[0]
    assert "if all_magnets is None:" in imported
    assert "if all_magnets is None:" in full


def test_scheduler_profiles_provider_and_download_domains():
    scheduler = (REPO_ROOT / "backend/core/scheduler.py").read_text()
    assert 'async_timer("scheduler.provider_poll")' in scheduler
    assert 'async_timer("scheduler.provider_inventory")' in scheduler
    assert 'async_timer("scheduler.download_client_sync")' in scheduler
    assert "await manager.reconcile_provider_inventory()" in scheduler
    full_loop = scheduler.split("async def full_sync_loop", 1)[1].split(
        "async def sync_download_clients_loop", 1
    )[0]
    assert "import_existing_magnets" not in full_loop
    assert "full_alldebrid_sync" not in full_loop


def test_lifespan_closes_database_runtime_pool():
    main = (REPO_ROOT / "backend/main.py").read_text()
    shutdown = main.split('logger.info("Shutting down %s...", APP_NAME)', 1)[1].split(
        "app = FastAPI(", 1
    )[0]
    assert "from db.database import close_db_runtime" in shutdown
    assert "await close_db_runtime()" in shutdown


def test_magnet_materialization_defers_unlock_until_a_delivery_slot_exists():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    download = manager.split("async def _download(self, torrent_id", 1)[1].split(
        "async def _fetch_ready_files", 1
    )[0]
    assert "Materialize the provider manifest without eager URL generation" in download
    assert "unlock_results = await asyncio.gather" not in download
    assert "manifest_rows: List[tuple] = []" in download
    assert "source_url," in download
    assert download.count("await db.executemany(") >= 1

    dispatcher = manager.split("async def _dispatch_pending_aria2_queue", 1)[1].split(
        "async def _schedule_ready_aria2_parents", 1
    )[0]
    assert "await _retry_async(self.ad().unlock_link, sl)" in dispatcher
    assert 'provider_code == "LINK_HOST_NOT_SUPPORTED"' in dispatcher
    assert "SET status='blocked', blocked=1" in dispatcher
