import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import AppSettings
from core.scheduler import _coerce_int_setting, _stats_report_window_hours
import services.rate_limit as rate_limit


class SchedulerSettingsTests(unittest.TestCase):
    def test_coerce_int_setting_preserves_zero(self):
        self.assertEqual(_coerce_int_setting(0, 10), 0)

    def test_coerce_int_setting_uses_default_for_none(self):
        self.assertEqual(_coerce_int_setting(None, 10), 10)

    def test_coerce_int_setting_uses_default_for_invalid(self):
        self.assertEqual(_coerce_int_setting("invalid", 10), 10)

    def test_stats_report_window_uses_configured_value(self):
        self.assertEqual(_stats_report_window_hours(types.SimpleNamespace(stats_report_window_hours=168)), 168)

    def test_stats_report_window_falls_back_to_default(self):
        self.assertEqual(_stats_report_window_hours(types.SimpleNamespace(stats_report_window_hours=None)), 24)


class AllDebridRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        rate_limit._alldebrid_rate_limiter = rate_limit.TokenBucketRateLimiter(rate=60, window=60.0)

    async def test_rate_limit_zero_means_effectively_unlimited(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=0)
        with patch("services.rate_limit.get_settings", return_value=cfg):
            limiter = await rate_limit.get_alldebrid_rate_limiter()
        self.assertGreaterEqual(limiter._rate, 1_000_000)

    async def test_rate_limit_positive_value_is_respected(self):
        cfg = types.SimpleNamespace(alldebrid_rate_limit_per_minute=12)
        with patch("services.rate_limit.get_settings", return_value=cfg):
            limiter = await rate_limit.get_alldebrid_rate_limiter()
        self.assertEqual(limiter._rate, 12)


class SQLiteOnlySettingsTests(unittest.TestCase):
    def test_server_database_fields_are_removed(self):
        cfg = AppSettings()
        for field in ("db_type", "postgres_host", "postgres_port", "postgres_db",
                      "postgres_user", "postgres_password", "postgres_schema",
                      "postgres_ssl", "postgres_application_name"):
            self.assertFalse(hasattr(cfg, field), field)

    def test_delivery_is_aria2_only(self):
        cfg = AppSettings()
        self.assertEqual(cfg.download_client, "aria2")
        self.assertFalse(hasattr(cfg, "symlink_path"))


class SettingsFrontendContractTests(unittest.TestCase):
    def test_active_settings_tab_lookup_is_scoped(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        self.assertIn("document.querySelector('#settings-tabs .stab.active')?.dataset.tab", js)
        self.assertNotIn("document.querySelector('.stab.active')?.dataset.tab", js)

    def test_database_tab_is_sqlite_only(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        self.assertNotIn("Runtime Database", js)
        self.assertIn("Database Maintenance", js)
        for stale in ("s-postgres_host", "s-postgres_password", "btn-test-postgres",
                      "PostgreSQL (external)", "docs/postgresql.md"):
            self.assertNotIn(stale, js)

    def test_stalled_download_recovery_remains_download_scoped(self):
        js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()
        general = js.split('id="tab-general"', 1)[1].split('id="tab-download"', 1)[0]
        download = js.split('id="tab-download"', 1)[1].split('id="tab-extract"', 1)[0]
        self.assertNotIn('id="s-stuck_download_timeout_hours"', general)
        self.assertIn('id="s-stuck_download_timeout_hours"', download)
        self.assertIn("Auto-Recover Stalled Downloads", download)
        self.assertIn("regardless of transfer source", download)


if __name__ == "__main__":
    unittest.main()
