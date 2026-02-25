
PRODUCT REQUIREMENTS DOCUMENT
Nexus Multi-Agent Chat Interface
Wiring to Openclaw / Clawdbot Gateway on NVIDIA Spark DGX
February 2026  |  v1.0  |  Jason Wells / Novvi
QUICK REFERENCE
Target hardware: NVIDIA Spark DGX (GB10, 128GB LPDDR5x)
Gateway: Clawdbot (Openclaw) on ws://ether-spark:18789
Frontend: nexus.html (single-file, zero-dependency)
Integration effort: ~2 hours (adapter code + config)
 
1. System Architecture Overview
Nexus is a single-file HTML interface that connects to multiple AI agents simultaneously via WebSockets. The Clawdbot (Openclaw) Gateway running on the DGX Spark serves as the backend control plane for all agents.
1.1 Current Architecture (MoltBot Gateway)
Component	Details
Gateway	MoltBot / Clawdbot Gateway, ws://ether-spark:18789
Auth	Token-based: gateway.auth.token must match gateway.remote.token in ~/.clawdbot/clawdbot.json
Agents	10-15 Openclaw agents, each with isolated sessions and independent context
WebChat	Current: 1 browser window = 1 agent session via ?agent=<name>&token=<token>
Inference	Local Ollama (qwen3-next:80b, deepseek-r1:70b, etc.) + Anthropic Claude API
1.2 Target Architecture (Nexus)
Nexus replaces N separate browser windows with a single stacked-panel interface that manages N independent WebSocket connections:
Browser (nexus.html)
  |
  +-- WS 1 --> ws://ether-spark:18789/api/chat/ws?agent=jarvis&token=XXX
  +-- WS 2 --> ws://ether-spark:18789/api/chat/ws?agent=willb&token=XXX
  +-- WS 3 --> ws://ether-spark:18789/api/chat/ws?agent=aria&token=XXX
  +-- WS N --> ws://ether-spark:18789/api/chat/ws?agent=<name>&token=XXX
  |
  Each WS = independent session, same as current single-agent webchat
No gateway modifications required. Nexus connects to the same endpoints that the existing single-agent webchat uses.
 
2. Clawdbot Gateway Protocol Specification
The Nexus adapter must speak the Clawdbot Gateway WebSocket protocol. The gateway exposes two relevant interfaces:
2.1 WebSocket Chat Endpoint
Property	Value
URL Pattern	ws://ether-spark:18789/api/chat/ws?agent=<agent_id>&token=<auth_token>
Auth	Token passed as query parameter; must match gateway.auth.token in clawdbot.json
Session	Bound at connection time. One WS = one agent session. Session persists until disconnect.
Bind Mode	Loopback (127.0.0.1) or LAN (0.0.0.0) per gateway.bind config. LAN required for cross-device access.
2.2 OpenAI-Compatible REST API (Alternative)
The gateway also exposes an OpenAI-compatible SSE endpoint. This can serve as a fallback or alternative to WebSocket for agents that need stateless request/response:
Property	Value
Endpoint	POST /v1/chat/completions
Auth Header	Authorization: Bearer <GATEWAY_TOKEN>
Agent Select	x-openclaw-agent-id: <agent_id>  (header) or model: "openclaw:<agent_id>"  (body)
Streaming	SSE stream: data: {"choices":[{"delta":{"content":"..."}}]}  then  data: [DONE]
2.3 Message Protocol (WebSocket)
Based on the current MoltBot webchat implementation, the WebSocket protocol uses the following message formats. These are the adaptation points in nexus.html:
Outgoing (browser to gateway): Plain text string or JSON envelope. Test plain text first.
// Option A: Plain text (try first)
ws.send("Search patents for narrow MWD PAO claims");

// Option B: JSON envelope (if gateway requires it)
ws.send(JSON.stringify({ type: "message", content: "Search patents..." }));
Incoming (gateway to browser): JSON or plain text. The adapter should handle both:
// Gateway may send any of these patterns:

// 1. Plain text (complete response)
"Here are the search results..."

// 2. Streaming chunks
{"type": "chunk", "token": "Here", "done": false}
{"type": "chunk", "token": " are", "done": false}
{"type": "chunk", "token": "...", "done": true}

// 3. Complete message as JSON
{"content": "Here are the search results..."}

// 4. System/status messages
{"type": "system", "message": "Agent initialized"}
 
3. Nexus Adaptation Guide
The nexus.html file contains two clearly marked adaptation points (search for >>> ADAPT <<<). All other code is gateway-agnostic.
3.1 Adaptation Point 1: handleIncoming()
Location: handleIncoming() function. This parses messages received from the gateway WebSocket.
Action required: Test the current implementation against your gateway. It already handles plain text, JSON chunks, and complete messages. If your gateway uses a different envelope, modify the parsing logic here.
The current implementation tries JSON.parse first, falls back to plain text. Streaming is handled by buffering chunks until done=true, then finalizing the message. This matches the SSE pattern from the /v1/chat/completions endpoint.
3.2 Adaptation Point 2: sendMessage()
Location: sendMessage() function. This formats outgoing user messages.
Action required: Currently sends plain text via ws.send(text). If the Clawdbot WebSocket endpoint requires a JSON envelope, switch to the commented-out JSON.stringify version.
3.3 Agent Registration
Each agent needs to be registered in Nexus with its name and full WebSocket URL. The URL encodes the agent identity and auth token:
ws://ether-spark:18789/api/chat/ws?agent=jarvis&token=1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c
This URL is identical to the one shown in the MoltBot Dashboard chat interface (screenshot: "Option 1: Webchat"). Users can copy-paste the URL directly from the dashboard into Nexus.
Agent configurations persist in localStorage and auto-load on page refresh.
 
4. Agent Configuration Reference
Configure each Openclaw agent in Nexus using the + Agent button or /add command. Below is an example fleet configuration:
Agent	Role	Model	WebSocket URL
Jarvis	Research	qwen3-next:80b-a3b	ws://ether-spark:18789/api/chat/ws?agent=jarvis&token=<TOKEN>
Will B.	Coder	codellama-34b / Claude	ws://...?agent=willb&token=<TOKEN>
Aria	Writer	qwen3-next:80b-a3b	ws://...?agent=aria&token=<TOKEN>
Scout	Research	llama3.1:8b	ws://...?agent=scout&token=<TOKEN>
Cipher	Reviewer	deepseek-r1:70b	ws://...?agent=cipher&token=<TOKEN>
Forge	Coder	codellama-34b	ws://...?agent=forge&token=<TOKEN>
Prism	Analyst	qwen3-next:80b-a3b	ws://...?agent=prism&token=<TOKEN>
All agents share the same gateway token (from ~/.clawdbot/clawdbot.json: gateway.auth.token). The agent parameter determines which Openclaw agent handles the session.
5. Nexus UI Feature Specification
5.1 Stacked Panel Layout
•	Each agent gets a collapsible panel in a vertical stack
•	Collapsed panels show: status dot (green/yellow/red/gray) + agent name + role badge + last message preview + message count
•	Active panel expands to fill available space with full chat thread, toolbar, and input bar
•	Click any collapsed header to activate that panel (others collapse)
•	Unread indicator: cyan left border on collapsed panels with new messages
5.2 Commands and Shortcuts
Command / Key	Action
@agentname <msg>	Send to specific agent and switch focus to that panel
/broadcast <msg>	Send message to all connected agents simultaneously
/connect	Connect current agent WebSocket
/disconnect	Disconnect current agent
/clear	Clear current agent chat history
/export	Download chat as .txt file
Ctrl+]  /  Ctrl+[	Cycle to next/previous agent panel
Ctrl+K	Focus input bar of active panel
5.3 Top Bar Telemetry
•	Connected/total agent count with color coding (red if 0 connected)
•	Hardware identifier (SPARK DGX / GB10)
•	Global actions: connect all, disconnect all, add agent, broadcast, save/load config
 
6. Implementation Tasks
Ordered by priority. Each task includes the specific code location in nexus.html.
#	Task	Details	Location	Est.
1	Deploy nexus.html	Copy nexus.html to DGX Spark. Serve via python -m http.server 8000 or Nginx. Open in browser.	File system	5 min
2	Test WS connect	Add one agent (Jarvis) with full ws:// URL from MoltBot dashboard. Click connect. Verify handshake.	UI: + agent	10 min
3	Adapt incoming	If JSON parse fails or messages display wrong, modify handleIncoming() to match gateway output format.	handleIncoming()	15 min
4	Adapt outgoing	If agent does not receive messages, switch sendMessage() from plain text to JSON envelope.	sendMessage()	5 min
5	Add all agents	Register remaining 9-14 agents with their WebSocket URLs. Test each. Click save to persist.	UI: + agent	15 min
6	Streaming tune	If gateway streams tokens, verify chunk buffering works. Adjust done/finished/complete flags if needed.	handleIncoming()	15 min
7	LAN bind	If accessing from another device: set gateway.bind to "lan" in clawdbot.json, restart clawdbot.	clawdbot.json	5 min
Total estimated integration time: 60-90 minutes for a working multi-agent setup.
7. Configuration Reference
7.1 Clawdbot Gateway Config
File: ~/.clawdbot/clawdbot.json
{
  "gateway": {
    "port": 18789,
    "bind": "loopback",        // Change to "lan" for cross-device access
    "auth": {
      "token": "<your-token>"   // Server-side validation token
    },
    "remote": {
      "token": "<your-token>"   // Must match auth.token
    }
  }
}
7.2 Nexus localStorage Schema
Key: nexus_config. Nexus persists agent configurations in browser localStorage:
[
  {
    "name": "Jarvis",
    "url": "ws://ether-spark:18789/api/chat/ws?agent=jarvis&token=<TOKEN>",
    "role": "research"
  },
  { "name": "Will B.", "url": "ws://...", "role": "coder" }
]
 
8. Feature Roadmap
The Nexus architecture is intentionally modular. Future phases add functionality without rewriting the core:
Phase	Feature	Description	Complexity
0	Core chat	Stacked panels, multi-WS, @routing, broadcast, save/load. This PRD.	Done
1	Telemetry sidebar	Poll /api/health or gateway status endpoint. Show per-agent memory, tok/s, model loaded.	Low
1	History persistence	Save chat history to localStorage or IndexedDB. Survive page refresh.	Low
2	Pipeline DAG view	Visual flow chart showing agent dependencies (Scout output triggers Jarvis). Canvas or SVG.	Medium
2	Cron / scheduler	Schedule agents for periodic tasks. Visual crontab UI.	Medium
2	SSE fallback	Use /v1/chat/completions SSE endpoint as alternative to WebSocket for stateless agents.	Low
3	Multiplexed WS	Single WebSocket with frame-tagged protocol. Requires gateway-side router. Only if 15 connections cause issues.	High
3	Full dashboard	Memory heatmap, KV cache manager, model swapper, FP4/FP8 toggle. The original Nexus v1 concept.	High

9. Known Constraints and Mitigations
Constraint	Impact	Mitigation
1 WS per agent	15 open WebSocket connections from browser	Browsers handle 50+ WS easily. Only matters if gateway enforces connection limits.
No session resume	Page refresh loses live WS connections (history preserved via save)	Auto-reconnect on page load (Phase 1). Auto-load saved config already works.
Loopback bind	Can only access Nexus from DGX Spark browser if gateway bind = loopback	Set bind to "lan" in clawdbot.json for cross-device. Token auth still enforced.
128GB memory	Running 10-15 agents may saturate unified memory pool	Use mix of large (70B) and small (8B) models. Not all agents need to be loaded simultaneously.
Token in URL	Auth token visible in localStorage and browser devtools	Acceptable for local/LAN use. For remote: use Tailscale Serve + HTTPS.

