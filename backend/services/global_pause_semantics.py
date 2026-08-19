"""Safe transition from Pause All to one selectively resumed transfer.

Pause All is a global scheduling gate. If an operator explicitly resumes one
paused transfer while that gate is active, DebridPulse converts the other
currently paused transfers into durable selective pauses before releasing the
global gate, then resumes only the selected transfer.
"""
from __future__ import annotations

import logging
from typing import Iterable

from core.config import apply_settings, get_settings, save_settings
from core.logging_utils import sanitize_exception
from db.database import get_db

logger = logging.getLogger("alldebrid.global_pause_semantics")
_INTENT_TABLE = "transfer_pause_intents"


def _paused_sibling_ids(rows: Iterable[dict], target_id: int) -> list[int]:
    target_id = int(target_id)
    return sorted(
        {
            int(row["id"])
            for row in rows
            if int(row["id"]) != target_id
        }
    )


def _set_global_paused(paused: bool) -> None:
    cfg = get_settings()
    if bool(cfg.paused) == bool(paused):
        return
    cfg = cfg.model_copy(update={"paused": bool(paused)})
    save_settings(cfg)
    apply_settings(cfg)


async def _persist_transition(
    coordinator,
    torrent_id: int,
    sibling_ids: list[int],
    *,
    target_paused: bool,
) -> None:
    """Persist sibling intents and the selected transfer tombstone together."""
    async with get_db() as db:
        for sibling_id in sibling_ids:
            await db.execute(
                f"""INSERT INTO {_INTENT_TABLE}
                       (torrent_id, paused, updated_at)
                   VALUES (?, 1, CURRENT_TIMESTAMP)
                   ON CONFLICT(torrent_id) DO UPDATE SET
                       paused=1, updated_at=CURRENT_TIMESTAMP""",
                (int(sibling_id),),
            )
        await db.execute(
            f"""INSERT INTO {_INTENT_TABLE}
                   (torrent_id, paused, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(torrent_id) DO UPDATE SET
                   paused=excluded.paused,
                   updated_at=CURRENT_TIMESTAMP""",
            (int(torrent_id), 1 if target_paused else 0),
        )
        await db.commit()

    coordinator._pause_intents.update(sibling_ids)
    if target_paused:
        coordinator._pause_intents.add(int(torrent_id))
    else:
        coordinator._pause_intents.discard(int(torrent_id))


def install_global_pause_semantics(manager) -> None:
    coordinator = getattr(manager, "_dp_transfer_control", None)
    if coordinator is None:
        raise RuntimeError("transfer-control coordinator must be installed first")
    if getattr(coordinator, "_global_pause_semantics_installed", False):
        return

    original_resume = coordinator.resume_torrent

    async def resume_torrent(torrent_id: int):
        torrent_id = int(torrent_id)
        await coordinator.ensure_initialized()

        # Ordinary selective Resume keeps the already-tested v1.0.3 path.
        if not bool(get_settings().paused):
            return await original_resume(torrent_id)

        released_while_waiting = False
        sibling_ids: list[int] = []
        result = None

        async with manager._aria2_state_lock:
            # Resume All or another operator action may have released the global
            # gate while this request waited for serialization.
            if not bool(get_settings().paused):
                released_while_waiting = True
            else:
                async with get_db() as db:
                    target = await db.fetchone(
                        "SELECT id, status FROM torrents WHERE id=?",
                        (torrent_id,),
                    )
                    if not target:
                        raise ValueError("Transfer not found")
                    if str(target.get("status") or "") != "paused":
                        raise ValueError("Transfer is not paused")

                    rows = await db.fetchall(
                        """SELECT id FROM torrents
                             WHERE status='paused' AND id!=?
                             ORDER BY id""",
                        (torrent_id,),
                    )

                sibling_ids = _paused_sibling_ids(rows, torrent_id)

                # Every sibling receives durable selective-pause intent before
                # the global scheduling gate is released. There is no interval
                # where the scheduler can interpret those paused GIDs as accidental.
                await _persist_transition(
                    coordinator,
                    torrent_id,
                    sibling_ids,
                    target_paused=False,
                )

                try:
                    _set_global_paused(False)
                except Exception:
                    # Nothing has been resumed yet. Restore the selected transfer's
                    # pause intent and leave Pause All in force.
                    await _persist_transition(
                        coordinator,
                        torrent_id,
                        sibling_ids,
                        target_paused=True,
                    )
                    raise

                try:
                    result = await coordinator._resume_parent(torrent_id)
                except Exception:
                    # A multi-GID resume can fail after partially changing daemon
                    # state. Re-park the selected transfer and restore the original
                    # global mode instead of exposing an unrequested mixed state.
                    await _persist_transition(
                        coordinator,
                        torrent_id,
                        sibling_ids,
                        target_paused=True,
                    )
                    try:
                        await coordinator._pause_parent(torrent_id, strict=False)
                    except Exception as pause_exc:
                        logger.warning(
                            "Could not fully re-park transfer %s after failed "
                            "global-pause Resume: %s",
                            torrent_id,
                            sanitize_exception(pause_exc, max_length=180),
                        )
                    try:
                        _set_global_paused(True)
                    except Exception as restore_exc:
                        logger.error(
                            "Could not restore global Pause All after failed "
                            "individual Resume: %s",
                            sanitize_exception(restore_exc, max_length=180),
                        )
                    raise

        if released_while_waiting:
            return await original_resume(torrent_id)

        await manager._log_event(
            torrent_id,
            "info",
            "Global Pause All converted to selective pause; "
            f"resumed this transfer while {len(sibling_ids)} other "
            "paused transfer(s) remain parked",
        )
        coordinator._schedule_queue()
        return result

    coordinator.resume_torrent = resume_torrent
    manager.resume_torrent = resume_torrent
    coordinator._global_pause_semantics_installed = True
    logger.info("v1.0.3 global-to-selective pause semantics installed")
