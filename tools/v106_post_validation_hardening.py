from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


# Remove capability URLs from every ensure_download diagnostic path, including
# short URLs that the generic URL sanitizer intentionally leaves readable.
replace_once(
    "backend/services/aria2.py",
    '''                                logger.warning("Removing stale duplicate aria2 entry %s for %s", dup.gid, normalized_uri)\n''',
    '''                                logger.warning("Removing stale duplicate aria2 entry %s for queued download", dup.gid)\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''                    logger.warning("Removing duplicate aria2 entry %s for %s", dup.gid, normalized_uri)\n''',
    '''                    logger.warning("Removing duplicate aria2 entry %s for queued download", dup.gid)\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''            last_error: Optional[Exception] = None\n            for attempt in range(1, max_retries + 1):\n''',
    '''            def safe_download_error(exc: BaseException) -> str:\n                # Strip the exact capability first; generic sanitization is then\n                # defense in depth rather than the capability boundary itself.\n                raw = str(exc).replace(normalized_uri, "<download-url>")\n                return sanitize_log_value(raw, max_length=200)\n\n            last_error: Optional[Exception] = None\n            for attempt in range(1, max_retries + 1):\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''                    logger.warning("aria2 unreachable (attempt %s/%s), retrying in %ss: %s", attempt, max_retries, delay, exc)\n                    await asyncio.sleep(delay)\n                except Aria2RPCError:\n                    raise\n''',
    '''                    logger.warning(\n                        "aria2 unreachable (attempt %s/%s), retrying in %ss: %s",\n                        attempt,\n                        max_retries,\n                        delay,\n                        safe_download_error(exc),\n                    )\n                    await asyncio.sleep(delay)\n                except Aria2RPCError as exc:\n                    logger.warning("aria2 rejected download request: %s", safe_download_error(exc))\n                    raise Aria2RPCError("aria2 rejected download request") from exc\n''',
)
replace_once(
    "backend/services/aria2.py",
    '''                    logger.warning(\n                        "Error queuing download (attempt %s/%s) for %s, retrying in %ss: %s",\n                        attempt,\n                        max_retries,\n                        sanitize_log_value(normalized_uri, max_length=120),\n                        delay,\n                        sanitize_log_value(exc, max_length=200),\n                    )\n                    await asyncio.sleep(delay)\n\n        safe_error = sanitize_log_value(last_error, max_length=200)\n        raise Aria2RPCError(\n            f"Unable to queue aria2 download after retries: {safe_error or 'unknown aria2 error'}"\n        )\n''',
    '''                    logger.warning(\n                        "Error queuing download (attempt %s/%s), retrying in %ss: %s",\n                        attempt,\n                        max_retries,\n                        delay,\n                        safe_download_error(exc),\n                    )\n                    await asyncio.sleep(delay)\n\n        error_type = type(last_error).__name__ if last_error is not None else "unknown error"\n        raise Aria2RPCError(f"Unable to queue aria2 download after retries ({error_type})")\n''',
)

# Use full UUID identities for new backup runs. Keep recognizing the prior
# second-only and short-UUID shapes so rotation remains backward compatible.
for path in ("backend/services/backup.py", "backend/services/db_maintenance.py"):
    replace_once(
        path,
        r'''_BACKUP_DIR_RE = re.compile(r"^\d{8}_\d{6}(?:_[0-9a-f]{8})?$")''',
        r'''_BACKUP_DIR_RE = re.compile(r"^\d{8}_\d{6}(?:_[0-9a-f]{8}|_[0-9a-f]{32})?$")''',
    )
    replace_once(
        path,
        '''uuid.uuid4().hex[:8]''',
        '''uuid.uuid4().hex''',
    )
    replace_once(
        path,
        '''    backup_dir.mkdir(parents=True, exist_ok=True)\n''',
        '''    backup_dir.mkdir(parents=True, exist_ok=False)\n''',
    )

# Make the regression deliberately use a short capability URL so success does
# not depend on the generic long-URL sanitizer heuristic.
replace_once(
    "backend/tests/test_v106_final_audit.py",
    '''    capability = "https://locked.example.invalid/download/" + ("capability-" * 20)\n''',
    '''    capability = "https://locked.example.invalid/cap"\n''',
)
replace_once(
    "backend/tests/test_v106_final_audit.py",
    '''        f"20260820_200000_{__import__('uuid').uuid4().hex[:8]}"\n''',
    '''        f"20260820_200000_{__import__('uuid').uuid4().hex}"\n''',
)

print("Applied post-validation capability/backup hardening")
