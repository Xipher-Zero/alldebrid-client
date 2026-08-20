from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

index = ROOT / "frontend/static/index.html"
html = index.read_text()
old = '''          <div style="display:flex;gap:6px">
            <button class="btn btn-ghost btn-sm" id="btn-import-existing"'''
new = '''          <div style="display:flex;gap:6px;margin-left:auto">
            <button class="btn btn-ghost btn-sm" id="btn-import-existing"'''
count = html.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one unified action group target, found {count}")
index.write_text(html.replace(old, new, 1))

contracts = ROOT / "backend/tests/test_v106_audit_contracts.py"
tests = contracts.read_text()
needle = "    assert 'font-size:11px;font-weight:400;color:var(--text3)' in html\n"
replacement = needle + "    assert 'style=\"display:flex;gap:6px;margin-left:auto\"' in html\n"
count = tests.count(needle)
if count != 1:
    raise SystemExit(f"expected exactly one header style contract insertion point, found {count}")
contracts.write_text(tests.replace(needle, replacement, 1))

print("Pinned unified submission actions to the right edge")
