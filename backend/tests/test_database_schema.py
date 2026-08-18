from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePostgresConnection:
    def __init__(self):
        self.statements: list[str] = []

    def transaction(self):
        return _FakeTransaction()

    async def execute(self, sql: str, *args):
        self.statements.append(sql)

    async def fetchrow(self, sql: str, *args):
        if "data_type" in sql:
            return {"data_type": "bigint"}
        return {"exists": 1}

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_postgres_schema_excludes_removed_automation_tables():
    from db.database import _init_db_postgres

    fake_conn = _FakePostgresConnection()

    with patch("db.database._build_dsn", return_value="postgresql://test"), \
         patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        await _init_db_postgres()

    ddl = "\n".join(fake_conn.statements)
    assert "CREATE TABLE IF NOT EXISTS torrents" in ddl
    assert "CREATE TABLE IF NOT EXISTS stats_snapshots" in ddl
    assert "CREATE TABLE IF NOT EXISTS saved_searches" not in ddl
    assert "CREATE TABLE IF NOT EXISTS flexget_runs" not in ddl


def test_bidirectional_migration_only_includes_supported_tables():
    from db.migration import MIGRATION_TABLES

    assert MIGRATION_TABLES == [
        "torrents",
        "download_files",
        "events",
        "stats_snapshots",
    ]
