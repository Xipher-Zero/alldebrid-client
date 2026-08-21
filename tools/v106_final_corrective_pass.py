from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1. Capability-bearing provider/download URLs must never survive error persistence.
replace_once(
    "backend/services/manager_v2.py",
    '''def _safe_persisted_error(exc: BaseException) -> str:\n    """Never persist provider/download capability material from an exception."""\n    return sanitize_exception(exc, max_length=300)\n''',
    '''def _safe_persisted_error(exc: BaseException, capability: str = "") -> str:\n    """Never persist provider/download capability material from an exception."""\n    raw = str(exc).strip() or repr(exc)\n    exact = str(capability or "").strip()\n    if exact:\n        raw = raw.replace(exact, "<capability-url>")\n    return sanitize_exception(Exception(raw), max_length=300)\n''',
)
replace_once(
    "backend/services/manager_v2.py",
    '''                            "error": sanitize_exception(exc, max_length=500),\n''',
    '''                            "error": _safe_persisted_error(exc, row["source_url"]),\n''',
)
replace_once(
    "backend/services/manager_v2.py",
    '''                if row["_err"]:\n                    error = row["_err"]\n                    error_text = str(error)\n                    provider_code = str(getattr(error, "code", "") or "")\n''',
    '''                if row["_err"]:\n                    error = row["_err"]\n                    capability = str(\n                        row.get("source_url")\n                        if row.get("transfer_source") == DIRECT_LINK_SOURCE\n                        else row.get("download_url")\n                        or ""\n                    ).strip()\n                    error_text = _safe_persisted_error(error, capability)\n                    provider_code = str(getattr(error, "code", "") or "")\n''',
)
replace_once(
    "backend/services/manager_v2.py",
    '''                        logger.error(\n                            "aria2 dispatch failed [%s]: %s",\n                            row["filename"],\n                            error,\n                        )\n''',
    '''                        logger.error(\n                            "aria2 dispatch failed [%s]: %s",\n                            row["filename"],\n                            error_text,\n                        )\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''                    logger.info("aria2: queued download %s (%s)", sanitize_log_value(normalized_uri, max_length=120), gid)\n''',
    '''                    logger.info("aria2: queued download accepted as GID %s", gid)\n''',
)

# 2. Provider routes must use tracked gateway operations; do not expose a raw client.
replace_once(
    "backend/services/provider_gateway.py",
    '''    def client(self):\n        """Return the configured AllDebrid client for read-only/provider-only operations."""\n        return self.engine.ad()\n\n''',
    '''    async def get_magnet_files(self, magnet_ids):\n        async with self._operation():\n            return await self.engine.ad().get_magnet_files(magnet_ids)\n\n''',
)
replace_once(
    "backend/services/provider_gateway.py",
    '''    async def test(self):\n        async with self._operation():\n            return await self.client().get_user()\n''',
    '''    async def test(self):\n        async with self._operation():\n            return await self.engine.ad().get_user()\n''',
)
replace_once(
    "backend/services/transfer_service.py",
    '''    def ad(self):\n        """Compatibility name retained for one provider-only route; no fallback."""\n        return self.provider.client()\n\n''',
    '''''',
)
replace_once(
    "backend/api/routes.py",
    '''    from services.alldebrid import AllDebridService\n    svc = AllDebridService(cfg.alldebrid_api_key, cfg.alldebrid_agent)\n    try:\n        user = await svc.get_user()\n        await svc.close()\n''',
    '''    try:\n        user = await transfer_service.provider.test()\n''',
)
replace_once(
    "backend/api/routes.py",
    '''        files_data = await transfer_service.provider.client().get_magnet_files([str(row["alldebrid_id"])])\n''',
    '''        files_data = await transfer_service.provider.get_magnet_files([str(row["alldebrid_id"])])\n''',
)

# 3. Source-built OCI metadata must match the V1 AllDebrid scope even without CI overrides.
replace_once(
    "Dockerfile",
    '''LABEL org.opencontainers.image.title="DebridPulse — Multi-provider Debrid Download Manager"\n''',
    '''LABEL org.opencontainers.image.title="DebridPulse — AllDebrid + aria2 Download Manager"\n''',
)
replace_once(
    "Dockerfile",
    '''LABEL org.opencontainers.image.description="Multi-provider debrid download manager for direct links, magnets, and torrent files"\n''',
    '''LABEL org.opencontainers.image.description="AllDebrid-backed download manager for direct links, magnets, and torrent files via aria2"\n''',
)

# 4. Lifespan cleanup must run even if the ASGI lifespan context exits exceptionally.
replace_once(
    "backend/main.py",
    '''    await start_scheduler()\n    yield\n    logger.info("Shutting down %s...", APP_NAME)\n    await stop_scheduler()\n    try:\n        await aria2_runtime.stop()\n    except Exception as exc:\n        logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(exc))\n''',
    '''    await start_scheduler()\n    try:\n        yield\n    finally:\n        logger.info("Shutting down %s...", APP_NAME)\n        try:\n            await stop_scheduler()\n        finally:\n            try:\n                await aria2_runtime.stop()\n            except Exception as exc:\n                logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(exc))\n''',
)

# 5. Remaining browser-facing event/snapshot timestamps use the canonical serializer.
replace_once(
    "backend/api/routes.py",
    '''            "events": [dict(event) for event in events],\n''',
    '''            "events": [public_payload(dict(event)) for event in events],\n''',
)
replace_once(
    "backend/api/routes.py",
    '''@router.get("/events")\nasync def get_events(limit: int = Query(200, le=500)):\n    async with get_db() as db:\n        return await db.fetchall(\n            """SELECT e.*, t.name AS torrent_name\n               FROM events e\n               LEFT JOIN torrents t ON t.id = e.torrent_id\n               ORDER BY e.created_at DESC LIMIT ?""",\n            (limit,),\n        )\n''',
    '''@router.get("/events")\nasync def get_events(limit: int = Query(200, le=500)):\n    async with get_db() as db:\n        rows = await db.fetchall(\n            """SELECT e.*, t.name AS torrent_name\n               FROM events e\n               LEFT JOIN torrents t ON t.id = e.torrent_id\n               ORDER BY e.created_at DESC LIMIT ?""",\n            (limit,),\n        )\n    return public_payload(rows)\n''',
)
replace_once(
    "backend/api/routes.py",
    '''    return {"snapshots": rows}\n''',
    '''    return {"snapshots": public_payload(rows)}\n''',
)

# Focused regressions for every finding closed by this pass.
test_path = ROOT / "backend/tests/test_v106_final_corrective_pass.py"
test_path.write_text('''import asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\n\nimport pytest\n\n\ndef test_exact_capability_is_removed_from_persisted_errors():\n    from services.manager_v2 import _safe_persisted_error\n\n    capability = "https://locked.invalid/cap"\n    rendered = _safe_persisted_error(\n        RuntimeError(f"provider echoed {capability} in failure"), capability\n    )\n    assert capability not in rendered\n    assert "<capability-url>" in rendered\n\n\ndef test_aria2_success_logging_never_formats_request_uri():\n    source = (Path(__file__).parents[1] / "services" / "aria2.py").read_text()\n    ensure = source.split("async def ensure_download", 1)[1].split("def _find_all_matches", 1)[0]\n    assert "queued download accepted as GID %s" in ensure\n    assert "sanitize_log_value(normalized_uri" not in ensure\n    assert "queued download %s (%s)" not in ensure\n\n\n@pytest.mark.asyncio\nasync def test_provider_gateway_tracks_read_only_file_preview_and_test_calls():\n    from services.provider_gateway import ProviderGateway\n\n    class Client:\n        async def get_magnet_files(self, ids):\n            return [{"id": ids[0]}]\n\n        async def get_user(self):\n            return {"user": {"username": "ok"}}\n\n    client = Client()\n    gateway = ProviderGateway(SimpleNamespace(ad=lambda: client))\n    assert await gateway.get_magnet_files(["7"]) == [{"id": "7"}]\n    assert (await gateway.test())["user"]["username"] == "ok"\n\n    await gateway.begin_quiescence()\n    try:\n        with pytest.raises(RuntimeError, match="quiesced"):\n            await gateway.get_magnet_files(["7"])\n        with pytest.raises(RuntimeError, match="quiesced"):\n            await gateway.test()\n    finally:\n        await gateway.end_quiescence()\n\n\ndef test_routes_do_not_bypass_provider_gateway():\n    root = Path(__file__).parents[1]\n    routes = (root / "api" / "routes.py").read_text()\n    service = (root / "services" / "transfer_service.py").read_text()\n    assert "provider.client()" not in routes\n    test_block = routes.split("async def test_alldebrid():", 1)[1].split(\n        '@router.post("/settings/test-aria2")', 1\n    )[0]\n    assert "transfer_service.provider.test()" in test_block\n    assert "AllDebridService" not in test_block\n    assert "def ad(self)" not in service\n\n\ndef test_dockerfile_uses_current_v1_oci_identity():\n    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text()\n    assert 'org.opencontainers.image.title="DebridPulse — AllDebrid + aria2 Download Manager"' in dockerfile\n    assert 'org.opencontainers.image.description="AllDebrid-backed download manager for direct links, magnets, and torrent files via aria2"' in dockerfile\n    assert "Multi-provider Debrid Download Manager" not in dockerfile\n    assert "Multi-provider debrid download manager" not in dockerfile\n\n\ndef test_lifespan_shutdown_is_finally_guarded():\n    source = (Path(__file__).parents[1] / "main.py").read_text()\n    block = source.split("async def lifespan", 1)[1].split("class _RequestBodyTooLarge", 1)[0]\n    started = block.index("await start_scheduler()")\n    guarded = block.index("try:", started)\n    yielded = block.index("yield", guarded)\n    final = block.index("finally:", yielded)\n    stopped = block.index("await stop_scheduler()", final)\n    aria2 = block.index("await aria2_runtime.stop()", stopped)\n    assert started < guarded < yielded < final < stopped < aria2\n\n\ndef test_event_and_snapshot_routes_use_public_timestamp_serialization():\n    source = (Path(__file__).parents[1] / "api" / "routes.py").read_text()\n    detail = source.split("async def get_torrent(torrent_id: int):", 1)[1].split(\n        '@router.delete("/torrents/{torrent_id}")', 1\n    )[0]\n    events = source.split("async def get_events(", 1)[1].split(\n        '@router.get("/admin/performance")', 1\n    )[0]\n    snapshots = source.split("async def list_stats_snapshots", 1)[1].split("@router", 1)[0]\n    assert 'public_payload(dict(event))' in detail\n    assert "return public_payload(rows)" in events\n    assert 'return {"snapshots": public_payload(rows)}' in snapshots\n\n\ndef test_public_payload_normalizes_event_timestamp():\n    from api.serializers import public_payload\n\n    payload = public_payload({"message": "x", "created_at": "2026-08-21 03:00:00"})\n    assert payload["created_at"] == "2026-08-21T03:00:00Z"\n''', encoding="utf-8")

print("Applied final v1.0.6 corrective pass")
