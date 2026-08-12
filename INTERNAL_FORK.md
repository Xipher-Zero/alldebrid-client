# Internal fork state

## Base and purpose

This fork starts from upstream release `v1.9.9` at commit
`c0f7a5bfeba4f259fb2acc62ac6eed27e8ac4d5c`.

It converts a production-tested bind-mount override deployment into a normal
source repository. Runtime configuration, databases, API credentials, download
history, host-specific paths, and backup files are intentionally excluded.

## Commit organization

The fork divergence is kept in two reviewable commits:

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

## Validation

- Python syntax compilation passed for the changed backend modules.
- JavaScript syntax validation passed for `frontend/static/app.js`.
- Nine focused direct-link tests pass.
- A live 1fichier URL completed submission, AllDebrid generation, generated-URL
  retrieval, external aria2 dispatch, and active progress reporting.
- The inherited fork's legacy `test_manager_v2` result is unchanged from the
  pre-feature override baseline: 74 tests run with five failures and six errors.
  Those existing failures reflect stale upstream test mocks/expectations and a
  missing `asyncpg` dependency in the scratch verification environment.

Full completion/finalization of the first live direct-link download was not yet
observed when this snapshot was prepared.

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
