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
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one regex match, found {count}: {pattern[:100]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Transfer service: destructive actions must quiesce the daemon first.
# ---------------------------------------------------------------------------
replace_once(
    "backend/services/transfer_service.py",
    "    def reset_services(self):\n        self.control.reset_runtime_state()\n        return self._engine.reset_services()\n",
    "    async def quiesce_for_database_wipe(self):\n"
    "        \"\"\"Physically park owned aria2 work before destructive DB maintenance.\"\"\"\n"
    "        pause_result = await self.pause_all_downloads()\n"
    "        failed = int((pause_result or {}).get(\"failed\") or 0)\n"
    "        if failed:\n"
    "            raise RuntimeError(f\"Could not confirm pause for {failed} transfer(s)\")\n"
    "        # Prove the daemon is reachable before trusting an observational snapshot.\n"
    "        await self.aria2.test()\n"
    "        owned = await self.aria2.get_owned()\n"
    "        live = [item for item in owned if item.status in {\"active\", \"waiting\"}]\n"
    "        if live:\n"
    "            raise RuntimeError(\n"
    "                f\"Database wipe refused: {len(live)} owned aria2 job(s) are still live\"\n"
    "            )\n"
    "        return {\"pause\": pause_result, \"owned_checked\": len(owned)}\n\n"
    "    def reset_services(self):\n"
    "        self.control.reset_runtime_state()\n"
    "        return self._engine.reset_services()\n",
)

replace_once(
    "backend/services/db_maintenance.py",
    "async def wipe_database() -> dict:\n    async with get_db() as db:\n",
    "async def wipe_database(*, verified_quiesced: bool = False) -> dict:\n"
    "    if not verified_quiesced:\n"
    "        raise RuntimeError(\"Database wipe requires verified quiesced transfer state\")\n"
    "    async with get_db() as db:\n",
)

# ---------------------------------------------------------------------------
# API: explicit public serializers, event binding, and destructive guarantees.
# ---------------------------------------------------------------------------
replace_once(
    "backend/api/routes.py",
    "from services.transfer_service import transfer_service\nfrom services.aria2_runtime import runtime as aria2_runtime\nfrom services.aria2 import aria2_download_to_dict\n",
    "from services.transfer_service import transfer_service\n"
    "from services.aria2_runtime import runtime as aria2_runtime\n"
    "from services.event_bus import bind_publisher\n"
    "from api.serializers import (\n"
    "    public_aria2_download,\n"
    "    public_download_file,\n"
    "    public_payload,\n"
    "    public_torrent,\n"
    ")\n",
)

replace_once(
    "backend/api/routes.py",
    "            diagnostics = await transfer_service._aria2_get_memory_diagnostics()\n",
    "            diagnostics = await transfer_service.aria2.memory_diagnostics()\n",
)

replace_once(
    "backend/api/routes.py",
    "    items = [aria2_download_to_dict(download) for download in downloads]\n",
    "    items = [public_aria2_download(download) for download in downloads]\n",
)

replace_once(
    "backend/api/routes.py",
    "        return {\"items\": rows, \"total\": total}\n",
    "        return {\"items\": [public_torrent(row) for row in rows], \"total\": total}\n",
)

replace_once(
    "backend/api/routes.py",
    "        row = await transfer_service.add_magnet_direct(magnet, source=\"manual\")\n        return row\n",
    "        row = await transfer_service.add_magnet_direct(magnet, source=\"manual\")\n"
    "        return public_payload(row)\n",
)

replace_once(
    "backend/api/routes.py",
    "        return await transfer_service.add_torrent_file_direct(\n            data,\n            filename,\n            source=\"manual_file\",\n        )\n",
    "        result = await transfer_service.add_torrent_file_direct(\n"
    "            data,\n"
    "            filename,\n"
    "            source=\"manual_file\",\n"
    "        )\n"
    "        return public_payload(result)\n",
)

replace_once(
    "backend/api/routes.py",
    "        return await transfer_service.add_direct_links(links)\n",
    "        return public_payload(await transfer_service.add_direct_links(links))\n",
)

replace_once(
    "backend/api/routes.py",
    "    results = await transfer_service.import_existing_magnets()\n    return {\"imported\": len(results), \"items\": results}\n",
    "    results = await transfer_service.import_existing_magnets()\n"
    "    return {\"imported\": len(results), \"items\": public_payload(results)}\n",
)

replace_once(
    "backend/api/routes.py",
    "        files_data = await transfer_service.ad().get_magnet_files([str(row[\"alldebrid_id\"])])\n",
    "        files_data = await transfer_service.provider.client().get_magnet_files([str(row[\"alldebrid_id\"])])\n",
)

replace_once(
    "backend/api/routes.py",
    "                        {\n                            \"link\":     f.get(\"link\", \"\"),\n                            \"filename\": f.get(\"filename\") or f.get(\"name\") or f.get(\"link\", \"\"),\n                            \"size_bytes\": int(f.get(\"size\") or 0),\n                        }\n",
    "                        {\n"
    "                            \"filename\": f.get(\"path\") or f.get(\"name\") or \"download\",\n"
    "                            \"size_bytes\": int(f.get(\"size\") or 0),\n"
    "                        }\n",
)

replace_once(
    "backend/api/routes.py",
    "        return {**dict(row), \"files\": [dict(f) for f in files], \"events\": [dict(e) for e in events]}\n",
    "        return {\n"
    "            **public_torrent(row),\n"
    "            \"files\": [public_download_file(file_row) for file_row in files],\n"
    "            \"events\": [dict(event) for event in events],\n"
    "        }\n",
)

replace_once(
    "backend/api/routes.py",
    "    backup_result = None\n    if getattr(cfg, \"db_backup_before_wipe\", True):\n        from services.db_maintenance import run_database_backup\n        backup_result = await run_database_backup()\n\n    from services.db_maintenance import wipe_database\n    result = await wipe_database()\n    transfer_service.reset_services()\n    return {**result, \"backup\": backup_result}\n",
    "    try:\n"
    "        quiesce_result = await transfer_service.quiesce_for_database_wipe()\n"
    "    except Exception as exc:\n"
    "        raise HTTPException(409, _sanitize_error(exc))\n\n"
    "    backup_result = None\n"
    "    if getattr(cfg, \"db_backup_before_wipe\", True):\n"
    "        from services.db_maintenance import run_database_backup\n"
    "        backup_result = await run_database_backup()\n"
    "        if backup_result.get(\"skipped\"):\n"
    "            raise HTTPException(409, \"Pre-wipe database backup is required but disabled\")\n"
    "        if backup_result.get(\"errors\"):\n"
    "            raise HTTPException(500, \"Pre-wipe database backup failed; wipe aborted\")\n\n"
    "    from services.db_maintenance import wipe_database\n"
    "    result = await wipe_database(verified_quiesced=True)\n"
    "    return {**result, \"backup\": backup_result, \"quiesced\": quiesce_result}\n",
)

replace_once(
    "backend/api/routes.py",
    "async def _sse_broadcast(event_type: str, data: dict) -> None:\n    \"\"\"Push an SSE event to all connected clients (fire-and-forget).\"\"\"\n    payload = f\"event: {event_type}\\ndata: {_json.dumps(data)}\\n\\n\"\n    dead: list[asyncio.Queue] = []\n    async with _sse_lock:\n        for q in _sse_subscribers:\n            try:\n                q.put_nowait(payload)\n            except asyncio.QueueFull:\n                dead.append(q)\n        for q in dead:\n            _sse_subscribers.discard(q)\n\n\nasync def _sse_generator",
    "async def _sse_broadcast(event_type: str, data: dict) -> None:\n"
    "    \"\"\"Push an SSE event to all connected clients (fire-and-forget).\"\"\"\n"
    "    payload = f\"event: {event_type}\\ndata: {_json.dumps(data)}\\n\\n\"\n"
    "    dead: list[asyncio.Queue] = []\n"
    "    async with _sse_lock:\n"
    "        for q in _sse_subscribers:\n"
    "            try:\n"
    "                q.put_nowait(payload)\n"
    "            except asyncio.QueueFull:\n"
    "                dead.append(q)\n"
    "        for q in dead:\n"
    "            _sse_subscribers.discard(q)\n\n\n"
    "bind_publisher(_sse_broadcast)\n\n\n"
    "async def _sse_generator",
)

regex_once(
    "backend/api/routes.py",
    r"@router\.get\(\"/mediainfo\"\)\nasync def get_mediainfo_endpoint\(path: str = Query\(\.\.\., description=\"Local file path\"\)\):.*?\n# ── AllDebrid orphan cleanup",
    "@router.get(\"/mediainfo\")\n"
    "async def get_mediainfo_endpoint(path: str = Query(..., description=\"Local file path\")):\n"
    "    \"\"\"Return technical metadata for a file inside the configured download root.\"\"\"\n"
    "    from services.mediainfo import get_mediainfo\n"
    "    try:\n"
    "        return await get_mediainfo(path)\n"
    "    except PermissionError as exc:\n"
    "        raise HTTPException(403, _sanitize_error(exc))\n"
    "    except FileNotFoundError:\n"
    "        raise HTTPException(404, \"File not found\")\n\n"
    "# ── AllDebrid orphan cleanup",
    flags=re.S,
)

# ---------------------------------------------------------------------------
# Main process: bounded request bodies, explicit service calls, safer headers.
# ---------------------------------------------------------------------------
replace_once(
    "backend/main.py",
    "from fastapi.middleware.cors import CORSMiddleware\n",
    "from fastapi.middleware.cors import CORSMiddleware\nfrom starlette.types import ASGIApp, Message, Receive, Scope, Send\n",
)

replace_once(
    "backend/main.py",
    "                asyncio.create_task(transfer_service._start_download(\n                    row[\"id\"], str(row[\"alldebrid_id\"]), str(row[\"name\"] or \"\")\n                ))\n",
    "                asyncio.create_task(transfer_service.control.start_download(\n"
    "                    row[\"id\"], str(row[\"alldebrid_id\"]), str(row[\"name\"] or \"\")\n"
    "                ))\n",
)

replace_once(
    "backend/main.py",
    "        await transfer_service.run_aria2_housekeeping()\n",
    "        await transfer_service.aria2.housekeeping()\n",
)

replace_once(
    "backend/main.py",
    "    try:\n        from core.config import get_settings, apply_settings, save_settings\n",
    "    if not (str(getattr(cfg, \"auth_username\", \"\") or \"\").strip() and str(getattr(cfg, \"auth_password\", \"\") or \"\").strip()):\n"
    "        logger.warning(\"HTTP authentication is disabled; restrict DebridPulse to a trusted network or authenticated reverse proxy\")\n\n"
    "    try:\n"
    "        from core.config import get_settings, apply_settings, save_settings\n",
)

replace_once(
    "backend/main.py",
    "app = FastAPI(\n",
    "class _RequestBodyTooLarge(Exception):\n"
    "    pass\n\n\n"
    "class RequestBodyLimitMiddleware:\n"
    "    def __init__(self, app: ASGIApp, max_bytes: int):\n"
    "        self.app = app\n"
    "        self.max_bytes = max(1, int(max_bytes))\n\n"
    "    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:\n"
    "        if scope.get(\"type\") != \"http\" or str(scope.get(\"method\") or \"\").upper() not in {\"POST\", \"PUT\", \"PATCH\", \"DELETE\"}:\n"
    "            await self.app(scope, receive, send)\n"
    "            return\n"
    "        headers = {key.lower(): value for key, value in scope.get(\"headers\", [])}\n"
    "        raw_length = headers.get(b\"content-length\", b\"\")\n"
    "        try:\n"
    "            if raw_length and int(raw_length) > self.max_bytes:\n"
    "                response = Response(content=\"Request body too large\", status_code=413)\n"
    "                await response(scope, receive, send)\n"
    "                return\n"
    "        except ValueError:\n"
    "            pass\n"
    "        seen = 0\n"
    "        async def limited_receive() -> Message:\n"
    "            nonlocal seen\n"
    "            message = await receive()\n"
    "            if message.get(\"type\") == \"http.request\":\n"
    "                seen += len(message.get(\"body\", b\"\"))\n"
    "                if seen > self.max_bytes:\n"
    "                    raise _RequestBodyTooLarge\n"
    "            return message\n"
    "        try:\n"
    "            await self.app(scope, limited_receive, send)\n"
    "        except _RequestBodyTooLarge:\n"
    "            response = Response(content=\"Request body too large\", status_code=413)\n"
    "            await response(scope, receive, send)\n\n\n"
    "try:\n"
    "    _MAX_REQUEST_BODY_BYTES = max(1024 * 1024, min(100 * 1024 * 1024, int(os.getenv(\"DEBRIDPULSE_MAX_REQUEST_BYTES\", str(20 * 1024 * 1024)))))\n"
    "except ValueError:\n"
    "    _MAX_REQUEST_BODY_BYTES = 20 * 1024 * 1024\n\n\n"
    "app = FastAPI(\n",
)

replace_once(
    "backend/main.py",
    "@app.exception_handler(PermissionError)\nasync def permission_error_handler(_request: Request, _exc: PermissionError):\n    \"\"\"Do not turn service-layer authorization failures into HTTP 500 responses.\"\"\"\n    return Response(content=\"Forbidden\", status_code=403)\n\n\n_cors_origins",
    "@app.exception_handler(PermissionError)\n"
    "async def permission_error_handler(_request: Request, _exc: PermissionError):\n"
    "    \"\"\"Do not turn service-layer authorization failures into HTTP 500 responses.\"\"\"\n"
    "    return Response(content=\"Forbidden\", status_code=403)\n\n\n"
    "app.add_middleware(RequestBodyLimitMiddleware, max_bytes=_MAX_REQUEST_BODY_BYTES)\n\n\n"
    "_cors_origins",
)

replace_once(
    "backend/main.py",
    "    req_id = request.headers.get(\"X-Request-ID\") or str(uuid.uuid4())\n    response = await call_next(request)\n    response.headers[\"X-Request-ID\"] = req_id\n    return response\n",
    "    req_id = str(request.headers.get(\"X-Request-ID\") or \"\").strip()\n"
    "    if not req_id or len(req_id) > 128:\n"
    "        req_id = str(uuid.uuid4())\n"
    "    response = await call_next(request)\n"
    "    response.headers[\"X-Request-ID\"] = req_id\n"
    "    response.headers.setdefault(\"X-Content-Type-Options\", \"nosniff\")\n"
    "    response.headers.setdefault(\"Referrer-Policy\", \"no-referrer\")\n"
    "    response.headers.setdefault(\"X-Frame-Options\", \"DENY\")\n"
    "    return response\n",
)

# ---------------------------------------------------------------------------
# Configuration and scheduler contracts.
# ---------------------------------------------------------------------------
replace_once(
    "backend/core/config.py",
    "    aria2_poll_interval_seconds: int = 1  # fast polling for responsive dispatch\n",
    "    aria2_poll_interval_seconds: int = 2  # validated scheduler cadence\n",
)
replace_once(
    "backend/core/config.py",
    "    extract_max_concurrent: int = 1        # max parallel extractions\n",
    "    extract_max_concurrent: int = 1        # max parallel extractions\n"
    "    extract_max_files: int = 20000          # archive member ceiling\n"
    "    extract_max_expanded_gb: float = 250.0  # expanded bytes per archive\n"
    "    extract_max_compression_ratio: float = 1000.0  # expanded/archive size\n",
)

replace_once(
    "backend/core/config_validator.py",
    '        "aria2_poll_interval_seconds":    (1, 300),\n',
    '        "aria2_poll_interval_seconds":    (2, 300),\n',
)
replace_once(
    "backend/core/config_validator.py",
    '        "full_sync_interval_minutes":     (1, 1440),\n',
    '        "full_sync_interval_minutes":     (0, 1440),\n',
)
replace_once(
    "backend/core/config_validator.py",
    '        "min_file_size_mb":               (0, 100_000),\n',
    '        "min_file_size_mb":               (0, 100_000),\n'
    '        "extract_max_files":              (1, 1_000_000),\n'
    '        "extract_max_expanded_gb":        (1, 10_000),\n'
    '        "extract_max_compression_ratio":  (1, 100_000),\n',
)
replace_once(
    "backend/core/config_validator.py",
    "        elif lo > 0 and val < lo:\n",
    "        elif val < lo:\n",
)

replace_once(
    "backend/core/scheduler.py",
    "from services.reconcile_cycle import reconcile_download_client_cycle\n",
    "",
)
replace_once(
    "backend/core/scheduler.py",
    "                await reconcile_download_client_cycle(transfer_service)\n",
    "                await transfer_service.reconciliation.reconcile()\n",
)
regex_once(
    "backend/core/scheduler.py",
    r"\nasync def recovery_loop\(\):.*?\n\nasync def disk_guard_loop\(\):",
    "\n\nasync def disk_guard_loop():",
    flags=re.S,
)
replace_once(
    "backend/core/scheduler.py",
    "    _tasks.append(asyncio.create_task(recovery_loop()))\n",
    "",
)
replace_once(
    "backend/core/scheduler.py",
    "async def start_scheduler():\n    _tasks.append(asyncio.create_task(sync_status_loop()))\n",
    "async def start_scheduler():\n"
    "    if any(not task.done() for task in _tasks):\n"
    "        logger.debug(\"Scheduler already running\")\n"
    "        return\n"
    "    _tasks.clear()\n"
    "    _tasks.append(asyncio.create_task(sync_status_loop()))\n",
)
replace_once(
    "backend/core/scheduler.py",
    "async def stop_scheduler():\n    for t in _tasks:\n        t.cancel()\n    _tasks.clear()\n",
    "async def stop_scheduler():\n"
    "    tasks = list(_tasks)\n"
    "    _tasks.clear()\n"
    "    for task in tasks:\n"
    "        task.cancel()\n"
    "    if tasks:\n"
    "        await asyncio.gather(*tasks, return_exceptions=True)\n",
)
replace_once(
    "backend/core/scheduler.py",
    "    all pending files from the DB within one poll cycle (≤1 second).\n",
    "    all pending files from the DB within one poll cycle (normally ≤2 seconds).\n",
)

# ---------------------------------------------------------------------------
# Container ownership: never recursively mutate a shared download tree by default.
# ---------------------------------------------------------------------------
replace_once(
    "entrypoint.sh",
    "# When PUID/PGID are omitted the app runs as the 'appuser' created in the\n# Dockerfile (UID 1000 / GID 1000) — still non-root.\n# To run as root deliberately set PUID=0.\n",
    "# When PUID/PGID are omitted DebridPulse uses the image defaults (99:100).\n"
    "# To run as root deliberately set PUID=0.\n",
)
replace_once(
    "entrypoint.sh",
    "for DIR in /app/data /app/config /download; do\n    if [ -d \"${DIR}\" ]; then\n        chown -R \"${PUID}:${PGID}\" \"${DIR}\" 2>/dev/null || true\n    fi\ndone\n",
    "for DIR in /app/data /app/config; do\n"
    "    if [ -d \"${DIR}\" ]; then\n"
    "        chown -R \"${PUID}:${PGID}\" \"${DIR}\" 2>/dev/null || true\n"
    "    fi\n"
    "done\n"
    "if [ -d /download ]; then\n"
    "    if [ \"${CHOWN_DOWNLOADS_RECURSIVE:-false}\" = \"true\" ]; then\n"
    "        chown -R \"${PUID}:${PGID}\" /download 2>/dev/null || true\n"
    "    else\n"
    "        chown \"${PUID}:${PGID}\" /download 2>/dev/null || true\n"
    "    fi\n"
    "fi\n",
)

# ---------------------------------------------------------------------------
# Existing regressions updated for the stronger gateway/wipe contracts.
# ---------------------------------------------------------------------------
path = "backend/tests/test_v105_audit_regressions.py"
text = read(path)
text = text.replace(
    "    gateway = gateway_module.Aria2Gateway(engine)\n",
    "    ownership = SimpleNamespace(owns=AsyncMock(return_value=True), filter_owned=AsyncMock())\n"
    "    gateway = gateway_module.Aria2Gateway(engine, ownership)\n",
)
if text.count("Aria2Gateway(engine, ownership)") != 2:
    raise RuntimeError("expected two Aria2Gateway test constructor updates")
text = text.replace(
    "    result = await maintenance.wipe_database()\n",
    "    result = await maintenance.wipe_database(verified_quiesced=True)\n",
    1,
)
write(path, text)

# New contracts specific to the 1.0.6 cleanup.
write(
    "backend/tests/test_v106_audit_contracts.py",
    '''import asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\nfrom unittest.mock import AsyncMock\n\nimport pytest\n\n\ndef test_transfer_service_has_no_transparent_legacy_fallback():\n    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_service.py").read_text()\n    assert "def __getattr__" not in source\n    assert "return getattr(self._engine" not in source\n\n\ndef test_state_machine_does_not_import_http_layer():\n    source = (Path(__file__).resolve().parents[1] / "services" / "transfer_state_machine.py").read_text()\n    assert "from api.routes" not in source\n    assert "from services.event_bus import publish" in source\n\n\n@pytest.mark.asyncio\nasync def test_external_gateway_rejects_foreign_gid(monkeypatch):\n    import services.aria2_gateway as gateway_module\n\n    monkeypatch.setattr(gateway_module, "is_builtin_mode", lambda: False)\n    aria2 = SimpleNamespace(pause=AsyncMock(), resume=AsyncMock())\n    engine = SimpleNamespace(aria2=lambda: aria2)\n    ownership = SimpleNamespace(owns=AsyncMock(return_value=False))\n    gateway = gateway_module.Aria2Gateway(engine, ownership)\n\n    with pytest.raises(PermissionError):\n        await gateway.pause("foreign")\n    with pytest.raises(PermissionError):\n        await gateway.resume("foreign")\n    aria2.pause.assert_not_awaited()\n    aria2.resume.assert_not_awaited()\n\n\ndef test_public_serializers_strip_capability_urls():\n    from api.serializers import public_download_file, public_payload, public_torrent\n\n    torrent = public_torrent({"id": 1, "magnet": "magnet:?xt=secret", "download_url": "https://token", "name": "x"})\n    assert torrent == {"id": 1, "name": "x"}\n    file_row = public_download_file({"id": 2, "source_url": "https://source", "download_url": "https://unlocked", "filename": "x.mkv"})\n    assert file_row == {"id": 2, "filename": "x.mkv"}\n    nested = public_payload({"items": [{"magnet": "secret", "source_url": "secret", "id": 3}]})\n    assert nested == {"items": [{"id": 3}]}\n\n\ndef test_backup_rotation_requires_ownership_manifest(tmp_path):\n    from services import backup\n\n    unrelated = tmp_path / "20000101_000000"\n    unrelated.mkdir()\n    (unrelated / "keep.txt").write_text("keep")\n    assert backup._rotate_backups(tmp_path, 1) == 0\n    assert (unrelated / "keep.txt").exists()\n\n\ndef test_database_wipe_requires_verified_quiescence():\n    import services.db_maintenance as maintenance\n\n    with pytest.raises(RuntimeError, match="verified quiesced"):\n        asyncio.run(maintenance.wipe_database())\n\n\ndef test_entrypoint_does_not_recursive_chown_downloads_by_default():\n    source = (Path(__file__).resolve().parents[2] / "entrypoint.sh").read_text()\n    assert "CHOWN_DOWNLOADS_RECURSIVE" in source\n    assert "for DIR in /app/data /app/config /download" not in source\n\n\ndef test_scheduler_has_single_reconciliation_loop():\n    source = (Path(__file__).resolve().parents[1] / "core" / "scheduler.py").read_text()\n    assert "reconcile_download_client_cycle" not in source\n    assert "async def recovery_loop" not in source\n    assert "transfer_service.reconciliation.reconcile()" in source\n''',
)

# Strengthen the existing architecture regression.
replace_once(
    "backend/tests/test_v105_architecture.py",
    "    assert \"bind_architecture\" in root\n",
    "    assert \"bind_architecture\" in root\n"
    "    assert \"def __getattr__\" not in root\n",
)

print("v1.0.6 core cleanup patch applied")
