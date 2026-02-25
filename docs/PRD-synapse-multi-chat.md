# PRD: Synapse Multi-Chat Interface

**Product**: Mission Control — Synapse Page  
**Version**: 1.0  
**Last Updated**: 2026-02-11  
**Author**: Jarvis  

---

## 1. Overview

### 1.1 Purpose
Synapse is a multi-agent chat interface that enables simultaneous conversations with multiple AI agents in a unified dashboard. It serves as the primary interaction surface for the OpenClaw agent constellation.

### 1.2 Problem Statement
Managing a fleet of 16+ specialized AI agents requires efficient context-switching and parallel interaction. Traditional single-chat interfaces force sequential communication, limiting productivity and cross-agent collaboration.

### 1.3 Solution
A 2x2 grid of chat panes with:
- Real-time agent selection and streaming responses
- Unified command bar for fleet-wide operations
- Visual organization by agent domain/organization
- Per-pane model override capability

---

## 2. User Personas

**Primary User**: Jason Wells (operator)
- Needs to query multiple specialists simultaneously
- Wants to see agent responses in parallel
- Requires quick agent switching without losing context

---

## 3. Core Features

### 3.1 Multi-Pane Chat Grid
- **Layout**: 2x2 grid of independent chat panes
- **Pane Components**:
  - Header bar with agent name, org badge, model selector
  - Message history with user/assistant differentiation
  - Input field with send button
  - Connection status indicator
- **Independence**: Each pane maintains its own:
  - Selected agent
  - Message history
  - Streaming state
  - Model override (optional)

### 3.2 Agent Selection
- **Agent Picker**: Dropdown in pane header showing all available agents
- **Organization Grouping**: Agents grouped by org with color coding:
  - Internal (Indigo #6366f1): Jarvis, Aria, Peter, Watson, ELon, Dewey, Ares
  - Novvi (Emerald #10b981): Will B., JC
  - X-Cognis (Amber #f59e0b): Xavier, Xena, Xander, Xyla, Ximena, Xerxes, Xeno
- **Visual Indicators**: Org color appears on:
  - Fleet cards (left border + badge)
  - Pane headers
  - Agent picker dropdown
  - Command bar results

### 3.3 Real-Time Streaming
- **Protocol**: WebSocket connection to `/api/synapse/ws`
- **Streaming Events**:
  - `type: agents` — Agent list with status
  - `type: subscribed` — Confirmation of agent subscription
  - `type: chunk` — Streaming text delta
  - `type: complete` — Response finished
  - `type: error` — Error message
- **Cumulative Text**: Gateway sends cumulative text (not incremental deltas)
- **Content Blocks**: Message content arrives as array of blocks, must iterate to extract text

### 3.4 Fleet Status Cards
- **Location**: Left sidebar
- **Information Displayed**:
  - Agent name and emoji
  - Organization badge with color
  - Online/offline status
  - Last activity timestamp
- **Interaction**: Click to assign agent to focused pane

### 3.5 Command Bar (Cmd+K)
- **Trigger**: Keyboard shortcut Cmd+K (Mac) or Ctrl+K (Windows)
- **Features**:
  - Fuzzy search across all agents
  - Quick agent assignment to panes
  - Fleet-wide commands (future)
- **Results**: Show agent name, org, and status

### 3.6 Model Selector
- **Location**: Pane header, next to agent picker
- **Options**: 
  - Default (uses agent's configured model)
  - Sonnet (anthropic/claude-sonnet-4-20250514)
  - Opus (anthropic/claude-opus-4-5)
- **Behavior**: Override persists for pane session, sent with each message

---

## 4. Architecture

### 4.1 Frontend Stack
- **Template**: `templates/synapse.html` (Jinja2)
- **Styling**: Tailwind CSS (CDN)
- **JavaScript**: Vanilla JS, no framework
- **WebSocket**: Native WebSocket API

### 4.2 Backend Stack
- **Framework**: FastAPI (Python)
- **WebSocket Handler**: `agent_router.py`
- **Gateway Integration**: Proxies to OpenClaw gateway at `localhost:18789`

### 4.3 Data Flow

```
┌─────────────┐     WebSocket      ┌─────────────────┐     HTTP/WS     ┌─────────────┐
│   Browser   │ ◄───────────────► │  agent_router   │ ◄─────────────► │   Gateway   │
│  (Synapse)  │                   │   (FastAPI)     │                 │  (OpenClaw) │
└─────────────┘                   └─────────────────┘                 └─────────────┘
      │                                   │                                  │
      │ 1. Connect to /api/synapse/ws     │                                  │
      │ ──────────────────────────────►   │                                  │
      │                                   │ 2. Fetch agent list              │
      │                                   │ ──────────────────────────────►  │
      │ 3. Receive agents list            │                                  │
      │ ◄──────────────────────────────   │                                  │
      │                                   │                                  │
      │ 4. Subscribe to agent             │                                  │
      │ ──────────────────────────────►   │                                  │
      │                                   │ 5. Connect to agent session      │
      │                                   │ ──────────────────────────────►  │
      │ 6. Subscription confirmed         │                                  │
      │ ◄──────────────────────────────   │                                  │
      │                                   │                                  │
      │ 7. Send message                   │                                  │
      │ ──────────────────────────────►   │                                  │
      │                                   │ 8. Forward to gateway            │
      │                                   │ ──────────────────────────────►  │
      │                                   │ 9. Stream response chunks        │
      │                                   │ ◄──────────────────────────────  │
      │ 10. Receive chunks                │                                  │
      │ ◄──────────────────────────────   │                                  │
```

### 4.4 Session Management
- **Session Key Pattern**: `agent:<agent_id>:<suffix>`
  - Example: `agent:jarvis:jarvis`, `agent:atlas:main`
- **Session Lookup**: Extract agent_id from pattern, find matching session
- **Context Limits**: Sessions can hit 200k token limit, require reset

---

## 5. API Specification

### 5.1 WebSocket Endpoint
**URL**: `ws://host:3000/api/synapse/ws`

#### Client → Server Messages

```json
// Subscribe to agent
{
  "type": "subscribe",
  "agent_id": "jarvis"
}

// Send message
{
  "type": "message",
  "agent_id": "jarvis",
  "content": "Hello",
  "model": "anthropic/claude-sonnet-4-20250514"  // optional override
}

// Unsubscribe
{
  "type": "unsubscribe",
  "agent_id": "jarvis"
}
```

#### Server → Client Messages

```json
// Agent list
{
  "type": "agents",
  "agents": [
    {
      "id": "jarvis",
      "name": "Jarvis",
      "emoji": "🎩",
      "org": "internal",
      "status": "online"
    }
  ]
}

// Subscription confirmed
{
  "type": "subscribed",
  "agent_id": "jarvis"
}

// Streaming chunk
{
  "type": "chunk",
  "agent_id": "jarvis",
  "payload": {
    "text": "cumulative response text so far"
  }
}

// Response complete
{
  "type": "complete",
  "agent_id": "jarvis"
}

// Error
{
  "type": "error",
  "agent_id": "jarvis",
  "message": "Session context limit exceeded"
}
```

### 5.2 Agent Registry
**Location**: `agent_router.py` → `AGENT_REGISTRY`

```python
AGENT_REGISTRY = {
    "jarvis": {"name": "Jarvis", "emoji": "🎩", "org": "internal"},
    "aria": {"name": "Aria", "emoji": "🔬", "org": "internal"},
    "xavier": {"name": "Xavier", "emoji": "🎯", "org": "xcognis"},
    # ... etc
}
```

---

## 6. UI Specifications

### 6.1 Layout
```
┌────────────────────────────────────────────────────────────────┐
│  Mission Control        [Briefing] [Email] [Kanban] [Synapse] │
├──────────┬─────────────────────────────────────────────────────┤
│          │  ┌─────────────────────┐ ┌─────────────────────┐   │
│  Fleet   │  │ Pane 0              │ │ Pane 1              │   │
│  Cards   │  │ [Agent ▼] [Model ▼] │ │ [Agent ▼] [Model ▼] │   │
│          │  │                     │ │                     │   │
│  🎩 Jarvis│  │  Chat messages...   │ │  Chat messages...   │   │
│  🔬 Aria │  │                     │ │                     │   │
│  💰 Peter│  │ [Input............] │ │ [Input............] │   │
│  🏥 Watson│  └─────────────────────┘ └─────────────────────┘   │
│  🎯 Xavier│  ┌─────────────────────┐ ┌─────────────────────┐   │
│  ...     │  │ Pane 2              │ │ Pane 3              │   │
│          │  │ [Agent ▼] [Model ▼] │ │ [Agent ▼] [Model ▼] │   │
│          │  │                     │ │                     │   │
│          │  │  Chat messages...   │ │  Chat messages...   │   │
│          │  │                     │ │                     │   │
│          │  │ [Input............] │ │ [Input............] │   │
│          │  └─────────────────────┘ └─────────────────────┘   │
└──────────┴─────────────────────────────────────────────────────┘
```

### 6.2 Color Palette (Organizations)
| Org | Primary | Badge BG | Badge Text |
|-----|---------|----------|------------|
| Internal | #6366f1 (Indigo) | #eef2ff | #4338ca |
| Novvi | #10b981 (Emerald) | #ecfdf5 | #047857 |
| X-Cognis | #f59e0b (Amber) | #fffbeb | #b45309 |

### 6.3 Message Styling
- **User messages**: Right-aligned, blue background (#3b82f6)
- **Assistant messages**: Left-aligned, gray background (#374151)
- **Streaming indicator**: Pulsing cursor or "..." animation
- **Error messages**: Red background, error icon

---

## 7. Known Issues & Technical Debt

### 7.1 Current Issues
1. **Subscription Spam**: `selectAgent()` sends subscribe unconditionally (line 1555-1580)
   - **Impact**: Duplicate subscriptions, wasted resources
   - **Fix**: Check `paneSubscribed[paneIdx]` before sending

2. **Agent-to-Agent Relay Cross-Talk**: When agents message each other, responses can leak to wrong panes
   - **Impact**: Token bloat, confusing UX
   - **Fix**: Consider disabling `agentToAgent: { enabled: true }` or improving routing

3. **Context Limit Handling**: Sessions hitting 200k token limit return 400 errors
   - **Impact**: Agent becomes unresponsive
   - **Fix**: Proactive session reset, token usage display

### 7.2 Technical Debt
- No message persistence (messages lost on page refresh)
- No pagination for long conversations
- No message editing or deletion
- Model selector state not persisted

---

## 8. Future Enhancements

### 8.1 Short-Term (v1.1)
- [ ] Persist messages to localStorage
- [ ] Add token usage indicator per pane
- [ ] Implement session reset button
- [ ] Fix subscription spam

### 8.2 Medium-Term (v1.5)
- [ ] Cross-pane message routing (send to multiple agents)
- [ ] Saved pane configurations (presets)
- [ ] Message search across all panes
- [ ] Export conversation as Markdown

### 8.3 Long-Term (v2.0)
- [ ] Agent collaboration mode (agents can see each other's panes)
- [ ] Voice input/output per pane
- [ ] Custom pane layouts (1x1, 2x3, etc.)
- [ ] Agent workflow automation

---

## 9. Files Reference

| File | Purpose |
|------|---------|
| `templates/synapse.html` | Frontend template (HTML + JS) |
| `agent_router.py` | WebSocket handler, gateway proxy |
| `static/css/synapse.css` | Custom styles (if any) |
| `data/config.json` | App configuration |

---

## 10. Testing Checklist

- [ ] Agent selection updates pane header
- [ ] Messages send and stream correctly
- [ ] Model override works
- [ ] Org colors display correctly
- [ ] Cmd+K opens command bar
- [ ] Fleet cards show correct status
- [ ] WebSocket reconnects on disconnect
- [ ] Error messages display in pane
