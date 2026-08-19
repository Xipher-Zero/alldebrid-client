from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_between(path: Path, start: str, end: str, replacement: str) -> None:
    text = path.read_text()
    start_at = text.find(start)
    if start_at < 0:
        raise SystemExit(f"{path}: start marker not found: {start!r}")
    end_at = text.find(end, start_at + len(start))
    if end_at < 0:
        raise SystemExit(f"{path}: end marker not found: {end!r}")
    if text.find(start, start_at + 1) >= 0:
        raise SystemExit(f"{path}: start marker is not unique")
    path.write_text(text[:start_at] + replacement + text[end_at:])


manager = ROOT / "backend/services/manager_v2.py"
routes = ROOT / "backend/api/routes.py"
app = ROOT / "frontend/static/app.js"
scope_test = ROOT / "backend/tests/test_v1_scope.py"

# Provider polling and download-client reconciliation already have independent
# scheduler loops. Keep each domain responsible for its own state instead of
# nesting the 1-second aria2 reconciliation inside the provider poll.
replace_once(
    manager,
    """        if not rows:\n            await self.sync_download_clients()\n            return\n""",
    """        if not rows:\n            return\n""",
)
replace_once(
    manager,
    """\n        await self.sync_download_clients()\n\n    async def deep_sync_aria2_finished(self):\n""",
    """\n\n    async def deep_sync_aria2_finished(self):\n""",
)

# Batch persistence after parallel direct-link generation. The old code opened
# and committed one DB connection per result, which turned a 100-link batch into
# roughly 100 transaction cycles after the network work had already completed.
direct_start = "            results = await asyncio.gather(*[_unlock(row) for row in file_rows])\n"
direct_end = "            final_name = direct_link_collection_name(\n"
direct_replacement = '''            results = await asyncio.gather(*[_unlock(row) for row in file_rows])
            reserved_paths: Set[str] = set()
            succeeded = 0
            failed = 0
            missing = 0
            total_size = 0
            resolved_names: List[str] = []
            failed_updates: List[tuple] = []
            success_updates: List[tuple] = []
            generation_events: List[tuple] = []

            for position, result in enumerate(results, start=1):
                if result["error"]:
                    failed += 1
                    is_missing = bool(result.get("missing"))
                    if is_missing:
                        missing += 1
                    failure_status = "missing" if is_missing else "error"
                    failure_reason = (
                        "File is no longer available on the source host"
                        if is_missing
                        else result["error"]
                    )
                    failed_updates.append(
                        (failure_status, failure_reason, result["file_id"])
                    )
                    generation_events.append(
                        (
                            torrent_id,
                            "error",
                            f"AllDebrid could not generate link {position}: {failure_reason}",
                        )
                    )
                else:
                    succeeded += 1
                    total_size += int(result["size_bytes"] or 0)
                    resolved_names.append(result["filename"])
                    local_path = self._unique_direct_link_path(
                        output_root,
                        result["filename"],
                        reserved_paths,
                        reuse_existing=(
                            result["source_url"] in reusable_source_urls
                        ),
                    )
                    success_updates.append(
                        (
                            result["filename"],
                            result["size_bytes"],
                            result["generated_url"],
                            str(local_path),
                            result["file_id"],
                        )
                    )

            if failed_updates or success_updates or generation_events:
                async with get_db() as db:
                    if failed_updates:
                        await db.executemany(
                            """UPDATE download_files
                               SET status=?, block_reason=?,
                                   updated_at=CURRENT_TIMESTAMP
                               WHERE id=?""",
                            failed_updates,
                        )
                    if success_updates:
                        await db.executemany(
                            """UPDATE download_files
                               SET filename=?, size_bytes=?, download_url=?,
                                   local_path=?, status='pending', block_reason=NULL,
                                   updated_at=CURRENT_TIMESTAMP
                               WHERE id=?""",
                            success_updates,
                        )
                    if generation_events:
                        await db.executemany(
                            "INSERT INTO events (torrent_id, level, message) VALUES (?, ?, ?)",
                            generation_events,
                        )
                    await db.commit()

'''
replace_between(manager, direct_start, direct_end, direct_replacement)

# Collapse /stats from a long sequence of scalar queries into one grouped query
# plus one conditional-aggregation query while preserving the response contract.
stats_start = '@router.get("/stats")\nasync def get_stats():\n'
stats_end = '\n\n@router.get("/stats/detail")\n'
stats_replacement = '''@router.get("/stats")
async def get_stats():
    started = time.monotonic()
    async with get_db() as db:
        by_status_rows = await db.fetchall(
            "SELECT status, COUNT(*) as count FROM torrents GROUP BY status"
        )
        by_status = {r["status"]: r["count"] for r in by_status_rows}

        last_24h_expr = _sql_now_minus("1 day")
        last_7d_expr = _sql_now_minus("7 days")
        aggregate = await db.fetchone(
            f"""SELECT
                   COALESCE(SUM(CASE WHEN status='completed' THEN size_bytes ELSE 0 END), 0)
                       AS total_completed_bytes,
                   SUM(CASE WHEN status IN ('downloading','processing','uploading','paused')
                            THEN 1 ELSE 0 END) AS active_downloads,
                   SUM(CASE WHEN status IN ('ready','queued') THEN 1 ELSE 0 END)
                       AS queued_downloads,
                   SUM(CASE WHEN status='downloading' THEN 1 ELSE 0 END)
                       AS operator_active_downloads,
                   AVG(CASE WHEN status='downloading' THEN COALESCE(progress, 0)
                            ELSE NULL END) AS operator_active_progress_pct,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_count,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_count,
                   SUM(CASE WHEN completed_at >= {last_24h_expr} THEN 1 ELSE 0 END)
                       AS completed_last_24h,
                   SUM(CASE WHEN completed_at >= {last_7d_expr} THEN 1 ELSE 0 END)
                       AS completed_last_7d,
                   AVG(CASE
                       WHEN completed_at IS NOT NULL AND created_at IS NOT NULL
                       THEN CAST((julianday(completed_at)-julianday(created_at))*86400 AS INTEGER)
                       ELSE NULL END) AS avg_download_duration_seconds,
                   AVG(CASE WHEN status='completed' AND size_bytes>0 THEN size_bytes
                            ELSE NULL END) AS avg_torrent_size_bytes,
                   (SELECT COUNT(*) FROM download_files WHERE blocked=1)
                       AS total_blocked_files
               FROM torrents"""
        ) or {}

    operator_active = int(aggregate.get("operator_active_downloads") or 0)
    operator_progress = None
    if operator_active > 0:
        average = float(aggregate.get("operator_active_progress_pct") or 0)
        operator_progress = max(0, min(100, round(average)))

    error_count = int(aggregate.get("error_count") or 0)
    completed_count = int(aggregate.get("completed_count") or 0)
    terminal = completed_count + error_count
    success_rate = (
        round(completed_count / terminal * 100, 1)
        if terminal > 0
        else None
    )

    env_db = os.getenv("DB_TYPE", "").strip()
    act_db = getattr(get_settings(), "db_type", "sqlite")
    db_type = (
        "sqlite_fallback"
        if act_db == "sqlite" and env_db == "postgres"
        else act_db
    )

    result = {
        "version": read_version(),
        "by_status": by_status,
        "total_completed_bytes": int(aggregate.get("total_completed_bytes") or 0),
        "db_type": db_type,
        "total_blocked_files": int(aggregate.get("total_blocked_files") or 0),
        "active_downloads": int(aggregate.get("active_downloads") or 0),
        "queued_downloads": int(aggregate.get("queued_downloads") or 0),
        "operator_active_downloads": operator_active,
        "operator_active_progress_pct": operator_progress,
        "error_count": error_count,
        "completed_count": completed_count,
        "success_rate_pct": success_rate,
        "completed_last_24h": int(aggregate.get("completed_last_24h") or 0),
        "completed_last_7d": int(aggregate.get("completed_last_7d") or 0),
        "avg_download_duration_seconds": int(
            aggregate.get("avg_download_duration_seconds") or 0
        ),
        "avg_torrent_size_bytes": int(aggregate.get("avg_torrent_size_bytes") or 0),
        "paused": bool(get_settings().paused),
    }
    from core.performance import observe
    observe("api.stats", time.monotonic() - started)
    return result
'''
replace_between(routes, stats_start, stats_end, stats_replacement)

# Expose process-local counters for staging profiling. No configuration values,
# URLs, provider tokens, or filenames are included.
perf_marker = "# ── Statistics ─────────────────────────────────────────────────────────────────\n"
perf_route = '''@router.get("/admin/performance")
async def performance_diagnostics():
    from core.performance import snapshot as performance_snapshot
    from db.database import db_runtime_metrics

    return {
        "timers": performance_snapshot(),
        "database": db_runtime_metrics(),
        "aria2": manager.aria2().rpc_metrics(),
    }


'''
replace_once(routes, perf_marker, perf_route + perf_marker)

# Keep immediate stats refreshes for state transitions, but throttle progress-only
# refreshes. Row progress remains incremental and immediate; aggregate KPIs/title
# catch up within 1.5 seconds instead of issuing one /stats query per SSE event.
sse_start = "        es.addEventListener(\n          'torrent_updated',\n"
sse_end = "\n        es.addEventListener(\n          'ping',\n"
sse_replacement = '''        var progressStatsTimer = null;

        es.addEventListener(
          'torrent_updated',
          function(e) {
            let payload = {};

            try {
              payload = JSON.parse(e.data || '{}');
            } catch (_) {}

            const patchedProgress =
              patchProgressOnlyTransferEvent(payload);

            if (!patchedProgress) {
              if (
                document
                  .getElementById('view-torrents')
                  ?.classList.contains('active')
              ) {
                loadTorrents().catch(()=>{});
              }

              if (
                document
                  .getElementById('view-dashboard')
                  ?.classList.contains('active')
              ) {
                loadRecent().catch(()=>{});
              }

              loadStats().catch(()=>{});
            } else if (!progressStatsTimer) {
              progressStatsTimer = setTimeout(
                ()=>{
                  progressStatsTimer = null;
                  loadStats().catch(()=>{});
                },
                1500
              );
            }
          }
        );
'''
replace_between(app, sse_start, sse_end, sse_replacement)

# The tab-title contract still requires an equal-weight average of active parent
# progress; update the static assertion to the equivalent conditional aggregate.
replace_once(
    scope_test,
    '''    assert "AVG(COALESCE(progress, 0)) AS average_progress" in routes
    assert "AS weighted_progress" not in routes
    assert "WHERE status='downloading'" in routes
''',
    '''    assert "AVG(CASE WHEN status='downloading' THEN COALESCE(progress, 0)" in routes
    assert "AS operator_active_progress_pct" in routes
    assert "AS weighted_progress" not in routes
''',
)

print("v1.0.4 surgical refactor applied")
