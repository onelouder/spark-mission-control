/**
 * =============================================================================
 * Briefing.js - Running Briefing Page Logic
 * =============================================================================
 * 
 * Handles the Running Briefing page which displays:
 * - Decisions Waiting on You (always expanded, high-priority emails)
 * - Today's Runway (horizontal timeline + collapsible tasks)
 * - Active Threads (LLM-generated project clusters)
 * - Incoming Tasks & Action Items (lower-priority emails)
 * - This Week's Pulse (LLM-generated narrative summary)
 * - Stale/Aging (items sitting too long)
 * - Snoozed (temporarily hidden items)
 * 
 * Features:
 * - Auto-refresh every 10 minutes
 * - Snooze system with custom durations
 * - Context/Account filtering
 * - Block collapse/expand with localStorage persistence
 * - Horizontal timeline with overlap detection
 * 
 * Data Flow:
 * - Fetches from /api/briefing (cached) or /api/briefing/refresh (fresh)
 * - Snooze operations: POST /api/snooze, DELETE /api/snooze/:id
 * - Filters: /api/filters, /api/contexts/filter, /api/accounts/filter
 */

console.log('[BRIEFING.JS] VERSION 2026-02-11-v10 loaded at', new Date().toISOString());

// =============================================================================
// Global State
// =============================================================================

let briefingData = null;           // Current briefing data from API
let currentSnoozeItem = null;      // Item being snoozed (for modal)
let contextsData = null;           // Life domain contexts (Novvi, Personal, etc.)
let accountsData = null;           // Email accounts (Office365, Gmail, etc.)
let activeContextFilter = null;    // Current context filter (null = all)
let activeAccountFilter = null;    // Current account filter (null = all)
let globalTimelineItems = [];      // Timeline items for periodic "next event" updates

// Block state (collapsed/expanded) - persisted to localStorage
const blockStates = {
    runway: true,      // Expanded
    agents: true,      // Expanded - agent constellation
    cron: false,       // Collapsed by default - background jobs
    notes: true,       // Expanded - quick notes scratchpad
    threads: true,     // Expanded
    people: true,      // Expanded
    pulse: true,       // Expanded
    stale: false,      // Collapsed by default (less important)
    snoozed: false     // Collapsed by default (out of sight)
};

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initializePage();
    loadPhasedContent();
});

async function loadPhasedContent() {
    // Phase 0: Filters (needed before rendering briefing content)
    await loadFilters();

    // Phase 1: Critical — briefing is the main page content
    await loadBriefingData();

    // Phase 2: Fast secondary widgets (~4 concurrent, all <100ms)
    await Promise.all([
        loadAgentStatus(),
        loadCronStatus(),
        loadHealth(),
        loadQuickNotes(),
    ]);

    // Phase 3: Medium widgets (~4 concurrent, <1s each)
    await Promise.all([
        loadQueueSummary(),
        loadAccomplishments(),
        loadGitActivity(),
        loadWorkingContext(),
        loadEmailQuickview(),
    ]);

    // Phase 4: Slower widgets (~4 concurrent, 0.3-1s each)
    await Promise.all([
        loadUpcomingMeetings(),
        loadWeekendPreview(),
        loadSystemMetrics(),
    ]);

    // Phase 5: Heaviest — external APIs + LLM-generated (1-6s each)
    await Promise.all([
        loadWeather(),
        loadMorningSummary(),
        loadFilterStats(),
    ]);
}

// =============================================================================
// Auto-Refresh System
// =============================================================================
// Briefing auto-refreshes every 10 minutes to stay current.
// Manual refresh resets the timer. Countdown shown in nav bar.

const AUTO_REFRESH_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes
let autoRefreshTimer = null;
let lastRefreshTime = null;

function initializePage() {
    // Set up event listeners
    const refreshBtn = document.getElementById('refresh-btn');
    const retryBtn = document.getElementById('retry-btn');
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', manualRefresh);
    }
    
    if (retryBtn) {
        retryBtn.addEventListener('click', loadBriefingData);
    }
    
    // Initialize block states
    restoreBlockStates();
    
    // Update current time
    updateCurrentTime();
    setInterval(updateCurrentTime, 60000); // Update every minute
    
    // Start auto-refresh timer (10 minutes)
    startAutoRefreshTimer();
    
    // Update countdown display every minute
    setInterval(updateRefreshCountdown, 60000);
}

function startAutoRefreshTimer() {
    // Clear existing timer if any
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
    }
    
    lastRefreshTime = Date.now();
    autoRefreshTimer = setInterval(autoRefresh, AUTO_REFRESH_INTERVAL_MS);
    updateRefreshCountdown();
}

async function autoRefresh() {
    console.log('[Auto-refresh] Refreshing briefing data...');
    lastRefreshTime = Date.now();
    await refreshBriefing();
    updateRefreshCountdown();
}

async function manualRefresh() {
    console.log('[Manual refresh] User triggered refresh');
    lastRefreshTime = Date.now();
    await refreshBriefing();
    // Reset the auto-refresh timer on manual refresh
    startAutoRefreshTimer();
}

function updateRefreshCountdown() {
    const countdownEl = document.getElementById('refresh-countdown');
    if (!countdownEl || !lastRefreshTime) return;
    
    const elapsed = Date.now() - lastRefreshTime;
    const remaining = Math.max(0, AUTO_REFRESH_INTERVAL_MS - elapsed);
    const minutesRemaining = Math.ceil(remaining / 60000);
    
    if (minutesRemaining <= 1) {
        countdownEl.textContent = 'refreshing soon...';
    } else {
        countdownEl.textContent = `next refresh in ${minutesRemaining} min`;
    }
}

// =============================================================================
// Filter System (Context + Account)
// =============================================================================
// Contexts: Life domains (Novvi, Personal, Startup, etc.)
// Accounts: Email sources (Office365, Gmail, etc.)
// Both filters are applied server-side and affect which items appear.

async function loadFilters() {
    try {
        const response = await fetch('/api/filters');
        if (!response.ok) {
            console.warn('Failed to load filters, using defaults');
            return;
        }
        
        const data = await response.json();
        contextsData = { contexts: data.contexts };
        accountsData = { accounts: data.accounts };
        activeContextFilter = data.active_context;
        activeAccountFilter = data.active_account;
        
        renderContextFilters(data.contexts);
        renderAccountFilters(data.accounts);

        // Note: loadFilterStats() is deferred to Phase 5 of loadPhasedContent()
        // to avoid holding a connection during critical content loading.
        
    } catch (error) {
        console.error('Error loading filters:', error);
    }
}

async function loadFilterStats() {
    try {
        const response = await fetch('/api/contexts/aggregated');
        if (!response.ok) return;
        
        const data = await response.json();
        updateFilterBadges(data.context_stats, data.account_stats);
    } catch (error) {
        console.warn('Could not load filter stats:', error);
    }
}

function updateFilterBadges(contextStats, accountStats) {
    // Update context badges
    if (contextStats) {
        for (const [ctxId, stats] of Object.entries(contextStats)) {
            const btn = document.querySelector(`.context-btn[data-context="${ctxId}"]`);
            if (btn && stats.unread > 0) {
                let badge = btn.querySelector('.ctx-count');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'ctx-count';
                    btn.appendChild(badge);
                }
                badge.textContent = stats.unread;
            }
        }
    }
    
    // Update account badges  
    if (accountStats) {
        for (const [accId, stats] of Object.entries(accountStats)) {
            const btn = document.querySelector(`.account-btn[data-account="${accId}"]`);
            if (btn && stats.unread > 0) {
                let badge = btn.querySelector('.acc-count');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'acc-count';
                    btn.appendChild(badge);
                }
                badge.textContent = stats.unread;
            }
        }
    }
}

function renderContextFilters(contexts) {
    const select = document.getElementById('context-filter');
    if (!select) return;
    
    // Build dropdown options
    let html = `<option value="">All Contexts</option>`;
    
    for (const ctx of contexts) {
        if (!ctx.enabled) continue;
        const isSelected = activeContextFilter === ctx.id;
        html += `<option value="${ctx.id}" ${isSelected ? 'selected' : ''}>${ctx.name}</option>`;
    }
    
    select.innerHTML = html;
    
    // Add change listener if not already added
    if (!select.dataset.listenerAdded) {
        select.addEventListener('change', (e) => setContextFilter(e.target.value || null));
        select.dataset.listenerAdded = 'true';
    }
}

async function setContextFilter(contextId) {
    // Update local state
    activeContextFilter = contextId;
    
    // Update dropdown if needed
    const select = document.getElementById('context-filter');
    if (select && select.value !== (contextId || '')) {
        select.value = contextId || '';
    }
    
    // Save filter to backend
    try {
        await fetch('/api/contexts/filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ context_id: contextId })
        });
    } catch (error) {
        console.error('Failed to save context filter:', error);
    }
    
    // Re-render briefing with filter applied
    if (briefingData) {
        renderBriefing(briefingData);
    }
}

function getContextBadge(contextId) {
    if (!contextId || !contextsData) return '';
    
    const ctx = contextsData.contexts.find(c => c.id === contextId);
    if (!ctx) return '';
    
    return `<span class="item-context-badge" data-context="${contextId}" style="border-left-color: ${ctx.color}">${ctx.name}</span>`;
}

function filterByContext(items) {
    if (!activeContextFilter || !items) return items;
    return items.filter(item => item.context_id === activeContextFilter);
}

// === Account Filter Functions ===

function renderAccountFilters(accounts) {
    const select = document.getElementById('account-filter');
    if (!select) return;
    
    // Build dropdown options
    let html = `<option value="">All Accounts</option>`;
    
    for (const acc of accounts) {
        if (!acc.enabled) continue;
        const isSelected = activeAccountFilter === acc.id;
        html += `<option value="${acc.id}" ${isSelected ? 'selected' : ''}>${acc.name}</option>`;
    }
    
    select.innerHTML = html;
    
    // Add change listener if not already added
    if (!select.dataset.listenerAdded) {
        select.addEventListener('change', (e) => setAccountFilter(e.target.value || null));
        select.dataset.listenerAdded = 'true';
    }
}

async function setAccountFilter(accountId) {
    // Update local state
    activeAccountFilter = accountId;
    
    // Update dropdown if needed
    const select = document.getElementById('account-filter');
    if (select && select.value !== (accountId || '')) {
        select.value = accountId || '';
    }
    
    // Save filter to backend
    try {
        await fetch('/api/accounts/filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_id: accountId })
        });
    } catch (error) {
        console.error('Failed to save account filter:', error);
    }
    
    // Re-render briefing with filter applied
    if (briefingData) {
        renderBriefing(briefingData);
    }
}

function getAccountBadge(accountId) {
    if (!accountId || !accountsData) return '';
    
    const acc = accountsData.accounts.find(a => a.id === accountId);
    if (!acc) return '';
    
    return `<span class="item-account-badge" style="border-left: 2px solid ${acc.color}">
        ${acc.icon} ${acc.email.split('@')[0]}
    </span>`;
}

function filterByAccount(items) {
    if (!activeAccountFilter || !items) return items;
    return items.filter(item => item.account_id === activeAccountFilter);
}

function filterItems(items) {
    let filtered = items;
    filtered = filterByContext(filtered);
    filtered = filterByAccount(filtered);
    return filtered;
}

function updateCurrentTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'America/Los_Angeles'
    });
    
    const currentTimeEl = document.getElementById('current-time');
    if (currentTimeEl) {
        currentTimeEl.textContent = timeStr;
    }
    
    // Check for focus mode
    checkFocusMode();
}

// =============================================================================
// Focus Mode Detection
// =============================================================================
// Checks if user is currently in a Focus/Deep Work calendar block
// and displays a prominent banner to remind them to stay focused.

function checkFocusMode() {
    const banner = document.getElementById('focus-mode-banner');
    if (!banner) return;
    
    const now = new Date();
    const nowHours = now.getHours();
    const nowMins = now.getMinutes();
    const nowTotalMins = nowHours * 60 + nowMins;
    
    // Check timeline items for focus blocks
    const focusKeywords = ['focus', 'deep work', 'heads down', 'no meetings', 'blocked'];
    let currentFocusEvent = null;
    
    for (const item of globalTimelineItems) {
        if (!item.time || item.day !== 'Today') continue;
        
        // Check if title matches focus keywords (case-insensitive)
        const titleLower = (item.title || '').toLowerCase();
        const isFocusBlock = focusKeywords.some(kw => titleLower.includes(kw));
        if (!isFocusBlock) continue;
        
        // Parse event time
        const [hours, mins] = item.time.split(':').map(Number);
        const startMins = hours * 60 + (mins || 0);
        const durationMins = item.duration_mins || 60;
        const endMins = startMins + durationMins;
        
        // Check if we're currently in this focus block
        if (nowTotalMins >= startMins && nowTotalMins < endMins) {
            currentFocusEvent = {
                title: item.title,
                endMins: endMins,
                remainingMins: endMins - nowTotalMins
            };
            break;
        }
    }
    
    // Update banner visibility and content
    if (currentFocusEvent) {
        banner.classList.add('active');
        
        const titleEl = document.getElementById('focus-title');
        const subtitleEl = document.getElementById('focus-subtitle');
        const remainingEl = document.getElementById('focus-time-remaining');
        
        if (titleEl) titleEl.textContent = currentFocusEvent.title;
        if (subtitleEl) subtitleEl.textContent = 'Protect this time — stay in the zone';
        
        if (remainingEl) {
            const hrs = Math.floor(currentFocusEvent.remainingMins / 60);
            const mins = currentFocusEvent.remainingMins % 60;
            if (hrs > 0) {
                remainingEl.textContent = `${hrs}h ${mins}m left`;
            } else {
                remainingEl.textContent = `${mins}m left`;
            }
        }
    } else {
        banner.classList.remove('active');
    }
}

async function loadBriefingData() {
    showLoadingState();
    
    try {
        const response = await fetch('/api/briefing');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        briefingData = await response.json();
        renderBriefing(briefingData);
        showBriefingContent();
        updateLastUpdated(briefingData);
        
        // Track refresh time for countdown
        lastRefreshTime = Date.now();
        updateRefreshCountdown();
        
    } catch (error) {
        console.error('Failed to load briefing:', error);
        showErrorState();
    }
}

// =============================================================================
// Agent Constellation
// =============================================================================
// Displays status of all configured agents from Moltbot gateway

const AGENT_EMOJIS = {
    jarvis: '🎩',
    aria: '🔬',
    peter: '📊',
    watson: '🏥',
    willb: '🏢',
    elon: '🚀'
};

const AGENT_NAMES = {
    jarvis: 'Jarvis',
    aria: 'Aria',
    peter: 'Peter',
    watson: 'Dr. Watson',
    willb: 'Will B.',
    elon: 'ELon'
};

async function loadAgentStatus() {
    try {
        const response = await fetch('/api/agents/status');
        if (!response.ok) {
            console.error('Failed to load agent status:', response.status);
            return;
        }
        
        const data = await response.json();
        renderAgentConstellation(data.agents || [], data.fetched_at);
        
    } catch (error) {
        console.error('Failed to load agent status:', error);
    }
}

function renderAgentConstellation(agents, fetchedAt) {
    const container = document.querySelector('#agents-content .agents-grid');
    const countEl = document.getElementById('agents-count');
    
    if (!container) return;
    
    if (agents.length === 0) {
        container.innerHTML = '<div class="empty-state">No agents online</div>';
        if (countEl) countEl.textContent = '0';
        return;
    }
    
    if (countEl) countEl.textContent = agents.length;
    
    // Add staleness indicator
    let staleWarning = '';
    if (fetchedAt) {
        const fetchedTime = new Date(fetchedAt);
        const ageMs = Date.now() - fetchedTime.getTime();
        const ageMins = Math.floor(ageMs / 60000);
        if (ageMins > 30) {
            staleWarning = `<div class="agents-stale-warning">⚠️ Data ${ageMins}m old</div>`;
        }
    }
    
    const agentCards = agents.map(agent => {
        const emoji = AGENT_EMOJIS[agent.id] || '🤖';
        const name = AGENT_NAMES[agent.id] || agent.id;
        const contextPct = agent.context_pct || 0;
        const model = (agent.model || '').split('/').pop().replace('claude-', '').slice(0, 8);
        
        let contextClass = 'low';
        if (contextPct >= 80) contextClass = 'critical';
        else if (contextPct >= 60) contextClass = 'high';
        else if (contextPct >= 30) contextClass = 'medium';
        
        const statusClass = agent.status || 'idle';
        
        return `
            <div class="agent-card status-${statusClass}" data-agent-id="${agent.id}" onclick="openAgentChat('${agent.id}')">
                <span class="agent-emoji">${emoji}</span>
                <div class="agent-info">
                    <div class="agent-name">${name}</div>
                    <div class="agent-meta">
                        <span class="agent-model">${model}</span>
                        <span class="agent-context">
                            <div class="context-bar">
                                <div class="context-fill ${contextClass}" style="width: ${contextPct}%"></div>
                            </div>
                            <span>${contextPct}%</span>
                        </span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = staleWarning + agentCards;
}

function openAgentChat(agentId) {
    // Open webchat with this agent
    const token = '1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c';
    window.open(`http://ether-spark:18789/?agent=${agentId}&token=${token}`, '_blank');
}

// =============================================================================
// Cron Status (Background Jobs)
// =============================================================================

async function loadCronStatus() {
    try {
        const response = await fetch('/api/cron/status');
        if (!response.ok) {
            console.error('Failed to load cron status:', response.status);
            return;
        }
        
        const data = await response.json();
        renderCronStatus(data.runs || [], data.updated_at);
        
    } catch (error) {
        console.error('Failed to load cron status:', error);
    }
}

function renderCronStatus(runs, updatedAt) {
    const container = document.querySelector('#cron-content .cron-runs');
    const countEl = document.getElementById('cron-count');
    const summaryEl = document.getElementById('cron-summary');
    
    if (!container) return;
    
    if (runs.length === 0) {
        container.innerHTML = '<div class="empty-state">No background jobs logged</div>';
        if (countEl) countEl.textContent = '0';
        return;
    }
    
    if (countEl) countEl.textContent = runs.length;
    
    // Count running and recent success/fail
    const running = runs.filter(r => r.status === 'running').length;
    const recent = runs.slice(0, 4);
    const recentSuccess = recent.filter(r => r.status === 'success').length;
    const recentFail = recent.filter(r => r.status === 'error' || r.status === 'failed').length;
    
    // Summary line
    if (summaryEl) {
        let summary = '';
        if (running > 0) {
            summary = `— ${running} running`;
        } else if (recentFail > 0) {
            summary = `— ${recentFail} recent failures`;
        } else {
            summary = '— all recent OK';
        }
        summaryEl.textContent = summary;
    }
    
    // Render run rows
    const runRows = runs.map(run => {
        const statusIcon = {
            'success': '✓',
            'running': '⏳',
            'error': '✗',
            'failed': '✗'
        }[run.status] || '?';
        
        const statusClass = run.status || 'unknown';
        
        // Format time
        let timeStr = '';
        if (run.last_run) {
            const runTime = new Date(run.last_run);
            const ageMs = Date.now() - runTime.getTime();
            const ageMins = Math.floor(ageMs / 60000);
            
            if (ageMins < 1) timeStr = 'just now';
            else if (ageMins < 60) timeStr = `${ageMins}m ago`;
            else {
                const ageHours = Math.floor(ageMins / 60);
                timeStr = `${ageHours}h ago`;
            }
        }
        
        // Duration
        let durationStr = '';
        if (run.duration_ms) {
            const durSec = Math.round(run.duration_ms / 1000);
            durationStr = durSec > 60 ? `${Math.round(durSec/60)}m` : `${durSec}s`;
        }
        
        return `
            <div class="cron-run status-${statusClass}">
                <span class="cron-status-icon">${statusIcon}</span>
                <span class="cron-name">${run.name || run.id}</span>
                <span class="cron-result">${run.result || ''}</span>
                <span class="cron-time">${timeStr}</span>
                ${durationStr ? `<span class="cron-duration">${durationStr}</span>` : ''}
            </div>
        `;
    }).join('');
    
    container.innerHTML = runRows;
}

// Refresh cron status periodically (every 2 minutes)
setInterval(loadCronStatus, 2 * 60 * 1000);

// =============================================================================
// Weather Widget
// =============================================================================

async function loadWeather() {
    try {
        const response = await fetch('/api/weather');
        const data = await response.json();
        
        const compactEl = document.getElementById('weather-compact');
        const forecastEl = document.getElementById('weather-forecast');
        const iconEl = document.getElementById('weather-icon');
        
        // Skip if elements don't exist (widget may be removed from template)
        if (!compactEl && !forecastEl && !iconEl) {
            console.log('[WEATHER] Widget elements not found, skipping');
            return;
        }
        
        if (data.compact && compactEl) {
            // Extract icon from compact string (e.g., "San Jose, CA: ⛅️ +55°F 65% ↙5km/h")
            const iconMatch = data.compact.match(/[\u2600-\u26FF\u2700-\u27BF]|[\uD83C-\uDBFF\uDC00-\uDFFF]+/);
            if (iconMatch && iconEl) {
                iconEl.textContent = iconMatch[0];
            }
            
            // Show compact weather (remove location prefix since we know it)
            const weatherPart = data.compact.replace(/^[^:]+:\s*/, '');
            compactEl.textContent = weatherPart;
        }
        
        if (data.forecast && forecastEl) {
            forecastEl.textContent = data.forecast;
        }
        
    } catch (err) {
        console.error('[WEATHER] Failed to load:', err);
        const compactEl = document.getElementById('weather-compact');
        if (compactEl) compactEl.textContent = 'Weather unavailable';
    }
}

// Refresh weather every 30 minutes
setInterval(loadWeather, 30 * 60 * 1000);

// =============================================================================
// System Health Widget
// =============================================================================

async function loadHealth() {
    try {
        const response = await fetch('/api/health');
        const data = await response.json();
        
        const summaryEl = document.getElementById('health-summary');
        const indicatorsEl = document.getElementById('health-indicators');
        const blockEl = document.getElementById('health-block');
        
        // Skip if widget elements don't exist
        if (!summaryEl || !indicatorsEl || !blockEl) {
            console.log('[HEALTH] Widget elements not found, skipping');
            return;
        }
        
        if (data.services) {
            // Update summary
            summaryEl.textContent = data.summary || 'Services';
            
            // Toggle block style based on health
            if (data.all_ok) {
                blockEl.classList.remove('has-issues');
            } else {
                blockEl.classList.add('has-issues');
            }
            
            // Render indicators
            indicatorsEl.innerHTML = data.services.map(svc => `
                <div class="health-indicator" title="${svc.description || ''} (port ${svc.port || '?'})">
                    <span class="health-dot ${svc.status}"></span>
                    <span class="service-name">${svc.name}</span>
                </div>
            `).join('');
        }
        
    } catch (err) {
        console.error('[HEALTH] Failed to load:', err);
        const summaryEl = document.getElementById('health-summary');
        if (summaryEl) summaryEl.textContent = 'Health check failed';
    }
}

// Refresh health every 5 minutes
setInterval(loadHealth, 5 * 60 * 1000);

// =============================================================================
// System Metrics - CPU, Memory, Disk
// =============================================================================

async function loadSystemMetrics() {
    try {
        const response = await fetch('/api/system-metrics');
        const data = await response.json();
        
        const barsEl = document.getElementById('metrics-bars');
        const uptimeEl = document.getElementById('metrics-uptime');
        
        if (!data.metrics) return;
        
        // Update uptime
        if (uptimeEl && data.metrics.uptime) {
            uptimeEl.textContent = `⏱️ ${data.metrics.uptime}`;
        }
        
        // Build metric bars
        const metricsHtml = [];
        
        if (data.metrics.cpu) {
            const level = data.metrics.cpu.percent > 80 ? 'critical' : (data.metrics.cpu.percent > 60 ? 'warning' : '');
            metricsHtml.push(`
                <div class="metric-item">
                    <span class="metric-label">CPU</span>
                    <div class="metric-bar-container">
                        <div class="metric-bar ${level}" style="width: ${data.metrics.cpu.percent}%"></div>
                    </div>
                    <span class="metric-value">${data.metrics.cpu.percent}%</span>
                </div>
            `);
        }
        
        if (data.metrics.memory) {
            const level = data.metrics.memory.percent > 85 ? 'critical' : (data.metrics.memory.percent > 70 ? 'warning' : '');
            metricsHtml.push(`
                <div class="metric-item">
                    <span class="metric-label">MEM</span>
                    <div class="metric-bar-container">
                        <div class="metric-bar ${level}" style="width: ${data.metrics.memory.percent}%"></div>
                    </div>
                    <span class="metric-value">${data.metrics.memory.used_gb}/${data.metrics.memory.total_gb}G</span>
                </div>
            `);
        }
        
        if (data.metrics.disk) {
            const level = data.metrics.disk.percent > 90 ? 'critical' : (data.metrics.disk.percent > 75 ? 'warning' : '');
            metricsHtml.push(`
                <div class="metric-item">
                    <span class="metric-label">DISK</span>
                    <div class="metric-bar-container">
                        <div class="metric-bar ${level}" style="width: ${data.metrics.disk.percent}%"></div>
                    </div>
                    <span class="metric-value">${data.metrics.disk.used}/${data.metrics.disk.total}</span>
                </div>
            `);
        }
        
        if (barsEl) {
            barsEl.innerHTML = metricsHtml.join('');
        }
        
    } catch (err) {
        console.error('[METRICS] Failed to load:', err);
    }
}

// Refresh metrics every 5 minutes
setInterval(loadSystemMetrics, 5 * 60 * 1000);

// =============================================================================
// Quick Notes - Persistent Scratchpad
// =============================================================================

let notesDebounceTimer = null;
let notesLastSaved = null;

async function loadQuickNotes() {
    try {
        const response = await fetch('/api/notes');
        const data = await response.json();
        
        const textarea = document.getElementById('quick-notes-textarea');
        const statusEl = document.getElementById('notes-status');
        
        if (textarea && data.content) {
            textarea.value = data.content;
        }
        
        if (statusEl && data.updated_at) {
            const updatedAt = new Date(data.updated_at);
            statusEl.textContent = `Last saved ${formatRelativeTime(updatedAt)}`;
        }
        
        // Set up auto-save on input
        if (textarea) {
            textarea.addEventListener('input', debounceNoteSave);
        }
        
    } catch (err) {
        console.error('[NOTES] Failed to load:', err);
    }
}

function debounceNoteSave() {
    const statusEl = document.getElementById('notes-status');
    if (statusEl) {
        statusEl.textContent = 'Saving...';
        statusEl.classList.remove('saved');
    }
    
    // Debounce: wait 1 second after typing stops before saving
    if (notesDebounceTimer) {
        clearTimeout(notesDebounceTimer);
    }
    
    notesDebounceTimer = setTimeout(saveQuickNotes, 1000);
}

async function saveQuickNotes() {
    const textarea = document.getElementById('quick-notes-textarea');
    const statusEl = document.getElementById('notes-status');
    
    if (!textarea) return;
    
    try {
        const response = await fetch('/api/notes', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: textarea.value })
        });
        
        const data = await response.json();
        
        if (statusEl && data.updated_at) {
            statusEl.textContent = 'Saved ✓';
            statusEl.classList.add('saved');
            notesLastSaved = new Date(data.updated_at);
            
            // After 3 seconds, show relative time
            setTimeout(() => {
                if (statusEl && notesLastSaved) {
                    statusEl.textContent = `Last saved ${formatRelativeTime(notesLastSaved)}`;
                    statusEl.classList.remove('saved');
                }
            }, 3000);
        }
        
    } catch (err) {
        console.error('[NOTES] Failed to save:', err);
        if (statusEl) {
            statusEl.textContent = 'Save failed!';
            statusEl.classList.remove('saved');
        }
    }
}

function formatRelativeTime(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
}

// =============================================================================
// Task Queue Summary
// =============================================================================

async function loadQueueSummary() {
    try {
        const response = await fetch('/api/queue/summary');
        const data = await response.json();
        
        const summaryEl = document.getElementById('queue-summary-text');
        const countsEl = document.getElementById('queue-counts');
        
        if (data.error) {
            if (summaryEl) summaryEl.textContent = 'Queue unavailable';
            return;
        }
        
        // Update summary text
        if (summaryEl) {
            const total = data.total || 0;
            const active = data.active || 0;
            summaryEl.textContent = `${total} tasks (${active} active)`;
        }
        
        // Update count indicators
        if (countsEl) {
            const columns = [
                { key: 'active', label: 'Active', value: data.active || 0 },
                { key: 'queued', label: 'Queued', value: data.queued || 0 },
                { key: 'review', label: 'Review', value: data.review || 0 },
                { key: 'ideas', label: 'Ideas', value: data.ideas || 0 }
            ];
            
            countsEl.innerHTML = columns.map(col => `
                <div class="queue-count-item ${col.key}">
                    <span class="count-value">${col.value}</span>
                    <span class="count-label">${col.label}</span>
                </div>
            `).join('');
        }
        
    } catch (err) {
        console.error('[QUEUE] Failed to load summary:', err);
        const summaryEl = document.getElementById('queue-summary-text');
        if (summaryEl) summaryEl.textContent = 'Queue unavailable';
    }
}

// Refresh queue summary every 5 minutes
setInterval(loadQueueSummary, 5 * 60 * 1000);


// =============================================================================
// Morning Summary Widget (AI-generated daily briefing)
// =============================================================================

async function loadMorningSummary(force = false) {
    const contentEl = document.getElementById('morning-summary-content');
    const timeEl = document.getElementById('morning-time');
    const block = document.getElementById('morning-summary-block');
    const refreshBtn = block?.querySelector('.morning-refresh');
    
    if (!contentEl) return;
    
    // Update time greeting
    const now = new Date();
    const hour = now.getHours();
    let greeting = 'Good Morning';
    if (hour >= 12 && hour < 17) greeting = 'Good Afternoon';
    else if (hour >= 17) greeting = 'Good Evening';
    
    const titleEl = block?.querySelector('.morning-title');
    if (titleEl) titleEl.textContent = greeting;
    
    // Show loading state
    contentEl.innerHTML = '<span class="loading-dots">Generating summary...</span>';
    if (refreshBtn) refreshBtn.classList.add('loading');
    
    try {
        const url = force ? '/api/morning-summary?force=true' : '/api/morning-summary';
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.summary) {
            contentEl.textContent = data.summary;
            block?.classList.remove('error');
            
            // Show generation time
            if (timeEl && data.generated_at) {
                const genTime = new Date(data.generated_at);
                const ago = Math.floor((now - genTime) / 60000);
                if (ago < 1) {
                    timeEl.textContent = 'just now';
                } else if (ago < 60) {
                    timeEl.textContent = `${ago}m ago`;
                } else {
                    timeEl.textContent = genTime.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
                }
            }
        } else {
            contentEl.textContent = 'Unable to generate summary.';
            block?.classList.add('error');
        }
    } catch (error) {
        console.error('Failed to load morning summary:', error);
        contentEl.textContent = 'Check your calendar and queue for today\'s priorities.';
        block?.classList.add('error');
    } finally {
        if (refreshBtn) refreshBtn.classList.remove('loading');
    }
}

// Refresh morning summary every 30 minutes
setInterval(() => loadMorningSummary(false), 30 * 60 * 1000);

// Make available globally for the refresh button
window.loadMorningSummary = loadMorningSummary;


// =============================================================================
// Upcoming Meetings Widget
// =============================================================================

async function loadUpcomingMeetings() {
    const refreshBtn = document.querySelector('.meetings-refresh');
    const listEl = document.getElementById('meetings-list');
    const countEl = document.getElementById('meetings-count');
    
    if (refreshBtn) refreshBtn.classList.add('spinning');
    
    try {
        const resp = await fetch('/api/calendar/upcoming');
        const data = await resp.json();
        
        // Update count
        if (countEl) countEl.textContent = data.count || 0;
        
        // Render meetings
        if (!listEl) return;
        
        if (!data.meetings || data.meetings.length === 0) {
            listEl.innerHTML = '<div class="meetings-empty">No meetings remaining today</div>';
            return;
        }
        
        listEl.innerHTML = data.meetings.map(m => {
            const statusClass = m.status === 'now' || m.status === 'soon' ? `status-${m.status}` : '';
            const statusBadge = m.status === 'now' ? '<span class="meeting-status now">NOW</span>' :
                              m.status === 'soon' ? '<span class="meeting-status soon">SOON</span>' : '';
            const location = m.location ? `<span class="meeting-location">${escapeHtml(m.location)}</span>` : '';
            
            return `
                <div class="meeting-item ${statusClass}">
                    <span class="meeting-time">${escapeHtml(m.start_time)}</span>
                    <span class="meeting-title">${escapeHtml(m.title)}</span>
                    ${statusBadge}
                    ${location}
                </div>
            `;
        }).join('');
        
    } catch (err) {
        console.error('Failed to load upcoming meetings:', err);
        if (listEl) listEl.innerHTML = '<div class="meetings-empty">Unable to load calendar</div>';
    } finally {
        if (refreshBtn) refreshBtn.classList.remove('spinning');
    }
}

// Refresh meetings every 5 minutes
setInterval(loadUpcomingMeetings, 5 * 60 * 1000);

// Make available globally
window.loadUpcomingMeetings = loadUpcomingMeetings;


// =============================================================================
// Weekend Preview Widget (Shown Fri-Sun)
// =============================================================================

async function loadWeekendPreview() {
    const blockEl = document.getElementById('weekend-preview-block');
    const saturdayEventsEl = document.getElementById('saturday-events');
    const sundayEventsEl = document.getElementById('sunday-events');
    const saturdayLabelEl = document.getElementById('saturday-label');
    const sundayLabelEl = document.getElementById('sunday-label');
    const refreshBtn = blockEl?.querySelector('.weekend-refresh');
    
    // Only show on Friday, Saturday, or Sunday
    const today = new Date().getDay(); // 0=Sunday, 5=Friday, 6=Saturday
    if (today !== 0 && today !== 5 && today !== 6) {
        if (blockEl) blockEl.style.display = 'none';
        return;
    }
    
    if (blockEl) blockEl.style.display = 'block';
    if (refreshBtn) refreshBtn.classList.add('spinning');
    
    try {
        const resp = await fetch('/api/calendar/weekend');
        const data = await resp.json();
        
        // Update Saturday
        if (saturdayLabelEl && data.saturday?.date) {
            saturdayLabelEl.textContent = data.saturday.date;
        }
        
        if (saturdayEventsEl) {
            if (data.saturday?.events?.length > 0) {
                saturdayEventsEl.innerHTML = data.saturday.events.map(ev => {
                    const isAllDay = ev.is_all_day;
                    return `
                        <div class="weekend-event ${isAllDay ? 'all-day' : ''}">
                            <span class="weekend-event-time">${ev.start_time}</span>
                            <span class="weekend-event-title">${escapeHtml(ev.title)}</span>
                        </div>
                    `;
                }).join('');
            } else if (data.saturday?.date) {
                saturdayEventsEl.innerHTML = '<div class="weekend-free"><span class="icon">✨</span> Free day!</div>';
            } else {
                // It's already Saturday or Sunday - hide Saturday
                const satEl = document.getElementById('weekend-saturday');
                if (satEl) satEl.style.display = 'none';
            }
        }
        
        // Update Sunday
        if (sundayLabelEl && data.sunday?.date) {
            sundayLabelEl.textContent = data.sunday.date;
        }
        
        if (sundayEventsEl) {
            if (data.sunday?.events?.length > 0) {
                sundayEventsEl.innerHTML = data.sunday.events.map(ev => {
                    const isAllDay = ev.is_all_day;
                    return `
                        <div class="weekend-event ${isAllDay ? 'all-day' : ''}">
                            <span class="weekend-event-time">${ev.start_time}</span>
                            <span class="weekend-event-title">${escapeHtml(ev.title)}</span>
                        </div>
                    `;
                }).join('');
            } else {
                sundayEventsEl.innerHTML = '<div class="weekend-free"><span class="icon">✨</span> Free day!</div>';
            }
        }
        
    } catch (err) {
        console.error('Failed to load weekend preview:', err);
        if (saturdayEventsEl) saturdayEventsEl.innerHTML = '<div class="weekend-empty">Unable to load</div>';
        if (sundayEventsEl) sundayEventsEl.innerHTML = '<div class="weekend-empty">Unable to load</div>';
    } finally {
        if (refreshBtn) refreshBtn.classList.remove('spinning');
    }
}

// Load on init (called from page load)
// Refresh every 30 minutes
setInterval(loadWeekendPreview, 30 * 60 * 1000);

// Make available globally
window.loadWeekendPreview = loadWeekendPreview;


// =============================================================================
// Accomplishments Today Widget
// =============================================================================

async function loadAccomplishments() {
    try {
        const resp = await fetch('/api/accomplishments');
        const data = await resp.json();
        
        // Update count
        const countEl = document.getElementById('accomplishments-count');
        if (countEl) countEl.textContent = data.count || 0;
        
        // Render list
        const listEl = document.getElementById('accomplishments-list');
        if (!listEl) return;
        
        if (!data.items || data.items.length === 0) {
            listEl.innerHTML = '<div class="accomplishments-empty">No wins yet today — you got this!</div>';
            return;
        }
        
        let html = '';
        for (const item of data.items) {
            const time = item.added_at ? new Date(item.added_at).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}) : '';
            const deleteBtn = item.type === 'manual' 
                ? `<button class="accomplishment-delete" onclick="deleteAccomplishment('${item.id}')" title="Remove">×</button>`
                : '';
            html += `
                <div class="accomplishment-item">
                    <span class="accomplishment-icon">${item.icon || '✓'}</span>
                    <span class="accomplishment-text">${escapeHtml(item.text)}</span>
                    <span class="accomplishment-time">${time}</span>
                    ${deleteBtn}
                </div>
            `;
        }
        listEl.innerHTML = html;
        
    } catch (err) {
        console.error('[ACCOMPLISHMENTS] Load failed:', err);
    }
}

function showAccomplishmentInput() {
    const row = document.getElementById('accomplishments-input-row');
    if (row) {
        row.style.display = row.style.display === 'none' ? 'flex' : 'none';
        if (row.style.display === 'flex') {
            document.getElementById('accomplishment-input')?.focus();
        }
    }
}

function handleAccomplishmentKeypress(e) {
    if (e.key === 'Enter') {
        saveAccomplishment();
    } else if (e.key === 'Escape') {
        document.getElementById('accomplishments-input-row').style.display = 'none';
    }
}

async function saveAccomplishment() {
    const input = document.getElementById('accomplishment-input');
    const text = input?.value?.trim();
    if (!text) return;
    
    try {
        const resp = await fetch('/api/accomplishments', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text})
        });
        
        if (resp.ok) {
            input.value = '';
            document.getElementById('accomplishments-input-row').style.display = 'none';
            loadAccomplishments();
        }
    } catch (err) {
        console.error('[ACCOMPLISHMENTS] Save failed:', err);
    }
}

async function deleteAccomplishment(itemId) {
    try {
        const resp = await fetch(`/api/accomplishments/${itemId}`, {method: 'DELETE'});
        if (resp.ok) {
            loadAccomplishments();
        }
    } catch (err) {
        console.error('[ACCOMPLISHMENTS] Delete failed:', err);
    }
}

// Helper to escape HTML (reuse if already defined)
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Refresh accomplishments every 5 minutes
setInterval(loadAccomplishments, 5 * 60 * 1000);

// Make functions globally available
window.showAccomplishmentInput = showAccomplishmentInput;
window.handleAccomplishmentKeypress = handleAccomplishmentKeypress;
window.saveAccomplishment = saveAccomplishment;
window.deleteAccomplishment = deleteAccomplishment;


// =============================================================================
// Git Activity Widget
// =============================================================================

async function loadGitActivity(force = false) {
    const listEl = document.getElementById('git-activity-list');
    const countEl = document.getElementById('git-activity-count');
    const refreshBtn = document.querySelector('.git-activity-refresh-btn');
    
    if (!listEl) return;
    
    // Show spinning state on refresh
    if (force && refreshBtn) {
        refreshBtn.classList.add('spinning');
    }
    
    try {
        const url = force ? '/api/git-activity?force=true' : '/api/git-activity';
        const response = await fetch(url);
        const data = await response.json();
        
        const commits = data.commits || [];
        
        // Update count
        if (countEl) {
            countEl.textContent = commits.length;
        }
        
        // Render commits
        if (commits.length === 0) {
            listEl.innerHTML = '<div class="git-activity-empty">No commits in the last 24 hours</div>';
        } else {
            listEl.innerHTML = commits.map(commit => `
                <div class="git-commit-item">
                    <span class="git-commit-repo">${escapeHtml(commit.repo)}</span>
                    <span class="git-commit-message" title="${escapeHtml(commit.message)}">${escapeHtml(commit.message)}</span>
                    <span class="git-commit-time">${escapeHtml(commit.relative_time)}</span>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Failed to load git activity:', error);
        listEl.innerHTML = '<div class="git-activity-empty">Failed to load commits</div>';
    } finally {
        if (refreshBtn) {
            refreshBtn.classList.remove('spinning');
        }
    }
}

// Refresh git activity every 10 minutes
setInterval(loadGitActivity, 10 * 60 * 1000);

// Make globally available
window.loadGitActivity = loadGitActivity;


// ===== WORKING CONTEXT WIDGET =====

async function loadWorkingContext() {
    const grid = document.getElementById('working-context-grid');
    if (!grid) return;
    const refreshBtn = document.querySelector('.working-context-refresh-btn');
    
    if (refreshBtn) refreshBtn.classList.add('spinning');
    
    try {
        const response = await fetch('/api/working-context');
        if (!response.ok) throw new Error('Failed to load working context');
        
        const data = await response.json();
        
        if (!data.agents || data.agents.length === 0) {
            grid.innerHTML = '<div class="wc-no-agents">No agent workspaces found</div>';
            return;
        }
        
        grid.innerHTML = data.agents.map(agent => {
            const isIdle = !agent.context || agent.context.toLowerCase().includes('idle') || !agent.last_updated;
            const idleClass = isIdle ? 'wc-agent-idle' : '';
            
            // Parse the time to show relative
            let timeDisplay = '';
            if (agent.last_updated) {
                // Extract date/time - format is usually "2026-02-06 12:22 PST"
                const parts = agent.last_updated.split(' ');
                if (parts.length >= 2) {
                    timeDisplay = `${parts[0]} ${parts[1]}`;
                } else {
                    timeDisplay = agent.last_updated.substring(0, 16);
                }
            }
            
            // Build sections tags
            let sectionsHtml = '';
            if (agent.active_sections && agent.active_sections.length > 0) {
                sectionsHtml = '<div class="wc-agent-sections">' +
                    agent.active_sections.slice(0, 3).map(s => 
                        `<span class="wc-section-tag">${s}</span>`
                    ).join('') +
                    '</div>';
            }
            
            return `
                <div class="working-context-agent ${idleClass}">
                    <div class="wc-agent-header">
                        <span class="wc-agent-emoji">${agent.emoji}</span>
                        <span class="wc-agent-name">${agent.agent}</span>
                        <span class="wc-agent-time">${timeDisplay}</span>
                    </div>
                    <div class="wc-agent-context">${agent.context || 'No active context'}</div>
                    ${sectionsHtml}
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading working context:', error);
        grid.innerHTML = '<div class="wc-error">Failed to load context</div>';
    } finally {
        if (refreshBtn) refreshBtn.classList.remove('spinning');
    }
}

// Refresh working context every 5 minutes
setInterval(loadWorkingContext, 5 * 60 * 1000);

// Make globally available
window.loadWorkingContext = loadWorkingContext;


function showLoadingState() {
    document.getElementById('loading-state').classList.remove('hidden');
    document.getElementById('error-state').classList.add('hidden');
    document.getElementById('briefing-container').classList.add('hidden');
}

function showErrorState() {
    document.getElementById('loading-state').classList.add('hidden');
    document.getElementById('error-state').classList.remove('hidden');
    document.getElementById('briefing-container').classList.add('hidden');
}

function showBriefingContent() {
    document.getElementById('loading-state').classList.add('hidden');
    document.getElementById('error-state').classList.add('hidden');
    document.getElementById('briefing-container').classList.remove('hidden');
}

function updateLastUpdated(data) {
    const lastUpdatedEl = document.getElementById('last-updated');
    if (lastUpdatedEl) {
        let text = '';
        let className = 'status-fresh';
        
        if (data.cached && data.cached_at) {
            // Show relative time from cached_at
            const cachedTime = new Date(data.cached_at);
            const now = new Date();
            const minutesAgo = Math.floor((now - cachedTime) / 60000);
            
            if (minutesAgo < 1) {
                text = 'Generated just now';
            } else if (minutesAgo === 1) {
                text = 'Generated 1 min ago';
            } else {
                text = `Generated ${minutesAgo} min ago`;
            }
            
            className = 'status-cached';
        } else if (data.generated_at) {
            // Fresh generation - use pre-formatted string directly
            text = `Updated: ${data.generated_at}`;
            className = 'status-fresh';
        }
        
        lastUpdatedEl.textContent = text;
        lastUpdatedEl.className = className;
        
        // Add cached indicator
        const cachedIndicator = document.getElementById('cached-indicator');
        if (cachedIndicator) {
            if (data.cached) {
                cachedIndicator.style.display = 'inline';
                cachedIndicator.textContent = 'cached';
            } else {
                cachedIndicator.style.display = 'none';
            }
        }
    }
}

function renderBriefing(data) {
    if (!data || !data.blocks) return;
    
    // Render each block with error isolation to prevent one failing block from breaking the entire page
    const blocks = [
        ['decisions', () => renderDecisionsBlock(data.blocks.decisions)],
        ['runway', () => renderRunwayBlock(data.blocks.runway)],
        ['threads', () => renderThreadsBlock(data.blocks.threads)],
        ['people', () => renderPeopleBlock(data.blocks.people)],
        ['pulse', () => renderPulseBlock(data.blocks.pulse)],
        ['stale', () => renderStaleBlock(data.blocks.stale)],
        ['snoozed', () => renderSnoozedBlock(data.snoozed)],
    ];
    
    for (const [name, renderFn] of blocks) {
        try {
            renderFn();
        } catch (err) {
            console.error(`[BRIEFING] Error rendering ${name} block:`, err);
            // Continue with other blocks even if this one fails
        }
    }
}

function renderDecisionsBlock(decisions) {
    const countEl = document.querySelector('#decisions-block .block-count');
    const contentEl = document.getElementById('decisions-content');
    
    if (countEl) countEl.textContent = decisions?.count || 0;
    if (!contentEl) return;
    
    if (!decisions || decisions.count === 0) {
        contentEl.innerHTML = '<div class="empty-state">No pending decisions</div>';
        return;
    }
    
    const itemsHtml = decisions.items.map(item => createDecisionItemHtml(item)).join('');
    contentEl.innerHTML = itemsHtml;
}

function createDecisionItemHtml(item) {
    const template = document.getElementById('decision-item-template');
    if (!template) {
        console.error('[BRIEFING] decision-item-template not found');
        return '';
    }
    const clone = document.importNode(template.content, true);
    
    const itemEl = clone.querySelector('.decision-item');
    if (itemEl) {
        itemEl.setAttribute('data-urgency', item.urgency || 'low');
        itemEl.setAttribute('data-id', item.id);
        itemEl.setAttribute('data-type', item.type);
    }
    
    const senderName = clone.querySelector('.sender-name');
    const tierBadge = clone.querySelector('.tier-badge');
    const decisionDays = clone.querySelector('.decision-days');
    const decisionSubject = clone.querySelector('.decision-subject');
    const decisionSummary = clone.querySelector('.decision-summary');
    
    if (senderName) senderName.textContent = item.sender_name || 'Unknown';
    if (tierBadge) tierBadge.textContent = item.tier_badge || '';
    if (decisionDays) decisionDays.textContent = `${item.days_waiting || 0}d ago`;
    if (decisionSubject) decisionSubject.textContent = item.subject || 'No subject';
    if (decisionSummary) decisionSummary.textContent = item.summary || 'No summary';
    
    // Populate date
    const decisionDate = clone.querySelector('.decision-date');
    if (decisionDate && item.received_date) {
        decisionDate.textContent = item.received_date;
    }
    
    // Populate open-in-Outlook link using data attribute (URLs contain & and % that break inline handlers)
    const openLink = clone.querySelector('.decision-open-link');
    if (openLink && item.source_url) {
        openLink.setAttribute('data-url', item.source_url);
        openLink.setAttribute('href', '#');
        openLink.style.display = 'inline';
    } else if (openLink) {
        openLink.style.display = 'none';
    }
    
    // Make subject clickable to open in Outlook
    if (item.source_url && decisionSubject) {
        decisionSubject.style.cursor = 'pointer';
        decisionSubject.setAttribute('data-url', item.source_url);
    }
    
    const wrapper = document.createElement("div"); wrapper.appendChild(clone); return wrapper.innerHTML;
}

function renderRunwayBlock(runway) {
    const countEl = document.querySelector('#runway-block .block-count');
    const contentEl = document.getElementById('runway-items');
    
    if (countEl) countEl.textContent = runway.count || 0;
    
    if (!runway || runway.count === 0 || runway.count === undefined) {
        contentEl.innerHTML = '<div class="empty-state">No items for today</div>';
        return;
    }
    
    let itemsHtml = '';
    
    // Build horizontal timeline for today's events
    const todayItems = (runway.data.timeline_items || []).filter(item => item.day === 'Today');
    if (todayItems.length > 0) {
        itemsHtml += buildHorizontalTimeline(todayItems);
    }
    
    // Tomorrow items removed - timeline focuses on today only
    
    // Add today tasks in collapsible section
    if (runway.data.today_tasks && runway.data.today_tasks.length > 0) {
        const taskCount = runway.data.today_tasks.length;
        itemsHtml += `
            <div class="tasks-stack collapsed" id="tasks-stack">
                <div class="tasks-stack-header" onclick="toggleTasksStack()">
                    <span class="tasks-stack-arrow">▸</span>
                    <span class="tasks-stack-label">Tasks (${taskCount})</span>
                </div>
                <div class="tasks-stack-content">
        `;
        runway.data.today_tasks.forEach(task => {
            itemsHtml += createTodayTaskHtml(task);
        });
        itemsHtml += `
                </div>
            </div>
        `;
    }
    
    contentEl.innerHTML = itemsHtml;
    
    // Update next event display and store for periodic refresh
    globalTimelineItems = runway.data.timeline_items || [];
    updateNextEventDisplay(globalTimelineItems);
}

/**
 * Create HTML for a single runway item (vertical list format).
 * 
 * NOTE: This is superseded by buildHorizontalTimeline() for calendar events.
 * Kept for potential future use (e.g., detailed event view, accessibility mode).
 * 
 * @param {Object} item - Event/task item with time, title, type, etc.
 * @returns {string} HTML string for the item
 */
function createRunwayItemHtml(item) {
    const template = document.getElementById('runway-item-template');
    if (!template) {
        console.error('[BRIEFING] runway-item-template not found');
        return '';
    }
    const clone = document.importNode(template.content, true);
    
    const itemEl = clone.querySelector('.runway-item');
    
    clone.querySelector('.runway-time').textContent = item.time || '--:--';
    clone.querySelector('.runway-title').textContent = item.title || 'Untitled';
    
    let details = '';
    
    if (item.type === 'meeting') {
        // Style meetings differently
        itemEl.style.borderLeft = '3px solid #00d4aa';
        
        // Show attendee information for meetings
        if (item.attendees_count && item.attendee_names) {
            const attendeeText = item.attendee_names.length > 3 
                ? `${item.attendee_names.slice(0, 3).join(', ')}, ...` 
                : item.attendee_names.join(', ');
            details += `${item.attendees_count} attendees: ${attendeeText}`;
        }
        
        if (item.location) {
            if (details) details += ' • ';
            details += item.location;
        }
        
        // Add click handler for webLink
        if (item.webLink) {
            clone.querySelector('.runway-title').style.cursor = 'pointer';
            clone.querySelector('.runway-title').addEventListener('click', () => {
                window.open(item.webLink, '_blank');
            });
        }
    } else {
        // Regular events or tasks
        if (item.attendees_count) {
            details += `${item.attendees_count} attendees`;
        }
        if (item.location) {
            if (details) details += ' • ';
            details += item.location;
        }
        if (item.prep_notes) {
            if (details) details += ' • ';
            details += item.prep_notes;
        }
    }
    
    clone.querySelector('.runway-details').textContent = details;
    
    // Return as HTML string, not DocumentFragment
    const wrapper = document.createElement('div');
    wrapper.appendChild(clone);
    return wrapper.innerHTML;
}

// NOTE: createWorkWindowHtml() was removed - work_windows feature not yet implemented.
// When implemented, add function here to render work window gaps between meetings.

function createTodayTaskHtml(task) {
    const taskId = task.id || '';
    const sourceUrl = task.source_url || '';
    const openBtn = sourceUrl ? `<button class="task-action-btn" onclick="window.open('${sourceUrl}', '_blank')" title="Open in Office 365">Open</button>` : '';
    
    return `
        <div class="runway-item task-item" data-task-id="${taskId}">
            <div class="runway-time data-text">TASK</div>
            <div class="runway-content">
                <div class="runway-title">${task.title || 'Untitled'}</div>
                <div class="task-actions">
                    ${openBtn}
                    <button class="task-action-btn" onclick="addTaskToKanban('${taskId}')" title="Add to Kanban">+ Kanban</button>
                    <select class="task-snooze-select" onchange="snoozeTask('${taskId}', this.value)" title="Snooze">
                        <option value="">Snooze...</option>
                        <option value="1">1 hour</option>
                        <option value="2">2 hours</option>
                        <option value="4">4 hours</option>
                        <option value="8">8 hours</option>
                        <option value="24">Tomorrow</option>
                    </select>
                    <button class="task-action-btn task-delete-btn" onclick="deleteTask('${taskId}')" title="Delete">✕</button>
                </div>
            </div>
        </div>
    `;
}

function renderThreadsBlock(threads) {
    const countEl = document.querySelector('#threads-block .block-count');
    const contentEl = document.getElementById('threads-content');
    
    if (countEl) countEl.textContent = threads.count || 0;
    
    if (threads.count === 0) {
        contentEl.innerHTML = '<div class="empty-state">No active threads</div>';
        return;
    }
    
    const itemsHtml = threads.items.map(item => createThreadItemHtml(item)).join('');
    contentEl.innerHTML = itemsHtml;
}

function createThreadItemHtml(item) {
    const template = document.getElementById('thread-item-template');
    if (!template) {
        console.error('[BRIEFING] thread-item-template not found');
        return '';
    }
    const clone = document.importNode(template.content, true);
    
    const itemEl = clone.querySelector('.thread-item');
    itemEl.setAttribute('data-id', item.id || '');
    itemEl.setAttribute('data-type', 'thread');
    
    clone.querySelector('.thread-title').textContent = item.title || 'Untitled Thread';
    clone.querySelector('.thread-days').textContent = `${item.days_since_activity || 0} days ago`;
    clone.querySelector('.thread-participants').textContent = 
        item.participants ? `Participants: ${item.participants.join(', ')}` : 'No participants';
    clone.querySelector('.thread-status').textContent = item.status || 'No status';
    clone.querySelector('.thread-next-action').textContent = item.next_action || 'No action defined';
    
    const wrapper = document.createElement("div"); wrapper.appendChild(clone); return wrapper.innerHTML;
}

function renderPeopleBlock(people) {
    const countEl = document.querySelector('#people-block .block-count');
    const contentEl = document.getElementById('people-content');
    
    if (countEl) countEl.textContent = people.count || 0;
    
    if (people.count === 0) {
        contentEl.innerHTML = '<div class="empty-state">No incoming items</div>';
        return;
    }
    
    const itemsHtml = people.items.map(item => createPeopleItemHtml(item)).join('');
    contentEl.innerHTML = itemsHtml;
}

function createPeopleItemHtml(item) {
    const template = document.getElementById('people-item-template');
    if (!template) {
        console.error('[BRIEFING] people-item-template not found');
        return '';
    }
    const clone = document.importNode(template.content, true);
    
    const itemEl = clone.querySelector('.people-item');
    if (itemEl) {
        itemEl.setAttribute('data-id', item.id);
        itemEl.setAttribute('data-type', item.type);
    }
    
    const contactName = clone.querySelector('.contact-name');
    const tierBadge = clone.querySelector('.tier-badge');
    const peopleDays = clone.querySelector('.people-days');
    const peopleSubject = clone.querySelector('.people-subject');
    const peopleAction = clone.querySelector('.people-action');
    
    if (contactName) contactName.textContent = item.name || 'Unknown';
    if (tierBadge) tierBadge.textContent = item.tier || '';
    if (peopleDays) peopleDays.textContent = `${item.days_waiting || 0} days`;
    if (peopleSubject) peopleSubject.textContent = item.subject || 'No subject';
    if (peopleAction) peopleAction.textContent = item.action_needed || 'Review needed';
    
    // Set Open link href
    const openLink = clone.querySelector('.open-link');
    if (item.source_url && openLink) {
        openLink.href = item.source_url;
    } else if (openLink) {
        openLink.style.display = 'none';
        // Hide the separator before it
        const seps = clone.querySelectorAll('.action-sep');
        if (seps.length > 0) seps[seps.length - 1].style.display = 'none';
    }
    
    const wrapper = document.createElement("div"); wrapper.appendChild(clone); return wrapper.innerHTML;
}

function renderStaleBlock(stale) {
    const countEl = document.querySelector('#stale-block .block-count');
    const contentEl = document.getElementById('stale-content');
    
    if (countEl) countEl.textContent = stale.count || 0;
    if (!contentEl) return;
    
    if (stale.count === 0) {
        contentEl.innerHTML = '<div class="empty-state">No stale items</div>';
        return;
    }
    
    const itemsHtml = stale.items.map(item => createStaleItemHtml(item)).join('');
    contentEl.innerHTML = itemsHtml;
}

function createStaleItemHtml(item) {
    const template = document.getElementById('stale-item-template');
    if (!template) {
        console.error('[BRIEFING] stale-item-template not found');
        return '';
    }
    const clone = document.importNode(template.content, true);
    
    const itemEl = clone.querySelector('.stale-item');
    if (itemEl) {
        itemEl.setAttribute('data-id', item.id);
        itemEl.setAttribute('data-type', item.type);
    }
    
    const staleTitle = clone.querySelector('.stale-title');
    const staleDays = clone.querySelector('.stale-days');
    const staleSource = clone.querySelector('.stale-source');
    
    if (staleTitle) staleTitle.textContent = item.title || 'Untitled';
    if (staleDays) staleDays.textContent = `${item.days_stale || 0}d`;
    if (staleSource) staleSource.textContent = item.source || '';
    
    // Set Open link href
    const openLink = clone.querySelector('.open-link');
    if (item.source_url && openLink) {
        openLink.href = item.source_url;
    } else if (openLink) {
        openLink.style.display = 'none';
        // Also hide the separator before it
        const seps = clone.querySelectorAll('.action-sep');
        if (seps.length > 0) seps[seps.length - 1].style.display = 'none';
    }
    
    const wrapper = document.createElement("div"); wrapper.appendChild(clone); return wrapper.innerHTML;
}

function renderPulseBlock(pulse) {
    const contentEl = document.querySelector('#pulse-content .pulse-text');
    const metaEl = document.querySelector('#pulse-generated-at');
    
    if (pulse.content) {
        // Convert bullet points to HTML
        const content = pulse.content.replace(/^• (.+)$/gm, '<li>$1</li>');
        const hasListItems = content.includes('<li>');
        
        if (hasListItems) {
            contentEl.innerHTML = `<ul>${content}</ul>`;
        } else {
            contentEl.innerHTML = `<p>${content}</p>`;
        }
    } else {
        contentEl.innerHTML = '<p>No pulse data available</p>';
    }
    
    if (metaEl && pulse.generated_at) {
        metaEl.textContent = `Generated at: ${pulse.generated_at}`;
    }
}

function renderSnoozedBlock(snoozed) {
    const countEl = document.querySelector('#snoozed-block .block-count');
    const contentEl = document.getElementById('snoozed-content');
    
    if (countEl) countEl.textContent = snoozed.count || 0;
    
    if (snoozed.count === 0) {
        contentEl.innerHTML = '<div class="empty-state">No snoozed items</div>';
        return;
    }
    
    let itemsHtml = '';
    snoozed.items.forEach(item => {
        const wakeDate = new Date(item.wake_at);
        const wakeStr = wakeDate.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZone: 'America/Los_Angeles'
        });
        
        itemsHtml += `
            <div class="stale-item" data-snooze-id="${item.id}">
                <div class="stale-content">
                    <div class="stale-header">
                        <span class="stale-title">${item.title}</span>
                        <span class="stale-days data-text">Wake: ${wakeStr}</span>
                    </div>
                    <div class="stale-source">${item.context}</div>
                    <div class="stale-actions">
                        <button class="action-btn" onclick="unsnoozeItem('${item.id}')">Unsnooze</button>
                    </div>
                </div>
            </div>
        `;
    });
    
    contentEl.innerHTML = itemsHtml;
}

// Update block item count (delta: +1 or -1)
function updateBlockCount(blockEl, delta) {
    if (!blockEl) return;
    const countEl = blockEl.querySelector('.block-count');
    if (countEl) {
        const current = parseInt(countEl.textContent) || 0;
        countEl.textContent = Math.max(0, current + delta);
    }
}

// Block toggle functionality
function toggleBlock(blockName) {
    const block = document.getElementById(`${blockName}-block`);
    const arrow = block.querySelector('.block-fold-arrow');
    const isCollapsed = block.classList.contains('collapsed');
    
    if (isCollapsed) {
        block.classList.remove('collapsed');
        arrow.textContent = '▾';
        blockStates[blockName] = true;
    } else {
        block.classList.add('collapsed');
        arrow.textContent = '▸';
        blockStates[blockName] = false;
    }
    
    saveBlockStates();
}

function saveBlockStates() {
    localStorage.setItem('briefing_block_states', JSON.stringify(blockStates));
}

function restoreBlockStates() {
    const saved = localStorage.getItem('briefing_block_states');
    if (saved) {
        try {
            const states = JSON.parse(saved);
            Object.assign(blockStates, states);
        } catch (e) {
            console.warn('Failed to parse saved block states');
        }
    }
    
    // Apply states
    Object.entries(blockStates).forEach(([blockName, isExpanded]) => {
        const block = document.getElementById(`${blockName}-block`);
        if (block) {
            const arrow = block.querySelector('.block-fold-arrow');
            if (isExpanded) {
                block.classList.remove('collapsed');
                if (arrow) arrow.textContent = '▾';
            } else {
                block.classList.add('collapsed');
                if (arrow) arrow.textContent = '▸';
            }
        }
    });
}

// =============================================================================
// Snooze System
// =============================================================================
// Allows temporarily hiding items from the briefing.
// Items reappear when their wake_at time passes (checked on each refresh).
// Snooze data stored server-side in data/snoozed.json.

function openSnoozeModal(buttonEl) {
    const itemEl = buttonEl.closest('[data-id]');
    if (!itemEl) return;
    
    const itemId = itemEl.getAttribute('data-id');
    const itemType = itemEl.getAttribute('data-type');
    let title = 'Unknown Item';
    
    // Get title based on item type
    if (itemType === 'email') {
        const subjectEl = itemEl.querySelector('.decision-subject, .people-subject');
        if (subjectEl) title = subjectEl.textContent;
    } else if (itemType === 'task') {
        const titleEl = itemEl.querySelector('.stale-title, .runway-title');
        if (titleEl) title = titleEl.textContent;
    } else if (itemType === 'thread') {
        const titleEl = itemEl.querySelector('.thread-title');
        if (titleEl) title = titleEl.textContent;
    }
    
    currentSnoozeItem = {
        id: itemId,
        type: itemType,
        title: title,
        element: itemEl
    };
    
    document.getElementById('snooze-item-title').textContent = `Snoozing: ${title}`;
    document.getElementById('snooze-modal').classList.remove('hidden');
    
    // Set up snooze option event listeners
    document.querySelectorAll('.snooze-option[data-hours], .snooze-option[data-days], .snooze-option[data-preset]').forEach(btn => {
        btn.onclick = () => snoozeWithOption(btn);
    });
}

function closeSnoozeModal() {
    document.getElementById('snooze-modal').classList.add('hidden');
    currentSnoozeItem = null;
}

function snoozeWithOption(buttonEl) {
    if (!currentSnoozeItem) return;
    
    const hours = buttonEl.getAttribute('data-hours');
    const days = buttonEl.getAttribute('data-days');
    const preset = buttonEl.getAttribute('data-preset');
    
    let wakeAt;
    const now = new Date();
    
    if (hours) {
        wakeAt = new Date(now.getTime() + parseInt(hours) * 60 * 60 * 1000);
    } else if (days) {
        wakeAt = new Date(now.getTime() + parseInt(days) * 24 * 60 * 60 * 1000);
        wakeAt.setHours(9, 0, 0, 0); // 9 AM PT
    } else if (preset === 'tomorrow') {
        wakeAt = new Date(now);
        wakeAt.setDate(wakeAt.getDate() + 1);
        wakeAt.setHours(9, 0, 0, 0); // 9 AM PT
    } else if (preset === 'next-week') {
        wakeAt = new Date(now);
        const daysToMonday = (8 - wakeAt.getDay()) % 7;
        wakeAt.setDate(wakeAt.getDate() + daysToMonday);
        wakeAt.setHours(9, 0, 0, 0); // 9 AM PT Monday
    }
    
    if (wakeAt) {
        snoozeItem(wakeAt.toISOString());
    }
}

function snoozeToCustomDate() {
    if (!currentSnoozeItem) return;
    
    const dateInput = document.getElementById('custom-snooze-date');
    const dateValue = dateInput.value;
    
    if (!dateValue) {
        alert('Please select a date');
        return;
    }
    
    const wakeAt = new Date(dateValue);
    wakeAt.setHours(9, 0, 0, 0); // 9 AM PT
    
    snoozeItem(wakeAt.toISOString());
}

async function snoozeItem(wakeAt) {
    if (!currentSnoozeItem) return;
    
    const snoozeData = {
        item_id: currentSnoozeItem.id,
        type: currentSnoozeItem.type,
        source_id: currentSnoozeItem.id,
        title: currentSnoozeItem.title,
        context: `Snoozed from briefing`,
        wake_at: wakeAt,
        original_block: getOriginalBlockName(currentSnoozeItem.element)
    };
    
    try {
        const response = await fetch('/api/snooze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(snoozeData)
        });
        
        if (response.ok) {
            // Remove item from UI and update count
            const block = currentSnoozeItem.element.closest('.briefing-block');
            currentSnoozeItem.element.remove();
            closeSnoozeModal();
            updateBlockCount(block, -1);
        } else {
            alert('Failed to snooze item');
        }
    } catch (error) {
        console.error('Error snoozing item:', error);
        alert('Failed to snooze item');
    }
}

function getOriginalBlockName(itemEl) {
    if (itemEl.closest('#decisions-block')) return 'decisions';
    if (itemEl.closest('#people-block')) return 'people';
    if (itemEl.closest('#threads-block')) return 'threads';
    if (itemEl.closest('#stale-block')) return 'stale';
    return 'unknown';
}

async function unsnoozeItem(snoozeId) {
    try {
        const response = await fetch(`/api/snooze/${snoozeId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            // Remove from snoozed list in UI
            const itemEl = document.querySelector(`[data-snooze-id="${snoozeId}"]`);
            if (itemEl) {
                const block = itemEl.closest('.briefing-block');
                itemEl.remove();
                updateBlockCount(block, -1);
            }
        } else {
            alert('Failed to unsnooze item');
        }
    } catch (error) {
        console.error('Error unsnoozing item:', error);
        alert('Failed to unsnooze item');
    }
}

async function markItemDone(buttonEl) {
    const itemEl = buttonEl.closest('[data-id]');
    if (!itemEl) return;
    
    const itemId = itemEl.getAttribute('data-id');
    const itemType = itemEl.getAttribute('data-type');
    
    try {
        const response = await fetch(`/api/briefing/item/${itemId}/done`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                item_id: itemId,
                type: itemType
            })
        });
        
        if (response.ok) {
            // Remove item from UI and update count
            const block = itemEl.closest('.briefing-block');
            itemEl.remove();
            updateBlockCount(block, -1);
        } else {
            alert('Failed to mark item as done');
        }
    } catch (error) {
        console.error('Error marking item done:', error);
        alert('Failed to mark item as done');
    }
}

async function refreshBriefing() {
    showLoadingState();
    
    try {
        const response = await fetch('/api/briefing/refresh', {
            method: 'POST'
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        briefingData = await response.json();
        renderBriefing(briefingData);
        showBriefingContent();
        updateLastUpdated(briefingData);
        
    } catch (error) {
        console.error('Failed to refresh briefing:', error);
        showErrorState();
    }
}

async function refreshPulse() {
    try {
        const response = await fetch('/api/briefing/pulse');
        if (response.ok) {
            const data = await response.json();
            renderPulseBlock(data);
        }
    } catch (error) {
        console.error('Failed to refresh pulse:', error);
    }
}

async function resetPulse() {
    if (!confirm('Reset weekly pulse? This clears all accumulated daily entries.')) {
        return;
    }
    try {
        const response = await fetch('/api/briefing/pulse/reset', { method: 'POST' });
        if (response.ok) {
            // Refresh to regenerate
            await refreshPulse();
        }
    } catch (error) {
        console.error('Failed to reset pulse:', error);
    }
}

// Close modal when clicking outside
document.addEventListener('click', function(event) {
    const modal = document.getElementById('snooze-modal');
    if (event.target === modal) {
        closeSnoozeModal();
    }
});

// Delegated click handler for Outlook links (data-url survives innerHTML serialization)
document.addEventListener('click', function(event) {
    const el = event.target.closest('[data-url]');
    if (el && el.dataset.url) {
        event.preventDefault();
        event.stopPropagation();
        window.open(el.dataset.url, '_blank');
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeSnoozeModal();
    }
    if (event.key === 'r' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        refreshBriefing();
    }
});

// Make functions globally available
window.toggleBlock = toggleBlock;
window.openSnoozeModal = openSnoozeModal;
window.closeSnoozeModal = closeSnoozeModal;
window.snoozeToCustomDate = snoozeToCustomDate;
window.unsnoozeItem = unsnoozeItem;
window.markItemDone = markItemDone;
window.refreshPulse = refreshPulse;
window.resetPulse = resetPulse;
// Toggle tasks stack collapsed/expanded
function toggleTasksStack() {
    const stack = document.getElementById('tasks-stack');
    if (stack) {
        stack.classList.toggle('collapsed');
    }
}

window.toggleTasksStack = toggleTasksStack;

// Task actions
async function deleteTask(taskId) {
    if (!taskId) return;
    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (response.ok) {
            const el = document.querySelector(`[data-task-id="${taskId}"]`);
            if (el) el.remove();
            updateTaskCount();
        }
    } catch (e) {
        console.error('Failed to delete task:', e);
    }
}

async function addTaskToKanban(taskId) {
    if (!taskId) return;
    try {
        const response = await fetch(`/api/tasks/${taskId}/to-kanban`, { method: 'POST' });
        if (response.ok) {
            const el = document.querySelector(`[data-task-id="${taskId}"]`);
            if (el) el.remove();
            updateTaskCount();
        }
    } catch (e) {
        console.error('Failed to add to kanban:', e);
    }
}

async function snoozeTask(taskId, hours) {
    if (!taskId || !hours) return;
    try {
        const response = await fetch(`/api/tasks/${taskId}/snooze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hours: parseInt(hours) })
        });
        if (response.ok) {
            const el = document.querySelector(`[data-task-id="${taskId}"]`);
            if (el) el.remove();
            updateTaskCount();
        }
    } catch (e) {
        console.error('Failed to snooze task:', e);
    }
}

function updateTaskCount() {
    const stack = document.getElementById('tasks-stack');
    if (stack) {
        const count = stack.querySelectorAll('.task-item').length;
        const label = stack.querySelector('.tasks-stack-label');
        if (label) label.textContent = `Tasks (${count})`;
        if (count === 0) stack.remove();
    }
}

window.deleteTask = deleteTask;
window.addTaskToKanban = addTaskToKanban;
window.snoozeTask = snoozeTask;

// Archive item (similar to done but different semantics - item is not actionable)
async function archiveItem(buttonEl) {
    const itemEl = buttonEl.closest('[data-id]');
    if (!itemEl) return;
    
    const itemId = itemEl.getAttribute('data-id');
    const itemType = itemEl.getAttribute('data-type');
    
    try {
        const response = await fetch(`/api/briefing/item/${itemId}/archive`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                item_id: itemId,
                type: itemType
            })
        });
        
        if (response.ok) {
            // Remove item from UI with a nice fade
            itemEl.style.opacity = '0.5';
            itemEl.style.textDecoration = 'line-through';
            setTimeout(() => {
                const block = itemEl.closest('.briefing-block');
                itemEl.remove();
                updateBlockCount(block, -1);
            }, 300);
        } else {
            alert('Failed to archive item');
        }
    } catch (error) {
        console.error('Error archiving item:', error);
        alert('Failed to archive item');
    }
}

window.archiveItem = archiveItem;

// =============================================================================
// Horizontal Timeline
// =============================================================================

/**
 * Build horizontal timeline visualization for today's calendar events.
 * 
 * Features:
 * - Shows 6 AM - 6 PM by default (expands if events outside this range)
 * - Meeting blocks sized by actual duration
 * - NOW marker with red vertical line
 * - Overlap detection: yellow for 2 meetings, red for 3+ (triple-booked)
 * - Click blocks to open in Office 365
 * - Past events shown with reduced opacity
 * 
 * @param {Array} events - Array of event objects with time, duration_mins, title, webLink
 * @returns {string} HTML string for the timeline
 */
function buildHorizontalTimeline(events) {
    // Determine time range (6 AM to 6 PM default, expand if needed)
    let startHour = 6;
    let endHour = 18;
    
    events.forEach(e => {
        const hour = parseInt(e.time?.split(':')[0] || '12');
        if (hour < startHour) startHour = Math.max(0, hour - 1);
        if (hour >= endHour) endHour = Math.min(24, hour + 2);
    });
    
    const totalHours = endHour - startHour;
    
    // Build hour labels
    let hoursHtml = '';
    for (let h = startHour; h < endHour; h++) {
        const label = h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h-12}p`;
        hoursHtml += `<div class="timeline-hour">${label}</div>`;
    }
    
    // Calculate positions and detect overlaps
    const eventBlocks = [];
    events.forEach(event => {
        const [hours, mins] = (event.time || '12:00').split(':').map(Number);
        const startMins = (hours - startHour) * 60 + (mins || 0);
        const durationMins = event.duration_mins || 60; // Default 1 hour if not specified
        
        const leftPercent = (startMins / (totalHours * 60)) * 100;
        const widthPercent = (durationMins / (totalHours * 60)) * 100;
        
        eventBlocks.push({
            ...event,
            left: leftPercent,
            width: Math.max(widthPercent, 3), // Minimum 3% width
            startMins,
            endMins: startMins + durationMins
        });
    });
    
    // Detect overlaps
    eventBlocks.forEach((block, i) => {
        let overlapLevel = 0;
        for (let j = 0; j < i; j++) {
            const other = eventBlocks[j];
            if (block.startMins < other.endMins && block.endMins > other.startMins) {
                overlapLevel = Math.max(overlapLevel, (other.overlapLevel || 0) + 1);
            }
        }
        block.overlapLevel = overlapLevel;
    });
    
    // Current time marker
    const now = new Date();
    const nowHour = now.getHours();
    const nowMin = now.getMinutes();
    const nowMins = (nowHour - startHour) * 60 + nowMin;
    const nowPercent = (nowMins / (totalHours * 60)) * 100;
    const showNowMarker = nowPercent >= 0 && nowPercent <= 100;
    
    // Build event blocks HTML
    let eventsHtml = '';
    eventBlocks.forEach(block => {
        const isPast = block.startMins < nowMins - 30;
        const overlapClass = block.overlapLevel === 1 ? 'overlap' : block.overlapLevel >= 2 ? 'overlap-2' : '';
        const pastClass = isPast ? 'past' : '';
        const url = block.webLink || '';
        const onclick = url ? `onclick="window.open('${url}', '_blank')"` : '';
        
        eventsHtml += `
            <div class="timeline-event ${overlapClass} ${pastClass}" 
                 style="left:${block.left}%; width:${block.width}%;"
                 title="${block.time} - ${block.title}"
                 ${onclick}>
                ${block.title}
            </div>
        `;
    });
    
    // Check for conflicts
    const hasOverlap = eventBlocks.some(b => b.overlapLevel > 0);
    const hasConflict = eventBlocks.some(b => b.overlapLevel >= 2);
    
    return `
        <div class="timeline-horizontal">
            <div class="timeline-hours">${hoursHtml}</div>
            <div class="timeline-events">
                ${eventsHtml}
                ${showNowMarker ? `<div class="timeline-now" style="left:${nowPercent}%"></div>` : ''}
            </div>
        </div>
        ${hasOverlap ? `
        <div class="timeline-legend">
            <span><span class="dot normal"></span> Scheduled</span>
            ${hasOverlap ? '<span><span class="dot overlap"></span> Overlap</span>' : ''}
            ${hasConflict ? '<span><span class="dot conflict"></span> Double-booked!</span>' : ''}
        </div>
        ` : ''}
    `;
}

window.buildHorizontalTimeline = buildHorizontalTimeline;

// Update next event display
function updateNextEventDisplay(timelineItems) {
    const nameEl = document.getElementById('next-event-name');
    const timeEl = document.getElementById('next-event-time');
    
    if (!nameEl || !timeEl) return;
    
    const now = new Date();
    const nowMins = now.getHours() * 60 + now.getMinutes();
    
    // Find next upcoming event (today only)
    const todayItems = (timelineItems || []).filter(item => item.day === 'Today');
    let nextEvent = null;
    let minDiff = Infinity;
    
    todayItems.forEach(item => {
        const [hours, mins] = (item.time || '00:00').split(':').map(Number);
        const eventMins = hours * 60 + mins;
        const diff = eventMins - nowMins;
        
        // Event is in the future and closer than current best
        if (diff > 0 && diff < minDiff) {
            minDiff = diff;
            nextEvent = item;
        }
    });
    
    if (nextEvent) {
        nameEl.textContent = nextEvent.title || 'Untitled';
        
        // Format time remaining
        const hours = Math.floor(minDiff / 60);
        const mins = minDiff % 60;
        let timeStr = '';
        if (hours > 0) {
            timeStr = `in ${hours}h ${mins}m`;
        } else {
            timeStr = `in ${mins}m`;
        }
        timeEl.textContent = timeStr;
    } else {
        nameEl.textContent = 'No more events today';
        timeEl.textContent = '';
    }
}

// Update next event display every minute (uses global globalTimelineItems)
setInterval(() => {
    updateNextEventDisplay(globalTimelineItems);
}, 60000);

window.updateNextEventDisplay = updateNextEventDisplay;

// ======================= 
// Pomodoro Timer Widget   
// ======================= 

let pomodoroState = {
    timeRemaining: 25 * 60,  // seconds
    totalTime: 25 * 60,
    isRunning: false,
    isBreak: false,
    intervalId: null,
    todayPomodoros: 0
};

function loadPomodoroState() {
    const saved = localStorage.getItem('pomodoroState');
    if (saved) {
        const parsed = JSON.parse(saved);
        // Reset if it's a new day
        const lastDate = parsed.date;
        const today = new Date().toDateString();
        if (lastDate !== today) {
            parsed.todayPomodoros = 0;
        }
        pomodoroState.todayPomodoros = parsed.todayPomodoros || 0;
    }
    updatePomodoroDisplay();
    updatePomodoroStats();
}

function savePomodoroState() {
    localStorage.setItem('pomodoroState', JSON.stringify({
        todayPomodoros: pomodoroState.todayPomodoros,
        date: new Date().toDateString()
    }));
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function updatePomodoroDisplay() {
    const timerEl = document.getElementById('pomodoro-timer');
    const progressEl = document.getElementById('pomodoro-progress');
    const startBtn = document.getElementById('pomodoro-start');
    const block = document.getElementById('pomodoro-block');
    
    if (timerEl) {
        timerEl.textContent = formatTime(pomodoroState.timeRemaining);
        timerEl.classList.toggle('running', pomodoroState.isRunning);
    }
    
    if (progressEl) {
        const percent = (pomodoroState.timeRemaining / pomodoroState.totalTime) * 100;
        progressEl.style.width = percent + '%';
    }
    
    if (startBtn) {
        startBtn.textContent = pomodoroState.isRunning ? 'Pause' : 'Start';
    }
    
    if (block) {
        block.classList.toggle('break-mode', pomodoroState.isBreak);
    }
}

function updatePomodoroStats() {
    const statsEl = document.getElementById('pomodoro-stats');
    if (statsEl) {
        const plural = pomodoroState.todayPomodoros === 1 ? 'pomodoro' : 'pomodoros';
        statsEl.textContent = `Today: ${pomodoroState.todayPomodoros} ${plural} completed`;
    }
}

function togglePomodoro() {
    if (pomodoroState.isRunning) {
        // Pause
        clearInterval(pomodoroState.intervalId);
        pomodoroState.isRunning = false;
    } else {
        // Start
        pomodoroState.isRunning = true;
        pomodoroState.intervalId = setInterval(() => {
            pomodoroState.timeRemaining--;
            updatePomodoroDisplay();
            
            if (pomodoroState.timeRemaining <= 0) {
                pomodoroComplete();
            }
        }, 1000);
    }
    updatePomodoroDisplay();
}

function pomodoroComplete() {
    clearInterval(pomodoroState.intervalId);
    pomodoroState.isRunning = false;
    
    // Play notification sound
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2teleVkwHEV2kLB0');
        audio.play().catch(() => {});
    } catch (e) {}
    
    // Show browser notification if permitted
    if (Notification.permission === 'granted') {
        new Notification(pomodoroState.isBreak ? 'Break Over!' : 'Pomodoro Complete!', {
            body: pomodoroState.isBreak ? 'Time to focus!' : 'Great work! Take a break.',
            icon: '🍅'
        });
    }
    
    if (!pomodoroState.isBreak) {
        // Completed a work session
        pomodoroState.todayPomodoros++;
        savePomodoroState();
        updatePomodoroStats();
        
        // Add to accomplishments
        addPomodoroAccomplishment();
        
        // Auto-switch to break
        setPomodoroDuration(5, true);
    } else {
        // Completed a break
        setPomodoroDuration(25, false);
    }
    
    updatePomodoroDisplay();
}

function addPomodoroAccomplishment() {
    // Add completed pomodoro to accomplishments
    fetch('/api/accomplishments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            text: `Completed a 25-minute focus session 🍅`
        })
    }).then(() => {
        // Reload accomplishments if function exists
        if (typeof loadAccomplishments === 'function') {
            loadAccomplishments();
        }
    }).catch(() => {});
}

function resetPomodoro() {
    clearInterval(pomodoroState.intervalId);
    pomodoroState.isRunning = false;
    pomodoroState.timeRemaining = pomodoroState.totalTime;
    updatePomodoroDisplay();
}

function setPomodoroDuration(minutes, isBreak = false) {
    clearInterval(pomodoroState.intervalId);
    pomodoroState.isRunning = false;
    pomodoroState.isBreak = isBreak;
    pomodoroState.totalTime = minutes * 60;
    pomodoroState.timeRemaining = minutes * 60;
    
    // Update preset buttons
    document.querySelectorAll('.pomodoro-preset').forEach(btn => {
        btn.classList.remove('active');
        const btnMins = parseInt(btn.textContent);
        const btnIsBreak = btn.textContent.includes('break');
        if (btnMins === minutes && btnIsBreak === isBreak) {
            btn.classList.add('active');
        }
    });
    
    updatePomodoroDisplay();
}

// Request notification permission on page load
if ('Notification' in window && Notification.permission === 'default') {
    // Request permission silently on first interaction
    document.addEventListener('click', function requestNotificationPermission() {
        Notification.requestPermission();
        document.removeEventListener('click', requestNotificationPermission);
    }, { once: true });
}

// Initialize pomodoro on page load
document.addEventListener('DOMContentLoaded', loadPomodoroState);

// Expose functions globally
window.togglePomodoro = togglePomodoro;
window.resetPomodoro = resetPomodoro;
window.setPomodoroDuration = setPomodoroDuration;

// =============================================================================
// Keyboard Shortcuts System
// =============================================================================

const keyboardShortcuts = {
    pending: null,  // For two-key sequences like 'g b'
    timeout: null,
    
    shortcuts: {
        // Navigation (g + key)
        'g b': { action: () => window.location.href = '/briefing', desc: 'Go to Briefing' },
        'g e': { action: () => window.location.href = '/email', desc: 'Go to Email' },
        'g q': { action: () => window.location.href = '/queue', desc: 'Go to Queue' },
        'g s': { action: () => window.location.href = '/synapse', desc: 'Go to Synapse' },
        'g k': { action: () => window.location.href = '/', desc: 'Go to Kanban' },
        
        // Actions
        'p': { action: togglePomodoro, desc: 'Start/Pause Pomodoro' },
        'r': { action: () => document.getElementById('refresh-btn')?.click(), desc: 'Refresh data' },
        '?': { action: toggleShortcutsModal, desc: 'Show keyboard shortcuts' },
        'Escape': { action: closeShortcutsModal, desc: 'Close modal' }
    }
};

function handleKeyboardShortcut(e) {
    // Ignore if user is typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
        return;
    }
    
    const key = e.key.toLowerCase();
    
    // Handle Escape specially
    if (e.key === 'Escape') {
        closeShortcutsModal();
        keyboardShortcuts.pending = null;
        return;
    }
    
    // Handle ? for help
    if (e.key === '?') {
        e.preventDefault();
        toggleShortcutsModal();
        return;
    }
    
    // Check for pending two-key sequence
    if (keyboardShortcuts.pending) {
        clearTimeout(keyboardShortcuts.timeout);
        const combo = `${keyboardShortcuts.pending} ${key}`;
        keyboardShortcuts.pending = null;
        
        if (keyboardShortcuts.shortcuts[combo]) {
            e.preventDefault();
            keyboardShortcuts.shortcuts[combo].action();
            return;
        }
    }
    
    // Check for single-key shortcut
    if (keyboardShortcuts.shortcuts[key]) {
        e.preventDefault();
        keyboardShortcuts.shortcuts[key].action();
        return;
    }
    
    // Start two-key sequence for 'g'
    if (key === 'g') {
        e.preventDefault();
        keyboardShortcuts.pending = 'g';
        keyboardShortcuts.timeout = setTimeout(() => {
            keyboardShortcuts.pending = null;
        }, 1000);  // 1 second to complete sequence
        showShortcutHint('g...');
    }
}

function showShortcutHint(text) {
    let hint = document.getElementById('shortcut-hint');
    if (!hint) {
        hint = document.createElement('div');
        hint.id = 'shortcut-hint';
        hint.className = 'shortcut-hint';
        document.body.appendChild(hint);
    }
    hint.textContent = text;
    hint.classList.add('visible');
    setTimeout(() => hint.classList.remove('visible'), 800);
}

function toggleShortcutsModal() {
    let modal = document.getElementById('shortcuts-modal');
    if (modal) {
        modal.classList.toggle('visible');
    } else {
        createShortcutsModal();
        document.getElementById('shortcuts-modal').classList.add('visible');
    }
}

function closeShortcutsModal() {
    const modal = document.getElementById('shortcuts-modal');
    if (modal) modal.classList.remove('visible');
}

function createShortcutsModal() {
    const modal = document.createElement('div');
    modal.id = 'shortcuts-modal';
    modal.className = 'shortcuts-modal';
    modal.innerHTML = `
        <div class="shortcuts-content">
            <div class="shortcuts-header">
                <h2>⌨️ Keyboard Shortcuts</h2>
                <button class="shortcuts-close" onclick="closeShortcutsModal()">×</button>
            </div>
            <div class="shortcuts-body">
                <div class="shortcuts-section">
                    <h3>Navigation</h3>
                    <div class="shortcut-row"><kbd>g</kbd> <kbd>b</kbd> <span>Go to Briefing</span></div>
                    <div class="shortcut-row"><kbd>g</kbd> <kbd>e</kbd> <span>Go to Email</span></div>
                    <div class="shortcut-row"><kbd>g</kbd> <kbd>q</kbd> <span>Go to Queue</span></div>
                    <div class="shortcut-row"><kbd>g</kbd> <kbd>s</kbd> <span>Go to Synapse</span></div>
                    <div class="shortcut-row"><kbd>g</kbd> <kbd>k</kbd> <span>Go to Kanban</span></div>
                </div>
                <div class="shortcuts-section">
                    <h3>Actions</h3>
                    <div class="shortcut-row"><kbd>p</kbd> <span>Start/Pause Pomodoro</span></div>
                    <div class="shortcut-row"><kbd>r</kbd> <span>Refresh data</span></div>
                    <div class="shortcut-row"><kbd>?</kbd> <span>Show this help</span></div>
                    <div class="shortcut-row"><kbd>Esc</kbd> <span>Close modal</span></div>
                </div>
                <div class="shortcuts-section">
                    <h3>Synapse</h3>
                    <div class="shortcut-row"><kbd>Cmd</kbd> <kbd>K</kbd> <span>Command palette</span></div>
                </div>
            </div>
        </div>
    `;
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeShortcutsModal();
    });
    document.body.appendChild(modal);
}

// Initialize keyboard shortcuts
document.addEventListener('keydown', handleKeyboardShortcut);

// Expose for global access
window.toggleShortcutsModal = toggleShortcutsModal;
window.closeShortcutsModal = closeShortcutsModal;

// =============================================================================
// BREATHING EXERCISE
// =============================================================================

const breathingPatterns = {
    box: { inhale: 4, hold1: 4, exhale: 4, hold2: 4, name: 'Box Breathing' },
    '478': { inhale: 4, hold1: 7, exhale: 8, hold2: 0, name: '4-7-8 Relaxing' },
    quick: { inhale: 4, hold1: 2, exhale: 4, hold2: 0, name: 'Quick Focus' }
};

let breathingState = {
    running: false,
    pattern: 'box',
    phase: 'ready',   // ready, inhale, hold1, exhale, hold2
    timer: null,
    cycleTimer: null,
    countdown: 0,
    cycles: 0
};

function openBreathingPopup() {
    const overlay = document.getElementById('breathing-popup-overlay');
    if (overlay) overlay.classList.add('active');
}

function closeBreathingPopup(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('breathing-popup-overlay');
    if (overlay) overlay.classList.remove('active');
}

function setBreathingPattern() {
    const select = document.getElementById('breathing-pattern');
    if (select) {
        breathingState.pattern = select.value;
    }
}

function toggleBreathing() {
    if (breathingState.running) {
        stopBreathing();
    } else {
        startBreathing();
    }
}

function startBreathing() {
    breathingState.running = true;
    breathingState.cycles = 0;
    
    const btn = document.getElementById('breathing-start');
    if (btn) {
        btn.textContent = 'Stop';
        btn.classList.add('stop');
        btn.classList.remove('primary');
    }
    
    runBreathingCycle();
}

function stopBreathing() {
    breathingState.running = false;
    breathingState.phase = 'ready';
    
    if (breathingState.timer) clearInterval(breathingState.timer);
    if (breathingState.cycleTimer) clearTimeout(breathingState.cycleTimer);
    
    const btn = document.getElementById('breathing-start');
    if (btn) {
        btn.textContent = 'Start';
        btn.classList.remove('stop');
        btn.classList.add('primary');
    }
    
    updateBreathingUI('Ready', '', 'ready');
}

function runBreathingCycle() {
    if (!breathingState.running) return;
    
    const pattern = breathingPatterns[breathingState.pattern];
    const phases = [
        { name: 'inhale', text: 'Breathe In', duration: pattern.inhale },
        { name: 'hold1', text: 'Hold', duration: pattern.hold1 },
        { name: 'exhale', text: 'Breathe Out', duration: pattern.exhale },
        { name: 'hold2', text: 'Hold', duration: pattern.hold2 }
    ].filter(p => p.duration > 0);
    
    let phaseIndex = 0;
    
    function nextPhase() {
        if (!breathingState.running) return;
        
        if (phaseIndex >= phases.length) {
            breathingState.cycles++;
            if (breathingState.cycles >= 4) {  // 4 cycles = ~1 minute
                completeBreathing();
                return;
            }
            phaseIndex = 0;
        }
        
        const phase = phases[phaseIndex];
        breathingState.phase = phase.name;
        breathingState.countdown = phase.duration;
        
        updateBreathingUI(phase.text, phase.duration, phase.name);
        
        // Countdown timer
        breathingState.timer = setInterval(() => {
            breathingState.countdown--;
            if (breathingState.countdown > 0) {
                document.getElementById('breathing-timer').textContent = breathingState.countdown;
            }
        }, 1000);
        
        // Schedule next phase
        breathingState.cycleTimer = setTimeout(() => {
            clearInterval(breathingState.timer);
            phaseIndex++;
            nextPhase();
        }, phase.duration * 1000);
    }
    
    nextPhase();
}

function updateBreathingUI(text, timer, phase) {
    const circle = document.getElementById('breathing-circle');
    const textEl = document.getElementById('breathing-text');
    const timerEl = document.getElementById('breathing-timer');
    
    if (circle) {
        circle.className = 'breathing-circle ' + phase;
    }
    if (textEl) {
        textEl.textContent = text;
    }
    if (timerEl) {
        timerEl.textContent = timer || '';
    }
}

function completeBreathing() {
    stopBreathing();
    updateBreathingUI('Done ✓', '', 'ready');
    
    // Log to accomplishments if available
    if (typeof addAccomplishment === 'function') {
        addAccomplishment('Completed a breathing reset 🌬️');
    }
}

// Expose for global access
window.toggleBreathing = toggleBreathing;
window.setBreathingPattern = setBreathingPattern;
window.openBreathingPopup = openBreathingPopup;
window.closeBreathingPopup = closeBreathingPopup;

// ===== EMAIL QUICK GLANCE WIDGET =====

async function loadEmailQuickview() {
    const contentEl = document.getElementById('email-glance-content');
    const badgeEl = document.getElementById('email-unsorted-count');
    
    if (!contentEl) return;
    
    try {
        const response = await fetch('/api/email/quickview');
        if (!response.ok) throw new Error('Failed to load email status');
        
        const data = await response.json();
        renderEmailQuickview(data, contentEl, badgeEl);
        
    } catch (error) {
        console.error('Email quickview error:', error);
        contentEl.innerHTML = '<div class="email-glance-loading">Unable to load email status</div>';
    }
}

function renderEmailQuickview(data, contentEl, badgeEl) {
    const { unsorted_count, priority_count, top_items } = data;
    
    // Update badge
    if (badgeEl) {
        badgeEl.textContent = unsorted_count;
        if (unsorted_count === 0) {
            badgeEl.classList.add('zero');
        } else {
            badgeEl.classList.remove('zero');
        }
    }
    
    // Handle inbox zero
    if (unsorted_count === 0) {
        contentEl.innerHTML = `
            <div class="email-glance-empty">
                <div class="icon">✨</div>
                <div>Inbox Zero! All emails sorted.</div>
            </div>
        `;
        return;
    }
    
    // Build summary and list
    let html = `
        <div class="email-glance-summary">
            <div class="email-glance-stat">
                <span class="count">${unsorted_count}</span> unsorted
            </div>
            ${priority_count > 0 ? `
                <div class="email-glance-stat priority">
                    <span class="count">${priority_count}</span> priority
                </div>
            ` : ''}
        </div>
    `;
    
    if (top_items && top_items.length > 0) {
        html += '<div class="email-glance-list">';
        for (const item of top_items) {
            const priorityClass = item.priority ? ' priority' : '';
            const subject = item.title.replace(/^📧\s*/, '');
            html += `
                <div class="email-glance-item${priorityClass}" onclick="window.location.href='/email'">
                    <span class="sender">${escapeHtml(item.sender)}</span>
                    <span class="subject">${escapeHtml(subject)}</span>
                </div>
            `;
        }
        html += '</div>';
    }
    
    contentEl.innerHTML = html;
}

// Refresh every 5 minutes
setInterval(loadEmailQuickview, 5 * 60 * 1000);

// Helper function if not already defined
if (typeof escapeHtml !== 'function') {
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
