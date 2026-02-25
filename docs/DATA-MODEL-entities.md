# Data Model: The Graph (Entity Schemas)

**Version:** 1.0  
**Updated:** 2026-01-28

This document defines the data structures for the Unified Command Center's entity-centric model.

---

## Overview

The Graph consists of four primary entity types:

1. **Person** — A human being (may have multiple email addresses)
2. **Project** — A container for related work across contexts
3. **Interaction** — A single email, event, or task
4. **Context** — A life domain (Work, Personal, Startup, Academic)

```
┌──────────────┐         ┌──────────────┐
│    PERSON    │◄───────►│   PROJECT    │
│              │ member  │              │
└──────┬───────┘         └──────┬───────┘
       │ has                    │ contains
       ▼                        ▼
┌──────────────┐         ┌──────────────┐
│ EMAIL_ADDR   │         │ INTERACTION  │
│              │◄───────►│              │
└──────────────┘  from/  └──────────────┘
                   to
```

---

## Entity: Person

A **Person** represents a unique human being across all contexts.

```json
{
  "id": "uuid-v4",
  "display_name": "Eduardo Baralt",
  "sort_name": "Baralt, Eduardo",
  
  "emails": [
    {
      "address": "baralt@novvi.com",
      "context_id": "work",
      "is_primary": true,
      "discovered_at": "2021-03-15T00:00:00Z",
      "interaction_count": 847
    },
    {
      "address": "eduardo.baralt@gmail.com",
      "context_id": "personal",
      "is_primary": false,
      "discovered_at": "2023-06-20T00:00:00Z",
      "interaction_count": 12
    }
  ],
  
  "tier": "T1",
  "tags": ["colleague", "friend", "novvi-team"],
  
  "relationship": {
    "first_interaction": "2021-03-15T14:30:00Z",
    "last_interaction": "2026-01-26T09:15:00Z",
    "total_interactions": 859,
    "avg_response_time_hours": 4.2,
    "interaction_trend": "stable"
  },
  
  "contexts": ["work", "personal"],
  
  "metadata": {
    "company": "Novvi",
    "title": "VP Engineering",
    "phone": "+1-555-0123",
    "linkedin": "https://linkedin.com/in/eduardobaralt",
    "notes": "Reports to Jason. Go-to for technical decisions."
  },
  
  "created_at": "2021-03-15T14:30:00Z",
  "updated_at": "2026-01-26T09:15:00Z"
}
```

### Person Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `display_name` | string | How to show this person |
| `sort_name` | string | For alphabetical sorting |
| `emails` | array | All known email addresses |
| `emails[].context_id` | string | Which context this email belongs to |
| `emails[].is_primary` | bool | Preferred email for this context |
| `tier` | enum | T1 (critical), T2 (important), T3 (normal), T4 (low) |
| `tags` | array | Relationship labels |
| `relationship` | object | Interaction statistics |
| `contexts` | array | Which life contexts this person appears in |
| `metadata` | object | Additional info (company, title, notes) |

### Tier Definitions

| Tier | Label | Description | Response SLA |
|------|-------|-------------|--------------|
| T1 | Critical | Family, key colleagues, investors, close friends | Same day |
| T2 | Important | Regular collaborators, active partners | 2-3 days |
| T3 | Normal | Professional network, acquaintances | 1 week |
| T4 | Low | Newsletters, vendors, one-time contacts | When convenient |

---

## Entity: Project

A **Project** is a container for related work that may span multiple contexts.

```json
{
  "id": "uuid-v4",
  "name": "MCPP Patent Opposition",
  "slug": "mcpp-patent",
  "description": "Responding to MCPP patent challenge",
  
  "status": "active",
  "priority": "high",
  
  "contexts": ["work"],
  
  "rules": {
    "keywords": ["MCPP", "patent", "opposition", "Okin Adams", "USPTO"],
    "people_ids": ["uuid-abby-cotton", "uuid-tim-wentworth"],
    "sender_domains": ["okinadams.com", "bclp.com"],
    "subject_patterns": ["patent.*opposition", "MCPP.*response"]
  },
  
  "members": [
    {
      "person_id": "uuid-abby-cotton",
      "role": "lead-counsel"
    },
    {
      "person_id": "uuid-tim-wentworth",
      "role": "ip-counsel"
    }
  ],
  
  "stats": {
    "total_interactions": 47,
    "unread_count": 3,
    "tasks_open": 2,
    "tasks_done": 5,
    "last_activity": "2026-01-27T16:30:00Z"
  },
  
  "milestones": [
    {
      "name": "Response deadline",
      "date": "2026-02-15",
      "status": "upcoming"
    }
  ],
  
  "created_at": "2025-11-01T00:00:00Z",
  "updated_at": "2026-01-27T16:30:00Z"
}
```

### Project Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | Display name |
| `slug` | string | URL-safe identifier |
| `status` | enum | active, paused, completed, archived |
| `priority` | enum | critical, high, normal, low |
| `contexts` | array | Which contexts this project spans |
| `rules` | object | Auto-matching rules for interactions |
| `rules.keywords` | array | Words to match in subject/body |
| `rules.people_ids` | array | Auto-include interactions with these people |
| `rules.sender_domains` | array | Domains to match |
| `rules.subject_patterns` | array | Regex patterns for subjects |
| `members` | array | People involved in this project |
| `stats` | object | Computed statistics |
| `milestones` | array | Key dates |

---

## Entity: Interaction

An **Interaction** is a single email, calendar event, or task.

```json
{
  "id": "uuid-v4",
  "type": "email",
  "context_id": "work",
  
  "external_id": "AAMkADc3OGEx...",
  "external_url": "https://outlook.office365.com/...",
  
  "subject": "Re: MCPP Opposition - Draft Response",
  "preview": "Jason, attached is the revised draft incorporating...",
  
  "from_person_id": "uuid-abby-cotton",
  "from_email": "acotton@bclp.com",
  "to_person_ids": ["uuid-jason-wells"],
  "cc_person_ids": ["uuid-tim-wentworth"],
  
  "timestamp": "2026-01-27T16:30:00Z",
  "received_at": "2026-01-27T16:30:00Z",
  
  "signal": {
    "level": "actionable",
    "score": 0.85,
    "reasons": ["T1 sender", "reply expected", "project match"],
    "classified_at": "2026-01-27T16:30:05Z"
  },
  
  "state": {
    "is_read": true,
    "is_archived": false,
    "is_snoozed": false,
    "snooze_until": null,
    "response_status": "pending",
    "response_due": "2026-01-28T17:00:00Z"
  },
  
  "project_ids": ["uuid-mcpp-patent"],
  "tags": ["legal", "deadline"],
  
  "thread_id": "thread-uuid",
  "in_reply_to": "prev-interaction-uuid",
  
  "attachments": [
    {
      "name": "MCPP_Response_Draft_v3.pdf",
      "size_bytes": 245000,
      "content_type": "application/pdf"
    }
  ],
  
  "created_at": "2026-01-27T16:30:05Z",
  "updated_at": "2026-01-27T18:00:00Z"
}
```

### Interaction Types

| Type | Description |
|------|-------------|
| `email` | Email message |
| `event` | Calendar event/meeting |
| `task` | Kanban task |
| `reminder` | System-generated reminder |

### Signal Levels

| Level | Score Range | Description |
|-------|-------------|-------------|
| `critical` | 0.9 - 1.0 | Requires immediate attention |
| `actionable` | 0.6 - 0.9 | Needs response/action |
| `log` | 0.3 - 0.6 | Informational, archive-worthy |
| `noise` | 0.0 - 0.3 | Auto-archive, don't show |

### Response Status

| Status | Description |
|--------|-------------|
| `none_needed` | No response expected |
| `pending` | Response needed, not yet sent |
| `draft` | Draft in progress |
| `sent` | Response sent |
| `delegated` | Delegated to someone else |

---

## Entity: Context

A **Context** represents a life domain (account/profile).

```json
{
  "id": "work",
  "name": "Work",
  "icon": "🏢",
  "color": "#3b82f6",
  
  "provider": "office365",
  "gateway_url": "http://localhost:8766",
  
  "user_email": "wells@novvi.com",
  "user_name": "Jason Wells",
  
  "enabled": true,
  "last_sync": "2026-01-28T19:30:00Z",
  "sync_status": "ok",
  
  "settings": {
    "sync_interval_minutes": 5,
    "archive_after_days": 30,
    "default_tier_for_unknown": "T3"
  }
}
```

---

## Entity: Thread

Groups related interactions (email thread, meeting series).

```json
{
  "id": "uuid-v4",
  "subject": "MCPP Opposition - Draft Response",
  "context_id": "work",
  
  "participants": [
    {"person_id": "uuid-abby-cotton", "role": "initiator"},
    {"person_id": "uuid-jason-wells", "role": "participant"},
    {"person_id": "uuid-tim-wentworth", "role": "cc"}
  ],
  
  "interaction_ids": ["uuid-1", "uuid-2", "uuid-3"],
  "interaction_count": 3,
  
  "first_message": "2026-01-25T10:00:00Z",
  "last_message": "2026-01-27T16:30:00Z",
  
  "project_ids": ["uuid-mcpp-patent"],
  
  "state": {
    "status": "active",
    "awaiting_response_from": "uuid-jason-wells"
  }
}
```

---

## Storage Schema

### Option A: SQLite (Recommended for Phase 1)

```sql
-- People
CREATE TABLE people (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    sort_name TEXT,
    tier TEXT DEFAULT 'T3',
    tags TEXT,  -- JSON array
    metadata TEXT,  -- JSON object
    created_at TEXT,
    updated_at TEXT
);

-- Email addresses (many-to-one with Person)
CREATE TABLE email_addresses (
    address TEXT PRIMARY KEY,
    person_id TEXT REFERENCES people(id),
    context_id TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    discovered_at TEXT,
    interaction_count INTEGER DEFAULT 0
);

-- Contexts
CREATE TABLE contexts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT,
    color TEXT,
    provider TEXT,
    gateway_url TEXT,
    user_email TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    settings TEXT  -- JSON
);

-- Projects
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    priority TEXT DEFAULT 'normal',
    rules TEXT,  -- JSON
    created_at TEXT,
    updated_at TEXT
);

-- Project-Context relationship
CREATE TABLE project_contexts (
    project_id TEXT REFERENCES projects(id),
    context_id TEXT REFERENCES contexts(id),
    PRIMARY KEY (project_id, context_id)
);

-- Project-Person relationship
CREATE TABLE project_members (
    project_id TEXT REFERENCES projects(id),
    person_id TEXT REFERENCES people(id),
    role TEXT,
    PRIMARY KEY (project_id, person_id)
);

-- Interactions
CREATE TABLE interactions (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- email, event, task
    context_id TEXT REFERENCES contexts(id),
    external_id TEXT,
    external_url TEXT,
    subject TEXT,
    preview TEXT,
    from_person_id TEXT REFERENCES people(id),
    from_email TEXT,
    timestamp TEXT,
    signal_level TEXT,
    signal_score REAL,
    signal_reasons TEXT,  -- JSON array
    state TEXT,  -- JSON object
    thread_id TEXT,
    data TEXT,  -- Full JSON for type-specific fields
    created_at TEXT,
    updated_at TEXT
);

-- Interaction-Project relationship
CREATE TABLE interaction_projects (
    interaction_id TEXT REFERENCES interactions(id),
    project_id TEXT REFERENCES projects(id),
    PRIMARY KEY (interaction_id, project_id)
);

-- Interaction recipients (to/cc)
CREATE TABLE interaction_recipients (
    interaction_id TEXT REFERENCES interactions(id),
    person_id TEXT REFERENCES people(id),
    recipient_type TEXT,  -- to, cc, bcc
    PRIMARY KEY (interaction_id, person_id, recipient_type)
);

-- Indexes
CREATE INDEX idx_interactions_context ON interactions(context_id);
CREATE INDEX idx_interactions_timestamp ON interactions(timestamp);
CREATE INDEX idx_interactions_signal ON interactions(signal_level);
CREATE INDEX idx_interactions_from ON interactions(from_person_id);
CREATE INDEX idx_email_addresses_person ON email_addresses(person_id);
```

### Option B: JSON Files (Simpler, current MC style)

```
data/
├── graph/
│   ├── people.json        # All Person entities
│   ├── projects.json      # All Project entities
│   ├── contexts.json      # Context configurations
│   └── threads.json       # Thread groupings
├── interactions/
│   ├── work/
│   │   └── 2026-01.json   # Interactions by month
│   └── personal/
│       └── 2026-01.json
└── cache/
    ├── runway.json        # Pre-computed Runway view
    └── radar.json         # Pre-computed Radar view
```

---

## Entity Resolution Logic

When a new email arrives:

```python
def resolve_sender(email_address: str, context_id: str) -> Person:
    # 1. Exact match in email_addresses table
    existing = lookup_email(email_address)
    if existing:
        update_last_interaction(existing.person_id)
        return get_person(existing.person_id)
    
    # 2. Check for fuzzy matches (same name, different domain)
    candidates = fuzzy_match_by_name(extract_name(email_address))
    if candidates:
        # Suggest linking, don't auto-merge
        return create_provisional_person(email_address, link_candidates=candidates)
    
    # 3. Create new provisional person
    person = create_provisional_person(email_address)
    
    # 4. Infer relationship type via LLM (async)
    schedule_classification(person.id, email_address)
    
    return person
```

---

## Migration from Current MC

Current Mission Control stores:
- `processed_emails.json` — Flat email list
- `tasks.json` — Kanban tasks
- `contacts.json` — Simple contact tiers

Migration steps:
1. Create `contexts.json` with Work context
2. Import contacts → People entities
3. Import emails → Interactions with entity linking
4. Import tasks → Interactions (type=task)
5. Create default Projects from existing threads

---

## Changelog

- 2026-01-28: Initial data model specification
