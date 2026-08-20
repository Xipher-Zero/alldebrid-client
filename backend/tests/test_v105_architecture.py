from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path):
    return (ROOT / path).read_text()


def test_service_root_and_explicit_components_exist():
    root = text("backend/services/transfer_service.py")
    for name in (
        "ProviderGateway", "TransferRepository", "DispatchCoordinator",
        "Aria2Gateway", "OwnershipLedger", "TransferStateMachine",
        "TransferControlService", "ReconciliationService", "ExtractionService", "NotificationService",
    ):
        assert name in root
    assert "bind_architecture" in root


def test_runtime_monkey_patching_is_removed():
    manager = text("backend/services/manager_v2.py")
    control = text("backend/services/transfer_control.py")
    assert "_install_transfer_control(manager)" not in manager
    assert "_install_parent_progress_guard(manager)" not in manager
    assert "_install_global_pause_semantics(manager)" not in manager
    for assignment in (
        "self.manager.pause_torrent =", "self.manager.resume_torrent =",
        "self.manager._aria2_get_all =", "self.manager._download =",
    ):
        assert assignment not in control


def test_sqlite_is_the_only_runtime_database():
    production = [
        "backend/db/database.py", "backend/core/config.py", "backend/main.py",
        "backend/api/routes.py", "backend/services/db_maintenance.py",
    ]
    combined = "\n".join(text(path).lower() for path in production)
    assert "asyncpg" not in combined
    assert "postgresql" not in combined
    assert "db_type" not in text("backend/core/config.py")
    assert not (ROOT / "backend/db/migration.py").exists()


def test_entrypoints_use_transfer_service():
    for path in ("backend/api/routes.py", "backend/core/scheduler.py", "backend/main.py"):
        src = text(path)
        assert "from services.transfer_service import transfer_service" in src
        assert "from services.manager_v2 import manager" not in src


def test_security_contracts():
    routes = text("backend/api/routes.py")
    main = text("backend/main.py")
    config = text("backend/core/config.py")
    assert "_SECRET_SETTINGS" in routes
    assert 'data[field] = ""' in routes
    assert '"/api/health"' in main
    assert '"/api/stats"' not in main.split("_AUTH_EXEMPT =", 1)[1].split("\n", 1)[0]
    assert 'allow_origins=["*"]' not in main
    assert "os.chmod(CONFIG_PATH, 0o600)" in config


def test_reconciliation_keeps_v104_snapshot_and_negative_cache_invariants():
    src = text("backend/services/reconciliation_service.py")
    assert "aria2.scheduler_snapshot_reuse" in src
    assert "confirmed_missing" in src
    assert "aria2.confirm_gid_cache_hits" in src
    assert "await self.engine._engine_aria2_get_all()" in src


def test_removed_runtime_scope_is_not_exposed_in_frontend():
    js = text("frontend/static/app.js")
    for stale in ("PostgreSQL (external)", "s-postgres_host", "btn-test-postgres", "symlink-settings"):
        assert stale not in js


def test_fastapi_lifespan_has_single_context_manager_boundary():
    main = text("backend/main.py")
    assert "@asynccontextmanager\n@asynccontextmanager\nasync def lifespan" not in main
    assert main.count("@asynccontextmanager\nasync def lifespan(app: FastAPI):") == 1
    assert "_PG_CONNECT_RETRIES" not in main
    assert "_PG_CONNECT_DELAY" not in main
