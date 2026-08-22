/* DebridPulse 1.0.6 authentication help augmentation. */
(() => {
  'use strict';

  function findDetails(panel, summaryText) {
    if (!panel) return null;
    return Array.from(panel.querySelectorAll('details')).find(details => {
      const summary = details.querySelector('summary');
      return summary && summary.textContent.trim() === summaryText;
    }) || null;
  }

  function installAuthenticationReference() {
    const panel = document.getElementById('htab-settings');
    if (!panel) return;

    const general = findDetails(panel, 'General');
    if (general) {
      const body = general.querySelector('div');
      if (body) {
        body.innerHTML = `
          <b>AllDebrid API Key</b> — Required. Get it at alldebrid.com/apikeys.<br>
          <b>Authentication</b> — Configure native access control under <b>Settings → Authentication</b>, not General. Intentional no-auth operation remains supported for trusted LAN/standalone deployments.<br>
        `;
      }
    }

    if (findDetails(panel, 'Authentication')) return;

    const reference = document.createElement('details');
    reference.style.marginBottom = '10px';
    reference.innerHTML = `
      <summary style="cursor:pointer;font-weight:600;color:var(--text1);font-size:13px">Authentication</summary>
      <div style="padding:6px 0 0 12px">
        <b>Username &amp; Password</b> — Browser users sign in through the DebridPulse login page. REST clients may use HTTP Basic with the same credentials. Passwords are stored only as Argon2id verifiers.<br>
        <b>OpenID Connect</b> — Provider-neutral Authorization Code + PKCE login. Configure the HTTPS Public Base URL and register the derived <code>/auth/oidc/callback</code> URL with the IdP. On a fresh/open installation, enable Username &amp; Password as a temporary fallback first, sign in locally, then use <b>Verify Sign-In</b> to prove the real provider flow before relying on OIDC-only access.<br>
        <b>API Access</b> — Generate a <code>dp_…</code> bearer token for automation, Prometheus, and scripts. The full token is shown once; only a one-way verifier is persisted. Rotation invalidates the old token immediately.<br>
        <b>Lockout prevention</b> — An unproven OIDC configuration cannot become the first and only interactive mechanism. Password cannot be disabled in favor of OIDC until a real OIDC login succeeds. Critical OIDC changes in OIDC-only mode remain pending until the proposed configuration completes a successful login. Disabling all interactive authentication requires explicit open-mode confirmation.<br>
      </div>
    `;

    if (general) general.insertAdjacentElement('afterend', reference);
    else panel.querySelector('.card-body')?.prepend(reference);
  }

  function installAuthenticationTroubleshooting() {
    const panel = document.getElementById('htab-trouble');
    const details = findDetails(panel, "Auth is enabled but I'm locked out");
    if (!details) return;

    const body = details.querySelector('div');
    if (!body) return;
    body.innerHTML = `
      DebridPulse is designed to fail closed when a configured authentication mechanism is unavailable.<br>
      1. If Username &amp; Password is enabled, use the local DebridPulse login page or HTTP Basic with the configured credentials.<br>
      2. If OIDC is enabled alongside Password, an IdP outage does not disable the local password path.<br>
      3. OIDC-only critical changes must use <b>Verify Sign-In</b>; failed pending settings do not replace the last known-working configuration.<br>
      4. For last-resort local recovery, stop DebridPulse, make a backup of <code>/app/config/config.json</code>, and deliberately restore a known authentication configuration. Do not delete or publish credential hashes/secrets while troubleshooting.<br>
      See <code>docs/authentication.md</code> in the repository for the complete authentication and recovery model.
    `;
  }

  function install() {
    installAuthenticationReference();
    installAuthenticationTroubleshooting();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once: true});
  } else {
    install();
  }
})();
