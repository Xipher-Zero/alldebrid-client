"""Efficient, serialized aria2 reconciliation for the scheduler hot path.

The normal scheduler cycle observes one authoritative aria2 snapshot and reuses
it for database reconciliation, slot accounting, and dispatch. Operator control
paths still use direct tellStatus confirmation and are intentionally unaffected.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import logging
from typing import Optional

from core.config import get_settings
from core.performance import async_timer, increment
from db.database import get_db
from services.aria2_runtime import is_builtin_mode

logger = logging.getLogger("alldebrid.reconcile_cycle")

# The owner task is stored with the snapshot because ContextVar values are copied
# into newly-created asyncio tasks. A child task must never inherit and reuse a
# scheduler snapshot that was authoritative only for its parent's reconciliation.
_cycle_snapshot: ContextVar[Optional[tuple[asyncio.Task, list]]] = ContextVar(
    "debridpulse_aria2_cycle_snapshot",
    default=None,
)


def install_scheduler_snapshot_reuse(manager) -> None:
    """Make manager._aria2_get_all reuse a snapshot only in its owner task."""
    if getattr(manager, "_dp_scheduler_snapshot_reuse_installed", False):
        return

    original_get_all = manager._aria2_get_all
    manager._dp_scheduler_raw_aria2_get_all = original_get_all

    async def contextual_get_all():
        cached = _cycle_snapshot.get()
        current = asyncio.current_task()
        if cached is not None and cached[0] is current:
            increment("aria2.scheduler_snapshot_reuse")
            return list(cached[1])
        return await original_get_all()

    manager._aria2_get_all = contextual_get_all
    manager._dp_scheduler_snapshot_reuse_installed = True


def _install_confirm_gid_metrics(manager) -> None:
    """Instrument the manager confirmation path without changing semantics.

    TransferControlCoordinator.install() binds ``manager._aria2_confirm_gid`` to
    the coordinator's then-current bound method. Replacing
    ``coordinator.confirm_gid`` later does not update that already-bound manager
    attribute, so scheduler instrumentation must wrap the manager reference
    itself. This is diagnostic-only and leaves operator pause/resume methods
    untouched.
    """
    if getattr(manager, "_dp_confirm_gid_metrics_installed", False):
        return

    original_confirm_gid = manager._aria2_confirm_gid

    async def profiled_confirm_gid(*args, **kwargs):
        increment("aria2.confirm_gid_calls")
        try:
            async with async_timer("aria2.confirm_gid"):
                result = await original_confirm_gid(*args, **kwargs)
        except Exception:
            increment("aria2.confirm_gid_errors")
            raise
        if result is None:
            increment("aria2.confirm_gid_missing")
        return result

    manager._aria2_confirm_gid = profiled_confirm_gid
    manager._dp_confirm_gid_metrics_installed = True


async def _raw_snapshot(manager):
    install_scheduler_snapshot_reuse(manager)
    increment("aria2.scheduler_snapshot_fetch")
    async with async_timer("reconcile.snapshot"):
        return await manager._dp_scheduler_raw_aria2_get_all()


async def _has_unintended_paused_children(coordinator) -> bool:
    """Return True when Resume intent exists but aria2 is still physically parked."""
    async with get_db() as db:
        rows = await db.fetchall(
            """SELECT DISTINCT f.torrent_id
                 FROM download_files f
                 JOIN torrents t ON t.id=f.torrent_id
                WHERE f.download_client='aria2'
                  AND f.blocked=0
                  AND f.status='paused'
                  AND t.status NOT IN ('completed','deleted','error')"""
        )
    pause_intents = coordinator._pause_intents
    return any(int(row["torrent_id"]) not in pause_intents for row in rows)


async def reconcile_download_client_cycle(manager) -> None:
    """Run one scheduler reconciliation with minimal duplicate aria2 snapshots.

    One snapshot is authoritative for observation and ordinary dispatch. A fresh
    snapshot is fetched only after an operation that may actually mutate aria2
    state. Strict operator pause/resume confirmation remains unchanged.
    """
    coordinator = getattr(manager, "_dp_transfer_control", None)
    if coordinator is None or manager.download_client_name() != "aria2":
        await manager.sync_download_clients()
        return

    install_scheduler_snapshot_reuse(manager)
    _install_confirm_gid_metrics(manager)
    await coordinator.ensure_initialized()
    globally_paused = bool(get_settings().paused)

    async with manager._aria2_state_lock:
        snapshot = await _raw_snapshot(manager)

        # sync_aria2_downloads() was written to fetch its own snapshot. Reuse the
        # cycle snapshot inside this task without changing its public contract.
        owner = asyncio.current_task()
        async with async_timer("reconcile.sync_downloads"):
            if owner is None:
                await manager.sync_aria2_downloads()
            else:
                token = _cycle_snapshot.set((owner, snapshot))
                try:
                    await manager.sync_aria2_downloads()
                finally:
                    _cycle_snapshot.reset(token)

        if globally_paused:
            async with async_timer("reconcile.global_pause"):
                await coordinator._enforce_global_pause()
            return

        # Selective pause enforcement may physically pause a newly-created GID.
        # Keep the strict reliability behavior and refresh only when intents exist.
        if coordinator._pause_intents:
            async with async_timer("reconcile.selective_pause"):
                await coordinator._enforce_selective_pauses()
            snapshot = await _raw_snapshot(manager)

        owned = await coordinator._owned(snapshot)
        limit = manager._aria2_slot_limit()
        live = [item for item in owned if item.status in {"active", "waiting"}]
        available = max(0, limit - len(live))

        # A resumed transfer can remain physically paused while all application
        # slots are occupied. Avoid a new daemon snapshot merely to discover
        # there is no capacity. When capacity exists, retain the proven resume
        # path and refresh only if it actually changed daemon state.
        async with async_timer("reconcile.resume_parked"):
            should_resume = (
                available > 0
                and await _has_unintended_paused_children(coordinator)
            )
            if should_resume:
                resumed = await coordinator._resume_unintended_paused()
            else:
                resumed = 0
        if resumed:
            snapshot = await _raw_snapshot(manager)

        # dispatch_queue already accepts an authoritative snapshot. Passing this
        # one avoids its own get_all() while preserving ownership and slot checks.
        async with async_timer("reconcile.dispatch"):
            await coordinator.dispatch_queue(snapshot)
        async with async_timer("reconcile.ready_parent"):
            await manager._schedule_ready_aria2_parents()

    # External aria2 history is daemon-owned, so orphan cleanup is already a
    # no-op there. Keep the dedicated built-in cleanup behavior unchanged.
    if is_builtin_mode():
        try:
            async with async_timer("reconcile.cleanup"):
                await manager._cleanup_aria2_orphans()
        except Exception as exc:
            logger.debug("aria2 orphan cleanup deferred: %s", exc)
