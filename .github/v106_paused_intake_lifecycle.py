from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def write(path, text):
    (ROOT / path).write_text(text)


def replace_once(path, old, new):
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    write(path, text.replace(old, new, 1))


# Explicit deletion preserves the parent row for history, so a queued .torrent
# BLOB must be removed explicitly rather than relying on FK cascade semantics.
replace_once(
    "backend/services/manager_v2.py",
    '''            await db.execute("UPDATE torrents SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE id=?", (torrent_id,))
            await db.commit()
''',
    '''            await db.execute("UPDATE torrents SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE id=?", (torrent_id,))
            await db.execute(
                "DELETE FROM deferred_provider_submissions WHERE torrent_id=?",
                (torrent_id,),
            )
            await db.commit()
''',
)

# Add behavior-level contracts for every paused intake type plus the deferred drain.
test_path = "backend/tests/test_v106_audit_contracts.py"
tests = read(test_path).rstrip()
if "test_paused_magnet_intake_does_not_contact_provider" in tests:
    raise SystemExit("paused lifecycle tests already present")

append = r'''


@pytest.mark.asyncio
async def test_paused_magnet_intake_does_not_contact_provider(monkeypatch):
    import services.duplicates as duplicates
    import services.manager_v2 as manager_module

    class FakeDb:
        async def fetchone(self, sql, params=()):
            return None

    @asynccontextmanager
    async def fake_get_db():
        yield FakeDb()

    settings = SimpleNamespace(paused=True, alldebrid_api_key="configured")
    decision = SimpleNamespace(action="allow", matches=[])
    manager = manager_module.TorrentManager()
    provider = SimpleNamespace(upload_magnet=AsyncMock())
    persisted = AsyncMock(
        return_value={
            "id": 81,
            "status": "paused",
            "provider_status": "deferred",
            "_deferred": True,
        }
    )

    monkeypatch.setattr(manager_module, "get_settings", lambda: settings)
    monkeypatch.setattr(manager_module, "get_db", fake_get_db)
    monkeypatch.setattr(duplicates, "check_before_add", AsyncMock(return_value=decision))
    monkeypatch.setattr(manager, "ad", lambda: provider)
    monkeypatch.setattr(manager, "_persist_deferred_magnet", persisted)

    result = await manager.add_magnet_direct(
        "magnet:?xt=urn:btih:" + ("a" * 40)
    )

    assert result["_deferred"] is True
    persisted.assert_awaited_once()
    provider.upload_magnet.assert_not_awaited()


@pytest.mark.asyncio
async def test_paused_torrent_file_intake_does_not_contact_provider(monkeypatch):
    import services.duplicates as duplicates
    import services.manager_v2 as manager_module

    settings = SimpleNamespace(paused=True, alldebrid_api_key="configured")
    decision = SimpleNamespace(action="allow", matches=[])
    manager = manager_module.TorrentManager()
    provider = SimpleNamespace(upload_torrent_file=AsyncMock())
    persisted = AsyncMock(
        return_value={
            "id": 82,
            "status": "paused",
            "provider_status": "deferred",
            "_deferred": True,
        }
    )

    monkeypatch.setattr(manager_module, "get_settings", lambda: settings)
    monkeypatch.setattr(duplicates, "check_before_add", AsyncMock(return_value=decision))
    monkeypatch.setattr(manager, "ad", lambda: provider)
    monkeypatch.setattr(manager, "_persist_deferred_torrent_file", persisted)

    result = await manager.add_torrent_file_direct(
        b"torrent-payload",
        "queued.torrent",
        preferred_hash="b" * 40,
    )

    assert result["_deferred"] is True
    persisted.assert_awaited_once_with(
        b"torrent-payload", "queued.torrent", "manual", "b" * 40
    )
    provider.upload_torrent_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_direct_link_drain_starts_after_resume(monkeypatch):
    import services.manager_v2 as manager_module

    deferred_row = {
        "id": 83,
        "status": "queued",
        "provider_status": "deferred",
        "source": "direct_link",
        "magnet": '["https://host.invalid/queued.bin"]',
        "deferred_kind": None,
        "deferred_payload": None,
        "deferred_filename": None,
        "deferred_source": None,
    }

    class FakeDb:
        def __init__(self):
            self.statements = []

        async def fetchall(self, sql, params=()):
            return [deferred_row]

        async def fetchone(self, sql, params=()):
            if "SELECT status, provider_status" in sql:
                return {"status": "queued", "provider_status": "deferred"}
            return None

        async def execute(self, sql, params=()):
            self.statements.append((sql, params))

        async def commit(self):
            return None

    fake_db = FakeDb()

    @asynccontextmanager
    async def fake_get_db():
        yield fake_db

    settings = SimpleNamespace(paused=False)
    manager = manager_module.TorrentManager()
    schedule = MagicMock()
    monkeypatch.setattr(manager_module, "get_settings", lambda: settings)
    monkeypatch.setattr(manager_module, "get_db", fake_get_db)
    monkeypatch.setattr(manager, "_schedule_direct_link_collection", schedule)

    result = await manager.resume_deferred_provider_submissions()

    assert result == {"started": 1, "failed": 0}
    schedule.assert_called_once_with(83, ["https://host.invalid/queued.bin"])
    assert any("provider_status='submitted'" in sql for sql, _ in fake_db.statements)


def test_deleting_deferred_torrent_purges_stored_payload():
    root = Path(__file__).resolve().parents[2]
    manager = (root / "backend/services/manager_v2.py").read_text()
    start = manager.index("async def delete_torrent")
    end = manager.index("async def test_aria2", start)
    segment = manager[start:end]
    assert "DELETE FROM deferred_provider_submissions WHERE torrent_id=?" in segment
'''

write(test_path, (tests + append).rstrip() + "\n")

# The exact source changes must be present before CI gets to run.
manager = read("backend/services/manager_v2.py")
delete_start = manager.index("async def delete_torrent")
delete_end = manager.index("async def test_aria2", delete_start)
assert "DELETE FROM deferred_provider_submissions WHERE torrent_id=?" in manager[delete_start:delete_end]

# Successful commit must not retain this temporary workflow/helper.
(ROOT / ".github" / "v106_paused_intake_lifecycle.py").unlink(missing_ok=True)
(ROOT / ".github" / "workflows" / "v106-paused-intake-lifecycle.yml").unlink(missing_ok=True)
