const COLUMNS = ['urgent', 'active', 'review', 'queued', 'ideas', 'backlog', 'archive'];

let currentItem = null;
let items = [];
let agents = [];
let draggedItemId = null;

document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  loadAgents();
  loadQueue();
  setInterval(loadQueue, 30000);
});

function setupEventListeners() {
  document.getElementById('quick-add-form').addEventListener('submit', quickAdd);
  document.getElementById('queue-refresh').addEventListener('click', refreshQueue);
  document.getElementById('item-modal').addEventListener('click', onModalBackdrop);
  document.getElementById('close-modal-btn').addEventListener('click', closeModal);
  document.getElementById('save-item-btn').addEventListener('click', saveCurrentItem);
  document.getElementById('delete-item-btn').addEventListener('click', deleteCurrentItem);
  document.getElementById('dispatch-btn').addEventListener('click', dispatchSelectedAgent);
  document.getElementById('auto-dispatch-btn').addEventListener('click', dispatchAuto);
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('dragstart', onDragStart);
  document.addEventListener('dragend', onDragEnd);
  document.querySelectorAll('.queue-content').forEach(setupDropTarget);
}

function setupDropTarget(target) {
  target.addEventListener('dragover', onDragOver);
  target.addEventListener('dragleave', onDragLeave);
  target.addEventListener('drop', onDrop);
}

async function apiJson(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json();
}

async function errorMessage(response) {
  try {
    const body = await response.json();
    return body.detail || body.error || `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

async function loadAgents() {
  try {
    agents = await apiJson('/api/queue/agents');
    renderAgents();
  } catch (error) {
    showToast(`Agent load failed: ${error.message}`, 'error');
  }
}

async function loadQueue() {
  try {
    const snapshot = await apiJson('/api/queue');
    items = snapshot.items || [];
    renderBoard();
    renderAgents();
  } catch (error) {
    showToast(`Queue load failed: ${error.message}`, 'error');
  }
}

function refreshQueue() {
  loadAgents();
  loadQueue();
}

async function createItem(itemData) {
  const item = await apiJson('/api/queue', {
    method: 'POST',
    body: JSON.stringify(itemData),
  });
  items.push(item);
  renderBoard();
  renderAgents();
  showToast('Task added', 'success');
  return item;
}

async function updateItem(itemId, updates) {
  const item = await apiJson(`/api/queue/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
  items = items.map((existing) => existing.id === itemId ? item : existing);
  renderBoard();
  renderAgents();
  return item;
}

async function removeItem(itemId) {
  await apiJson(`/api/queue/${itemId}`, { method: 'DELETE' });
  items = items.filter((item) => item.id !== itemId);
  renderBoard();
  renderAgents();
  showToast('Task deleted', 'success');
}

function renderBoard() {
  const byColumn = groupItems();
  COLUMNS.forEach((column) => {
    const container = document.getElementById(`col-${column}`);
    container.innerHTML = '';
    byColumn[column].forEach((item) => container.appendChild(createItemCard(item)));
    document.querySelector(`[data-count="${column}"]`).textContent = byColumn[column].length;
  });
  updateStats(byColumn);
}

function groupItems() {
  const grouped = Object.fromEntries(COLUMNS.map((column) => [column, []]));
  items.forEach((item) => {
    const column = COLUMNS.includes(item.column) ? item.column : 'backlog';
    grouped[column].push(item);
  });
  COLUMNS.forEach((column) => {
    grouped[column].sort((a, b) => (b.priority || 0) - (a.priority || 0));
  });
  return grouped;
}

function createItemCard(item) {
  const card = document.createElement('article');
  card.className = 'queue-item';
  card.draggable = true;
  card.dataset.itemId = item.id;

  const title = document.createElement('button');
  title.type = 'button';
  title.className = 'queue-item-title queue-item-title-btn';
  title.textContent = item.title;
  title.addEventListener('click', () => openItemModal(item));
  card.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'queue-item-meta';
  addMetaBadges(meta, item);
  if (meta.children.length > 0) card.appendChild(meta);
  return card;
}

function addMetaBadges(meta, item) {
  if (item.complexity) addBadge(meta, item.complexity, item.complexity);
  if (item.agent) addBadge(meta, 'agent', agentName(item.agent));
  if (item.session_status) addBadge(meta, item.session_status, item.session_status);
  if (item.doc_path) addBadge(meta, 'doc', 'doc');
  if ((item.priority || 0) > 0) {
    const priority = document.createElement('span');
    priority.className = 'queue-item-priority';
    priority.textContent = `P${item.priority}`;
    meta.appendChild(priority);
  }
}

function addBadge(container, className, label) {
  const badge = document.createElement('span');
  badge.className = `queue-badge ${className}`;
  badge.textContent = label;
  container.appendChild(badge);
}

function updateStats(byColumn) {
  const el = document.getElementById('queue-stats');
  const running = items.filter((item) => item.session_status === 'running').length;
  el.textContent = [
    `${byColumn.urgent.length} urgent`,
    `${byColumn.active.length} active`,
    `${byColumn.queued.length} queued`,
    `${byColumn.review.length} review`,
    `${byColumn.backlog.length} backlog`,
    `${running} running`,
  ].join(' · ');
}

function renderAgents() {
  const container = document.getElementById('agent-status-list');
  const select = document.getElementById('modal-item-agent');
  container.innerHTML = '';
  renderAgentOptions(select);
  agents.forEach((agent) => container.appendChild(createAgentChip(agent)));
}

function renderAgentOptions(select) {
  const selected = select.value;
  select.innerHTML = '<option value="">Auto-route</option>';
  agents.forEach((agent) => {
    const option = document.createElement('option');
    option.value = agent.id;
    option.textContent = `${agent.name || agent.id} (${agent.id})`;
    select.appendChild(option);
  });
  select.value = selected;
}

function createAgentChip(agent) {
  const counts = agentCounts(agent.id);
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = `agent-chip ${agentStatus(counts)}`;
  chip.title = agent.session_key || agent.id;
  chip.addEventListener('click', () => selectAgent(agent.id));
  chip.appendChild(statusDot());
  chip.appendChild(labelSpan(agent.name || agent.id));
  chip.appendChild(countSpan(counts));
  return chip;
}

function agentCounts(agentId) {
  return items.reduce((counts, item) => {
    if (item.agent !== agentId) return counts;
    counts.assigned += 1;
    if (item.session_status === 'running') counts.running += 1;
    if (item.column === 'queued' || item.column === 'urgent') counts.pending += 1;
    return counts;
  }, { assigned: 0, running: 0, pending: 0 });
}

function agentStatus(counts) {
  if (counts.running > 0) return 'busy';
  if (counts.assigned > 0) return 'active';
  return 'idle';
}

function statusDot() {
  const dot = document.createElement('span');
  dot.className = 'status-dot';
  return dot;
}

function labelSpan(label) {
  const span = document.createElement('span');
  span.textContent = label;
  return span;
}

function countSpan(counts) {
  const span = document.createElement('span');
  span.className = 'agent-count font-mono';
  span.textContent = `${counts.running}/${counts.assigned}`;
  return span;
}

function selectAgent(agentId) {
  const select = document.getElementById('modal-item-agent');
  select.value = agentId;
  showToast(`${agentName(agentId)} selected`, 'info');
}

function agentName(agentId) {
  const agent = agents.find((candidate) => candidate.id === agentId);
  return agent ? agent.name || agent.id : agentId;
}

async function quickAdd(event) {
  event.preventDefault();
  const input = document.getElementById('quick-add-input');
  const title = input.value.trim();
  if (!title) return;
  const column = document.getElementById('quick-add-column').value;
  await createItem({ title, column, priority: column === 'urgent' ? 90 : 0 });
  input.value = '';
  input.focus();
}

function onDragStart(event) {
  const card = event.target.closest('.queue-item');
  if (!card) return;
  draggedItemId = card.dataset.itemId;
  card.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', draggedItemId);
}

function onDragEnd(event) {
  const card = event.target.closest('.queue-item');
  if (card) card.classList.remove('dragging');
  document.querySelectorAll('.queue-content').forEach((column) => {
    column.classList.remove('drag-over');
  });
  draggedItemId = null;
}

function onDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add('drag-over');
}

function onDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    event.currentTarget.classList.remove('drag-over');
  }
}

async function onDrop(event) {
  event.preventDefault();
  event.currentTarget.classList.remove('drag-over');
  if (!draggedItemId) return;
  const column = event.currentTarget.closest('.queue-column').dataset.column;
  await updateItem(draggedItemId, { column });
}

function openItemModal(item) {
  currentItem = item;
  setModalValues(item);
  document.getElementById('item-modal').classList.remove('hidden');
  document.getElementById('modal-item-title').focus();
  loadDispatchHistory(item.id);
}

function setModalValues(item) {
  document.getElementById('modal-item-id').value = item.id;
  document.getElementById('modal-item-title').value = item.title || '';
  document.getElementById('modal-item-description').value = item.description || '';
  document.getElementById('modal-item-column').value = item.column || 'queued';
  document.getElementById('modal-item-complexity').value = item.complexity || 'medium';
  document.getElementById('modal-item-priority').value = item.priority || 0;
  document.getElementById('modal-item-doc-path').value = item.doc_path || '';
  document.getElementById('modal-item-tags').value = (item.tags || []).join(', ');
  document.getElementById('modal-item-notes').value = item.notes || '';
  document.getElementById('modal-item-agent').value = item.agent || '';
  renderSessionInfo(item);
}

function renderSessionInfo(item) {
  const box = document.getElementById('session-info');
  if (!item.session_id) {
    box.classList.add('hidden');
    return;
  }
  box.classList.remove('hidden');
  document.getElementById('session-status-text').textContent = (
    `${item.session_id} (${item.session_status || 'unknown'})`
  );
}

async function loadDispatchHistory(itemId) {
  const history = document.getElementById('dispatch-history');
  history.textContent = 'Loading dispatch history';
  try {
    const rows = await apiJson(`/api/queue/${itemId}/status`);
    renderDispatchHistory(rows);
  } catch (error) {
    history.textContent = `History unavailable: ${error.message}`;
  }
}

function renderDispatchHistory(rows) {
  const history = document.getElementById('dispatch-history');
  history.innerHTML = '';
  if (rows.length === 0) {
    history.textContent = 'No dispatch history';
    return;
  }
  rows.slice(0, 5).forEach((row) => history.appendChild(historyRow(row)));
}

function historyRow(row) {
  const item = document.createElement('div');
  item.className = 'queue-history-row';
  const run = row.run_id ? ` · ${row.run_id}` : '';
  item.textContent = `${agentName(row.agent_id)} · ${row.status}${run}`;
  return item;
}

function closeModal() {
  document.getElementById('item-modal').classList.add('hidden');
  currentItem = null;
}

function onModalBackdrop(event) {
  if (event.target.id === 'item-modal') closeModal();
}

function onKeyDown(event) {
  if (event.key === 'Escape') closeModal();
}

async function saveCurrentItem() {
  if (!currentItem) return;
  const updates = modalUpdates();
  await updateItem(currentItem.id, updates);
  closeModal();
  showToast('Task updated', 'success');
}

function modalUpdates() {
  const agent = document.getElementById('modal-item-agent').value || null;
  const docPath = document.getElementById('modal-item-doc-path').value || null;
  return {
    title: document.getElementById('modal-item-title').value,
    description: document.getElementById('modal-item-description').value,
    column: document.getElementById('modal-item-column').value,
    complexity: document.getElementById('modal-item-complexity').value,
    priority: Number.parseInt(document.getElementById('modal-item-priority').value, 10) || 0,
    doc_path: docPath,
    tags: parseTags(document.getElementById('modal-item-tags').value),
    notes: document.getElementById('modal-item-notes').value,
    agent,
  };
}

function parseTags(value) {
  return value.split(',').map((tag) => tag.trim()).filter(Boolean);
}

async function deleteCurrentItem() {
  if (!currentItem || !window.confirm('Delete this task?')) return;
  await removeItem(currentItem.id);
  closeModal();
}

async function dispatchSelectedAgent() {
  const agentId = document.getElementById('modal-item-agent').value;
  if (!agentId) {
    await dispatchAuto();
    return;
  }
  await dispatchCurrent(`/api/queue/${currentItem.id}/dispatch`, { agent_id: agentId });
}

async function dispatchAuto() {
  if (!currentItem) return;
  await dispatchCurrent(`/api/queue/${currentItem.id}/dispatch/auto`, {});
}

async function dispatchCurrent(url, payload) {
  if (!currentItem) return;
  setDispatchButtons(true);
  try {
    const result = await apiJson(url, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const mode = result.offline ? 'queued offline' : 'dispatched';
    showToast(`${agentName(result.agent_id)} ${mode}`, 'success');
    closeModal();
    await loadQueue();
  } catch (error) {
    showToast(`Dispatch failed: ${error.message}`, 'error');
  } finally {
    setDispatchButtons(false);
  }
}

function setDispatchButtons(disabled) {
  document.getElementById('dispatch-btn').disabled = disabled;
  document.getElementById('auto-dispatch-btn').disabled = disabled;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
