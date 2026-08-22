/* DebridPulse application-session bootstrap. Loaded before app.js. */
(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  const mutatingMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
  let csrfToken = '';
  let sessionState = null;
  let sessionRequest = null;
  let redirecting = false;

  function currentReturnPath() {
    return window.location.pathname + window.location.search + window.location.hash;
  }

  function redirectToLogin() {
    if (redirecting || window.location.pathname === '/login') return;
    redirecting = true;
    window.location.assign('/login?next=' + encodeURIComponent(currentReturnPath()));
  }

  function isSameOrigin(input) {
    try {
      const raw = input instanceof Request ? input.url : String(input || '');
      return new URL(raw, window.location.href).origin === window.location.origin;
    } catch (_) {
      return false;
    }
  }

  function syncSidebarSessionUi(data) {
    const footer = document.querySelector('.sidebar-footer');
    if (!footer) return;

    // These inherited convenience links occupied the natural account-action
    // position. Authentication now owns that space instead.
    footer.querySelector('a[href="https://alldebrid.com"]')?.closest('.conn-row')?.remove();
    document.getElementById('aria2ng-row')?.remove();

    let row = document.getElementById('sidebar-auth-row');
    if (!data?.authenticated) {
      row?.remove();
      return;
    }

    if (!row) {
      row = document.createElement('div');
      row.id = 'sidebar-auth-row';
      row.className = 'conn-row';
      row.style.cssText = 'margin-top:8px;padding-top:8px;border-top:1px solid var(--border);margin-bottom:0';

      const button = document.createElement('button');
      button.id = 'sidebar-logout';
      button.type = 'button';
      button.setAttribute('aria-label', 'Log out of DebridPulse');
      button.style.cssText = 'width:100%;border:0;background:transparent;color:var(--text3);font:inherit;font-size:11px;cursor:pointer;text-align:left;padding:2px 0;display:flex;align-items:center;gap:6px;transition:color .15s';
      button.innerHTML = '<span aria-hidden="true">↪</span><span>Log Out</span>';
      button.addEventListener('mouseenter', () => { button.style.color = 'var(--accent)'; });
      button.addEventListener('mouseleave', () => { button.style.color = 'var(--text3)'; });
      button.addEventListener('focus', () => { button.style.color = 'var(--accent)'; });
      button.addEventListener('blur', () => { button.style.color = 'var(--text3)'; });
      button.addEventListener('click', async () => {
        button.disabled = true;
        const label = button.querySelector('span:last-child');
        if (label) label.textContent = 'Logging out…';
        const ok = await logoutSession();
        if (!ok) {
          button.disabled = false;
          if (label) label.textContent = 'Log Out';
        }
      });
      row.appendChild(button);
      footer.appendChild(row);
    }
  }

  async function refreshSession({force = false} = {}) {
    if (sessionRequest && !force) return sessionRequest;
    sessionRequest = nativeFetch('/api/auth/session', {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json'}
    }).then(async response => {
      if (response.status === 401) {
        csrfToken = '';
        sessionState = null;
        syncSidebarSessionUi(null);
        redirectToLogin();
        return null;
      }
      if (!response.ok) return sessionState;
      const data = await response.json();
      sessionState = data;
      csrfToken = String(data && data.csrf_token || '');
      syncSidebarSessionUi(data);
      return data;
    }).catch(() => sessionState).finally(() => {
      sessionRequest = null;
    });
    return sessionRequest;
  }

  window.fetch = async function debridPulseFetch(input, init) {
    const options = {...(init || {})};
    const requestMethod = input instanceof Request ? input.method : 'GET';
    const method = String(options.method || requestMethod || 'GET').toUpperCase();
    const sameOrigin = isSameOrigin(input);

    if (sameOrigin) {
      options.credentials = options.credentials || 'same-origin';
    }

    if (sameOrigin && mutatingMethods.has(method)) {
      await refreshSession();
      if (csrfToken) {
        const inherited = input instanceof Request ? input.headers : undefined;
        const headers = new Headers(options.headers || inherited || {});
        headers.set('X-CSRF-Token', csrfToken);
        options.headers = headers;
      }
    }

    const response = await nativeFetch(input, options);
    if (sameOrigin && response.status === 401 && window.location.pathname !== '/login') {
      csrfToken = '';
      sessionState = null;
      syncSidebarSessionUi(null);
      redirectToLogin();
    }
    return response;
  };

  async function logoutSession() {
    const response = await window.fetch('/api/auth/logout', {method: 'POST'});
    if (response.ok) {
      csrfToken = '';
      sessionState = null;
      syncSidebarSessionUi(null);
      window.location.assign('/login');
      return true;
    }
    return false;
  }

  window.debridPulseAuth = Object.freeze({
    refreshSession,
    session: () => sessionState,
    logout: logoutSession,
  });

  refreshSession().catch(() => {});
  window.setInterval(() => refreshSession({force: true}).catch(() => {}), 60000);

  // Authentication UI/help augmentations remain isolated from the inherited
  // settings/index renderers. Dynamic loading keeps the 1.0.6 auth pass additive
  // while the combined app.js bundle finishes defining the legacy application.
  for (const source of ['/auth-settings.js?v=1', '/auth-help.js?v=1']) {
    const script = document.createElement('script');
    script.src = source;
    script.async = false;
    document.head.appendChild(script);
  }
})();