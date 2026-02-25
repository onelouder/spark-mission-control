# Mission Control: Unified Command Center ("LifeOS")
## Product Requirements Document v2

**Author:** Jarvis + Jason Wells  
**Created:** 2026-01-28  
**Updated:** 2026-01-28  
**Status:** Planning → In Progress

---

## Executive Summary

Transform Mission Control from a single-account work dashboard into a **Federated Identity & Context Manager** — a semantic layer that sits above email protocols to structure information around **People** and **Projects** rather than inboxes.

The core insight: You are one person with one attention budget. The problem isn't "managing email" — it's **managing state across distributed systems** (where the systems are aspects of your life).

---

## The Core Architecture: "The Airlock Model"

All data flows through a local, secure processing layer (The Airlock) before reaching the UI. This enables unified entity resolution, signal classification, and context-aware filtering without mixing sensitive data inappropriately.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           THE FLIGHT DECK (UI)                              │
│  ┌──────────────┐  ┌─────────────────────────┐  ┌────────────────────────┐  │
│  │ Command Rail │  │      The Runway         │  │    Radar & Scope       │  │
│  │ (Modes/Ctx)  │  │ (Time-Unified Stream)   │  │ (Relationships/Proj)   │  │
│  └──────────────┘  └─────────────────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         THE AIRLOCK (Processing Layer)                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    THE GRAPH (The State)                            │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │   │
│  │  │   PEOPLE    │◄──►│  PROJECTS   │◄──►│     INTERACTIONS        │  │   │
│  │  │  (Entities) │    │ (Containers)│    │ (Emails/Events/Tasks)   │  │   │
│  │  └─────────────┘    └─────────────┘    └─────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    THE BRAIN (Intelligence Layer)                   │   │
│  │  • Signal Classification (Spam / Log / Actionable / Critical)       │   │
│  │  • Entity Resolution (Is this sender a known Person?)               │   │
│  │  • Project Matching (Does this belong to a tracked Project?)        │   │
│  │  • Relationship Decay (When did we last interact?)                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────┬───────────┴───────────┬─────────────┐
          ▼             ▼                       ▼             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     THE CONNECTORS (Ingestion Layer)                        │
│                                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐                │
│  │ Office365 │  │   Gmail   │  │   Gmail   │  │   IMAP    │                │
│  │  (Novvi)  │  │(Personal) │  │  (IEEE)   │  │ (Startup) │                │
│  │ Port 8766 │  │ Port 8767 │  │ Port 8768 │  │ Port 8769 │                │
│  │    🏢     │  │    🏠     │  │    🎓     │  │    🚀     │                │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘                │
│                                                                             │
│  Decapoda-Lite    Decapoda-Gmail (multi-account)                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The Paradigm Shift: Entities Over Inboxes

### The Old Model (Inbox-Centric)
```
Work Inbox → Work Emails → Work Tasks
Personal Inbox → Personal Emails → Personal Tasks
(No connection between them)
```

### The New Model (Entity-Centric)
```
                    ┌─────────────────┐
                    │     PERSON      │
                    │  "Eduardo B."   │
                    │                 │
                    │  Tier: T1       │
                    │  Tags: colleague│
                    │        friend   │
                    │  Last: 2 days   │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
   │ EMAIL ADDR  │    │ EMAIL ADDR  │    │  PROJECT    │
   │ baralt@     │    │ eduardo@    │    │ "Patent     │
   │ novvi.com   │    │ gmail.com   │    │  Opposition"│
   │ ctx: 🏢     │    │ ctx: 🏠     │    │             │
   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
          │                  │                  │
          ▼                  ▼                  ▼
   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
   │INTERACTIONS │    │INTERACTIONS │    │   ITEMS     │
   │ 847 emails  │    │ 12 emails   │    │ 3 emails    │
   │ 45 meetings │    │ 2 events    │    │ 2 tasks     │
   └─────────────┘    └─────────────┘    └─────────────┘
```

**Key principle:** An email is not a thing to process. It's an **interaction** attached to a **Person** within a **Context**, potentially related to a **Project**.

---

## The UI Layout: "Mission Control"

Three-pane layout optimized for **high situational awareness, low cognitive load**.

```
┌──[ COMMAND RAIL ]──┬────────────────[ THE RUNWAY ]────────────────┬──[ RADAR & SCOPE ]──┐
│                    │                                              │                     │
│  MODE SELECTOR     │  09:00 ┌──────────────────────────────────┐  │  RELATIONSHIP HUD   │
│  [■] ALL SYSTEMS   │        │ 🏢 MEETING: Novvi Eng Sync       │  │                     │
│  [ ] DEEP WORK     │        │    • Agenda: Thermal data review │  │  ⚠️ CRITICAL        │
│  [ ] COMMUNICATIONS│        │    • Prep: Read attached PDF     │  │  • Mom (5d ago)     │
│  [ ] FAMILY        │        └──────────────────────────────────┘  │  • Co-author (2d)   │
│                    │                                              │                     │
│  CONTEXT FILTERS   │  10:00 ┌──────────────────────────────────┐  │  ❄️ COOLING OFF     │
│  [✓] 🏢 Novvi      │        │ 🚀 EMAIL: Term Sheet Revision    │  │  • Roommate Alex    │
│  [✓] 🏠 Personal   │        │    • From: Lead Investor         │  │    (90 days)        │
│  [✓] 🚀 Startup    │        │    • Signal: HIGH (Time sens.)   │  │                     │
│  [✓] 🎓 IEEE       │        └──────────────────────────────────┘  │                     │
│                    │                                              │  ACTIVE PROJECTS    │
│  SYSTEM HEALTH     │  11:30 ┌──────────────────────────────────┐  │                     │
│  Inbox: 12 (4 High)│        │ 🏠 REMINDER: Call Contractor     │  │  [■] Patent Opp.    │
│  Tasks: 5          │        │    • Context: Kitchen Reno       │  │  [▶] Series A       │
│  Sync: 2m ago      │        └──────────────────────────────────┘  │  [▶] IEEE Paper     │
│                    │                                              │                     │
└────────────────────┴──────────────────────────────────────────────┴─────────────────────┘
```

### Zone A: Command Rail (Left)
- **Mode Selector:** Physical toggles that collapse/mute streams
- **Context Filters:** Toggle visibility of each life context
- **System Health:** Inbox pressure, task count, last sync

### Zone B: The Runway (Center)
- **Time-Unified Stream:** Chronological river of commitments
- **Interleaved Objects:** Meetings, emails, tasks in one timeline
- **Smart Collapse:** Low-signal items grouped into expandable "Log"

### Zone C: Radar & Scope (Right)
- **Relationship HUD:** CRM for life — tracks decay, surfaces neglected relationships
- **Active Projects:** Progress on major initiatives, click to filter Runway

---

## Signal Classification System

Every incoming item is classified by The Brain:

| Signal Level | Meaning | UI Treatment |
|--------------|---------|--------------|
| **CRITICAL** | Time-sensitive, high-tier person, explicit urgency | Red highlight, stays visible |
| **ACTIONABLE** | Needs response/action, but not urgent | Normal visibility in Runway |
| **LOG** | Informational, receipts, confirmations | Collapsed into "Log" group |
| **NOISE** | Newsletters, marketing, detected spam | Auto-archived, not shown |

### Classification Logic

```
IF sender is UNKNOWN:
  → Create provisional Entity
  → LLM infers relationship type from signature/context
  → Default to LOG until promoted

IF sender is KNOWN Entity:
  → Update last_contact timestamp
  → Check Entity tier:
    T1 (Critical) → Bias toward ACTIONABLE/CRITICAL
    T2 (Important) → Bias toward ACTIONABLE
    T3+ → Classify normally

IF email matches PROJECT keywords/people:
  → Tag with Project
  → Boost signal if Project is active

IF email contains urgency signals:
  → Keywords: "urgent", "ASAP", "deadline", "EOD"
  → Boost to CRITICAL

IF email is automated/transactional:
  → Receipts, confirmations, notifications
  → Demote to LOG
```

---

## Implementation Strategy: "The Trojan Horse"

Start with the messiest data (Personal Gmail). If we can tame that, everything else is easy.

### Phase 1: The Personal Shadow (Current)
**Goal:** Prove Signal Classification and Relationship Radar on Personal Gmail

**Deliverables:**
1. Decapoda-Gmail connector for jwells@gmail.com
2. The Graph data model (People, Projects, Interactions)
3. The Brain classification logic
4. Basic Runway UI showing classified items
5. Relationship Radar (who haven't I talked to?)

**Success:** Can see Personal Gmail in entity-centric view with signal classification

---

### Phase 2: The Satellite Contexts
**Goal:** Test multi-context merging

**Deliverables:**
1. Add Startup account connector
2. Add IEEE account connector
3. Cross-context entity linking (same person, multiple emails)
4. Project containers spanning contexts
5. Mode switching (hide contexts when focusing)

**Success:** Can track a Project that spans multiple accounts

---

### Phase 3: Work Integration
**Goal:** Full Unified Command

**Deliverables:**
1. Connect Office365 (already have Decapoda-Lite)
2. Merge Work entities into The Graph
3. Full three-pane Mission Control UI
4. Airlock respects corporate data policies

**Success:** One morning briefing across all life contexts

---

### Phase 4: Intelligence Upgrades
**Goal:** Proactive assistance

**Deliverables:**
1. Relationship decay alerts
2. Project progress inference
3. Suggested responses/actions
4. Smart scheduling recommendations

---

## Data Model

See: `DATA-MODEL-entities.md` (separate document)

---

## Technical Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Connectors** | Python + FastAPI | Decapoda-Lite (O365), Decapoda-Gmail (Google) |
| **The Graph** | SQLite + JSON | Start simple, migrate to PostgreSQL if needed |
| **The Brain** | Clawdbot Gateway LLM | Or local Ollama for privacy |
| **The Flight Deck** | FastAPI + Jinja2 + Vanilla JS | Current MC stack, evolve as needed |

---

## Context Definitions

| ID | Name | Icon | Color | Provider | Email |
|----|------|------|-------|----------|-------|
| `work` | Work | 🏢 | #3b82f6 (Blue) | Office365 | wells@novvi.com |
| `personal` | Personal | 🏠 | #10b981 (Green) | Gmail | jwells@gmail.com |
| `startup` | Startup | 🚀 | #8b5cf6 (Purple) | TBD | TBD |
| `academic` | Academic | 🎓 | #f59e0b (Amber) | Gmail | TBD (IEEE) |

---

## Success Metrics

- **Signal Accuracy:** 90%+ emails correctly classified
- **Entity Resolution:** 80%+ contacts auto-linked across accounts
- **Relationship Radar:** Zero "forgot to reply" for T1/T2 contacts
- **Cognitive Load:** Single glance shows full life state
- **Response Time:** <200ms for cached views

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Gmail OAuth complexity | Well-tested google-auth library |
| Data model migrations | Start with flexible JSON, schema versioning |
| LLM classification latency | Async processing, cache classifications |
| Corporate data concerns | Airlock keeps contexts isolated, local processing |
| Scope creep | Phase-gated delivery, prove each phase before advancing |

---

## Changelog

- 2026-01-28 v1: Initial PRD (profile-based architecture)
- 2026-01-28 v2: Rewritten with Airlock architecture, Entity-centric model
