/**
 * Mission Control - Email Dashboard JavaScript
 * Handles email dashboard functionality, processing, and UI interactions
 */

class EmailDashboard {
    constructor() {
        this.emails = {};
        this.filteredEmails = {};
        this.stats = {};
        this.lastSync = null;
        this.autoRefreshInterval = null;
        this.selectedIndex = -1;
        this.allEmailCards = [];
        this.activeSource = localStorage.getItem('mc_email_source') || 'novvi';

        this.init();
    }

    async init() {
        this.setupEventListeners();
        this.setupKeyboardShortcuts();
        this.setupAutoRefresh();
        this.initSourceToggle();
        this.initDraftModal();

        // Initial data load
        await this.loadDashboard();

        console.log('📧 Email Dashboard initialized');
    }

    // ── Source Toggle ────────────────────────────────────────────────
    initSourceToggle() {
        const btns = document.querySelectorAll('.source-btn');
        btns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.source === this.activeSource);
            btn.addEventListener('click', async () => {
                this.activeSource = btn.dataset.source;
                localStorage.setItem('mc_email_source', this.activeSource);
                btns.forEach(b => b.classList.toggle('active', b === btn));
                await this.loadDashboard();
            });
        });
    }

    applySourceFilter() {
        const showNovvi = this.activeSource === 'novvi' || this.activeSource === 'both';
        const showGmail = this.activeSource === 'gmail' || this.activeSource === 'both';

        // Show/hide O365 sections
        ['needs-response', 'action-items', 'meetings', 'fyi'].forEach(id => {
            const section = document.getElementById(`list-${id}`)?.closest('.email-section');
            if (section) section.classList.toggle('hidden', !showNovvi);
        });

        // Show/hide Gmail section
        const gmailSection = document.getElementById('gmail-section');
        if (gmailSection) gmailSection.classList.toggle('hidden', !showGmail);
    }

    async loadGmailEmails() {
        try {
            const data = await this.apiCall('/gmail/emails?days=7&limit=50');
            this.renderGmailSection(data.emails || []);
        } catch (e) {
            document.getElementById('list-gmail').innerHTML =
                '<div class="empty-state">Failed to load Gmail</div>';
        }
    }

    renderGmailSection(emails) {
        const list = document.getElementById('list-gmail');
        const count = document.getElementById('count-gmail');
        list.innerHTML = '';
        count.textContent = emails.length;

        if (!emails.length) {
            list.innerHTML = '<div class="empty-state">No Gmail messages</div>';
            return;
        }
        emails.forEach(email => list.appendChild(this.createGmailCard(email)));
    }

    // ── Draft Modal ──────────────────────────────────────────────────
    async draftResponse(emailId, webLink) {
        const modal    = document.getElementById('draft-modal');
        const spinner  = document.getElementById('draft-spinner');
        const textarea = document.getElementById('draft-body');
        const actions  = document.getElementById('draft-actions');
        const toLine   = document.getElementById('draft-to');
        const openBtn  = document.getElementById('draft-open');

        // Reset state
        spinner.classList.remove('hidden');
        textarea.classList.add('hidden');
        actions.classList.add('hidden');
        toLine.textContent = '';
        textarea.value = '';
        modal.classList.remove('hidden');

        try {
            const data = await this.apiCall(`/email/${emailId}/draft`, { method: 'POST' });
            spinner.classList.add('hidden');
            textarea.value = data.draft;
            toLine.textContent = `To: ${data.to_name ? data.to_name + ' ' : ''}<${data.to}>  ·  ${data.subject}`;
            textarea.classList.remove('hidden');
            actions.classList.remove('hidden');
            if (webLink) openBtn.href = webLink;
            else openBtn.style.display = 'none';
        } catch (e) {
            spinner.textContent = 'Failed to generate draft. Try again.';
        }
    }

    initDraftModal() {
        document.getElementById('draft-close').addEventListener('click', () => {
            document.getElementById('draft-modal').classList.add('hidden');
        });
        document.getElementById('draft-modal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget)
                e.currentTarget.classList.add('hidden');
        });
        document.getElementById('draft-copy').addEventListener('click', () => {
            const text = document.getElementById('draft-body').value;
            navigator.clipboard.writeText(text).then(() => this.showMessage('Copied to clipboard', 'success'));
        });
    }

    createGmailCard(email) {
        const card = document.createElement('div');
        card.className = 'email-card gmail-card';
        card.dataset.emailId = email.id;

        const from = email.from || {};
        const name = from.name || from.address || 'Unknown';
        const addr = from.address || '';
        const unread = !email.isRead;
        const time = email.received ? this.formatRelativeTime(email.received) : '';

        card.innerHTML = `
            <div class="email-header">
                <div class="email-sender">
                    ${unread ? '<span class="unread-dot"></span>' : ''}
                    <span class="sender-name">${name}</span>
                    <span class="source-badge gmail">GMAIL</span>
                </div>
                <div class="email-meta">
                    <span class="email-time">${time}</span>
                </div>
            </div>
            <h3 class="email-subject">${email.subject || '(no subject)'}</h3>
            <p class="email-snippet">${email.snippet || ''}</p>
            <div class="email-footer">
                <div class="email-actions">
                    <a class="action-btn outlook-btn" href="${email.webLink || '#'}" target="_blank">Open</a>
                </div>
            </div>`;

        return card;
    }

    setupEventListeners() {
        // Sync button
        document.getElementById('sync-btn').addEventListener('click', () => this.syncEmails());
        
        // Filtered section toggle
        document.getElementById('filtered-toggle').addEventListener('click', () => this.toggleFiltered());
        
        // Add delegation for email card actions
        document.addEventListener('click', (e) => {
            if (e.target.matches('.task-btn')) {
                const emailId = this.getEmailIdFromElement(e.target);
                this.createTaskFromEmail(emailId);
            } else if (e.target.matches('.archive-btn')) {
                const emailId = this.getEmailIdFromElement(e.target);
                this.archiveEmail(emailId);
            } else if (e.target.matches('.snooze-btn')) {
                const emailId = this.getEmailIdFromElement(e.target);
                this.snoozeEmail(emailId);
            } else if (e.target.matches('.spam-btn')) {
                const emailId = this.getEmailIdFromElement(e.target);
                this.markAsSpam(emailId);
            }
        });
    }

    setupAutoRefresh() {
        // Auto-refresh every 5 minutes
        this.autoRefreshInterval = setInterval(() => {
            this.loadDashboard(true); // Silent refresh
        }, 5 * 60 * 1000);
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ignore if typing in an input
            if (e.target.matches('input, textarea, select')) return;
            
            switch (e.key.toLowerCase()) {
                case 'j':
                    // Next email
                    e.preventDefault();
                    this.selectNextEmail();
                    break;
                    
                case 'k':
                    // Previous email
                    e.preventDefault();
                    this.selectPreviousEmail();
                    break;
                    
                case 'o':
                case 'enter':
                    // Open in Outlook
                    e.preventDefault();
                    this.openSelectedEmail();
                    break;
                    
                case 't':
                    // Create task from email
                    e.preventDefault();
                    this.taskFromSelectedEmail();
                    break;
                    
                case 'a':
                    // Archive
                    e.preventDefault();
                    this.archiveSelectedEmail();
                    break;
                    
                case 's':
                    // Snooze
                    e.preventDefault();
                    this.snoozeSelectedEmail();
                    break;
                    
                case 'x':
                    // Mark as spam
                    e.preventDefault();
                    this.spamSelectedEmail();
                    break;
                    
                case 'd':
                case 'delete':
                case 'backspace':
                    // Delete
                    e.preventDefault();
                    this.deleteSelectedEmail();
                    break;
                    
                case 'r':
                    // Refresh
                    e.preventDefault();
                    this.loadDashboard();
                    break;
                    
                case '?':
                    // Show help
                    e.preventDefault();
                    this.showKeyboardHelp();
                    break;
            }
        });
    }

    updateEmailCardsList() {
        // Collect all visible email cards in DOM order
        this.allEmailCards = Array.from(document.querySelectorAll('.email-card:not(.filtered)'));
    }

    selectEmail(index) {
        this.updateEmailCardsList();
        
        if (this.allEmailCards.length === 0) return;
        
        // Clamp index
        if (index < 0) index = 0;
        if (index >= this.allEmailCards.length) index = this.allEmailCards.length - 1;
        
        // Deselect previous
        if (this.selectedIndex >= 0 && this.selectedIndex < this.allEmailCards.length) {
            this.allEmailCards[this.selectedIndex].classList.remove('selected');
        }
        
        // Select new
        this.selectedIndex = index;
        const card = this.allEmailCards[index];
        card.classList.add('selected');
        
        // Scroll into view
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    selectNextEmail() {
        this.updateEmailCardsList();
        if (this.selectedIndex < 0) {
            this.selectEmail(0);
        } else {
            this.selectEmail(this.selectedIndex + 1);
        }
    }

    selectPreviousEmail() {
        this.updateEmailCardsList();
        if (this.selectedIndex < 0) {
            this.selectEmail(0);
        } else {
            this.selectEmail(this.selectedIndex - 1);
        }
    }

    getSelectedEmailId() {
        this.updateEmailCardsList();
        if (this.selectedIndex < 0 || this.selectedIndex >= this.allEmailCards.length) {
            return null;
        }
        return this.allEmailCards[this.selectedIndex].dataset.emailId;
    }

    openSelectedEmail() {
        this.updateEmailCardsList();
        if (this.selectedIndex < 0 || this.selectedIndex >= this.allEmailCards.length) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        const card = this.allEmailCards[this.selectedIndex];
        const link = card.querySelector('.outlook-btn');
        if (link && link.href) {
            window.open(link.href, '_blank');
        } else {
            this.showMessage('No link available for this email', 'info');
        }
    }

    taskFromSelectedEmail() {
        const emailId = this.getSelectedEmailId();
        if (!emailId) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        this.createTaskFromEmail(emailId);
    }

    archiveSelectedEmail() {
        const emailId = this.getSelectedEmailId();
        if (!emailId) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        this.archiveEmail(emailId);
        // Move to next email after archiving
        setTimeout(() => this.selectNextEmail(), 100);
    }

    snoozeSelectedEmail() {
        const emailId = this.getSelectedEmailId();
        if (!emailId) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        this.snoozeEmail(emailId);
        // Move to next email after snoozing
        setTimeout(() => this.selectNextEmail(), 100);
    }

    deleteSelectedEmail() {
        const emailId = this.getSelectedEmailId();
        if (!emailId) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        this.deleteEmail(emailId);
        // Move to next email after deleting
        setTimeout(() => this.selectNextEmail(), 100);
    }

    spamSelectedEmail() {
        const emailId = this.getSelectedEmailId();
        if (!emailId) {
            this.showMessage('No email selected. Use j/k to navigate.', 'info');
            return;
        }
        this.markAsSpam(emailId);
        // Move to next email after marking as spam
        setTimeout(() => this.selectNextEmail(), 100);
    }

    showKeyboardHelp() {
        const helpText = `
Keyboard Shortcuts:
━━━━━━━━━━━━━━━━━━
j / k     Navigate down/up
o / Enter Open in Outlook
t         Create task
a         Archive
s         Snooze (1 hour)
d / Del   Delete
r         Refresh
?         Show this help
        `.trim();
        
        alert(helpText);
    }

    getEmailIdFromElement(element) {
        const emailCard = element.closest('.email-card');
        return emailCard ? emailCard.dataset.emailId : null;
    }

    // API Methods
    async apiCall(endpoint, options = {}) {
        try {
            const response = await fetch(`/api${endpoint}`, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });
            
            if (!response.ok) {
                throw new Error(`API call failed: ${response.statusText}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            if (!options.silent) {
                this.showMessage(`Error: ${error.message}`, 'error');
            }
            throw error;
        }
    }

    async loadDashboard(silent = false) {
        try {
            if (!silent) this.showMessage('Loading dashboard...', 'info');

            const loadNovvi = this.activeSource === 'novvi' || this.activeSource === 'both';
            const loadGmail = this.activeSource === 'gmail' || this.activeSource === 'both';

            // Load O365 dashboard
            if (loadNovvi) {
                const dashboard = await this.apiCall('/email/dashboard');
                this.updateDashboard(dashboard);
                const filtered = await this.apiCall('/email/filtered');
                this.updateFilteredSection(filtered.filtered_emails);
            }

            // Load Gmail
            if (loadGmail) await this.loadGmailEmails();

            // Show/hide sections based on active source
            this.applySourceFilter();

            if (!silent) this.showMessage('Dashboard updated', 'success');

        } catch (error) {
            if (!silent) this.showMessage('Failed to load dashboard', 'error');
        }
    }

    async syncEmails() {
        try {
            this.showLoading(true);
            this.showMessage('Processing emails...', 'info');
            
            const result = await this.apiCall('/email/sync', { method: 'POST' });
            
            await this.loadDashboard(true); // Reload data silently
            
            const message = `Email sync complete: ${result.passed} passed, ${result.filtered} filtered`;
            this.showMessage(message, 'success');
            
        } catch (error) {
            this.showMessage('Email sync failed', 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async createTaskFromEmail(emailId) {
        if (!emailId) return;
        
        try {
            this.showMessage('Creating task...', 'info');
            
            const result = await this.apiCall(`/email/${emailId}/to-task`, {
                method: 'POST',
                body: JSON.stringify({})
            });
            
            this.showMessage('Task created successfully! 📋', 'success');
            
            // Mark email as converted
            const emailCard = document.querySelector(`[data-email-id="${emailId}"]`);
            if (emailCard) {
                emailCard.classList.add('converted-to-task');
                const taskBtn = emailCard.querySelector('.task-btn');
                if (taskBtn) {
                    taskBtn.textContent = '✅ Task Created';
                    taskBtn.disabled = true;
                }
            }
            
        } catch (error) {
            this.showMessage('Failed to create task', 'error');
        }
    }

    async archiveEmail(emailId) {
        if (!emailId) return;
        
        try {
            await this.apiCall(`/email/${emailId}/action`, {
                method: 'POST',
                body: JSON.stringify({ action: 'archive' })
            });
            
            // Remove from dashboard
            const emailCard = document.querySelector(`[data-email-id="${emailId}"]`);
            if (emailCard) {
                emailCard.style.opacity = '0.5';
                emailCard.style.pointerEvents = 'none';
                setTimeout(() => emailCard.remove(), 500);
            }
            
            this.showMessage('Email archived', 'success');
            this.updateStats();
            
        } catch (error) {
            this.showMessage('Failed to archive email', 'error');
        }
    }

    async snoozeEmail(emailId) {
        if (!emailId) return;
        
        try {
            await this.apiCall(`/email/${emailId}/action`, {
                method: 'POST',
                body: JSON.stringify({ action: 'snooze' })
            });
            
            // Remove from dashboard temporarily
            const emailCard = document.querySelector(`[data-email-id="${emailId}"]`);
            if (emailCard) {
                emailCard.style.opacity = '0.5';
                emailCard.style.pointerEvents = 'none';
                setTimeout(() => emailCard.remove(), 300);
            }
            
            this.showMessage('Email snoozed for 1 hour', 'success');
            
        } catch (error) {
            this.showMessage('Failed to snooze email', 'error');
        }
    }

    async deleteEmail(emailId) {
        if (!emailId) return;
        
        try {
            await this.apiCall(`/email/${emailId}/action`, {
                method: 'POST',
                body: JSON.stringify({ action: 'delete' })
            });
            
            // Remove from dashboard
            const emailCard = document.querySelector(`[data-email-id="${emailId}"]`);
            if (emailCard) {
                emailCard.style.opacity = '0.5';
                emailCard.style.transform = 'translateX(20px)';
                emailCard.style.transition = 'all 0.2s';
                setTimeout(() => emailCard.remove(), 200);
            }
            
            this.showMessage('Email deleted', 'success');
            this.updateStats();
            
        } catch (error) {
            this.showMessage('Failed to delete email', 'error');
        }
    }

    async markAsSpam(emailId) {
        if (!emailId) return;
        
        try {
            const result = await this.apiCall(`/email/${emailId}/spam`, {
                method: 'POST'
            });
            
            // Remove from dashboard
            const emailCard = document.querySelector(`[data-email-id="${emailId}"]`);
            if (emailCard) {
                emailCard.style.opacity = '0.5';
                emailCard.style.background = 'rgba(255, 92, 92, 0.1)';
                emailCard.style.transition = 'all 0.2s';
                setTimeout(() => emailCard.remove(), 200);
            }
            
            const blockedItem = result.blocked_domain || result.blocked_pattern || 'sender';
            this.showMessage(`Blocked: ${blockedItem}`, 'success');
            this.updateStats();
            
        } catch (error) {
            this.showMessage('Failed to mark as spam', 'error');
        }
    }

    // UI Rendering Methods
    updateDashboard(data) {
        this.emails = data;
        this.stats = data.stats || {};
        
        // Update stats
        this.updateStats();
        
        // Clear and update each section
        this.renderEmailSection('needs_response', data.needs_response || []);
        this.renderEmailSection('action_items', data.action_items || []);
        this.renderEmailSection('meeting_requests', data.meeting_requests || []);
        this.renderEmailSection('fyi', data.fyi || []);
        
        // Update last sync time
        if (data.stats && data.stats.last_sync) {
            const syncTime = new Date(data.stats.last_sync);
            document.getElementById('last-sync').textContent = `Last sync: ${syncTime.toLocaleTimeString()}`;
        }
    }

    updateStats() {
        const stats = this.stats;
        
        document.getElementById('stat-needs-response').textContent = this.emails.needs_response?.length || 0;
        document.getElementById('stat-action-items').textContent = this.emails.action_items?.length || 0;
        document.getElementById('stat-meetings').textContent = this.emails.meeting_requests?.length || 0;
        document.getElementById('stat-fyi').textContent = this.emails.fyi?.length || 0;
        document.getElementById('stat-filtered').textContent = stats.total_filtered || 0;
        
        // Update section counts
        document.getElementById('count-needs-response').textContent = this.emails.needs_response?.length || 0;
        document.getElementById('count-action-items').textContent = this.emails.action_items?.length || 0;
        document.getElementById('count-meetings').textContent = this.emails.meeting_requests?.length || 0;
        document.getElementById('count-fyi').textContent = this.emails.fyi?.length || 0;
        document.getElementById('count-filtered').textContent = Object.keys(this.filteredEmails).length;
    }

    renderEmailSection(sectionName, emails) {
        const listElement = document.getElementById(`list-${sectionName.replace('_', '-')}`);
        if (!listElement) return;
        
        listElement.innerHTML = '';
        
        if (emails.length === 0) {
            listElement.innerHTML = '<div class="empty-state">No emails in this category</div>';
            return;
        }
        
        emails.forEach(email => {
            const emailCard = this.createEmailCard(email);
            listElement.appendChild(emailCard);
        });
    }

    createEmailCard(email) {
        const template = document.getElementById('email-card-template');
        const cardElement = template.content.cloneNode(true);
        const card = cardElement.querySelector('.email-card');
        
        // Set email ID for event handling
        card.dataset.emailId = email.id;
        
        // Sender information
        const senderName = cardElement.querySelector('.sender-name');
        const contactBadge = cardElement.querySelector('.contact-tier-badge');
        
        if (email.from && typeof email.from === 'object') {
            senderName.textContent = email.from.name || email.from.address || 'Unknown';
        } else {
            senderName.textContent = email.from || 'Unknown';
        }
        
        // Contact tier badge
        contactBadge.textContent = this.getContactTierBadge(email.contact_tier);
        contactBadge.className = `contact-tier-badge ${email.contact_tier}`;
        
        // Urgency indicator
        const urgencyIndicator = cardElement.querySelector('.urgency-indicator');
        urgencyIndicator.textContent = this.getUrgencyIndicator(email.urgency);
        urgencyIndicator.className = `urgency-indicator ${email.urgency}`;
        
        // Time
        const emailTime = cardElement.querySelector('.email-time');
        if (email.received) {
            emailTime.textContent = this.formatRelativeTime(email.received);
        }
        
        // Subject and summary
        cardElement.querySelector('.email-subject').textContent = email.subject || 'No subject';
        cardElement.querySelector('.email-summary').textContent = email.summary || 'No summary available';
        
        // Action needed
        if (email.action_needed || email.deadline) {
            const actionDiv = cardElement.querySelector('.email-action');
            actionDiv.style.display = 'block';
            
            if (email.action_needed) {
                cardElement.querySelector('.action-text').textContent = email.action_needed;
            }
            
            if (email.deadline) {
                const deadlineText = cardElement.querySelector('.deadline-text');
                deadlineText.textContent = `⏰ ${email.deadline}`;
                deadlineText.style.display = 'inline';
            }
        }
        
        // Draft button
        const draftBtn = cardElement.querySelector('.draft-btn');
        if (draftBtn) {
            draftBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.draftResponse(email.id, email.webLink);
            });
        }

        // Set up action buttons
        const outlookBtn = cardElement.querySelector('.outlook-btn');
        if (email.webLink) {
            outlookBtn.href = email.webLink;
        } else {
            outlookBtn.style.display = 'none';
        }
        
        return cardElement;
    }

    updateFilteredSection(filteredEmails) {
        this.filteredEmails = filteredEmails;
        document.getElementById('count-filtered').textContent = filteredEmails.length;
        
        const listElement = document.getElementById('list-filtered');
        listElement.innerHTML = '';
        
        if (filteredEmails.length === 0) {
            listElement.innerHTML = '<div class="empty-state">No filtered emails</div>';
            return;
        }
        
        filteredEmails.forEach(email => {
            const emailCard = this.createFilteredEmailCard(email);
            listElement.appendChild(emailCard);
        });
    }

    createFilteredEmailCard(email) {
        const template = document.getElementById('filtered-email-template');
        const cardElement = template.content.cloneNode(true);
        
        // Sender information
        const senderName = cardElement.querySelector('.sender-name');
        if (email.from && typeof email.from === 'object') {
            senderName.textContent = `${email.from.name || ''} <${email.from.address || ''}>`;
        } else {
            senderName.textContent = email.from || 'Unknown';
        }
        
        // Time
        const emailTime = cardElement.querySelector('.email-time');
        if (email.received) {
            emailTime.textContent = this.formatRelativeTime(email.received);
        }
        
        // Subject
        cardElement.querySelector('.email-subject').textContent = email.subject || 'No subject';
        
        // Filter reason
        cardElement.querySelector('.filter-text').textContent = email.filter_reason || 'Unknown reason';
        
        return cardElement;
    }

    // Utility Methods
    getContactTierBadge(tier) {
        const badges = {
            'internal': '[NOVVI]',
            'tier1': '[⭐⭐⭐ Top 20]',
            'tier2': '[⭐⭐ Top 100]',
            'partner': '[Partner]',
            'unknown': ''
        };
        return badges[tier] || '';
    }

    getUrgencyIndicator(urgency) {
        const indicators = {
            'high': '🔴',
            'medium': '🟡',
            'low': '🟢'
        };
        return indicators[urgency] || '⚪';
    }

    formatRelativeTime(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / (1000 * 60));
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        
        return date.toLocaleDateString();
    }

    toggleFiltered() {
        const listElement = document.getElementById('list-filtered');
        listElement.classList.toggle('hidden');
        
        if (!listElement.classList.contains('hidden') && Object.keys(this.filteredEmails).length === 0) {
            // Load filtered emails if not already loaded
            this.loadFilteredEmails();
        }
    }

    async loadFilteredEmails() {
        try {
            const result = await this.apiCall('/email/filtered');
            this.updateFilteredSection(result.filtered_emails);
        } catch (error) {
            console.error('Failed to load filtered emails:', error);
        }
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (show) {
            overlay.classList.remove('hidden');
        } else {
            overlay.classList.add('hidden');
        }
    }

    showMessage(text, type = 'info') {
        const message = document.createElement('div');
        message.className = `toast-message ${type}`;
        message.textContent = text;
        document.body.appendChild(message);
        
        setTimeout(() => {
            message.remove();
        }, 3000);
    }
}

// Initialize the email dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.emailDashboard = new EmailDashboard();
});