from pathlib import Path

from core.branding import APP_METADATA_TITLE, APP_NAME, APP_SHORT_NAME, REPOSITORY_URL
from core.config import AppSettings
from main import app


REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_SETTINGS = {
    "sonarr_enabled",
    "radarr_enabled",
    "jackett_enabled",
    "prowlarr_enabled",
    "flexget_enabled",
    "rules_enabled",
    "saved_searches_interval_minutes",
    "plex_url",
    "jellyfin_url",
    "on_torrent_complete",
    "download_profiles",
    "priority_aging_interval_minutes",
    "watch_folder",
    "processed_folder",
    "watch_interval_seconds",
}

REMOVED_ROUTE_MARKERS = {
    "/api/v2",
    "/jackett",
    "/prowlarr",
    "/flexget",
    "/saved-searches",
    "/rules/",
    "/download-profiles",
    "/webhooks/test",
}


def test_v1_identity_is_debridpulse_everywhere_it_is_centralized():
    assert APP_NAME == "DebridPulse"
    assert APP_SHORT_NAME == "DebridPulse"
    assert APP_METADATA_TITLE == "DebridPulse — Multi-provider Debrid Download Manager"
    assert REPOSITORY_URL == "https://github.com/Xipher-Zero/debridpulse"


def test_removed_services_and_qbit_router_are_not_shipped():
    removed_files = (
        "backend/api/qbit.py",
        "backend/services/flexget.py",
        "backend/services/integrations.py",
        "backend/services/jackett.py",
        "backend/services/learning.py",
        "backend/services/media_server.py",
        "backend/services/prowlarr.py",
        "backend/services/rules.py",
        "backend/services/webhook_actions.py",
    )
    assert not [path for path in removed_files if (REPO_ROOT / path).exists()]


def test_removed_settings_are_not_accepted_by_v1_model():
    assert REMOVED_SETTINGS.isdisjoint(AppSettings.model_fields)


def test_removed_api_routes_are_not_registered():
    routes = {getattr(route, "path", "") for route in app.routes}
    assert not {
        path
        for path in routes
        if any(marker in path for marker in REMOVED_ROUTE_MARKERS)
    }


def test_api_has_no_duplicate_method_and_path_registrations():
    registrations = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    ]
    assert len(registrations) == len(set(registrations))


def test_frontend_and_runtime_lock_have_no_legacy_surface():
    frontend = "\n".join(
        (REPO_ROOT / path).read_text().casefold()
        for path in ("frontend/static/index.html", "frontend/static/app.js")
    )
    for marker in (
        "qbittorrent",
        "jackett",
        "prowlarr",
        "flexget",
        "saved-search",
        "sonarr",
        "radarr",
    ):
        assert marker not in frontend

    requirements = (REPO_ROOT / "backend/requirements.txt").read_text().casefold()
    assert "bencode2==0.3.33" in requirements
    assert "bencodepy" not in requirements


def test_operator_tab_title_uses_short_active_identity_and_queue_average():
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    routes = (REPO_ROOT / "backend/api/routes.py").read_text()

    assert "document.title = 'DebridPulse';" in frontend
    assert "document.title = `DP | (${active} Active) ${progress}%`;" in frontend
    assert "document.title = `DebridPulse | (${active} Active)" not in frontend

    assert "AVG(COALESCE(progress, 0)) AS average_progress" in routes
    assert "AS weighted_progress" not in routes
    assert "WHERE status='downloading'" in routes


def test_dashboard_recent_activity_exposes_pause_resume_but_not_remove():
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    index = (REPO_ROOT / "frontend/static/index.html").read_text()

    recent_renderer = frontend.split("async function loadRecent()", 1)[1].split(
        "function openTorrentFilePicker()", 1
    )[0]
    recent_markup = index.split('id="dash-activity-card"', 1)[1].split(
        "</table>", 1
    )[0]

    assert "pauseT(${t.id})" in recent_renderer
    assert "resumeT(${t.id})" in recent_renderer
    assert "Pause this download" in recent_renderer
    assert "Resume this download" in recent_renderer
    assert "deleteT(" not in recent_renderer
    assert "Remove" not in recent_markup
    assert 'colspan="6"' in recent_markup

    assert frontend.count("loadTorrents(); loadStats(); loadRecent();") == 2


def test_global_pause_control_is_explicitly_labeled_pause_all():
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    routes = (REPO_ROOT / "backend/api/routes.py").read_text()

    assert "${paused ? 'Resume All' : 'Pause All'}" in frontend
    assert "${paused ? 'Resume' : 'Pause All'}" not in frontend
    assert "${paused ? 'Resume' : 'Pause'}" not in frontend

    pause_handler = frontend.split("async function pauseProcessing()", 1)[1].split(
        "async function resumeProcessing()", 1
    )[0]
    assert "loadRecent();" in pause_handler
    assert "loadTorrents()" in pause_handler

    pause_route = routes.split("async def pause_processing():", 1)[1].split(
        '@router.post("/processing/resume")', 1
    )[0]
    resume_route = routes.split("async def resume_processing():", 1)[1].split(
        "# ── Changelog", 1
    )[0]
    assert "await manager.pause_all_downloads()" in pause_route
    assert "await manager.resume_all_downloads()" in resume_route

    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    sync_handler = manager.split("async def sync_aria2_downloads(self):", 1)[1].split(
        "async def _reset_torrent_for_redownload", 1
    )[0]
    dispatch_handler = manager.split(
        "async def _dispatch_pending_aria2_queue", 1
    )[1].split("async def sync_download_clients", 1)[0]
    assert "if self.is_paused()" not in sync_handler.split("all_downloads =", 1)[0]
    assert "or self.is_paused()" in dispatch_handler.split("return", 1)[0]


def test_watch_folder_ingestion_is_not_shipped_in_v1():
    frontend = "\n".join(
        (REPO_ROOT / path).read_text()
        for path in ("frontend/static/index.html", "frontend/static/app.js")
    )
    scheduler = (REPO_ROOT / "backend/core/scheduler.py").read_text()
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()

    for marker in (
        'id="s-watch_folder"',
        'id="s-processed_folder"',
        'id="s-watch_interval_seconds"',
        "Watch Folder Scan",
    ):
        assert marker not in frontend

    assert "watch_folder_loop" not in scheduler
    assert "scan_watch_folder" not in manager
    assert "_handle_magnet_file" not in manager
    assert "_handle_torrent" not in manager


def test_dashboard_kpi_strip_omits_duplicate_database_tile_and_stays_centered():
    index = (REPO_ROOT / "frontend/static/index.html").read_text()
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    styles = (REPO_ROOT / "frontend/static/style.css").read_text()

    dashboard_strip = index.split(
        '<div class="dash-kpi-strip dash-kpi-strip--dashboard">', 1
    )[1].split('</div>\n\n      <div id="debug-status"', 1)[0]

    assert dashboard_strip.count('class="dash-kpi"') == 6
    assert 'id="i-db-type"' not in dashboard_strip
    assert '<div class="dash-kpi-lbl">Database</div>' not in dashboard_strip
    assert "getElementById('i-db-type')" not in frontend
    assert "setDot('db'" in frontend
    assert ".dash-kpi-strip--dashboard" in styles
    assert "width: 85.7142857%;" in styles
