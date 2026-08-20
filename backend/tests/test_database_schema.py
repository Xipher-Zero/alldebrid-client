from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch


def test_default_database_path_uses_debridpulse_name_and_preserves_legacy_install():
    from db.database import _default_sqlite_path

    with patch.dict(os.environ, {}, clear=True), patch.object(Path, "exists", return_value=False):
        assert _default_sqlite_path() == Path("/app/data/debridpulse.db")

    with patch.dict(os.environ, {}, clear=True), patch.object(
        Path, "exists", side_effect=[True, False]
    ):
        assert _default_sqlite_path() == Path("/app/data/alldebrid.db")

    with patch.dict(os.environ, {"DB_PATH": "/custom/library.db"}, clear=True):
        assert _default_sqlite_path() == Path("/custom/library.db")


def test_runtime_database_is_sqlite_only():
    root = Path(__file__).resolve().parents[1]
    source = (root / "db" / "database.py").read_text().lower()
    config = (root / "core" / "config.py").read_text().lower()
    assert "asyncpg" not in source
    assert "postgres" not in source
    assert "db_type" not in config
    assert not (root / "db" / "migration.py").exists()
