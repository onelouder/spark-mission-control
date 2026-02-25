# Ideas: Reducing Cognitive Load & Context Switching Friction

**Date:** 2026-01-29  
**Status:** Brainstorm for Jason's review

---

## Current State

Mission Control now has:
- Gmail + Google Calendar connected (jwells@gmail.com)
- Context system with 4 domains (Novvi, Startup, Academic, Personal)
- Toggle filters in the nav bar
- Unified email/calendar aggregation

---

## The Core Problem

**Context switching is expensive.** Every time you shift from "Novvi legal matter" to "personal email" to "IEEE review", there's cognitive overhead:
- Mental model reload
- Priority recalibration  
- Attention residue from the previous context

The goal isn't just filtering emails — it's **protecting focus** and **reducing decision fatigue**.

---

## Ideas: Cognitive Load Reduction

### 1. **Context Modes, Not Just Filters**

Instead of just filtering what you see, **context modes** could adjust the entire interface:

```
┌─────────────────────────────────────────────────────────┐
│  🏢 NOVVI MODE                              [switch] ▾  │
├─────────────────────────────────────────────────────────┤
│  Only Novvi emails, calendar, tasks                     │
│  Contact tiers weighted for Novvi people                │
│  "Decisions" = Novvi-relevant decisions only            │
│  Quick actions: "Draft to Eduardo", "Check legal inbox" │
└─────────────────────────────────────────────────────────┘
```

When you're in Novvi mode:
- Everything else is **hidden**, not just dimmed
- Keyboard shortcuts change (e.g., `n` = new Novvi email)
- The color scheme subtly shifts (blue tint for Novvi, amber for Personal)
- Tasks kanban filters to Novvi-tagged items

**Why:** Full immersion reduces "what about that other thing?" anxiety.

---

### 2. **Time-Based Context Scheduling**

Most people have natural rhythms:
- Morning: High-priority work (Novvi)
- Lunch: Personal catch-up
- Afternoon: Deep work or meetings
- Evening: Academic/side projects

**Auto-context switching:**
```
Schedule:
  09:00-12:00  → Novvi (auto-switch)
  12:00-13:00  → Personal
  13:00-17:00  → Novvi
  After 18:00  → Personal (no work interruptions)
```

With a manual override, but the default follows your rhythm.

---

### 3. **Inbox Zero Per Context**

Instead of one overwhelming inbox, treat each context as its own mini-inbox:

```
┌──────────────────────────────────────────┐
│  Context Health                          │
├──────────────────────────────────────────┤
│  🏢 Novvi      ████████░░  12 unread     │
│  🏠 Personal   ██░░░░░░░░   3 unread     │
│  🎓 Academic   ░░░░░░░░░░   0 unread  ✓  │
│  🚀 Startup    ████░░░░░░   7 unread     │
└──────────────────────────────────────────┘
```

Gamify it: "Academic is at inbox zero!" feels like a win.

---

### 4. **Smart Triage Queue**

Instead of browsing, present items one at a time:

```
┌─────────────────────────────────────────────────────────┐
│  TRIAGE MODE                                   [exit]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  From: Abby Cotton (T1 - Legal Counsel)                 │
│  Subject: MCPP Response - Final Draft                   │
│  Context: 🏢 Novvi                                      │
│                                                         │
│  "Jason, attached is the final draft. Please review     │
│   and confirm by EOD Thursday..."                       │
│                                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ Archive │ │ Snooze  │ │ Task    │ │ Reply   │       │
│  │   [a]   │ │   [s]   │ │   [t]   │ │   [r]   │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│                                                         │
│  Progress: ████████░░░░░░░░  8/23 items                 │
└─────────────────────────────────────────────────────────┘
```

Keyboard-driven, one decision at a time, progress bar for dopamine.

---

### 5. **"What's Actually Urgent?" AI Summary**

On load, before showing any lists, show a 3-line summary:

```
┌─────────────────────────────────────────────────────────┐
│  🎯 RIGHT NOW                                           │
├─────────────────────────────────────────────────────────┤
│  • MCPP response due Thursday (Abby waiting)            │
│  • Board deck feedback needed today (Eduardo asked 2x)  │
│  • Nothing else is actually urgent                      │
└─────────────────────────────────────────────────────────┘
```

Not a list of 47 items. Just: **what matters in the next 4 hours?**

---

### 6. **Relationship Pulse (People-Centric View)**

Flip the model: instead of emails, show **people**:

```
┌─────────────────────────────────────────────────────────┐
│  RELATIONSHIPS                                          │
├─────────────────────────────────────────────────────────┤
│  ⚠️  Cooling off (no contact >14 days):                 │
│      • Sam Burkett (BioBlend) - last: Jan 12            │
│      • Tim Wentworth (Okin Adams) - last: Jan 10        │
│                                                         │
│  🔥  Hot threads (active back-and-forth):               │
│      • Abby Cotton - 4 emails this week                 │
│      • Eduardo Baralt - daily contact                   │
│                                                         │
│  📥  Waiting on you:                                    │
│      • Chuck Kraft - sent Jan 27, no reply              │
│      • Daniela Michel - sent Jan 26, no reply           │
└─────────────────────────────────────────────────────────┘
```

Relationships > messages.

---

### 7. **"End of Day" Ritual Mode**

A guided 5-minute routine:

```
EOD Ritual (3 min remaining)
─────────────────────────────
Step 1: Review today's decisions ✓
Step 2: Clear quick replies (2 left)
Step 3: Set tomorrow's top 3
Step 4: Snooze everything else

[Continue] [Skip ritual today]
```

Reduces "did I forget something?" anxiety.

---

### 8. **Distraction Shield**

When in deep focus:

```
┌─────────────────────────────────────────────────────────┐
│  🛡️ FOCUS MODE ACTIVE (2h 15m remaining)               │
├─────────────────────────────────────────────────────────┤
│  3 emails arrived (held for later)                      │
│  1 calendar reminder (snoozed)                          │
│                                                         │
│  Nothing from T1 contacts. You're clear.                │
│                                                         │
│  [End focus early]                                      │
└─────────────────────────────────────────────────────────┘
```

Only T1/critical breaks through. Everything else waits.

---

## Ideas: Multi-Account Architecture

### Account Registry

```json
{
  "accounts": {
    "novvi-outlook": {
      "provider": "office365",
      "email": "wells@novvi.com",
      "gateway": "http://localhost:8766",
      "contexts": ["novvi"],
      "sync_interval": 5
    },
    "personal-gmail": {
      "provider": "gmail",
      "email": "jwells@gmail.com",
      "tokens_path": "data/gmail_tokens_personal.json",
      "contexts": ["personal", "academic"],
      "sync_interval": 10
    },
    "xcognis-gmail": {
      "provider": "gmail",
      "email": "jwells@xcognis.com",
      "tokens_path": "data/gmail_tokens_xcognis.json",
      "contexts": ["startup"],
      "sync_interval": 15
    },
    "ieee-email": {
      "provider": "imap",
      "email": "jwells@ieee.org",
      "contexts": ["academic"],
      "sync_interval": 30
    }
  }
}
```

### Context → Account Mapping

One context can span multiple accounts:
- **Academic**: jwells@gmail.com (filtered) + jwells@ieee.org
- **Personal**: jwells@gmail.com (default) + jwells.xyz

### OAuth Token Management

```
data/
  tokens/
    gmail_jwells_gmail_com.json
    gmail_jwells_xcognis_com.json
  imap/
    ieee_credentials.json (encrypted)
```

Each account has isolated credentials. The gmail_auth.py script gets a `--account` flag.

---

## Ideas: Aesthetic Improvements

### Current
- Functional but dense
- All contexts look the same
- No visual breathing room

### Proposed

1. **Context Color Coding**
   - Subtle background tint per context
   - Left border accent on items
   - Header color shifts with active context

2. **Information Hierarchy**
   - Larger, bolder "what's urgent now" section
   - Smaller, grayer "everything else"
   - More whitespace between logical groups

3. **Progress Indicators**
   - Visual inbox health bars
   - "You've handled 12 items today" stat
   - Streak tracking for inbox zero

4. **Dark Mode Polish**
   - Current: #0f1419 background (good)
   - Add: subtle gradients, better shadows
   - Card hover states that feel tactile

5. **Typography**
   - Slightly larger base font (14px vs 13px)
   - Better line height for readability
   - Distinct fonts for data vs prose

---

## Implementation Priority

### Phase 1 (This Week)
- [x] Gmail OAuth + multi-account foundation
- [x] Context toggles in UI
- [ ] Fix Office365/decapoda-lite connection
- [ ] Context badges on all briefing items

### Phase 2 (Next Week)
- [ ] Triage Queue mode
- [ ] "Right Now" AI summary at top
- [ ] EOD ritual mode
- [ ] Add xcognis.com account

### Phase 3 (Later)
- [ ] Time-based auto-context switching
- [ ] Focus mode / distraction shield
- [ ] People-centric relationship view
- [ ] IMAP support for IEEE

---

## Questions for Jason

1. Which ideas resonate most with how you work?
2. Are there specific pain points I'm missing?
3. What's the #1 thing that would reduce your cognitive load tomorrow?
4. Any accounts to prioritize after xcognis?

---

*These are starting points. The best features will emerge from watching how you actually use the tool.*
