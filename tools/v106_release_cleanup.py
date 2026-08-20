from pathlib import Path


def replace(path: str, old: str, new: str, *, count: int | None = None) -> None:
    target = Path(path)
    text = target.read_text()
    found = text.count(old)
    if found == 0:
        raise RuntimeError(f"expected text not found in {path}: {old[:120]!r}")
    if count is not None and found != count:
        raise RuntimeError(f"expected {count} match(es) in {path}, found {found}: {old[:120]!r}")
    target.write_text(text.replace(old, new))


replace("VERSION", "1.0.5\n", "1.0.6\n", count=1)
replace(
    "docker-compose.yml",
    "ghcr.io/xipher-zero/debridpulse:v1.0.5",
    "ghcr.io/xipher-zero/debridpulse:v1.0.6",
    count=1,
)
replace(
    "backend/tests/test_v105_deployment_hardening.py",
    'assert "ghcr.io/xipher-zero/debridpulse:v1.0.5" in compose',
    'assert "ghcr.io/xipher-zero/debridpulse:v1.0.6" in compose',
    count=1,
)
replace(
    "backend/tests/test_v105_performance_architecture.py",
    'assert (ROOT / "VERSION").read_text().strip() == "1.0.5"',
    'assert (ROOT / "VERSION").read_text().strip() == "1.0.6"',
    count=1,
)

replace(
    "README.md",
    "ghcr.io/xipher-zero/debridpulse:v1.0.0",
    "ghcr.io/xipher-zero/debridpulse:v1.0.6",
    count=2,
)
replace(
    "README.md",
    "### Extract\n\nConfigure optional archive extraction.\n",
    "### Extract\n\nConfigure optional archive extraction. DebridPulse enforces per-archive file-count, expanded-size, and compression-ratio limits. External 7z/RAR extraction is performed in an isolated staging directory and validated before files are merged into the download tree.\n",
    count=1,
)
replace(
    "README.md",
    """The primary implementation areas are:\n\n```text\nbackend/\n  api/\n    routes.py\n  services/\n    alldebrid.py\n    aria2.py\n    aria2_runtime.py\n    manager_v2.py\n  db/\n    database.py\n\nfrontend/static/\n  index.html\n  app.js\n  style.css\n```\n""",
    """The primary implementation areas are:\n\n```text\nbackend/\n  api/\n    routes.py\n    serializers.py\n  core/\n    scheduler.py\n  services/\n    transfer_service.py\n    transfer_repository.py\n    transfer_state_machine.py\n    transfer_control_service.py\n    dispatch_coordinator.py\n    reconciliation_service.py\n    provider_gateway.py\n    aria2_gateway.py\n    ownership_ledger.py\n    extraction_safety.py\n    manager_v2.py        # V1 provider/materialization implementation\n  db/\n    database.py\n\nfrontend/static/\n  index.html\n  app.js\n  style.css\n```\n""",
    count=1,
)

replace(
    "index.html",
    "Swagger UI at /api/docs.",
    "Swagger UI at /docs.",
    count=1,
)
replace(
    "index.html",
    '<div class="feat-card reveal"><div class="feat-icon">🗄️</div><div class="feat-title">SQLite or PostgreSQL</div><div class="feat-text">SQLite by default — zero config. Switch to external PostgreSQL via environment variable for multi-container setups.</div></div>',
    '<div class="feat-card reveal"><div class="feat-icon">🗄️</div><div class="feat-title">SQLite / WAL</div><div class="feat-text">A single SQLite/WAL database is the authoritative runtime store — persistent, self-contained, and zero-config.</div></div>',
    count=1,
)

changelog = """## [1.0.6] — 2026-08-20\n\n### Corrective architecture and security audit\n\n- Removed the transparent `TransferService.__getattr__` fallback and made application-visible provider, aria2, control, dispatch, reconciliation, extraction, notification, and persistence boundaries explicit.\n- Moved parent state persistence behind `TransferRepository`; `TransferStateMachine` now performs derivation and event publication without importing the database or HTTP layers.\n- Centralized external-aria2 mutation authorization at the gateway so foreign GIDs cannot be paused, resumed, or removed by DebridPulse.\n- Added browser-facing serializers that strip magnets, source/unlocked download URLs, and aria2 request URIs from ordinary API responses.\n- Hardened database wipe with verified transfer quiescence and fail-closed pre-wipe backup requirements.\n- Hardened backup rotation with DebridPulse ownership manifests so unrelated directories under a configured backup root are never recursively removed.\n- Added bounded request-body handling, baseline browser security headers, and retained same-origin mutation checks for Basic Auth browser sessions.\n- Added extraction file-count, expanded-size, and compression-ratio budgets; external 7z/RAR extraction now uses isolated staging plus pre/post validation before merging files into the destination.\n- Moved AllDebrid request rate limiting into the provider networking layer, including multipart uploads.\n- Reduced scheduler authority to one reconciliation loop, made scheduler lifecycle idempotent, and made recursive `/download` ownership repair explicit opt-in instead of startup behavior.\n- Removed the obsolete hidden Runtime Database settings card and synchronized release documentation, compose metadata, API docs paths, and SQLite-only product surfaces.\n\n## [1.0.5] — 2026-08-20\n\n### Architecture and release hardening\n\n- Introduced the explicit V1 service root and component boundaries for provider access, transfer persistence/state/control, dispatch, reconciliation, extraction, notifications, aria2 access, and ownership tracking.\n- Completed the SQLite-only runtime transition and promoted pause-intent and aria2-ownership state to first-class persisted schema.\n- Made live SQLite backups WAL-safe through the SQLite online-backup API and included operational tables in database exports and wipes.\n- Fixed scheduler and notification undefined-name/null-client failures, retained the dedicated added-download webhook, and added an undefined-name CI gate.\n- Added real-path media containment and same-origin mutation protection for authenticated browser sessions.\n- Preserved the v1.0.3/v1.0.4 pause, queue, reconciliation, source-retention, and shared-external-aria2 safety contracts through the architectural refactor.\n\n## [1.0.4] — 2026-08-20\n\n### Performance and reconciliation\n\n- Reused authoritative aria2 snapshots across reconciliation work, reduced redundant RPC/database work, and added hot SQLite indexes and instrumentation for the transfer cycle.\n- Coalesced progress/status updates and preserved incremental SSE behavior instead of forcing full UI refreshes.\n- Preserved external aria2 ownership filtering and safe grandfathering when live DebridPulse jobs exceed a newly lowered concurrency limit.\n- Retained durable selective pause intent, strict operator confirmation, deferred queue refill, and provider source-URL preservation while reducing reconciliation overhead.\n\n## [1.0.3] — 2026-08-20\n\n### Pause/resume reliability\n\n- Added durable selective pause intent distinct from observed aria2 state and strict fresh GID confirmation for operator pause/resume actions.\n- Defined Resume One under Pause All without allowing global pause to be bypassed, and kept no-slot resumed work queued rather than incorrectly user-paused.\n- Added missing-GID confirmation/negative caching so transient RPC/control snapshots cannot trigger destructive recovery.\n- Preserved completed siblings during lost-GID recovery when source URLs are known and retained provider source URLs before generated download URLs replace them.\n- Ensured external aria2 operations remain ownership-scoped and do not mutate unrelated daemon state.\n\n"""
replace(
    "CHANGELOG.md",
    "# Changelog\n\n## [1.0.2] — 2026-08-19\n",
    "# Changelog\n\n" + changelog + "## [1.0.2] — 2026-08-19\n",
    count=1,
)

print("v1.0.6 release metadata cleanup applied")
