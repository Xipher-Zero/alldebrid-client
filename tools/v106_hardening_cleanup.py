from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Provider networking owns its rate limiter; manager_v2 no longer does.
# ---------------------------------------------------------------------------
replace_once("backend/services/manager_v2.py", "import time as _time\n", "")
replace_once("backend/services/manager_v2.py", "from collections import deque\n", "")
regex_once(
    "backend/services/manager_v2.py",
    r"\nclass _TokenBucketRateLimiter:.*?\n\nclass TransientAllDebridStateError",
    "\nclass TransientAllDebridStateError",
    flags=re.S,
)

replace_once(
    "backend/services/alldebrid.py",
    "from core.branding import APP_SHORT_NAME\n",
    "from core.branding import APP_SHORT_NAME\nfrom services.rate_limit import acquire_alldebrid_request_slot\n",
)
regex_once(
    "backend/services/alldebrid.py",
    r"        # Acquire a token from the rate limiter before every HTTP call\.\n        # This is a no-op when the limiter is configured as unlimited \(rate=1_000_000\)\.\n        try:\n            from services\.manager_v2 import _get_ad_rate_limiter\n            limiter = await _get_ad_rate_limiter\(\)\n            await limiter\.acquire\(\)\n        except ImportError:\n            pass  # tests or standalone use — skip rate limiting\n",
    "        await acquire_alldebrid_request_slot()\n",
)
replace_once(
    "backend/services/alldebrid.py",
    "    async def _multipart(self, endpoint: str, form: aiohttp.FormData) -> Dict[str, Any]:\n        url = f\"{API_V4}/{endpoint}\"\n",
    "    async def _multipart(self, endpoint: str, form: aiohttp.FormData) -> Dict[str, Any]:\n"
    "        await acquire_alldebrid_request_slot()\n"
    "        url = f\"{API_V4}/{endpoint}\"\n",
)

# ---------------------------------------------------------------------------
# Archive safety: preflight native formats, bound streams, stage external tools.
# ---------------------------------------------------------------------------
replace_once(
    "backend/services/extractor.py",
    "from typing import Iterable, List, Optional, Tuple\n\nlogger = logging.getLogger(\"alldebrid.extractor\")\n",
    "from typing import Iterable, List, Optional, Tuple\n\n"
    "from services.extraction_safety import (\n"
    "    copy_limited,\n"
    "    staged_external_extract,\n"
    "    validate_7z_listing,\n"
    "    validate_tar_members,\n"
    "    validate_zip_members,\n"
    ")\n\n"
    "logger = logging.getLogger(\"alldebrid.extractor\")\n",
)
replace_once(
    "backend/services/extractor.py",
    "    with zipfile.ZipFile(archive, \"r\") as zf:\n        for member in zf.infolist():\n",
    "    with zipfile.ZipFile(archive, \"r\") as zf:\n"
    "        members = zf.infolist()\n"
    "        validate_zip_members(archive, members)\n"
    "        for member in members:\n",
)
replace_once(
    "backend/services/extractor.py",
    "def _extract_tar(archive: Path, dest: Path) -> None:\n    with tarfile.open(archive, \"r:*\") as tf:\n        tf.extractall(dest, filter=\"data\")\n",
    "def _extract_tar(archive: Path, dest: Path) -> None:\n"
    "    with tarfile.open(archive, \"r:*\") as tf:\n"
    "        members = tf.getmembers()\n"
    "        validate_tar_members(archive, members)\n"
    "        tf.extractall(dest, members=members, filter=\"data\")\n",
)
replace_once(
    "backend/services/extractor.py",
    "    with gzip.open(archive, \"rb\") as gz_in, open(out_path, \"wb\") as f_out:\n        shutil.copyfileobj(gz_in, f_out)\n",
    "    try:\n"
    "        with gzip.open(archive, \"rb\") as gz_in, open(out_path, \"wb\") as f_out:\n"
    "            copy_limited(gz_in, f_out, archive=archive)\n"
    "    except Exception:\n"
    "        out_path.unlink(missing_ok=True)\n"
    "        raise\n",
)
replace_once(
    "backend/services/extractor.py",
    "    with bz2.open(archive, \"rb\") as bz_in, open(out_path, \"wb\") as f_out:\n        shutil.copyfileobj(bz_in, f_out)\n",
    "    try:\n"
    "        with bz2.open(archive, \"rb\") as bz_in, open(out_path, \"wb\") as f_out:\n"
    "            copy_limited(bz_in, f_out, archive=archive)\n"
    "    except Exception:\n"
    "        out_path.unlink(missing_ok=True)\n"
    "        raise\n",
)
replace_once(
    "backend/services/extractor.py",
    "    with lzma.open(archive, \"rb\") as xz_in, open(out_path, \"wb\") as f_out:\n        shutil.copyfileobj(xz_in, f_out)\n",
    "    try:\n"
    "        with lzma.open(archive, \"rb\") as xz_in, open(out_path, \"wb\") as f_out:\n"
    "            copy_limited(xz_in, f_out, archive=archive)\n"
    "    except Exception:\n"
    "        out_path.unlink(missing_ok=True)\n"
    "        raise\n",
)

old_7z = '''def _extract_7z(archive: Path, dest: Path) -> None:\n    """Use system `7z` binary (p7zip-full). Tries each configured password in order."""\n    passwords = _get_extraction_passwords()\n    # Always try without password first, then each configured password\n    candidates = [""] + passwords if passwords else [""]\n    for binary in ("7z", "7za", "7zz"):\n        if not _tool_available(binary):\n            continue\n        for pw in candidates:\n            cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n            if pw:\n                cmd.insert(-1, f"-p{pw}")\n            rc, out = _run_tool(cmd)\n            if rc == 0:\n                return\n        raise RuntimeError(f"{binary} failed to extract {archive.name}")\n    raise RuntimeError("No 7z binary found (install p7zip-full in the container)")\n'''
new_7z = '''def _preflight_7z(archive: Path, binary: str, candidates: list[str]) -> None:\n    last_output = ""\n    for pw in candidates:\n        cmd = [binary, "l", "-slt"]\n        if pw:\n            cmd.append(f"-p{pw}")\n        cmd.append(str(archive))\n        rc, output = _run_tool(cmd, timeout=300)\n        last_output = output\n        if rc == 0:\n            validate_7z_listing(archive, output)\n            return\n    raise RuntimeError(\n        f"{binary} could not safely inspect {archive.name}: {last_output[-160:]}"\n    )\n\n\ndef _extract_7z_to(archive: Path, dest: Path) -> None:\n    """Use system 7z inside an already-isolated staging directory."""\n    passwords = _get_extraction_passwords()\n    candidates = [""] + passwords if passwords else [""]\n    for binary in ("7z", "7za", "7zz"):\n        if not _tool_available(binary):\n            continue\n        _preflight_7z(archive, binary, candidates)\n        for pw in candidates:\n            cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n            if pw:\n                cmd.insert(-1, f"-p{pw}")\n            rc, _out = _run_tool(cmd)\n            if rc == 0:\n                return\n        raise RuntimeError(f"{binary} failed to extract {archive.name}")\n    raise RuntimeError("No 7z binary found (install p7zip-full in the container)")\n\n\ndef _extract_7z(archive: Path, dest: Path) -> None:\n    staged_external_extract(\n        archive, dest, lambda stage: _extract_7z_to(archive, stage)\n    )\n'''
replace_once("backend/services/extractor.py", old_7z, new_7z)

old_rar = '''def _extract_rar(archive: Path, dest: Path) -> None:\n    """Extract RAR archives using 7z (primary) or unrar-free/unrar (fallback).\n\n    7z from p7zip-full handles both RAR3 and RAR5 and is always present in\n    the Docker image.  Tries each configured password in order.\n    """\n    passwords = _get_extraction_passwords()\n    candidates = [""] + passwords if passwords else [""]\n\n    # Primary: 7z handles RAR3 and RAR5\n    for binary in ("7z", "7za", "7zz"):\n        if _tool_available(binary):\n            for pw in candidates:\n                cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n                if pw:\n                    cmd.insert(-1, f"-p{pw}")\n                rc, out = _run_tool(cmd)\n                if rc == 0:\n                    return\n            # 7z present but all passwords failed — try unrar tools\n            break\n\n    # Fallback: unrar (non-free, 'x' subcommand)\n    if _tool_available("unrar"):\n        for pw in candidates:\n            cmd = ["unrar", "x", "-y", str(archive), str(dest) + "/"]\n            if pw:\n                cmd.insert(2, f"-p{pw}")\n            rc, out = _run_tool(cmd)\n            if rc == 0:\n                return\n\n    # Last resort: unrar-free (LGPL, uses '-x' flag — different from non-free unrar)\n    if _tool_available("unrar-free"):\n        rc, out = _run_tool(["unrar-free", "-x", str(archive), str(dest) + "/"])\n        if rc == 0:\n            return\n\n    raise RuntimeError("No RAR extraction tool available (p7zip-full or unrar-free required)")\n'''
new_rar = '''def _extract_rar_to(archive: Path, dest: Path) -> None:\n    """Extract RAR into an isolated staging directory."""\n    passwords = _get_extraction_passwords()\n    candidates = [""] + passwords if passwords else [""]\n\n    for binary in ("7z", "7za", "7zz"):\n        if _tool_available(binary):\n            _preflight_7z(archive, binary, candidates)\n            for pw in candidates:\n                cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n                if pw:\n                    cmd.insert(-1, f"-p{pw}")\n                rc, _out = _run_tool(cmd)\n                if rc == 0:\n                    return\n            break\n\n    if _tool_available("unrar"):\n        for pw in candidates:\n            cmd = ["unrar", "x", "-y", str(archive), str(dest) + "/"]\n            if pw:\n                cmd.insert(2, f"-p{pw}")\n            rc, _out = _run_tool(cmd)\n            if rc == 0:\n                return\n\n    if _tool_available("unrar-free"):\n        rc, _out = _run_tool(["unrar-free", "-x", str(archive), str(dest) + "/"])\n        if rc == 0:\n            return\n\n    raise RuntimeError("No RAR extraction tool available (p7zip-full or unrar-free required)")\n\n\ndef _extract_rar(archive: Path, dest: Path) -> None:\n    staged_external_extract(\n        archive, dest, lambda stage: _extract_rar_to(archive, stage)\n    )\n'''
replace_once("backend/services/extractor.py", old_rar, new_rar)

replace_once(
    "backend/services/extraction_safety.py",
    "    text = str(output or \"\")\n",
    "    text = str(output or \"\").replace(\"\\r\\n\", \"\\n\")\n",
)

# ---------------------------------------------------------------------------
# Remove the hidden runtime-DB presentation card instead of hiding it with CSS.
# ---------------------------------------------------------------------------
replace_once(
    "frontend/static/index.html",
    "<style>\n#tab-database > .scard:first-child { display: none; }\n</style>\n",
    "",
)
replace_once(
    "frontend/static/app.js",
    '''      <div class="scard">\n      <div class="scard-header">🗄️ Database</div>\n      <div class="scard-body">\n        <div class="form-group">\n          <label class="form-label">Runtime Database</label>\n          <input class="input" value="SQLite (internal, WAL)" disabled/>\n          <span class="form-hint">SQLite is the authoritative and only runtime database in DebridPulse 1.0.5.</span>\n        </div>\n      </div>\n    </div>\n\n''',
    "",
)

# ---------------------------------------------------------------------------
# Fix stale regressions and move rate-limit tests to their real owner.
# ---------------------------------------------------------------------------
path = "backend/tests/test_v105_audit_regressions.py"
text = read(path)
old = '''    seen = []\n\n    async def one_cycle(service):\n        seen.append(service)\n        raise asyncio.CancelledError\n\n    monkeypatch.setattr(scheduler, "reconcile_download_client_cycle", one_cycle)\n    with pytest.raises(asyncio.CancelledError):\n        await scheduler.sync_download_clients_loop()\n    assert seen == [scheduler.transfer_service]\n'''
new = '''    seen = []\n\n    async def one_cycle():\n        seen.append(scheduler.transfer_service)\n        raise asyncio.CancelledError\n\n    monkeypatch.setattr(scheduler.transfer_service.reconciliation, "reconcile", one_cycle)\n    with pytest.raises(asyncio.CancelledError):\n        await scheduler.sync_download_clients_loop()\n    assert seen == [scheduler.transfer_service]\n'''
if text.count(old) != 1:
    raise RuntimeError("stale scheduler regression block not found exactly once")
write(path, text.replace(old, new, 1))

path = "backend/tests/test_settings_semantics.py"
text = read(path)
text = text.replace("from services import manager_v2\n", "import services.rate_limit as rate_limit\n")
text = text.replace(
    "        manager_v2._ad_rate_limiter = manager_v2._TokenBucketRateLimiter(rate=60, window=60.0)\n",
    "        rate_limit._alldebrid_rate_limiter = rate_limit.TokenBucketRateLimiter(rate=60, window=60.0)\n",
)
text = text.replace(
    '        with patch("services.manager_v2.get_settings", return_value=cfg):\n            limiter = await manager_v2._get_ad_rate_limiter()\n',
    '        with patch("services.rate_limit.get_settings", return_value=cfg):\n            limiter = await rate_limit.get_alldebrid_rate_limiter()\n',
)
if "manager_v2._get_ad_rate_limiter" in text or "services.manager_v2.get_settings" in text:
    raise RuntimeError("rate limit tests still depend on manager_v2")
write(path, text)

replace_once(
    "backend/tests/test_v105_database_ui.py",
    '''    assert "#tab-database > .scard:first-child { display: none; }" in index_html\n    assert "Runtime Database" in app_js\n    assert "Database Maintenance" in app_js\n''',
    '''    assert "#tab-database > .scard:first-child { display: none; }" not in index_html\n    assert "Runtime Database" not in app_js\n    assert "Database Maintenance" in app_js\n''',
)

# The existing SQLite-only frontend contract should assert the actual remaining UI.
replace_once(
    "backend/tests/test_settings_semantics.py",
    '        self.assertIn("SQLite (internal, WAL)", js)\n',
    '        self.assertNotIn("Runtime Database", js)\n        self.assertIn("Database Maintenance", js)\n',
)

# Extraction security regressions use low limits without allocating large fixtures.
with (ROOT / "backend/tests/test_v106_audit_contracts.py").open("a", encoding="utf-8") as f:
    f.write('''\n\ndef test_zip_preflight_rejects_file_count_budget(tmp_path, monkeypatch):\n    import zipfile\n    import services.extraction_safety as safety\n    from services.extractor import _extract_zip\n\n    archive = tmp_path / "many.zip"\n    with zipfile.ZipFile(archive, "w") as zf:\n        zf.writestr("one.txt", b"1")\n        zf.writestr("two.txt", b"2")\n    monkeypatch.setattr(\n        safety, "get_settings",\n        lambda: SimpleNamespace(\n            extract_max_files=1,\n            extract_max_expanded_gb=1,\n            extract_max_compression_ratio=1000,\n        ),\n    )\n    dest = tmp_path / "out"\n    dest.mkdir()\n    with pytest.raises(ValueError, match="files"):\n        _extract_zip(archive, dest)\n    assert list(dest.iterdir()) == []\n\n\ndef test_external_staging_rejects_symlink_output(tmp_path, monkeypatch):\n    import services.extraction_safety as safety\n\n    archive = tmp_path / "archive.7z"\n    archive.write_bytes(b"archive")\n    dest = tmp_path / "dest"\n    dest.mkdir()\n    monkeypatch.setattr(\n        safety, "get_settings",\n        lambda: SimpleNamespace(\n            extract_max_files=100,\n            extract_max_expanded_gb=1,\n            extract_max_compression_ratio=1000,\n        ),\n    )\n\n    def malicious(stage):\n        (stage / "escape").symlink_to(tmp_path / "outside")\n\n    with pytest.raises(ValueError, match="symlink"):\n        safety.staged_external_extract(archive, dest, malicious)\n    assert list(dest.iterdir()) == []\n\n\ndef test_7z_listing_budget_is_validated_before_extraction(tmp_path, monkeypatch):\n    import services.extraction_safety as safety\n\n    archive = tmp_path / "archive.7z"\n    archive.write_bytes(b"x" * 100)\n    monkeypatch.setattr(\n        safety, "get_settings",\n        lambda: SimpleNamespace(\n            extract_max_files=1,\n            extract_max_expanded_gb=1,\n            extract_max_compression_ratio=1000,\n        ),\n    )\n    listing = "Header\\n----------\\nPath = one\\nSize = 1\\nAttributes = A\\n\\nPath = two\\nSize = 1\\nAttributes = A\\n"\n    with pytest.raises(ValueError, match="files"):\n        safety.validate_7z_listing(archive, listing)\n\n\ndef test_alldebrid_client_rate_limits_multipart_uploads():\n    source = (Path(__file__).resolve().parents[1] / "services" / "alldebrid.py").read_text()\n    multipart = source.split("async def _multipart", 1)[1].split("# ── User", 1)[0]\n    assert "await acquire_alldebrid_request_slot()" in multipart\n    assert "services.manager_v2" not in source\n''')

print("v1.0.6 hardening cleanup patch applied")
