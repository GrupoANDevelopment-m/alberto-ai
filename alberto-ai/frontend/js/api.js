// Alberto AI — API client
// Bridges the frontend to the agent's REST/WebSocket backend.

export class AlbertoAPI {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
    this.ws = null;
    this.listeners = new Map();
  }

  async _fetch(path, options = {}) {
    const resp = await fetch(this.baseUrl + path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  // Status
  status() { return this._fetch('/api/status'); }
  banner() { return this._fetch('/api/banner'); }

  // Memory
  memoryList() { return this._fetch('/api/memory/list'); }
  memorySet(key, value, tags) {
    return this._fetch('/api/memory/set', {
      method: 'POST',
      body: JSON.stringify({ key, value, tags }),
    });
  }
  memoryGet(key) { return this._fetch(`/api/memory/get?key=${encodeURIComponent(key)}`); }
  memorySearch(query) { return this._fetch(`/api/memory/search?q=${encodeURIComponent(query)}`); }
  memoryDelete(key) {
    return this._fetch(`/api/memory/delete?key=${encodeURIComponent(key)}`, { method: 'DELETE' });
  }

  // Squads
  squadList() { return this._fetch('/api/squad/list'); }
  squadDescribe(name) { return this._fetch(`/api/squad/describe?name=${encodeURIComponent(name)}`); }
  squadActivate(name) {
    return this._fetch('/api/squad/activate', {
      method: 'POST', body: JSON.stringify({ name }),
    });
  }
  squadHibernate() { return this._fetch('/api/squad/hibernate', { method: 'POST' }); }
  squadRun(name, prompt) {
    return this._fetch('/api/squad/run', {
      method: 'POST',
      body: JSON.stringify({ name, prompt }),
    });
  }

  // Shortcuts
  shortcutList() { return this._fetch('/api/shortcut/list'); }
  shortcutAdd(key, expansion) {
    return this._fetch('/api/shortcut/add', {
      method: 'POST',
      body: JSON.stringify({ key, expansion }),
    });
  }
  shortcutRemove(key) {
    return this._fetch(`/api/shortcut/remove?key=${encodeURIComponent(key)}`, { method: 'DELETE' });
  }
  shortcutUse(key, args = '') {
    return this._fetch('/api/shortcut/use', {
      method: 'POST',
      body: JSON.stringify({ key, args }),
    });
  }

  // Chat (with streaming via SSE)
  async chat(prompt, onChunk, conversationId) {
    const body = { prompt };
    if (conversationId) body.conversation_id = conversationId;
    const resp = await fetch(this.baseUrl + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6);
          try { onChunk?.(JSON.parse(payload)); } catch { onChunk?.({ type: 'text', content: payload }); }
        }
      }
    }
  }


  // Tools
  toolsList() { return this._fetch('/api/tools/list'); }
  toolInvoke(name, args) {
    return this._fetch('/api/tools/invoke', {
      method: 'POST', body: JSON.stringify({ name, args }),
    });
  }

  // Models
  modelList() { return this._fetch('/api/model/list'); }
  modelSet(task, provider, modelId, baseUrl, credEnv) {
    return this._fetch('/api/model/set', {
      method: 'POST',
      body: JSON.stringify({
        task, provider, model_id: modelId, base_url: baseUrl, credential_env: credEnv,
      }),
    });
  }
  modelTest(task) { return this._fetch(`/api/model/test?task=${encodeURIComponent(task)}`); }

  // Strategy debug
  strategy(prompt) {
    return this._fetch(`/api/strategy?prompt=${encodeURIComponent(prompt)}`);
  }

  // Hermes commands
  hermesBrowser(url) {
    return this._fetch('/api/hermes/browser', {
      method: 'POST', body: JSON.stringify({ url }),
    });
  }
  hermesExec(code, language = 'python') {
    return this._fetch('/api/hermes/exec', {
      method: 'POST', body: JSON.stringify({ code, language }),
    });
  }
}