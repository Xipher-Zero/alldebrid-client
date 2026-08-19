# Internal fork state

## Base and purpose

This fork starts from upstream release `v1.9.9` at commit
`c0f7a5bfeba4f259fb2acc62ac6eed27e8ac4d5c`.

It converts a production-tested bind-mount override deployment into a normal
source repository. Runtime configuration, databases, API credentials, download
history, host-specific paths, and backup files are intentionally excluded.

## Initial divergence

The initial fork divergence was kept in two reviewable commits:

1. `Preserve internal v1.9.9 corrections`
   - persistent ownership tracking for downloads added to a shared external
     aria2 daemon;
   - ownership-aware control, removal, reconciliation, and deduplication;
   - no external-daemon global-option or download-history mutation;
   - bounded aria2 dispatch, startup recovery, parent progress aggregation,
     remote path handling, and memory/reconciliation corrections;
   - direct `.torrent` upload through AllDebrid;
   - stricter AllDebrid provider-response validation;
   - external-mode configuration preservation and UI/API corrections;
   - dashboard branding and favicon changes.
2. `Add direct debrid link downloads`
   - multi-URL dashboard submission above the magnet/torrent form;
   - tracked parent transaction and one child download per submitted URL;
   - AllDebrid immediate and delayed link generation;
   - automatic dispatch of generated HTTPS downloads to aria2;
   - lifecycle events, Recent Activity progress, retry, redownload, partial
     failure handling, and startup recovery;
   - persistent `download_files.source_url` migration so expiring generated
     URLs can be refreshed;
   - frontend cache invalidation and immediate `Adding…` feedback;
   - focused direct-link regression tests.

## Direct-link lifecycle

1. `POST /api/links/add` validates and persists up to 100 unique HTTP/HTTPS
   URLs as a `direct_link` transaction.
2. `/v4/link/unlock` resolves each hoster URL through AllDebrid.
3. A returned delayed ID is polled through `/v4/link/delayed` no more often
   than once every five seconds.
4. Successful files enter the existing ownership-aware aria2 dispatcher.
5. Existing synchronization updates queued, downloading, completed, and error
   states in Recent Activity and the event log.
6. Retry and recovery regenerate expiring URLs from the stored original URL.

## V1 cleanup

The V1 line removes inherited media-automation, indexer, saved-search, rules,
and qBittorrent-compatibility code. Current validation results belong in the
release notes and CI logs rather than this historical snapshot.

## Deployment

The repository builds as a normal source checkout:

```sh
docker compose build
docker compose up -d
```

Review and adapt the generic paths and environment values in
`docker-compose.yml` before deployment. Existing installations that use the
v1.9.9 image plus bind-mounted overrides can remain on that model until a
fork-owned image has been built and validated.

## Upstream and migration

Keep the original project configured as the `upstream` Git remote. The GitHub
fork should be `origin`. When the Codeberg repository is ready, add it as a
second push remote and transfer all branches and tags without rewriting this
history.

## Licensing provenance

Upstream release `v1.9.9` and commit
`c0f7a5bfeba4f259fb2acc62ac6eed27e8ac4d5c` were distributed under the MIT
License, copyright © 2026 kroeberd. That notice is preserved in `NOTICE` and
`LICENSES/MIT.txt`. DebridPulse modifications are copyright © 2026 Chris Moore and
licensed under GPL-2.0-or-later.
