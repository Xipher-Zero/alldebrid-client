# Authentication

DebridPulse 1.0.6 supports three authentication mechanisms while retaining intentional no-auth operation for trusted standalone/LAN deployments:

- **Username & Password** for browser sign-in, with the same credentials also available to REST clients through HTTP Basic authentication;
- **OpenID Connect (OIDC)** for browser sign-in through a standards-compliant identity provider;
- **API bearer token** for automation, Prometheus, scripts, and other machine clients.

Authentication is configured under **Settings → Authentication**. The normal application settings page no longer owns authentication controls.

## Deployment modes

The interactive authentication state is one of:

| Mode | Browser access | Machine access |
|---|---|---|
| No authentication | Open | API is open as well |
| Username & Password | DebridPulse login page | HTTP Basic; bearer token if configured |
| OIDC | OIDC login | Bearer token if configured |
| Username & Password + OIDC | OIDC is presented as the preferred path; local password remains available | HTTP Basic and/or bearer token |

The API token is supplemental. Configuring one does **not** create a separate API-token-only deployment mode, and it does not turn an intentionally open installation into a protected one.

## Username & Password

DebridPulse stores the local password only as an Argon2id verifier. The plaintext password is accepted only as transient input when setting or replacing the credential.

Browser users authenticate through the DebridPulse login page. REST clients may use the same credentials with standard HTTP Basic authentication:

```bash
curl -u operator:'your-password' https://debridpulse.example/api/stats
```

Changing or clearing the password invalidates password-derived browser sessions and the HTTP Basic verification cache. Disabling Username & Password immediately disables HTTP Basic and invalidates password-derived browser sessions. Disabling the mechanism does not erase the stored hash unless **Clear stored password** is explicitly selected.

## OpenID Connect

DebridPulse implements provider-neutral OpenID Connect Authorization Code flow with PKCE, state, nonce, issuer/audience validation, and server-side application sessions.

Configure at minimum:

- provider display name;
- issuer URL;
- client ID;
- client secret when required by the provider;
- scopes (normally `openid profile email`);
- canonical public base URL;
- authorization policy.

The public base URL must be the externally reachable HTTPS origin used by the identity provider, for example:

```text
https://debridpulse.example
```

The callback is derived from that origin:

```text
https://debridpulse.example/auth/oidc/callback
```

Register that exact callback URL with the identity provider.

### Authorization policy

OIDC authentication and DebridPulse authorization are separate checks. Configure either **Allow all authenticated identities** or one or more explicit allow lists for subject, email, or group claims. Group matching uses the configured group-claim name.

Do not enable OIDC without an authorization policy that matches the intended users.

### Lockout prevention

Enabling OIDC never silently disables a working local password.

Username & Password cannot be disabled in favor of OIDC until a **real OIDC login** has completed successfully. Discovery or a configuration-only HTTP check is not sufficient.

When OIDC is already the sole interactive mechanism, security-critical OIDC changes are staged as a pending configuration. The current known-working configuration remains authoritative until the proposed settings themselves complete a successful OIDC login. If verification fails, the previous configuration is retained unchanged.

Use **Verify Sign-In** in the Authentication settings tab after entering proposed OIDC changes.

## API bearer token

Generate the token under **Settings → Authentication → API Access**. Tokens use a recognizable `dp_...` format and are shown in full only once on generation or rotation.

The raw token is never persisted. DebridPulse stores only a SHA-256 verifier in `api-token.json` beside `config.json`, using restrictive file permissions where supported.

Use it as:

```bash
curl \
  -H 'Authorization: Bearer dp_REPLACE_WITH_TOKEN' \
  https://debridpulse.example/api/stats
```

Rotation immediately invalidates the previous token. Clearing removes the persisted verifier. Disabling bearer authentication retains the verifier so the same token can be re-enabled later; **Clear token** is the destructive operation.

When interactive authentication is enabled, request authentication precedence is:

1. valid DebridPulse application session;
2. explicit Bearer token;
3. explicit HTTP Basic credentials;
4. unauthenticated.

A valid browser application session therefore remains authoritative even if an intermediary unexpectedly adds another authorization header.

## Intentional open mode

Both Username & Password and OIDC may be deliberately disabled. Moving from an authenticated deployment into no-auth mode requires explicit confirmation because the application and REST API become unrestricted.

DebridPulse distinguishes intentional open mode from a broken configured authentication mechanism. A configured authentication failure must not cause the application to fail open.

## Browser sessions and CSRF

Successful local-password and OIDC browser logins both produce the same server-side DebridPulse application-session model. Sessions have an absolute lifetime configured in the Authentication tab.

State-changing requests made through an application session require the session CSRF token. Logout is a state-changing POST and revokes the server-side session.

Same-origin EventSource connections use the normal browser session cookie. REST requests that are not browser navigation receive ordinary HTTP authentication failures rather than identity-provider HTML.

## Reverse proxies

For OIDC deployments, terminate HTTPS at the public ingress and set **Public Base URL** to the canonical external origin. Ensure the proxy preserves the normal Host/protocol information expected by the deployment and does not rewrite the registered callback path.

DebridPulse does not require an external authentication proxy when its native Password/OIDC mechanisms are enabled. An external proxy may still be used as an additional perimeter control, but it should not be relied on to repair an intentionally misconfigured native authentication state.

## Configuration-file examples

The web UI is the supported configuration surface. The following JSON fragments document the persistent representation for recovery and automation; they are not a substitute for the lockout protections in the Authentication UI/API.

Password only:

```json
{
  "auth_password_enabled": true,
  "auth_username": "operator",
  "auth_password_hash": "$argon2id$...",
  "auth_oidc_enabled": false,
  "auth_session_lifetime_hours": 12
}
```

OIDC plus Password fallback:

```json
{
  "auth_password_enabled": true,
  "auth_username": "operator",
  "auth_password_hash": "$argon2id$...",
  "auth_oidc_enabled": true,
  "oidc_provider_name": "Authentik",
  "oidc_issuer_url": "https://id.example/application/o/debridpulse",
  "oidc_client_id": "debridpulse",
  "oidc_client_secret": "REDACTED",
  "oidc_scopes": ["openid", "profile", "email"],
  "oidc_allow_all": false,
  "oidc_allowed_emails": ["operator@example.com"],
  "public_base_url": "https://debridpulse.example"
}
```

Do not copy a password hash or client secret into documentation, logs, bug reports, or screenshots. The API token verifier is stored separately in `api-token.json`; never place the raw bearer token in `config.json`.
