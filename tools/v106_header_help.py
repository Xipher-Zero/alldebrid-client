from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

index = ROOT / "frontend/static/index.html"
source = index.read_text()
old = '''        <div class="card-header">
          <span class="card-title">⬇️ Add Links, Magnets, or Torrent File</span>
          <div style="display:flex;gap:6px">
            <button class="btn btn-ghost btn-sm" id="btn-import-existing" onclick="importExisting(this)" title="Import all AllDebrid magnets not yet in the local database">⬇ Import</button>
            <button class="btn btn-warn btn-sm" id="btn-recover-all" onclick="recoverAll(this)" title="Reset stuck or errored torrents — re-dispatches from AllDebrid">⟳ Recover All</button>
          </div>
        </div>
        <div style="padding:12px 16px">
          <div class="direct-link-entry">
            <textarea class="input direct-link-input" id="q-transfer-input" rows="2" placeholder="https://example-hoster.com/file/…&#10;magnet:?xt=urn:btih:…" oninput="resizeDebridLinkInput(this)" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')addDashboardEntries()"></textarea>
            <button class="btn btn-primary" id="btn-add-transfer" onclick="addDashboardEntries()" style="padding:9px 20px" title="Submit direct links and magnets through AllDebrid; when empty, choose a .torrent file">Add</button>
          </div>
          <div style="margin-top:6px;font-size:11px;color:var(--text3)">One item per line. Leave empty and click Add to choose a .torrent file.</div>
        </div>'''
new = '''        <div class="card-header">
          <div style="display:flex;align-items:baseline;column-gap:14px;row-gap:2px;flex-wrap:wrap;min-width:0">
            <span class="card-title">⬇️ Add Links, Magnets, or Torrent File</span>
            <span style="font-size:11px;font-weight:400;color:var(--text3)">One item per line · Empty + Add opens a .torrent file</span>
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn btn-ghost btn-sm" id="btn-import-existing" onclick="importExisting(this)" title="Import all AllDebrid magnets not yet in the local database">⬇ Import</button>
            <button class="btn btn-warn btn-sm" id="btn-recover-all" onclick="recoverAll(this)" title="Reset stuck or errored torrents — re-dispatches from AllDebrid">⟳ Recover All</button>
          </div>
        </div>
        <div style="padding:12px 16px">
          <div class="direct-link-entry">
            <textarea class="input direct-link-input" id="q-transfer-input" rows="2" placeholder="https://example-hoster.com/file/…&#10;magnet:?xt=urn:btih:…" oninput="resizeDebridLinkInput(this)" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')addDashboardEntries()"></textarea>
            <button class="btn btn-primary" id="btn-add-transfer" onclick="addDashboardEntries()" style="padding:9px 20px" title="Submit direct links and magnets through AllDebrid; when empty, choose a .torrent file">Add</button>
          </div>
        </div>'''
if source.count(old) != 1:
    raise SystemExit(f"unified submission markup target count: {source.count(old)}")
index.write_text(source.replace(old, new, 1))

contracts = ROOT / "backend/tests/test_v106_audit_contracts.py"
source = contracts.read_text()
old = '''    assert 'id="btn-add-transfer"' in html
    assert 'https://example-hoster.com/file/' in html
    assert 'magnet:?xt=urn:btih:' in html
'''
new = '''    assert 'id="btn-add-transfer"' in html
    assert 'https://example-hoster.com/file/' in html
    assert 'magnet:?xt=urn:btih:' in html
    assert 'One item per line · Empty + Add opens a .torrent file' in html
    assert 'column-gap:14px' in html
    assert 'font-size:11px;font-weight:400;color:var(--text3)' in html
    assert 'One item per line. Leave empty and click Add to choose a .torrent file.' not in html
'''
if source.count(old) != 1:
    raise SystemExit(f"unified submission contract target count: {source.count(old)}")
contracts.write_text(source.replace(old, new, 1))

print("v1.0.6 unified submission header refinement applied")
