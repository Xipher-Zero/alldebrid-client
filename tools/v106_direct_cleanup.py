from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)
    print(f"updated {path}")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement target, found {count}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one regex target, found {count}")
    write(path, updated)


def remove(path: str) -> None:
    target = ROOT / path
    if target.exists():
        target.unlink()
        print(f"removed {path}")


# 1. Remove orphaned/transitional backend surfaces.
for obsolete in (
    "backend/services/mediainfo.py",
    "backend/services/reconcile_cycle.py",
    "backend/services/recovery.py",
    "backend/tests/test_recovery.py",
):
    remove(obsolete)

regex_once(
    "backend/api/routes.py",
    r"\n# ── MediaInfo ─+.*?(?=\n# ── [^\n]+ ─+)",
    "",
    flags=re.S,
)

# Sanitize remaining scheduler/diagnostic exception surfaces.
for old, new in (
    ('logger.warning("Version check failed: %s", exc)', 'logger.warning("Version check failed: %s", sanitize_exception(exc))'),
    ('"error": str(exc)', '"error": sanitize_exception(exc)'),
    ('logger.warning("Could not apply aria2 memory settings immediately: %s", exc)', 'logger.warning("Could not apply aria2 memory settings immediately: %s", sanitize_exception(exc))'),
    ('diagnostics = {"error": str(exc)}', 'diagnostics = {"error": sanitize_exception(exc)}'),
):
    text = read("backend/api/routes.py")
    if old in text:
        write("backend/api/routes.py", text.replace(old, new))

scheduler_replacements = {
    'logger.error(f"Status sync error: {e}")': 'logger.error("Status sync error: %s", sanitize_exception(e))',
    'logger.error(f"No-peer cleanup error: {e}")': 'logger.error("No-peer cleanup error: %s", sanitize_exception(e))',
    'logger.debug(f"AllDebrid orphan cleanup error: {e}")': 'logger.debug("AllDebrid orphan cleanup error: %s", sanitize_exception(e))',
    'logger.error(f"Stuck download cleanup error: {e}")': 'logger.error("Stuck download cleanup error: %s", sanitize_exception(e))',
    'logger.error(f"Download client sync error: {e}")': 'logger.error("Download client sync error: %s", sanitize_exception(e))',
    'logger.error(f"Deep aria2 sync error: {e}")': 'logger.error("Deep aria2 sync error: %s", sanitize_exception(e))',
    'logger.error(f"Backup error: {e}")': 'logger.error("Backup error: %s", sanitize_exception(e))',
    'logger.error(f"aria2 housekeeping error: {e}")': 'logger.error("aria2 housekeeping error: %s", sanitize_exception(e))',
    'logger.error("aria2 log rotation error: %s", e)': 'logger.error("aria2 log rotation error: %s", sanitize_exception(e))',
    'logger.error("aria2_restart_loop error: %s", e)': 'logger.error("aria2_restart_loop error: %s", sanitize_exception(e))',
    'logger.warning("update_check_loop error: %s", exc)': 'logger.warning("update_check_loop error: %s", sanitize_exception(exc))',
    'logger.warning("events_ttl_loop error: %s", exc)': 'logger.warning("events_ttl_loop error: %s", sanitize_exception(exc))',
    'logger.debug(f"disk_guard check error: {e}")': 'logger.debug("disk_guard check error: %s", sanitize_exception(e))',
    'logger.error(f"Stats snapshot error: {e}")': 'logger.error("Stats snapshot error: %s", sanitize_exception(e))',
    'logger.error(f"Stats report error: {e}")': 'logger.error("Stats report error: %s", sanitize_exception(e))',
}
scheduler = read("backend/core/scheduler.py")
for old, new in scheduler_replacements.items():
    if old not in scheduler:
        raise RuntimeError(f"scheduler target missing: {old}")
    scheduler = scheduler.replace(old, new, 1)
write("backend/core/scheduler.py", scheduler)

# 2. Count every outbound AllDebrid retry attempt against the provider limiter.
replace_once(
    "backend/services/alldebrid.py",
    '''        await acquire_alldebrid_request_slot()\n\n        url = f"{base}/{endpoint}"\n''',
    '''        url = f"{base}/{endpoint}"\n''',
)
replace_once(
    "backend/services/alldebrid.py",
    '''        for attempt in range(1, attempts + 1):\n            result = None\n''',
    '''        for attempt in range(1, attempts + 1):\n            await acquire_alldebrid_request_slot()\n            result = None\n''',
)

# 3. Live-watch external extraction staging so deceptive metadata cannot grow
#    without an active file-count/expanded-size/ratio check.
insert_before = '''\ndef validate_extracted_tree(root: Path, archive: Path) -> None:\n'''
live_guard = '''\ndef validate_staging_tree(root: Path, archive: Path) -> None:\n    """Validate a live external-extractor staging tree.\n\n    The scan is intentionally race-tolerant: files may disappear between\n    rglob/lstat/stat while the extractor is active. Unsafe links/special files\n    and budget overruns are still rejected as soon as a stable observation\n    sees them.\n    """\n    root = root.resolve()\n    file_count = 0\n    expanded = 0\n    for current in root.rglob("*"):\n        try:\n            mode = current.lstat().st_mode\n        except FileNotFoundError:\n            continue\n        if stat.S_ISLNK(mode):\n            raise ValueError(f"Extracted archive created a symlink: {current.name!r}")\n        if stat.S_ISDIR(mode):\n            continue\n        if not stat.S_ISREG(mode):\n            raise ValueError(f"Extracted archive created a special file: {current.name!r}")\n        try:\n            size = max(0, int(current.stat().st_size))\n        except FileNotFoundError:\n            continue\n        file_count += 1\n        expanded += size\n    validate_budget(archive=archive, file_count=file_count, expanded_bytes=expanded)\n\n'''
replace_once("backend/services/extraction_safety.py", insert_before, live_guard + insert_before)

extractor = read("backend/services/extractor.py")
extractor = extractor.replace("import subprocess\n", "import subprocess\nimport tempfile\nimport time\n", 1)
extractor = extractor.replace(
    "    staged_external_extract,\n",
    "    staged_external_extract,\n    validate_staging_tree,\n",
    1,
)
run_tool_pattern = r'''def _run_tool\(cmd: List\[str\], timeout: int = 3600\) -> Tuple\[int, str\]:\n.*?\n\ndef _extract_zip'''
run_tool_replacement = '''def _run_tool(\n    cmd: List[str],\n    timeout: int = 3600,\n    *,\n    watch_dir: Path | None = None,\n    watch_archive: Path | None = None,\n) -> Tuple[int, str]:\n    """Run an external command and optionally enforce a live staging budget."""\n    kwargs = {}\n    if os.name == "posix":\n        kwargs["preexec_fn"] = lambda: os.nice(10)\n\n    started = time.monotonic()\n    try:\n        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as capture:\n            process = subprocess.Popen(\n                cmd,\n                stdout=capture,\n                stderr=subprocess.STDOUT,\n                text=True,\n                **kwargs,\n            )\n            guard_error = ""\n            timed_out = False\n            while process.poll() is None:\n                if time.monotonic() - started > timeout:\n                    timed_out = True\n                    process.kill()\n                    break\n                if watch_dir is not None and watch_archive is not None:\n                    try:\n                        validate_staging_tree(watch_dir, watch_archive)\n                    except ValueError as exc:\n                        guard_error = str(exc)\n                        process.kill()\n                        break\n                time.sleep(0.25)\n\n            process.wait(timeout=10)\n            capture.flush()\n            capture.seek(0)\n            output = capture.read().strip()\n            if guard_error:\n                return -1, f"Extraction safety limit: {guard_error}"\n            if timed_out:\n                return -1, f"Timeout after {timeout}s"\n            return int(process.returncode or 0), output\n    except FileNotFoundError as exc:\n        return -1, str(exc)\n\n\ndef _extract_zip'''
extractor, count = re.subn(run_tool_pattern, run_tool_replacement, extractor, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"extractor: expected one _run_tool block, found {count}")
count = extractor.count("rc, _out = _run_tool(cmd)")
if count != 2:
    raise RuntimeError(f"extractor: expected two extraction _run_tool calls, found {count}")
extractor = extractor.replace(
    "rc, _out = _run_tool(cmd)",
    "rc, _out = _run_tool(cmd, watch_dir=dest, watch_archive=archive)",
)
write("backend/services/extractor.py", extractor)

# 4. Dashboard: one mixed submission field; backend endpoints remain separate.
old_dashboard = '''      <!-- ── Add Direct Debrid Links ──────────────────────────────────────── -->\n      <div class="card" style="margin-bottom:14px">\n        <div class="card-header">\n          <span class="card-title">⬇️ Add Links to Generate and Download Debrid Links</span>\n        </div>\n        <div style="padding:12px 16px">\n          <div class="direct-link-entry">\n            <textarea class="input direct-link-input" id="q-debrid-links" rows="1" placeholder="https://example-hoster.com/file/… or paste multiple links, one per line" oninput="resizeDebridLinkInput(this)" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')addDebridLinks()"></textarea>\n            <button class="btn btn-primary" id="btn-add-debrid-links" onclick="addDebridLinks()" style="padding:9px 20px" title="Generate each link through AllDebrid and queue the resulting downloads in aria2">Add</button>\n          </div>\n        </div>\n      </div>\n\n      <!-- ── Add Magnet or Torrent File ─────────────────────────────────────── -->\n      <div class="card" style="margin-bottom:14px">\n        <div class="card-header">\n          <span class="card-title">🧲 Add Magnet Links or a Torrent File</span>\n          <div style="display:flex;gap:6px">\n            <button class="btn btn-ghost btn-sm" id="btn-import-existing" onclick="importExisting(this)" title="Import all AllDebrid magnets not yet in the local database">⬇ Import</button>\n            <button class="btn btn-warn btn-sm" id="btn-recover-all" onclick="recoverAll(this)" title="Reset stuck or errored torrents — re-dispatches from AllDebrid">⟳ Recover All</button>\n          </div>\n        </div>\n        <div style="padding:12px 16px">\n          <div class="direct-link-entry">\n            <textarea class="input direct-link-input" id="q-magnet" rows="1" placeholder="magnet:?xt=urn:btih:… or paste multiple lines, one per line" oninput="resizeDebridLinkInput(this)" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')quickAdd()"></textarea>\n            <button class="btn btn-primary" id="btn-add-magnet" onclick="quickAdd()" style="padding:9px 20px" title="Add entered magnet links, or choose a .torrent file when the field is empty">Add</button>\n          </div>\n        </div>\n      </div>\n'''
new_dashboard = '''      <!-- ── Unified transfer submission ───────────────────────────────────── -->\n      <div class="card" style="margin-bottom:14px">\n        <div class="card-header">\n          <span class="card-title">⬇️ Add Links, Magnets, or Torrent File</span>\n          <div style="display:flex;gap:6px">\n            <button class="btn btn-ghost btn-sm" id="btn-import-existing" onclick="importExisting(this)" title="Import all AllDebrid magnets not yet in the local database">⬇ Import</button>\n            <button class="btn btn-warn btn-sm" id="btn-recover-all" onclick="recoverAll(this)" title="Reset stuck or errored torrents — re-dispatches from AllDebrid">⟳ Recover All</button>\n          </div>\n        </div>\n        <div style="padding:12px 16px">\n          <div class="direct-link-entry">\n            <textarea class="input direct-link-input" id="q-transfer-input" rows="2" placeholder="https://example-hoster.com/file/…&#10;magnet:?xt=urn:btih:…" oninput="resizeDebridLinkInput(this)" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')addDashboardEntries()"></textarea>\n            <button class="btn btn-primary" id="btn-add-transfer" onclick="addDashboardEntries()" style="padding:9px 20px" title="Submit direct links and magnets through AllDebrid; when empty, choose a .torrent file">Add</button>\n          </div>\n          <div style="margin-top:6px;font-size:11px;color:var(--text3)">One item per line. Leave empty and click Add to choose a .torrent file.</div>\n        </div>\n      </div>\n'''
replace_once("frontend/static/index.html", old_dashboard, new_dashboard)

app = read("frontend/static/app.js")
app = app.replace(
    "async function loadRecent() {\n  try {\n    const {items} = await api('GET', '/torrents?limit=4');",
    "function dashboardRecentLimit() {\n  return window.matchMedia('(max-width: 700px)').matches ? 4 : 6;\n}\n\nasync function loadRecent() {\n  try {\n    const recentLimit = dashboardRecentLimit();\n    const {items} = await api('GET', `/torrents?limit=${recentLimit}`);",
    1,
)
old_handlers_pattern = r'''async function quickAdd\(\) \{.*?\n\}\n\nfunction resizeDebridLinkInput\(input\) \{.*?\n\}\n\nasync function addDebridLinks\(\) \{.*?\n\}\n\n// ── Torrents'''
new_handlers = '''function resizeDebridLinkInput(input) {\n  if (!input) return;\n  const styles = window.getComputedStyle(input);\n  const lineHeight = parseFloat(styles.lineHeight) || 18;\n  const chrome = (parseFloat(styles.paddingTop) || 0) +\n    (parseFloat(styles.paddingBottom) || 0) +\n    (parseFloat(styles.borderTopWidth) || 0) +\n    (parseFloat(styles.borderBottomWidth) || 0);\n  const minimum = Math.ceil((lineHeight * 2) + chrome);\n  const maximum = Math.ceil((lineHeight * 5) + chrome);\n  input.style.height = `${minimum}px`;\n  const target = Math.max(minimum, Math.min(input.scrollHeight, maximum));\n  input.style.height = `${target}px`;\n  input.style.overflowY = input.scrollHeight > maximum ? 'auto' : 'hidden';\n}\n\nfunction classifyDashboardEntries(raw) {\n  const seen = new Set();\n  const direct = [];\n  const magnets = [];\n  const invalid = [];\n  String(raw || '').split(/\\r?\\n/).forEach((rawValue, index) => {\n    const value = rawValue.trim();\n    if (!value || seen.has(value)) return;\n    seen.add(value);\n    const entry = {value, line: index + 1};\n    if (/^https?:\\/\\/\\S+$/i.test(value)) direct.push(entry);\n    else if (/^magnet:\\?/i.test(value)) magnets.push(entry);\n    else invalid.push(entry);\n  });\n  return {direct, magnets, invalid};\n}\n\nasync function mapWithConcurrency(items, concurrency, worker) {\n  const results = new Array(items.length);\n  let cursor = 0;\n  async function run() {\n    while (cursor < items.length) {\n      const index = cursor++;\n      try {\n        results[index] = {ok: true, value: await worker(items[index])};\n      } catch (error) {\n        results[index] = {ok: false, error};\n      }\n    }\n  }\n  const workers = Array.from(\n    {length: Math.min(Math.max(1, concurrency), Math.max(1, items.length))},\n    () => run()\n  );\n  await Promise.all(workers);\n  return results;\n}\n\nasync function addDashboardEntries() {\n  const input = document.getElementById('q-transfer-input');\n  const button = document.getElementById('btn-add-transfer');\n  const raw = input?.value || '';\n  if (!raw.trim()) {\n    openTorrentFilePicker();\n    return;\n  }\n\n  const {direct, magnets, invalid} = classifyDashboardEntries(raw);\n  if (invalid.length) {\n    const first = invalid[0];\n    toast(`Line ${first.line}: enter an HTTP(S) link or magnet URI`, 'error');\n    input?.focus();\n    return;\n  }\n  if (!direct.length && !magnets.length) {\n    toast('Enter at least one HTTP(S) link or magnet URI', 'warn');\n    input?.focus();\n    return;\n  }\n\n  setButtonPending(button, true, 'Adding…');\n  const failed = [];\n  let handled = 0;\n  try {\n    if (direct.length) {\n      try {\n        await api('POST', '/links/add', {links: direct.map(entry => entry.value)}, 30000);\n        handled += direct.length;\n      } catch (error) {\n        direct.forEach(entry => failed.push({...entry, error}));\n      }\n    }\n\n    if (magnets.length) {\n      const results = await mapWithConcurrency(\n        magnets,\n        3,\n        entry => api('POST', '/torrents/add-magnet', {magnet: entry.value}, 30000)\n      );\n      results.forEach((result, index) => {\n        if (result.ok) handled += 1;\n        else failed.push({...magnets[index], error: result.error});\n      });\n    }\n\n    failed.sort((a, b) => a.line - b.line);\n    input.value = failed.map(entry => entry.value).join('\\n');\n    resizeDebridLinkInput(input);\n    input.focus();\n\n    if (failed.length) {\n      toast(`${handled} handled · ${failed.length} failed`, handled ? 'warn' : 'error');\n    } else {\n      toast(`${handled} item${handled === 1 ? '' : 's'} submitted`, 'success');\n    }\n\n    if (handled) {\n      loadStats();\n      loadRecent();\n      if (document.getElementById('view-torrents')?.classList.contains('active')) {\n        loadTorrents();\n      }\n    }\n  } finally {\n    setButtonPending(button, false);\n  }\n}\n\n// ── Torrents'''
app, count = re.subn(old_handlers_pattern, new_handlers, app, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"app.js: expected one dashboard handler block, found {count}")
write("frontend/static/app.js", app)

# Remove inherited search/indexer CSS that has no V1 HTML/JS consumer, and let
# Recent Activity use the lower viewport space with a vertical safety scroll.
css = read("frontend/static/style.css")
for token in ("search-tags-row", "idx-picker", "idx-dropdown"):
    html_js = read("frontend/static/index.html") + read("frontend/static/app.js")
    if token in html_js:
        raise RuntimeError(f"obsolete CSS selector is still referenced: {token}")
css, count = re.subn(
    r"/\* ── Search Advanced Tags ─+ \*/.*?(?=/\* ── Mobile responsive \(max 700px\) ─+ \*/)",
    "",
    css,
    count=1,
    flags=re.S,
)
if count != 1:
    raise RuntimeError(f"style.css: obsolete search/indexer block count={count}")
css = css.replace(
    ".dash-activity-table-wrap {\n  flex:1;\n  min-height:0;\n  overflow:hidden;\n  overflow-x:auto;",
    ".dash-activity-table-wrap {\n  flex:1;\n  min-height:0;\n  overflow:auto;",
    1,
)
write("frontend/static/style.css", css)

# 5. Documentation/deployment hardening.
security = '''# Security Policy\n\n## Supported Versions\n\n| Version | Supported |\n|---------|-----------|\n| 1.0.x   | ✅ Yes     |\n| < 1.0.0 | ❌ No      |\n\nOnly the latest release receives security fixes. Please update before reporting.\n\n---\n\n## Reporting a Vulnerability\n\n**Do not open a public GitHub issue for security vulnerabilities.**\n\nReport security issues through a private GitHub Security Advisory (preferred), or contact the maintainer through the repository profile. Include the vulnerability, reproduction steps, likely impact, and any suggested mitigation.\n\n---\n\n## Security Considerations\n\n### Secrets and configuration\n\nThe AllDebrid API key, optional HTTP Basic Authentication password, Discord webhook URLs, aria2 credentials, and extraction passwords are secrets stored in `config/config.json`. Keep that file private:\n\n```bash\nchmod 600 config/config.json\n```\n\nDo not publish the config volume or commit it to version control. API responses intentionally redact configured secret values and capability-bearing provider/download URLs.\n\n### Web UI and API access control\n\nDebridPulse supports optional HTTP Basic Authentication in **Settings → General**. Authentication is disabled until credentials are configured. When enabled, state-changing cross-origin requests are rejected and credentials are compared using constant-time checks.\n\nFor any network you do not fully trust, enable DebridPulse authentication and/or place the application behind an authenticated reverse proxy such as Authentik, Authelia, or an equivalent access-control layer.\n\n**Do not expose port 8080 directly to the public internet.** The generic Compose example uses bridge networking with an explicit port mapping so exposure remains visible and can be bound/restricted by the operator. Host networking should be an explicit deployment choice, not the generic default.\n\n### Shared external aria2\n\nExternal aria2 may be shared with unrelated applications. DebridPulse records ownership for GIDs it creates, permits per-GID mutations only for owned downloads, and avoids daemon-global mutation outside built-in aria2 mode. Keep aria2 RPC itself on a trusted network and configure its RPC secret when supported.\n\n### Archive extraction\n\nArchive extraction enforces member-path/type checks plus file-count, expanded-size, and compression-ratio budgets. External 7z/RAR extraction occurs in an isolated staging directory, is monitored while the extractor runs, and is validated again before files are merged into the download tree.\n\n### Backups and database maintenance\n\nDatabase wipe requires verified transfer quiescence and fails closed if a required pre-wipe backup fails. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.\n\n### Discord webhook URL\n\nTreat Discord webhook URLs as secrets: possession of the URL permits posting to the configured channel.\n\n---\n\n## Scope\n\nThe following are **in scope** for security reports:\n\n- secret or capability-bearing URL exposure;\n- remote code execution;\n- path traversal or unsafe archive extraction;\n- authentication or authorization bypass;\n- cross-origin state-changing request bypass;\n- mutation of unrelated transfers on shared external aria2;\n- unsafe destructive database/backup behavior.\n\nThe following are **out of scope**:\n\n- issues in AllDebrid's own service/API;\n- vulnerabilities that exist solely in an unmodified third-party dependency (report upstream as well);\n- resource exhaustion requiring trusted local access with no network exposure, unless it crosses a documented DebridPulse safety boundary.\n'''
write("SECURITY.md", security)

compose = '''# DebridPulse — AllDebrid download manager\n# Generic bridge-network example. Adapt host paths, UID/GID and timezone.\n\nservices:\n  debridpulse:\n    image: ghcr.io/xipher-zero/debridpulse:v1.0.6\n    build: .\n    container_name: debridpulse\n    restart: unless-stopped\n    ports:\n      - "8080:8080"\n    volumes:\n      - /mnt/user/appdata/debridpulse/data:/app/data\n      - /mnt/user/appdata/debridpulse/config:/app/config\n      - /mnt/user/downloads:/download\n    environment:\n      - PUID=99\n      - PGID=100\n      - CONFIG_PATH=/app/config/config.json\n      - DB_PATH=/app/data/debridpulse.db\n      - TZ=Europe/Berlin\n    healthcheck:\n      test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]\n      interval: 30s\n      timeout: 10s\n      retries: 3\n      start_period: 20s\n'''
write("docker-compose.yml", compose)

readme = read("README.md")
readme = readme.replace(
    "| **Direct debrid links** | Submit ordinary HTTP/HTTPS links from AllDebrid-supported hosts directly from the Dashboard |\n| **Batch link submission** | Submit up to 100 unique direct links in one tracked transaction |\n| **Magnet links** | Submit one or more magnets through AllDebrid |",
    "| **Unified Dashboard submission** | Paste HTTP/HTTPS direct links and magnet URIs into one mixed-input control, or use the same Add action with an empty field to choose a `.torrent` file |\n| **Batch link submission** | Submit up to 100 unique direct links in one tracked transaction |\n| **Magnet links** | Submit one or more magnets through AllDebrid |",
    1,
)
readme = readme.replace(
    "Paste one or more HTTP/HTTPS links into the direct-link field on the Dashboard. DebridPulse then:",
    "Paste one or more HTTP/HTTPS links into the unified Dashboard submission field (direct links and magnets may be mixed, one item per line). DebridPulse then:",
    1,
)
readme = readme.replace(
    "- direct-link submission;\n- magnet and `.torrent` submission;",
    "- one unified direct-link/magnet submission field;\n- `.torrent` file selection from the same Add control when the field is empty;",
    1,
)
readme = readme.replace(
    "Review `docker-compose.yml` before starting it. Adapt host paths, UID/GID, timezone, networking, and persistent storage to your environment.",
    "Review `docker-compose.yml` before starting it. Adapt host paths, UID/GID, timezone, networking, and persistent storage to your environment. The generic example uses bridge networking and an explicit `8080:8080` port mapping; use host networking only when your platform specifically requires it.",
    1,
)
write("README.md", readme)

landing = read("index.html")
landing = landing.replace(
    '<span class="cm">network_mode</span>: <span class="str">host</span>',
    '<span class="cm">ports</span>: <span class="str">["8080:8080"]</span>',
    1,
)
landing = landing.replace("  --network host \\\n", "  -p 8080:8080 \\\n", 1)
landing = landing.replace("ghcr.io/xipher-zero/debridpulse:v1.0.0", "ghcr.io/xipher-zero/debridpulse:v1.0.6")
write("index.html", landing)

# 6. Regression contracts for the audit cleanup and unified Dashboard.
test_path = "backend/tests/test_v106_audit_contracts.py"
tests = read(test_path)
extra = r'''\n\ndef test_v106_transitional_and_mediainfo_residue_removed():\n    root = Path(__file__).resolve().parents[1]\n    for relative in ("services/mediainfo.py", "services/reconcile_cycle.py", "services/recovery.py"):\n        assert not (root / relative).exists()\n    routes = (root / "api" / "routes.py").read_text()\n    assert '/mediainfo' not in routes\n    assert 'services.mediainfo' not in routes\n\n\ndef test_alldebrid_retry_attempts_are_individually_rate_limited():\n    source = (Path(__file__).resolve().parents[1] / "services" / "alldebrid.py").read_text()\n    post = source.split("async def _post", 1)[1].split("async def _multipart", 1)[0]\n    loop_at = post.index("for attempt in range(1, attempts + 1):")\n    limiter_at = post.index("await acquire_alldebrid_request_slot()")\n    assert limiter_at > loop_at\n    assert post.count("await acquire_alldebrid_request_slot()") == 1\n\n\ndef test_dashboard_has_one_mixed_submission_control():\n    root = Path(__file__).resolve().parents[2]\n    html = (root / "frontend" / "static" / "index.html").read_text()\n    js = (root / "frontend" / "static" / "app.js").read_text()\n    assert html.count('id="q-transfer-input"') == 1\n    assert 'id="q-debrid-links"' not in html\n    assert 'id="q-magnet"' not in html\n    assert 'id="btn-add-transfer"' in html\n    assert 'https://example-hoster.com/file/' in html\n    assert 'magnet:?xt=urn:btih:' in html\n    assert 'addDashboardEntries()' in html\n    assert "function classifyDashboardEntries" in js\n    assert "openTorrentFilePicker();" in js\n    assert "'/links/add'" in js\n    assert "'/torrents/add-magnet'" in js\n    assert "async function quickAdd()" not in js\n    assert "async function addDebridLinks()" not in js\n\n\ndef test_dashboard_recent_activity_uses_viewport_slack():\n    js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.js").read_text()\n    assert "window.matchMedia('(max-width: 700px)').matches ? 4 : 6" in js\n    assert "`/torrents?limit=${recentLimit}`" in js\n\n\ndef test_dead_indexer_css_is_physically_removed():\n    css = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "style.css").read_text()\n    assert ".idx-picker" not in css\n    assert ".idx-dropdown" not in css\n    assert ".search-tags-row" not in css\n\n\ndef test_external_extractor_has_live_staging_budget_watch():\n    root = Path(__file__).resolve().parents[1] / "services"\n    safety = (root / "extraction_safety.py").read_text()\n    extractor = (root / "extractor.py").read_text()\n    assert "def validate_staging_tree" in safety\n    assert "watch_dir: Path | None" in extractor\n    assert "validate_staging_tree(watch_dir, watch_archive)" in extractor\n    assert extractor.count("watch_dir=dest, watch_archive=archive") == 2\n\n\ndef test_security_and_compose_document_current_boundaries():\n    root = Path(__file__).resolve().parents[2]\n    security = (root / "SECURITY.md").read_text()\n    compose = (root / "docker-compose.yml").read_text()\n    assert "if auth is added in future" not in security\n    assert "supports optional HTTP Basic Authentication" in security\n    assert "network_mode: host" not in compose\n    assert '"8080:8080"' in compose\n\n\ndef test_scheduler_exception_logging_is_sanitized():\n    source = (Path(__file__).resolve().parents[1] / "core" / "scheduler.py").read_text()\n    assert 'sanitize_exception' in source\n    assert 'error: {e}' not in source\n    assert 'error: %s", e)' not in source\n    assert 'error: %s", exc)' not in source\n'''
if "test_v106_transitional_and_mediainfo_residue_removed" in tests:
    raise RuntimeError("v1.0.6 cleanup contracts already present unexpectedly")
write(test_path, tests.rstrip() + extra + "\n")

# Final residue checks before the workflow runs tests.
all_python = "\n".join(
    p.read_text(errors="ignore")
    for p in (ROOT / "backend").rglob("*.py")
)
for forbidden in ("services.reconcile_cycle", "services.recovery", "services.mediainfo"):
    if forbidden in all_python:
        raise RuntimeError(f"remaining obsolete Python reference: {forbidden}")

print("v1.0.6 direct audit cleanup applied successfully")
