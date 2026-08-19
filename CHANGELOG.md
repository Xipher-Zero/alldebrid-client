# Changelog

## [1.0.2] — 2026-08-19

### Responsiveness

- Kept top-bar Pause/Resume controls as stable DOM nodes so live refreshes cannot replace them during a click.
- Added immediate pressed/pending feedback for queue controls and opened transfer details before the API round trip completes.
- Coalesced overlapping stats, recent-activity, and download-list refreshes.
- Added incremental SSE progress updates so progress-only events no longer rebuild entire clickable tables.
- Returned authoritative settings from `PUT /settings` and removed redundant follow-up settings reads.
- Added frontend cache-busting and regression coverage for the responsiveness contract.
- Reduced no-op provider/aria2 database writes and SSE churn so transfer freshness reflects real progress.
- Preserved local aria2 transfer status, progress, and size while AllDebrid is already in the ready state so provider reconciliation cannot overwrite live local telemetry.
- Removed redundant aria2 queue fetches, debounced download search input, and scoped download filters to their own view.

## [1.0.1] — 2026-08-19

### Hotfix

- Restored the upper-right live aria2 telemetry indicator when using an external aria2 daemon.
- External mode now shows DebridPulse-owned active transfers and live download speed while clearly marking the bandwidth cap as **Externally Controlled**.
- Restored live download speed in the active browser-tab title for external aria2.
- Prevented unrelated jobs on a shared external aria2 daemon from appearing in DebridPulse telemetry or the live aria2 queue.
- Preserved the external-daemon safety boundary: DebridPulse does not modify daemon-global bandwidth limits in external mode.


## [1.0.0] — 2026-08-19

### DebridPulse identity

- Finalized the V1 product name as **DebridPulse**.
- Standardized the repository, container, service, and image name as `debridpulse`.
- Set browser and notification identity to `DebridPulse` and API/OCI metadata to **DebridPulse — Multi-provider Debrid Download Manager**.
- Added startup migration from the transitional ACDC identity and prior AllDebrid client names while preserving custom user-supplied identities.
- Corrected the project landing page to describe the pruned V1 feature set and GPL-2.0-or-later license.

### Direct debrid links

- Added tracked direct-link transfers for ordinary hoster URLs using the existing AllDebrid account and aria2 delivery path.
- Added newline-separated multi-link submission from the dashboard, with the input expanding to five visible lines and returning to its compact height after submission.
- Added deterministic recovery and retry for interrupted direct-link batches while retaining the original source URLs locally.
- Added explicit missing-file handling for links that AllDebrid reports as no longer available on the source host.
- Preserved successful files when a multi-link batch completes with a mixture of successful and failed entries.

### Queue and delivery control

- Reworked Pause/Resume semantics so global pause, selective per-transfer pause, and queue dispatch remain distinct states.
- Added slot-based aria2 dispatch that treats paused transfers as not consuming active download slots.
- Added explicit **Download Now** priority control for ready/pending transfers.
- Improved startup reconciliation and recovery when aria2 jobs are missing, removed, duplicated, or already complete.
- Added ownership tracking for aria2 GIDs so DebridPulse only controls jobs it created when connected to a shared external aria2 daemon.
- Added external aria2 safety behavior that avoids daemon-global tuning and cleanup outside DebridPulse-owned jobs.

### Interface and observability

- Added live active-download speed and queue progress to the browser tab title.
- Added an upper-right aria2 telemetry/control surface for active count, max concurrent downloads, live speed, and bandwidth cap.
- Added responsive light/dark themes, revised tab presentation, and final DebridPulse branding/icons.
- Added dashboard activity controls for pausing/resuming transfers without exposing destructive removal there.
- Added live SSE-driven status refresh with polling fallback.
- Added explicit source labels for direct links, magnets, torrent files, imports, and API submissions.

### Scope and compatibility

- Removed unscoped V1 services, routes, settings, and documentation for qBittorrent, search/indexer automation, watch-folder ingestion, and the broken internal PostgreSQL sidecar mode.
- Preserved SQLite as the default database and external PostgreSQL as the supported optional database backend.
- Preserved existing V1 upgrade paths and legacy configuration compatibility where doing so does not reintroduce removed product surface.

### Security and licensing

- Hardened ZIP extraction against path traversal and symlink archive members.
- Updated runtime/development dependencies and refreshed lock files.
- Added license-policy tests and bundled dependency license inventory.
- Standardized the project license as **GPL-2.0-or-later** while preserving upstream MIT attribution, the upstream license text, source-offer information, and dependency notices.
