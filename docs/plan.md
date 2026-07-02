# Ether-Voice Integration Contract Plan

Date: 2026-06-12

## Goal

Build Ether-Voice integration as a voice transport for Synapse, not as a voice agent.

The intended path is:

```text
Browser mic/audio
  -> Ether-Voice STT and turn detection
  -> Mission Control voice bridge
  -> selected Synapse pane session
  -> OpenClaw chat.send
  -> selected agent reply text
  -> Mission Control voice bridge
  -> Ether-Voice TTS playback
```

Ether-Voice owns audio capture/playback behavior. Mission Control owns routing. OpenClaw owns agent identity, history, memory, model selection, and response generation.

## Non-Goals

Do not build or keep these behaviors in the voice path:

- No Ether-Voice LLM selection.
- No Ether-Voice prompt, system prompt, persona, memory, or workspace context.
- No standalone voice-agent OpenClaw session such as `agent:jarvis:voice`.
- No agent selection inside Ether-Voice.
- No transcript routing based on stale URL query state.
- No hidden voice conversation history separate from Synapse.

Voice should feel like speaking into the active Synapse chat pane. Anything said by voice must land in that pane's visible history and use that pane's selected agent/session continuity.

## Ownership Boundary

### Ether-Voice Owns

- Browser microphone and speaker media path.
- WebRTC/client audio setup where needed.
- Wake/listen/speaking/connected state.
- VAD and end-of-turn detection.
- STT transcript production.
- TTS synthesis and playback.
- Barge-in and audio disconnect commands.

### Mission Control Owns

- The voice session binding.
- Mapping each voice turn to the active Synapse pane.
- Calling OpenClaw gateway `chat.send` for the selected pane session.
- Waiting for the corresponding assistant final text.
- Sending `say` and `end_of_turn` messages back to Ether-Voice.
- Presenting voice state in the Synapse pane UI.

### OpenClaw Owns

- Agent identity/persona.
- Session history and transcript persistence.
- Model routing and context management.
- Memory/tool policy for the selected agent/session.
- Assistant response generation.

## Voice Session Binding

A Mission Control voice session must be bound to a concrete Synapse pane, not just an agent name.

Required binding fields:

```json
{
  "voiceSessionId": "voice_...",
  "clientId": "synapse browser client id",
  "paneId": "synapse pane id",
  "agentId": "willb",
  "sessionKey": "agent:willb:main"
}
```

Rules:

- `clientId + paneId` identifies the active browser chat pane.
- `agentId + sessionKey` identifies the OpenClaw target.
- A voice session must never infer its target from a stale Ether-Voice page URL.
- Starting voice for Will must not reuse or mutate a Jarvis voice session.
- Starting voice in one browser client must not steal another browser client's voice bridge.
- If the pane changes agent or session, the existing voice session must be stopped or rebound explicitly.

## Protocol Contract

### Start Voice

Browser to Mission Control:

```http
POST /api/synapse/voice/sessions
```

Payload:

```json
{
  "clientId": "client_...",
  "paneId": "0",
  "agentId": "willb",
  "sessionKey": "agent:willb:main"
}
```

Response:

```json
{
  "session": {
    "id": "voice_...",
    "clientId": "client_...",
    "paneId": "0",
    "agentId": "willb",
    "sessionKey": "agent:willb:main",
    "voice": "af_heart",
    "state": "starting",
    "publicUrl": "https://voice.example.test/...?agent=willb"
  }
}
```

Notes:

- `voice` is the TTS voice only.
- There should be no `model` field in the durable contract. If retained temporarily for compatibility, it must not affect response generation.
- `publicUrl` may include `agent` for Ether-Voice audio-side selection, but Mission Control remains authoritative for routing.

### Ether-Voice Hello

Mission Control to Ether-Voice:

```json
{
  "type": "hello",
  "seq": 1,
  "protocol_version": "1.0",
  "agent_name": "willb",
  "auth": "...",
  "voice": "af_heart",
  "wake_phrases": ["will"],
  "capabilities": {
    "barge_in": true,
    "text": true,
    "audio": false
  }
}
```

Interpretation:

- `agent_name` is an appliance-side channel label only.
- It must not cause Ether-Voice to choose an LLM, prompt, memory, or OpenClaw session.

### STT Turn

Ether-Voice to Mission Control:

```json
{
  "type": "user_turn",
  "turn_id": "turn_...",
  "text": "What is the status of the build?"
}
```

Mission Control behavior:

1. Look up the stored `voiceSessionId -> clientId + paneId + agentId + sessionKey` binding.
2. Emit the text into the visible Synapse pane as a user/voice message.
3. Call OpenClaw `chat.send` with that exact `sessionKey`.
4. Track the returned `runId` for the final assistant text.

OpenClaw call shape:

```json
{
  "sessionKey": "agent:willb:main",
  "message": "What is the status of the build?",
  "idempotencyKey": "turn_..."
}
```

Optional future optimization:

```json
{
  "toolsAllow": ["memory_search", "memory_get", "session_status"]
}
```

This is only a per-turn OpenClaw prompt/tool policy hint. It must not create a separate voice agent or voice memory system.

### Assistant Speech

Mission Control to Ether-Voice:

```json
{
  "type": "say",
  "seq": 2,
  "session_id": "ether_voice_session_id",
  "turn_id": "turn_...",
  "text": "The build passed and Mission Control is running on port 3000."
}
```

Then:

```json
{
  "type": "end_of_turn",
  "seq": 3,
  "session_id": "ether_voice_session_id",
  "turn_id": "turn_..."
}
```

Rules:

- Speak only assistant text from the selected Synapse/OpenClaw run.
- Do not speak tool JSON, diagnostics, hidden reasoning, or progress-only events.
- If there is no final speakable text, end the turn and surface the issue in the Synapse voice status.

### Barge-In

Ether-Voice to Mission Control:

```json
{
  "type": "barge_in",
  "turn_id": "turn_..."
}
```

Mission Control behavior:

- Cancel the active voice turn task.
- Abort the matching OpenClaw run/session using the stored `sessionKey` and known `runId` where available.
- Send `end_of_turn` if needed.
- Return to listening state.

## UI Contract

Synapse pane voice control should be compact:

- `Talk` starts voice for that pane.
- A status light indicates `connecting`, `connected/listening`, `speaking`, or `error`.
- `End` stops the pane-bound voice session.
- No required popup workflow.
- No large static Ether-Voice page inside the chat pane.
- The embedded/client audio surface, if still needed, must be compact, auto-connect, and not steal the chat workflow.

Visible transcript behavior:

- Voice user turns appear in the same Synapse pane history.
- Assistant replies appear in the same Synapse pane history.
- Reloading or revisiting the session shows the conversation in normal Synapse history.

## Prompt and Context Policy

Correctness comes first: voice must route to the selected Synapse session.

After routing is correct, reduce voice-turn bloat by adding an OpenClaw interactive profile for voice-originated turns:

- Keep selected agent identity and real session continuity.
- Do not add any voice-specific system prompt.
- Do not add any Ether-Voice memory or bootstrap.
- Prefer a narrow per-turn tool allowlist when supported.
- Avoid advertising broad tool schemas for casual spoken turns.
- Preserve memory lookup if it is part of the selected agent's normal behavior.

This policy belongs in OpenClaw/Synapse turn execution, not Ether-Voice.

## Build Plan

### Phase 1: Lock Down Routing

1. Add `paneId` and explicit `sessionKey` to `POST /api/synapse/voice/sessions`.
2. Store voice sessions by `clientId + paneId + agentId + sessionKey`.
3. Stop reusing live sessions by agent alone.
4. Always overwrite stale `agent` query params when constructing Ether-Voice URLs.
5. Reject or stop voice if the pane's current agent/session no longer matches the stored binding.

Tests:

- Starting Will voice produces `sessionKey=agent:willb:main`.
- Starting Will voice does not reuse Jarvis voice state.
- Two browser clients can hold separate voice sessions for the same agent.
- A configured `ETHER_VOICE_PUBLIC_URL` with `agent=jarvis` is overwritten to `agent=willb` when Will starts voice.

### Phase 2: Make STT a Synapse Turn

1. Change `VoiceBridgeSession._stream_openclaw_turn` to route by stored binding.
2. Ensure `HUB.send_voice_message` accepts and uses the explicit `sessionKey`.
3. Emit a visible `voice_user` frame into only the bound pane/client.
4. Call OpenClaw `chat.send` against the bound session key.
5. Track `turnId -> runId -> final assistant text`.

Tests:

- A Will voice transcript calls `chat.send` with `agent:willb:main`.
- A Jarvis voice transcript calls `chat.send` with `agent:jarvis:main`.
- Concurrent Will and Jarvis voice sessions do not cross-deliver transcripts or replies.
- The visible Synapse pane receives the voice transcript before the assistant final.

### Phase 3: Remove Voice Agent Semantics

1. Remove `model` from the durable voice API response or mark it deprecated and inert.
2. Remove `ETHER_VOICE_DEFAULT_MODEL` from the active response path.
3. Remove any code that creates `agent:<id>:voice` sessions.
4. Remove UI copy that implies a separate voice agent or model.
5. Keep only TTS voice and wake/listen configuration in voice settings.

Tests:

- Voice start does not require a voice model.
- Voice transcript path does not read or pass a voice model to OpenClaw.
- Legacy `agent:<id>:voice` sessions are ignored by the current voice bridge.

### Phase 4: Speak Final Assistant Text Only

1. Ensure final assistant text extraction ignores hidden reasoning and tool/progress events.
2. Send exactly one `say` per final assistant reply unless the assistant intentionally emits no speakable text.
3. Always send `end_of_turn` after final, abort, or error.
4. Surface no-speakable-text as a pane voice status error, not a silent hang.

Tests:

- Assistant final text is sent to Ether-Voice as `say`.
- Tool/progress-only output is not spoken.
- Empty final produces `end_of_turn` and a visible status message.
- Barge-in cancels the active turn and returns to listening.

### Phase 5: Trim Prompt Bloat Without Breaking Session Continuity

1. Add or use OpenClaw per-turn `toolsAllow` support for `chat.send`.
2. For voice-originated turns, pass a narrow allowlist such as `memory_search`, `memory_get`, and `session_status`.
3. Verify this strips broad skill/tool catalog exposure while preserving the selected session history.
4. Do not move prompt policy into Ether-Voice.

Tests:

- Voice `chat.send` forwards `toolsAllow` into OpenClaw reply options.
- Prompt/report diagnostics show no voice-specific prompt or workspace bootstrap from Ether-Voice.
- Token/context indicators remain stable across short voice turns.
- Typed Synapse chat keeps its normal policy unless explicitly configured otherwise.

### Phase 6: End-to-End Smoke Tests

Manual smoke path:

1. Open Synapse.
2. Select Jarvis in one pane and Will in another.
3. Click `Talk` in Will's pane.
4. Speak a short turn.
5. Confirm transcript appears only in Will's pane.
6. Confirm OpenClaw session key is `agent:willb:main`.
7. Confirm TTS speaks Will's assistant reply.
8. Click `End`.
9. Repeat for Jarvis.

Automated checks where practical:

- FastAPI voice API tests for session binding and lifecycle.
- Synapse hub tests for correct session key and client delivery.
- Browser helper tests or Playwright smoke for Talk/End/status behavior.
- OpenClaw gateway regression for `toolsAllow` forwarding.

## Acceptance Criteria

The integration is complete when:

- A voice transcript always enters the selected Synapse pane's active session.
- Will voice can never accidentally send text to Jarvis.
- Ether-Voice has no response-generation model, prompt, memory, or session history role.
- The full conversation is visible in Synapse history.
- `Talk` and `End` are the only required user actions in Synapse.
- Small screens and Android do not require a popup/static-button workflow.
- Voice turn latency is not dominated by an extra voice-agent prompt or duplicate context path.
