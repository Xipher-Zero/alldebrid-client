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
source = helper.read_text()
replace_once(
    helper,
    "extra = r'''",
    "extra = '''",
    "regression block quoting",
)
source = helper.read_text()
replace_once(
    helper,
    "app, count = re.subn(old_handlers_pattern, new_handlers, app, count=1, flags=re.S)",
    "app, count = re.subn(old_handlers_pattern, lambda _match: new_handlers, app, count=1, flags=re.S)",
    "literal frontend replacement",
)
source = helper.read_text()
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
