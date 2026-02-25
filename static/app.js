/**
 * Mission Control - Kanban Dashboard JavaScript
 * Handles all interactive functionality including drag & drop, API calls, focus mode, etc.
 */

class MissionControl {
    constructor() {
        this.tasks = [];
        this.focusSession = null;
        this.focusTimer = null;
        this.lastSync = null;
        this.draggedTask = null;
        this.collapsedColumns = new Set();
        this.draggedColumn = null;
        
        // Default columns with colors
        this.defaultColumns = [
            { id: 'unsorted', name: 'Unsorted', color: '#f0b429' },
            { id: 'todo', name: 'To Do', color: '#4ea1ff' },
            { id: 'inprogress', name: 'In Progress', color: '#f97316' },
            { id: 'tickler', name: 'Tickler', color: '#a855f7' },
            { id: 'longterm', name: 'Long-term', color: '#06b6d4' },
            { id: 'done', name: 'Done', color: '#35d07f' },
            { id: 'archive', name: 'Archive', color: 'rgba(255,255,255,0.35)' }
        ];
        this.columns = [];
        
        this.init();
    }

    async init() {
        this.loadColumnConfig();
        this.renderColumns();
        this.loadCollapseState();
        this.setupEventListeners();
        this.setupKeyboardShortcuts();
        this.setupDragAndDrop();
        this.setupColumnDragAndDrop();
        
        // Initial data load
        await this.syncData();
        await this.loadTasks();
        await this.loadMorningBrief();
        await this.loadTimeline();
        
        // Apply collapse state after tasks are loaded
        this.applyCollapseState();
        
        // Check for active focus session
        await this.checkFocusStatus();
        
        // Auto-sync every 5 minutes
        setInterval(() => this.syncData(), 5 * 60 * 1000);
        
        console.log('🚀 Mission Control initialized');
    }

    setupEventListeners() {
        // Sync button
        document.getElementById('sync-btn').addEventListener('click', () => this.syncData());
        
        // Reset columns button
        document.getElementById('reset-columns-btn').addEventListener('click', () => this.resetColumns());
        
        // Focus mode button
        document.getElementById('focus-mode-btn').addEventListener('click', () => this.toggleFocusMode());
        
        // Stop focus button
        document.getElementById('stop-focus-btn').addEventListener('click', () => this.stopFocus());
        
        // Archive toggle (optional - may not exist in new layout)
        document.getElementById('archive-toggle')?.addEventListener('click', () => this.toggleArchive());
        
        // Quick add modal
        document.getElementById('quick-add-submit').addEventListener('click', () => this.submitQuickAdd());
        document.getElementById('quick-add-cancel').addEventListener('click', () => this.hideQuickAdd());
        
        // Quick add input - submit on Enter
        document.getElementById('quick-add-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.submitQuickAdd();
            } else if (e.key === 'Escape') {
                this.hideQuickAdd();
            }
        });

        // Setup column-specific listeners (buttons inside columns)
        this.setupEventListenersForColumns();

        // Expand collapsed columns (click on collapsed stack item)
        document.getElementById('collapsed-stack').addEventListener('click', (e) => {
            const collapsedCol = e.target.closest('.collapsed-column');
            if (collapsedCol) {
                this.expandColumn(collapsedCol.dataset.column);
            }
        });

        // Edit modal
        document.getElementById('edit-card-save')?.addEventListener('click', () => this.saveEditCard());
        document.getElementById('edit-card-cancel')?.addEventListener('click', () => this.hideEditModal());
        document.getElementById('edit-card-delete')?.addEventListener('click', () => this.deleteTaskFromModal());
        
        // Edit modal keyboard shortcuts
        document.getElementById('edit-card-modal')?.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideEditModal();
            } else if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                this.saveEditCard();
            }
        });

        // Notes modal
        document.getElementById('notes-save')?.addEventListener('click', () => this.saveNotes());
        document.getElementById('notes-close')?.addEventListener('click', () => this.hideNotesModal());
        
        // Notes tab switching
        document.querySelectorAll('.notes-tab').forEach(tab => {
            tab.addEventListener('click', (e) => this.switchNotesTab(e.target.dataset.tab));
        });

        // Close menus when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.task-menu-container')) {
                document.querySelectorAll('.task-menu').forEach(menu => menu.classList.add('hidden'));
            }
        });
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Cmd+K or Ctrl+K for quick add
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                this.showQuickAdd();
            }
            
            // Escape to close modals
            if (e.key === 'Escape') {
                this.hideQuickAdd();
                if (this.focusSession) {
                    this.stopFocus();
                }
            }
            
            // F key for focus mode
            if (e.key === 'f' && !e.target.matches('input, textarea')) {
                e.preventDefault();
                this.toggleFocusMode();
            }
        });
    }

    setupDragAndDrop() {
        // Add event listeners to droppable areas
        document.querySelectorAll('[data-droppable]').forEach(zone => {
            zone.addEventListener('dragover', this.handleDragOver.bind(this));
            zone.addEventListener('drop', this.handleDrop.bind(this));
            zone.addEventListener('dragleave', this.handleDragLeave.bind(this));
        });
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
            this.showMessage(`Error: ${error.message}`, 'error');
            throw error;
        }
    }

    async syncData() {
        try {
            this.showMessage('Syncing data...', 'info');
            
            // Sync email and calendar in parallel
            const [emailResult, calendarResult] = await Promise.all([
                this.apiCall('/sync/email'),
                this.apiCall('/sync/calendar')
            ]);
            
            this.lastSync = new Date();
            this.updateLastSyncDisplay();
            
            if (emailResult.new_tasks > 0) {
                this.showMessage(`Added ${emailResult.new_tasks} new tasks from email`, 'success');
                await this.loadTasks(); // Reload tasks to show new ones
            }
            
            await this.loadTimeline(); // Update timeline with new calendar data
            
        } catch (error) {
            this.showMessage('Sync failed', 'error');
        }
    }

    async loadTasks() {
        try {
            const result = await this.apiCall('/tasks');
            this.tasks = result.tasks || [];
            this.renderTasks();
            this.updateTaskCounts();
        } catch (error) {
            console.error('Failed to load tasks:', error);
        }
    }

    async loadMorningBrief() {
        try {
            const brief = await this.apiCall('/brief');
            this.renderMorningBrief(brief);
        } catch (error) {
            console.error('Failed to load morning brief:', error);
        }
    }

    async loadTimeline() {
        try {
            const result = await this.apiCall('/sync/calendar');
            this.renderTimeline(result.events || []);
        } catch (error) {
            console.error('Failed to load timeline:', error);
        }
    }

    async checkFocusStatus() {
        try {
            const result = await this.apiCall('/focus/status');
            if (result.session) {
                this.focusSession = result.session;
                this.showFocusMode();
                this.updateFocusTimer(result.session.elapsed_seconds);
            }
        } catch (error) {
            console.error('Failed to check focus status:', error);
        }
    }

    // Rendering Methods
    renderTasks() {
        console.log('[renderTasks] Starting, tasks:', this.tasks.length);
        
        // Clear all columns
        document.querySelectorAll('.kanban-content').forEach(column => {
            column.innerHTML = '';
        });

        // Group tasks by column
        const tasksByColumn = this.groupTasksByColumn();
        console.log('[renderTasks] Grouped:', Object.entries(tasksByColumn).map(([k,v]) => `${k}:${v.length}`).join(', '));

        // Render tasks in each column
        Object.entries(tasksByColumn).forEach(([column, tasks]) => {
            const columnElement = document.querySelector(`[data-droppable="${column}"]`);
            if (columnElement) {
                tasks.forEach(task => {
                    try {
                        const taskElement = this.createTaskElement(task);
                        if (taskElement) {
                            columnElement.appendChild(taskElement);
                        } else {
                            console.error('[renderTasks] createTaskElement returned null for:', task.id);
                        }
                    } catch (e) {
                        console.error('[renderTasks] Error creating task element:', task.id, e);
                    }
                });
            } else {
                console.warn('[renderTasks] No column element for:', column);
            }
        });
        
        console.log('[renderTasks] Done');
    }

    groupTasksByColumn() {
        const grouped = {};
        
        // Initialize all columns
        this.columns.forEach(col => {
            grouped[col.id] = [];
        });

        this.tasks.forEach(task => {
            if (grouped[task.column]) {
                grouped[task.column].push(task);
            } else if (grouped['unsorted']) {
                // Unknown column, put in unsorted
                grouped['unsorted'].push(task);
            } else if (this.columns.length > 0) {
                // Fallback to first column
                grouped[this.columns[0].id].push(task);
            }
        });

        // Sort each column by position
        Object.keys(grouped).forEach(col => {
            grouped[col].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
        });

        return grouped;
    }

    createTaskElement(task) {
        const template = document.getElementById('task-card-template');
        if (!template) {
            console.error('[createTaskElement] Template not found!');
            return null;
        }
        const taskElement = template.content.cloneNode(true);
        const card = taskElement.querySelector('.task-card');
        if (!card) {
            console.error('[createTaskElement] Card not found in template!');
            return null;
        }

        // Set task data
        card.dataset.taskId = task.id;
        card.querySelector('.task-title').textContent = task.title;
        card.querySelector('.task-description').textContent = task.description;
        
        // Energy level
        const energyElement = card.querySelector('.task-energy');
        if (task.energy) {
            energyElement.className = `task-energy ${task.energy}`;
        }

        // Source indicator
        const sourceElement = card.querySelector('.task-source');
        if (task.source_type === 'email') {
            sourceElement.textContent = '📧';
        } else if (task.source_type === 'calendar') {
            sourceElement.textContent = '📅';
        } else {
            sourceElement.textContent = '📝';
        }

        // Source link
        const linkElement = card.querySelector('.task-link');
        if (task.source_url) {
            linkElement.href = task.source_url;
            linkElement.style.display = 'inline';
        } else {
            linkElement.style.display = 'none';
        }

        // Health indicator (how long stuck)
        const healthElement = card.querySelector('.task-health');
        if (healthElement) {
            const stuckDays = this.calculateStuckDays(task);
            if (stuckDays < 2) {
                healthElement.className = 'task-health healthy';
            } else if (stuckDays < 4) {
                healthElement.className = 'task-health warning';
            } else {
                healthElement.className = 'task-health stuck';
            }
        }

        // Event listeners

        // Menu toggle
        const menuBtn = card.querySelector('.task-menu-btn');
        const menu = card.querySelector('.task-menu');
        menuBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            // Close all other menus first
            document.querySelectorAll('.task-menu').forEach(m => {
                if (m !== menu) m.classList.add('hidden');
            });
            menu.classList.toggle('hidden');
        });

        // Complete action (from menu)
        card.querySelector('.task-complete')?.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.add('hidden');
            this.completeTask(task.id);
        });

        // Quick complete button
        card.querySelector('.task-complete-quick')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.completeTask(task.id);
        });

        // Archive action
        card.querySelector('.task-archive')?.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.add('hidden');
            this.archiveTask(task.id);
        });

        // Edit action
        card.querySelector('.task-edit')?.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.add('hidden');
            this.showEditModal(task);
        });

        // Notes button (always visible, highlighted if has notes)
        const notesBtn = card.querySelector('.task-notes-btn');
        if (notesBtn) {
            notesBtn.classList.remove('hidden');
            if (task.notes && task.notes.trim()) {
                notesBtn.classList.add('has-notes');
            }
            notesBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showNotesModal(task);
            });
        }

        // Delete action (from menu - removed, keeping for compatibility)
        card.querySelector('.task-delete')?.addEventListener('click', (e) => {
            e.stopPropagation();
            menu?.classList.add('hidden');
            this.deleteTask(task.id);
        });

        // Quick delete button (always visible X)
        card.querySelector('.task-delete-quick')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.deleteTask(task.id);
        });

        // Snooze button
        card.querySelector('.task-snooze-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showSnoozeModal(task);
        });

        // Edit button
        card.querySelector('.task-edit-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showEditModal(task);
        });

        // Click title to edit
        card.querySelector('.task-title')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showEditModal(task);
        });

        // Focus button
        card.querySelector('.task-focus-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.startFocus(task);
        });

        // Drag events
        card.addEventListener('dragstart', (e) => {
            this.draggedTask = task;
            card.classList.add('dragging');
        });

        card.addEventListener('dragend', (e) => {
            card.classList.remove('dragging');
        });

        return card;
    }

    calculateStuckDays(task) {
        if (!task.stuck_since) return 0;
        const stuckDate = new Date(task.stuck_since);
        const now = new Date();
        const diffTime = Math.abs(now - stuckDate);
        return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    }

    renderMorningBrief(brief) {
        const briefContent = document.getElementById('brief-content');
        const totalTasks = Object.values(brief.task_counts).reduce((a, b) => a + b, 0);
        briefContent.innerHTML = `
            <div class="brief-stats">
                <div class="brief-stat">
                    <span class="brief-stat-label">Meetings</span>
                    <span class="brief-stat-value">${brief.meeting_count}</span>
                </div>
                <div class="brief-stat">
                    <span class="brief-stat-label">Tasks</span>
                    <span class="brief-stat-value">${totalTasks}</span>
                </div>
                <div class="brief-stat">
                    <span class="brief-stat-label">In Progress</span>
                    <span class="brief-stat-value">${brief.task_counts.inprogress || 0}</span>
                </div>
                <div class="brief-stat">
                    <span class="brief-stat-label">Done</span>
                    <span class="brief-stat-value">${brief.task_counts.done || 0}</span>
                </div>
            </div>
            <div class="text-secondary">${brief.summary}</div>
        `;
    }

    renderTimeline(events) {
        const timelineBar = document.getElementById('timeline-bar');
        timelineBar.innerHTML = '';

        // Add hour markers (6 AM to 10 PM)
        for (let hour = 6; hour <= 22; hour++) {
            const marker = document.createElement('div');
            marker.className = 'timeline-hour-marker';
            marker.style.left = `${((hour - 6) / 16) * 100}%`;
            marker.textContent = hour > 12 ? `${hour - 12}p` : `${hour}a`;
            timelineBar.appendChild(marker);
        }

        // Add "Now" indicator
        const now = new Date();
        const nowHour = now.getHours() + now.getMinutes() / 60;
        if (nowHour >= 6 && nowHour <= 22) {
            const nowLine = document.createElement('div');
            nowLine.className = 'timeline-now';
            nowLine.style.left = `${((nowHour - 6) / 16) * 100}%`;
            nowLine.title = `Now: ${now.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
            timelineBar.appendChild(nowLine);
        }

        // Add events
        const today = new Date();
        const todayEvents = events.filter(event => {
            let startStr = event.start;
            if (!startStr.endsWith('Z') && !startStr.includes('+') && !startStr.includes('-', 10)) {
                startStr += 'Z';
            }
            const eventDate = new Date(startStr);
            return eventDate.toDateString() === today.toDateString();
        });

        todayEvents.forEach(event => {
            // API returns times without timezone - treat as UTC
            let startStr = event.start;
            let endStr = event.end;
            if (!startStr.endsWith('Z') && !startStr.includes('+') && !startStr.includes('-', 10)) {
                startStr += 'Z';
            }
            if (!endStr.endsWith('Z') && !endStr.includes('+') && !endStr.includes('-', 10)) {
                endStr += 'Z';
            }
            const startTime = new Date(startStr);
            const endTime = new Date(endStr);
            
            const startHour = startTime.getHours() + startTime.getMinutes() / 60;
            const endHour = endTime.getHours() + endTime.getMinutes() / 60;
            
            if (startHour >= 6 && startHour <= 22) {
                const eventElement = document.createElement('div');
                eventElement.className = 'timeline-event meeting';
                eventElement.style.left = `${((startHour - 6) / 16) * 100}%`;
                eventElement.style.width = `${((endHour - startHour) / 16) * 100}%`;
                eventElement.textContent = event.title;
                eventElement.title = `${event.title}\n${startTime.toLocaleTimeString()} - ${endTime.toLocaleTimeString()}`;
                timelineBar.appendChild(eventElement);
            }
        });
    }

    updateTaskCounts() {
        const counts = this.tasks.reduce((acc, task) => {
            acc[task.column] = (acc[task.column] || 0) + 1;
            return acc;
        }, {});

        // Update column counts (both expanded and collapsed)
        this.columns.forEach(col => {
            const count = counts[col.id] || 0;
            // Expanded column count
            const columnElement = document.querySelector(`.kanban-column[data-column="${col.id}"] .kanban-count`);
            if (columnElement) {
                columnElement.textContent = count;
            }
        });

        // Update collapsed stack counts
        this.updateCollapsedStack();

        // Update total count
        document.getElementById('task-count').textContent = `${this.tasks.length} tasks`;
    }

    updateLastSyncDisplay() {
        const lastSyncElement = document.getElementById('last-sync');
        if (this.lastSync) {
            lastSyncElement.textContent = `Last sync: ${this.lastSync.toLocaleTimeString()}`;
        }
    }

    // Task Management
    async createTask(title) {
        try {
            const newTask = await this.apiCall('/tasks', {
                method: 'POST',
                body: JSON.stringify({ title })
            });
            
            this.tasks.push(newTask);
            this.renderTasks();
            this.updateTaskCounts();
            this.showMessage('Task created', 'success');
            
            return newTask;
        } catch (error) {
            this.showMessage('Failed to create task', 'error');
        }
    }

    async updateTask(taskId, updates) {
        try {
            const updatedTask = await this.apiCall(`/tasks/${taskId}`, {
                method: 'PUT',
                body: JSON.stringify(updates)
            });
            
            // Update local task
            const index = this.tasks.findIndex(t => t.id === taskId);
            if (index !== -1) {
                this.tasks[index] = updatedTask;
                this.renderTasks();
                this.updateTaskCounts();
            }
            
            return updatedTask;
        } catch (error) {
            this.showMessage('Failed to update task', 'error');
        }
    }

    async deleteTask(taskId) {
        // No confirmation - just delete (speed over safety for cleanup)
        try {
            await this.apiCall(`/tasks/${taskId}`, { method: 'DELETE' });
            
            this.tasks = this.tasks.filter(t => t.id !== taskId);
            this.renderTasks();
            this.updateTaskCounts();
            this.showMessage('Deleted', 'success');
        } catch (error) {
            this.showMessage('Failed to delete task', 'error');
        }
    }

    async completeTask(taskId) {
        await this.updateTask(taskId, { column: 'done' });
        this.showMessage('Task completed! 🎉', 'success');
    }

    async archiveTask(taskId) {
        await this.updateTask(taskId, { column: 'archive' });
        this.showMessage('Task archived', 'success');
    }

    async clearColumn(column) {
        const tasksInColumn = this.tasks.filter(t => t.column === column);
        if (tasksInColumn.length === 0) {
            this.showMessage('Column is empty', 'info');
            return;
        }
        
        try {
            const result = await this.apiCall(`/tasks/column/${column}`, { method: 'DELETE' });
            await this.loadTasks();
            this.showMessage(`Cleared ${result.deleted} tasks`, 'success');
        } catch (e) {
            this.showMessage('Failed to clear column', 'error');
        }
    }

    // Inline Add Card
    showInlineAddCard(column) {
        // Remove any existing add card forms
        document.querySelectorAll('.add-card-form').forEach(f => f.remove());

        const template = document.getElementById('add-card-template');
        const fragment = template.content.cloneNode(true);
        const formEl = fragment.querySelector('.add-card-form');

        // Insert at top of column content
        const columnContent = document.querySelector(`[data-droppable="${column}"]`);
        columnContent.insertBefore(formEl, columnContent.firstChild);

        // Now query from the inserted DOM element (not the fragment)
        const insertedForm = columnContent.querySelector('.add-card-form');
        const input = insertedForm.querySelector('.add-card-input');
        const submitBtn = insertedForm.querySelector('.add-card-submit');
        const cancelBtn = insertedForm.querySelector('.add-card-cancel');

        // Focus input
        input.focus();

        // Handle submit
        submitBtn?.addEventListener('click', async () => {
            const title = input.value.trim();
            if (title) {
                await this.createTaskInColumn(title, column);
                insertedForm.remove();
            }
        });

        // Handle cancel
        cancelBtn?.addEventListener('click', () => {
            insertedForm.remove();
        });

        // Handle Enter/Escape
        input.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                const title = input.value.trim();
                if (title) {
                    await this.createTaskInColumn(title, column);
                    insertedForm.remove();
                }
            } else if (e.key === 'Escape') {
                insertedForm.remove();
            }
        });
    }

    async createTaskInColumn(title, column) {
        try {
            const newTask = await this.apiCall('/tasks', {
                method: 'POST',
                body: JSON.stringify({ title, column })
            });
            
            this.tasks.push(newTask);
            this.renderTasks();
            this.updateTaskCounts();
            this.showMessage('Task created', 'success');
            
            return newTask;
        } catch (error) {
            this.showMessage('Failed to create task', 'error');
        }
    }

    // Edit Modal
    showEditModal(task) {
        const modal = document.getElementById('edit-card-modal');
        document.getElementById('edit-task-id').value = task.id;
        document.getElementById('edit-task-title').value = task.title || '';
        document.getElementById('edit-task-description').value = task.description || '';
        document.getElementById('edit-task-energy').value = task.energy || 'low_stakes';
        document.getElementById('edit-task-notes').value = task.notes || '';
        
        // Populate column dropdown
        const columnSelect = document.getElementById('edit-task-column');
        columnSelect.innerHTML = '';
        this.columns.forEach(col => {
            const option = document.createElement('option');
            option.value = col.id;
            option.textContent = col.name;
            if (col.id === task.column) option.selected = true;
            columnSelect.appendChild(option);
        });
        
        modal.classList.remove('hidden');

        // Focus title input
        document.getElementById('edit-task-title').focus();
    }

    hideEditModal() {
        document.getElementById('edit-card-modal').classList.add('hidden');
    }

    async saveEditCard() {
        const taskId = document.getElementById('edit-task-id').value;
        const title = document.getElementById('edit-task-title').value.trim();
        const description = document.getElementById('edit-task-description').value.trim();
        const energy = document.getElementById('edit-task-energy').value;
        const notes = document.getElementById('edit-task-notes').value;
        const column = document.getElementById('edit-task-column').value;

        if (!title) {
            this.showMessage('Title is required', 'error');
            return;
        }

        await this.updateTask(taskId, { title, description, energy, notes, column });
        this.hideEditModal();
        this.showMessage('Task updated', 'success');
    }
    
    async deleteTaskFromModal() {
        const taskId = document.getElementById('edit-task-id').value;
        this.hideEditModal();
        await this.deleteTask(taskId);
    }

    // Snooze Modal
    showSnoozeModal(task) {
        this._snoozeTaskId = task.id;
        const modal = document.getElementById('snooze-modal');
        document.getElementById('snooze-task-title').textContent = `Snoozing: ${task.title}`;
        modal.classList.remove('hidden');
    }

    closeSnoozeModal() {
        document.getElementById('snooze-modal').classList.add('hidden');
        this._snoozeTaskId = null;
    }

    async snoozeTask(amount, unit) {
        const taskId = this._snoozeTaskId;
        if (!taskId) return;

        const now = new Date();
        let wakeAt;
        if (unit === 'hours') {
            wakeAt = new Date(now.getTime() + amount * 60 * 60 * 1000);
        } else if (unit === 'days') {
            wakeAt = new Date(now.getTime() + amount * 24 * 60 * 60 * 1000);
        }

        // Move to snoozed column and set wake_at
        await this.updateTask(taskId, { 
            column: 'snoozed', 
            snoozed_until: wakeAt.toISOString() 
        });

        this.closeSnoozeModal();
        this.showMessage(`Task snoozed until ${wakeAt.toLocaleString()}`, 'success');
    }

    // Notes Modal
    showNotesModal(task) {
        const modal = document.getElementById('notes-modal');
        const titleEl = document.getElementById('notes-modal-title');
        const preview = document.getElementById('notes-preview');
        const editor = document.getElementById('notes-editor');
        
        document.getElementById('notes-task-id').value = task.id;
        titleEl.textContent = task.title;
        
        // Set content
        const notes = task.notes || '';
        editor.value = notes;
        
        // Render markdown preview
        if (notes.trim()) {
            preview.innerHTML = marked.parse(notes);
            preview.classList.remove('empty');
        } else {
            preview.innerHTML = '<span>No notes yet. Click Edit to add notes.</span>';
            preview.classList.add('empty');
        }
        
        // Start in preview mode
        this.switchNotesTab('preview');
        
        modal.classList.remove('hidden');
    }

    hideNotesModal() {
        document.getElementById('notes-modal').classList.add('hidden');
    }

    switchNotesTab(tab) {
        const preview = document.getElementById('notes-preview');
        const editor = document.getElementById('notes-editor');
        const tabs = document.querySelectorAll('.notes-tab');
        
        tabs.forEach(t => t.classList.remove('active'));
        document.querySelector(`.notes-tab[data-tab="${tab}"]`)?.classList.add('active');
        
        if (tab === 'edit') {
            preview.classList.add('hidden');
            editor.classList.remove('hidden');
            editor.focus();
        } else {
            editor.classList.add('hidden');
            preview.classList.remove('hidden');
            
            // Update preview with current editor content
            const notes = editor.value || '';
            if (notes.trim()) {
                preview.innerHTML = marked.parse(notes);
                preview.classList.remove('empty');
            } else {
                preview.innerHTML = '<span>No notes yet. Click Edit to add notes.</span>';
                preview.classList.add('empty');
            }
        }
    }

    async saveNotes() {
        const taskId = document.getElementById('notes-task-id').value;
        const notes = document.getElementById('notes-editor').value;
        
        await this.updateTask(taskId, { notes });
        this.hideNotesModal();
        this.showMessage('Notes saved', 'success');
    }

    // Drag and Drop
    handleDragOver(e) {
        e.preventDefault();
        const dropZone = e.currentTarget;
        dropZone.classList.add('drag-over');
        
        // Calculate drop position based on mouse position
        if (this.draggedTask) {
            const cards = Array.from(dropZone.querySelectorAll('.task-card:not(.dragging)'));
            const afterElement = this.getDragAfterElement(dropZone, e.clientY);
            const draggingCard = document.querySelector('.task-card.dragging');
            
            if (draggingCard) {
                if (afterElement) {
                    dropZone.insertBefore(draggingCard, afterElement);
                } else {
                    dropZone.appendChild(draggingCard);
                }
            }
        }
    }

    getDragAfterElement(container, y) {
        const draggableElements = [...container.querySelectorAll('.task-card:not(.dragging)')];
        
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

    handleDragLeave(e) {
        // Only remove drag-over if we're leaving the container itself
        if (e.target === e.currentTarget) {
            e.currentTarget.classList.remove('drag-over');
        }
    }

    async handleDrop(e) {
        e.preventDefault();
        const dropZone = e.currentTarget;
        dropZone.classList.remove('drag-over');
        
        if (!this.draggedTask) return;
        
        const newColumn = dropZone.dataset.droppable;
        const oldColumn = this.draggedTask.column;
        
        // Calculate new position based on where card was dropped
        const cards = Array.from(dropZone.querySelectorAll('.task-card'));
        const newPosition = cards.findIndex(card => card.dataset.taskId === this.draggedTask.id);
        
        // Always call reorder to handle both column changes and position changes
        try {
            await this.apiCall('/tasks/reorder', {
                method: 'POST',
                body: JSON.stringify({
                    task_id: this.draggedTask.id,
                    column: newColumn,
                    position: newPosition >= 0 ? newPosition : 0
                })
            });
            
            // Update local task data
            const task = this.tasks.find(t => t.id === this.draggedTask.id);
            if (task) {
                task.column = newColumn;
                task.position = newPosition >= 0 ? newPosition : 0;
            }
            
            if (newColumn !== oldColumn) {
                this.showMessage(`Task moved to ${newColumn}`, 'success');
            }
            
            // Reload to get correct positions from server
            await this.loadTasks();
        } catch (error) {
            console.error('Failed to reorder task:', error);
            // Reload to reset positions
            await this.loadTasks();
        }
        
        this.draggedTask = null;
    }

    // Focus Mode
    async startFocus(task) {
        // Move task to in progress if not already there
        if (task.column !== 'inprogress') {
            await this.updateTask(task.id, { column: 'inprogress' });
        }

        try {
            const session = await this.apiCall('/focus/start', {
                method: 'POST',
                body: JSON.stringify({
                    task_id: task.id,
                    started_at: new Date().toISOString(),
                    mode: 'pomodoro'
                })
            });
            
            this.focusSession = session;
            this.showFocusMode();
            this.startFocusTimer();
            
        } catch (error) {
            this.showMessage('Failed to start focus mode', 'error');
        }
    }

    async stopFocus() {
        try {
            await this.apiCall('/focus/stop', { method: 'POST' });
            
            this.focusSession = null;
            this.hideFocusMode();
            this.stopFocusTimer();
            
            this.showMessage('Focus session ended', 'info');
        } catch (error) {
            this.showMessage('Failed to stop focus mode', 'error');
        }
    }

    toggleFocusMode() {
        if (this.focusSession) {
            this.stopFocus();
        } else {
            // Find a task in progress to focus on
            const inProgressTasks = this.tasks.filter(t => t.column === 'inprogress');
            if (inProgressTasks.length > 0) {
                this.startFocus(inProgressTasks[0]);
            } else {
                this.showMessage('No tasks in progress to focus on', 'info');
            }
        }
    }

    showFocusMode() {
        document.body.classList.add('focus-mode');
        document.getElementById('focus-overlay').classList.remove('hidden');
        
        if (this.focusSession) {
            document.getElementById('focus-task-title').textContent = this.focusSession.task_title;
            
            // Highlight the current task
            document.querySelectorAll('.task-card').forEach(card => {
                if (card.dataset.taskId === this.focusSession.task_id) {
                    card.classList.add('current-focus');
                } else {
                    card.classList.remove('current-focus');
                }
            });
        }
    }

    hideFocusMode() {
        document.body.classList.remove('focus-mode');
        document.getElementById('focus-overlay').classList.add('hidden');
        
        document.querySelectorAll('.task-card').forEach(card => {
            card.classList.remove('current-focus');
        });
    }

    startFocusTimer() {
        this.updateFocusTimer(0);
        this.focusTimer = setInterval(() => {
            if (this.focusSession) {
                const elapsed = Math.floor((Date.now() - new Date(this.focusSession.started_at)) / 1000);
                this.updateFocusTimer(elapsed);
            }
        }, 1000);
    }

    stopFocusTimer() {
        if (this.focusTimer) {
            clearInterval(this.focusTimer);
            this.focusTimer = null;
        }
    }

    updateFocusTimer(elapsedSeconds) {
        const timerElement = document.getElementById('focus-timer');
        
        if (this.focusSession && this.focusSession.mode === 'pomodoro') {
            // Pomodoro countdown (25 minutes)
            const totalSeconds = 25 * 60;
            const remainingSeconds = Math.max(0, totalSeconds - elapsedSeconds);
            const minutes = Math.floor(remainingSeconds / 60);
            const seconds = remainingSeconds % 60;
            timerElement.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            
            if (remainingSeconds === 0) {
                this.showMessage('Pomodoro complete! 🍅', 'success');
                this.stopFocus();
            }
        } else {
            // Regular timer (count up)
            const minutes = Math.floor(elapsedSeconds / 60);
            const seconds = elapsedSeconds % 60;
            timerElement.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
    }

    // Quick Add
    showQuickAdd() {
        const modal = document.getElementById('quick-add-modal');
        const input = document.getElementById('quick-add-input');
        
        modal.classList.remove('hidden');
        input.focus();
        input.value = '';
    }

    hideQuickAdd() {
        document.getElementById('quick-add-modal').classList.add('hidden');
    }

    async submitQuickAdd() {
        const input = document.getElementById('quick-add-input');
        const title = input.value.trim();
        
        if (!title) return;
        
        await this.createTask(title);
        this.hideQuickAdd();
    }

    // Column Collapse/Expand
    loadCollapseState() {
        try {
            const saved = localStorage.getItem('kanban-collapsed-columns');
            if (saved) {
                const parsed = JSON.parse(saved);
                // Validate against current columns
                const validColumns = this.columns.map(c => c.id);
                const filtered = parsed.filter(c => validColumns.includes(c));
                this.collapsedColumns = new Set(filtered);
            }
        } catch (e) {
            console.error('Failed to load collapse state:', e);
            localStorage.removeItem('kanban-collapsed-columns');
            this.collapsedColumns = new Set();
        }
    }
    
    resetCollapseState() {
        localStorage.removeItem('kanban-collapsed-columns');
        this.collapsedColumns = new Set();
        document.querySelectorAll('.kanban-column.collapsed').forEach(col => {
            col.classList.remove('collapsed');
        });
        this.updateCollapsedStack();
    }

    saveCollapseState() {
        try {
            localStorage.setItem('kanban-collapsed-columns', JSON.stringify([...this.collapsedColumns]));
        } catch (e) {
            console.error('Failed to save collapse state:', e);
        }
    }

    applyCollapseState() {
        // Apply collapse state to all columns
        this.collapsedColumns.forEach(column => {
            this.collapseColumn(column, false);
        });
    }

    collapseColumn(column, save = true) {
        const columnEl = document.querySelector(`.kanban-column[data-column="${column}"]`);
        if (!columnEl) return;

        // Hide the column
        columnEl.classList.add('collapsed');
        this.collapsedColumns.add(column);

        // Add to collapsed stack
        this.updateCollapsedStack();

        if (save) {
            this.saveCollapseState();
        }
    }

    expandColumn(column) {
        const columnEl = document.querySelector(`.kanban-column[data-column="${column}"]`);
        if (!columnEl) return;

        // Show the column
        columnEl.classList.remove('collapsed');
        this.collapsedColumns.delete(column);

        // Update collapsed stack
        this.updateCollapsedStack();
        this.saveCollapseState();
    }

    updateCollapsedStack() {
        const stack = document.getElementById('collapsed-stack');
        const template = document.getElementById('collapsed-column-template');
        stack.innerHTML = '';

        // Get counts for collapsed columns
        const tasksByColumn = this.groupTasksByColumn();

        this.collapsedColumns.forEach(columnId => {
            const col = this.columns.find(c => c.id === columnId);
            if (!col) return;
            
            const el = template.content.cloneNode(true);
            const colEl = el.querySelector('.collapsed-column');
            colEl.dataset.column = columnId;
            colEl.style.borderTopColor = col.color;
            el.querySelector('.collapsed-title').textContent = col.name;
            el.querySelector('.collapsed-count').textContent = (tasksByColumn[columnId] || []).length;
            stack.appendChild(el);
        });
    }

    // Archive (legacy - now handled by collapse)
    toggleArchive() {
        const archiveContent = document.getElementById('archive-content');
        archiveContent?.classList.toggle('hidden');
    }

    // Column Configuration
    loadColumnConfig() {
        try {
            const saved = localStorage.getItem('kanban-columns');
            if (saved) {
                this.columns = JSON.parse(saved);
            } else {
                this.columns = [...this.defaultColumns];
            }
        } catch (e) {
            console.error('Failed to load column config:', e);
            this.columns = [...this.defaultColumns];
        }
    }

    saveColumnConfig() {
        try {
            localStorage.setItem('kanban-columns', JSON.stringify(this.columns));
        } catch (e) {
            console.error('Failed to save column config:', e);
        }
    }

    renderColumns() {
        const board = document.getElementById('kanban-board');
        board.innerHTML = '';

        this.columns.forEach(col => {
            const columnEl = this.createColumnElement(col);
            board.appendChild(columnEl);
        });

        // Add the "Add Column" button at the end
        const addColBtn = document.createElement('button');
        addColBtn.className = 'add-column-btn';
        addColBtn.innerHTML = '+';
        addColBtn.title = 'Add Column';
        addColBtn.addEventListener('click', () => this.showAddColumnModal());
        board.appendChild(addColBtn);
    }

    createColumnElement(col) {
        const column = document.createElement('div');
        column.className = 'kanban-column';
        column.dataset.column = col.id;
        column.style.borderLeftColor = col.color;

        column.innerHTML = `
            <div class="kanban-header" draggable="true">
                <span class="drag-handle" title="Drag to reorder">⠿</span>
                <button class="collapse-btn" title="Collapse">‹</button>
                <span class="kanban-title">${col.name}</span>
                <div class="kanban-header-actions">
                    <span class="kanban-count font-mono">0</span>
                    ${col.id === 'unsorted' ? '<button class="clear-column-btn" data-column="' + col.id + '" title="Clear all">⌫</button>' : ''}
                    <button class="add-card-btn" data-column="${col.id}" title="Add">+</button>
                    <button class="delete-column-btn" data-column="${col.id}" title="Delete column">×</button>
                </div>
            </div>
            <div class="kanban-content" data-droppable="${col.id}"></div>
        `;

        return column;
    }

    setupColumnDragAndDrop() {
        const board = document.getElementById('kanban-board');
        
        // Use event delegation for column header dragging
        board.addEventListener('dragstart', (e) => {
            // Ignore if dragging a task card
            if (e.target.closest('.task-card')) return;
            
            const header = e.target.closest('.kanban-header');
            if (header && header.draggable) {
                const column = header.closest('.kanban-column');
                if (column) {
                    this.draggedColumn = column;
                    column.classList.add('column-dragging');
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', column.dataset.column);
                }
            }
        });

        board.addEventListener('dragend', (e) => {
            if (this.draggedColumn) {
                this.draggedColumn.classList.remove('column-dragging');
                this.draggedColumn = null;
                document.querySelectorAll('.kanban-column').forEach(c => c.classList.remove('column-drag-over'));
            }
        });

        board.addEventListener('dragover', (e) => {
            if (!this.draggedColumn) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            const column = e.target.closest('.kanban-column');
            if (column && column !== this.draggedColumn) {
                document.querySelectorAll('.kanban-column').forEach(c => c.classList.remove('column-drag-over'));
                column.classList.add('column-drag-over');
            }
        });

        board.addEventListener('drop', (e) => {
            if (!this.draggedColumn) return;
            e.preventDefault();
            
            const targetColumn = e.target.closest('.kanban-column');
            if (targetColumn && targetColumn !== this.draggedColumn) {
                // Reorder columns
                const draggedId = this.draggedColumn.dataset.column;
                const targetId = targetColumn.dataset.column;
                
                const draggedIdx = this.columns.findIndex(c => c.id === draggedId);
                const targetIdx = this.columns.findIndex(c => c.id === targetId);
                
                if (draggedIdx !== -1 && targetIdx !== -1) {
                    const [removed] = this.columns.splice(draggedIdx, 1);
                    this.columns.splice(targetIdx, 0, removed);
                    this.saveColumnConfig();
                    this.renderColumns();
                    this.setupEventListenersForColumns();
                    this.setupDragAndDrop();
                    this.renderTasks();
                    this.showMessage('Column moved', 'success');
                }
            }
            
            document.querySelectorAll('.kanban-column').forEach(c => c.classList.remove('column-drag-over'));
        });
    }

    setupEventListenersForColumns() {
        // Add card buttons
        document.querySelectorAll('.add-card-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showInlineAddCard(btn.dataset.column);
            });
        });

        // Clear column buttons
        document.querySelectorAll('.clear-column-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.clearColumn(btn.dataset.column);
            });
        });

        // Collapse buttons
        document.querySelectorAll('.collapse-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const column = btn.closest('.kanban-column').dataset.column;
                this.collapseColumn(column);
            });
        });

        // Delete column buttons
        document.querySelectorAll('.delete-column-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteColumn(btn.dataset.column);
            });
        });
    }

    showAddColumnModal() {
        const name = prompt('New column name:');
        if (!name || !name.trim()) return;

        const id = name.toLowerCase().replace(/[^a-z0-9]/g, '');
        if (this.columns.some(c => c.id === id)) {
            this.showMessage('Column already exists', 'error');
            return;
        }

        // Pick a color
        const colors = ['#4ea1ff', '#35d07f', '#f0b429', '#f97316', '#a855f7', '#06b6d4', '#ec4899', '#84cc16'];
        const usedColors = new Set(this.columns.map(c => c.color));
        const color = colors.find(c => !usedColors.has(c)) || colors[0];

        this.columns.push({ id, name: name.trim(), color });
        this.saveColumnConfig();
        this.renderColumns();
        this.setupEventListenersForColumns();
        this.setupDragAndDrop();
        this.renderTasks();
        this.showMessage(`Column "${name}" created`, 'success');
    }

    deleteColumn(columnId) {
        const column = this.columns.find(c => c.id === columnId);
        if (!column) return;

        const tasksInColumn = this.tasks.filter(t => t.column === columnId);
        if (tasksInColumn.length > 0) {
            if (!confirm(`Delete "${column.name}" and move ${tasksInColumn.length} tasks to Unsorted?`)) {
                return;
            }
            // Move tasks to unsorted
            tasksInColumn.forEach(t => {
                this.updateTask(t.id, { column: 'unsorted' });
            });
        }

        this.columns = this.columns.filter(c => c.id !== columnId);
        this.saveColumnConfig();
        this.renderColumns();
        this.setupEventListenersForColumns();
        this.setupDragAndDrop();
        this.renderTasks();
        this.showMessage(`Column "${column.name}" deleted`, 'success');
    }

    resetColumns() {
        localStorage.removeItem('kanban-columns');
        this.columns = [...this.defaultColumns];
        this.renderColumns();
        this.setupEventListenersForColumns();
        this.setupDragAndDrop();
        this.renderTasks();
    }

    // Utility
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

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.missionControl = new MissionControl();
    // Expose reset functions for debugging
    window.resetKanban = () => {
        window.missionControl.resetCollapseState();
        window.missionControl.loadTasks();
    };
    window.resetColumns = () => {
        window.missionControl.resetColumns();
    };
});