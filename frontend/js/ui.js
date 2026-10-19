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
    this.conversationId = sessionStorage.getItem('alberto.conversationId') || null;
    this.isSending = false;
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

      $('#status-dot').classList.remove('error');
      $('#status-text').textContent = 'online';
      await Promise.allSettled([
        this.loadSquads(), this.loadShortcuts(), this.loadMemory(),
        this.loadTools(), this.loadModels(),
      ]);
      this.updateGreeting();
    } catch (e) {
      $('#status-dot').classList.remove('online');
      $('#status-dot').classList.add('error');
      $('#status-text').textContent = 'offline';
      this.toast(`Backend indisponível: ${e.message}`, 'error');
    }
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

    if (this.isSending) return;
    this.isSending = true;
    $('#send-btn').disabled = true;
    $('#chat-empty').style.display = 'none';

    // Add user message
    this.appendMessage('user', text);

    composer.value = '';
    this.autoresizeComposer();

    // Strategy decision
    let strategy = { mode: 'solo', engine: 'mimo', task_routing: 'code' };
    try {
      strategy = await this.api.strategy(text);
    } catch (error) {
      this.toast(`Não foi possível obter a estratégia: ${error.message}`, 'error');
    }

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
          responseText = `Erro do backend: ${chunk.error || 'falha não especificada'}`;
        }
      }, this.conversationId);
      if (finalConvId) {
        this.conversationId = finalConvId;
        sessionStorage.setItem('alberto.conversationId', finalConvId);
      }
      if (!responseText.trim()) throw new Error('O backend terminou o stream sem conteúdo.');
    } catch (e) {
      responseText = `Não foi possível obter resposta real do Alberto: ${e.message}`;
      $('#status-dot').classList.add('error');
      $('#status-dot').classList.remove('online');
      $('#status-text').textContent = 'erro de API';
    } finally {
      typing.remove();
      this.isSending = false;
      $('#send-btn').disabled = false;
    }

    this.appendMessage('assistant', responseText, finalStrategy);

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
    if (this.isSending) {
      this.toast('Aguarde a resposta atual antes de limpar a conversa.', 'info');
      return;
    }
    $('#chat-scroll').innerHTML = '';
    $('#chat-empty').style.display = 'flex';
    this.conversationId = null;
    sessionStorage.removeItem('alberto.conversationId');
  }

  // ===== Voice & Upload =====
  toggleVoice() { this.toast('A chamada de voz ainda não está implementada.', 'info'); }
  uploadFile() {
    this.toast('O envio de ficheiros ainda não está ligado ao backend; nenhum ficheiro foi enviado.', 'info');
  }
  takeScreenshot() { this.toast('A captura de screenshot ainda não está implementada.', 'info'); }
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
      this.toast('Hermes inicia automaticamente quando uma ferramenta compatível é chamada; este cartão não altera o backend.', 'info');
    } else if (engine === 'mimo') {
      this.toast('MiMo é gerido pelo runtime; este cartão é apenas informativo.', 'info');
    }
  }

  // ===== Squads =====
  async loadSquads() {
    try {
      const data = await this.api.squadList();
      this.squads = Array.isArray(data) ? data : (data.squads || []);
      this.renderSquads();
      this.updateSquadPanel();
    } catch (error) {
      this.squads = [];
      this.renderSquads();
      this.toast(`Não foi possível carregar squads: ${error.message}`, 'error');
      throw error;
    }
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
    try {
      const result = await this.api.squadActivate(name);
      if (!result?.ok) throw new Error('O backend não confirmou a ativação.');
      this.activeSquad = result.active || name;
      this.toast(`Squad "${this.activeSquad}" ativado`, 'success');
      this.updateSquadPanel();
      this.renderSquads();
    } catch (error) {
      this.toast(`Falha ao ativar squad: ${error.message}`, 'error');
    }
  }

  async hibernateSquad() {
    try {
      const result = await this.api.squadHibernate();
      if (!result?.ok) throw new Error('O backend não confirmou a hibernação.');
      this.activeSquad = null;
      this.toast('Squad hibernado', 'success');
      this.updateSquadPanel();
      this.renderSquads();
    } catch (error) {
      this.toast(`Falha ao hibernar squad: ${error.message}`, 'error');
    }
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
    try {
      const data = await this.api.memoryList();
      this.memory = Array.isArray(data) ? data : (data.items || []);
      this.renderMemory(this.memory);
    } catch (error) {
      this.memory = [];
      this.renderMemory([]);
      this.toast(`Não foi possível carregar memória: ${error.message}`, 'error');
      throw error;
    }
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
      this.renderMemory(Array.isArray(hits) ? hits : (hits.items || []));
    } catch (error) {
      this.toast(`Falha na pesquisa de memória: ${error.message}`, 'error');
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
    try {
      const result = await this.api.memorySet(key, value, tags);
      if (!result?.ok) throw new Error('O backend não confirmou a gravação.');
      await this.loadMemory();
      this.closeModal();
      this.toast(`"${key}" guardado na memória real`, 'success');
    } catch (error) {
      this.toast(`Falha ao guardar memória: ${error.message}`, 'error');
    }
  }

  // ===== Shortcuts =====
  async loadShortcuts() {
    try {
      const data = await this.api.shortcutList();
      this.shortcuts = data && typeof data === 'object' ? data : {};
      this.renderShortcuts();
    } catch (error) {
      this.shortcuts = {};
      this.renderShortcuts();
      this.toast(`Não foi possível carregar atalhos: ${error.message}`, 'error');
      throw error;
    }
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
    try {
      const data = await this.api.toolsList();
      const tools = Array.isArray(data) ? data : (data.tools || []);
      const grid = $('#tools-grid');
      grid.innerHTML = '';
      for (const tool of tools) {
        const name = tool.name || tool.function?.name || 'tool';
        const desc = tool.description || tool.function?.description || '';
        const card = document.createElement('div');
        card.className = 'tool-card';
        card.innerHTML = `
          <div class="tool-header"><div class="tool-name">${this.escapeHtml(name)}</div><div class="tool-engine">backend</div></div>
          <div class="tool-desc">${this.escapeHtml(desc)}</div>
          <div class="tool-status"><span class="dot"></span><span>registada no backend</span></div>`;
        grid.appendChild(card);
      }
      if (!tools.length) grid.innerHTML = '<div class="shortcut-empty">O backend não registou ferramentas.</div>';
    } catch (error) {
      $('#tools-grid').innerHTML = '<div class="shortcut-empty">Não foi possível carregar ferramentas reais.</div>';
      this.toast(`Falha ao carregar ferramentas: ${error.message}`, 'error');
      throw error;
    }
  }

  async loadModels() {
    try {
      const models = await this.api.modelList();
      const container = $('#settings-models');
      container.innerHTML = '';
      for (const model of models) {
        const row = document.createElement('div');
        row.className = 'kv-row';
        row.innerHTML = `<span class="lbl">${this.escapeHtml(model.task)}</span><span class="val">${this.escapeHtml(model.provider)}/${this.escapeHtml(model.model_id)}</span>`;
        container.appendChild(row);
        const status = document.querySelector(`#m-${CSS.escape(model.task)}`);
        if (status) {
          status.textContent = `${model.provider}/${model.model_id}`;
          status.classList.remove('empty');
        }
      }
      if (!models.length) container.textContent = 'Nenhum modelo configurado no backend.';
    } catch (error) {
      $('#settings-models').textContent = 'Não foi possível carregar os modelos.';
      this.toast(`Falha ao carregar modelos: ${error.message}`, 'error');
      throw error;
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
    try {
      const result = await this.api.modelSet(task, provider, modelId, baseUrl, credEnv);
      if (!result?.ok) throw new Error('O backend não confirmou a configuração.');
      await this.loadModels();
      this.closeModal();
      this.toast(`Modelo ${task} guardado no backend.`, 'success');
    } catch (error) {
      this.toast(`Falha ao guardar modelo: ${error.message}`, 'error');
    }
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