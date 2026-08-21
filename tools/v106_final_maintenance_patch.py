from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1))


def remove_between(path: str, start: str, end: str) -> None:
    target = ROOT / path
    text = target.read_text()
    i = text.find(start)
    j = text.find(end, i + len(start))
    if i < 0 or j < 0:
        raise SystemExit(f"{path}: could not locate removal boundaries")
    target.write_text(text[:i] + text[j:])


# Application-level admission gate. Already-admitted operations drain before
# destructive maintenance owns the gate; new operations fail closed. Reentrant
# admission lets an already-admitted task finish nested service work.
(ROOT / "backend/services/maintenance_gate.py").write_text('''"""Application mutation/execution admission gate for destructive maintenance."""\nfrom __future__ import annotations\n\nimport asyncio\nfrom contextlib import asynccontextmanager\n\n\nclass ApplicationMaintenanceActive(RuntimeError):\n    """Raised when new application work is attempted during maintenance."""\n\n\nclass ApplicationMaintenanceGate:\n    """Drain admitted work, then reject new mutation/execution operations.\n\n    Admission closes before maintenance waits for already-admitted operations.\n    A task admitted before closure may finish nested/reentrant service calls; a\n    different task cannot enter until maintenance releases the gate. The\n    maintenance owner itself may call gated operations needed to quiesce state.\n    """\n\n    def __init__(self) -> None:\n        self._condition = asyncio.Condition()\n        self._active_operations = 0\n        self._depths: dict[asyncio.Task, int] = {}\n        self._maintenance_active = False\n        self._owner: asyncio.Task | None = None\n\n    @property\n    def active(self) -> bool:\n        return self._maintenance_active\n\n    @asynccontextmanager\n    async def operation(self):\n        current = asyncio.current_task()\n        if current is None:\n            raise RuntimeError("Application operation requires an asyncio task")\n        owner = current is self._owner\n        counted = False\n        async with self._condition:\n            depth = self._depths.get(current, 0)\n            if self._maintenance_active and not owner and depth == 0:\n                raise ApplicationMaintenanceActive("Application maintenance is in progress")\n            if not owner:\n                if depth == 0:\n                    self._active_operations += 1\n                    counted = True\n                self._depths[current] = depth + 1\n        try:\n            yield\n        finally:\n            if not owner:\n                async with self._condition:\n                    depth = self._depths.get(current, 0)\n                    if depth <= 1:\n                        self._depths.pop(current, None)\n                        if counted:\n                            self._active_operations = max(0, self._active_operations - 1)\n                            if self._active_operations == 0:\n                                self._condition.notify_all()\n                    else:\n                        self._depths[current] = depth - 1\n\n    @asynccontextmanager\n    async def maintenance(self):\n        current = asyncio.current_task()\n        if current is None:\n            raise RuntimeError("Application maintenance requires an asyncio task")\n        async with self._condition:\n            if self._maintenance_active:\n                raise ApplicationMaintenanceActive("Application maintenance is already in progress")\n            self._maintenance_active = True\n            self._owner = current\n            while self._active_operations:\n                await self._condition.wait()\n        try:\n            yield\n        finally:\n            async with self._condition:\n                self._owner = None\n                self._maintenance_active = False\n                self._condition.notify_all()\n''')

# Bind application-visible mutation/execution operations to the gate.
replace_once(
    "backend/services/transfer_service.py",
    "from services.notification_service import NotificationService\n",
    "from services.notification_service import NotificationService\nfrom services.maintenance_gate import ApplicationMaintenanceGate\n",
)
replace_once(
    "backend/services/transfer_service.py",
    "        self.notifications = NotificationService()\n        materialization_engine.bind_architecture(self)\n",
    "        self.notifications = NotificationService()\n        self._application_maintenance = ApplicationMaintenanceGate()\n        materialization_engine.bind_architecture(self)\n",
)

simple_wrappers = {
    "        return await self.control.pause_transfer(transfer_id)": "        async with self._application_maintenance.operation():\n            return await self.control.pause_transfer(transfer_id)",
    "        return await self.control.resume_transfer(transfer_id)": "        async with self._application_maintenance.operation():\n            return await self.control.resume_transfer(transfer_id)",
    "        return await self.control.pause_all()": "        async with self._application_maintenance.operation():\n            return await self.control.pause_all()",
    "        return await self.control.resume_all()": "        async with self._application_maintenance.operation():\n            return await self.control.resume_all()",
    "        return await self.control.control_gid(*args, **kwargs)": "        async with self._application_maintenance.operation():\n            return await self.control.control_gid(*args, **kwargs)",
    "        return await self.provider.sync_status()": "        async with self._application_maintenance.operation():\n            return await self.provider.sync_status()",
    "        return await self.provider.reconcile_inventory()": "        async with self._application_maintenance.operation():\n            return await self.provider.reconcile_inventory()",
    "        return await self.provider.import_existing()": "        async with self._application_maintenance.operation():\n            return await self.provider.import_existing()",
    "        return await self.provider.full_sync()": "        async with self._application_maintenance.operation():\n            return await self.provider.full_sync()",
    "        return await self.provider.add_magnet(magnet, source=source)": "        async with self._application_maintenance.operation():\n            return await self.provider.add_magnet(magnet, source=source)",
    "        return await self.provider.add_torrent_file(*args, **kwargs)": "        async with self._application_maintenance.operation():\n            return await self.provider.add_torrent_file(*args, **kwargs)",
    "        return await self.provider.add_direct_links(links)": "        async with self._application_maintenance.operation():\n            return await self.provider.add_direct_links(links)",
    "        return await self.provider.retry_direct_link_collection(transfer_id)": "        async with self._application_maintenance.operation():\n            return await self.provider.retry_direct_link_collection(transfer_id)",
    "        return await self.provider.cleanup_no_peer_errors()": "        async with self._application_maintenance.operation():\n            return await self.provider.cleanup_no_peer_errors()",
    "        return await self.provider.cleanup_orphans()": "        async with self._application_maintenance.operation():\n            return await self.provider.cleanup_orphans()",
    "        return await self.provider.cleanup_stuck()": "        async with self._application_maintenance.operation():\n            return await self.provider.cleanup_stuck()",
    "        return await self.aria2.advance_queue()": "        async with self._application_maintenance.operation():\n            return await self.aria2.advance_queue()",
    "        return await self.aria2.apply_memory_tuning()": "        async with self._application_maintenance.operation():\n            return await self.aria2.apply_memory_tuning()",
    "        return await self.aria2.housekeeping()": "        async with self._application_maintenance.operation():\n            return await self.aria2.housekeeping()",
    "        return await self.aria2.deep_sync()": "        async with self._application_maintenance.operation():\n            return await self.aria2.deep_sync()",
    "        return await self.aria2.disk_guard()": "        async with self._application_maintenance.operation():\n            return await self.aria2.disk_guard()",
    "        return await self.control.start_download(*args, **kwargs)": "        async with self._application_maintenance.operation():\n            return await self.control.start_download(*args, **kwargs)",
}
for old, new in simple_wrappers.items():
    replace_once("backend/services/transfer_service.py", old, new)

replace_once(
    "backend/services/transfer_service.py",
    "    async def delete_torrent(self, *args, **kwargs):\n        \"\"\"Delete remains a materialization-engine operation in V1, explicitly exposed.\"\"\"\n        return await self._engine.delete_torrent(*args, **kwargs)\n\n    async def quiesce_for_database_wipe(self):\n",
    "    async def delete_torrent(self, *args, **kwargs):\n        \"\"\"Delete remains a materialization-engine operation in V1, explicitly exposed.\"\"\"\n        async with self._application_maintenance.operation():\n            return await self._engine.delete_torrent(*args, **kwargs)\n\n    def database_wipe_admission(self):\n        \"\"\"Close application mutation/execution admission for destructive maintenance.\"\"\"\n        return self._application_maintenance.maintenance()\n\n    async def quiesce_for_database_wipe(self):\n",
)

# Wipe owns the application gate first, drains admitted work, rechecks Pause All
# after the drain, then stops scheduler/provider/materialization/DB writers.
routes = ROOT / "backend/api/routes.py"
text = routes.read_text()
start = text.index('@router.post("/admin/database/wipe")')
end = text.index('\n\n\n# ── Statistics & Reporting', start)
new_block = '''@router.post("/admin/database/wipe")\nasync def wipe_database_admin(body: dict | None = None):\n    cfg = get_settings()\n    if not getattr(cfg, "db_wipe_enabled", False):\n        raise HTTPException(400, "Database wipe is disabled in settings")\n    if not getattr(cfg, "paused", False):\n        raise HTTPException(409, "Pause processing before wiping the database")\n    if not (body or {}).get("confirm"):\n        raise HTTPException(400, "Wipe confirmation required")\n\n    if _database_wipe_lock.locked():\n        raise HTTPException(409, "Database wipe is already in progress")\n\n    async with _database_wipe_lock:\n        scheduler_was_running = scheduler_runtime.scheduler_running()\n        quiesced = False\n        try:\n            async with transfer_service.database_wipe_admission():\n                # A Resume could have been admitted immediately before maintenance\n                # closed admission. The gate drains it first; re-check the durable\n                # Pause All invariant only after that drain completes.\n                if not getattr(get_settings(), "paused", False):\n                    raise HTTPException(409, "Pause processing before wiping the database")\n\n                if scheduler_was_running:\n                    await scheduler_runtime.stop_scheduler()\n\n                try:\n                    quiesce_result = await transfer_service.quiesce_for_database_wipe()\n                    quiesced = True\n                except Exception as exc:\n                    raise HTTPException(409, _sanitize_error(exc))\n\n                try:\n                    # Application execution admission, scheduler activity, provider\n                    # work, materialization work and owned aria2 execution are all\n                    # closed/drained before this database writer gate is acquired.\n                    async with database_maintenance():\n                        backup_result = None\n                        if getattr(cfg, "db_backup_before_wipe", True):\n                            from services.db_maintenance import run_database_backup\n                            backup_result = await run_database_backup()\n                            if backup_result.get("skipped"):\n                                raise HTTPException(409, "Pre-wipe database backup is required but disabled")\n                            if backup_result.get("errors"):\n                                raise HTTPException(500, "Pre-wipe database backup failed; wipe aborted")\n\n                        from services.db_maintenance import wipe_database\n                        result = await wipe_database(verified_quiesced=True)\n\n                    return {**result, "backup": backup_result, "quiesced": quiesce_result}\n                finally:\n                    if quiesced:\n                        await transfer_service.release_database_wipe_quiescence()\n                        quiesced = False\n        finally:\n            # Restart only after application admission has reopened so new\n            # scheduler tasks cannot immediately bounce off the maintenance gate.\n            if scheduler_was_running:\n                await scheduler_runtime.start_scheduler()\n'''
routes.write_text(text[:start] + new_block + text[end:])

# Map uncaught application-gate rejections to the same transient 503 contract as
# the DB gate. Routes that already sanitize generic service errors still fail closed.
replace_once(
    "backend/main.py",
    "from services.transfer_service import transfer_service\n",
    "from services.transfer_service import transfer_service\nfrom services.maintenance_gate import ApplicationMaintenanceActive\n",
)
replace_once(
    "backend/main.py",
    "@app.exception_handler(DatabaseMaintenanceActive)\nasync def database_maintenance_handler(_request: Request, _exc: DatabaseMaintenanceActive):\n    \"\"\"Fail closed rather than queue stale request work behind a destructive wipe.\"\"\"\n    return Response(\n        content=\"Database maintenance in progress\",\n        status_code=503,\n        headers={\"Retry-After\": \"2\"},\n    )\n\n\n",
    "@app.exception_handler(DatabaseMaintenanceActive)\nasync def database_maintenance_handler(_request: Request, _exc: DatabaseMaintenanceActive):\n    \"\"\"Fail closed rather than queue stale request work behind a destructive wipe.\"\"\"\n    return Response(\n        content=\"Database maintenance in progress\",\n        status_code=503,\n        headers={\"Retry-After\": \"2\"},\n    )\n\n\n@app.exception_handler(ApplicationMaintenanceActive)\nasync def application_maintenance_handler(_request: Request, _exc: ApplicationMaintenanceActive):\n    \"\"\"Reject new mutation/execution work while destructive maintenance owns admission.\"\"\"\n    return Response(\n        content=\"Application maintenance in progress\",\n        status_code=503,\n        headers={\"Retry-After\": \"2\"},\n    )\n\n\n",
)

# Remove dead disk-guard pause bookkeeping. Current policy never pauses active
# jobs; recovery only kicks deferred dispatch.
replace_once(
    "backend/services/manager_v2.py",
    "        self._disk_guard_paused: set[str] = set()     # aria2 GIDs paused by the guard\n",
    "",
)
remove_between(
    "backend/services/manager_v2.py",
    "    async def _disk_guard_pause_all(self) -> None:\n",
    "    async def _disk_guard_resume_all(self) -> None:\n",
)
replace_once(
    "backend/services/manager_v2.py",
    "        self._disk_guard_paused.clear()  # defensive — should already be empty\n",
    "",
)

# Documentation precision.
replace_once(
    "SECURITY.md",
    "Database wipe drains provider/materialization work, suspends scheduler writers, then holds an exclusive database-maintenance gate that rejects concurrent non-owner DB sessions; it also fails closed if a required pre-wipe backup fails. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.",
    "Database wipe first closes and drains application mutation/execution admission, then suspends scheduler activity and drains provider/materialization work before holding an exclusive database-maintenance gate that rejects concurrent non-owner application DB sessions; it also fails closed if a required pre-wipe backup fails. The SQLite online-backup API may hold a separate read-only source connection, but it cannot mutate or repopulate the live database. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.",
)
replace_once(
    "CHANGELOG.md",
    "- Hardened database wipe with provider/materialization drain, scheduler suspension, an exclusive fail-closed database maintenance gate, and required pre-wipe backup verification.",
    "- Hardened database wipe with an application mutation/execution admission gate, post-drain Pause All revalidation, provider/materialization drain, scheduler suspension, an exclusive fail-closed database maintenance gate, and required pre-wipe backup verification.",
)

# Add adversarial coverage for the newly closed race and cleanup contract.
tests = ROOT / "backend/tests/test_v106_corrective_regressions.py"
text = tests.read_text()
append = r'''

@pytest.mark.asyncio
async def test_application_maintenance_gate_drains_admitted_work_and_rejects_new_work():
    from services.maintenance_gate import ApplicationMaintenanceActive, ApplicationMaintenanceGate

    gate = ApplicationMaintenanceGate()
    started = asyncio.Event()
    release = asyncio.Event()
    entered = asyncio.Event()
    release_maintenance = asyncio.Event()

    async def admitted_operation():
        async with gate.operation():
            started.set()
            # Reentrant work in the already-admitted task must be allowed to finish.
            async with gate.operation():
                await release.wait()

    async def maintainer():
        async with gate.maintenance():
            entered.set()
            await release_maintenance.wait()

    operation_task = asyncio.create_task(admitted_operation())
    await started.wait()
    maintenance_task = asyncio.create_task(maintainer())
    await asyncio.sleep(0)
    assert not entered.is_set()

    release.set()
    await operation_task
    await entered.wait()

    with pytest.raises(ApplicationMaintenanceActive, match="maintenance"):
        async with gate.operation():
            pass

    release_maintenance.set()
    await maintenance_task


@pytest.mark.asyncio
async def test_transfer_service_gate_blocks_resume_and_intake_during_wipe_admission():
    from services.maintenance_gate import ApplicationMaintenanceActive, ApplicationMaintenanceGate
    from services.transfer_service import TransferService

    service = object.__new__(TransferService)
    service._application_maintenance = ApplicationMaintenanceGate()
    service.control = SimpleNamespace(resume_all=AsyncMock(return_value={"ok": True}))
    service.provider = SimpleNamespace(add_magnet=AsyncMock(return_value={"ok": True}))

    async with service.database_wipe_admission():
        with pytest.raises(ApplicationMaintenanceActive):
            await service.resume_all_downloads()
        with pytest.raises(ApplicationMaintenanceActive):
            await service.add_magnet_direct("magnet:?xt=urn:btih:test")

    service.control.resume_all.assert_not_awaited()
    service.provider.add_magnet.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_wipe_rechecks_pause_after_application_admission_drain(monkeypatch):
    import api.routes as routes

    calls = []
    state = SimpleNamespace(paused=True)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            db_wipe_enabled=True,
            paused=state.paused,
            db_backup_before_wipe=False,
        ),
    )
    monkeypatch.setattr(routes.scheduler_runtime, "scheduler_running", lambda: True)

    @asynccontextmanager
    async def application_gate():
        calls.append("app-gate-enter")
        # Simulate a Resume that was admitted just before maintenance closed.
        state.paused = False
        try:
            yield
        finally:
            calls.append("app-gate-exit")

    monkeypatch.setattr(routes.transfer_service, "database_wipe_admission", application_gate)
    monkeypatch.setattr(routes.scheduler_runtime, "stop_scheduler", AsyncMock())
    monkeypatch.setattr(routes.scheduler_runtime, "start_scheduler", AsyncMock())

    with pytest.raises(Exception) as exc:
        await routes.wipe_database_admin({"confirm": True})
    assert getattr(exc.value, "status_code", None) == 409
    routes.scheduler_runtime.stop_scheduler.assert_not_awaited()
    routes.scheduler_runtime.start_scheduler.assert_awaited_once()
    assert calls == ["app-gate-enter", "app-gate-exit"]


def test_database_wipe_application_gate_covers_execution_opening_boundaries():
    service = (Path(__file__).resolve().parents[1] / "services" / "transfer_service.py").read_text()
    for method in (
        "resume_torrent",
        "resume_all_downloads",
        "control_aria2_gid",
        "add_magnet_direct",
        "add_torrent_file_direct",
        "add_direct_links",
        "retry_direct_link_collection",
        "delete_torrent",
        "advance_aria2_queue",
        "deep_sync_aria2_finished",
    ):
        block = service.split(f"async def {method}", 1)[1].split("\n    async def ", 1)[0]
        assert "self._application_maintenance.operation()" in block


def test_dead_disk_guard_pause_path_removed():
    manager = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()
    assert "_disk_guard_pause_all" not in manager
    assert "_disk_guard_paused" not in manager
'''
if "test_application_maintenance_gate_drains_admitted_work_and_rejects_new_work" in text:
    raise SystemExit("tests already patched")
tests.write_text(text + append)

print("v1.0.6 final maintenance patch applied")
