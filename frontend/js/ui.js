// Alberto AI — main UI controller

import { AlbertoAPI } from './api.js';
import { Background3D } from './bg3d.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

class AlbertoApp {
  constructor() {
    this.api = new AlbertoAPI();
    this.bg = new Background3D($('#bg-canvas'));
    this.currentView = 'chat';
    this.activeSquad = null;
    this.shortcuts = {};
    this.squads = [];
    this.memory = [];
    this.bindEvents();
    this.init();
  }

  bindEvents() {
    // View navigation
    $$('.nav-btn').forEach((btn) => {
      btn.addEventListener('click', () => this.switchView(btn.dataset.view));
    });

    // Composer
    const composer = $('#composer');
    composer.addEventListener('input', () => this.autoresizeComposer());
    composer.addEventListener('keydown', (e) => this.onComposerKeydown(e));
    $('#send-btn').addEventListener('click', () => this.sendPrompt());

    // Toolbar buttons
    $('#btn-clear').addEventListener('click', () => this.clearChat());
    $('#btn-voice').addEventListener('click', () => this.toggleVoice());
    $('#btn-upload').addEventListener('click', () => this.uploadFile());

    // Tool buttons
    $('#tool-attachment').addEventListener('click', () => this.uploadFile());
    $('#tool-screenshot').addEventListener('click', () => this.takeScreenshot());
    $('#tool-voice-input').addEventListener('click', () => this.startVoiceInput());

    // Engine cards
    $$('.engine-card').forEach((card) => {
      card.addEventListener('click', () => this.toggleEngine(card.dataset.engine));
    });

    // Suggestions
    $$('.suggestion').forEach((btn) => {
      btn.addEventListener('click', () => {
        $('#composer').value = btn.dataset.prompt;
        this.sendPrompt();
      });
    });

    // Memory search
    $('#memory-search-input').addEventListener('input', (e) => this.searchMemory(e.target.value));
    $('#memory-add-btn').addEventListener('click', () => this.openMemoryAddModal());

    // Settings
    $('#settings-add-model').addEventListener('click', () => this.openModelAddModal());

    // Palette
    $('#palette-input').addEventListener('input', (e) => this.updatePaletteResults(e.target.value));
    $('#palette-input').addEventListener('keydown', (e) => this.onPaletteKeydown(e));
    document.addEventListener('keydown', (e) => this.onGlobalKeydown(e));

    // Modal
    $('#modal-close').addEventListener('click', () => this.closeModal());
    $('#modal-backdrop').addEventListener('click', (e) => {
      if (e.target === $('#modal-backdrop')) this.closeModal();
    });
  }

  async init() {
    try {
      const status = await this.api.status();
      this.applyStatus(status);
      $('#status-dot').classList.add('online');
      $('#status-text').textContent = 'online';

      await this.loadSquads();
      await this.loadShortcuts();
      await this.loadMemory();
      await this.loadTools();
      this.updateGreeting();
    } catch (e) {
      $('#status-dot').classList.add('error');
      $('#status-text').textContent = 'offline (mock)';
      this.toast('Backend offline — usando dados mock pra preview', 'info');
      this.applyStatus(this.mockStatus());
    }
  }

  mockStatus() {
    return {
      name: 'Alberto AI',
      version: '1.0.0',
      sandbox: 'LocalSandbox',
      mimo: { running: true, memory_keys: 0 },
      hermes: { running: false },
      shortcuts: 0,
      squads: ['engineering', 'research', 'product', 'incident', 'data-ml', 'growth', 'finance', 'support'],
      active_squad: null,
      models: [],
    };
  }

  applyStatus(status) {
    if (!status) return;
    if (status.mimo?.running) {
      $('#engine-grid [data-engine="mimo"]').classList.add('active');
    }
    if (status.hermes?.running) {
      $('#engine-grid [data-engine="hermes"]').classList.add('active');
    }
    if (status.active_squad) {
      this.activeSquad = status.active_squad;
      this.updateSquadPanel();
    }
    const models = status.models || [];
    ['chat', 'code', 'reasoning'].forEach((t) => {
      const el = $(`#m-${t}`);
      if (models.includes(t)) {
        el.textContent = 'configured';
        el.classList.remove('empty');
      } else {
        el.textContent = 'not set';
        el.classList.add('empty');
      }
    });
  }

  updateGreeting() {
    const h = new Date().getHours();
    let greeting = 'Olá, eu sou o Alberto.';
    if (h < 6) greeting = 'Boa madrugada. Em que posso ajudar?';
    else if (h < 12) greeting = 'Bom dia. Eu sou o Alberto.';
    else if (h < 18) greeting = 'Boa tarde. Vamos lá.';
    else greeting = 'Boa noite. Como posso ajudar?';
    $('#chat-greeting').textContent = greeting;
  }

  switchView(view) {
    this.currentView = view;
    $$('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
    $$('.view').forEach((v) => v.classList.toggle('active', v.dataset.view === view));
  }

  // ===== Composer =====
  autoresizeComposer() {
    const composer = $('#composer');
    composer.style.height = 'auto';
    composer.style.height = Math.min(composer.scrollHeight, 200) + 'px';
  }

  onComposerKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.sendPrompt();
    } else if (e.key === 'Escape') {
      $('#composer').blur();
    }
  }

  async sendPrompt() {
    const composer = $('#composer');
    const text = composer.value.trim();
    if (!text) return;

    // Hide empty state
    $('#chat-empty').style.display = 'none';
    this.removeSquadPanel();

    // Add user message
    this.appendMessage('user', text);

    composer.value = '';
    this.autoresizeComposer();

    // Strategy decision
    let strategy = { mode: 'solo', engine: 'mimo', task_routing: 'code' };
    try {
      strategy = await this.api.strategy(text);
    } catch {}

    // Add typing indicator
    const typing = this.appendTyping();
    this.updateComposerMode(strategy);

    // Stream response via /api/chat (SSE)
    let responseText = '';
    let finalStrategy = strategy;
    let finalToolCalls = [];
    let finalConvId = null;
    try {
      await this.api.chat(text, (chunk) => {
        if (chunk.type === 'text') {
          responseText += chunk.content;
          if (typing.querySelector('.msg-content')) {
            typing.querySelector('.msg-content').textContent = responseText;
          }
        } else if (chunk.type === 'done') {
          if (chunk.strategy) finalStrategy = chunk.strategy;
          if (chunk.tool_calls) finalToolCalls = chunk.tool_calls;
          if (chunk.conversation_id) finalConvId = chunk.conversation_id;
        } else if (chunk.type === 'error') {
          responseText = `[erro: ${chunk.error}]`;
        }
      });
    } catch (e) {
      responseText = `[backend offline] ${e.message}\n\nVocê precisa rodar:\n  alberto serve --port 8741\n\nResposta local (preview):\n${this.mockResponse(text, strategy)}`;
    }

    typing.remove();
    const finalText = responseText || this.mockResponse(text, finalStrategy);
    this.appendMessage('assistant', finalText, finalStrategy);

    if (finalToolCalls && finalToolCalls.length) {
      finalToolCalls.forEach((tc) => {
        this.appendToolCall(tc);
      });
    }

    // Reload memory if changed
    if (text.toLowerCase().includes('memory')) {
      this.loadMemory();
    }
  }

  mockResponse(text, strategy) {
    if (text.startsWith('/aiox-squad activate')) {
      const name = text.split(' ').pop();
      this.activeSquad = name;
      this.updateSquadPanel();
      return `Squad **${name}** ativado. Próximos comandos serão roteados por ele.`;
    }
    if (text.startsWith('/hermes browser')) {
      return `🌐 Buscando ${text.split(' ').slice(2).join(' ')}... (em produção, abriria Hermes browser)`;
    }
    if (text.startsWith('/s ')) {
      const parts = text.split(' ');
      const key = parts[1];
      const expansion = parts.slice(2).join(' ');
      this.shortcuts[key] = { expansion, use_count: 0 };
      this.renderShortcuts();
      return `Atalho **${key}** → \`${expansion}\``;
    }
    if (text.startsWith('/strategy')) {
      return JSON.stringify(strategy, null, 2);
    }
    return `Recebi: "${text}"\n\nEstratégia: ${strategy.mode} | engine=${strategy.engine} | task=${strategy.task_routing}\n\n(Em produção, isto viria do LLM via streaming.)`;
  }

  appendMessage(role, content, strategy = null) {
    const scroll = $('#chat-scroll');
    const msg = document.createElement('div');
    msg.className = `msg ${role}`;

    const avatar = role === 'user' ? '👤' : '🤖';
    const roleText = role === 'user' ? 'você' : 'Alberto';

    let strategyHtml = '';
    if (strategy && role === 'assistant') {
      const glyph = strategy.mode === 'speculative' ? '🎲' :
                    strategy.mode === 'squad' ? '👥' : '⚡';
      strategyHtml = `<div class="msg-strategy strategy-${strategy.mode}">
        <span class="glyph">${glyph}</span>
        <span class="strategy-mode">${strategy.mode}</span>
        <span>·</span>
        <span>${strategy.engine}</span>
        ${strategy.squad ? `<span>·</span><span>${strategy.squad}</span>` : ''}
      </div>`;
    }

    msg.innerHTML = `
      <div class="msg-avatar">${avatar}</div>
      <div class="msg-body">
        <div class="msg-meta">
          <span class="role">${roleText}</span>
          <span>${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        ${strategyHtml}
        <div class="msg-content">${this.renderMarkdown(content)}</div>
      </div>
    `;

    scroll.appendChild(msg);
    scroll.scrollTop = scroll.scrollHeight;
    return msg;
  }

  appendTyping() {
    const scroll = $('#chat-scroll');
    const msg = document.createElement('div');
    msg.className = 'msg assistant typing-msg';
    msg.innerHTML = `
      <div class="msg-avatar">🤖</div>
      <div class="msg-body">
        <div class="msg-meta">
          <span class="role">Alberto</span>
          <span class="typing">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
          </span>
        </div>
        <div class="msg-content"></div>
      </div>
    `;
    scroll.appendChild(msg);
    scroll.scrollTop = scroll.scrollHeight;
    return msg;
  }

  updateComposerMode(strategy) {
    $('#mode-value').textContent = strategy.mode;
  }

  renderMarkdown(text) {
    // Tiny safe-ish markdown: code, bold, lists, paragraphs
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    html = html.replace(/```([\s\S]*?)```/g, (m, code) => `<pre><code>${code.trim()}</code></pre>`);
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
    html = html.split(/\n\n+/).map(p => /^<(h\d|ul|pre)/.test(p.trim()) ? p : `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return html;
  }

  clearChat() {
    $('#chat-scroll').innerHTML = '';
    $('#chat-empty').style.display = 'flex';
    this.loadMemory();
  }

  // ===== Voice & Upload =====
  toggleVoice() { this.toast('voice: em desenvolvimento', 'info'); }
  uploadFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = (e) => {
      const f = e.target.files[0];
      if (f) this.toast(`arquivo "${f.name}" anexado`, 'info');
    };
    input.click();
  }
  takeScreenshot() { this.toast('screenshot: em desenvolvimento', 'info'); }
  startVoiceInput() {
    if (!('webkitSpeechRecognition' in window)) {
      this.toast('voz não suportada neste navegador', 'error');
      return;
    }
    const rec = new webkitSpeechRecognition();
    rec.lang = 'pt-BR';
    rec.onresult = (e) => {
      const text = e.results[0][0].transcript;
      $('#composer').value = text;
      this.autoresizeComposer();
    };
    rec.start();
    this.toast('ouvindo…', 'info');
  }

  // ===== Engine toggle =====
  toggleEngine(engine) {
    if (engine === 'hermes') {
      this.toast('Hermes: lazy spawn (ativa em /hermes)', 'info');
      $('#engine-grid [data-engine="hermes"]').classList.toggle('active');
    } else if (engine === 'mimo') {
      this.toast('MiMo: sempre ligado', 'info');
    }
  }

  // ===== Squads =====
  async loadSquads() {
    try {
      this.squads = await this.api.squadList();
    } catch {
      this.squads = ['engineering', 'research', 'product', 'incident', 'data-ml', 'growth', 'finance', 'support'];
    }
    this.renderSquads();
    this.updateSquadPanel();
  }

  async renderSquads() {
    const grid = $('#squads-grid');
    const descriptions = {
      engineering: { emoji: '🏗️', desc: 'pm → architect → dev → qa → devops', tags: 'cross-functional sprint' },
      research: { emoji: '🔬', desc: 'researcher → reviewer → analyst → writer → critic', tags: 'academic/market/tech' },
      product: { emoji: '🎯', desc: 'ux-researcher → pm → ux-designer → data-analyst → tech-lead', tags: 'discovery' },
      incident: { emoji: '🚨', desc: 'oncall → sre → comms → pm → postmortem', tags: 'production' },
      'data-ml': { emoji: '🧬', desc: 'analyst → data-eng → ml-eng → mlops → sre', tags: 'pipelines + models' },
      growth: { emoji: '📈', desc: 'analyst → growth → content → pm → analyst', tags: 'funnels + content' },
      finance: { emoji: '💰', desc: 'analyst → finance → pm → finance', tags: 'modelling + decisions' },
      support: { emoji: '🎧', desc: 'support → product → dev → qa → support', tags: 'tickets → fix' },
    };
    const personasBySquad = {
      engineering: ['pm', 'architect', 'dev', 'qa', 'devops'],
      research: ['researcher', 'reviewer', 'analyst', 'writer', 'critic'],
      product: ['ux_researcher', 'pm', 'ux_designer', 'data_analyst', 'tech_lead'],
      incident: ['oncall', 'sre', 'comms', 'pm', 'reviewer'],
      'data-ml': ['analyst', 'data_engineer', 'ml_engineer', 'mlops', 'sre'],
      growth: ['analyst', 'growth', 'content', 'pm', 'analyst'],
      finance: ['analyst', 'finance', 'pm', 'finance'],
      support: ['support', 'product', 'dev', 'qa', 'support'],
    };

    grid.innerHTML = '';
    for (const name of this.squads) {
      const meta = descriptions[name] || { emoji: '📦', desc: 'workflow', tags: '' };
      const personas = personasBySquad[name] || [];
      const card = document.createElement('div');
      card.className = 'squad-card' + (this.activeSquad === name ? ' active' : '');
      card.innerHTML = `
        <div class="squad-card-header">
          <div class="squad-name">${meta.emoji} ${name}</div>
          <div class="squad-badge">${this.activeSquad === name ? 'ATIVO' : 'OPT-IN'}</div>
        </div>
        <div class="squad-description">${meta.desc}</div>
        <div class="squad-workflow">
          ${personas.map((p, i) =>
            `<span class="squad-persona">${p}</span>${i < personas.length - 1 ? '<span class="squad-arrow">→</span>' : ''}`
          ).join('')}
        </div>
        <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-faint);">${meta.tags}</div>
        <div class="squad-actions">
          ${this.activeSquad === name
            ? '<button class="ghost-btn" data-action="hibernate">hibernar</button>'
            : '<button class="primary-btn" data-action="activate">ativar</button>'}
          <button class="ghost-btn" data-action="run">▶ rodar demo</button>
        </div>
      `;
      card.querySelector('[data-action="activate"]')?.addEventListener('click', () => this.activateSquad(name));
      card.querySelector('[data-action="hibernate"]')?.addEventListener('click', () => this.hibernateSquad());
      card.querySelector('[data-action="run"]')?.addEventListener('click', () => this.runSquadDemo(name));
      grid.appendChild(card);
    }
  }

  async activateSquad(name) {
    try { await this.api.squadActivate(name); } catch {}
    this.activeSquad = name;
    this.toast(`squad "${name}" ativado`, 'success');
    this.updateSquadPanel();
    this.renderSquads();
  }

  async hibernateSquad() {
    try { await this.api.squadHibernate(); } catch {}
    this.activeSquad = null;
    this.toast('squad hibernado', 'info');
    this.updateSquadPanel();
    this.renderSquads();
  }

  async runSquadDemo(name) {
    this.switchView('chat');
    $('#composer').value = `demo do squad ${name}: build a counter`;
    await this.sendPrompt();
  }

  updateSquadPanel() {
    const panel = $('#squad-status');
    if (this.activeSquad) {
      panel.innerHTML = `
        <div class="squad-active">
          <div class="squad-active-name">⚡ ${this.activeSquad}</div>
          <div class="squad-active-stage">próximo /ask → squad pipeline</div>
        </div>
      `;
    } else {
      panel.innerHTML = '<div class="squad-empty">nenhum squad ativo</div>';
    }
  }

  removeSquadPanel() {} // placeholder

  // ===== Memory =====
  async loadMemory() {
    try { this.memory = await this.api.memoryList(); } catch {
      this.memory = this.mockMemory();
    }
    this.renderMemory(this.memory);
  }

  mockMemory() {
    return [
      { key: 'user.name', value: 'Você', tags: 'user' },
      { key: 'project.name', value: 'Alberto AI', tags: 'project' },
      { key: 'preferences.language', value: 'pt-BR', tags: 'prefs' },
    ];
  }

  renderMemory(items) {
    const list = $('#memory-list');
    if (!items || items.length === 0) {
      list.innerHTML = '<div class="shortcut-empty">memória vazia</div>';
      return;
    }
    list.innerHTML = '';
    for (const m of items) {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.innerHTML = `
        <div class="memory-key">${this.escapeHtml(m.key)}</div>
        <div class="memory-value">${this.escapeHtml((m.value || '').slice(0, 200))}</div>
        <div class="memory-tags">${m.tags || ''}</div>
      `;
      list.appendChild(item);
    }
  }

  async searchMemory(query) {
    if (!query) { this.renderMemory(this.memory); return; }
    try {
      const hits = await this.api.memorySearch(query);
      this.renderMemory(hits);
    } catch {
      const filtered = this.memory.filter(m =>
        m.key.toLowerCase().includes(query.toLowerCase()) ||
        (m.value || '').toLowerCase().includes(query.toLowerCase())
      );
      this.renderMemory(filtered);
    }
  }

  openMemoryAddModal() {
    this.openModal('Adicionar à memória', `
      <div style="display:flex; flex-direction:column; gap:12px;">
        <input id="modal-mem-key" placeholder="chave (ex: user.name)" style="..."/>
        <textarea id="modal-mem-val" placeholder="valor" rows="4" style="..."></textarea>
        <input id="modal-mem-tags" placeholder="tags (opcional)" style="..."/>
      </div>
    `, [
      { label: 'cancelar', class: 'ghost-btn', action: () => this.closeModal() },
      { label: 'salvar', class: 'primary-btn', action: () => this.saveMemory() },
    ]);
  }

  async saveMemory() {
    const key = $('#modal-mem-key').value.trim();
    const value = $('#modal-mem-val').value.trim();
    const tags = $('#modal-mem-tags').value.trim();
    if (!key || !value) { this.toast('chave e valor obrigatórios', 'error'); return; }
    try { await this.api.memorySet(key, value, tags); } catch {}
    this.memory.unshift({ key, value, tags });
    this.renderMemory(this.memory);
    this.closeModal();
    this.toast(`"${key}" salvo`, 'success');
  }

  // ===== Shortcuts =====
  async loadShortcuts() {
    try { this.shortcuts = await this.api.shortcutList(); } catch {
      this.shortcuts = this.mockShortcuts();
    }
    this.renderShortcuts();
  }

  mockShortcuts() {
    return {
      ms: { expansion: 'memory search {{args}}', use_count: 3 },
      gdp: { expansion: 'hermes exec "git diff && (test -z \\"$(git status -s)\\" && git push || echo uncommitted)"', use_count: 1 },
      hi: { expansion: 'chat "olá, como vai?"', use_count: 7 },
    };
  }

  renderShortcuts() {
    const list = $('#shortcuts-list');
    const keys = Object.keys(this.shortcuts);
    if (keys.length === 0) {
      list.innerHTML = '<div class="shortcut-empty">nenhum atalho. comece com <code>/s add &lt;key&gt; &lt;exp&gt;</code></div>';
      return;
    }
    list.innerHTML = '';
    for (const k of keys) {
      const s = this.shortcuts[k];
      const item = document.createElement('div');
      item.className = 'shortcut-item';
      item.innerHTML = `
        <div class="shortcut-key">${this.escapeHtml(k)}</div>
        <div class="shortcut-exp">${this.escapeHtml(s.expansion || '')}</div>
        <div class="shortcut-count">usado ${s.use_count || 0}x</div>
      `;
      list.appendChild(item);
    }
  }

  // ===== Tools =====
  async loadTools() {
    const tools = [
      { name: 'memory.set', engine: 'mimo', desc: 'persiste key/value no FTS5', enabled: true },
      { name: 'memory.get', engine: 'mimo', desc: 'recupera valor por chave', enabled: true },
      { name: 'memory.search', engine: 'mimo', desc: 'busca full-text na memória', enabled: true },
      { name: 'goal.set', engine: 'mimo', desc: 'define goal + critérios pro judge', enabled: true },
      { name: 'judge', engine: 'mimo', desc: 'LLM avalia candidato vs critérios', enabled: true },
      { name: 'max_mode', engine: 'mimo', desc: 'best-of-N paralelo + judge escolhe', enabled: true },
      { name: 'compose', engine: 'mimo', desc: 'pipeline spec → tdd → review', enabled: true },
      { name: 'subagent', engine: 'mimo', desc: 'N sessões paralelas via ThreadPool', enabled: true },
      { name: 'distill', engine: 'mimo', desc: 'sumariza toda memória em MEMORY.md', enabled: true },
      { name: 'worktree', engine: 'mimo', desc: 'git worktree por sessão', enabled: false },
      { name: 'snapshot', engine: 'mimo', desc: 'checkpoint de sessão', enabled: false },
      { name: 'lsp', engine: 'mimo', desc: 'diagnostics do LSP server', enabled: false },

      { name: 'browser', engine: 'hermes', desc: 'HTTP fetch + HTML strip', enabled: false },
      { name: 'code_execution', engine: 'hermes', desc: 'subprocess sandboxed', enabled: true },
      { name: 'session_search', engine: 'hermes', desc: 'FTS5 session search', enabled: true },
      { name: 'cron', engine: 'hermes', desc: 'in-process scheduler', enabled: false },
      { name: 'computer_use', engine: 'hermes', desc: 'screen + click (precisa Xvfb)', enabled: false },
      { name: 'voice_tts', engine: 'hermes', desc: 'text → speech', enabled: false },
      { name: 'image_gen', engine: 'hermes', desc: 'text → image', enabled: false },
      { name: 'video_gen', engine: 'hermes', desc: 'text → video', enabled: false },
      { name: 'x_search', engine: 'hermes', desc: 'busca no X/Twitter', enabled: false },
    ];
    const grid = $('#tools-grid');
    grid.innerHTML = '';
    for (const t of tools) {
      const card = document.createElement('div');
      card.className = 'tool-card' + (t.enabled ? '' : ' disabled');
      card.innerHTML = `
        <div class="tool-header">
          <div class="tool-name">${this.escapeHtml(t.name)}</div>
          <div class="tool-engine ${t.engine}">${t.engine}</div>
        </div>
        <div class="tool-desc">${this.escapeHtml(t.desc)}</div>
        <div class="tool-status">
          <span class="dot ${t.enabled ? '' : 'off'}"></span>
          <span>${t.enabled ? 'enabled' : 'off (opt-in)'}</span>
        </div>
      `;
      grid.appendChild(card);
    }
  }

  // ===== Settings =====
  openModelAddModal() {
    this.openModal('Configurar model', `
      <div style="display:flex; flex-direction:column; gap:12px;">
        <select id="modal-task" style="...">
          <option value="chat">chat</option>
          <option value="code">code</option>
          <option value="reasoning">reasoning</option>
          <option value="vision">vision</option>
          <option value="embedding">embedding</option>
        </select>
        <input id="modal-provider" placeholder="provider (ex: nvidia, openai, anthropic)" style="..."/>
        <input id="modal-modelid" placeholder="model_id (ex: moonshotai/kimi-k2.6)" style="..."/>
        <input id="modal-baseurl" placeholder="base_url (ex: https://integrate.api.nvidia.com/v1)" style="..."/>
        <input id="modal-credenv" placeholder="credential_env (ex: NVIDIA_API_KEY)" style="..."/>
      </div>
    `, [
      { label: 'cancelar', class: 'ghost-btn', action: () => this.closeModal() },
      { label: 'salvar', class: 'primary-btn', action: () => this.saveModel() },
    ]);
  }

  async saveModel() {
    const task = $('#modal-task').value;
    const provider = $('#modal-provider').value.trim();
    const modelId = $('#modal-modelid').value.trim();
    const baseUrl = $('#modal-baseurl').value.trim();
    const credEnv = $('#modal-credenv').value.trim();
    if (!provider || !modelId || !baseUrl || !credEnv) {
      this.toast('todos os campos obrigatórios', 'error');
      return;
    }
    try { await this.api.modelSet(task, provider, modelId, baseUrl, credEnv); } catch {}
    $(`#m-${task}`).textContent = `${provider}/${modelId}`;
    $(`#m-${task}`).classList.remove('empty');
    this.closeModal();
    this.toast(`${task} → ${provider}/${modelId}`, 'success');
  }

  // ===== Modal =====
  openModal(title, bodyHtml, footerButtons = []) {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML = bodyHtml;
    const footer = $('#modal-footer');
    footer.innerHTML = '';
    for (const btn of footerButtons) {
      const el = document.createElement('button');
      el.className = btn.class;
      el.textContent = btn.label;
      el.onclick = btn.action;
      footer.appendChild(el);
    }
    $('#modal-backdrop').classList.add('open');
  }

  closeModal() {
    $('#modal-backdrop').classList.remove('open');
  }

  // ===== Palette =====
  onGlobalKeydown(e) {
    if (e.key === '/' && document.activeElement !== $('#composer') && document.activeElement !== $('#palette-input')) {
      e.preventDefault();
      this.openPalette();
    }
    if (e.key === 'Escape') {
      this.closePalette();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      this.togglePalette();
    }
  }

  togglePalette() {
    $('#palette').classList.toggle('open');
    if ($('#palette').classList.contains('open')) {
      $('#palette-input').focus();
      this.updatePaletteResults('');
    }
  }

  openPalette() { this.togglePalette(); }
  closePalette() { $('#palette').classList.remove('open'); }

  updatePaletteResults(query) {
    const all = [
      { glyph: '⚡', name: 'modo solo', cmd: 'engine=mimo', action: () => {} },
      { glyph: '🎲', name: 'modo speculative (max)', cmd: 'engine=mimo', action: () => {} },
      { glyph: '👥', name: 'ativar squad engineering', cmd: '/aiox-squad activate engineering', action: () => this.activateSquad('engineering') },
      { glyph: '🔬', name: 'ativar squad research', cmd: '/aiox-squad activate research', action: () => this.activateSquad('research') },
      { glyph: '🎯', name: 'ativar squad product', cmd: '/aiox-squad activate product', action: () => this.activateSquad('product') },
      { glyph: '🚨', name: 'ativar squad incident', cmd: '/aiox-squad activate incident', action: () => this.activateSquad('incident') },
      { glyph: '🧬', name: 'ativar squad data-ml', cmd: '/aiox-squad activate data-ml', action: () => this.activateSquad('data-ml') },
      { glyph: '📈', name: 'ativar squad growth', cmd: '/aiox-squad activate growth', action: () => this.activateSquad('growth') },
      { glyph: '💰', name: 'ativar squad finance', cmd: '/aiox-squad activate finance', action: () => this.activateSquad('finance') },
      { glyph: '🎧', name: 'ativar squad support', cmd: '/aiox-squad activate support', action: () => this.activateSquad('support') },
      { glyph: '🧠', name: 'mostrar estratégia', cmd: '/strategy', action: () => {} },
      { glyph: '🔍', name: 'buscar memória', cmd: '/memory search', action: () => this.switchView('memory') },
      { glyph: '🌐', name: 'abrir browser', cmd: '/hermes browser', action: () => {} },
      { glyph: '⚙️', name: 'configurações', cmd: '/config', action: () => this.switchView('settings') },
    ];
    const q = query.toLowerCase();
    const filtered = q ? all.filter(c => c.name.toLowerCase().includes(q) || c.cmd.toLowerCase().includes(q)) : all;
    const results = $('#palette-results');
    results.innerHTML = '';
    filtered.forEach((c, i) => {
      const item = document.createElement('div');
      item.className = 'palette-item' + (i === 0 ? ' active' : '');
      item.innerHTML = `
        <span class="glyph">${c.glyph}</span>
        <span>${c.name}</span>
        <span class="cmd">${c.cmd}</span>
      `;
      item.onclick = () => { c.action(); this.closePalette(); };
      results.appendChild(item);
    });
  }

  onPaletteKeydown(e) {
    if (e.key === 'Enter') {
      const active = $('#palette-results .palette-item.active');
      if (active) active.click();
    }
  }

  // ===== Utils =====
  escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  appendToolCall(tc) {
    const scroll = $('#chat-scroll');
    const el = document.createElement('div');
    el.className = 'msg tool-msg';
    const result = tc.result || tc.error;
    el.innerHTML = `
      <div class="msg-avatar">🔧</div>
      <div class="msg-body">
        <div class="msg-meta">
          <span class="role">tool: ${tc.tool}</span>
          <span>${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        <div class="msg-content"><pre><code>${this.escapeHtml(JSON.stringify(result, null, 2).slice(0, 1500))}</code></pre></div>
      </div>
    `;
    scroll.appendChild(el);
    scroll.scrollTop = scroll.scrollHeight;
  }

  toast(text, type = 'info') {
    const c = $('#toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = text;
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }
}

// bootstrap
window.addEventListener('DOMContentLoaded', () => {
  new AlbertoApp();
});