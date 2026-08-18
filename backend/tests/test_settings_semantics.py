import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic" not in sys.modules:
    class _BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def model_dump(self):
            return dict(self.__dict__)

    sys.modules["pydantic"] = types.SimpleNamespace(BaseModel=_BaseModel)

if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientTimeout=lambda *a, **kw: None,
        ClientSession=object,
        TCPConnector=lambda **kw: None,
        FormData=object,
        ClientError=Exception,
        ServerDisconnectedError=Exception,
        ClientConnectorError=Exception,
        ClientOSError=Exception,
    )

if "aiofiles" not in sys.modules:
    sys.modules["aiofiles"] = types.SimpleNamespace(open=lambda *a, **kw: None)

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(
        Connection=object,
        Row=object,
        connect=lambda *a, **kw: None,
    )

from core.scheduler import _coerce_int_setting, _stats_report_window_hours
from services import manager_v2


class SchedulerSettingsTests(unittest.TestCase):
    def test_coerce_int_setting_preserves_zero(self):
        self.assertEqual(_coerce_int_setting(0, 10), 0)

    def test_coerce_int_setting_uses_default_for_none(self):
        self.assertEqual(_coerce_int_setting(None, 10), 10)

    def test_coerce_int_setting_uses_default_for_invalid(self):
        self.assertEqual(_coerce_int_setting("invalid", 10), 10)

    def test_stats_report_window_uses_configured_value(self):
        cfg = types.SimpleNamespace(stats_report_window_hours=168)
        self.assertEqual(_stats_report_window_hours(cfg), 168)

    def test_stats_report_window_falls_back_to_default(self):
        cfg = types.SimpleNamespace(stats_report_window_hours=None)
        self.assertEqual(_stats_report_window_hours(cfg), 24)


class AllDebridRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Reset the singleton limiter to a known state before each test
        manager_v2._ad_rate_limiter = manager_v2._TokenBucketRateLimiter(rate=60, window=60.0)

    async def test_rate_limit_zero_means_effectively_unlimited(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=0)
        with patch("services.manager_v2.get_settings", return_value=cfg):
            limiter = await manager_v2._get_ad_rate_limiter()
        self.assertGreaterEqual(limiter._rate, 1_000_000)

    async def test_rate_limit_positive_value_is_respected(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=12)
        with patch("services.manager_v2.get_settings", return_value=cfg):
            limiter = await manager_v2._get_ad_rate_limiter()
        self.assertEqual(limiter._rate, 12)


class SettingsFrontendContractTests(unittest.TestCase):
    def test_active_settings_tab_lookup_is_scoped_to_settings_tabs(self):
        js = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "static"
            / "app.js"
        ).read_text()

        self.assertIn(
            "document.querySelector('#settings-tabs .stab.active')?.dataset.tab",
            js,
        )
        self.assertNotIn(
            "document.querySelector('.stab.active')?.dataset.tab",
            js,
        )

        self.assertIn(
            "const activeTab=getActiveSettingsTab(); "
            "settingsData.aria2_mode=this.value; renderSettings(); "
            "switchSettingsTab(activeTab);",
            js,
        )

    def test_settings_footer_test_actions_follow_the_active_tab(self):
        root = Path(__file__).resolve().parents[2]
        js = (root / "frontend" / "static" / "app.js").read_text()
        html = (root / "frontend" / "static" / "index.html").read_text()

        expected = {
            "tab-general": "Test AllDebrid",
            "tab-download": "Test Aria2",
            "tab-notifications": "Test Discord",
            "tab-database": "Test DB",
        }
        for tab, label in expected.items():
            self.assertIn(f'data-settings-test-tab="{tab}"', html)
            self.assertIn(label, html)

        self.assertEqual(html.count('data-settings-test-tab="tab-general"'), 1)
        self.assertEqual(html.count('data-settings-test-tab="tab-download"'), 1)
        self.assertEqual(html.count('data-settings-test-tab="tab-notifications"'), 1)
        self.assertIn("updateSettingsFooterActions(id);", js)
        self.assertIn("button.hidden = !visible;", js)
        self.assertIn("dbType === 'postgres' || dbType === 'postgres_internal'", js)

    def test_stalled_download_recovery_is_download_scoped_and_type_agnostic(self):
        js = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "static"
            / "app.js"
        ).read_text()
        general_panel = js.split('id="tab-general"', 1)[1].split(
            'id="tab-download"', 1
        )[0]
        download_panel = js.split('id="tab-download"', 1)[1].split(
            'id="tab-extract"', 1
        )[0]

        self.assertNotIn('id="s-stuck_download_timeout_hours"', general_panel)
        self.assertIn('id="s-stuck_download_timeout_hours"', download_panel)
        self.assertIn("Auto-Recover Stalled Downloads", download_panel)
        self.assertIn("regardless of transfer source", download_panel)
        self.assertNotIn("Torrents stuck", download_panel)


if __name__ == "__main__":
    unittest.main()
