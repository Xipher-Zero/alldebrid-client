"""Focused contract tests for the internal direct/debrid-link workflow."""

import asyncio
import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The scratch verification environment intentionally has no runtime wheels.
# Match the upstream suite's lightweight import stubs.
if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientTimeout=lambda *args, **kwargs: None,
        ClientSession=object,
        TCPConnector=lambda **kwargs: None,
        FormData=object,
        ClientError=Exception,
        ServerDisconnectedError=Exception,
        ClientConnectorError=Exception,
        ClientOSError=Exception,
    )
if "aiofiles" not in sys.modules:
    sys.modules["aiofiles"] = types.SimpleNamespace(open=lambda *args, **kwargs: None)
if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(
        Connection=object,
        Row=object,
        connect=lambda *args, **kwargs: None,
    )

from db.database import _SCHEMA_COLUMNS_FILES
from services.alldebrid import AllDebridService
from services.manager_v2 import (
    TorrentManager,
    direct_link_filename,
    normalize_direct_links,
)


class DirectLinkInputTests(unittest.TestCase):
    def test_normalizes_deduplicates_and_preserves_order(self):
        links = normalize_direct_links(
            [
                " https://host.invalid/a ",
                "http://host.invalid/b",
                "https://host.invalid/a",
                "",
            ]
        )
        self.assertEqual(
            links,
            ["https://host.invalid/a", "http://host.invalid/b"],
        )

    def test_rejects_non_http_input(self):
        with self.assertRaisesRegex(ValueError, "Invalid debrid link"):
            normalize_direct_links(["magnet:?xt=urn:btih:abc"])

    def test_caps_each_batch_at_one_hundred_links(self):
        with self.assertRaisesRegex(ValueError, "maximum of 100"):
            normalize_direct_links(
                [f"https://host.invalid/file-{index}" for index in range(101)]
            )

    def test_derives_safe_filename(self):
        self.assertEqual(
            direct_link_filename("https://host.invalid/files/My%20File?.zip"),
            "My File",
        )
        self.assertEqual(direct_link_filename("https://host.invalid"), "host.invalid")

    def test_schema_migrates_original_source_url(self):
        self.assertIn(("source_url", "TEXT"), _SCHEMA_COLUMNS_FILES)


class DelayedAllDebridTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_immediate_unlocked_link(self):
        service = AllDebridService("test-key")
        service._post = AsyncMock(
            return_value={"link": "https://download.invalid/file", "filename": "file"}
        )
        result = await service.unlock_link("https://host.invalid/file")
        self.assertEqual(result["link"], "https://download.invalid/file")
        self.assertEqual(service._post.await_count, 1)

    async def test_polls_delayed_generation_at_documented_interval(self):
        service = AllDebridService("test-key")
        service._post = AsyncMock(
            side_effect=[
                {"delayed": "job-42", "filename": "archive.zip", "filesize": 123},
                {"status": 1},
                {"status": 2, "link": "https://download.invalid/archive.zip"},
            ]
        )
        with patch("services.alldebrid.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await service.unlock_link("https://host.invalid/archive")

        self.assertEqual(result["filename"], "archive.zip")
        self.assertEqual(result["filesize"], 123)
        self.assertEqual(result["link"], "https://download.invalid/archive.zip")
        self.assertEqual(sleep.await_args_list[0].args, (5,))
        self.assertEqual(service._post.await_count, 3)


class DirectLinkTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_submission_persists_parent_and_schedules_generation(self):
        class FakeDb:
            def __init__(self):
                self.statements = []

            async def execute_returning_id(self, sql, params=()):
                self.statements.append((sql, params))
                return 42

            async def execute(self, sql, params=()):
                self.statements.append((sql, params))

            async def fetchone(self, sql, params=()):
                return {
                    "id": 42,
                    "name": "sample.zip",
                    "status": "processing",
                    "source": "direct_link",
                }

            async def commit(self):
                return None

        fake_db = FakeDb()

        @asynccontextmanager
        async def fake_get_db():
            yield fake_db

        manager = TorrentManager()
        settings = SimpleNamespace(paused=False, alldebrid_api_key="configured")
        with patch("services.manager_v2.get_settings", return_value=settings), patch(
            "services.manager_v2.get_db", fake_get_db
        ), patch.object(
            manager, "_broadcast_direct_link_update", new=AsyncMock()
        ), patch.object(
            manager, "_schedule_direct_link_collection", new=MagicMock()
        ) as schedule:
            result = await manager.add_direct_links(
                ["https://host.invalid/sample.zip"]
            )

        self.assertEqual(result["accepted_links"], 1)
        self.assertEqual(result["source"], "direct_link")
        insert_sql, insert_params = fake_db.statements[0]
        self.assertIn("INSERT INTO torrents", insert_sql)
        self.assertIn("direct_link", insert_params)
        schedule.assert_called_once_with(42, ["https://host.invalid/sample.zip"])


class DashboardContractTests(unittest.TestCase):
    def test_dashboard_and_downloads_page_match_unified_transfer_ui(self):
        repo_root = Path(__file__).resolve().parents[2]
        html = (repo_root / "frontend/static/index.html").read_text()
        js = (repo_root / "frontend/static/app.js").read_text()
        direct_heading = "⬇️ Add Links to Generate and Download DeBrid links"
        magnet_heading = "🧲 Add Magnet Links or a Torrent File"
        self.assertIn(direct_heading, html)
        self.assertLess(html.index(direct_heading), html.index(magnet_heading))
        self.assertIn('id="q-debrid-links" rows="1"', html)
        self.assertNotIn('data-view="aria2queue"', html)
        self.assertNotIn('id="t-magnet"', html)
        self.assertIn('<span class="nav-label">Downloads</span>', html)
        self.assertIn('id="torrent-card-title">All Downloads</span>', html)
        self.assertIn('<script src="/app.js?v=5" defer></script>', html)
        self.assertIn("'/links/add'", js)
        self.assertIn("button.textContent = 'Adding…'", js)
        self.assertIn("🔗 Direct link", js)
        self.assertIn("torrents:'Downloads'", js)
        self.assertIn("`All Downloads (${torrentTotal})`", js)
        self.assertIn("function sourceLabel(source)", js)


if __name__ == "__main__":
    unittest.main()
