// Agent Queue - Mission Control
// Follows the same patterns as app.js

let currentItemId = null;
let currentItem = null;
let items = [];
let agents = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadQueue();
    loadAgentStatus();
    setupEventListeners();
    
    // Refresh agent status every 30s
    setInterval(loadAgentStatus, 30000);
});

function setupEventListeners() {
    // Quick add
    document.getElementById('quick-add-btn').addEventListener('click', quickAdd);
    document.getElementById('quick-add-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') quickAdd();
    });

    // Drag and drop on content areas
    document.querySelectorAll('.queue-content').forEach(col => {
        col.addEventListener('dragover', handleDragOver);
        col.addEventListener('dragleave', handleDragLeave);
        col.addEventListener('drop', handleDrop);
    });

    // Modal close on backdrop click
    document.getElementById('item-modal').addEventListener('click', (e) => {
        if (e.target.id === 'item-modal') closeModal();
    });

    // Escape key closes modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });
    
    // Archive all done
    const archiveAllBtn = document.getElementById('archive-all-btn');
    if (archiveAllBtn) {
        archiveAllBtn.addEventListener('click', archiveAllDone);
    }

    // Refresh agents button
    const refreshBtn = document.getElementById('refresh-agents-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadAgentStatus);
    }
    
    // Cron panel button
    const cronPanelBtn = document.getElementById('cron-panel-btn');
    if (cronPanelBtn) {
        cronPanelBtn.addEventListener('click', openCronPanel);
    }
    
    // Chat panel toggle
    const toggleChatBtn = document.getElementById('toggle-chat-btn');
    if (toggleChatBtn) {
        toggleChatBtn.addEventListener('click', toggleChatPanel);
    }
    
    const closeChatBtn = document.getElementById('close-chat-btn');
    if (closeChatBtn) {
        closeChatBtn.addEventListener('click', () => toggleChatPanel(false));
    }
    
    // Chat agent selector
    const chatAgentSelect = document.getElementById('chat-agent-select');
    if (chatAgentSelect) {
        chatAgentSelect.addEventListener('change', () => {
            loadChatForAgent(chatAgentSelect.value);
        });
    }
}

// ============================================
// Chat Panel Functions
// ============================================

const WEBCHAT_TOKEN = '1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c';
const GATEWAY_PORT = 18789;

function getWebchatUrl(agentId) {
    const host = window.location.hostname;
    let baseUrl;
    if (host.includes('jwells.net')) {
        baseUrl = 'https://chat.jwells.net/webchat';
    } else {
        baseUrl = `http://${host}:${GATEWAY_PORT}/webchat`;
    }
    let url = `${baseUrl}?token=${WEBCHAT_TOKEN}`;
    if (agentId && agentId !== 'jarvis') {
        url += `&agent=${agentId}`;
    }
    return url;
}

function openCronPanel() {
    const host = window.location.hostname;
    let url;
    if (host.includes('jwells.net')) {
        url = `https://chat.jwells.net/cron?token=${WEBCHAT_TOKEN}`;
    } else {
        url = `http://${host}:${GATEWAY_PORT}/cron?token=${WEBCHAT_TOKEN}`;
    }
    window.open(url, '_blank');
}

function toggleChatPanel(show = null) {
    const panel = document.getElementById('chat-panel');
    if (!panel) return;
    const shouldShow = show !== null ? show : panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !shouldShow);
    if (shouldShow) {
        const iframe = document.getElementById('chat-iframe');
        if (!iframe.src) {
            const agentSelect = document.getElementById('chat-agent-select');
            loadChatForAgent(agentSelect ? agentSelect.value : 'jarvis');
        }
    }
}

function loadChatForAgent(agentId) {
    const iframe = document.getElementById('chat-iframe');
    if (iframe) {
        iframe.src = getWebchatUrl(agentId);
    }
}

// ============================================
// Agent Status Functions
// ============================================

async function loadAgentStatus() {
    try {
        const response = await fetch('/api/agents');
        const data = await response.json();
        agents = data.agents || [];
        renderAgentStatus();
    } catch (error) {
        console.error('Failed to load agent status:', error);
    }
}

function populateAgentDropdowns() {
    const selects = document.querySelectorAll('#modal-item-agent, #chat-agent-select');
    selects.forEach(select => {
        const currentVal = select.value;
        const isModal = select.id === 'modal-item-agent';
        select.innerHTML = isModal ? '<option value="">-- Auto-route --</option>' : '';
        agents.forEach(agent => {
            const opt = document.createElement('option');
            opt.value = agent.id;
            opt.textContent = `${agent.emoji || '🤖'} ${agent.name || agent.id}${agent.domain ? ' (' + agent.domain + ')' : ''}`;
            select.appendChild(opt);
        });
        if (currentVal) select.value = currentVal;
    });
}

function renderAgentStatus() {
    const container = document.getElementById('agent-status-list');
    if (!container) return;
    container.innerHTML = '';
    populateAgentDropdowns();
    
    agents.forEach(agent => {
        const chip = document.createElement('div');
        chip.className = `agent-chip ${agent.status}`;
        chip.dataset.agentId = agent.id;
        
        let tooltip = `${agent.name} (${agent.domain})`;
        if (agent.updated_ago) tooltip += ` - ${agent.updated_ago}`;
        if (agent.context_pct !== null) tooltip += ` - ${agent.context_pct}% context`;
        chip.title = tooltip;
        
        chip.innerHTML = `
            <span class="status-dot"></span>
            <span>${agent.emoji} ${agent.name}</span>
            ${agent.context_pct !== null ? `<span class="context-pct">${agent.context_pct}%</span>` : ''}
        `;
        
        chip.addEventListener('click', () => {
            const agentSelect = document.getElementById('modal-item-agent');
            if (agentSelect) agentSelect.value = agent.id;
            showToast(`${agent.name} selected for dispatch`, 'info');
        });
        
        container.appendChild(chip);
    });
}

async function dispatchToAgent() {
    const agentSelect = document.getElementById('modal-item-agent');
    const agentId = agentSelect.value;
    
    if (!agentId) {
        showToast('Select an agent first', 'error');
        return;
    }
    if (!currentItem) {
        showToast('No task selected', 'error');
        return;
    }
    
    let task = currentItem.title;
    if (currentItem.description) task += `\n\n${currentItem.description}`;
    if (currentItem.notes) task += `\n\nNotes:\n${currentItem.notes}`;
    if (currentItem.doc_path) task += `\n\nRelevant doc: ${currentItem.doc_path}`;
    
    const dispatchBtn = document.getElementById('dispatch-btn');
    dispatchBtn.disabled = true;
    dispatchBtn.textContent = 'Dispatching...';
    
    try {
        const response = await fetch('/api/agents/spawn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_id: agentId,
                task: task,
                queue_item_id: currentItem.id
            })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Spawn failed');
        }
        
        showToast(`Task dispatched to ${agentId}`, 'success');
        closeModal();
        loadQueue();
        loadAgentStatus();
    } catch (error) {
        console.error('Dispatch failed:', error);
        showToast(`Dispatch failed: ${error.message}`, 'error');
    } finally {
        dispatchBtn.disabled = false;
        dispatchBtn.textContent = 'Dispatch';
    }
}

// ============================================
// API Functions
// ============================================

async function loadQueue() {
    try {
        const response = await fetch('/api/queue');
        const data = await response.json();
        items = data.items || [];
        renderBoard();
        updateStats(data.stats);
    } catch (error) {
        console.error('Failed to load queue:', error);
        showToast('Failed to load queue', 'error');
    }
}

async function createItem(itemData) {
    try {
        const response = await fetch('/api/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(itemData)
        });
        const newItem = await response.json();
        items.push(newItem);
        renderBoard();
        showToast('Task added', 'success');
        return newItem;
    } catch (error) {
        console.error('Failed to create item:', error);
        showToast('Failed to create task', 'error');
    }
}

async function updateItem(itemId, updates) {
    try {
        const response = await fetch(`/api/queue/${itemId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });
        const updatedItem = await response.json();
        
        const index = items.findIndex(i => i.id === itemId);
        if (index !== -1) {
            items[index] = updatedItem;
        }
        renderBoard();
        return updatedItem;
    } catch (error) {
        console.error('Failed to update item:', error);
        showToast('Failed to update task', 'error');
    }
}

async function deleteItem(itemId) {
    try {
        await fetch(`/api/queue/${itemId}`, { method: 'DELETE' });
        items = items.filter(i => i.id !== itemId);
        renderBoard();
        showToast('Task deleted', 'success');
    } catch (error) {
        console.error('Failed to delete item:', error);
        showToast('Failed to delete task', 'error');
    }
}

async function openInEditor(docPath) {
    try {
        const response = await fetch('/api/queue/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: docPath })
        });
        const result = await response.json();
        if (result.success) {
            showToast(result.message, 'info');
        } else {
            showToast(result.error || 'Failed to open editor', 'error');
        }
    } catch (error) {
        console.error('Failed to open editor:', error);
        showToast('Failed to open editor', 'error');
    }
}

// ============================================
// Render Functions
// ============================================

function renderBoard() {
    const columns = {
        urgent: document.getElementById('col-urgent'),
        active: document.getElementById('col-active'),
        review: document.getElementById('col-review'),
        queued: document.getElementById('col-queued'),
        ideas: document.getElementById('col-ideas'),
        done: document.getElementById('col-done'),
        archive: document.getElementById('col-archive')
    };

    // Clear all columns
    Object.values(columns).forEach(col => { if (col) col.innerHTML = ''; });

    // Group items by column
    const byColumn = { urgent: [], active: [], review: [], queued: [], ideas: [], done: [], archive: [] };
    items.forEach(item => {
        const col = item.column || 'queued';
        if (byColumn[col]) {
            byColumn[col].push(item);
        }
    });

    // Sort by priority (descending) within each column
    Object.values(byColumn).forEach(colItems => {
        colItems.sort((a, b) => (b.priority || 0) - (a.priority || 0));
    });

    // Render items
    Object.entries(byColumn).forEach(([col, colItems]) => {
        if (!columns[col]) return;
        colItems.forEach(item => {
            columns[col].appendChild(createItemCard(item));
        });
        
        const countEl = document.querySelector(`[data-count="${col}"]`);
        if (countEl) countEl.textContent = colItems.length;
    });

    // Show/hide archive all button
    const archiveAllBtn = document.getElementById('archive-all-btn');
    if (archiveAllBtn) {
        archiveAllBtn.style.display = byColumn.done.length > 0 ? '' : 'none';
    }

    const stats = {
        active: byColumn.active.length,
        queued: byColumn.queued.length,
        review: byColumn.review.length,
        urgent: byColumn.urgent.length,
        done: byColumn.done.length
    };
    updateStats(stats);
}

function createItemCard(item) {
    const card = document.createElement('div');
    card.className = 'queue-item';
    card.draggable = true;
    card.dataset.itemId = item.id;

    // Header row: checkbox + title + delete button
    const header = document.createElement('div');
    header.className = 'queue-item-header';

    // Done checkbox
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'queue-item-checkbox';
    checkbox.checked = item.column === 'done' || item.column === 'archive';
    checkbox.title = item.column === 'done' ? 'Mark incomplete' : 'Mark done';
    checkbox.addEventListener('click', (e) => {
        e.stopPropagation();
        if (item.column === 'done' || item.column === 'archive') {
            updateItem(item.id, { column: 'queued' });
        } else {
            updateItem(item.id, { column: 'done' });
            showToast('Task marked done ✓', 'success');
        }
    });
    header.appendChild(checkbox);

    // Title (clickable to open modal)
    const title = document.createElement('div');
    title.className = 'queue-item-title';
    if (item.column === 'done' || item.column === 'archive') {
        title.classList.add('done');
    }
    title.textContent = item.title;
    title.addEventListener('click', () => openItemModal(item));
    header.appendChild(title);

    // Archive button (only on done items)
    if (item.column === 'done') {
        const archiveBtn = document.createElement('button');
        archiveBtn.className = 'queue-item-archive';
        archiveBtn.textContent = '📦';
        archiveBtn.title = 'Archive';
        archiveBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            updateItem(item.id, { column: 'archive' });
        });
        header.appendChild(archiveBtn);
    }

    // Delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'queue-item-delete';
    deleteBtn.textContent = '×';
    deleteBtn.title = 'Delete task';
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm('Delete this task?')) {
            deleteItem(item.id);
        }
    });
    header.appendChild(deleteBtn);

    card.appendChild(header);

    // Meta badges row
    const meta = document.createElement('div');
    meta.className = 'queue-item-meta';

    if (item.complexity) {
        const complexityLabels = { quick: 'Quick', medium: 'Medium', deep: 'Deep' };
        const badge = document.createElement('span');
        badge.className = `queue-badge ${item.complexity}`;
        badge.textContent = complexityLabels[item.complexity] || item.complexity;
        meta.appendChild(badge);
    }

    if (item.doc_path) {
        const docBadge = document.createElement('span');
        docBadge.className = 'queue-badge doc';
        docBadge.textContent = 'Doc';
        docBadge.title = item.doc_path;
        docBadge.addEventListener('click', (e) => {
            e.stopPropagation();
            openInEditor(item.doc_path);
        });
        meta.appendChild(docBadge);
    }

    if (item.session_status === 'running') {
        const sessionBadge = document.createElement('span');
        sessionBadge.className = 'queue-badge running';
        sessionBadge.textContent = 'Running';
        meta.appendChild(sessionBadge);
    }

    if (item.agent) {
        const agentBadge = document.createElement('span');
        agentBadge.className = 'queue-badge agent';
        const agentInfo = agents.find(a => a.id === item.agent);
        agentBadge.textContent = agentInfo ? `${agentInfo.emoji || '🤖'} ${agentInfo.name || item.agent}` : item.agent;
        agentBadge.title = `Assigned to ${item.agent}`;
        meta.appendChild(agentBadge);
    }

    if (item.priority > 0) {
        const priorityEl = document.createElement('span');
        priorityEl.className = 'queue-item-priority';
        priorityEl.textContent = `P${item.priority}`;
        meta.appendChild(priorityEl);
    }

    if (meta.children.length > 0) {
        card.appendChild(meta);
    }

    return card;
}

function updateStats(stats) {
    if (!stats) return;
    const el = document.getElementById('queue-stats');
    if (el) {
        const parts = [];
        if (stats.urgent) parts.push(`${stats.urgent} urgent`);
        parts.push(`${stats.active || 0} active`);
        parts.push(`${stats.queued || 0} queued`);
        parts.push(`${stats.review || 0} review`);
        if (stats.done) parts.push(`${stats.done} done`);
        el.textContent = parts.join(' · ');
    }
}

// ============================================
// Quick Add
// ============================================

function quickAdd() {
    const input = document.getElementById('quick-add-input');
    const columnSelect = document.getElementById('quick-add-column');
    
    const title = input.value.trim();
    if (!title) return;

    const column = columnSelect.value;
    const itemData = { title, column };
    
    // Urgent tasks get high default priority
    if (column === 'urgent') {
        itemData.priority = 90;
    }

    createItem(itemData);
    input.value = '';
    input.focus();
}

// ============================================
// Drag and Drop
// ============================================

let draggedEl = null;
let draggedItemId = null;

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    
    const content = e.currentTarget;
    content.classList.add('drag-over');
    
    // Show insertion indicator
    const afterEl = getDragAfterElement(content, e.clientY);
    const dragging = document.querySelector('.queue-item.dragging');
    if (dragging) {
        if (afterEl) {
            content.insertBefore(dragging, afterEl);
        } else {
            content.appendChild(dragging);
        }
    }
}

function handleDragLeave(e) {
    // Only remove if actually leaving the container (not entering a child)
    if (!e.currentTarget.contains(e.relatedTarget)) {
        e.currentTarget.classList.remove('drag-over');
    }
}

function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    
    if (!draggedItemId) return;
    
    const newColumn = e.currentTarget.closest('.queue-column').dataset.column;
    
    // Persist the column change
    updateItem(draggedItemId, { column: newColumn });
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.queue-item:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

// Use event delegation for drag start/end on the board
document.addEventListener('dragstart', (e) => {
    const card = e.target.closest('.queue-item');
    if (!card) return;
    
    draggedEl = card;
    draggedItemId = card.dataset.itemId;
    card.classList.add('dragging');
    
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', draggedItemId);
    
    // Slight delay to let the browser capture the drag image
    requestAnimationFrame(() => {
        card.style.opacity = '0.4';
    });
});

document.addEventListener('dragend', (e) => {
    const card = e.target.closest('.queue-item');
    if (!card) return;
    
    card.classList.remove('dragging');
    card.style.opacity = '';
    
    document.querySelectorAll('.queue-content').forEach(col => {
        col.classList.remove('drag-over');
    });
    
    draggedEl = null;
    draggedItemId = null;
});

// ============================================
// Modal Functions
// ============================================

function openItemModal(item) {
    currentItemId = item.id;
    currentItem = item;
    
    document.getElementById('modal-item-id').value = item.id;
    document.getElementById('modal-item-title').value = item.title || '';
    document.getElementById('modal-item-description').value = item.description || '';
    document.getElementById('modal-item-column').value = item.column || 'queued';
    document.getElementById('modal-item-complexity').value = item.complexity || 'medium';
    document.getElementById('modal-item-priority').value = item.priority || 0;
    document.getElementById('modal-item-doc-path').value = item.doc_path || '';
    document.getElementById('modal-item-notes').value = item.notes || '';
    
    const agentSelect = document.getElementById('modal-item-agent');
    if (agentSelect) agentSelect.value = item.agent || '';
    
    const dispatchBtn = document.getElementById('dispatch-btn');
    if (dispatchBtn) {
        dispatchBtn.disabled = item.session_status === 'running';
        dispatchBtn.textContent = item.session_status === 'running' ? 'Running...' : 'Dispatch';
    }

    const sessionInfo = document.getElementById('session-info');
    if (item.session_id) {
        sessionInfo.classList.remove('hidden');
        document.getElementById('session-status-text').textContent = 
            `${item.session_id} (${item.session_status || 'unknown'})`;
    } else {
        sessionInfo.classList.add('hidden');
    }

    document.getElementById('item-modal').classList.remove('hidden');
    document.getElementById('modal-item-title').focus();
}

function closeModal() {
    document.getElementById('item-modal').classList.add('hidden');
    currentItemId = null;
    currentItem = null;
}

function saveCurrentItem() {
    if (!currentItemId) return;

    const agentVal = document.getElementById('modal-item-agent').value;
    const updates = {
        title: document.getElementById('modal-item-title').value,
        description: document.getElementById('modal-item-description').value,
        column: document.getElementById('modal-item-column').value,
        complexity: document.getElementById('modal-item-complexity').value,
        priority: parseInt(document.getElementById('modal-item-priority').value) || 0,
        doc_path: document.getElementById('modal-item-doc-path').value || null,
        notes: document.getElementById('modal-item-notes').value,
        agent: agentVal || null
    };

    updateItem(currentItemId, updates);
    closeModal();
    showToast('Task updated', 'success');
}

function deleteCurrentItem() {
    if (!currentItemId) return;
    if (confirm('Delete this task?')) {
        deleteItem(currentItemId);
        closeModal();
    }
}

function openDocInEditor() {
    const docPath = document.getElementById('modal-item-doc-path').value;
    if (docPath) {
        openInEditor(docPath);
    } else {
        showToast('No document path specified', 'error');
    }
}

// ============================================
// Archive Functions
// ============================================

function toggleArchive() {
    const content = document.getElementById('col-archive');
    const toggle = document.getElementById('archive-toggle');
    if (content && toggle) {
        content.classList.toggle('hidden');
        toggle.textContent = content.classList.contains('hidden') ? '▶' : '▼';
    }
}

function archiveAllDone() {
    const doneItems = items.filter(i => i.column === 'done');
    if (doneItems.length === 0) return;
    
    doneItems.forEach(item => {
        updateItem(item.id, { column: 'archive' });
    });
    showToast(`Archived ${doneItems.length} tasks`, 'success');
}

// ============================================
// Toast Notifications
// ============================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.15s ease';
        setTimeout(() => toast.remove(), 150);
    }, 3000);
}
