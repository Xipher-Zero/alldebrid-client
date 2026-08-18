<div align="center">
  <img src="docs/logo.svg" width="96" alt="DebridPulse Logo"/>
  <h1>DebridPulse</h1>
  <p><strong>A self-hosted AllDebrid download client for direct links, magnets, and torrent files.</strong><br/>AllDebrid processing · aria2 downloads · unified transfer tracking · recovery · observability</p>

  [![License](https://img.shields.io/github/license/Xipher-Zero/debridpulse?style=flat-square)](LICENSE)
  [![Tests](https://img.shields.io/github/actions/workflow/status/Xipher-Zero/debridpulse/tests.yml?style=flat-square&label=tests)](https://github.com/Xipher-Zero/debridpulse/actions/workflows/tests.yml)
  [![Image](https://img.shields.io/github/actions/workflow/status/Xipher-Zero/debridpulse/fork-image.yml?style=flat-square&label=image)](https://github.com/Xipher-Zero/debridpulse/actions/workflows/fork-image.yml)
</div>

---

## What is DebridPulse?

**DebridPulse** is a self-hosted debrid download manager for direct links, magnet links, and `.torrent` files. V1 submits work through AllDebrid and manages the resulting transfers through aria2.

The normal workflow is intentionally simple:

1. Submit an ordinary HTTP/HTTPS hoster link, magnet link, or `.torrent` file.
2. DebridPulse sends it to AllDebrid for unlocking or torrent processing.
3. AllDebrid produces downloadable HTTP(S) file URLs.
4. DebridPulse dispatches those files to aria2.
5. The resulting transfer is tracked through the Dashboard, Downloads view, statistics, and event log.
6. Failed or expired transfers can be retried or recovered without rebuilding the download manually.

DebridPulse can manage its own built-in aria2 instance or safely use a shared external aria2 daemon.

---

## Core features

| Feature | Description |
|---|---|
| **Direct debrid links** | Submit ordinary HTTP/HTTPS links from AllDebrid-supported hosts directly from the Dashboard |
| **Batch link submission** | Submit up to 100 unique direct links in one tracked transaction |
| **Magnet links** | Submit one or more magnets through AllDebrid |
| **Torrent files** | Upload `.torrent` files directly to AllDebrid |
| **Delayed link generation** | Automatically handles AllDebrid links that require asynchronous generation |
| **Built-in aria2** | Run DebridPulse with its bundled aria2 instance for a self-contained deployment |
| **External aria2** | Connect to an existing aria2 JSON-RPC daemon |
| **Shared aria2 safety** | Tracks DebridPulse-owned downloads and avoids modifying global settings, result history, or unrelated transfers on external aria2 instances |
| **Unified Downloads view** | Direct links, magnets, torrent files, and imported transfers share one lifecycle and history |
| **Recent Activity** | Dashboard view of active and recently processed downloads |
| **Retry and recovery** | Retry failed transfers and regenerate expired AllDebrid download URLs from the original source |
| **Import existing magnets** | Import AllDebrid magnets not yet represented in the local database |
| **Live status updates** | Server-Sent Events carry the application's pulse without requiring full-page polling |
| **Event log** | Searchable transfer and application event history |
| **Statistics and analytics** | Built-in operational and download statistics |
| **Auto-extraction** | Optional post-download extraction of common archive formats |
| **Notifications** | Optional Discord notifications for download lifecycle events |
| **Prometheus metrics** | Application and transfer metrics through `/api/metrics` |
| **SQLite or PostgreSQL** | SQLite by default with optional external PostgreSQL |
| **Access control** | Optional HTTP Basic Authentication |

---

## Direct-link downloads

Direct hoster links are first-class DebridPulse transfers rather than untracked aria2 jobs.

Paste one or more HTTP/HTTPS links into the direct-link field on the Dashboard. DebridPulse then:

1. validates and records the original URL;
2. asks AllDebrid to unlock the link;
3. waits for delayed generation when required;
4. records the generated file information;
5. submits the generated download URL to aria2;
6. tracks progress with the rest of the download queue.

The original source URL is retained. If an AllDebrid-generated URL expires, DebridPulse can generate a new one during retry or recovery.

A single submission can contain up to **100 unique links**.

---

## Torrent downloads

DebridPulse supports both magnet links and `.torrent` files.

For a torrent submission:

1. the magnet or torrent metadata is sent to AllDebrid;
2. DebridPulse monitors the AllDebrid torrent state;
3. once files are available, their unlocked HTTP(S) links are retrieved;
4. those files are dispatched to aria2;
5. DebridPulse tracks the complete transfer lifecycle locally.

The local aria2 daemon does **not** need to participate in BitTorrent swarms. AllDebrid performs the torrent-side work and aria2 downloads the resulting files.

---

## aria2 modes

### Built-in aria2

The default configuration can run a bundled aria2 instance controlled by DebridPulse.

In this mode DebridPulse owns the daemon and can manage its runtime configuration.

### External aria2

DebridPulse can instead use an existing aria2 JSON-RPC endpoint.

External mode is designed to be safe for a **shared aria2 daemon**. DebridPulse maintains ownership information for downloads that it creates and does not assume that every transfer in aria2 belongs to DebridPulse.

In external mode DebridPulse intentionally avoids operations such as:

- changing daemon-wide bandwidth limits;
- rewriting global aria2 configuration;
- purging global download-result history;
- controlling unrelated aria2 GIDs.

Application-level concurrency for DebridPulse-owned jobs remains independently configurable.

---

## Installation

### Docker Compose

Clone the repository:

```bash
git clone https://github.com/Xipher-Zero/debridpulse.git
cd debridpulse
```

Review `docker-compose.yml` before starting it. Adapt host paths, UID/GID, timezone, networking, and persistent storage to your environment.

Then start DebridPulse:

```bash
docker compose up -d
```

Open:

```text
http://your-server:8080
```

Go to **Settings → General** and configure your AllDebrid API key.

### Docker image

Fork-owned images are published to GHCR.

Current version:

```text
ghcr.io/xipher-zero/debridpulse:internal-v0.9.4
```

Example:

```bash
docker run -d \
  --name debridpulse \
  --restart unless-stopped \
  -p 8080:8080 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=America/Phoenix \
  -e CONFIG_PATH=/app/config/config.json \
  -e DB_PATH=/app/data/alldebrid.db \
  -v /path/to/debridpulse/config:/app/config \
  -v /path/to/debridpulse/data:/app/data \
  -v /path/to/downloads:/downloads \
  ghcr.io/xipher-zero/debridpulse:internal-v0.9.4
```

Adjust the paths and UID/GID for your system.

---

## Configuration

The primary supported configuration is available through **Settings**.

### General

Configure:

- AllDebrid API key;
- AllDebrid agent name;
- optional HTTP Basic Authentication.

### Download

Configure:

- download directory;
- built-in or external aria2 mode;
- external aria2 URL and authentication when applicable;
- DebridPulse download concurrency;
- download filtering and limits.

### Extract

Configure optional archive extraction.

### Notifications

Configure optional Discord lifecycle notifications.

### Database

Use the default SQLite database or configure an external PostgreSQL instance.

### Advanced

Additional application and operational settings are available here.

---

## Dashboard

The Dashboard is intended for current activity and common download submission.

It provides:

- direct-link submission;
- magnet and `.torrent` submission;
- import and recovery controls;
- current queue state;
- completion and error counts;
- recent download activity.

The Dashboard intentionally shows only a small Recent Activity window. Use **Downloads** for full transfer history and management.

---

## Downloads

The **Downloads** view is the unified transfer history.

It includes transfers originating from:

- direct debrid links;
- magnets;
- `.torrent` files;
- imported AllDebrid entries;
- supported API submissions.

Transfers can be searched and filtered by state, with retry, reset, pause, resume, and delete controls available where applicable.

---

## REST API

DebridPulse exposes a REST API used by the web interface and available for external automation.

### Download submission and management

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/links/add` | Submit one or more direct HTTP/HTTPS links |
| `POST` | `/api/torrents/add-magnet` | Submit a magnet link |
| `POST` | `/api/torrents/add-file` | Upload a `.torrent` file |
| `GET` | `/api/torrents` | List tracked downloads |
| `GET` | `/api/torrents/{id}` | Retrieve a tracked download |
| `DELETE` | `/api/torrents/{id}` | Delete a tracked download |
| `POST` | `/api/torrents/{id}/retry` | Retry a failed download |
| `POST` | `/api/torrents/import-existing` | Import existing AllDebrid magnets |
| `POST` | `/api/torrents/recover-all` | Recover eligible stuck or failed transfers |
| `GET` | `/api/torrents/diagnose` | Return transfer-state diagnostics |

### Application state

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stats` | Application and transfer statistics |
| `GET` | `/api/settings` | Current application settings |
| `PUT` | `/api/settings` | Update application settings |
| `GET` | `/api/events/stream` | Server-Sent Events status stream |
| `GET` | `/api/metrics` | Prometheus-compatible metrics |
| `GET` | `/api/version` | DebridPulse version |
| `GET` | `/api/health` | Lightweight application health endpoint |

---

## V1 scope boundary

DebridPulse began as a fork of `kroeberd/alldebrid-client` v1.9.9. V1 removes the inherited media-automation and indexer surface, including:

- qBittorrent API emulation;
- Sonarr/Radarr integration;
- Jackett/Prowlarr search;
- FlexGet;
- saved-search and automation systems.

Their routes, services, scheduler jobs, configuration, UI, database tables, and dependencies are not part of the V1 application. DebridPulse is a **debrid download manager**, not an all-in-one media automation suite.

---

## Fork history

DebridPulse is derived from upstream `kroeberd/alldebrid-client` release **v1.9.9**, commit:

```text
c0f7a5bfeba4f259fb2acc62ac6eed27e8ac4d5c
```

The fork initially preserved production corrections around AllDebrid processing and shared external aria2 operation, then added tracked direct-link downloading and began simplifying the user interface around the actual AllDebrid download workflow.

See [`INTERNAL_FORK.md`](INTERNAL_FORK.md) for historical notes about the initial divergence.

See [`CHANGELOG.md`](CHANGELOG.md) for current DebridPulse changes.

---

## Development

Backend requirements are under `backend/`.

```bash
cd backend
pip install -r requirements.txt
python -m pytest tests -v
```

Run the development server with:

```bash
uvicorn main:app --reload --port 8080
```

The primary implementation areas are:

```text
backend/
  api/
    routes.py
  services/
    alldebrid.py
    aria2.py
    aria2_runtime.py
    manager_v2.py
  db/
    database.py

frontend/static/
  index.html
  app.js
  style.css
```

---

## Project direction

DebridPulse favors a focused responsibility:

> **Submit work to AllDebrid, retrieve the resulting files, download them reliably, and make that lifecycle observable and recoverable.**

Features that improve that workflow belong naturally in DebridPulse. Provider-specific integrations belong behind the DebridPulse provider layer; V1 uses AllDebrid as its provider backend.

Recreating an entire media-management or indexer ecosystem inside the download client does not.

---

## License

DebridPulse modifications are copyright © 2026 Chris Moore and are distributed under
[`GPL-2.0-or-later`](LICENSE). The upstream MIT copyright and permission notice
are preserved in [`NOTICE`](NOTICE) and [`LICENSES/MIT.txt`](LICENSES/MIT.txt).
Runtime dependency licensing is inventoried in
[`docs/DEPENDENCY_LICENSES.md`](docs/DEPENDENCY_LICENSES.md).
