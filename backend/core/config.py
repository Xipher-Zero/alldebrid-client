import json
import logging
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from auth.passwords import hash_password
from core.branding import APP_SHORT_NAME

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/app/config/config.json"))
logger = logging.getLogger("alldebrid.config")


class AppSettings(BaseModel):
    # AllDebrid
    alldebrid_api_key: str = ""
    alldebrid_agent: str = APP_SHORT_NAME

    # Logging
    log_level: str = "INFO"
    log_pretty: bool = False
    log_format: str = "plain"

    # Persistence — SQLite is the only runtime database.

    # Download control
    download_folder: str = "/download"
    max_concurrent_downloads: int = 3
    max_speed_mbps: int = 0
    aria2_max_download_limit: int = 0  # bytes/s, 0=unlimited — persisted across restarts
    aria2_max_upload_limit: int = 0    # bytes/s, 0=unlimited

    # Download delivery
    download_client: str = "aria2"
    aria2_mode: str = "builtin"  # built-in is the default; no extra setup required
    aria2_url: str = "http://127.0.0.1:6800/jsonrpc"
    aria2_secret: str = ""
    aria2_download_path: str = ""
    aria2_builtin_auto_start: bool = True
    aria2_builtin_port: int = 6800
    aria2_builtin_log_file: str = "/app/data/aria2/aria2.log"
    aria2_builtin_log_max_mb: int = 25
    aria2_builtin_log_backups: int = 3
    aria2_builtin_session_file: str = "/app/data/aria2/aria2.session"
    aria2_operation_timeout_seconds: int = 15
    aria2_start_paused: bool = False
    aria2_poll_interval_seconds: int = 2  # validated scheduler cadence
    aria2_max_active_downloads: int = 3
    aria2_purge_interval_minutes: int = 5  # purge completed results more often to free RAM
    aria2_max_download_result: int = 20  # lower = less RAM for completed download metadata
    aria2_keep_unfinished_download_result: bool = False
    aria2_waiting_window: int = 100
    aria2_stopped_window: int = 100
    aria2_split: int = 16             # segments per file — more = faster on fast connections
    aria2_min_split_size: str = "10M"  # split files >40 MB with split=16 (aria2 default)
    aria2_max_connection_per_server: int = 16  # parallel connections per server
    aria2_disk_cache: str = "64M"  # 64 MiB write buffer; reduces FUSE/NFS round-trips and syscall overhead
    aria2_file_allocation: str = "falloc"  # prealloc disk space for fewer write syscalls; use 'none' on FUSE/NFSa2
    aria2_continue_downloads: bool = True
    aria2_lowest_speed_limit: str = "0"

    # Discord
    discord_webhook_url: str = ""
    discord_webhook_added: str = ""
    discord_username: str = APP_SHORT_NAME
    discord_avatar_url: str = ""  # Discord only accepts PNG/JPG/WEBP — SVG rejected
    discord_notify_added: bool = True
    discord_notify_finished: bool = True
    discord_notify_error: bool = True
    discord_notify_update: bool = True

    # Filters
    filters_enabled: bool = False
    blocked_extensions: List[str] = [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
        ".svg", ".ico", ".tiff", ".heic", ".nfo", ".sfv"
    ]
    blocked_keywords: List[str] = []
    min_file_size_mb: int = 0

    # ── Smart File Selection ──────────────────────────────────────────────────
    # Automatically block sample files, extras, and featurettes.
    # Works alongside blocked_keywords — enabling this adds the most common
    # sample/extra patterns without requiring manual keyword configuration.
    block_samples:    bool = False   # block files matching common sample patterns
    block_extras:     bool = False   # block extras / featurettes / behind-the-scenes

    # ── Advanced Extraction ───────────────────────────────────────────────────
    # Optional password applied to all archive extractions (7z -p and unrar -p).
    # Leave empty if archives are not password-protected.
    extraction_password: str = ""

    # Deep aria2 filesystem sync
    # Interval in minutes (0 = disabled). Checks actual file presence on disk
    # independently of aria2 GID/status, resolving same-filename-different-folder issues.
    aria2_deep_sync_interval_minutes: int = 10
    # Periodic built-in aria2 restart to reclaim glibc malloc arena memory.
    # aria2 uses glibc malloc which retains freed pages in arenas even with
    # MALLOC_ARENA_MAX=1. A periodic restart fully resets the process heap.
    # Set to 0 to disable. Downloads are recovered from DB within 1 poll cycle.
    aria2_restart_interval_hours: float = 0  # 0 = disabled; recommended: 4-8h
    # disk-cache for built-in aria2. Set to 0 for native filesystems (ext4/XFS).
    # Set to 16M or higher for FUSE-based mounts (mergerfs, NFS, SMB) to reduce
    # FUSE round-trips and actually lower aria2 heap usage.

    # Polling
    poll_interval_seconds: int = 30
    paused: bool = False

    # Rate limiting — AllDebrid API calls per minute (0 = unlimited)
    alldebrid_rate_limit_per_minute: int = 60

    # Auto-recover stalled downloads
    # Transfers stuck in queued/downloading for longer than this are reset (0 = disabled)
    stuck_download_timeout_hours: int = 6
    # Full AllDebrid reconciliation interval (minutes) — syncs ALL torrents incl. error/queued
    full_sync_interval_minutes: int = 5

    # Backups
    backup_enabled: bool = True
    backup_folder: str = "/app/data/backups"
    backup_keep_days: int = 7
    backup_interval_hours: int = 24

    # Database maintenance
    db_backup_enabled: bool = True
    db_backup_folder: str = "/app/data/db-backups"
    db_backup_keep_days: int = 7
    db_wipe_enabled: bool = False
    db_backup_before_wipe: bool = True

    # Post-download extraction
    extract_enabled: bool = False          # auto-extract archives after download
    extract_delete_archive: bool = True    # delete archive after successful extraction
    extract_max_concurrent: int = 1        # max parallel extractions
    extract_max_files: int = 20000          # archive member ceiling
    extract_max_expanded_gb: float = 250.0  # expanded bytes per archive
    extract_max_compression_ratio: float = 1000.0  # expanded/archive size
    discord_notify_extract: bool = True    # Discord notification after extraction

    # AllDebrid upload retry (statusCode 5 = upload failed)
    upload_fail_retry_count: int = 3   # max retries for statusCode 5
    upload_fail_retry_delay_minutes: int = 5  # minutes between retries

    # aria2 download retry on error
    # How many times to retry a failed aria2 download before giving up (0 = no retry)
    aria2_error_retry_count: int = 3
    # Seconds to wait between retries
    aria2_error_retry_delay_seconds: int = 60

    # Labels / categories (comma-separated, empty = disabled)
    torrent_labels: List[str] = []

    # ── Statistics & Reporting ────────────────────────────────────────────────
    # How often to take a stats snapshot (minutes, 0 = disabled)
    stats_snapshot_interval_minutes: int = 60
    # How many days to keep snapshots
    stats_snapshot_keep_days: int = 30
    # Auto-report: interval in hours (0 = disabled)
    stats_report_interval_hours: int = 0
    update_check_interval_hours: int = 12
    # Report window in hours used for manual default display and scheduled reports
    stats_report_window_hours: int = 24
    # Webhook URL that receives automated reporting payloads
    stats_report_webhook_url: str = ""

    # ── Event log TTL ─────────────────────────────────────────────────────────
    # How many days to keep event log entries (0 = keep forever).
    # Only events are pruned — torrent rows are NEVER deleted by TTL, so
    # the unique hash constraint and status fields remain intact and prevent
    # duplicate downloads from being started.
    events_keep_days: int = 30

    # ── Authentication ────────────────────────────────────────────────────────
    # Username & Password is an explicit mechanism. auth_password is retained
    # only as transient legacy/settings input and is never persisted after
    # migration; auth_password_hash is the authoritative stored verifier and is
    # excluded from normal model serialization.
    auth_password_enabled: bool = False
    auth_username: str = ""
    auth_password_hash: str = Field(default="", exclude=True)
    auth_password: str = ""
    # Browser application sessions use absolute expiration, not sliding expiry.
    auth_session_lifetime_hours: int = 12

    # ── Disk space guard ─────────────────────────────────────────────────────
    # Minimum free disk space required (GB) on the download folder's filesystem.
    # 0 = disabled.
    #
    # When free space drops below this threshold:
    #   - New aria2 dispatches are deferred (not errored)
    #   - Transfers already active in aria2 are allowed to finish
    #
    # When free space rises back above threshold + 0.5 GB hysteresis:
    #   - Deferred dispatch resumes automatically
    #
    # Checked every disk_guard_interval_seconds (default 60 s) — not on every
    # poll cycle — to avoid excessive stat() calls on FUSE/NFS mounts.
    #
    # Compatible with all filesystems: ext4, XFS, ZFS, Btrfs, FUSE, NFS,
    # Unraid's FUSE/shfs, and Windows (shutil fallback).
    min_free_disk_gb: float = 0

    # How often (seconds) to check free disk space. 30–120 is sensible.
    # Lower values = more responsive but more stat() calls on FUSE/NFS.
    disk_guard_interval_seconds: int = 60

    # Hysteresis: resume paused downloads only when free space exceeds
    # min_free_disk_gb + disk_guard_resume_hysteresis_gb to prevent flapping.
    disk_guard_resume_hysteresis_gb: float = 0.5

_settings: AppSettings = AppSettings()


def _build_effective_settings(loaded: dict) -> AppSettings:
    return AppSettings(**{k: v for k, v in loaded.items() if k in AppSettings.model_fields})


def _migrate_password_settings(loaded: dict) -> bool:
    """Migrate legacy plaintext Basic credentials to the owned password model."""
    changed = False
    auth_state_present = any(
        field in loaded
        for field in ("auth_password_enabled", "auth_username", "auth_password_hash", "auth_password")
    )
    legacy_enable_semantics = "auth_password_enabled" not in loaded
    username = str(loaded.get("auth_username") or "").strip()
    plaintext = str(loaded.get("auth_password") or "")
    password_hash = str(loaded.get("auth_password_hash") or "").strip()

    if plaintext:
        if username and not password_hash:
            loaded["auth_password_hash"] = hash_password(plaintext)
            password_hash = loaded["auth_password_hash"]
        loaded["auth_password"] = ""
        changed = True

    if auth_state_present and legacy_enable_semantics:
        loaded["auth_password_enabled"] = bool(username and (password_hash or plaintext))
        changed = True

    return changed


def get_settings() -> AppSettings:
    return _settings


def load_settings() -> AppSettings:
    loaded: dict = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            loaded = {k: v for k, v in data.items() if k in AppSettings.model_fields}
        except Exception as exc:
            logger.warning("Config file could not be read (%s) — using defaults", exc)

    # ── Performance migration: built-in aria2 only ──────────────────────────
    # External mode targets a shared daemon. Its explicitly stored transfer
    # values must be preserved exactly; they are ADC job policy, not defaults
    # that a migration may silently reinterpret.
    if loaded.get("aria2_mode", "builtin") == "builtin":
        _PERF_UPGRADES = {
            "aria2_split":                     (4, 8, 16),
            "aria2_max_connection_per_server": (4, 8, 16),
        }
        for field, (old_low, old_mid, new_val) in _PERF_UPGRADES.items():
            stored = loaded.get(field)
            if stored in (old_low, old_mid):
                logger.info(
                    "Config migration: %s %s → %s (performance upgrade)",
                    field,
                    stored,
                    new_val,
                )
                loaded[field] = new_val

    password_migrated = _migrate_password_settings(loaded)
    settings = _build_effective_settings(loaded)
    if password_migrated:
        try:
            save_settings(settings)
            logger.info("Config migration: local authentication password stored as Argon2id hash")
        except Exception as exc:
            logger.warning("Password migration could not be persisted: %s", exc)
    return settings


def save_settings(s: AppSettings):
    """Atomically persist configuration with secret-safe filesystem permissions."""
    global _settings
    plaintext = str(getattr(s, "auth_password", "") or "")
    if plaintext:
        s.auth_password_hash = hash_password(plaintext)
        s.auth_password = ""
    elif not str(getattr(s, "auth_password_hash", "") or "").strip():
        s.auth_password_hash = str(getattr(_settings, "auth_password_hash", "") or "")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_PATH.parent, 0o700)
    except OSError:
        pass
    data = s.model_dump()
    data.pop("auth_password", None)
    data["auth_password_hash"] = str(getattr(s, "auth_password_hash", "") or "")
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def apply_settings(s: AppSettings):
    global _settings
    _settings = s


_settings = load_settings()
settings = _settings
