"""
Database layer for DebridPulse.

Supports two modes (controlled by db_type in AppSettings):
  sqlite   -> Default, fully backward compatible, no setup needed
  postgres -> External PostgreSQL instance

Both modes use the same _DbConnection abstraction. Runtime connections are
pooled so the scheduler/API hot paths do not repeatedly create and tear down
SQLite worker threads or PostgreSQL TCP/TLS sessions.

Usage:
    async with get_db() as db:
        rows = await db.fetchall("SELECT * FROM torrents WHERE status=?", ("completed",))
        row  = await db.fetchone("SELECT * FROM torrents WHERE id=?", (1,))
        await db.execute("UPDATE torrents SET status=? WHERE id=?", ("done", 1))
        await db.commit()

DB_PATH is exported for backward compatibility with existing code.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import aiosqlite

logger = logging.getLogger("alldebrid.db")


def _default_sqlite_path() -> Path:
    """Use the DebridPulse filename for new installs without stranding upgrades."""
    configured = os.getenv("DB_PATH", "").strip()
    if configured:
        return Path(configured)
    current = Path("/app/data/debridpulse.db")
    legacy = Path("/app/data/alldebrid.db")
    if legacy.exists() and not current.exists():
        logger.warning(
            "Using legacy SQLite path %s; set DB_PATH=%s to migrate explicitly",
            legacy,
            current,
        )
        return legacy
    return current


DB_PATH = _default_sqlite_path()


def _get_settings():
    try:
        from core.config import get_settings
        return get_settings()
    except Exception:
        return None


def _is_postgres() -> bool:
    cfg = _get_settings()
    return cfg is not None and getattr(cfg, "db_type", "sqlite") == "postgres"


def _build_dsn() -> str:
    cfg = _get_settings()
    if cfg is None:
        raise RuntimeError("Settings not available")
    ssl = "require" if getattr(cfg, "postgres_ssl", False) else "disable"
    app_name = getattr(cfg, "postgres_application_name", "debridpulse")
    return (
        f"postgresql://{cfg.postgres_user}:{cfg.postgres_password}"
        f"@{cfg.postgres_host}:{cfg.postgres_port}/{cfg.postgres_db}"
        f"?sslmode={ssl}&application_name={app_name}"
    )


def _pg_safe(v):
    """Ensure Python values retain their native asyncpg-compatible type."""
    return v


class _CursorWrapper:
    """Wrap cursor results so execute(...).fetchall()/fetchone() is portable."""

    def __init__(self, backend: str, cursor, pg_rows=None):
        self._backend = backend
        self._cursor = cursor
        self._pg_rows = pg_rows or []
        self._pg_index = 0

    async def fetchall(self):
        if self._backend == "sqlite" and self._cursor is not None:
            rows = await self._cursor.fetchall()
            return [dict(r) for r in rows]
        return self._pg_rows

    async def fetchone(self):
        if self._backend == "sqlite" and self._cursor is not None:
            row = await self._cursor.fetchone()
            return dict(row) if row else None
        return self._pg_rows[0] if self._pg_rows else None

    def __getitem__(self, key):
        return None


class _DbConnection:
    """Unified connection API for SQLite and PostgreSQL."""

    def __init__(self, backend: str, raw):
        self._backend = backend
        self._raw = raw

    @property
    def backend(self) -> str:
        return self._backend

    def _adapt(self, sql: str) -> str:
        if self._backend == "sqlite":
            return sql
        import re
        counter = 0

        def _repl(_m):
            nonlocal counter
            counter += 1
            return f"${counter}"

        sql = re.sub(r"\?", _repl, sql)
        sql = sql.replace("CURRENT_TIMESTAMP", "NOW()")

        sql = re.sub(
            r"datetime\('now',\s*'(-?\d+)\s+(\w+)'\)",
            lambda m: f"(NOW() + INTERVAL '{m.group(1)} {m.group(2)}')",
            sql,
        )
        sql = re.sub(r"datetime\('now'\)", "NOW()", sql)
        sql = re.sub(
            r"datetime\('now',\s*(\$\d+)\s*\|\|\s*'(\s*\w+\s*)'\)",
            lambda m: f"(NOW() + ({m.group(1)} || ' {m.group(2).strip()}')::interval)",
            sql,
        )
        sql = re.sub(
            r"CAST\(\(julianday\((\w+)\)\s*-\s*julianday\((\w+)\)\)\s*\*\s*86400\s*AS\s*INTEGER\)",
            lambda m: (
                f"CAST(EXTRACT(EPOCH FROM "
                f"({m.group(1)}::timestamptz - {m.group(2)}::timestamptz)) AS INTEGER)"
            ),
            sql,
        )
        sql = re.sub(
            r"julianday\((\w+)\)\s*-\s*julianday\((\w+)\)",
            lambda m: (
                f"(EXTRACT(EPOCH FROM "
                f"({m.group(1)}::timestamptz - {m.group(2)}::timestamptz)) / 86400.0)"
            ),
            sql,
        )
        sql = re.sub(r"\bDATE\(([^)]+)\)", lambda m: f"({m.group(1)})::date", sql)
        sql = re.sub(
            r"INTEGER PRIMARY KEY AUTOINCREMENT",
            "SERIAL PRIMARY KEY",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(r"\bDATETIME\b", "TIMESTAMPTZ", sql, flags=re.IGNORECASE)
        return sql

    async def execute(self, sql: str, params: Sequence[Any] = ()):
        sql = self._adapt(sql)
        if self._backend == "sqlite":
            cursor = await self._raw.execute(sql, params)
            return _CursorWrapper("sqlite", cursor)

        safe_params = tuple(_pg_safe(p) for p in params)
        stripped = sql.lstrip()
        if stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH"):
            rows = await self._raw.fetch(sql, *safe_params)
            pg_rows = [dict(r) for r in rows]
        else:
            await self._raw.execute(sql, *safe_params)
            pg_rows = []
        return _CursorWrapper("postgres", None, pg_rows=pg_rows)

    async def executemany(self, sql: str, params_list: List[Sequence[Any]]):
        sql = self._adapt(sql)
        if not params_list:
            return
        if self._backend == "sqlite":
            await self._raw.executemany(sql, params_list)
        else:
            await self._raw.executemany(
                sql,
                [tuple(_pg_safe(p) for p in row) for row in params_list],
            )

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        sql = self._adapt(sql)
        if self._backend == "sqlite":
            cur = await self._raw.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
        rows = await self._raw.fetch(sql, *tuple(_pg_safe(p) for p in params))
        return [dict(r) for r in rows]

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        sql = self._adapt(sql)
        if self._backend == "sqlite":
            cur = await self._raw.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None
        row = await self._raw.fetchrow(sql, *tuple(_pg_safe(p) for p in params))
        return dict(row) if row else None

    async def execute_returning_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        """Execute an INSERT and return the generated row id for either backend."""
        sql_adapted = self._adapt(sql)
        if self._backend == "sqlite":
            cur = await self._raw.execute(sql_adapted, params)
            return cur.lastrowid
        pg_sql = sql_adapted.rstrip().rstrip(";") + " RETURNING id"
        row = await self._raw.fetchrow(
            pg_sql,
            *tuple(_pg_safe(p) for p in params),
        )
        return int(row["id"]) if row else None

    async def commit(self):
        if self._backend == "sqlite":
            await self._raw.commit()

    async def rollback(self):
        if self._backend == "sqlite":
            await self._raw.rollback()


async def _configure_sqlite_connection(conn: aiosqlite.Connection) -> None:
    """Apply connection-local performance/reliability settings.

    Several SQLite pragmas are connection scoped. The old one-connection-at-a-
    time implementation configured them only during schema initialisation, so
    normal API/scheduler connections silently ran without those settings.
    """
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA busy_timeout=10000")
    await conn.execute("PRAGMA temp_store=MEMORY")
    await conn.execute("PRAGMA cache_size=-65536")
    await conn.execute("PRAGMA mmap_size=268435456")
    await conn.execute("PRAGMA foreign_keys=ON")


class _SQLitePool:
    """Small persistent pool of aiosqlite worker-thread connections."""

    def __init__(self, path: Path, size: int):
        self.path = path
        self.size = max(1, min(16, int(size)))
        self._queue: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(self.size)
        self._started = False
        self._start_lock = asyncio.Lock()
        self._connections: List[aiosqlite.Connection] = []

    async def start(self) -> None:
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            created: List[aiosqlite.Connection] = []
            try:
                for _ in range(self.size):
                    conn = await aiosqlite.connect(self.path, timeout=30)
                    await _configure_sqlite_connection(conn)
                    created.append(conn)
                    await self._queue.put(conn)
            except Exception:
                for conn in created:
                    try:
                        await conn.close()
                    except Exception:
                        pass
                raise
            self._connections = created
            self._started = True
            logger.info("SQLite runtime pool ready (%d connections)", self.size)

    async def acquire(self) -> aiosqlite.Connection:
        await self.start()
        return await self._queue.get()

    async def release(self, conn: aiosqlite.Connection) -> None:
        await self._queue.put(conn)

    async def close(self) -> None:
        async with self._start_lock:
            connections = list(self._connections)
            self._connections.clear()
            self._started = False
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            for conn in connections:
                try:
                    await conn.close()
                except Exception:
                    pass


_sqlite_pool: Optional[_SQLitePool] = None
_sqlite_pool_lock = asyncio.Lock()
_pg_pool = None
_pg_pool_dsn = ""
_pg_pool_lock = asyncio.Lock()
_db_metrics: Dict[str, float] = {
    "sqlite_acquires": 0,
    "postgres_acquires": 0,
    "wait_seconds": 0.0,
}


def _sqlite_pool_size() -> int:
    try:
        return max(1, min(16, int(os.getenv("DEBRIDPULSE_SQLITE_POOL_SIZE", "4"))))
    except Exception:
        return 4


def _postgres_pool_size() -> int:
    try:
        return max(2, min(32, int(os.getenv("DEBRIDPULSE_POSTGRES_POOL_SIZE", "8"))))
    except Exception:
        return 8


async def _get_sqlite_pool() -> _SQLitePool:
    global _sqlite_pool
    pool = _sqlite_pool
    if pool is not None and pool.path == DB_PATH and pool.size == _sqlite_pool_size():
        await pool.start()
        return pool
    async with _sqlite_pool_lock:
        pool = _sqlite_pool
        desired = _sqlite_pool_size()
        if pool is not None and (pool.path != DB_PATH or pool.size != desired):
            await pool.close()
            pool = None
        if pool is None:
            pool = _SQLitePool(DB_PATH, desired)
            _sqlite_pool = pool
        await pool.start()
        return pool


async def _get_postgres_pool():
    global _pg_pool, _pg_pool_dsn
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError("asyncpg is not installed. Run: pip install asyncpg")

    dsn = _build_dsn()
    pool = _pg_pool
    if pool is not None and _pg_pool_dsn == dsn:
        return pool

    async with _pg_pool_lock:
        if _pg_pool is not None and _pg_pool_dsn != dsn:
            await _pg_pool.close()
            _pg_pool = None
            _pg_pool_dsn = ""
        if _pg_pool is None:
            max_size = _postgres_pool_size()
            _pg_pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=max_size,
                command_timeout=30,
            )
            _pg_pool_dsn = dsn
            logger.info("PostgreSQL runtime pool ready (max=%d)", max_size)
        return _pg_pool


async def close_db_runtime() -> None:
    """Close persistent DB runtime pools; safe to call repeatedly."""
    global _sqlite_pool, _pg_pool, _pg_pool_dsn
    async with _sqlite_pool_lock:
        if _sqlite_pool is not None:
            await _sqlite_pool.close()
            _sqlite_pool = None
    async with _pg_pool_lock:
        if _pg_pool is not None:
            await _pg_pool.close()
            _pg_pool = None
            _pg_pool_dsn = ""


def db_runtime_metrics() -> Dict[str, Any]:
    """Return process-local database acquisition instrumentation."""
    total = int(_db_metrics["sqlite_acquires"] + _db_metrics["postgres_acquires"])
    return {
        "sqlite_acquires": int(_db_metrics["sqlite_acquires"]),
        "postgres_acquires": int(_db_metrics["postgres_acquires"]),
        "total_acquires": total,
        "wait_seconds": round(float(_db_metrics["wait_seconds"]), 6),
        "average_wait_ms": (
            round((_db_metrics["wait_seconds"] / total) * 1000.0, 3)
            if total
            else 0.0
        ),
        "sqlite_pool_size": _sqlite_pool_size(),
        "postgres_pool_size": _postgres_pool_size(),
    }


@asynccontextmanager
async def get_db() -> AsyncIterator[_DbConnection]:
    started = time.monotonic()
    if _is_postgres():
        pool = await _get_postgres_pool()
        async with pool.acquire() as conn:
            _db_metrics["postgres_acquires"] += 1
            _db_metrics["wait_seconds"] += max(0.0, time.monotonic() - started)
            async with conn.transaction():
                yield _DbConnection("postgres", conn)
        return

    pool = await _get_sqlite_pool()
    conn = await pool.acquire()
    _db_metrics["sqlite_acquires"] += 1
    _db_metrics["wait_seconds"] += max(0.0, time.monotonic() - started)
    try:
        yield _DbConnection("sqlite", conn)
    finally:
        # Closing the old per-use connection implicitly discarded uncommitted
        # work. Preserve that contract before returning a persistent connection
        # to the pool so one request cannot leak a transaction into another.
        try:
            await conn.rollback()
        except Exception:
            pass
        await pool.release(conn)


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str):
    """Adds column to table if it does not exist. Safe to call repeatedly."""
    try:
        cur = await db.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cur.fetchall()}
        if column not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            await db.commit()
            logger.debug("Added column %s.%s (%s)", table, column, definition)
    except Exception as exc:
        logger.warning("_ensure_column %s.%s failed (ignored): %s", table, column, exc)


async def _ensure_column_pg(conn, table: str, column: str, definition: str):
    import re
    row = await conn.fetchrow(
        "SELECT 1 FROM information_schema.columns WHERE table_name=$1 AND column_name=$2",
        table,
        column,
    )
    if row is None:
        definition = re.sub(r"\bDATETIME\b", "TIMESTAMPTZ", definition, flags=re.IGNORECASE)
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")


_SCHEMA_COLUMNS_TORRENTS = [
    ("provider_status", "TEXT"),
    ("provider_status_code", "INTEGER"),
    ("polling_failures", "INTEGER DEFAULT 0"),
    ("download_client", "TEXT DEFAULT 'aria2'"),
    ("label", "TEXT DEFAULT ''"),
    ("priority", "INTEGER DEFAULT 0"),
    ("upload_retry_count", "INTEGER DEFAULT 0"),
]

_SCHEMA_COLUMNS_FILES = [
    ("source_url", "TEXT"),
    ("download_id", "TEXT"),
    ("download_client", "TEXT DEFAULT 'aria2'"),
    ("retry_count", "INTEGER DEFAULT 0"),
    ("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
]


async def init_db():
    if _is_postgres():
        await _init_db_postgres()
    # Always initialise SQLite too for backward compatibility, migration, and
    # the explicit PostgreSQL-fallback path.
    await _init_db_sqlite()


async def _init_db_sqlite():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await _configure_sqlite_connection(db)
        await db.commit()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS torrents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                name TEXT,
                magnet TEXT,
                status TEXT DEFAULT 'pending',
                alldebrid_id TEXT,
                size_bytes INTEGER DEFAULT 0,
                progress REAL DEFAULT 0,
                download_url TEXT,
                local_path TEXT,
                source TEXT DEFAULT 'watch',
                provider_status TEXT,
                provider_status_code INTEGER,
                polling_failures INTEGER DEFAULT 0,
                download_client TEXT DEFAULT 'aria2',
                label TEXT DEFAULT '',
                priority INTEGER DEFAULT 0,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS download_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                torrent_id INTEGER,
                filename TEXT,
                size_bytes INTEGER,
                source_url TEXT,
                download_url TEXT,
                local_path TEXT,
                status TEXT DEFAULT 'pending',
                download_id TEXT,
                download_client TEXT DEFAULT 'aria2',
                blocked INTEGER DEFAULT 0,
                block_reason TEXT,
                retry_count INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (torrent_id) REFERENCES torrents(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                torrent_id INTEGER,
                level TEXT DEFAULT 'info',
                message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (torrent_id) REFERENCES torrents(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, defn in _SCHEMA_COLUMNS_TORRENTS:
            await _ensure_column(db, "torrents", col, defn)
        for col, defn in _SCHEMA_COLUMNS_FILES:
            await _ensure_column(db, "download_files", col, defn)
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as idx_db:
        for ddl in [
            "CREATE INDEX IF NOT EXISTS idx_dlfiles_torrent_status ON download_files (torrent_id, status, blocked)",
            "CREATE INDEX IF NOT EXISTS idx_dlfiles_queue ON download_files (status, download_client, blocked, torrent_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_dlfiles_download_id ON download_files (download_id)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_alldebrid_id ON torrents (alldebrid_id)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_status ON torrents (status)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_status_alldebrid ON torrents (status, alldebrid_id)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_status_updated ON torrents (status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_status_priority ON torrents (status, priority DESC, id ASC)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_completed_at ON torrents (completed_at)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_priority ON torrents (priority DESC, id ASC)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_hash ON torrents (hash)",
            "CREATE INDEX IF NOT EXISTS idx_torrents_created_at ON torrents (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_dlfiles_local_path ON download_files (local_path)",
            "CREATE INDEX IF NOT EXISTS idx_events_torrent_id ON events (torrent_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at)",
        ]:
            await idx_db.execute(ddl)
        await idx_db.commit()
    logger.debug("SQLite indexes ensured")

    async with aiosqlite.connect(DB_PATH) as verify_db:
        cur = await verify_db.execute("PRAGMA table_info(torrents)")
        cols = {row[1] for row in await cur.fetchall()}
        critical = {"priority", "label", "provider_status", "polling_failures"}
        missing = critical - cols
        if missing:
            logger.error("CRITICAL: columns still missing after migration: %s", missing)
        else:
            logger.info("SQLite schema verified — all critical columns present")
    logger.info("SQLite database initialised: %s", DB_PATH)

    _STATUS_REPR_MAP = {
        "TorrentStatus.PROCESSING": "processing",
        "TorrentStatus.UPLOADING": "uploading",
        "TorrentStatus.READY": "ready",
        "TorrentStatus.ERROR": "error",
        "TorrentStatus.COMPLETED": "completed",
        "TorrentStatus.DELETED": "deleted",
        "TorrentStatus.QUEUED": "queued",
        "TorrentStatus.DOWNLOADING": "downloading",
        "TorrentStatus.PENDING": "pending",
        "TorrentStatus.PAUSED": "paused",
    }
    async with aiosqlite.connect(DB_PATH) as fix_db:
        for bad_val, good_val in _STATUS_REPR_MAP.items():
            cur = await fix_db.execute(
                "SELECT COUNT(*) FROM torrents WHERE status = ?",
                (bad_val,),
            )
            (count,) = await cur.fetchone()
            if count:
                logger.warning(
                    "Repairing %d torrent(s) with corrupted status %r → %r",
                    count,
                    bad_val,
                    good_val,
                )
                await fix_db.execute(
                    "UPDATE torrents SET status = ? WHERE status = ?",
                    (good_val, bad_val),
                )
        await fix_db.commit()


async def _init_db_postgres():
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError("asyncpg is not installed. Run: pip install asyncpg")
    dsn = _build_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS torrents (
                    id SERIAL PRIMARY KEY,
                    hash TEXT UNIQUE NOT NULL,
                    name TEXT,
                    magnet TEXT,
                    status TEXT DEFAULT 'pending',
                    alldebrid_id TEXT,
                    size_bytes BIGINT DEFAULT 0,
                    progress DOUBLE PRECISION DEFAULT 0,
                    download_url TEXT,
                    local_path TEXT,
                    source TEXT DEFAULT 'watch',
                    provider_status TEXT,
                    provider_status_code INTEGER,
                    polling_failures INTEGER DEFAULT 0,
                    download_client TEXT DEFAULT 'aria2',
                    label TEXT DEFAULT '',
                    priority INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS download_files (
                    id SERIAL PRIMARY KEY,
                    torrent_id INTEGER REFERENCES torrents(id),
                    filename TEXT,
                    size_bytes BIGINT,
                    source_url TEXT,
                    download_url TEXT,
                    local_path TEXT,
                    status TEXT DEFAULT 'pending',
                    download_id TEXT,
                    download_client TEXT DEFAULT 'aria2',
                    blocked INTEGER DEFAULT 0,
                    block_reason TEXT,
                    retry_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    torrent_id INTEGER REFERENCES torrents(id),
                    level TEXT DEFAULT 'info',
                    message TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stats_snapshots (
                    id SERIAL PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            for col, defn in _SCHEMA_COLUMNS_TORRENTS:
                await _ensure_column_pg(conn, "torrents", col, defn)
            for col, defn in _SCHEMA_COLUMNS_FILES:
                await _ensure_column_pg(conn, "download_files", col, defn)
            for ddl in [
                "CREATE INDEX IF NOT EXISTS idx_dlfiles_torrent_status ON download_files (torrent_id, status, blocked)",
                "CREATE INDEX IF NOT EXISTS idx_dlfiles_queue ON download_files (status, download_client, blocked, torrent_id, id)",
                "CREATE INDEX IF NOT EXISTS idx_dlfiles_download_id ON download_files (download_id)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_alldebrid_id ON torrents (alldebrid_id)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_status ON torrents (status)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_status_alldebrid ON torrents (status, alldebrid_id)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_status_updated ON torrents (status, updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_status_priority ON torrents (status, priority DESC NULLS LAST, id ASC)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_completed_at ON torrents (completed_at)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_priority ON torrents (priority DESC NULLS LAST, id ASC)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_hash ON torrents (hash)",
                "CREATE INDEX IF NOT EXISTS idx_torrents_created_at ON torrents (created_at)",
                "CREATE INDEX IF NOT EXISTS idx_dlfiles_local_path ON download_files (local_path)",
                "CREATE INDEX IF NOT EXISTS idx_events_torrent_id ON events (torrent_id)",
                "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at)",
            ]:
                await conn.execute(ddl)

            for tbl, col in [
                ("torrents", "size_bytes"),
                ("download_files", "size_bytes"),
            ]:
                col_row = await conn.fetchrow(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name=$1 AND column_name=$2",
                    tbl,
                    col,
                )
                if col_row and col_row["data_type"].lower() in ("integer", "int4"):
                    await conn.execute(
                        f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE BIGINT"
                    )
                    logger.info("Migrated %s.%s from INT4 to BIGINT", tbl, col)
    finally:
        await conn.close()
    logger.info("PostgreSQL database initialised")
