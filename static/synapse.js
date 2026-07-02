const DEFAULT_LAYOUT = 4;

// Connection resilience: the heartbeat keeps idle sockets alive through
// proxy idle-timeouts; the watchdog force-reconnects half-open sockets that
// silently stop delivering frames; reconnects back off exponentially with
// jitter so a gateway restart doesn't trigger a thundering herd.
const HEARTBEAT_MS = 20000;
const WATCHDOG_CHECK_MS = 5000;
const WATCHDOG_STALL_MS = 35000;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 30000;

const state = {
  agents: [],
  panes: [],
  ws: null,
  wsEpoch: 0,
  wsAttempts: 0,
  lastFrameAt: 0,
  reconnectTimer: null,
  heartbeatTimer: null,
  watchdogTimer: null,
  // Per-TAB client id (sessionStorage, like v1): the hub keys connections by
  // clientId, so a shared localStorage id makes multiple tabs evict each
  // other's sockets in an endless connect/disconnect fight.
  clientId: sessionStorage.getItem('synapse.clientId') || makeId(),
  focusPane: Number.parseInt(localStorage.getItem('synapse.focusPane') || '0', 10),
  models: [],
  modelPresets: { fast: '', balanced: '', deep: '' },
  sessions: {
    items: [],
    filtered: [],
    query: '',
    open: false,
    lastLoadedAt: '',
  },
  voice: {
    sessions: [],
    timer: null,
    error: '',
  },
};

sessionStorage.setItem('synapse.clientId', state.clientId);
localStorage.removeItem('synapse.clientId'); // retire the shared cross-tab id

document.addEventListener('DOMContentLoaded', () => {
  setupShell();
  loadModels();
  loadFleet();
  loadVoiceSessions();
  connectSynapse();
});

function setupShell() {
  on('synapse-layout', 'change', (event) => {
    setPaneCount(Number.parseInt(event.target.value, 10));
  });
  on('synapse-reconnect', 'click', reconnectNow);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !isSocketOpen()) reconnectNow();
  });
  window.addEventListener('online', () => {
    if (!isSocketOpen()) reconnectNow();
  });
  window.addEventListener('message', onVoiceClientMessage);
  on('synapse-sessions', 'click', () => openSessionsDrawer(true));
  on('synapse-sessions-close', 'click', closeSessionsDrawer);
  on('synapse-sessions-refresh', 'click', loadSessionsList);
  on('synapse-sessions-filter', 'input', (event) => {
    applySessionsFilter(event.target.value);
  });
  on('synapse-sessions-overlay', 'click', (event) => {
    if (event.target.id === 'synapse-sessions-overlay') closeSessionsDrawer();
  });
  on('synapse-sessions-list', 'click', onSessionsListClick);
  setPaneCount(savedPaneCount());
}

function on(id, eventName, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(eventName, handler);
}

function makeId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function savedPaneCount() {
  return Number.parseInt(localStorage.getItem('synapse.panes') || DEFAULT_LAYOUT, 10);
}

function setPaneCount(count) {
  localStorage.setItem('synapse.panes', String(count));
  document.getElementById('synapse-layout').value = String(count);
  while (state.panes.length < count) {
    state.panes.push(newPane(state.panes.length));
  }
  state.panes = state.panes.slice(0, count);
  if (state.focusPane >= state.panes.length) state.focusPane = 0;
  renderGrid();
  autoAssignAgents();
}

function savedPaneModel(id) {
  const key = `synapse.pane.${id}.model`;
  const migratedKey = `${key}.longDefaultMigrated`;
  const model = localStorage.getItem(key) || '';
  if (!localStorage.getItem(migratedKey) && (model === 'local-fast' || model === 'local/local-fast')) {
    localStorage.setItem(key, 'local/local-long');
    localStorage.setItem(migratedKey, '1');
    return 'local/local-long';
  }
  if (!localStorage.getItem(migratedKey)) localStorage.setItem(migratedKey, '1');
  return model;
}

function newPane(id) {
  return {
    id,
    agentId: localStorage.getItem(`synapse.pane.${id}.agent`) || '',
    sessionKey: localStorage.getItem(`synapse.pane.${id}.sessionKey`) || '',
    model: savedPaneModel(id),
    modelExplicit: false,
    reasoning: localStorage.getItem(`synapse.pane.${id}.reasoning`) === '1',
    pendingModel: '',
    messages: [],
    streamText: '',
    pendingRunId: '',
    pendingRunStatus: '',
    draft: '',
    voiceExpanded: false,
    voiceFrontendState: '',
  };
}

async function loadFleet() {
  try {
    const res = await fetch('/api/synapse/fleet');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    updateAgents(body.agents || []);
  } catch (error) {
    showToast(`Fleet load failed: ${error.message}`, 'error');
  }
}

async function loadModels() {
  try {
    const res = await fetch('/api/synapse/models');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    state.models = body.models || [];
    state.modelPresets = body.presets || state.modelPresets;
    updatePaneHeaders();
  } catch (error) {
    showToast(`Model catalog load failed: ${error.message}`, 'error');
  }
}

function connectSynapse() {
  clearTimeout(state.reconnectTimer);
  state.reconnectTimer = null;
  clearConnectionTimers();
  // Each connection gets an epoch; callbacks from superseded sockets no-op
  // so a stale close can't double-schedule reconnects or clobber status.
  const epoch = ++state.wsEpoch;
  if (state.ws) {
    try { state.ws.close(); } catch (error) { /* already closed */ }
  }
  setStatus('Connecting');
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/synapse/ws?clientId=${state.clientId}`);
  state.ws = ws;
  ws.addEventListener('open', () => { if (epoch === state.wsEpoch) onOpen(); });
  ws.addEventListener('message', (event) => { if (epoch === state.wsEpoch) onFrame(event); });
  ws.addEventListener('close', () => { if (epoch === state.wsEpoch) onSocketClose(); });
  ws.addEventListener('error', () => { if (epoch === state.wsEpoch) setStatus('Error'); });
}

function reconnectNow() {
  state.wsAttempts = 0;
  connectSynapse();
}

function onOpen() {
  setStatus('Connected');
  state.wsAttempts = 0;
  state.lastFrameAt = Date.now();
  state.panes.forEach((pane) => {
    if (pane.agentId) sendFrame({ type: 'subscribe', agentId: pane.agentId });
  });
  state.heartbeatTimer = setInterval(() => {
    if (isSocketOpen()) state.ws.send(JSON.stringify({ type: 'ping' }));
  }, HEARTBEAT_MS);
  state.watchdogTimer = setInterval(() => {
    if (Date.now() - state.lastFrameAt > WATCHDOG_STALL_MS) {
      // Half-open socket: not even a pong arrived — force a reconnect.
      try { state.ws.close(); } catch (error) { /* already closed */ }
    }
  }, WATCHDOG_CHECK_MS);
}

function onSocketClose() {
  setStatus('Disconnected');
  clearConnectionTimers();
  scheduleReconnect();
}

function clearConnectionTimers() {
  clearInterval(state.heartbeatTimer);
  clearInterval(state.watchdogTimer);
  state.heartbeatTimer = null;
  state.watchdogTimer = null;
}

function scheduleReconnect() {
  if (state.reconnectTimer) return;
  const base = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** state.wsAttempts);
  const delay = base + Math.random() * base * 0.3;
  state.wsAttempts += 1;
  state.reconnectTimer = setTimeout(() => {
    state.reconnectTimer = null;
    connectSynapse();
  }, delay);
}

function onFrame(event) {
  state.lastFrameAt = Date.now();
  const frame = JSON.parse(event.data);
  if (frame.type === 'connected' || frame.type === 'status_all') {
    updateAgents((frame.payload || {}).agents || []);
    return;
  }
  if (frame.type === 'status') {
    updateAgent(frame.payload);
    return;
  }
  if (frame.type === 'subscribed' || frame.type === 'history') {
    setHistory(frame.agentId, (frame.payload || {}).history || (frame.payload || {}).messages || []);
    return;
  }
  if (frame.type === 'ack') {
    markAck(frame.agentId, frame.payload || {}, frame.paneId || (frame.payload || {}).paneId || '');
    return;
  }
  if (frame.type === 'voice_user') {
    appendVoiceUserMessage(frame.agentId, frame.payload || {}, frame.paneId || (frame.payload || {}).paneId || '');
    return;
  }
  if (frame.type === 'chunk') {
    appendChunk(frame.agentId, (frame.payload || {}).text || '', frame.paneId || (frame.payload || {}).paneId || '');
    return;
  }
  if (frame.type === 'run_heartbeat') {
    updateRunHeartbeat(frame.agentId, frame.payload || {}, frame.paneId || (frame.payload || {}).paneId || '');
    return;
  }
  if (frame.type === 'message') {
    appendAgentMessage(frame.agentId, frame.payload || {}, frame.paneId || (frame.payload || {}).paneId || '');
    return;
  }
  if (frame.type === 'model_set') {
    confirmModel(frame.agentId, (frame.payload || {}).model || '');
    return;
  }
  if (frame.type === 'reset') {
    appendSystem(frame.agentId, 'Session reset — fresh context.');
    return;
  }
  if (frame.type === 'aborted') {
    state.panes.filter((pane) => pane.agentId === frame.agentId).forEach((pane) => {
      pane.streamText = '';
      pane.pendingRunId = '';
      pane.pendingRunStatus = '';
      renderPaneMessages(pane);
    });
    appendSystem(frame.agentId, 'Run aborted.');
    return;
  }
  if (frame.type === 'error') {
    if ((frame.payload || {}).operation === 'set_model' && frame.agentId) {
      clearPendingModel(frame.agentId);
    }
    appendSystem(frame.agentId, (frame.payload || {}).error || 'Unknown error');
  }
}

function updateAgents(agents) {
  state.agents = agents.map((agent) => {
    const current = state.agents.find((row) => row.agentId === (agent.agentId || agent.id)) || {};
    return normalizeAgent(agent, current);
  });
  state.panes.forEach((pane) => {
    if (pane.agentId && !pane.sessionKey) pane.sessionKey = currentAgentSessionKey(pane.agentId);
  });
  renderAgentStrip();
  updatePaneAgentSelects();
  updatePaneHeaders();
  autoAssignAgents();
}

function normalizeAgent(agent, current = {}) {
  const model = agent.model || current.model || '';
  const contextUsed = Number(agent.contextUsed ?? agent.totalTokens ?? current.contextUsed ?? 0);
  const contextMax = modelContextWindow(model) || Number(agent.contextMax ?? current.contextMax ?? 200000);
  const providedPct = Number(agent.contextPct ?? current.contextPct ?? 0);
  const contextPct = contextMax ? (contextUsed / contextMax) * 100 : providedPct;
  return {
    agentId: agent.agentId || agent.id,
    name: agent.name || agent.agentId || agent.id,
    state: agent.state || 'idle',
    contextPct,
    contextUsed,
    contextMax,
    sessionKey: agent.sessionKey || agent.session_key || current.sessionKey || '',
    model,
    defaultModel: agent.defaultModel || current.defaultModel || model,
    sessionModel: agent.sessionModel || current.sessionModel || '',
    org: agent.org || 'internal',
  };
}

function updateAgent(agent) {
  const agentId = agent.agentId || agent.id;
  const index = state.agents.findIndex((candidate) => candidate.agentId === agentId);
  const row = normalizeAgent(agent, index >= 0 ? state.agents[index] : {});
  if (index >= 0) state.agents[index] = { ...state.agents[index], ...row };
  renderAgentStrip();
  updatePaneHeaders();
}

function renderAgentStrip() {
  const strip = document.getElementById('synapse-agent-strip');
  strip.innerHTML = '';
  state.agents.forEach((agent) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `synapse-agent-chip ${agent.state}`;
    chip.textContent = `${agent.name} ${tokenCountText(agent)}`;
    chip.title = tokenCountTitle(agent);
    chip.addEventListener('click', () => assignFocusedOrFirst(agent.agentId));
    strip.appendChild(chip);
  });
}

function renderGrid() {
  const grid = document.getElementById('synapse-grid');
  grid.dataset.count = String(state.panes.length);
  grid.innerHTML = '';
  state.panes.forEach((pane) => grid.appendChild(paneElement(pane)));
  updatePaneHeaders();
}

function paneElement(pane) {
  const el = document.createElement('section');
  el.className = 'synapse-pane';
  el.dataset.paneId = String(pane.id);
  el.innerHTML = `
    <div class="synapse-pane-header">
      <select class="synapse-agent-select" data-ref="agent"></select>
      <select class="synapse-model-select" data-ref="model"></select>
      <div class="synapse-preset-group" data-ref="presets">
        <button type="button" data-preset="fast" title="Fast model">F</button>
        <button type="button" data-preset="balanced" title="Balanced model">B</button>
        <button type="button" data-preset="deep" title="Deep model">D</button>
      </div>
      <span class="synapse-pane-state" data-ref="state">idle</span>
      <span class="synapse-token-count" data-ref="tokens" title="Token usage">0/200,000</span>
      <button type="button" data-action="reasoning">R:<span data-ref="reasoning">Off</span></button>
      <button type="button" data-action="new">New</button>
      <button type="button" data-action="voice" data-ref="voiceButton">Talk</button>
      <button type="button" data-action="reset">Reset</button>
      <button type="button" data-action="abort">Abort</button>
      <button type="button" data-action="clear">Clear</button>
    </div>
    <div class="synapse-terminal" data-ref="terminal"></div>
    <div class="synapse-voice-status" data-ref="voice" hidden></div>
    <div class="synapse-voice-client" data-ref="voiceClient" hidden></div>
    <form class="synapse-input-row">
      <span>&gt;</span>
      <textarea rows="2" data-ref="input" placeholder="Message agent..."></textarea>
      <button type="submit">Send</button>
    </form>
  `;
  wirePane(el, pane);
  renderMessages(pane, el.querySelector('[data-ref="terminal"]'));
  renderVoiceStatus(pane, el.querySelector('[data-ref="voice"]'));
  return el;
}

function wirePane(el, pane) {
  const select = el.querySelector('[data-ref="agent"]');
  const modelSelect = el.querySelector('[data-ref="model"]');
  const input = el.querySelector('[data-ref="input"]');
  populateAgentSelect(select, pane.agentId);
  populateModelSelect(modelSelect, pane.model || currentAgentModel(pane.agentId));
  input.value = pane.draft || '';
  el.addEventListener('pointerdown', () => setFocusPane(pane.id));
  el.addEventListener('focusin', () => setFocusPane(pane.id));
  select.addEventListener('change', () => assignPane(pane.id, select.value));
  modelSelect.addEventListener('change', () => setPaneModel(pane, modelSelect.value));
  el.querySelectorAll('[data-preset]').forEach((button) => {
    button.addEventListener('click', () => setPaneModel(pane, state.modelPresets[button.dataset.preset] || ''));
  });
  el.querySelector('[data-action="reasoning"]').addEventListener('click', () => toggleReasoning(pane));
  el.querySelector('[data-action="new"]').addEventListener('click', () => newSession(pane));
  el.querySelector('[data-action="voice"]').addEventListener('click', () => toggleVoiceSession(pane));
  el.querySelector('[data-ref="voice"]').addEventListener('click', (event) => onVoiceStatusClick(event, pane));
  el.querySelector('[data-action="reset"]').addEventListener('click', () => resetSession(pane));
  el.querySelector('[data-action="abort"]').addEventListener('click', () => agentAction(pane, 'abort'));
  el.querySelector('[data-action="clear"]').addEventListener('click', () => clearPane(pane));
  input.addEventListener('input', () => {
    pane.draft = input.value;
  });
  input.addEventListener('keydown', onPaneInputKeydown);
  el.querySelector('form').addEventListener('submit', (event) => {
    event.preventDefault();
    sendPaneMessage(pane, input);
  });
}

function onPaneInputKeydown(event) {
  if (event.key !== 'Enter' || event.altKey) return;
  event.preventDefault();
  event.target.closest('form').requestSubmit();
}

function populateAgentSelect(select, selected) {
  select.innerHTML = '<option value="">Select agent</option>';
  state.agents.forEach((agent) => {
    const option = document.createElement('option');
    option.value = agent.agentId;
    option.textContent = `${agent.name} (${agent.agentId})`;
    select.appendChild(option);
  });
  select.value = selected;
}

function updatePaneAgentSelects() {
  document.querySelectorAll('.synapse-pane').forEach((el) => {
    const pane = state.panes[Number.parseInt(el.dataset.paneId, 10)];
    const select = el.querySelector('[data-ref="agent"]');
    if (pane && select) populateAgentSelect(select, pane.agentId);
  });
}

function populateModelSelect(select, selected) {
  select.innerHTML = '<option value="">Model</option>';
  state.models.forEach((model) => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = model.label || model.id;
    select.appendChild(option);
  });
  select.value = resolveModelId(selected);
}

function updatePaneHeaders() {
  document.querySelectorAll('.synapse-pane').forEach((el) => {
    const pane = state.panes[Number.parseInt(el.dataset.paneId, 10)];
    const agent = findAgent(pane.agentId);
    const tokensEl = el.querySelector('[data-ref="tokens"]');
    el.querySelector('[data-ref="state"]').textContent = agent ? agent.state : 'unassigned';
    tokensEl.textContent = agent ? tokenCountText(agent) : '0/0';
    tokensEl.title = agent ? tokenCountTitle(agent) : 'No agent assigned';
    const pct = agent ? Number(agent.contextPct || 0) : 0;
    tokensEl.classList.toggle('warn', pct >= 90);
    if (pct >= 90) {
      tokensEl.title += ' — context near/over limit: Reset the session or switch to a longer-context model';
    }
    el.querySelector('[data-ref="reasoning"]').textContent = pane.reasoning ? 'On' : 'Off';
    el.querySelector('[data-action="reasoning"]').classList.toggle('active', Boolean(pane.reasoning));
    renderVoiceControl(pane, el);
    el.classList.toggle('is-focused', pane.id === state.focusPane);
    syncModelSelect(el, pane, agent);
    renderVoiceStatus(pane, el.querySelector('[data-ref="voice"]'));
    renderVoiceClient(pane, el.querySelector('[data-ref="voiceClient"]'));
  });
}

function syncModelSelect(el, pane, agent) {
  const select = el.querySelector('[data-ref="model"]');
  const selected = pane.pendingModel || pane.model || (agent ? agent.model : '');
  populateModelSelect(select, selected);
  select.disabled = !pane.agentId || pane.pendingModel || !state.models.length;
  select.title = pane.pendingModel ? `Updating to ${modelDisplayName(pane.pendingModel)}` : '';
}

function autoAssignAgents() {
  if (state.agents.length === 0) return;
  state.panes.forEach((pane, index) => {
    if (!pane.agentId && state.agents[index]) {
      assignPane(pane.id, state.agents[index].agentId, { quiet: true });
    }
  });
}

function assignFocusedOrFirst(agentId) {
  const empty = state.panes.find((pane) => !pane.agentId);
  const focused = state.panes[state.focusPane];
  assignPane((focused || empty || state.panes[0]).id, agentId);
}

function assignPane(paneId, agentId, options = {}) {
  const pane = state.panes[paneId];
  const voiceSession = latestLiveVoiceSession(pane);
  if (voiceSession) stopVoiceSession({ ...pane }, voiceSession, { quiet: true });
  pane.agentId = agentId;
  pane.sessionKey = currentAgentSessionKey(agentId);
  pane.model = currentAgentModel(agentId);
  pane.modelExplicit = false;
  pane.pendingModel = '';
  pane.messages = [];
  pane.streamText = '';
  pane.pendingRunId = '';
  pane.pendingRunStatus = '';
  localStorage.setItem(`synapse.pane.${paneId}.agent`, agentId);
  localStorage.setItem(`synapse.pane.${paneId}.sessionKey`, pane.sessionKey);
  localStorage.setItem(`synapse.pane.${paneId}.model`, pane.model);
  if (agentId && isSocketOpen()) sendFrame({ type: 'subscribe', agentId });
  renderGrid();
}

function setFocusPane(paneId) {
  state.focusPane = paneId;
  localStorage.setItem('synapse.focusPane', String(paneId));
  updatePaneHeaders();
}

function setHistory(agentId, messages) {
  state.panes.filter((pane) => pane.agentId === agentId).forEach((pane) => {
    pane.messages = messages.map((message) => ({
      role: message.role || 'assistant',
      text: message.text || '',
      ts: message.ts || new Date().toISOString(),
    }));
    pane.streamText = '';
    pane.pendingRunId = ''; // history replay supersedes any awaited reply
    pane.pendingRunStatus = '';
    renderPaneMessages(pane);
  });
}

function currentAgentModel(agentId) {
  const agent = findAgent(agentId);
  return agent ? resolveModelId(agent.model) : '';
}

function currentAgentSessionKey(agentId) {
  const agent = findAgent(agentId);
  return agent ? agent.sessionKey : '';
}

function paneSessionKey(pane) {
  return pane.sessionKey || currentAgentSessionKey(pane.agentId);
}

function resolveModelId(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const match = state.models.find((model) => {
    return model.id === raw || model.shortId === raw || model.alias === raw;
  });
  return match ? match.id : raw;
}

function modelDisplayName(value) {
  const resolved = resolveModelId(value);
  const match = state.models.find((model) => model.id === resolved);
  return match ? match.label : resolved;
}

function modelContextWindow(value) {
  const resolved = resolveModelId(value);
  const match = state.models.find((model) => model.id === resolved);
  return match ? Number(match.contextWindow || 0) : 0;
}

async function setPaneModel(pane, model) {
  const resolved = resolveModelId(model);
  if (!pane.agentId || !resolved) return;
  if (resolved === resolveModelId(pane.model || currentAgentModel(pane.agentId))) return;
  pane.pendingModel = resolved;
  updatePaneHeaders();
  if (isSocketOpen()) {
    sendFrame({ type: 'set_model', agentId: pane.agentId, payload: { model: resolved } });
    return;
  }
  await setPaneModelViaRest(pane, resolved);
}

async function setPaneModelViaRest(pane, model) {
  try {
    const res = await fetch(`/api/synapse/agent/${encodeURIComponent(pane.agentId)}/model`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    confirmModel(pane.agentId, body.model || model);
  } catch (error) {
    clearPendingModel(pane.agentId);
    showToast(`Model update failed: ${error.message}`, 'error');
  }
}

function confirmModel(agentId, model) {
  const resolved = resolveModelId(model);
  state.panes.filter((pane) => pane.agentId === agentId).forEach((pane) => {
    pane.model = resolved;
    pane.modelExplicit = true;
    pane.pendingModel = '';
    localStorage.setItem(`synapse.pane.${pane.id}.model`, resolved);
  });
  const agent = findAgent(agentId);
  if (agent) {
    agent.model = resolved;
    const contextMax = modelContextWindow(resolved);
    if (contextMax) {
      agent.contextMax = contextMax;
      agent.contextPct = agent.contextUsed ? (agent.contextUsed / contextMax) * 100 : 0;
    }
  }
  updatePaneHeaders();
  showToast(`Model updated for ${agentId}: ${modelDisplayName(resolved)}`, 'success');
}

function clearPendingModel(agentId) {
  state.panes.filter((pane) => pane.agentId === agentId).forEach((pane) => {
    pane.pendingModel = '';
  });
  updatePaneHeaders();
}

function sendPaneMessage(pane, input) {
  const text = input.value.trim();
  if (!pane.agentId || !text) return;
  appendLocalMessage(pane, { role: 'user', text, ts: new Date().toISOString() });
  const agent = findAgent(pane.agentId);
  if (agent && (agent.state === 'working' || agent.state === 'blocked')) {
    // Sending into a busy session queues behind the active run — say so
    // instead of looking dead (the gateway gives no queue feedback).
    appendLocalMessage(pane, {
      role: 'system',
      text: `${agent.name || pane.agentId} is mid-run — this message will queue behind the active run (Abort to jump the queue).`,
      ts: new Date().toISOString(),
    });
  }
  pane.pendingRunId = makeId();
  pane.pendingRunStatus = '';
  sendFrame({
    type: 'message',
    agentId: pane.agentId,
    payload: {
      text,
      clientMessageId: pane.pendingRunId,
      ...(pane.modelExplicit ? { model: pane.model } : {}),
    },
  });
  input.value = '';
  pane.draft = '';
}

function markAck(agentId, payload, paneId = '') {
  targetPanes(agentId, paneId).forEach((pane) => {
    pane.pendingRunId = payload.runId || pane.pendingRunId;
    renderPaneMessages(pane);
  });
}

function appendVoiceUserMessage(agentId, payload, paneId = '') {
  const text = String(payload.text || '').trim();
  if (!text) return;
  targetPanes(agentId, paneId).forEach((pane) => {
    pane.pendingRunId = payload.clientMessageId || pane.pendingRunId;
    appendLocalMessage(pane, { role: 'user', text, ts: new Date().toISOString() });
  });
}

function appendChunk(agentId, text, paneId = '') {
  targetPanes(agentId, paneId).forEach((pane) => {
    pane.streamText += text;
    pane.pendingRunStatus = '';
    renderPaneMessages(pane);
  });
}

function updateRunHeartbeat(agentId, payload, paneId = '') {
  targetPanes(agentId, paneId).forEach((pane) => {
    if (!pane.pendingRunId) return;
    if (payload.runId && pane.pendingRunId !== payload.runId) return;
    pane.pendingRunStatus = runHeartbeatText(payload);
    renderPaneMessages(pane);
  });
}

function runHeartbeatText(payload) {
  const elapsed = durationText(Number(payload.elapsedSeconds || 0));
  const quiet = durationText(Number(payload.quietSeconds || 0));
  if (!elapsed) return '... thinking';
  if (!quiet || quiet === elapsed) return `... thinking (${elapsed})`;
  return `... thinking (${elapsed}, quiet ${quiet})`;
}

function durationText(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const whole = Math.floor(seconds);
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const remainder = whole % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

function appendAgentMessage(agentId, payload, paneId = '') {
  targetPanes(agentId, paneId).forEach((pane) => {
    if (pane.streamText && !payload.text) {
      appendLocalMessage(pane, { role: 'assistant', text: pane.streamText, ts: new Date().toISOString() });
    } else if (payload.text) {
      appendLocalMessage(pane, { role: 'assistant', text: payload.text, ts: new Date().toISOString() });
    }
    pane.streamText = '';
    pane.pendingRunId = '';
    pane.pendingRunStatus = '';
    renderPaneMessages(pane);
  });
}

function targetPanes(agentId, paneId = '') {
  const id = String(paneId || '');
  if (id) return state.panes.filter((pane) => String(pane.id) === id && pane.agentId === agentId);
  return state.panes.filter((pane) => pane.agentId === agentId);
}

function appendSystem(agentId, text) {
  state.panes.filter((pane) => !agentId || pane.agentId === agentId).forEach((pane) => {
    pane.pendingRunId = ''; // an error ends the awaiting-reply placeholder
    pane.pendingRunStatus = '';
    appendLocalMessage(pane, { role: 'system', text, ts: new Date().toISOString() });
  });
  if (!agentId) showToast(text, 'error');
}

function appendLocalMessage(pane, message) {
  pane.messages.push(message);
  renderPaneMessages(pane);
}

function clearPane(pane) {
  pane.messages = [];
  pane.streamText = '';
  pane.pendingRunStatus = '';
  pane.pendingRunId = '';
  renderPaneMessages(pane);
}

function toggleReasoning(pane) {
  if (!pane.agentId) return;
  const next = !pane.reasoning;
  const text = next ? '/reasoning on' : '/reasoning off';
  if (!isSocketOpen()) {
    showToast('Synapse socket is not connected', 'error');
    return;
  }
  pane.reasoning = next;
  localStorage.setItem(`synapse.pane.${pane.id}.reasoning`, next ? '1' : '0');
  sendFrame({ type: 'message', agentId: pane.agentId, payload: { text, clientMessageId: makeId() } });
  appendLocalMessage(pane, { role: 'system', text: `Reasoning ${next ? 'on' : 'off'}`, ts: new Date().toISOString() });
  updatePaneHeaders();
}

function resetSession(pane) {
  if (!pane.agentId) return;
  clearPane(pane);
  appendLocalMessage(pane, {
    role: 'system',
    text: 'Resetting session (aborting any active run)…',
    ts: new Date().toISOString(),
  });
  agentAction(pane, 'reset');
}

function newSession(pane) {
  // "New" starts a real fresh session (abort + reset on the gateway);
  // "Clear" remains the local-only wipe.
  if (!pane.agentId) {
    clearPane(pane);
    return;
  }
  clearPane(pane);
  appendLocalMessage(pane, {
    role: 'system',
    text: 'Starting a new session…',
    ts: new Date().toISOString(),
  });
  agentAction(pane, 'reset');
}

function agentAction(pane, action) {
  if (!pane.agentId) return;
  sendFrame({ type: action, agentId: pane.agentId });
}

async function toggleVoiceSession(pane) {
  const session = latestLiveVoiceSession(pane);
  if (session) {
    await stopVoiceSession(pane, session);
    return;
  }
  await startVoiceSession(pane);
}

async function startVoiceSession(pane) {
  if (!pane.agentId) {
    showToast('Assign an agent before starting voice', 'error');
    return;
  }
  if (!canUseVoiceAudio()) {
    const text = voiceSecureContextMessage();
    appendLocalMessage(pane, { role: 'system', text, ts: new Date().toISOString() });
    showToast('Voice requires HTTPS for microphone access', 'error');
    updatePaneHeaders();
    return;
  }
  try {
    pane.voiceFrontendState = 'starting';
    updatePaneHeaders();
    const res = await fetch('/api/synapse/voice/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agentId: pane.agentId,
        clientId: state.clientId,
        paneId: String(pane.id),
        sessionKey: paneSessionKey(pane),
        model: pane.modelExplicit ? pane.model : '',
      }),
    });
    if (!res.ok) throw new Error(await responseError(res));
    const session = (await res.json()).session || {};
    pane.voiceExpanded = Boolean(session.publicUrl);
    pane.voiceFrontendState = session.publicUrl ? 'connecting' : '';
    upsertVoiceSession(session);
    startVoicePolling();
    appendLocalMessage(pane, {
      role: 'system',
      text: voiceStartMessage(pane.agentId, session),
      ts: new Date().toISOString(),
    });
  } catch (error) {
    pane.voiceFrontendState = 'error';
    updatePaneHeaders();
    showToast(`Voice start failed: ${error.message}`, 'error');
  }
}

async function stopVoiceSession(pane, session, options = {}) {
  disconnectVoiceClient(pane);
  try {
    const res = await fetch(`/api/synapse/voice/sessions/${encodeURIComponent(session.id)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(await responseError(res));
    const stopped = (await res.json()).session || {};
    pane.voiceExpanded = false;
    pane.voiceFrontendState = '';
    upsertVoiceSession(stopped);
    if (!options.quiet) {
      appendLocalMessage(pane, {
        role: 'system',
        text: `Voice bridge stopped for ${pane.agentId}`,
        ts: new Date().toISOString(),
      });
    }
  } catch (error) {
    showToast(`Voice stop failed: ${error.message}`, 'error');
  }
}

async function loadVoiceSessions() {
  try {
    const res = await fetch('/api/synapse/voice/sessions');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    state.voice.sessions = body.sessions || [];
    state.voice.error = '';
  } catch (error) {
    state.voice.error = error.message;
  }
  renderVoicePanels();
  if (hasLiveVoiceSession()) startVoicePolling();
  if (!hasLiveVoiceSession()) stopVoicePolling();
}

function startVoicePolling() {
  if (state.voice.timer) return;
  state.voice.timer = window.setInterval(loadVoiceSessions, 2000);
}

function stopVoicePolling() {
  if (!state.voice.timer) return;
  window.clearInterval(state.voice.timer);
  state.voice.timer = null;
}

function upsertVoiceSession(session) {
  if (!session.id) return;
  const index = state.voice.sessions.findIndex((row) => row.id === session.id);
  if (index >= 0) {
    state.voice.sessions[index] = session;
  } else {
    state.voice.sessions.push(session);
  }
  renderVoicePanels();
}

function renderVoicePanels() {
  document.querySelectorAll('.synapse-pane').forEach((el) => {
    const pane = state.panes[Number.parseInt(el.dataset.paneId, 10)];
    renderVoiceControl(pane, el);
    renderVoiceStatus(pane, el.querySelector('[data-ref="voice"]'));
    renderVoiceClient(pane, el.querySelector('[data-ref="voiceClient"]'));
  });
}

function renderVoiceControl(pane, el) {
  const button = el.querySelector('[data-ref="voiceButton"]');
  if (!button) return;
  const session = latestLiveVoiceSession(pane);
  button.textContent = session ? 'End' : 'Talk';
  button.classList.toggle('active', Boolean(session));
  button.disabled = !pane.agentId || pane.voiceFrontendState === 'starting';
  button.title = session ? 'End voice chat' : 'Start voice chat';
}

function renderVoiceStatus(pane, el) {
  if (!el) return;
  if (state.voice.error) {
    el.hidden = false;
    el.dataset.state = 'error';
    el.textContent = `voice status unavailable: ${state.voice.error}`;
    return;
  }
  const session = latestVoiceSession(pane);
  el.hidden = !session;
  if (!session) return;
  el.dataset.state = voiceLightState(pane, session);
  el.title = voiceStatusTitle(session);
  el.innerHTML = voiceStatusHtml(pane, session);
}

function renderVoiceClient(pane, el) {
  if (!el) return;
  const session = latestLiveVoiceSession(pane);
  const targetUrl = session ? voiceClientUrl(session.publicUrl, pane.agentId) : '';
  el.hidden = !session || !pane.voiceExpanded || !targetUrl;
  if (el.hidden) {
    el.innerHTML = '';
    return;
  }
  const frame = el.querySelector('iframe');
  if (frame && frame.src === targetUrl) return;
  el.innerHTML = '';
  el.appendChild(voiceClientFrame(pane, targetUrl));
}

function voiceClientFrame(pane, targetUrl) {
  const agentId = pane.agentId;
  const frame = document.createElement('iframe');
  frame.title = `Voice channel for ${agentId}`;
  frame.src = targetUrl;
  frame.allow = 'microphone; autoplay';
  frame.dataset.agentId = agentId;
  frame.dataset.paneId = String(pane.id);
  return frame;
}

function disconnectVoiceClient(pane) {
  const frame = document.querySelector(`.synapse-pane[data-pane-id="${pane.id}"] [data-ref="voiceClient"] iframe`);
  frame?.contentWindow?.postMessage({ type: 'etherVoice:disconnect' }, '*');
}

function onVoiceClientMessage(event) {
  const data = event.data || {};
  if (data.type !== 'etherVoice:status') return;
  const pane = paneForVoiceWindow(event.source);
  if (!pane) return;
  pane.voiceFrontendState = String(data.state || '');
  renderVoicePanels();
}

function paneForVoiceWindow(source) {
  const frames = document.querySelectorAll('.synapse-pane [data-ref="voiceClient"] iframe');
  for (const frame of frames) {
    if (frame.contentWindow !== source) continue;
    return state.panes.find((pane) => String(pane.id) === frame.dataset.paneId) || null;
  }
  return null;
}

function latestVoiceSession(pane) {
  if (!pane || !pane.agentId) return null;
  const sessionKey = paneSessionKey(pane);
  const matches = state.voice.sessions.filter((session) => {
    const sameAgent = session.agentId === pane.agentId;
    const sameClient = !session.clientId || session.clientId === state.clientId;
    const samePane = String(session.paneId || '') === String(pane.id);
    const sameSession = !sessionKey || session.sessionKey === sessionKey;
    return sameAgent && sameClient && samePane && sameSession;
  });
  matches.sort((left, right) => {
    const rightTime = Date.parse(right.updatedAt || right.createdAt || '');
    const leftTime = Date.parse(left.updatedAt || left.createdAt || '');
    return rightTime - leftTime;
  });
  return matches[0] || null;
}

function latestLiveVoiceSession(pane) {
  const session = latestVoiceSession(pane);
  if (!session) return null;
  return terminalVoiceStates().includes(String(session.state || '')) ? null : session;
}

function hasLiveVoiceSession() {
  return state.voice.sessions.some((session) => {
    return !terminalVoiceStates().includes(String(session.state || ''));
  });
}

function terminalVoiceStates() {
  return ['stopped', 'disconnected', 'error'];
}

function voiceStatusHtml(pane, session) {
  const heard = compactText(session.lastUserText || 'no transcript yet', 72);
  const assistant = compactText(session.lastAssistantText || '', 72);
  const parts = [
    `<span class="synapse-voice-dot" aria-hidden="true"></span>`,
    `<b>${escapeHtml(voiceDisplayState(pane, session))}</b>`,
    `voice ${escapeHtml(session.voice || '')}`,
    `heard: ${escapeHtml(heard)}`,
    `spoke: ${Number(session.sayCount || 0)}`,
  ];
  if (assistant) parts.push(`reply: ${escapeHtml(assistant)}`);
  if (session.error || session.lastOpenClawError) {
    parts.push(`error: ${escapeHtml(compactText(session.error || session.lastOpenClawError, 96))}`);
  }
  return parts.filter(Boolean).join('<span aria-hidden="true"> | </span>');
}

function voiceDisplayState(pane, session) {
  const frontend = pane.voiceFrontendState;
  if (frontend === 'connected') return 'connected';
  if (frontend === 'listening') return 'listening';
  if (frontend === 'speaking') return 'speaking';
  if (frontend === 'hearing') return 'hearing you';
  if (frontend === 'error') return 'audio error';
  if (frontend === 'connecting' || frontend === 'starting') return 'connecting';
  return session.state || 'starting';
}

function voiceLightState(pane, session) {
  const value = voiceDisplayState(pane, session);
  if (['connected', 'listening', 'speaking', 'hearing you'].includes(value)) return 'live';
  if (value.includes('error')) return 'error';
  return 'connecting';
}

function voiceStatusTitle(session) {
  return [
    `session: ${session.id || ''}`,
    `service: ${session.serviceSessionId || ''}`,
    `turn: ${session.lastTurnId || ''}`,
    `updated: ${session.updatedAt || ''}`,
  ].join('\n');
}

function voiceStartMessage(agentId, session) {
  const lines = [
    `Voice bridge started for ${agentId}`,
    `session: ${session.sessionKey || session.id || 'pending'}`,
  ];
  if (session.voice) lines.push(`voice: ${session.voice}`);
  if (session.publicUrl) lines.push('audio: connecting in this pane');
  return lines.join('\n');
}

function voiceClientUrl(publicUrl, agentId) {
  if (!publicUrl) return '';
  const url = new URL(publicUrl, window.location.origin);
  if (agentId) {
    url.searchParams.set('agent', agentId);
  }
  url.searchParams.set('compact', '1');
  url.searchParams.set('autoconnect', '1');
  return url.toString();
}

function canUseVoiceAudio() {
  return window.isSecureContext === true;
}

function voiceSecureContextMessage() {
  const target = voiceSecureSynapseUrl();
  if (target) {
    return `Voice needs HTTPS for microphone/WebRTC. Open ${target} and click Talk again.`;
  }
  return 'Voice needs HTTPS for microphone/WebRTC. Open Synapse over HTTPS and click Talk again.';
}

function voiceSecureSynapseUrl() {
  const el = document.querySelector('meta[name="synapse-voice-secure-url"]');
  const value = el?.getAttribute('content')?.trim() || '';
  if (!value) return '';
  try {
    return new URL(value, window.location.href).toString();
  } catch {
    return '';
  }
}

async function responseError(res) {
  try {
    const body = await res.json();
    return body.detail || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

async function loadSessionsList() {
  setSessionsStatus('Loading sessions...');
  try {
    const res = await fetch('/api/sessions/list');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    state.sessions.items = normalizeSessionRows(body.sessions || []);
    state.sessions.lastLoadedAt = new Date().toISOString();
    applySessionsFilter(state.sessions.query);
    setSessionsStatus(`Loaded ${state.sessions.items.length} sessions`);
  } catch (error) {
    state.sessions.items = [];
    state.sessions.filtered = [];
    renderSessionsList();
    setSessionsStatus(`Failed to load sessions: ${error.message}`, 'error');
  }
}

function normalizeSessionRows(rows) {
  return rows.map((session) => {
    const rawTotal = Number(session.totalTokens);
    const total = Number.isFinite(rawTotal) && rawTotal > 0 ? rawTotal : null;
    const context = Math.max(1, Number(session.contextTokens || 0));
    const lastActive = Date.parse(session.lastActive || '');
    const contextPct = total == null ? 0 : Math.min(100, Math.round((total / context) * 100));
    return {
      sessionKey: String(session.sessionKey || ''),
      agentId: String(session.agentId || ''),
      model: String(session.model || ''),
      defaultModel: String(session.defaultModel || ''),
      sessionModel: String(session.sessionModel || ''),
      contextPct,
      totalTokens: total,
      contextTokens: context,
      ageText: Number.isFinite(lastActive) ? formatAge(lastActive) : 'n/a',
    };
  });
}

function openSessionsDrawer(refresh = false) {
  const overlay = document.getElementById('synapse-sessions-overlay');
  state.sessions.open = true;
  overlay.classList.add('active');
  document.getElementById('synapse-sessions-filter').focus();
  if (refresh || !state.sessions.items.length) loadSessionsList();
}

function closeSessionsDrawer() {
  state.sessions.open = false;
  document.getElementById('synapse-sessions-overlay').classList.remove('active');
}

function applySessionsFilter(query = '') {
  state.sessions.query = query;
  const q = String(query || '').toLowerCase().trim();
  state.sessions.filtered = state.sessions.items.filter((row) => {
    const hay = `${row.agentId} ${row.model} ${row.sessionModel} ${row.sessionKey}`.toLowerCase();
    return !q || hay.includes(q);
  });
  renderSessionsList();
}

function renderSessionsList() {
  const list = document.getElementById('synapse-sessions-list');
  const meta = document.getElementById('synapse-sessions-meta');
  const rows = state.sessions.filtered;
  meta.textContent = `${rows.length}/${state.sessions.items.length}`;
  if (!rows.length) {
    list.innerHTML = '<div class="synapse-sessions-empty">No sessions match current filter.</div>';
    return;
  }
  list.innerHTML = sessionTableHtml(rows);
}

function sessionModelTitle(row) {
  const parts = [`selected: ${modelDisplayName(row.model)}`];
  if (row.sessionModel && row.sessionModel !== row.model) {
    parts.push(`runtime: ${modelDisplayName(row.sessionModel)}`);
  }
  if (row.defaultModel && row.defaultModel !== row.model) {
    parts.push(`default: ${modelDisplayName(row.defaultModel)}`);
  }
  return parts.join('\n');
}

function sessionTableHtml(rows) {
  const body = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.agentId || 'unknown')}</td>
      <td title="${escapeHtml(sessionModelTitle(row))}">${escapeHtml(modelDisplayName(row.model))}</td>
      <td title="${escapeHtml(row.totalTokens == null ? 'usage unknown' : `${row.contextPct}%`)}">${escapeHtml(`${row.totalTokens == null ? '?' : formatTokenNumber(row.totalTokens)}/${formatTokenNumber(row.contextTokens)}`)}</td>
      <td>${escapeHtml(row.ageText)}</td>
      <td title="${escapeHtml(row.sessionKey)}">${escapeHtml(row.sessionKey.slice(0, 44))}</td>
      <td><button type="button" data-session-agent="${escapeHtml(row.agentId)}">Use</button></td>
    </tr>
  `).join('');
  return `<table class="synapse-sessions-table"><thead><tr><th>Agent</th><th>Model</th><th>Context</th><th>Last</th><th>Session</th><th></th></tr></thead><tbody>${body}</tbody></table>`;
}

function onSessionsListClick(event) {
  const button = event.target.closest('[data-session-agent]');
  if (!button) return;
  const agentId = button.dataset.sessionAgent;
  if (!findAgent(agentId)) {
    showToast('Session agent is not in the active roster', 'error');
    return;
  }
  assignPane(state.focusPane, agentId);
  closeSessionsDrawer();
}

function setSessionsStatus(message, type = '') {
  const status = document.getElementById('synapse-sessions-status');
  status.textContent = message;
  status.dataset.state = type;
}

function renderPaneMessages(pane) {
  const el = document.querySelector(`.synapse-pane[data-pane-id="${pane.id}"] [data-ref="terminal"]`);
  if (el) renderMessages(pane, el);
}

function renderMessages(pane, terminal) {
  terminal.innerHTML = '';
  pane.messages.forEach((message) => terminal.appendChild(messageLine(message)));
  if (pane.streamText) {
    terminal.appendChild(messageLine({ role: 'assistant', text: pane.streamText, streaming: true }));
  } else if (pane.pendingRunId) {
    // Sent and acked but no tokens yet; long local prefill can last minutes.
    terminal.appendChild(messageLine({ role: 'assistant', text: pane.pendingRunStatus || '... thinking', streaming: true }));
  }
  terminal.scrollTop = terminal.scrollHeight;
}

function messageLine(message) {
  const line = document.createElement('div');
  line.className = `synapse-line ${message.role}${message.streaming ? ' streaming' : ''}`;
  const prompt = message.role === 'user' ? '$' : message.role === 'system' ? '!' : '<';
  const promptEl = document.createElement('span');
  promptEl.className = 'synapse-prompt';
  promptEl.textContent = prompt;
  const body = document.createElement('div');
  body.className = 'synapse-message';
  appendFormattedText(body, message.text || '');
  line.append(promptEl, body);
  return line;
}

function appendFormattedText(parent, text) {
  const fencePattern = /```([^\n`]*)\n?([\s\S]*?)```/g;
  let cursor = 0;
  let match = fencePattern.exec(text);
  while (match) {
    appendInlineText(parent, text.slice(cursor, match.index));
    parent.appendChild(codeBlock(match[1], match[2]));
    cursor = match.index + match[0].length;
    match = fencePattern.exec(text);
  }
  appendInlineText(parent, text.slice(cursor));
}

function appendInlineText(parent, text) {
  const inlinePattern = /`([^`\n]+)`/g;
  let cursor = 0;
  let match = inlinePattern.exec(text);
  while (match) {
    parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
    parent.appendChild(inlineCode(match[1]));
    cursor = match.index + match[0].length;
    match = inlinePattern.exec(text);
  }
  parent.appendChild(document.createTextNode(text.slice(cursor)));
}

function inlineCode(text) {
  const el = document.createElement('span');
  el.className = 'synapse-inline-code';
  el.textContent = text;
  return el;
}

function codeBlock(language, code) {
  const block = document.createElement('div');
  block.className = 'synapse-code-block';
  const label = language.trim();
  if (label) {
    const header = document.createElement('span');
    header.className = 'synapse-code-language';
    header.textContent = label;
    block.appendChild(header);
  }
  const pre = document.createElement('pre');
  pre.textContent = code;
  block.appendChild(pre);
  return block;
}

function sendFrame(frame) {
  if (!isSocketOpen()) {
    showToast('Synapse socket is not connected', 'error');
    return;
  }
  state.ws.send(JSON.stringify(frame));
}

function isSocketOpen() {
  return Boolean(state.ws && state.ws.readyState === WebSocket.OPEN);
}

function findAgent(agentId) {
  return state.agents.find((agent) => agent.agentId === agentId);
}

function tokenCountText(agent) {
  return `${formatTokenNumber(agent.contextUsed)}/${formatTokenNumber(agent.contextMax)}`;
}

function tokenCountTitle(agent) {
  return `${tokenCountText(agent)} tokens (${Math.round(agent.contextPct)}%)`;
}

function formatTokenNumber(value) {
  const number = Math.max(0, Math.round(Number(value || 0)));
  return number.toLocaleString();
}

function formatAge(timestamp) {
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function compactText(text, maxLength) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text || '');
  return div.innerHTML;
}

function setStatus(label) {
  const el = document.getElementById('synapse-status');
  el.textContent = label;
  el.dataset.state = label.toLowerCase();
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
