import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_live_refresh_keeps_action_nodes_stable_and_coalesces_core_loaders():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    assert "el.dataset.initialized !== '1'" in js
    assert 'id="btn-pause-all"' in js
    assert 'id="btn-resume-all"' in js
    assert "loadStats = coalesceAsync(loadStats);" in js
    assert "loadRecent = coalesceAsync(loadRecent);" in js
    assert "loadTorrents = coalesceAsync(loadTorrents);" in js


def test_progress_only_sse_updates_rows_without_forcing_full_render():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    manager = (
        REPO_ROOT / "backend/services/manager_v2.py"
    ).read_text()

    assert "function patchProgressOnlyTransferEvent(data)" in js
    assert 'data-role="transfer-progress"' in js
    assert 'data-status="${esc(t.status)}"' in js

    assert (
        '"progress_only": not any('
        in manager
    )
    assert (
        'item["status_changed"]'
        in manager
    )
    assert (
        "for item in changed_updates"
        in manager
    )
    assert '"items": changed_updates' in manager
    assert '"status_changed": status_changed' in manager


def test_async_controls_acknowledge_clicks_immediately():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    css = (REPO_ROOT / "frontend/static/style.css").read_text()

    for label in (
        "Pausing…",
        "Resuming…",
        "Retrying…",
        "Deleting…",
        "Queuing…",
    ):
        assert label in js

    assert '.btn:not(:disabled):active' in css
    assert 'aria-busy' in js


def test_detail_modal_opens_before_detail_request_finishes():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    detail = js.split(
        "async function showDetail(id)", 1
    )[1].split(
        "function closeModal", 1
    )[0]

    assert detail.index(
        "overlay.classList.add('open')"
    ) < detail.index(
        "await api('GET',`/torrents/${id}`)"
    )

    assert "Loading transfer details…" in detail


def test_settings_put_response_is_reused_without_followup_get():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    routes = (
        REPO_ROOT / "backend/api/routes.py"
    ).read_text()

    assert "data = _public_settings(clean)" in routes
    assert 'data["ok"] = True' in routes

    settings_put_assignments = re.findall(
        r"settingsData\s*=\s*await\s+api\(\s*'PUT'\s*,\s*'/settings'",
        js,
    )

    assert len(settings_put_assignments) == 5

    assert (
        "await api('PUT','/settings',d);\n"
        "    settingsData = await api('GET','/settings');"
        not in js
    )


def test_dashboard_magnet_button_has_its_own_pending_target():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    html = (
        REPO_ROOT / "frontend/static/index.html"
    ).read_text()

    assert 'id="btn-add-magnet"' in html
    assert (
        "document.getElementById('btn-add-magnet')"
        in js
    )


def test_secondary_operator_controls_get_pending_feedback():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    html = (REPO_ROOT / "frontend/static/index.html").read_text()

    for control_id in (
        "btn-import-existing",
        "btn-recover-all",
        "btn-save-settings",
        "btn-test-alldebrid",
        "btn-test-aria2",
        "btn-test-discord",
    ):
        assert f'id="{control_id}"' in html

    for signature in (
        "async function importExisting(button)",
        "async function recoverAll(button)",
        "async function bulkAction(action, button)",
        "async function saveSettings(button)",
        "async function testDiscord(button)",
        "async function testAD(button)",
        "async function testAria2(button)",
        "async function triggerFullSync(button)",
        "async function aria2RuntimeAction(action, button)",
        "async function runAria2Housekeeping(button)",
        "async function wipeDatabase(button)",
    ):
        assert signature in js

    for label in (
        "Importing…",
        "Recovering…",
        "Saving…",
        "Testing…",
        "Syncing…",
        "Restarting…",
        "Cleaning…",
        "Wiping…",
    ):
        assert label in js


def test_settings_remote_tests_hold_pending_state_through_remote_test():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    discord = js.split(
        "async function testDiscord(button)", 1
    )[1].split(
        "async function testAD(button)", 1
    )[0]

    assert discord.index(
        "'/settings/test-discord'"
    ) < discord.index(
        "renderSettings();"
    )

    aria2 = js.split(
        "async function testAria2(button)", 1
    )[1].split(
        "function renderAria2Diagnostics", 1
    )[0]

    assert aria2.index(
        "'/settings/test-aria2'"
    ) < aria2.index(
        "renderSettings();"
    )


def test_settings_aria2_queue_refresh_is_coalesced_and_actions_acknowledge():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    assert (
        "loadAria2Downloads =\n"
        "  coalesceAsync(loadAria2Downloads);"
        in js
    )

    assert (
        "async function refreshAria2Downloads(button)"
        in js
    )

    assert (
        "async function aria2DownloadAction(gid, action, button)"
        in js
    )

    assert "Refreshing…" in js
    assert "Removing…" in js

    wipe = js.split(
        "async function wipeDatabase(button)", 1
    )[1].split(
        "async function sendStatsReport", 1
    )[0]

    assert wipe.index(
        "if (confirmText !== 'WIPE') return;"
    ) < wipe.index(
        "'Wiping…'"
    )


def test_startup_initializer_and_queue_state_survive_ui_refactors():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    assert js.count("// ── Init ─") == 1
    assert js.count("var _aria2qTimer = null;") == 1
    assert js.count("var _aria2qErrCount = 0;") == 1

    init_start = js.index(
        "// ── Init ─"
    )

    queue_function = js.index(
        "async function loadAria2QueueView()"
    )

    init = js[
        init_start:queue_function
    ]

    assert "(async()=>{" in init
    assert (
        "settingsData = await api('GET', '/settings');"
        in init
    )
    assert "renderTopbarActions();" in init
    assert "updateAria2ngLink();" in init
    assert "statsLoaded = await loadStats();" in init

    assert re.search(
        r"new\s+EventSource\(\s*'/api/events/stream'\s*\)",
        init,
    )

    assert (
        "patchProgressOnlyTransferEvent("
        in init
    )

    assert "function startPolling()" in init

    assert (
        "checkConnections().catch(()=>{})"
        in init
    )

    settings_gets = re.findall(
        r"settingsData\s*=\s*await\s+api\("
        r"\s*'GET'\s*,\s*'/settings'\s*\)",
        js,
    )

    assert len(settings_gets) == 2

    # Queue loader relies on both state variables.
    queue = js.split(
        "async function loadAria2QueueView()", 1
    )[1]

    assert "_aria2qTimer" in queue
    assert "_aria2qErrCount" in queue


def test_stats_operator_actions_acknowledge_before_network_completion():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    assert (
        'onclick="triggerStatsSnapshot(this)"'
        in js
    )
    assert (
        'onclick="sendStatsReport(this)"'
        in js
    )

    send = js.split(
        "async function sendStatsReport(button)", 1
    )[1].split(
        "function exportStats", 1
    )[0]

    snapshot = js.split(
        "async function triggerStatsSnapshot(button)", 1
    )[1].split(
        "async function loadAnalytics", 1
    )[0]

    assert send.index(
        "setButtonPending("
    ) < send.index(
        "await api("
    )

    assert snapshot.index(
        "setButtonPending("
    ) < snapshot.index(
        "await api("
    )

    assert "'Sending…'" in send
    assert "'Taking…'" in snapshot

    assert (
        "setButtonPending(button, false);"
        in send
    )
    assert (
        "setButtonPending(button, false);"
        in snapshot
    )


def test_pass3_polling_noops_do_not_refresh_transfer_freshness():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()

    provider = manager.split(
        "async def _apply_provider_update", 1
    )[1].split(
        "async def _set_provider_missing", 1
    )[0]

    assert "meaningful_changed = (" in provider
    assert "if meaningful_changed:" in provider
    assert "if visible_changed:" in provider
    assert "persisted_progress = current_progress if local_delivery_active else progress" in provider
    assert "stable provider polling" in provider.lower()

    aggregate = (REPO_ROOT / "backend/services/transfer_state_machine.py").read_text()

    assert "if progress != current_progress or status != current_status:" in aggregate
    assert "if int(progress) != int(current_progress) or status != current_status:" in aggregate
    assert "await db.executemany(" in aggregate
    assert "updates.append((progress, status, transfer_id))" in aggregate

    sync = manager.split(
        "async def sync_aria2_downloads", 1
    )[1].split(
        "async def _reset_torrent_for_redownload", 1
    )[0]

    assert "f.download_id, f.status, f.blocked, f.size_bytes" in sync
    assert "def file_state_needs_update(desired_status: str)" in sync


def test_pass3_import_reconciliation_does_not_touch_stable_rows():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    imported = manager.split(
        "async def import_existing_magnets", 1
    )[1].split(
        "async def delete_torrent", 1
    )[0]

    assert "metadata_changed = (" in imported
    assert imported.count("if metadata_changed:") == 2
    assert "stuck-transfer watchdog" in imported
    assert "Stable provider" in imported


def test_pass3_frontend_queue_requests_search_and_filter_scope():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()

    runtime = js.split(
        "async function loadAria2Runtime()", 1
    )[1].split(
        "async function aria2RuntimeAction", 1
    )[0]
    assert "loadAria2Downloads" not in runtime

    switcher = js.split(
        "function switchSettingsTab", 1
    )[1].split(
        "function updateSettingsFooterActions", 1
    )[0]
    assert "loadAria2Runtime().catch(()=>{});" in switcher
    assert "loadAria2Downloads().catch(()=>{});" in switcher

    search = js.split(
        "function onTorrentSearchInput()", 1
    )[1].split(
        "async function loadTorrents()", 1
    )[0]
    assert "_torrentSearchTimer" in search
    assert "}, 250);" in search

    filter_fn = js.split(
        "function setFilter(el, status)", 1
    )[1].split(
        "function onTorrentSearchInput", 1
    )[0]
    assert "#view-torrents .filter-tabs .ftab" in filter_fn
    assert "document.querySelectorAll('.ftab')" not in filter_fn


def test_pass3_provider_noop_handles_zero_status_code_and_paused_delivery():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    provider = manager.split(
        "async def _apply_provider_update", 1
    )[1].split(
        "async def _increment_poll_failure", 1
    )[0]

    assert 'current_provider_code = row.get("provider_status_code")' in provider
    assert "if current_provider_code is not None" in provider
    assert "TorrentStatus.PAUSED" in provider
