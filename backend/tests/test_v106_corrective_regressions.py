import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_provider_quiescence_waits_for_inflight_operation():
    from services.provider_gateway import ProviderGateway

    started = asyncio.Event()
    release = asyncio.Event()

    async def add_magnet_direct(magnet, source="manual"):
        started.set()
        await release.wait()
        return {"ok": True}

    engine = SimpleNamespace(add_magnet_direct=add_magnet_direct)
    gateway = ProviderGateway(engine)
    operation = asyncio.create_task(gateway.add_magnet("magnet:?xt=urn:btih:test"))
    await started.wait()
    quiesce = asyncio.create_task(gateway.begin_quiescence())
    await asyncio.sleep(0)
    assert not quiesce.done()
    release.set()
    await operation
    await quiesce
    with pytest.raises(RuntimeError, match="quiesced"):
        await gateway.add_magnet("magnet:?xt=urn:btih:blocked")
    await gateway.end_quiescence()


def test_provider_delete_requires_positive_local_ownership():
    from services.manager_v2 import TorrentManager

    assert TorrentManager._provider_delete_authorized("manual") is True
    assert TorrentManager._provider_delete_authorized("manual_file") is True
    assert TorrentManager._provider_delete_authorized("alldebrid_existing") is False
    assert TorrentManager._provider_delete_authorized("import_existing") is False
    assert TorrentManager._provider_delete_authorized("") is False
    assert TorrentManager._provider_delete_authorized(None) is False


def test_orphan_cleanup_never_treats_unknown_as_delete_authority():
    source = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()
    block = source.split("async def cleanup_alldebrid_orphans", 1)[1].split("async def _apply_provider_update", 1)[0]
    assert "local is None" in block
    assert "_provider_delete_authorized" in block
    assert "local is None" in block
    assert "not self._provider_delete_authorized" in block
    assert block.index("local is None") < block.index("delete_magnet(ad_id)")
    assert "preserving unowned/unknown provider object" in block


def test_database_wipe_route_releases_quiescence_in_finally():
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text()
    block = routes.split('async def wipe_database_admin', 1)[1].split('# ── Statistics & Reporting', 1)[0]
    assert "quiesce_for_database_wipe" in block
    assert "finally:" in block
    assert "release_database_wipe_quiescence" in block


def test_settings_secret_merge_preserve_replace_clear():
    from api.routes import SettingsUpdate, _merge_secret_settings
    from core.config import AppSettings

    previous = AppSettings(alldebrid_api_key="old-key", auth_username="old-user", auth_password="old-pass")

    payload = previous.model_dump()
    payload.update(alldebrid_api_key="", auth_password="")
    preserve = SettingsUpdate(**payload)
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    payload = previous.model_dump()
    payload.update(auth_username="new-user", auth_password="new-pass")
    replace = SettingsUpdate(**payload)
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    payload = previous.model_dump()
    payload.update(auth_password="", clear_secrets=["auth_password"])
    clear = SettingsUpdate(**payload)
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    payload = previous.model_dump()
    payload.update(clear_secrets=["not_a_secret"])
    with pytest.raises(Exception):
        _merge_secret_settings(SettingsUpdate(**payload), previous)


def test_frontend_xss_and_secret_contracts():
    root = Path(__file__).resolve().parents[2]
    js = (root / "frontend/static/app.js").read_text()
    html = (root / "frontend/static/index.html").read_text()
    toast = js.split("function toast", 1)[1].split("function setButtonPending", 1)[0]
    assert "innerHTML" not in toast
    assert "text.textContent = String(msg ?? '')" in toast
    assert "${esc(ev.torrent_name)}" in js
    assert "auth_username: t('auth_username')" in js
    assert "auth_password: t('auth_password')" in js
    assert "clear_secrets: clearSecrets" in js
    assert "alldebrid_api_key_configured" in js
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js" not in html
    assert '/vendor/chart.umd.min.js?v=4.4.1' in html


def test_bulk_actions_are_schema_limited():
    from api.routes import BulkAction
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BulkAction(ids=[1], action="nonsense")


def test_codeql_covers_browser_javascript():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/codeql.yml").read_text()
    assert "javascript-typescript" in workflow


def test_dependency_docs_match_removed_runtime_components():
    root = Path(__file__).resolve().parents[2]
    docs = (root / "docs/DEPENDENCY_LICENSES.md").read_text()
    requirements = (root / "backend/requirements.txt").read_text().lower()
    dockerfile = (root / "Dockerfile").read_text().lower()
    assert "asyncpg" not in requirements
    assert "| asyncpg |" not in docs
    assert "unrar-free" not in dockerfile
    assert "| unrar-free |" not in docs
    assert "Chart.js | 4.4.1, vendored" in docs
    assert (root / "licenses/Chart.js-MIT.txt").is_file()
    assert (root / "frontend/static/vendor/chart.umd.min.js").is_file()
