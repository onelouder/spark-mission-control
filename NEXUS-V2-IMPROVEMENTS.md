# Nexus v2 Improvements Task

## Files to Modify
- `templates/nexus-v2.html` — Frontend (1606 lines, single-file HTML/CSS/JS)
- `agent_router.py` — Backend WebSocket handler

## Feature 1: Model Selector per Pane

### Backend (agent_router.py)
- Add `set_model` frame type handler in `_handle_frame()` (around line 968):
  ```python
  elif frame_type == "set_model":
      return await self._handle_set_model(client_id, agent_id, payload)
  ```
- Add `_handle_set_model` method that calls existing `self.set_agent_model(agent_id, model)`
- After success, broadcast updated status to all clients
- Also add Opus 4.6 to VALID_MODELS and MODEL_FULL_NAMES:
  ```python
  VALID_MODELS = ("opus", "sonnet", "opus-4-6", "claude-opus-4-5", "claude-opus-4-6", "claude-sonnet-4-20250514", "claude-sonnet-4-5")
  MODEL_FULL_NAMES = {
      "opus": "anthropic/claude-opus-4-5",
      "opus-4-6": "anthropic/claude-opus-4-6",
      "sonnet": "anthropic/claude-sonnet-4-20250514",
      ...
  }
  ```

### Frontend (nexus-v2.html)
- Add a model dropdown in each pane header (next to agent name)
- Options: Sonnet, Opus 4.5, Opus 4.6
- On change, send WS frame: `{ type: "set_model", agentId, payload: { model: "opus-4-6" } }`
- Show current model as a badge in the pane header
- Style: small dropdown matching IDE-noir palette, no emoji

## Feature 2: Token Counter per Pane

### Backend
- Agent status already includes context usage info. Check what `status_all` and `status` frames contain.
- If not present, add token usage from OpenClaw session_status to the agent status payload:
  - `contextUsed` (tokens used)
  - `contextMax` (context window)
  - `contextPercent` (usage %)

### Frontend
- Add a token usage bar in each pane header or footer
- Format: "45K / 200K (22%)" with color coding:
  - Green: < 50%
  - Yellow: 50-75%
  - Orange: 75-90%
  - Red: > 90%
- Update on every `status` frame

## Feature 3: Other Improvements
- Add "Reset Session" button to pane header (already has WS `reset` handler)
- Show agent org color as accent on pane border (data already in agent registry)

## Design Constraints
- IDE-noir aesthetic (dark theme, monospace, no emoji in UI)
- Dense, information-rich — no wasted space
- Jason is the sole user — optimize for power user
- Keep it a single HTML file (no build step)
- Use Tailwind CDN only for utilities, or inline styles only
