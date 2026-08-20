from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text()
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one target, found {count}")
    path.write_text(source.replace(old, new, 1))


def replace_function(path: Path, function_name: str, next_marker: str, replacement: str) -> None:
    source = path.read_text()
    start_marker = f"def {function_name}"
    count = source.count(start_marker)
    if count != 1:
        raise SystemExit(f"{path}: expected one {function_name}, found {count}")
    start = source.index(start_marker)
    end = source.index(next_marker, start)
    prefix = source[:start]
    suffix = source[end:]
    middle = replacement.rstrip()
    if middle:
        middle += "\n\n"
    path.write_text(prefix + middle + suffix)


# Keep the active recovery endpoint but remove the transitional wrapper module.
routes = ROOT / "backend/api/routes.py"
replace_once(
    routes,
    "    from services.recovery import run_recovery_checks\n    result = await run_recovery_checks()",
    "    result = await transfer_service.reconciliation.recover()",
    "recovery route migration",
)

# Patch helper-only quoting/substitution details before executing it.
helper = ROOT / "tools/v106_direct_cleanup.py"
replace_once(
    helper,
    "extra = r'''",
    "extra = '''",
    "regression block quoting",
)
replace_once(
    helper,
    "app, count = re.subn(old_handlers_pattern, new_handlers, app, count=1, flags=re.S)",
    "app, count = re.subn(old_handlers_pattern, lambda _match: new_handlers, app, count=1, flags=re.S)",
    "literal frontend replacement",
)
old_scan = '''all_python = "\\n".join(
    p.read_text(errors="ignore")
    for p in (ROOT / "backend").rglob("*.py")
)'''
new_scan = '''all_python = "\\n".join(
    p.read_text(errors="ignore")
    for p in (ROOT / "backend").rglob("*.py")
    if "tests" not in p.parts
)'''
replace_once(helper, old_scan, new_scan, "production residue scan")

runpy.run_path(str(helper), run_name="__main__")

# Remove the obsolete MediaInfo regression now that the surface is gone.
audit = ROOT / "backend/tests/test_v105_audit_regressions.py"
replace_function(
    audit,
    "test_mediainfo_service_uses_real_path_ancestry",
    "@pytest.mark.asyncio\nasync def test_service_permission_error_maps_to_http_403",
    "",
)

# Replace the old one-field direct-link resize contract with the unified field contract.
scope = ROOT / "backend/tests/test_v1_scope.py"
unified_test = '''def test_unified_submission_input_expands_to_five_lines():
    frontend = (REPO_ROOT / "frontend/static/index.html").read_text()
    scripts = (REPO_ROOT / "frontend/static/app.js").read_text()
    styles = (REPO_ROOT / "frontend/static/style.css").read_text()

    assert 'id="q-transfer-input" rows="2"' in frontend
    assert 'id="q-debrid-links"' not in frontend
    assert 'id="q-magnet"' not in frontend
    assert 'oninput="resizeDebridLinkInput(this)"' in frontend
    assert "function resizeDebridLinkInput(input)" in scripts
    assert "const minimum = Math.ceil((lineHeight * 2) + chrome);" in scripts
    assert "const maximum = Math.ceil((lineHeight * 5) + chrome);" in scripts
    assert "resizeDebridLinkInput(input);" in scripts
    assert ".direct-link-input" in styles
    assert "overflow-y: hidden" in styles'''
replace_function(
    scope,
    "test_direct_link_input_expands_to_five_lines_and_resets_after_submit",
    "def test_release_workflow_accepts_public_v1_tags",
    unified_test,
)

# Update the older v1.0.2 UI contract to the now-authoritative unified dashboard input.
scope_source = scope.read_text()
v102_start = scope_source.index("def test_v102_minor_ui_cleanup_contract():")
v102_replacement = '''def test_v102_minor_ui_cleanup_contract():
    index = (REPO_ROOT / "frontend/static/index.html").read_text()
    frontend = (REPO_ROOT / "frontend/static/app.js").read_text()
    styles = (REPO_ROOT / "frontend/static/style.css").read_text()

    assert '<div class="metric-label">Downloads</div>' in frontend
    assert '<div class="metric-label">Torrents</div>' not in frontend
    assert '<span class="card-title">Download Status</span>' in index
    assert '<span class="card-title">Torrent Status</span>' not in index

    assert '<textarea class="input direct-link-input" id="q-transfer-input" rows="2"' in index
    assert 'oninput="resizeDebridLinkInput(this)"' in index
    assert "(event.ctrlKey||event.metaKey)&&event.key==='Enter'" in index
    assert "addDashboardEntries()" in index
    unified_add = frontend.split("async function addDashboardEntries()", 1)[1].split(
        "// ── Torrents", 1
    )[0]
    assert "document.getElementById('q-transfer-input')" in unified_add
    assert "document.getElementById('btn-add-transfer')" in unified_add
    assert "openTorrentFilePicker();" in unified_add
    assert "resizeDebridLinkInput(input);" in unified_add
    assert "async function quickAdd()" not in frontend

    assert '.aria2-queue { display: flex; flex-direction: column; gap: 10px; min-width: 0; width: 100%; }' in styles
    assert 'max-width: 100%' in styles.split('.aria2-job {', 1)[1].split('}', 1)[0]
    assert 'overflow-wrap: anywhere' in styles.split('.aria2-job-name {', 1)[1].split('}', 1)[0]
    assert 'overflow-wrap: anywhere' in styles.split('.aria2-job-meta {', 1)[1].split('}', 1)[0]
    assert '/style.css?v=13' in index
    assert '/app.js?v=11' in index
'''
scope.write_text(scope_source[:v102_start] + v102_replacement)

# Update the direct-link dashboard contracts to the unified submission card and responsive recent limit.
direct_links = ROOT / "backend/tests/test_direct_links.py"
unified_dashboard_contract = '''def test_dashboard_and_downloads_page_match_unified_transfer_ui(self):
        repo_root = Path(__file__).resolve().parents[2]
        html = (repo_root / "frontend/static/index.html").read_text()
        js = (repo_root / "frontend/static/app.js").read_text()
        unified_heading = "⬇️ Add Links, Magnets, or Torrent File"
        self.assertIn(unified_heading, html)
        self.assertIn('id="q-transfer-input" rows="2"', html)
        self.assertIn('id="btn-add-transfer"', html)
        self.assertNotIn('id="q-debrid-links"', html)
        self.assertNotIn('id="q-magnet"', html)
        self.assertNotIn('data-view="aria2queue"', html)
        self.assertNotIn('id="t-magnet"', html)
        self.assertIn('<span class="nav-label">Downloads</span>', html)
        self.assertIn('id="torrent-card-title">All Downloads</span>', html)
        self.assertRegex(
            html,
            r'<script src="/app\\.js\\?v=\\d+" defer></script>',
        )
        self.assertIn("function classifyDashboardEntries", js)
        self.assertIn("async function addDashboardEntries()", js)
        self.assertIn("'/links/add'", js)
        self.assertIn("'/torrents/add-magnet'", js)
        self.assertIn("setButtonPending(button, true, 'Adding…')", js)
        self.assertIn("🔗 Direct link", js)
        self.assertIn("torrents:'Downloads'", js)
        self.assertIn("`All Downloads (${torrentTotal})`", js)
        self.assertIn("function sourceLabel(source)", js)
        self.assertIn("function transferDisplayStatus(t)", js)
        self.assertIn("missing:'❌ Missing file'", js)
        self.assertIn("downloading_with_errors:'⬇ Downloading'", js)
        self.assertIn("completed_with_errors:'⚠ Completed with errors'", js)
        self.assertIn("t.status === 'downloading'", js)
        self.assertIn("t.status === 'completed'", js)
        self.assertIn("String(t.error_message || '').trim()", js)
        manager_source = (repo_root / "backend/services/manager_v2.py").read_text()
        self.assertIn("File is no longer available on the source host", manager_source)
        self.assertIn("AND f.status != 'missing'", manager_source)
        self.assertIn("blocked=0 AND status!='missing'", manager_source)
        self.assertIn("required_count == 0 and missing_count > 0", manager_source)'''
replace_function(
    direct_links,
    "test_dashboard_and_downloads_page_match_unified_transfer_ui",
    "    def test_sidebar_and_settings_match_refined_navigation",
    unified_dashboard_contract,
)

recent_contract = '''def test_dashboard_is_a_fixed_at_a_glance_view(self):
        repo_root = Path(__file__).resolve().parents[2]
        html = (repo_root / "frontend/static/index.html").read_text()
        js = (repo_root / "frontend/static/app.js").read_text()
        css = (repo_root / "frontend/static/style.css").read_text()

        self.assertIn('<div id="content" class="dashboard-active">', html)
        self.assertIn('id="dash-activity-card"', html)
        self.assertIn('class="dash-activity-table-wrap"', html)
        self.assertIn("content.classList.toggle('dashboard-active', v === 'dashboard');", js)
        self.assertIn("function dashboardRecentLimit()", js)
        self.assertIn("window.matchMedia('(max-width: 700px)').matches ? 4 : 6", js)
        self.assertIn("api('GET', `/torrents?limit=${recentLimit}`)", js)
        self.assertIn("#content.dashboard-active { overflow-y: hidden; }", css)
        self.assertIn("#view-dashboard.active {", css)
        self.assertIn("#dash-activity-card {", css)'''
replace_function(
    direct_links,
    "test_dashboard_is_a_fixed_at_a_glance_view",
    'if __name__ == "__main__":',
    recent_contract,
)

# The unified Add button owns the dashboard pending state now.
ui = ROOT / "backend/tests/test_ui_responsiveness.py"
unified_pending = '''def test_dashboard_unified_add_button_has_its_own_pending_target():
    js = (REPO_ROOT / "frontend/static/app.js").read_text()
    html = (REPO_ROOT / "frontend/static/index.html").read_text()

    assert 'id="btn-add-transfer"' in html
    assert "document.getElementById('btn-add-transfer')" in js
    assert "setButtonPending(button, true, 'Adding…')" in js'''
replace_function(
    ui,
    "test_dashboard_magnet_button_has_its_own_pending_target",
    "def test_secondary_operator_controls_get_pending_feedback",
    unified_pending,
)

# Explicitly preserve the recovery API contract while proving the wrapper is gone.
contracts = ROOT / "backend/tests/test_v106_audit_contracts.py"
source = contracts.read_text()
marker = "test_recovery_route_survives_without_transitional_wrapper"
if marker in source:
    raise SystemExit("recovery boundary contract already present unexpectedly")
addition = '''

def test_recovery_route_survives_without_transitional_wrapper():
    root = Path(__file__).resolve().parents[1]
    routes = (root / "api" / "routes.py").read_text()
    block = routes.split('async def run_recovery():', 1)[1].split('# ──', 1)[0]
    assert 'transfer_service.reconciliation.recover()' in block
    assert 'services.recovery' not in block
    assert not (root / "services" / "recovery.py").exists()
'''
contracts.write_text(source.rstrip() + addition + "\n")

print("v1.0.6 gate preparation and stale-contract updates complete")
