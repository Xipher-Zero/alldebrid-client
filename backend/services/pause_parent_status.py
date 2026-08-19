"""Parent-status aggregation guard for DebridPulse v1.0.3 pause semantics.

The legacy aggregate progress calculation treated every non-completed child as
runnable work. A multi-file transfer with paused runnable children plus a
terminal error child was therefore derived as ``queued`` even though aria2 had
actually paused all controllable GIDs. This module replaces only the aggregate
parent-status calculation captured by the v1.0.3 transfer-control coordinator.
"""
from __future__ import annotations

import logging

from db.database import get_db

logger = logging.getLogger("alldebrid.pause_parent_status")
_RUNNABLE_FILE_STATES = frozenset({"pending", "queued", "downloading", "paused"})


def derive_parent_status(
    *,
    current_status: str,
    unfinished_files: int,
    runnable_files: int,
    paused_files: int,
    live_active: bool,
    live_waiting: bool,
    selectively_paused: bool,
) -> str:
    """Derive visible parent state from controllable work, not error siblings.

    ``unfinished_files`` still participates in progress clamping, but terminal
    error children are not runnable and therefore must not force a physically
    paused multi-file transfer back to ``queued``.

    A durable selective-pause intent may cover a short DB materialization gap
    where a no-GID child is still ``pending``. We report ``paused`` only when
    aria2 has no active/waiting child; observed daemon state wins while a pause
    transition is still incomplete.
    """
    if unfinished_files <= 0 or runnable_files <= 0:
        return current_status

    if selectively_paused:
        if live_active:
            return "downloading"
        if live_waiting:
            return "queued"
        return "paused"

    if live_active:
        return "downloading"
    if paused_files == runnable_files:
        return "paused"
    return "queued"


def install_parent_progress_guard(manager) -> None:
    """Replace the coordinator's captured aggregate function exactly once."""
    coordinator = getattr(manager, "_dp_transfer_control", None)
    if coordinator is None:
        raise RuntimeError("transfer-control coordinator must be installed first")
    if getattr(coordinator, "_parent_progress_guard_installed", False):
        return

    async def aggregate_parent_progress(all_downloads=None):
        if all_downloads is None:
            all_downloads = await manager._aria2_get_all()

        by_gid, _, _ = manager._build_aria2_indexes(all_downloads)

        async with get_db() as db:
            rows = await db.fetchall(
                """SELECT
                       t.id AS torrent_id,
                       t.status AS torrent_status,
                       t.progress AS torrent_progress,
                       f.id AS file_id,
                       f.status AS file_status,
                       f.size_bytes,
                       f.download_id
                   FROM torrents t
                   JOIN download_files f ON f.torrent_id = t.id
                   WHERE t.download_client = 'aria2'
                     AND t.status IN ('queued', 'downloading', 'paused')
                     AND f.download_client = 'aria2'
                     AND f.blocked = 0
                     AND f.status != 'missing'
                   ORDER BY t.id, f.id"""
            )

        grouped = {}
        for row in rows:
            grouped.setdefault(row["torrent_id"], []).append(row)

        updates = []
        changed_updates = []
        broadcast_needed = False

        for torrent_id, files in grouped.items():
            total_bytes = 0
            completed_bytes = 0
            completed_files = 0
            unfinished_files = 0
            runnable_files = 0
            paused_files = 0
            live_active = False
            live_waiting = False

            for row in files:
                status = str(row["file_status"] or "")
                gid = str(row["download_id"] or "")
                dl = by_gid.get(gid) if gid else None

                persisted_size = int(row["size_bytes"] or 0)
                live_size = int(dl.total_length or 0) if dl is not None else 0
                effective_size = max(persisted_size, live_size)
                total_bytes += effective_size

                if status == "completed":
                    completed_files += 1
                    completed_bytes += effective_size
                    continue

                unfinished_files += 1
                if status in _RUNNABLE_FILE_STATES:
                    runnable_files += 1
                    if status == "paused":
                        paused_files += 1

                if dl is not None:
                    if dl.status == "active":
                        live_active = True
                    elif dl.status == "waiting":
                        live_waiting = True

                    live_completed = max(int(dl.completed_length or 0), 0)
                    if effective_size > 0:
                        live_completed = min(live_completed, effective_size)
                    completed_bytes += live_completed

            if total_bytes > 0:
                progress = round(completed_bytes / total_bytes * 100, 1)
            elif files:
                progress = round(completed_files / len(files) * 100, 1)
            else:
                progress = 0.0

            if unfinished_files > 0:
                progress = min(progress, 99.9)
            else:
                progress = 100.0

            current_progress = float(files[0]["torrent_progress"] or 0.0)
            current_status = str(files[0]["torrent_status"] or "")
            parent_status = derive_parent_status(
                current_status=current_status,
                unfinished_files=unfinished_files,
                runnable_files=runnable_files,
                paused_files=paused_files,
                live_active=live_active,
                live_waiting=live_waiting,
                selectively_paused=int(torrent_id) in coordinator._pause_intents,
            )

            persist_progress_changed = progress != current_progress
            broadcast_progress_changed = int(progress) != int(current_progress)
            status_changed = parent_status != current_status

            if persist_progress_changed or status_changed:
                updates.append((progress, parent_status, torrent_id))

            if broadcast_progress_changed or status_changed:
                broadcast_needed = True
                changed_updates.append(
                    {
                        "id": int(torrent_id),
                        "progress": progress,
                        "status": parent_status,
                        "status_changed": status_changed,
                    }
                )

        if not updates:
            return

        async with get_db() as db:
            await db.executemany(
                """UPDATE torrents
                   SET progress=?, status=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?
                     AND status IN ('queued', 'downloading', 'paused')""",
                updates,
            )
            await db.commit()

        if broadcast_needed:
            try:
                from api.routes import _sse_broadcast

                await _sse_broadcast(
                    "torrent_updated",
                    {
                        "progress_only": not any(
                            item["status_changed"] for item in changed_updates
                        ),
                        "items": changed_updates,
                    },
                )
            except Exception as exc:
                logger.debug(
                    "Aggregate aria2 progress SSE broadcast failed: %s", exc
                )

    coordinator._orig_parent_progress = aggregate_parent_progress
    coordinator._parent_progress_guard_installed = True
