/* DebridPulse authentication presentation layer.
 *
 * This file deliberately does not own authentication state or persistence.
 * auth-settings.js remains authoritative for values and actions; this layer
 * only reorganizes the rendered controls into the DebridPulse visual language.
 */
(() => {
  'use strict';

  const icons = {
    mode: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.6-2.7 8.1-7 10-4.3-1.9-7-5.4-7-10V6l7-3z"></path><path d="M9.5 12l1.7 1.7 3.6-4"></path></svg>',
    oidc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="10" width="14" height="10" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path><circle cx="12" cy="15" r="1"></circle></svg>',
    runtime: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h3l2-5 4 10 2-5h5"></path></svg>',
    provider: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3"></circle><path d="M5 20c.8-4 3.1-6 7-6s6.2 2 7 6"></path></svg>',
    token: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="12" r="3"></circle><path d="M11 12h9M17 12v3M14 12v2"></path></svg>',
    session: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M8 9h8M8 13h5"></path></svg>',
    globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"></path></svg>',
  };

  function cardByHeader(panel, text) {
    return Array.from(panel.querySelectorAll(':scope > .scard')).find(card =>
      String(card.querySelector('.scard-header')?.textContent || '').includes(text)
    ) || null;
  }

  function directChildFor(element, parent) {
    let node = element;
    while (node && node.parentElement !== parent) node = node.parentElement;
    return node && node.parentElement === parent ? node : null;
  }

  function statusKind(label) {
    const value = String(label || '').toLowerCase();
    if (value.includes('effective mode')) return 'mode';
    if (value.includes('oidc configured')) return 'oidc';
    if (value.includes('oidc runtime')) return 'runtime';
    if (value.includes('provider')) return 'provider';
    if (value.includes('api token')) return 'token';
    return 'session';
  }

  function statusState(label, value) {
    const key = String(label || '').toLowerCase();
    const state = String(value || '').trim().toLowerCase();

    if (key.includes('oidc configured')) return state === 'yes' ? 'ok' : 'bad';
    if (key.includes('oidc runtime')) {
      if (state.includes('unavailable')) return 'bad';
      if (state.includes('available')) return 'ok';
      return 'info';
    }
    if (key.includes('api token')) {
      if (state.includes('not configured') || state.includes('disabled')) return 'bad';
      return state.includes('configured') || state.includes('enabled') ? 'ok' : 'info';
    }
    return 'info';
  }

  function decorateStatus(panel) {
    const card = cardByHeader(panel, 'Authentication Status');
    if (!card) return;
    card.classList.add('auth-status-panel');

    const body = card.querySelector('.scard-body');
    const grid = Array.from(body?.children || []).find(child => child.querySelector('.aria2-chip'));
    if (!grid) return;
    grid.classList.add('auth-status-grid');

    grid.querySelectorAll('.aria2-chip').forEach(chip => {
      if (chip.classList.contains('auth-status-card')) return;
      const label = String(chip.querySelector('b')?.textContent || '').trim();
      const raw = String(chip.textContent || '').trim();
      const value = raw.startsWith(label) ? raw.slice(label.length).trim() : raw;
      const kind = statusKind(label);

      chip.classList.add('auth-status-card');
      chip.dataset.state = statusState(label, value);
      chip.textContent = '';

      const icon = document.createElement('span');
      icon.className = 'auth-status-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = icons[kind] || icons.session;

      const copy = document.createElement('div');
      copy.className = 'auth-status-copy';
      const labelEl = document.createElement('div');
      labelEl.className = 'auth-status-label';
      labelEl.textContent = label;
      const valueEl = document.createElement('div');
      valueEl.className = 'auth-status-value';
      valueEl.textContent = value || '—';
      copy.append(labelEl, valueEl);
      chip.append(icon, copy);
    });

    const callbackGroup = Array.from(body?.querySelectorAll(':scope > .form-group') || []).find(group =>
      String(group.querySelector('.form-label')?.textContent || '').includes('Public OIDC Callback URL')
    );
    callbackGroup?.classList.add('auth-status-callback');
  }

  function promoteExternalOrigin(panel) {
    if (panel.querySelector('.auth-origin-card')) return;
    const statusCard = cardByHeader(panel, 'Authentication Status');
    const sessionsCard = cardByHeader(panel, 'Sessions & Security');
    if (!statusCard || !sessionsCard) return;

    const sessionBody = sessionsCard.querySelector('.scard-body');
    const originInput = sessionBody?.querySelector('#auth-public-base-url');
    if (!originInput) return;
    const originGroup = originInput.closest('.form-group');
    if (!originGroup) return;

    const label = originGroup.querySelector('.form-label');
    if (label) label.textContent = 'Canonical External URL';
    const hint = originGroup.querySelector('.form-hint');
    if (hint) {
      hint.textContent = originInput.readOnly
        ? 'This is the effective deployment origin supplied by PUBLIC_BASE_URL. It is authoritative and read-only here.'
        : 'Enter the exact externally reachable HTTPS origin operators use to access DebridPulse, for example https://download.example.com.';
    }

    const card = document.createElement('div');
    card.className = 'scard auth-origin-card';
    card.innerHTML = `
      <div class="scard-header auth-origin-header">
        ${icons.globe}
        <span>External Authentication Origin</span>
      </div>
      <div class="scard-body">
        <div class="auth-origin-layout">
          <div class="auth-origin-field"></div>
          <div class="auth-origin-explainer">
            <strong>This value is a prerequisite for external browser authentication.</strong>
            DebridPulse uses this origin for reverse-proxy origin validation, secure authentication cookies, and construction of the OpenID Connect callback URL.
            <div class="auth-origin-warning">If it does not match the externally reachable HTTPS URL, password or OIDC sign-in can fail even when the identity provider itself is configured correctly.</div>
          </div>
        </div>
      </div>`;

    card.querySelector('.auth-origin-field')?.appendChild(originGroup);
    if (originInput.readOnly) {
      const source = document.createElement('div');
      source.className = 'auth-origin-source';
      source.textContent = 'Managed by PUBLIC_BASE_URL';
      card.querySelector('.auth-origin-field')?.appendChild(source);
    }
    statusCard.insertAdjacentElement('afterend', card);

    sessionsCard.classList.add('auth-session-card');
    const sessionHeader = sessionsCard.querySelector('.scard-header');
    if (sessionHeader) sessionHeader.textContent = '🕒 Session Details';
    const logoutButton = sessionsCard.querySelector('button[onclick*="logoutAuthenticationSession"]');
    const logoutRow = logoutButton ? directChildFor(logoutButton, sessionBody) : null;
    logoutRow?.remove();
  }

  function arrangePassword(panel) {
    const card = cardByHeader(panel, 'Username & Password');
    if (!card) return;
    card.classList.add('auth-password-card');
    const body = card.querySelector('.scard-body');
    if (!body || body.querySelector('.auth-password-grid')) return;

    const username = body.querySelector('#auth-username')?.closest('.form-group');
    const password = body.querySelector('#auth-new-password')?.closest('.form-group');
    if (!username || !password) return;

    const grid = document.createElement('div');
    grid.className = 'auth-password-grid';
    username.insertAdjacentElement('beforebegin', grid);
    grid.append(username, password);

    const clear = body.querySelector('button[onclick*="clearAuthenticationPassword"]');
    const action = clear ? directChildFor(clear, body) : null;
    action?.classList.add('auth-card-actions');
  }

  function arrangeOidc(panel) {
    const card = cardByHeader(panel, 'OpenID Connect');
    if (!card) return;
    card.classList.add('auth-oidc-card');
    const body = card.querySelector('.scard-body');
    if (!body || body.querySelector('.auth-oidc-primary-grid')) return;

    const groups = {
      provider: body.querySelector('#auth-oidc-provider')?.closest('.form-group'),
      issuer: body.querySelector('#auth-oidc-issuer')?.closest('.form-group'),
      client: body.querySelector('#auth-oidc-client-id')?.closest('.form-group'),
      secret: body.querySelector('#auth-oidc-client-secret')?.closest('.form-group'),
      scopes: body.querySelector('#auth-oidc-scopes')?.closest('.form-group'),
    };
    const callback = Array.from(body.querySelectorAll(':scope > .form-group')).find(group =>
      String(group.querySelector('.form-label')?.textContent || '').includes('Derived Callback URL')
    );

    if (groups.provider && groups.issuer && groups.client && groups.secret && groups.scopes) {
      const grid = document.createElement('div');
      grid.className = 'auth-oidc-primary-grid';
      groups.provider.insertAdjacentElement('beforebegin', grid);
      groups.issuer.classList.add('auth-oidc-span-2');
      callback?.classList.add('auth-oidc-span-3');
      grid.append(groups.provider, groups.client, groups.secret, groups.issuer, groups.scopes);
      if (callback) grid.appendChild(callback);
    }

    const allowAll = body.querySelector('#auth-oidc-allow-all');
    const authz = allowAll ? directChildFor(allowAll, body) : null;
    if (authz) {
      authz.classList.add('auth-oidc-authz');
      const heading = document.createElement('div');
      heading.className = 'auth-subsection-heading';
      heading.innerHTML = '<div class="auth-subsection-title">Authorization & Claim Mapping</div><div class="auth-subsection-copy">Restrict which successfully authenticated identities may use DebridPulse. Configured subject, email, and group categories are authorization requirements when Allow Any is disabled.</div>';
      authz.insertAdjacentElement('afterbegin', heading);

      const subject = authz.querySelector('#auth-oidc-subjects')?.closest('.form-group');
      const email = authz.querySelector('#auth-oidc-emails')?.closest('.form-group');
      const groupsField = authz.querySelector('#auth-oidc-groups')?.closest('.form-group');
      const claim = authz.querySelector('#auth-oidc-group-claim')?.closest('.form-group');
      if (subject && email && groupsField && claim) {
        const grid = document.createElement('div');
        grid.className = 'auth-oidc-authz-grid';
        subject.insertAdjacentElement('beforebegin', grid);
        claim.classList.add('auth-oidc-group-claim');
        grid.append(subject, email, groupsField, claim);
      }
    }

    const verify = body.querySelector('button[onclick*="verifyOidcSignIn"]');
    const actions = verify ? directChildFor(verify, body) : null;
    actions?.classList.add('auth-card-actions');
  }

  function arrangeApi(panel) {
    const card = cardByHeader(panel, 'API Access');
    if (!card) return;
    card.classList.add('auth-api-card');
    const body = card.querySelector('.scard-body');
    const generate = body?.querySelector('button[onclick*="generateApiToken"]');
    const actions = generate ? directChildFor(generate, body) : null;
    actions?.classList.add('auth-card-actions');
  }

  function arrangeSessions(panel) {
    const card = cardByHeader(panel, 'Session Details') || cardByHeader(panel, 'Sessions & Security');
    if (!card) return;
    card.classList.add('auth-session-card');
  }

  function decorateAuthenticationUx() {
    const panel = document.getElementById('tab-authentication');
    if (!panel) return;
    decorateStatus(panel);
    promoteExternalOrigin(panel);
    arrangePassword(panel);
    arrangeOidc(panel);
    arrangeApi(panel);
    arrangeSessions(panel);
    panel.dataset.authUxReady = 'true';
  }

  const originalRenderSettings = window.renderSettings;
  if (typeof originalRenderSettings === 'function' && !originalRenderSettings.__debridPulseAuthUx) {
    const wrapped = function renderSettingsWithAuthUx(...args) {
      const result = originalRenderSettings.apply(this, args);
      decorateAuthenticationUx();
      return result;
    };
    wrapped.__debridPulseAuthUx = true;
    window.renderSettings = wrapped;
    try { renderSettings = wrapped; } catch (_) {}
  }

  window.addEventListener('load', decorateAuthenticationUx);
  window.setTimeout(decorateAuthenticationUx, 0);
})();
