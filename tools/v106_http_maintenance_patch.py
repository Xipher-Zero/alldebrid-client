from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


# Expose the same reentrant operation admission primitive to HTTP middleware.
replace_once(
    "backend/services/transfer_service.py",
    '''    def database_wipe_admission(self):\n        """Close application mutation/execution admission for destructive maintenance."""\n        return self._application_maintenance.maintenance()\n''',
    '''    def application_operation(self):\n        """Admit one state-changing application operation unless maintenance owns admission."""\n        return self._application_maintenance.operation()\n\n    def database_wipe_admission(self):\n        """Close application mutation/execution admission for destructive maintenance."""\n        return self._application_maintenance.maintenance()\n''',
)

# Gate every state-changing HTTP request, not merely routes that happen to call
# TransferService. The wipe endpoint is the owner that closes this gate itself.
replace_once(
    "backend/main.py",
    '''app = FastAPI(\n    title=APP_METADATA_TITLE,\n    description=(\n        "Self-hosted debrid transfer manager for direct links, magnets, and torrent files. "\n        "V1 includes the AllDebrid provider backend.\\n\\n"\n        "## API structure\\n\\n"\n        "| Prefix | Description |\\n"\n        "|--------|-------------|\\n"\n        f"| `/api/` | Native {APP_SHORT_NAME} REST API |\\n\\n"\n        "Interactive docs: `/docs` (Swagger UI) · `/redoc` (ReDoc) · `/openapi.json`"\n    ),\n    version=read_version(),\n    docs_url="/docs",\n    redoc_url="/redoc",\n    openapi_url="/openapi.json",\n    lifespan=lifespan,\n)\n\n\n''',
    '''app = FastAPI(\n    title=APP_METADATA_TITLE,\n    description=(\n        "Self-hosted debrid transfer manager for direct links, magnets, and torrent files. "\n        "V1 includes the AllDebrid provider backend.\\n\\n"\n        "## API structure\\n\\n"\n        "| Prefix | Description |\\n"\n        "|--------|-------------|\\n"\n        f"| `/api/` | Native {APP_SHORT_NAME} REST API |\\n\\n"\n        "Interactive docs: `/docs` (Swagger UI) · `/redoc` (ReDoc) · `/openapi.json`"\n    ),\n    version=read_version(),\n    docs_url="/docs",\n    redoc_url="/redoc",\n    openapi_url="/openapi.json",\n    lifespan=lifespan,\n)\n\n\n_MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}\n_DATABASE_WIPE_PATH = "/api/admin/database/wipe"\n\n\n@app.middleware("http")\nasync def application_mutation_admission_middleware(request: Request, call_next):\n    """Serialize all state-changing HTTP work against destructive maintenance."""\n    if (\n        request.method.upper() in _MUTATING_HTTP_METHODS\n        and request.url.path != _DATABASE_WIPE_PATH\n    ):\n        try:\n            async with transfer_service.application_operation():\n                return await call_next(request)\n        except ApplicationMaintenanceActive:\n            return Response(\n                content="Application maintenance in progress",\n                status_code=503,\n                headers={"Retry-After": "2"},\n            )\n    return await call_next(request)\n\n\n''',
)

# Re-read all destructive settings after the app gate drains operations; the
# pre-gate cfg object may have become stale due to a request admitted just before
# maintenance closed admission. Also restart scheduler only if this call stopped it.
routes = ROOT / "backend/api/routes.py"
text = routes.read_text()
old = '''    async with _database_wipe_lock:\n        scheduler_was_running = scheduler_runtime.scheduler_running()\n        quiesced = False\n        try:\n            async with transfer_service.database_wipe_admission():\n                # A Resume could have been admitted immediately before maintenance\n                # closed admission. The gate drains it first; re-check the durable\n                # Pause All invariant only after that drain completes.\n                if not getattr(get_settings(), "paused", False):\n                    raise HTTPException(409, "Pause processing before wiping the database")\n\n                if scheduler_was_running:\n                    await scheduler_runtime.stop_scheduler()\n\n                try:\n                    quiesce_result = await transfer_service.quiesce_for_database_wipe()\n                    quiesced = True\n                except Exception as exc:\n                    raise HTTPException(409, _sanitize_error(exc))\n\n                try:\n                    # Application execution admission, scheduler activity, provider\n                    # work, materialization work and owned aria2 execution are all\n                    # closed/drained before this database writer gate is acquired.\n                    async with database_maintenance():\n                        backup_result = None\n                        if getattr(cfg, "db_backup_before_wipe", True):\n                            from services.db_maintenance import run_database_backup\n                            backup_result = await run_database_backup()\n                            if backup_result.get("skipped"):\n                                raise HTTPException(409, "Pre-wipe database backup is required but disabled")\n                            if backup_result.get("errors"):\n                                raise HTTPException(500, "Pre-wipe database backup failed; wipe aborted")\n\n                        from services.db_maintenance import wipe_database\n                        result = await wipe_database(verified_quiesced=True)\n\n                    return {**result, "backup": backup_result, "quiesced": quiesce_result}\n                finally:\n                    if quiesced:\n                        await transfer_service.release_database_wipe_quiescence()\n                        quiesced = False\n        finally:\n            # Restart only after application admission has reopened so new\n            # scheduler tasks cannot immediately bounce off the maintenance gate.\n            if scheduler_was_running:\n                await scheduler_runtime.start_scheduler()\n'''
new = '''    async with _database_wipe_lock:\n        scheduler_was_running = scheduler_runtime.scheduler_running()\n        scheduler_stopped = False\n        quiesced = False\n        try:\n            async with transfer_service.database_wipe_admission():\n                # A state-changing request could have been admitted immediately\n                # before maintenance closed admission. The gate drains it first;\n                # refresh every destructive setting only after that drain.\n                cfg = get_settings()\n                if not getattr(cfg, "db_wipe_enabled", False):\n                    raise HTTPException(400, "Database wipe is disabled in settings")\n                if not getattr(cfg, "paused", False):\n                    raise HTTPException(409, "Pause processing before wiping the database")\n\n                if scheduler_was_running:\n                    await scheduler_runtime.stop_scheduler()\n                    scheduler_stopped = True\n\n                try:\n                    quiesce_result = await transfer_service.quiesce_for_database_wipe()\n                    quiesced = True\n                except Exception as exc:\n                    raise HTTPException(409, _sanitize_error(exc))\n\n                try:\n                    # Application execution admission, scheduler activity, provider\n                    # work, materialization work and owned aria2 execution are all\n                    # closed/drained before this database writer gate is acquired.\n                    async with database_maintenance():\n                        backup_result = None\n                        if getattr(cfg, "db_backup_before_wipe", True):\n                            from services.db_maintenance import run_database_backup\n                            backup_result = await run_database_backup()\n                            if backup_result.get("skipped"):\n                                raise HTTPException(409, "Pre-wipe database backup is required but disabled")\n                            if backup_result.get("errors"):\n                                raise HTTPException(500, "Pre-wipe database backup failed; wipe aborted")\n\n                        from services.db_maintenance import wipe_database\n                        result = await wipe_database(verified_quiesced=True)\n\n                    return {**result, "backup": backup_result, "quiesced": quiesce_result}\n                finally:\n                    if quiesced:\n                        await transfer_service.release_database_wipe_quiescence()\n                        quiesced = False\n        finally:\n            # Restart only after application admission has reopened so new\n            # scheduler tasks cannot immediately bounce off the maintenance gate.\n            if scheduler_stopped:\n                await scheduler_runtime.start_scheduler()\n'''
if text.count(old) != 1:
    raise SystemExit(f"routes wipe block match count={text.count(old)}")
text = text.replace(old, new, 1)
text = text.replace(
    '''    (downloads currently paused due to low disk space).\n''',
    '''    (new dispatches currently deferred due to low disk space).\n''',
    1,
)
routes.write_text(text)

# When disabling an active disk guard, clear the guard before kicking dispatch;
# otherwise the dispatch kick sees the guard still active and no-ops.
replace_once(
    "backend/services/manager_v2.py",
    '''        if min_gb <= 0:\n            # Guard disabled — ensure any previously paused downloads are resumed\n            if self._disk_guard_active:\n                await self._disk_guard_resume_all()\n                self._disk_guard_active = False\n            return {"enabled": False, "active": False, "free_gb": -1.0, "min_free_gb": 0}\n''',
    '''        if min_gb <= 0:\n            # Guard disabled — clear it before kicking deferred dispatch so the\n            # queue path does not immediately no-op on the old guard state.\n            if self._disk_guard_active:\n                self._disk_guard_active = False\n                await self._disk_guard_resume_all()\n            return {"enabled": False, "active": False, "free_gb": -1.0, "min_free_gb": 0}\n''',
)

# Document that HTTP mutation admission is part of the destructive boundary.
replace_once(
    "SECURITY.md",
    "Database wipe first closes and drains application mutation/execution admission, then suspends scheduler activity and drains provider/materialization work before holding an exclusive database-maintenance gate",
    "Database wipe first closes and drains application mutation/execution admission (including all state-changing HTTP requests), then suspends scheduler activity and drains provider/materialization work before holding an exclusive database-maintenance gate",
)
replace_once(
    "CHANGELOG.md",
    "- Hardened database wipe with an application mutation/execution admission gate, post-drain Pause All revalidation, provider/materialization drain, scheduler suspension, an exclusive fail-closed database maintenance gate, and required pre-wipe backup verification.",
    "- Hardened database wipe with an application mutation/execution admission gate covering all state-changing HTTP requests, post-drain destructive-setting revalidation, provider/materialization drain, scheduler suspension, an exclusive fail-closed database maintenance gate, and required pre-wipe backup verification.",
)

# Strengthen the regression suite for the route class that exposed the hole.
tests = ROOT / "backend/tests/test_v106_corrective_regressions.py"
text = tests.read_text()
text = text.replace(
    '''    routes.scheduler_runtime.stop_scheduler.assert_not_awaited()\n    routes.scheduler_runtime.start_scheduler.assert_awaited_once()\n    assert calls == ["app-gate-enter", "app-gate-exit"]\n''',
    '''    routes.scheduler_runtime.stop_scheduler.assert_not_awaited()\n    routes.scheduler_runtime.start_scheduler.assert_not_awaited()\n    assert calls == ["app-gate-enter", "app-gate-exit"]\n''',
    1,
)
append = r'''


def test_mutating_http_requests_share_application_maintenance_admission():
    main = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    block = main.split("async def application_mutation_admission_middleware", 1)[1].split("@app.exception_handler", 1)[0]
    assert '_MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}' in main
    assert '_DATABASE_WIPE_PATH = "/api/admin/database/wipe"' in main
    assert "request.url.path != _DATABASE_WIPE_PATH" in block
    assert "transfer_service.application_operation()" in block
    assert "ApplicationMaintenanceActive" in block
    assert 'status_code=503' in block


@pytest.mark.asyncio
async def test_database_wipe_refreshes_disabled_setting_after_admission_drain(monkeypatch):
    import api.routes as routes

    state = SimpleNamespace(enabled=True, paused=True)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            db_wipe_enabled=state.enabled,
            paused=state.paused,
            db_backup_before_wipe=False,
        ),
    )
    monkeypatch.setattr(routes.scheduler_runtime, "scheduler_running", lambda: True)

    @asynccontextmanager
    async def application_gate():
        state.enabled = False
        yield

    monkeypatch.setattr(routes.transfer_service, "database_wipe_admission", application_gate)
    monkeypatch.setattr(routes.scheduler_runtime, "stop_scheduler", AsyncMock())
    monkeypatch.setattr(routes.scheduler_runtime, "start_scheduler", AsyncMock())

    with pytest.raises(Exception) as exc:
        await routes.wipe_database_admin({"confirm": True})
    assert getattr(exc.value, "status_code", None) == 400
    routes.scheduler_runtime.stop_scheduler.assert_not_awaited()
    routes.scheduler_runtime.start_scheduler.assert_not_awaited()


def test_disk_guard_disable_clears_gate_before_dispatch_kick():
    manager = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()
    block = manager.split("if min_gb <= 0:", 1)[1].split("free_gb =", 1)[0]
    assert block.index("self._disk_guard_active = False") < block.index("await self._disk_guard_resume_all()")
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text()
    assert "downloads currently paused due to low disk space" not in routes
    assert "new dispatches currently deferred due to low disk space" in routes
'''
if "test_mutating_http_requests_share_application_maintenance_admission" in text:
    raise SystemExit("HTTP maintenance tests already present")
tests.write_text(text + append)

print("HTTP maintenance admission hardening applied")
