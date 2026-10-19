// Alberto AI — same-origin API client with secure browser-session exchange.
export class AlbertoAPI {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.ws = null;
    this.listeners = new Map();
    this.authPromise = null;
  }

  async _rawFetch(path, options = {}) {
    return fetch(this.baseUrl + path, {
      credentials: 'same-origin',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
  }

  async _authorizedFetch(path, options = {}) {
    let response = await this._rawFetch(path, options);
    if (response.status === 401 && path !== '/api/session/login' && !options._authRetried) {
      await this._requestLogin();
      response = await this._rawFetch(path, { ...options, _authRetried: true });
    }
    return response;
  }

  async _requestLogin() {
    if (this.authPromise) return this.authPromise;
    if (typeof document === 'undefined') throw new Error('Authentication required');
    this.authPromise = new Promise((resolve, reject) => {
      const overlay = document.createElement('div');
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'alberto-auth-title');
      overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:rgba(2,2,12,.82);padding:20px';
      const panel = document.createElement('form');
      panel.style.cssText = 'width:min(440px,100%);padding:24px;border:1px solid #51418b;border-radius:16px;background:#11122a;color:#e2e8f0;font:14px system-ui;box-shadow:0 24px 70px #0008';
      panel.innerHTML = '<h2 id="alberto-auth-title" style="margin:0 0 8px">Acesso ao Alberto AI</h2><p style="margin:0 0 16px;color:#aab2c8">Introduza o token de acesso. Será guardado apenas num cookie HttpOnly de sessão.</p><label for="alberto-auth-token">Token de acesso</label><input id="alberto-auth-token" type="password" autocomplete="current-password" required style="display:block;width:100%;margin:8px 0;padding:12px;border-radius:8px;border:1px solid #51418b;background:#080817;color:#fff"><p id="alberto-auth-error" role="alert" style="min-height:20px;color:#f87171"></p><div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" id="alberto-auth-cancel">Cancelar</button><button type="submit">Entrar</button></div>';
      document.body.appendChild(overlay);
      overlay.appendChild(panel);
      const input = panel.querySelector('#alberto-auth-token');
      const error = panel.querySelector('#alberto-auth-error');
      let settled = false;
      const cleanup = () => { overlay.remove(); this.authPromise = null; };
      const cancel = () => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(new Error('Authentication cancelled'));
      };
      panel.querySelector('#alberto-auth-cancel').addEventListener('click', cancel);
      overlay.addEventListener('click', (event) => { if (event.target === overlay) cancel(); });
      panel.addEventListener('submit', async (event) => {
        event.preventDefault();
        const token = input.value.trim();
        if (!token) { error.textContent = 'O token é obrigatório.'; return; }
        const submit = panel.querySelector('button[type="submit"]');
        submit.disabled = true;
        error.textContent = '';
        try {
          const response = await this._rawFetch('/api/session/login', {
            method: 'POST',
            body: JSON.stringify({ token }),
          });
          if (!response.ok) {
            error.textContent = response.status === 401 ? 'Token inválido.' : 'Não foi possível autenticar. Tente novamente.';
            return;
          }
          settled = true;
          cleanup();
          resolve();
        } catch {
          error.textContent = 'Falha de rede ao autenticar.';
        } finally {
          if (submit.isConnected) submit.disabled = false;
        }
      });
      input.focus();
    });
    return this.authPromise;
  }

  async _fetch(path, options = {}) {
    const resp = await this._authorizedFetch(path, options);
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${body || resp.statusText}`);
    }
    if (resp.status === 204) return null;
    return resp.json();
  }

  status() { return this._fetch('/api/status'); }
  banner() { return this._fetch('/api/banner'); }

  memoryList() { return this._fetch('/api/memory/list'); }
  memorySet(key, value, tags) {
    return this._fetch('/api/memory/set', { method: 'POST', body: JSON.stringify({ key, value, tags }) });
  }
  memoryGet(key) { return this._fetch(`/api/memory/get?key=${encodeURIComponent(key)}`); }
  memorySearch(query) { return this._fetch(`/api/memory/search?q=${encodeURIComponent(query)}`); }
  memoryDelete(key) { return this._fetch(`/api/memory/delete?key=${encodeURIComponent(key)}`, { method: 'DELETE' }); }

  squadList() { return this._fetch('/api/squad/list'); }
  squadDescribe(name) { return this._fetch(`/api/squad/describe?name=${encodeURIComponent(name)}`); }
  squadActivate(name) { return this._fetch('/api/squad/activate', { method: 'POST', body: JSON.stringify({ name }) }); }
  squadHibernate() { return this._fetch('/api/squad/hibernate', { method: 'POST' }); }
  squadRun(name, prompt) { return this._fetch('/api/squad/run', { method: 'POST', body: JSON.stringify({ name, prompt }) }); }

  shortcutList() { return this._fetch('/api/shortcut/list'); }
  shortcutAdd(key, expansion) { return this._fetch('/api/shortcut/add', { method: 'POST', body: JSON.stringify({ key, expansion }) }); }
  shortcutRemove(key) { return this._fetch(`/api/shortcut/remove?key=${encodeURIComponent(key)}`, { method: 'DELETE' }); }
  shortcutUse(key, args = '') { return this._fetch('/api/shortcut/use', { method: 'POST', body: JSON.stringify({ key, args }) }); }

  async chat(prompt, onChunk, conversationId, newConversation = false) {
    const body = { prompt };
    if (conversationId) body.conversation_id = conversationId;
    if (newConversation) body.new_conversation = true;
    const options = {
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    };
    const resp = await this._authorizedFetch('/api/chat', options);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    if (!resp.body || typeof resp.body.getReader !== 'function') {
      throw new Error('O backend não forneceu um stream SSE válido.');
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const dispatch = (raw) => {
      const data = raw.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!data) return;
      try { onChunk?.(JSON.parse(data)); }
      catch { onChunk?.({ type: 'error', error: 'Evento SSE inválido recebido do backend.' }); }
    };
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n');
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const event of events) dispatch(event);
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  }

  toolsList() { return this._fetch('/api/tools/list'); }
  toolInvoke(name, args) { return this._fetch('/api/tools/invoke', { method: 'POST', body: JSON.stringify({ name, args }) }); }

  modelList() { return this._fetch('/api/model/list'); }
  modelSet(task, provider, modelId, baseUrl, credEnv) {
    return this._fetch('/api/model/set', {
      method: 'POST',
      body: JSON.stringify({ task, provider, model_id: modelId, base_url: baseUrl, credential_env: credEnv }),
    });
  }
  modelTest(task) { return this._fetch(`/api/model/test?task=${encodeURIComponent(task)}`); }
  strategy(prompt) { return this._fetch(`/api/strategy?prompt=${encodeURIComponent(prompt)}`); }

  hermesBrowser(url) { return this._fetch('/api/hermes/browser', { method: 'POST', body: JSON.stringify({ url }) }); }
  hermesExec(code, language = 'python') {
    return this._fetch('/api/hermes/exec', { method: 'POST', body: JSON.stringify({ code, language }) });
  }

  logout() { return this._fetch('/api/session/logout', { method: 'POST' }); }
}
