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
