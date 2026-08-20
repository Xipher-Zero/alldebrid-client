"""Read-only queue analytics for the authoritative SQLite store."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("alldebrid.analytics")


async def get_queue_analytics(window_hours: int = 24) -> dict:
    try:
        from db.database import get_db
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

        async with get_db() as db:
            completed_row = await db.fetchone(
                "SELECT COUNT(*) AS c, COALESCE(SUM(size_bytes),0) AS total_bytes "
                "FROM torrents WHERE status='completed' AND completed_at >= ?",
                (since,),
            )
            completed_count = int((completed_row or {}).get("c") or 0)
            throughput_bytes = int((completed_row or {}).get("total_bytes") or 0)

            error_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM torrents WHERE status='error' AND updated_at >= ?",
                (since,),
            )
            error_count = int((error_row or {}).get("c") or 0)

            no_peer_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM torrents "
                "WHERE status='error' AND updated_at >= ? "
                "AND (LOWER(COALESCE(error_message,'')) LIKE '%no peer%' OR provider_status_code=8)",
                (since,),
            )
            no_peer_count = int((no_peer_row or {}).get("c") or 0)

            duration_row = await db.fetchone(
                "SELECT AVG((JULIANDAY(completed_at) - JULIANDAY(created_at)) * 86400) AS avg_sec "
                "FROM torrents WHERE status='completed' AND completed_at >= ? "
                "AND completed_at IS NOT NULL AND created_at IS NOT NULL",
                (since,),
            )
            avg_sec = float((duration_row or {}).get("avg_sec") or 0)

            active_row = await db.fetchone(
                "SELECT "
                "SUM(CASE WHEN status IN ('downloading','queued','processing','ready','uploading') THEN 1 ELSE 0 END) AS active,"
                "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors FROM torrents"
            )
            total_active = int((active_row or {}).get("active") or 0)
            total_error = int((active_row or {}).get("errors") or 0)

            error_reasons_rows = await db.fetchall(
                "SELECT COALESCE(error_message,'unknown') AS reason, COUNT(*) AS cnt "
                "FROM torrents WHERE status='error' AND updated_at >= ? "
                "AND error_message IS NOT NULL AND error_message != '' "
                "GROUP BY error_message ORDER BY cnt DESC LIMIT 5",
                (since,),
            )
            top_error_reasons = [
                {"reason": str(row["reason"])[:120], "count": int(row["cnt"])}
                for row in (error_reasons_rows or [])
            ]

            if window_hours <= 48:
                hourly_rows = await db.fetchall(
                    "SELECT STRFTIME('%Y-%m-%dT%H:00:00', completed_at) AS hour, COUNT(*) AS cnt "
                    "FROM torrents WHERE status='completed' AND completed_at >= ? "
                    "GROUP BY hour ORDER BY hour ASC",
                    (since,),
                )
                hourly_completed = [
                    {"hour": str(row["hour"]), "count": int(row["cnt"])}
                    for row in (hourly_rows or [])
                ]
            else:
                hourly_completed = []

        total_finished = completed_count + error_count
        success_rate = completed_count / total_finished if total_finished else 1.0
        return {
            "window_hours": window_hours,
            "completed_count": completed_count,
            "error_count": error_count,
            "no_peer_count": no_peer_count,
            "success_rate": round(success_rate, 4),
            "avg_duration_seconds": round(avg_sec, 1),
            "throughput_gb": round(throughput_bytes / (1024 ** 3), 2),
            "total_active": total_active,
            "total_error": total_error,
            "top_error_reasons": top_error_reasons,
            "hourly_completed": hourly_completed,
        }
    except Exception as exc:
        logger.error("analytics: query failed: %s", exc)
        return {"error": str(exc)}
