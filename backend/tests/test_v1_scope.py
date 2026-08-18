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
