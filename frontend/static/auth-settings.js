/* DebridPulse Authentication settings augmentation for the 1.0.6 auth overhaul. */
(() => {
  'use strict';

  let authSettingsData = null;
  const baseRenderSettings = renderSettings;
  const baseGetFormSettings = getFormSettings;
  const baseSaveSettings = saveSettings;
  const OIDC_VERIFICATION_MARKER = 'debridpulse.oidc-verification-started';
  const OIDC_VERIFICATION_MARKER_TTL_MS = 15 * 60 * 1000;

  function authEsc(value) {
    return esc(String(value ?? ''));
  }

  function authChecked(value) {
    return value ? 'checked' : '';
  }

  function authLines(values) {
    return (Array.isArray(values) ? values : []).join('\n');
  }

  function authScopes(values) {
    return (Array.isArray(values) ? values : []).join(' ');
  }

  function authStateBadge(label, ok, neutral) {
    const color = neutral ? 'var(--text2)' : (ok ? 'var(--green)' : 'var(--red)');
    return `<span style="font-weight:700;color:${color}">${authEsc(label)}</span>`;
  }

  function markOidcVerificationStarted() {
    try {
      window.sessionStorage.setItem(OIDC_VERIFICATION_MARKER, String(Date.now()));
    } catch (_) {
      // Session storage is only UX state; verification itself must still proceed.
    }
  }

  function consumeOidcVerificationResult(params) {
    let started = 0;
    try {
      started = Number(window.sessionStorage.getItem(OIDC_VERIFICATION_MARKER) || 0);
    } catch (_) {
      return;
    }
    if (!started) return;

    const age = Date.now() - started;
    if (age < 0 || age > OIDC_VERIFICATION_MARKER_TTL_MS) {
      try { window.sessionStorage.removeItem(OIDC_VERIFICATION_MARKER); } catch (_) {}
      return;
    }
    if (params.get('view') !== 'settings' || params.get('tab') !== 'authentication') return;

    try { window.sessionStorage.removeItem(OIDC_VERIFICATION_MARKER); } catch (_) {}
    const verified = authSettingsData?.current_session_mechanism === 'oidc_session';
    if (verified) {
      toast('OIDC verification successful — provider sign-in and authorization completed.', 'success');
    } else {
      toast('OIDC verification failed — no verified OIDC session was established.', 'error');
    }
  }

  function removeLegacyAuthenticationControls() {
    document.querySelectorAll('#tab-general .scard-header').forEach(header => {
      if (header.textContent.includes('Access Control')) {
        header.closest('.scard')?.remove();
      }
    });
    document.getElementById('s-clear-auth_password')?.closest('label')?.remove();
  }

  function authenticationPanelHtml() {
    const a = authSettingsData || {};
    const available = a.oidc_available;
    const availableText = available === true
      ? authStateBadge('Available', true, false)
      : available === false
        ? authStateBadge('Unavailable', false, false)
        : authStateBadge('Not active', false, true);
    const currentMechanism = a.current_session_mechanism || 'open / anonymous';
    const passwordConfigured = a.password_configured ? 'Configured' : 'Not configured';
    const oidcSecretConfigured = a.oidc_client_secret_configured ? 'Configured — blank keeps current secret' : 'Not configured / public client';
    const tokenConfigured = a.api_token_configured ? 'Configured' : 'Not configured';
    const externalBase = a.public_base_url_env_override
      ? (a.public_base_url_effective || '')
      : (a.public_base_url || '');
    const externalBaseReadonly = a.public_base_url_env_override ? 'readonly' : '';
    const externalBaseHint = a.public_base_url_env_override
      ? 'Effective value is supplied by the PUBLIC_BASE_URL environment variable in the deployment and overrides the persisted UI value.'
      : 'Canonical externally reachable HTTPS origin. Used for reverse-proxy origin validation, secure cookies, and OIDC callback construction.';

    return `<div class="stab-panel" id="tab-authentication">
      <div class="scard">
        <div class="scard-header">🛡 Authentication Status</div>
        <div class="scard-body">
          ${!a.authentication_required ? `<div style="padding:10px 12px;border:1px solid var(--yellow);border-radius:8px;background:rgba(245,158,11,.08);margin-bottom:12px">
            <b style="color:var(--yellow)">No authentication enabled</b><br>
            <span class="form-hint">This is a supported standalone/LAN configuration. The application and API are intentionally open.</span>
          </div>` : ''}
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px">
            <div class="aria2-chip"><b>Effective mode</b><br>${authEsc(a.mode || 'Unknown')}</div>
            <div class="aria2-chip"><b>OIDC configured</b><br>${a.oidc_configured ? 'Yes' : 'No'}</div>
            <div class="aria2-chip"><b>OIDC runtime</b><br>${availableText}</div>
            <div class="aria2-chip"><b>Provider</b><br>${authEsc(a.oidc_provider_name || 'OpenID Connect')}</div>
            <div class="aria2-chip"><b>API token</b><br>${authEsc(tokenConfigured)}</div>
            <div class="aria2-chip"><b>Current mechanism</b><br>${authEsc(currentMechanism)}</div>
          </div>
          <div class="form-group" style="margin-top:12px">
            <label class="form-label">Public OIDC Callback URL</label>
            <input class="input" value="${authEsc(a.oidc_callback_url || 'Configure Public Base URL to derive callback')}" readonly>
          </div>
        </div>
      </div>

      <div class="scard">
        <div class="scard-header">🔑 Username &amp; Password</div>
        <p class="form-hint" style="padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)">Browser users sign in through the DebridPulse login page. REST clients may also use HTTP Basic with the same credentials. Disabling this mechanism keeps the stored password unless you explicitly clear it.</p>
        <div class="scard-body">
          <div class="toggle-row">
            <div class="toggle-info"><div class="tl">Enable Username &amp; Password</div><div class="ts">Local interactive login plus HTTP Basic for API clients</div></div>
            <label class="toggle"><input type="checkbox" id="auth-password-enabled" ${authChecked(a.password_enabled)}><div class="ttrack"></div></label>
          </div>
          <div class="form-group">
            <label class="form-label">Username</label>
            <input class="input" id="auth-username" maxlength="256" autocomplete="username" value="${authEsc(a.username || '')}" placeholder="operator">
          </div>
          <div class="form-group">
            <label class="form-label">New Password</label>
            <input class="input" id="auth-new-password" type="password" maxlength="4096" autocomplete="new-password" value="" placeholder="${authEsc(a.password_configured ? 'Stored password configured — blank keeps it' : 'Set a password before enabling')}">
            <span class="form-hint">Stored state: <b>${authEsc(passwordConfigured)}</b>. Entering a value replaces the stored Argon2id password.</span>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-danger btn-sm" type="button" onclick="clearAuthenticationPassword(this)" ${a.password_configured ? '' : 'disabled'}>Clear Stored Password</button>
          </div>
        </div>
      </div>

      <div class="scard">
        <div class="scard-header">🔐 OpenID Connect</div>
        <p class="form-hint" style="padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)">Provider-neutral Authorization Code + PKCE login. Verify Sign-In performs the real provider flow; it is not a discovery-only test.</p>
        <div class="scard-body">
          <div class="toggle-row">
            <div class="toggle-info"><div class="tl">Enable OpenID Connect</div><div class="ts">OIDC is preferred on the unified login page when both mechanisms are enabled</div></div>
            <label class="toggle"><input type="checkbox" id="auth-oidc-enabled" ${authChecked(a.oidc_enabled)}><div class="ttrack"></div></label>
          </div>
          <div class="form-group"><label class="form-label">Provider Display Name</label><input class="input" id="auth-oidc-provider" value="${authEsc(a.oidc_provider_name || 'OpenID Connect')}"></div>
          <div class="form-group"><label class="form-label">Issuer URL</label><input class="input" id="auth-oidc-issuer" value="${authEsc(a.oidc_issuer_url || '')}" placeholder="https://id.example/application/o/debridpulse"></div>
          <div class="form-group"><label class="form-label">Client ID</label><input class="input" id="auth-oidc-client-id" value="${authEsc(a.oidc_client_id || '')}"></div>
          <div class="form-group">
            <label class="form-label">Client Secret</label>
            <input class="input" id="auth-oidc-client-secret" type="password" value="" autocomplete="off" placeholder="${authEsc(oidcSecretConfigured)}">
            <label style="display:flex;gap:8px;align-items:center;margin-top:8px;font-size:11px;color:var(--text2)"><input type="checkbox" id="auth-clear-oidc-secret"> Explicitly clear stored client secret</label>
          </div>
          <div class="form-group"><label class="form-label">Scopes</label><input class="input" id="auth-oidc-scopes" value="${authEsc(authScopes(a.oidc_scopes))}" placeholder="openid profile email"></div>
          <div class="form-group"><label class="form-label">Derived Callback URL</label><input class="input" value="${authEsc(a.oidc_callback_url || 'Configure External Base URL to derive callback')}" readonly></div>

          <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
            <div class="toggle-row">
              <div class="toggle-info"><div class="tl">Allow any authenticated OIDC identity</div><div class="ts">When off, configured subject/email/group categories are authorization requirements</div></div>
              <label class="toggle"><input type="checkbox" id="auth-oidc-allow-all" ${authChecked(a.oidc_allow_all)}><div class="ttrack"></div></label>
            </div>
            <div class="form-group"><label class="form-label">Allowed Subjects (one per line)</label><textarea class="input" id="auth-oidc-subjects" rows="3">${authEsc(authLines(a.oidc_allowed_subjects))}</textarea><div class="form-hint">Use issuer-qualified identities in the form <code>&lt;issuer&gt;|&lt;sub&gt;</code>.</div></div>
            <div class="form-group"><label class="form-label">Allowed Emails (one per line)</label><textarea class="input" id="auth-oidc-emails" rows="3">${authEsc(authLines(a.oidc_allowed_emails))}</textarea><div class="form-hint">Email authorization requires the provider to assert <code>email_verified=true</code>.</div></div>
            <div class="form-group"><label class="form-label">Allowed Groups (one per line)</label><textarea class="input" id="auth-oidc-groups" rows="3">${authEsc(authLines(a.oidc_allowed_groups))}</textarea></div>
            <div class="form-group"><label class="form-label">Group Claim</label><input class="input" id="auth-oidc-group-claim" value="${authEsc(a.oidc_group_claim || 'groups')}"></div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
            <button class="btn btn-blue" type="button" onclick="verifyOidcSignIn(this)">Verify Sign-In</button>
          </div>
        </div>
      </div>

      <div class="scard">
        <div class="scard-header">🤖 API Access</div>
        <p class="form-hint" style="padding:4px 14px 6px;margin:0;font-size:11px;color:var(--text3)">Bearer tokens are intended for automation, Prometheus, scripts, and high-frequency API access. HTTP Basic remains available whenever Username &amp; Password is enabled.</p>
        <div class="scard-body">
          <div class="toggle-row">
            <div class="toggle-info"><div class="tl">Enable API token</div><div class="ts">Supplemental machine credential; it never turns open mode into token-only mode</div></div>
            <label class="toggle"><input type="checkbox" id="auth-api-token-enabled" ${authChecked(a.api_token_enabled)} onchange="setApiTokenEnabled(this)"><div class="ttrack"></div></label>
          </div>
          <div class="form-hint" style="margin-bottom:10px">Stored state: <b>${authEsc(tokenConfigured)}</b>. The full token is shown only when generated or rotated.</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-blue btn-sm" type="button" onclick="generateApiToken(this)">${a.api_token_configured ? 'Rotate Token' : 'Generate Token'}</button>
            <button class="btn btn-danger btn-sm" type="button" onclick="clearApiToken(this)" ${a.api_token_configured ? '' : 'disabled'}>Clear Token</button>
          </div>
          <div id="auth-api-token-once" style="display:none;margin-top:12px;padding:10px 12px;border:1px solid var(--accent);border-radius:8px;background:var(--surface2)">
            <div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:6px">Copy this token now — it will not be shown again.</div>
            <div style="display:flex;gap:8px"><input class="input" id="auth-api-token-value" readonly><button class="btn btn-ghost btn-sm" type="button" onclick="copyApiToken()">Copy</button></div>
          </div>
        </div>
      </div>

      <div class="scard">
        <div class="scard-header">🕒 Sessions &amp; Security</div>
        <div class="scard-body">
          <div class="form-group">
            <label class="form-label">External Base URL (Canonical Origin)</label>
            <input class="input" id="auth-public-base-url" value="${authEsc(externalBase)}" placeholder="https://download.example.com" ${externalBaseReadonly}>
            <div class="form-hint">${authEsc(externalBaseHint)}</div>
          </div>
          <div class="form-group"><label class="form-label">Browser Session Lifetime (hours)</label><input class="input" type="number" id="auth-session-hours" min="1" max="168" value="${Number(a.session_lifetime_hours || 12)}"></div>
          <div class="form-hint">Current mechanism: <b>${authEsc(currentMechanism)}</b> · Active in-process sessions: <b>${Number(a.session_count || 0)}</b></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button class="btn btn-ghost btn-sm" type="button" onclick="logoutAuthenticationSession(this)">Log Out</button></div>
        </div>
      </div>
    </div>`;
  }

  function augmentAuthenticationSettings() {
    removeLegacyAuthenticationControls();
    const tabs = document.getElementById('settings-tabs');
    const form = document.getElementById('settings-form');
    if (!tabs || !form || !authSettingsData) return;
    if (!tabs.querySelector('[data-tab="tab-authentication"]')) {
      const general = tabs.querySelector('[data-tab="tab-general"]');
      general?.insertAdjacentHTML('afterend', '<div class="stab" data-tab="tab-authentication" onclick="switchSettingsTab(\'tab-authentication\')">🛡 Authentication</div>');
    }
    if (!document.getElementById('tab-authentication')) {
      const generalPanel = document.getElementById('tab-general');
      generalPanel?.insertAdjacentHTML('afterend', authenticationPanelHtml());
    }
  }

  renderSettings = function renderSettingsWithAuthentication() {
    baseRenderSettings();
    augmentAuthenticationSettings();
  };

  getFormSettings = function getNonAuthFormSettings() {
    const data = baseGetFormSettings();
    // Authentication is owned by /api/auth/config. Preserve the last server
    // state here so an unrelated General/Download save cannot revert it.
    if (settingsData) {
      data.auth_password_enabled = !!settingsData.auth_password_enabled;
      data.auth_username = String(settingsData.auth_username || '');
      data.auth_password = '';
      data.auth_oidc_enabled = !!settingsData.auth_oidc_enabled;
      data.oidc_provider_name = settingsData.oidc_provider_name || 'OpenID Connect';
      data.oidc_issuer_url = settingsData.oidc_issuer_url || '';
      data.oidc_client_id = settingsData.oidc_client_id || '';
      data.oidc_scopes = Array.isArray(settingsData.oidc_scopes) ? settingsData.oidc_scopes : ['openid','profile','email'];
      data.oidc_allow_all = !!settingsData.oidc_allow_all;
      data.oidc_allowed_subjects = settingsData.oidc_allowed_subjects || [];
      data.oidc_allowed_emails = settingsData.oidc_allowed_emails || [];
      data.oidc_allowed_groups = settingsData.oidc_allowed_groups || [];
      data.oidc_group_claim = settingsData.oidc_group_claim || 'groups';
      data.public_base_url = settingsData.public_base_url || '';
    }
    data.clear_secrets = (data.clear_secrets || []).filter(field => field !== 'auth_password' && field !== 'oidc_client_secret');
    return data;
  };

  function syncBroadSettingsFromAuth(a) {
    if (!settingsData || !a) return;
    settingsData.auth_password_enabled = !!a.password_enabled;
    settingsData.auth_username = a.username || '';
    settingsData.auth_oidc_enabled = !!a.oidc_enabled;
    settingsData.oidc_provider_name = a.oidc_provider_name || 'OpenID Connect';
    settingsData.oidc_issuer_url = a.oidc_issuer_url || '';
    settingsData.oidc_client_id = a.oidc_client_id || '';
    settingsData.oidc_scopes = a.oidc_scopes || [];
    settingsData.oidc_allow_all = !!a.oidc_allow_all;
    settingsData.oidc_allowed_subjects = a.oidc_allowed_subjects || [];
    settingsData.oidc_allowed_emails = a.oidc_allowed_emails || [];
    settingsData.oidc_allowed_groups = a.oidc_allowed_groups || [];
    settingsData.oidc_group_claim = a.oidc_group_claim || 'groups';
    settingsData.public_base_url = a.public_base_url || '';
    settingsData.auth_session_lifetime_hours = Number(a.session_lifetime_hours || 12);
  }

  const field = id => document.getElementById(id);
  const value = id => String(field(id)?.value || '').trim();
  const checked = id => !!field(id)?.checked;
  const lines = id => String(field(id)?.value || '').split('\n').map(item => item.trim()).filter(Boolean);

  function currentAuthPayload() {
    const scopeValues = value('auth-oidc-scopes').split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
    return {
      auth_password_enabled: checked('auth-password-enabled'),
      auth_username: value('auth-username'),
      auth_password: String(field('auth-new-password')?.value || ''),
      auth_session_lifetime_hours: Math.max(1, Math.min(168, parseInt(value('auth-session-hours') || '12', 10) || 12)),
      auth_oidc_enabled: checked('auth-oidc-enabled'),
      oidc_provider_name: value('auth-oidc-provider') || 'OpenID Connect',
      oidc_issuer_url: value('auth-oidc-issuer'),
      oidc_client_id: value('auth-oidc-client-id'),
      oidc_client_secret: String(field('auth-oidc-client-secret')?.value || ''),
      clear_oidc_client_secret: checked('auth-clear-oidc-secret'),
      oidc_scopes: scopeValues,
      oidc_allow_all: checked('auth-oidc-allow-all'),
      oidc_allowed_subjects: lines('auth-oidc-subjects'),
      oidc_allowed_emails: lines('auth-oidc-emails'),
      oidc_allowed_groups: lines('auth-oidc-groups'),
      oidc_group_claim: value('auth-oidc-group-claim') || 'groups',
      public_base_url: authSettingsData?.public_base_url_env_override ? undefined : value('auth-public-base-url'),
    };
  }

  async function loadAuthenticationSettings() {
    authSettingsData = await api('GET', '/auth/config', null, 5000);
    syncBroadSettingsFromAuth(authSettingsData);
    return authSettingsData;
  }

  loadSettings = async function loadSettingsWithAuthentication() {
    try {
      const results = await Promise.all([
        api('GET', '/settings'),
        api('GET', '/auth/config', null, 5000),
      ]);
      settingsData = results[0];
      authSettingsData = results[1];
      syncBroadSettingsFromAuth(authSettingsData);
      renderSettings();
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
      return;
    }

    const params = new URLSearchParams(window.location.search);
    switchSettingsTab(params.get('tab') === 'authentication' ? 'tab-authentication' : 'tab-general');
    consumeOidcVerificationResult(params);
    const avatarUrl = settingsData.discord_avatar_url || '';
    if (avatarUrl && !avatarUrl.includes('github') && !avatarUrl.includes('_DEFAULT')) {
      showAvatarPreview(avatarUrl, 'Custom avatar', 0);
    }
  };

  async function saveAuthenticationSettings(button) {
    const payload = currentAuthPayload();
    if (!payload.auth_password_enabled && !payload.auth_oidc_enabled && authSettingsData?.authentication_required) {
      if (!window.confirm('Disable all interactive authentication and place DebridPulse in open mode?')) return;
      payload.confirm_open_mode = true;
    }

    setButtonPending(button, true, 'Saving…');
    try {
      authSettingsData = await api('PUT', '/auth/config', payload, 10000);
      syncBroadSettingsFromAuth(authSettingsData);
      renderSettings();
      switchSettingsTab('tab-authentication');
      toast('Authentication settings saved', 'success');
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
    } finally {
      setButtonPending(button, false);
    }
  }

  saveSettings = async function saveSettingsRouted(button) {
    if (getActiveSettingsTab() === 'tab-authentication') {
      return saveAuthenticationSettings(button);
    }
    return baseSaveSettings(button);
  };

  window.clearAuthenticationPassword = async function clearAuthenticationPassword(button) {
    if (!window.confirm('Clear the stored local password? Username & Password authentication will also be disabled.')) return;
    const payload = currentAuthPayload();
    payload.auth_password_enabled = false;
    payload.auth_password = '';
    payload.clear_password = true;
    if (!payload.auth_oidc_enabled && authSettingsData?.authentication_required) {
      if (!window.confirm('This also leaves no interactive authentication. Continue into open mode?')) return;
      payload.confirm_open_mode = true;
    }
    setButtonPending(button, true, 'Clearing…');
    try {
      authSettingsData = await api('PUT', '/auth/config', payload, 10000);
      syncBroadSettingsFromAuth(authSettingsData);
      renderSettings();
      switchSettingsTab('tab-authentication');
      toast('Stored password cleared', 'success');
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
    } finally {
      setButtonPending(button, false);
    }
  };

  window.verifyOidcSignIn = async function verifyOidcSignIn(button) {
    const payload = currentAuthPayload();
    const verification = {
      oidc_provider_name: payload.oidc_provider_name,
      oidc_issuer_url: payload.oidc_issuer_url,
      oidc_client_id: payload.oidc_client_id,
      oidc_client_secret: payload.oidc_client_secret,
      clear_oidc_client_secret: payload.clear_oidc_client_secret,
      oidc_scopes: payload.oidc_scopes,
      oidc_allow_all: payload.oidc_allow_all,
      oidc_allowed_subjects: payload.oidc_allowed_subjects,
      oidc_allowed_emails: payload.oidc_allowed_emails,
      oidc_allowed_groups: payload.oidc_allowed_groups,
      oidc_group_claim: payload.oidc_group_claim,
      public_base_url: payload.public_base_url,
      return_to: '/?view=settings&tab=authentication',
    };
    setButtonPending(button, true, 'Starting…');
    try {
      const result = await api('POST', '/auth/oidc/verify-config', verification, 10000);
      if (!result.authorization_url) throw new Error('OIDC verification did not return an authorization URL');
      markOidcVerificationStarted();
      window.location.assign(result.authorization_url);
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
      setButtonPending(button, false);
    }
  };

  window.setApiTokenEnabled = async function setApiTokenEnabled(input) {
    const desired = !!input.checked;
    input.disabled = true;
    try {
      const result = await api('PUT', '/auth/api-token', {enabled: desired});
      authSettingsData.api_token_enabled = !!result.enabled;
      authSettingsData.api_token_configured = !!result.configured;
      renderSettings();
      switchSettingsTab('tab-authentication');
      toast(`API token ${result.enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (e) {
      input.checked = !desired;
      toast(sanitizeErrorMsg(e.message), 'error');
    } finally {
      input.disabled = false;
    }
  };

  window.generateApiToken = async function generateApiToken(button) {
    setButtonPending(button, true, authSettingsData?.api_token_configured ? 'Rotating…' : 'Generating…');
    try {
      const result = await api('POST', '/auth/api-token');
      authSettingsData.api_token_enabled = true;
      authSettingsData.api_token_configured = true;
      renderSettings();
      switchSettingsTab('tab-authentication');
      const box = field('auth-api-token-once');
      const tokenField = field('auth-api-token-value');
      if (box && tokenField) {
        tokenField.value = String(result.token || '');
        box.style.display = '';
      }
      toast(result.rotated ? 'API token rotated' : 'API token generated', 'success');
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
    } finally {
      setButtonPending(button, false);
    }
  };

  window.clearApiToken = async function clearApiToken(button) {
    if (!window.confirm('Clear the API token? Existing automation using it will immediately lose access.')) return;
    setButtonPending(button, true, 'Clearing…');
    try {
      await api('DELETE', '/auth/api-token');
      authSettingsData.api_token_enabled = false;
      authSettingsData.api_token_configured = false;
      renderSettings();
      switchSettingsTab('tab-authentication');
      toast('API token cleared', 'success');
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
    } finally {
      setButtonPending(button, false);
    }
  };

  window.copyApiToken = async function copyApiToken() {
    const token = String(field('auth-api-token-value')?.value || '');
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      toast('API token copied', 'success');
    } catch (_) {
      field('auth-api-token-value')?.select();
      toast('Select and copy the token manually', 'info');
    }
  };

  window.logoutAuthenticationSession = async function logoutAuthenticationSession(button) {
    setButtonPending(button, true, 'Logging out…');
    try {
      if (!window.debridPulseAuth) throw new Error('No browser application session is available');
      await window.debridPulseAuth.logout();
    } catch (e) {
      toast(sanitizeErrorMsg(e.message), 'error');
      setButtonPending(button, false);
    }
  };

  // After a successful OIDC verification, the callback can return directly to
  // the Authentication tab without introducing a new SPA routing framework.
  window.addEventListener('load', () => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('view') !== 'settings') return;
    const settingsNav = document.querySelector('.nav-item[data-view="settings"]');
    if (settingsNav) nav(settingsNav);
  });
})();
