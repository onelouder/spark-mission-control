# SYNAPSE — Multi-Agent Command Interface

## Product Requirements Document v1.0

**Project:** Synapse Personal AI Operating System  
**Component:** Synapse — Agent Fleet Interface  
**Author:** Jason  
**Hardware Target:** NVIDIA DGX Spark (GB10 Grace Blackwell, 128GB LPDDR5x, 4TB)  
**Date:** February 2026  

---

## 1. Vision

Synapse is the command interface for Synapse — a personal AI operating system built on data sovereignty. It replaces the "1 WebSocket → 1 session → 1 agent" paradigm with a unified cockpit for observing, directing, and conversing with a fleet of 10–15 specialized AI agents running locally on an NVIDIA DGX Spark.

The core insight: **you OBSERVE all agents, but you CHAT with one at a time.** This distinction drives every architectural decision — from the multiplexed WebSocket protocol to the visual hierarchy of the interface.

Synapse is not a chatbot UI. It is a mission control surface for autonomous agents that do real work.

---

## 2. Design Principles

### 2.1 Intent Layer, Not Chat Layer

Synapse functions as an intent layer — a central intelligence that understands your goals and orchestrates agents to act on your behalf. Synapse is the window into that layer. Users express intent (via command bar or direct chat), and the system routes, decomposes, and delegates to the right agents.

### 2.2 Autonomy First

Agents are not assistants waiting for input. They are workers assigned tasks that they execute until completion. The interface reflects this: agents report status, the user drops in to observe or redirect, then leaves them to it. No babysitting.

### 2.3 Data Sovereignty

All agent inference, memory, and data processing happens on the local DGX Spark. Personally identifiable information never leaves the hardware. Cloud models may be used for complex reasoning, but only through sanitized abstractions where PII has been stripped.

### 2.4 Terminal Aesthetics

The interface draws from the information density and readability of terminal UIs:

- **Monospace typography** — 14–15px, ~1.5–1.6x line height, 85–95 characters per line
- **Warm dark palette** — soft plum/mauve background (#2D2030 range), warm off-white text (#E0D0C0 range)
- **Zero-chrome density** — no padding waste, no decorative borders, no role badges eating horizontal space. Every pixel is content
- **10,000-line scrollback** — uncapped message arrays, browser-native scroll, instant history

This is not a design choice; it is an information architecture choice. Dense, readable, fast.

---

## 3. Architecture Overview

### 3.1 The Four Views

Synapse is a single-window application with four views and a universal command bar:

| View | Purpose | Phase |
|------|---------|-------|
| **FLEET** | Agent dashboard — status, context, tasks at a glance | Phase 1 |
| **CHAT** | Focused conversation with the selected agent | Phase 1 |
| **TELEMETRY** | GB10 hardware monitoring — memory, bandwidth, thermal | Phase 2 |
| **PIPELINE** | Visual orchestration graph — agent dependencies, data flow | Phase 3 |

Phase 1 is the product. Telemetry and Pipeline are operational enhancements.

### 3.2 Multiplexed WebSocket Protocol

Synapse uses a **two-tier WebSocket architecture**:

1. **Client ↔ Mission Control** — Synapse frame protocol (subscribe/message/status)
2. **Mission Control ↔ Moltbot Gateway** — Native Gateway RPC protocol

```
┌─────────────────────────────────────────────────────┐
│  Browser (Synapse UI)                               │
│  ┌───────────────────────────────────────────────┐  │
│  │  Single WebSocket to Mission Control          │  │
│  │  ws://localhost:3000/api/synapse/ws           │  │
│  │  (Synapse frame protocol)                     │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Mission Control (Agent Router)                     │
│  - Translates Synapse frames → Gateway RPCs         │
│  - Maintains ONE persistent WS to Gateway           │
│  - Polls sessions.list for status aggregation       │
│  - Routes messages via sessions.send                │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Moltbot Gateway (ws://localhost:18789)             │
│  - sessions.list → all session status               │
│  - sessions.send → route to any agent session       │
│  - sessions.history → fetch transcript              │
│  - Native auth, session lifecycle, streaming        │
└─────────────────────────────────────────────────────┘
```

**Why this architecture:**
- Gateway already owns session state — don't duplicate
- Single Gateway connection = no per-agent WebSocket overhead
- Forward compatible — when Gateway ships native multi-session events, we subscribe instead of poll
- Clean separation — Synapse owns UI/orchestration, Gateway owns sessions

**Status Channel** — derived from `sessions.list` polling (2-5s interval):

```json
{
  "agentId": "aria",
  "type": "status",
  "state": "working",
  "task": "Research semiconductor export restrictions",
  "ctx": 0.45,
  "updated": "2026-02-05T14:32:00Z"
}
```

**Message Channel** — focused agent only. Routed via `sessions.send`:

```json
{ "agentId": "aria", "type": "chunk", "text": "Based on the latest..." }
```

Focus switching is explicit subscribe/unsubscribe:

```json
→ { "type": "unsubscribe", "agentId": "aria", "channel": "messages" }
→ { "type": "subscribe", "agentId": "peter", "channel": "messages" }
→ { "type": "history", "agentId": "peter", "limit": 100 }
← [history payload from sessions.history]
← [live stream begins]
```

### 3.3 Frame Protocol

Every WebSocket frame carries a typed envelope:

```json
{
  "type": "<frame_type>",
  "agentId": "<target_agent>",
  "channel": "status" | "messages",
  "payload": { ... },
  "ts": "<ISO-8601>"
}
```

**Client → Server frame types:**

| Type | Purpose | Payload |
|------|---------|---------|
| `message` | Send message to agent | `{ text, attachments? }` |
| `subscribe` | Start receiving agent's messages | `{ channel }` |
| `unsubscribe` | Stop receiving agent's messages | `{ channel }` |
| `history` | Request conversation history | `{ limit, before? }` |
| `command` | System-level command | `{ cmd, args }` |
| `task.assign` | Assign task to agent | `{ task, priority? }` |
| `task.cancel` | Cancel running task | `{ taskId }` |

**Server → Client frame types:**

| Type | Purpose | Payload |
|------|---------|---------|
| `status` | Agent status update | `{ state, task, ctx, metrics? }` |
| `chunk` | Streaming response token | `{ text, done? }` |
| `message` | Complete message | `{ role, text, ts }` |
| `history` | History response | `{ messages[], cursor? }` |
| `error` | Error notification | `{ code, message }` |
| `task.update` | Task progress | `{ taskId, status, progress? }` |

---

## 4. FLEET View (Phase 1)

### 4.1 Purpose

The FLEET view is the default landing surface. It provides at-a-glance awareness of every agent in the fleet — what they are doing, whether they need attention, and how loaded they are.

### 4.2 Agent Card

Each agent is represented by a card in a responsive grid. Cards are dense and information-forward:

```
┌─────────────────────────────────────────────┐
│  ● ARIA                          working    │
│  Research: semiconductor export policy       │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░ 72% ctx             │
│  ⏱ 4m 32s  ↑3 msgs                         │
└─────────────────────────────────────────────┘
```

**Card fields:**

| Field | Description |
|-------|-------------|
| Agent name | Identifier + optional persona label |
| Status indicator | `idle`, `working`, `waiting`, `error`, `sleeping` |
| Current task | Brief description of what the agent is doing |
| Context usage | Percentage of context window consumed (visual bar) |
| Duration | Time on current task |
| Unread count | Messages since last focus |
| Last output preview | Truncated last message (on hover or compact mode) |

**Agent states and their visual encoding:**

| State | Color | Meaning |
|-------|-------|---------|
| `idle` | Dim / muted | No active task, awaiting assignment |
| `working` | Accent pulse | Actively processing a task |
| `waiting` | Amber | Blocked — needs input, approval, or external data |
| `error` | Red | Failed — needs attention |
| `sleeping` | Purple dim | Background consolidation (memory/indexing) |

### 4.3 Interactions

- **Click card** → switch to CHAT view focused on that agent
- **Right-click card** → context menu: assign task, view history, restart, kill
- **Drag card** → reorder grid (position persists)
- **Double-click status** → quick-send from FLEET without switching to CHAT

### 4.4 Fleet Summary Bar

A thin summary strip at the top of FLEET showing aggregate status:

```
FLEET: 12 agents | 8 working | 2 idle | 1 waiting | 1 error | GPU: 67% | MEM: 48/128 GB
```

---

## 5. CHAT View (Phase 1)

### 5.1 Purpose

The CHAT view is a focused, full-fidelity conversation with a single agent. It mirrors the terminal chat experience: dense monospace text, generous scrollback, no chrome.

### 5.2 Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [FLEET] [CHAT: aria] [TELEMETRY] [PIPELINE]    [⌘ cmd bar] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ARIA — Research Agent                         working  72%  │
│  ─────────────────────────────────────────────────────────── │
│                                                              │
│  [14:22] you: Look into the latest semiconductor export      │
│  restrictions and how they affect NVIDIA's supply chain.     │
│                                                              │
│  [14:22] aria: I'll research this now. Starting with the     │
│  most recent BIS rulings from January 2026...                │
│                                                              │
│  [14:28] aria: Here's what I've found so far:                │
│                                                              │
│  The Bureau of Industry and Security issued updated          │
│  controls on January 15, 2026 targeting advanced compute     │
│  architectures. Key changes include...                       │
│                                                              │
│  [streaming...]                                              │
│                                                              │
│                                                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  > @aria ░                                                   │
└──────────────────────────────────────────────────────────────┘
```

### 5.3 Message Rendering

- **User messages** highlighted with warm cream/yellow background block (distinct from agent output, no badges needed)
- **Agent messages** in default warm off-white on dark background
- **Timestamps** subdued, left-aligned, `[HH:MM]` format
- **Code blocks** rendered with syntax highlighting, monospace (already monospace context, so just background tint differentiation)
- **Tables** rendered with box-drawing characters, native terminal style
- **Streaming** tokens append in real-time; no skeleton loaders, no typing indicators — just text appearing

### 5.4 History

- Server-side storage, fetched on agent focus
- Paginated with cursor-based infinite scroll (`before: <cursor>` for older messages)
- Client-side cache: retain last N sessions in memory for instant switch-back
- Target: 10,000 messages per agent scrollback buffer
- Reconnect: refetch from server, instant restore

### 5.5 Cross-Agent Messaging from CHAT

While focused on one agent, you can still message others via the command bar:

```
@peter schedule a meeting with the design team for Thursday
```

The message routes to Peter. If Peter is not focused, his FLEET card updates with an unread badge and preview. If he is focused, the response streams live.

---

## 6. Command Bar (Phase 1)

### 6.1 Purpose

The command bar is the universal input surface, accessible from any view via keyboard shortcut (⌘K or `/`). It is the primary expression point for user intent.

### 6.2 Syntax

```
@<agent> <message>           Direct message to agent
/<command> [args]             System command
<bare text>                   Message to currently focused agent (in CHAT view)
```

### 6.3 Agent Routing

The `@agent` prefix routes messages to any agent regardless of which view or focus state the user is in. Auto-complete suggests agent names after `@`.

### 6.4 System Commands

| Command | Action |
|---------|--------|
| `/fleet` | Switch to FLEET view |
| `/chat <agent>` | Switch to CHAT view for agent |
| `/telemetry` | Switch to TELEMETRY view |
| `/pipeline` | Switch to PIPELINE view |
| `/spawn <agent> <config>` | Create a new agent instance |
| `/kill <agent>` | Terminate an agent |
| `/task <agent> <description>` | Assign task to agent |
| `/status` | Print fleet summary |
| `/history <agent> [n]` | Dump last N messages from agent |
| `/export <agent>` | Export agent memory/state |
| `/help` | List available commands |

### 6.5 Behavior

- Always visible as a thin bar at the top or bottom of the window
- Expands on focus to show autocomplete suggestions
- Command history with up/down arrows
- Agent names autocomplete with current status shown inline

---

## 7. Agent Router Backend (Phase 1)

### 7.1 Purpose

The Agent Router is a **thin translation layer** between Synapse UI and Moltbot Gateway. It does NOT replace the Gateway — it delegates to it.

### 7.2 Responsibilities

1. **Frame translation** — Synapse frames → Gateway RPC calls
2. **Status aggregation** — poll `sessions.list`, aggregate into status channel
3. **Subscription management** — track which agent's message channel the client is subscribed to
4. **Connection management** — maintain single persistent WS to Gateway

**NOT responsibilities (handled by Moltbot Gateway):**
- Connection auth (reuse Gateway token)
- Session lifecycle (Gateway manages sessions)
- Message history (call `sessions.history`)
- Message delivery (call `sessions.send`)

### 7.3 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agent Router                               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Client WS    │    │ Frame        │    │ Gateway Client   │  │
│  │ Handler      │───▶│ Translator   │───▶│ (Single WS)      │  │
│  │              │    │              │    │                  │  │
│  │ Synapse      │    │ subscribe →  │    │ sessions.list    │  │
│  │ frames       │    │   history    │    │ sessions.send    │  │
│  │              │    │ message →    │    │ sessions.history │  │
│  │              │    │   send       │    │                  │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│         ▲                                         │             │
│         │                                         ▼             │
│  ┌──────────────┐                        ┌──────────────────┐  │
│  │ Status       │◀───────────────────────│ Moltbot Gateway  │  │
│  │ Aggregator   │     poll every 2-5s    │ ws://localhost:  │  │
│  │ (push to     │                        │ 18789            │  │
│  │  clients)    │                        │                  │  │
│  └──────────────┘                        └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.4 Gateway Client

A single persistent WebSocket connection to Moltbot Gateway, shared across all Synapse clients:

```python
class GatewayClient:
    """Single persistent connection to Moltbot Gateway."""
    
    def __init__(self, url: str = "ws://localhost:18789", token: str = None):
        self.url = url
        self.token = token
        self.ws = None
        self.request_id = 0
        self.pending: Dict[int, asyncio.Future] = {}
        
    async def connect(self):
        """Establish connection and authenticate."""
        self.ws = await websockets.connect(self.url)
        await self._send_request("connect", {
            "auth": {"token": self.token} if self.token else {}
        })
        asyncio.create_task(self._listen())
        
    async def _listen(self):
        """Listen for responses and route to pending futures."""
        async for raw in self.ws:
            frame = json.loads(raw)
            if frame.get("type") == "res":
                req_id = frame.get("id")
                if req_id in self.pending:
                    self.pending[req_id].set_result(frame)
                    
    async def _request(self, method: str, params: dict) -> dict:
        """Send RPC request and await response."""
        self.request_id += 1
        req_id = self.request_id
        
        frame = {"type": "req", "id": req_id, "method": method, "params": params}
        future = asyncio.get_event_loop().create_future()
        self.pending[req_id] = future
        
        await self.ws.send(json.dumps(frame))
        result = await asyncio.wait_for(future, timeout=30)
        del self.pending[req_id]
        return result
        
    async def list_sessions(self) -> list:
        """Get all sessions from Gateway."""
        res = await self._request("sessions.list", {})
        return res.get("payload", {}).get("sessions", [])
        
    async def send_message(self, session_key: str, message: str) -> dict:
        """Send message to a specific session."""
        return await self._request("sessions.send", {
            "sessionKey": session_key,
            "message": message
        })
        
    async def get_history(self, session_key: str, limit: int = 50) -> list:
        """Fetch message history for a session."""
        res = await self._request("sessions.history", {
            "sessionKey": session_key,
            "limit": limit
        })
        return res.get("payload", {}).get("messages", [])
```

### 7.5 Frame Translation

Synapse frames map to Gateway RPCs:

| Synapse Frame | Gateway RPC | Notes |
|---------------|-------------|-------|
| `{type:"subscribe", agentId}` | `sessions.history` | Load history on focus |
| `{type:"message", agentId, text}` | `sessions.send` | Route via session key |
| `{type:"history", agentId, limit}` | `sessions.history` | Paginated fetch |
| `{type:"status_all"}` | `sessions.list` | Aggregate all agents |

Session key derivation: `agent:{agentId}:{agentId}` (e.g., `agent:aria:aria`)

### 7.6 Status Updates

Status is derived from Gateway session state, not separate heartbeats:

- Router polls `sessions.list` every 2-5 seconds
- Extracts per-agent status (context %, active run, last message)
- Pushes aggregated status to all connected Synapse clients
- **Future:** When Gateway ships session events, switch from polling to subscription

### 7.7 Connection Resilience

- **Client disconnect** — Gateway sessions continue. Reconnect resumes subscriptions.
- **Gateway restart** — Router reconnects with exponential backoff, rebuilds state.
- **Agent "crash"** — Really means session error. Router surfaces via status channel.

### 7.8 Forward Compatibility

This architecture is designed to evolve with Moltbot Gateway:

| Current (Polling) | Future (Native Events) |
|-------------------|------------------------|
| Poll `sessions.list` every 2-5s | Subscribe to `session.status` events |
| Call `sessions.send` | Same |
| Call `sessions.history` | Same |
| No streaming support | Subscribe to `session.stream` channel |

When Gateway ships native multi-session WebSocket events, the Router becomes even thinner — just frame translation with no polling.

---

## 8. Task & Job System

### 8.1 Use Existing Agent-Queue

**Do not build a new task system.** Use Mission Control's existing `agent_queue.py`:

- **Storage:** `data/queue.json` (file-based, simple, works)
- **UI:** Mission Control Kanban (`/` route)
- **API:** FastAPI endpoints in `app.py`

### 8.2 Queue Columns (existing)

```
ideas → queued → active → review → done
              ↘ urgent (high priority)
```

### 8.3 Task Schema (existing)

```json
{
  "id": "q_20260205_001",
  "title": "Research semiconductor export restrictions",
  "description": "...",
  "column": "active",
  "complexity": "deep",
  "session_id": "agent:aria:subagent:abc123",
  "session_status": "running",
  "priority": 80,
  "tags": ["research"],
  "notes": "Progress updates appended here",
  "created_at": "2026-02-05T14:20:00Z",
  "updated_at": "2026-02-05T14:22:00Z"
}
```

### 8.4 Agent Assignment Flow

1. User moves task to agent's column (or uses `/task @aria Research X`)
2. Synapse calls `sessions_spawn(agentId, task.description)`
3. Task updated: `session_id` = spawned session, `session_status` = "running"
4. Agent works autonomously
5. On completion: `session_status` = "done", task moves to "review"

### 8.5 Integration Points

| Action | Implementation |
|--------|----------------|
| Assign task | `sessions_spawn(agentId, task)` |
| Check progress | Poll `sessions.list`, match by `session_id` |
| Cancel task | `sessions.delete(session_id)` |
| Get output | Read from `~/clawd-shared/reports/` or session history |

**No new queue infrastructure.** Synapse reads from queue.json, dispatches via Moltbot.

---

## 9. Agent Registry

### 9.1 Agent Definitions

Each agent has a static definition and runtime state:

```json
{
  "id": "aria",
  "name": "Aria",
  "role": "Research Agent",
  "description": "Deep research, literature review, fact synthesis",
  "model": "deepseek-r1-distill-qwen-32b",
  "persona": "Thorough, citation-heavy, asks clarifying questions",
  "capabilities": ["web_search", "document_analysis", "citation"],
  "memory_tier": "episodic+semantic",
  "max_context": 32768,
  "color": "#7B9EC4",
  "icon": "microscope",
  "auto_assign_domains": ["research", "analysis", "literature"]
}
```

### 9.2 Planned Agent Fleet

| Agent | Role | Domain |
|-------|------|--------|
| **Jarvis** | Principal / Orchestrator | Task decomposition, delegation, synthesis |
| **Aria** | Research | Deep research, literature review, fact synthesis |
| **Will B.** | Schedule & Calendar | Calendar management, meeting coordination, time blocking |
| **Peter** | Document & Writing | Drafting, editing, formatting, publishing |
| **Nova** | Learning & Knowledge | Study plans, spaced repetition, knowledge graph |
| **Cipher** | Code & Engineering | Code generation, debugging, architecture review |
| **Scout** | Email & Communication | Email triage, drafting responses, follow-ups |
| **Atlas** | Data & Analytics | Data analysis, visualization, reporting |
| **Sentinel** | Security & Privacy | PII scanning, data sovereignty enforcement |
| **Librarian** | Indexing & RAG | Continuous background indexing, retrieval |
| **Moltbot** | Memory & Continuity | Hierarchical memory management, consolidation |

### 9.3 Agent Resource Budget

On a 128GB unified memory system running 10–15 agents:

| Component | Memory Estimate |
|-----------|-----------------|
| Primary model (32B, quantized) | 20–24 GB |
| Secondary models (smaller specialists) | 8–16 GB |
| Agent session state (×15) | 2–5 GB |
| Vector DB + indexes | 4–8 GB |
| Redis working memory | 1–2 GB |
| OS + services | 8–10 GB |
| **Headroom** | ~60–80 GB |

Note: Not all agents run inference simultaneously. The router manages inference scheduling — typically 1–2 agents run inference at a time, others hold state in memory awaiting their turn. The GB10's unified memory architecture means GPU and CPU share the pool, avoiding the copy overhead of discrete GPU systems.

---

## 10. TELEMETRY View (Phase 2)

### 10.1 Purpose

Real-time monitoring of the DGX Spark hardware. Critical for understanding resource contention when multiple agents are active.

### 10.2 Metrics

| Metric | Source | Update Interval |
|--------|--------|-----------------|
| GPU utilization | `nvidia-smi` / NVML | 1s |
| Memory usage (unified) | NVML | 1s |
| Memory per-agent breakdown | Agent Router | 5s |
| Inference throughput (tok/s) | Model server | Per-request |
| Thermal (GPU/CPU) | NVML / `sensors` | 2s |
| Disk I/O | `iostat` | 5s |
| Network bandwidth | `nethogs` | 5s |
| Active inference queue | Agent Router | 1s |

### 10.3 Visualization

- Sparkline charts for time-series metrics (last 5 minutes)
- Memory waterfall showing per-agent allocation
- Inference queue depth with agent attribution
- Thermal status with warning thresholds

---

## 11. PIPELINE View (Phase 3 — Stretch)

### 11.1 Purpose

Visual directed acyclic graph (DAG) showing agent dependencies and data flow for complex multi-agent tasks.

### 11.2 Use Case

When a complex task is decomposed:

```
User intent: "Prepare a briefing on the semiconductor situation"
  → Jarvis decomposes:
      1. Aria: Research recent policy changes
      2. Atlas: Pull market data on NVIDIA, TSMC, Samsung
      3. Peter: Draft briefing document (depends on 1 + 2)
      4. Sentinel: Review for PII before delivery (depends on 3)
```

The PIPELINE view shows this as a live DAG with status on each node, data flowing between agents, and the ability to click into any node to see that agent's CHAT.

### 11.3 Rendering

- Nodes = agents (colored by state)
- Edges = data dependencies (animated when data flowing)
- Click node = open CHAT for that agent
- Collapse/expand sub-graphs for complex pipelines

---

## 12. Technical Stack

### 12.1 Backend (Minimal — leverage existing)

| Component | Technology | Notes |
|-----------|-----------|-------|
| API server | FastAPI (Python) | **Existing:** Mission Control `app.py` |
| WebSocket | Starlette | Built into FastAPI |
| Agent Router | Custom Python | **New:** thin layer, ~500 lines |
| Task queue | `queue.json` | **Existing:** `agent_queue.py` |
| Agent backend | Moltbot Gateway | **Existing:** all session/chat APIs |
| Model serving | Moltbot → Anthropic/Ollama | **Existing:** configured in Moltbot |
| Telemetry | NVML (Phase 2) | Add later |

**Not needed for MVP:**
- Redis (Moltbot handles state)
- PostgreSQL (use file-based storage)
- Separate synapse-api service (extend Mission Control)

### 12.2 Frontend (Simple — vanilla JS or minimal React)

| Component | Technology | Notes |
|-----------|-----------|-------|
| Framework | Vanilla JS or Preact | Keep it simple, no heavy frameworks |
| WebSocket client | Native WebSocket API | Single connection |
| State | Plain JS objects | No state library needed for single-user |
| Typography | Monospace system font | `"JetBrains Mono", "Ubuntu Mono", monospace` |
| Charts (Phase 2) | Sparkline.js or D3 | Add when needed |

### 12.3 Deployment

**Extend Mission Control** — no new services:

```
Mission Control (FastAPI)
├── / (Kanban)
├── /briefing
├── /email  
├── /queue
├── /synapse          ← NEW: Synapse UI
└── /api/synapse/ws   ← NEW: Multiplexed WebSocket
```

Synapse is a new route in Mission Control, not a separate deployment.

---

## 13. Protocol Specification

### 13.1 Connection Lifecycle

```
1. Client connects: ws://localhost:3000/api/synapse/ws  (Mission Control port)
2. Server sends:    { type: "connected", agents: [...registry] }
3. Server begins:   Status channel for all agents (automatic)
4. Client sends:    { type: "subscribe", agentId: "aria", channel: "messages" }
5. Server sends:    { type: "history", agentId: "aria", messages: [...] }
6. Server streams:  { type: "chunk", agentId: "aria", text: "..." }
```

### 13.2 Focus Switch

```
Client: { type: "unsubscribe", agentId: "aria", channel: "messages" }
Client: { type: "subscribe", agentId: "peter", channel: "messages" }
Server: { type: "history", agentId: "peter", messages: [...], cursor: "..." }
Server: [live stream begins for peter]
```

### 13.3 Message Send (from any view)

```
Client: { type: "message", agentId: "peter", payload: { text: "schedule standup" } }
Server: { type: "chunk", agentId: "peter", text: "I'll set that up..." }
```

If Peter is not the focused agent, the chunk still arrives but the client routes it to update Peter's FLEET card (unread badge + preview) rather than the CHAT stream.

### 13.4 Reconnection

```
1. Client detects disconnect
2. Exponential backoff reconnect (1s, 2s, 4s, 8s, max 30s)
3. On reconnect, client sends: { type: "reconnect", lastSeen: "<timestamp>" }
4. Server sends: Full state snapshot (all agent statuses + missed messages for subscribed agent)
5. Resume normal operation
```

### 13.5 Error Frames

```json
{
  "type": "error",
  "agentId": "aria",
  "payload": {
    "code": "AGENT_CRASHED",
    "message": "Aria encountered an unrecoverable error",
    "recoverable": true,
    "action": "restart"
  }
}
```

---

## 14. UI/UX Specification

### 14.1 Color Palette

```
Background:           #2D2030  (warm dark plum)
Surface:              #3A2D3D  (elevated surface)
Border:               #4A3D4D  (subtle separation)
Text primary:         #E0D0C0  (warm off-white)
Text secondary:       #A090A0  (muted)
User message bg:      #3D3530  (warm cream tint)
Accent:               #7B9EC4  (cool blue — links, focus)
Status idle:          #6A6A6A  (dim gray)
Status working:       #7BCF7B  (green pulse)
Status waiting:       #CFB347  (amber)
Status error:         #CF4747  (red)
Status sleeping:      #7B6A9E  (purple dim)
```

### 14.2 Typography

```css
font-family: "Ubuntu Mono", "DejaVu Sans Mono", "Cascadia Code", "Fira Code", monospace;
font-size: 14px;
line-height: 1.55;
/* Target: 85-95 characters per line at this size */
```

### 14.3 Layout Rules

- No decorative padding, no card borders in CHAT view
- User input differentiated by subtle background tint (not badges or labels)
- Tables rendered with box-drawing characters where possible
- Timestamps subdued (`color: var(--text-secondary)`)
- Streaming text appears as raw token append — no skeleton loaders, no typing indicators
- Agent status dots are the only non-text visual elements

### 14.4 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `⌘K` or `/` | Focus command bar |
| `Esc` | Dismiss command bar / return to FLEET |
| `1–4` | Switch views (FLEET, CHAT, TELEMETRY, PIPELINE) |
| `Tab` | Cycle through agents in FLEET |
| `Enter` | Open CHAT for selected agent |
| `⌘↑` / `⌘↓` | Navigate chat history |
| `⌘Shift+R` | Reconnect WebSocket |

---

## 15. Phased Delivery Plan

### Phase 1: Synapse MVP (5 Epochs, 3 Sprints)

| Epoch | Focus | Deliverable | Sprint | Status |
|-------|-------|-------------|--------|--------|
| 1.1 | Backend | GatewayClient, WebSocket endpoint, frame handlers | Sprint 1 | ✅ Done |
| 1.2 | FLEET | Agent card grid, live status from sessions.list | Sprint 1 | ✅ Done |
| 1.3 | CHAT | Message routing via sessions.send, history via sessions.history | Sprint 2 | 🔄 Current |
| 1.4 | Command Bar | `@agent` routing, `/command` handling, autocomplete | Sprint 3 | ⏳ Pending |
| 1.5 | Polish | Error handling, reconnection, UX edge cases | Sprint 3 | ⏳ Pending |

#### Sprint 1 (Complete)
- [x] WebSocket endpoint at `/api/synapse/ws`
- [x] Frame protocol: subscribe, unsubscribe, message, history, status_all
- [x] Status polling from `data/agent_status.json` (cron-updated)
- [x] FLEET view with agent cards, status dots, context bars
- [x] Click-to-focus navigation

**Exit criteria:** FLEET view renders live agent cards. ✅

#### Sprint 2 (Current)
**Goal:** Full chat capability via Gateway integration

| Task | Implementation | Status |
|------|----------------|--------|
| GatewayClient class | Single persistent WS to `ws://localhost:18789` | ⏳ |
| Connect + auth | Send `connect` frame with token on startup | ⏳ |
| sessions.list polling | Replace file-based status with live Gateway data | ⏳ |
| sessions.send routing | Translate message frames → Gateway RPC | ⏳ |
| sessions.history fetch | Load history on agent focus/subscribe | ⏳ |
| Streaming display | Render chunks as they arrive (no typing indicator) | ⏳ |
| History scrollback | Paginated load with cursor-based scroll | ⏳ |

**Exit criteria:** Can hold conversation with focused agent, full history, live status from Gateway.

#### Sprint 3 (Pending)
- [ ] Command bar with `@agent` prefix routing
- [ ] `/command` system commands
- [ ] Agent name autocomplete
- [ ] Reconnection with exponential backoff
- [ ] Error frames and user feedback
- [ ] Cross-agent messaging from any view

**Exit criteria:** Can message any agent from any view. Graceful reconnection. Phase 1 complete.

### Phase 2: Telemetry (2 Epochs, 1 Sprint)

| Epoch | Focus | Deliverable |
|-------|-------|-------------|
| 2.1 | Metrics Backend | NVML integration, per-agent memory tracking, metrics WebSocket channel |
| 2.2 | Telemetry View | Sparkline dashboard, memory waterfall, inference queue |

### Phase 3: Pipeline (3 Epochs, 1–2 Sprints, Stretch)

| Epoch | Focus | Deliverable |
|-------|-------|-------------|
| 3.1 | Task DAG Backend | Dependency graph, task decomposition API |
| 3.2 | Pipeline View | Interactive DAG rendering, live status on nodes |
| 3.3 | Auto-Orchestration | Jarvis-driven decomposition → automatic pipeline generation |

Each sprint = 1–2 focused build sessions.

### Architecture Decision Record: Gateway Integration

**Date:** 2026-02-06  
**Decision:** Use Moltbot Gateway WebSocket RPC instead of custom transport

**Context:**
- OpenClaw/Moltbot Gateway already provides `sessions.list`, `sessions.send`, `sessions.history` RPCs
- Building custom session transport duplicates Gateway functionality
- Gateway will likely ship native multi-session events in future releases

**Decision:**
1. Agent Router maintains ONE WebSocket to Gateway (not per-agent connections)
2. Synapse frames translate to Gateway RPCs
3. Status derived from `sessions.list` polling (2-5s), not custom heartbeats
4. Messages routed via `sessions.send`, not custom transport

**Consequences:**
- ✅ No session state duplication
- ✅ Forward compatible with Gateway evolution
- ✅ Simpler Router (~300 lines vs ~800+)
- ⚠️ Polling latency for status (acceptable at 2-5s)
- ⚠️ No streaming until Gateway exposes stream subscription

---

## 16. Success Metrics

| Metric | Target |
|--------|--------|
| WebSocket latency (frame round-trip) | < 50ms local |
| Status update cadence (working agents) | 2s |
| Focus switch time (agent swap in CHAT) | < 200ms (cached), < 500ms (fetch) |
| History load (100 messages) | < 300ms |
| Streaming first-token visible | < 100ms after inference starts |
| Reconnection (from disconnect to live) | < 3s |
| Concurrent agent sessions (memory) | 15 agents, < 80GB total |
| Scrollback depth without perf degradation | 10,000+ messages |

---

## 17. Open Questions

1. **Inference scheduling** — Moltbot handles this. Focused agent gets priority naturally (user is waiting). Background agents queue behind.

2. **Agent-to-agent communication** — Use `~/clawd-shared/` for handoffs. Agent A writes to `reports/`, Agent B reads. Simple file-based coordination.

3. **Multi-user** — **Single-user for MVP.** Multi-client (phone + desktop for same user) is fine — subscription state is per-connection.

4. **Persistent task board** — Use existing Kanban (`/` route). FLEET shows agent status, Kanban shows task status. Don't duplicate.

5. **Voice integration** — Defer to Phase 2+. Current voice chat routes to Jarvis. Could add `@agent` prefix to voice commands later.

6. **Memory visibility** — Defer. Nice-to-have "brain view" but not MVP.

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Synapse** | The personal AI operating system AND its multi-agent command interface. |
| **Fleet** | The collection of all active agents. |
| **Agent** | A specialized AI instance with its own persona, memory, and capabilities. |
| **Frame** | A single WebSocket message conforming to the Synapse protocol. |
| **Focus** | The agent currently subscribed to on the message channel (1 at a time). |
| **Principal** | The orchestrator agent (Jarvis) that decomposes tasks and delegates. |
| **Librarian** | The background indexing agent that maintains RAG indexes. |
| **Context budget** | Percentage of an agent's context window currently consumed. |
| **Checkpoint** | Serialized agent state for crash recovery and persistence. |
| **Intent layer** | The abstraction where user goals are translated into agent actions. |
| **Data sovereignty** | PII never leaves the local DGX Spark hardware. |
| **Glass Box** | Design principle: all agent operations are visible and inspectable. |

## Appendix B: Wire Protocol Examples

### Full session transcript

```
// 1. Connect
→ WS OPEN ws://localhost:3000/api/synapse/ws  (Mission Control)
← { "type": "connected", "agents": ["jarvis","aria","willb","peter","nova","cipher","scout","atlas","sentinel","librarian","moltbot"], "ts": "2026-02-05T14:00:00Z" }

// 2. Status stream begins automatically
← { "type": "status", "agentId": "jarvis", "payload": { "state": "idle", "task": null, "ctx": 0.02 }, "ts": "..." }
← { "type": "status", "agentId": "aria", "payload": { "state": "working", "task": "Research: AI regulation EU", "ctx": 0.45 }, "ts": "..." }
← { "type": "status", "agentId": "cipher", "payload": { "state": "working", "task": "Refactor auth module", "ctx": 0.31 }, "ts": "..." }
...

// 3. User focuses on Aria
→ { "type": "subscribe", "agentId": "aria", "channel": "messages" }
← { "type": "history", "agentId": "aria", "payload": { "messages": [...last 100...], "cursor": "msg_0098" } }

// 4. User sends message
→ { "type": "message", "agentId": "aria", "payload": { "text": "Focus specifically on chip export controls to China" } }
← { "type": "chunk", "agentId": "aria", "payload": { "text": "Narrowing", "done": false } }
← { "type": "chunk", "agentId": "aria", "payload": { "text": " my research to", "done": false } }
← { "type": "chunk", "agentId": "aria", "payload": { "text": " China-specific controls...", "done": true } }

// 5. Meanwhile, status updates keep flowing
← { "type": "status", "agentId": "cipher", "payload": { "state": "working", "task": "Refactor auth module", "ctx": 0.38 }, "ts": "..." }

// 6. User messages Peter from command bar (while focused on Aria)
→ { "type": "message", "agentId": "peter", "payload": { "text": "Draft an executive summary from Aria's research when she's done" } }
← { "type": "chunk", "agentId": "peter", "payload": { "text": "Got it — I'll watch for Aria's output and draft the summary.", "done": true } }
// ^ Client routes this to Peter's FLEET card (unread badge), not CHAT view

// 7. Switch focus to Peter
→ { "type": "unsubscribe", "agentId": "aria", "channel": "messages" }
→ { "type": "subscribe", "agentId": "peter", "channel": "messages" }
← { "type": "history", "agentId": "peter", "payload": { "messages": [...], "cursor": "..." } }
```
