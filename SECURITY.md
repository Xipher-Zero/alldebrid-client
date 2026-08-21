# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ Yes     |
| < 1.0.0 | ❌ No      |

Only the latest release receives security fixes. Please update before reporting.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues through a private GitHub Security Advisory (preferred), or contact the maintainer through the repository profile. Include the vulnerability, reproduction steps, likely impact, and any suggested mitigation.

---

## Security Considerations

### Secrets and configuration

The AllDebrid API key, optional HTTP Basic Authentication password, Discord webhook URLs, aria2 credentials, and extraction passwords are secrets stored in `config/config.json`. Keep that file private:

```bash
chmod 600 config/config.json
```

Do not publish the config volume or commit it to version control. API responses intentionally redact configured secret values and capability-bearing provider/download URLs.

### Web UI and API access control

DebridPulse supports optional HTTP Basic Authentication in **Settings → General**. Authentication is disabled until credentials are configured. When enabled, state-changing cross-origin requests are rejected and credentials are compared using constant-time checks.

For any network you do not fully trust, enable DebridPulse authentication and/or place the application behind an authenticated reverse proxy such as Authentik, Authelia, or an equivalent access-control layer.

**Do not expose port 8080 directly to the public internet.** The generic Compose example uses bridge networking with an explicit port mapping so exposure remains visible and can be bound/restricted by the operator. Host networking should be an explicit deployment choice, not the generic default.

### Shared external aria2

External aria2 may be shared with unrelated applications. DebridPulse records ownership for GIDs it creates, permits per-GID mutations only for owned downloads, and avoids daemon-global mutation outside built-in aria2 mode. Keep aria2 RPC itself on a trusted network and configure its RPC secret when supported.

### Archive extraction

Archive extraction enforces member-path/type checks plus file-count, expanded-size, and compression-ratio budgets. External 7z/RAR extraction occurs in an isolated staging directory, is monitored while the extractor runs, and is validated again before files are merged into the download tree.

### Backups and database maintenance

Database wipe first closes and drains application mutation/execution admission, then suspends scheduler activity and drains provider/materialization work before holding an exclusive database-maintenance gate that rejects concurrent non-owner application DB sessions; it also fails closed if a required pre-wipe backup fails. The SQLite online-backup API may hold a separate read-only source connection, but it cannot mutate or repopulate the live database. Backup rotation only recursively removes DebridPulse-owned directories carrying the expected ownership manifest.

### Discord webhook URL

Treat Discord webhook URLs as secrets: possession of the URL permits posting to the configured channel.

---

## Scope

The following are **in scope** for security reports:

- secret or capability-bearing URL exposure;
- remote code execution;
- path traversal or unsafe archive extraction;
- authentication or authorization bypass;
- cross-origin state-changing request bypass;
- mutation of unrelated transfers on shared external aria2;
- unsafe destructive database/backup behavior.

The following are **out of scope**:

- issues in AllDebrid's own service/API;
- vulnerabilities that exist solely in an unmodified third-party dependency (report upstream as well);
- resource exhaustion requiring trusted local access with no network exposure, unless it crosses a documented DebridPulse safety boundary.
