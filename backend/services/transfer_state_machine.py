"""Pure transfer-state derivation plus parent aggregation."""
from __future__ import annotations

import logging

from core.config import get_settings
from db.database import get_db

logger = logging.getLogger("debridpulse.state_machine")
_RUNNABLE = frozenset({"pending", "queued", "downloading", "paused"})


def derive_parent_status(*, current_status: str, unfinished_files: int, runnable_files: int,
                         live_active: bool, live_waiting: bool,
                         selectively_paused: bool, globally_paused: bool) -> str:
    if unfinished_files <= 0 or runnable_files <= 0:
        return current_status
    if live_active:
        return "downloading"
    if live_waiting:
        return "queued"
    if selectively_paused or globally_paused:
        return "paused"
    return "queued"


class TransferStateMachine:
    def __init__(self, engine):
        self.engine = engine
        self.control = None

    def bind_control(self, control) -> None:
        self.control = control

    async def aggregate_parent_progress(self, all_downloads=None):
        if self.control is None:
            raise RuntimeError("state machine control dependency is not bound")
        await self.control.ensure_initialized()
        if all_downloads is None:
            all_downloads = await self.engine._aria2_get_all()
        by_gid, _, _ = self.engine._build_aria2_indexes(all_downloads)
        globally_paused = bool(get_settings().paused)
        async with get_db() as db:
            rows = await db.fetchall(
                """SELECT t.id AS torrent_id, t.status AS torrent_status,
                          t.progress AS torrent_progress, f.id AS file_id,
                          f.status AS file_status, f.size_bytes, f.download_id
                     FROM torrents t JOIN download_files f ON f.torrent_id=t.id
                    WHERE t.download_client='aria2'
                      AND t.status IN ('queued','downloading','paused')
                      AND f.download_client='aria2' AND f.blocked=0
                      AND f.status!='missing' ORDER BY t.id,f.id"""
            )
        grouped = {}
        for row in rows:
            grouped.setdefault(int(row["torrent_id"]), []).append(row)
        updates = []
        changed = []
        for transfer_id, files in grouped.items():
            total = done = completed_files = unfinished = runnable = 0
            live_active = live_waiting = False
            for row in files:
                status = str(row["file_status"] or "")
                gid = str(row["download_id"] or "")
                dl = by_gid.get(gid) if gid else None
                persisted = int(row["size_bytes"] or 0)
                live_size = int(dl.total_length or 0) if dl is not None else 0
                size = max(persisted, live_size)
                total += size
                if status == "completed":
                    completed_files += 1
                    done += size
                    continue
                unfinished += 1
                if status in _RUNNABLE:
                    runnable += 1
                if dl is not None:
                    live_active = live_active or dl.status == "active"
                    live_waiting = live_waiting or dl.status == "waiting"
                    amount = max(int(dl.completed_length or 0), 0)
                    done += min(amount, size) if size > 0 else amount
            progress = round(done / total * 100, 1) if total > 0 else (
                round(completed_files / len(files) * 100, 1) if files else 0.0
            )
            progress = min(progress, 99.9) if unfinished else 100.0
            current_progress = float(files[0]["torrent_progress"] or 0.0)
            current_status = str(files[0]["torrent_status"] or "")
            status = derive_parent_status(
                current_status=current_status,
                unfinished_files=unfinished,
                runnable_files=runnable,
                live_active=live_active,
                live_waiting=live_waiting,
                selectively_paused=transfer_id in self.control.pause_intents,
                globally_paused=globally_paused,
            )
            if progress != current_progress or status != current_status:
                updates.append((progress, status, transfer_id))
            if int(progress) != int(current_progress) or status != current_status:
                changed.append({"id": transfer_id, "progress": progress, "status": status,
                                "status_changed": status != current_status})
        if updates:
            async with get_db() as db:
                await db.executemany(
                    """UPDATE torrents SET progress=?,status=?,updated_at=CURRENT_TIMESTAMP
                         WHERE id=? AND status IN ('queued','downloading','paused')""",
                    updates,
                )
                await db.commit()
        if changed:
            try:
                from api.routes import _sse_broadcast
                await _sse_broadcast("torrent_updated", {
                    "progress_only": not any(item["status_changed"] for item in changed),
                    "items": changed,
                })
            except Exception as exc:
                logger.debug("parent progress SSE deferred: %s", exc)
