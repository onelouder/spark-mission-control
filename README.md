# Mission Control - Kanban Dashboard

A modern Kanban dashboard with email and calendar integration, designed for personal productivity. Mission Control aggregates data from Decapoda-Lite API (email/calendar) and presents it as a visual task management system.

## Features

### Core Kanban
- **5 Columns**: Unsorted, To Do, In Progress, Done, Archive
- **Drag & Drop**: Move tasks between columns
- **Energy Tags**: ⚡ High Burn, ☕ Low Stakes, 🧟 Brain Dead
- **Project Health**: Visual indicators for tasks stuck in columns
- **Auto-categorization**: Email triaged by subject/sender

### Focus Mode ("NOW" Button)
- Hide all columns except In Progress
- Timer (Pomodoro 25:00 or count-up)
- Visual blur/fade other tasks
- Keyboard shortcut: `F`

### Unified Timeline
- Horizontal bar showing today's calendar events
- Meeting blocks visualized
- Work windows identified

### Interruption Log
- **Keyboard shortcut**: `Cmd+K` / `Ctrl+K`
- Quick-add modal for capture thoughts
- Dumps to Unsorted column
- Minimal friction workflow

### Morning Brief
- Daily summary at top of dashboard
- Meeting count, task counts, work windows
- Template-based (can be enhanced with LLM later)

### Email Integration
- Auto-sync from Decapoda-Lite inbox
- Categorizes as: 🔴 Action Required, 📚 Reference, 🗑️ Ignore
- Links to original email
- Skips read emails and promotional content

### Calendar Integration
- Displays today's events on timeline
- Links to original calendar events
- Filters out cancelled meetings

## Architecture

**Single Source of Truth**: The Kanban is a visual aggregator, not manual entry. All data flows from Decapoda.

**Tech Stack**:
- Backend: FastAPI (Python)
- Frontend: Vanilla JavaScript + Tailwind CSS
- Persistence: JSON files (MVP), SQLite planned
- API Integration: Decapoda-Lite at localhost:8766

## Installation

1. **Prerequisites**: Ensure Decapoda-Lite is running at localhost:8766

2. **Setup**:
   ```bash
   cd ~/projects/mission-control
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Run**:
   ```bash
   source venv/bin/activate
   python app.py
   ```

4. **Access**: Open http://localhost:3000

## API Endpoints

### Sync
- `GET /api/sync/email` - Fetch new emails from Decapoda
- `GET /api/sync/calendar` - Fetch calendar events from Decapoda

### Tasks
- `GET /api/tasks` - Get all tasks
- `POST /api/tasks` - Create new task (quick-add)
- `PUT /api/tasks/{id}` - Update task (drag & drop)
- `DELETE /api/tasks/{id}` - Delete task

### Focus Mode
- `POST /api/focus/start` - Start focus session
- `POST /api/focus/stop` - End focus session
- `GET /api/focus/status` - Get current focus status

### Dashboard
- `GET /api/brief` - Get morning brief summary
- `GET /` - Main dashboard UI

## Usage

### Keyboard Shortcuts
- `Cmd+K` / `Ctrl+K`: Quick-add task
- `F`: Toggle focus mode
- `Escape`: Close modals/exit focus

### Workflow
1. **Morning**: Check brief and timeline
2. **Throughout day**: Use Cmd+K to capture interruptions
3. **Triage**: Drag tasks from Unsorted to To Do
4. **Focus**: Use NOW button on In Progress tasks
5. **End of day**: Move completed tasks to Done

### Energy Levels
- **⚡ High Burn**: Complex, urgent tasks requiring deep focus
- **☕ Low Stakes**: Regular tasks, moderate effort
- **🧟 Brain Dead**: Simple tasks for low-energy periods

## File Structure

```
~/projects/mission-control/
├── app.py              # FastAPI server
├── requirements.txt    # Python dependencies
├── static/
│   ├── app.js         # Main JavaScript
│   └── styles.css     # CSS styles (dark theme)
├── templates/
│   └── index.html     # Dashboard UI
└── data/              # JSON persistence
    ├── tasks.json     # Task storage
    └── focus.json     # Focus session state
```

## Design Philosophy

**Dark Theme**: Matches Decapoda admin aesthetic
**Minimal**: Clean, scannable cards without information overload
**Fast**: Optimized for speed and keyboard navigation
**Visual**: Uses emojis and colors for quick recognition
**Contextual**: Links back to source data (email/calendar)

## Future Enhancements

- SQLite database for better persistence
- LLM-powered email categorization
- Advanced timeline features
- Team collaboration features
- Mobile responsive design
- Custom energy level definitions
- Advanced filtering and search

## Troubleshooting

**Connection Issues**: Ensure Decapoda-Lite is running at localhost:8766
**Port Conflicts**: Change port in app.py if 3000 is occupied
**Permission Errors**: Check file permissions in data/ directory
**Missing Tasks**: Click "Sync Data" to refresh from Decapoda

## Contributing

This is a personal productivity tool. Fork and adapt for your needs!

---

Built with ❤️ for focused productivity and minimal cognitive overhead.