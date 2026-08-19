# PostgreSQL Configuration

DebridPulse uses SQLite by default and can connect to an existing PostgreSQL
server. V1 does not bundle or manage a PostgreSQL sidecar.

## SQLite (default)

No database configuration is required. New installations use:

```text
/app/data/debridpulse.db
```

Existing installations that still have `/app/data/alldebrid.db` continue to
use it automatically when `DB_PATH` is not explicitly set. Set `DB_PATH` to
move or rename the database intentionally.

## External PostgreSQL

Open **Settings → Database**, select **PostgreSQL (external)**, and provide:

- the PostgreSQL server hostname or IP address;
- port (normally `5432`);
- database and user names;
- password;
- schema (normally `public`);
- TLS preference.

Use **Test DB** before relying on the new connection. A container using host
networking must use an address reachable from the Docker host; `localhost`
only works when PostgreSQL itself is listening on that same host.

Example settings payload:

```json
{
  "db_type": "postgres",
  "postgres_host": "192.168.1.10",
  "postgres_port": 5432,
  "postgres_db": "debridpulse",
  "postgres_user": "debridpulse",
  "postgres_password": "replace-me",
  "postgres_schema": "public",
  "postgres_ssl": false
}
```

If PostgreSQL is unavailable at startup, DebridPulse falls back to SQLite for
that run and reports the fallback in the Dashboard status. Restart after the
PostgreSQL server is reachable to reconnect.

## Migrating data

See [migration.md](migration.md) before changing an existing installation from
SQLite to PostgreSQL or back again. Keep a backup of both the application data
directory and the target database before migrating.
