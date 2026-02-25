# Phase 1: The Personal Shadow — Implementation Plan

**Goal:** Prove Signal Classification and Relationship Radar on Personal Gmail (jwells@gmail.com)

**Philosophy:** Start with the messiest data. If we can tame a 25-year spam-heavy Gmail, everything else is easy.

---

## Prerequisites

- [ ] Google Cloud Console project with OAuth2 credentials
- [ ] Gmail API and Google Calendar API enabled
- [ ] `credentials.json` downloaded

---

## Task Breakdown

### 1.1 Decapoda-Gmail Service [~2 hours]

**Location:** `/home/jwells/projects/decapoda-gmail/`

#### 1.1.1 Project Setup
```bash
mkdir -p ~/projects/decapoda-gmail
cd ~/projects/decapoda-gmail
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn google-auth google-auth-oauthlib google-api-python-client
```

- [ ] Create `app.py` with FastAPI structure
- [ ] Create `requirements.txt`
- [ ] Create `data/` directory for tokens

#### 1.1.2 OAuth2 Implementation
- [ ] `/auth/start` — Redirect to Google consent screen
- [ ] `/auth/callback` — Exchange code for tokens
- [ ] Token storage in `data/tokens.json`
- [ ] Token refresh logic
- [ ] `/admin` — Status page showing auth state

#### 1.1.3 Email Endpoints (matching Decapoda-Lite contract)
- [ ] `GET /v1/email/inbox` — List messages
- [ ] `GET /v1/email/message/{id}` — Get full message
- [ ] Return format compatible with existing MC pipeline

#### 1.1.4 Calendar Endpoints
- [ ] `GET /v1/calendar/next` — Upcoming events
- [ ] Attendee parsing matching Decapoda-Lite

#### 1.1.5 Systemd Service
- [ ] Create `~/.config/systemd/user/decapoda-gmail.service`
- [ ] Port 8767, bind 127.0.0.1
- [ ] Enable and start

---

### 1.2 The Graph Database [~1.5 hours]

**Location:** `/home/jwells/projects/mission-control/data/graph.db` (SQLite)

#### 1.2.1 Schema Creation
- [ ] Create `graph.py` module for database operations
- [ ] Implement schema from DATA-MODEL-entities.md
- [ ] Tables: `people`, `email_addresses`, `contexts`, `projects`, `interactions`

#### 1.2.2 Entity Operations
- [ ] `create_person()`, `get_person()`, `update_person()`
- [ ] `lookup_person_by_email()` — The key entity resolution function
- [ ] `create_interaction()`, `get_interactions()`
- [ ] `link_email_to_person()` — For manual linking

#### 1.2.3 Context Setup
- [ ] Create `personal` context in graph
- [ ] Keep `work` context pointing to existing Decapoda-Lite

---

### 1.3 The Brain (Signal Classification) [~2 hours]

**Location:** `/home/jwells/projects/mission-control/brain.py`

#### 1.3.1 Fast Filters
- [ ] Implement `fast_filter_noise()` — Spam/marketing detection
- [ ] Implement `fast_filter_log()` — Transactional email detection
- [ ] Configurable pattern lists

#### 1.3.2 Signal Scoring
- [ ] Implement `compute_signal_score()` — Weighted scoring
- [ ] Implement `find_matching_projects()` — Project detection
- [ ] Implement `detect_response_needed()` — Response urgency

#### 1.3.3 Entity Resolution
- [ ] Implement `resolve_sender()` — Find or create Person
- [ ] Fuzzy name matching for linking suggestions
- [ ] Provisional person creation

#### 1.3.4 LLM Refinement (Optional)
- [ ] Classification prompt for borderline cases
- [ ] Integration with Clawdbot Gateway LLM
- [ ] Fallback to rule-based if LLM unavailable

#### 1.3.5 Full Pipeline
- [ ] Implement `classify_interaction()` — Full flow
- [ ] Batch processing for initial sync

---

### 1.4 Initial Gmail Sync [~1 hour]

#### 1.4.1 Historical Import
- [ ] Fetch last 6 months of email headers
- [ ] Build initial People graph from senders
- [ ] Classify all messages
- [ ] Store in graph database

#### 1.4.2 Contact Tier Seeding
- [ ] Identify high-frequency senders → suggest T2+
- [ ] Identify family patterns (same last name) → suggest T1
- [ ] Manual review UI for tier assignment

---

### 1.5 Relationship Radar View [~1.5 hours]

**New UI component for right pane**

#### 1.5.1 Backend
- [ ] `/api/radar` — Returns relationship health data
- [ ] "Cooling Off" query — No contact in 30+ days, tier T1-T3
- [ ] "Needs Response" query — Pending responses
- [ ] "Recently Active" query — Last 7 days

#### 1.5.2 Frontend
- [ ] Radar component in right pane
- [ ] Contact cards showing:
  - Name, tier badge
  - Days since last contact
  - Context icon
  - Quick actions (view thread, compose)
- [ ] Click to filter Runway to that person

---

### 1.6 Updated Briefing View [~1 hour]

#### 1.6.1 Backend Changes
- [ ] `/api/briefing` accepts `context` parameter
- [ ] `/api/briefing?context=personal` — Personal only
- [ ] `/api/briefing?context=all` — Unified (future)
- [ ] Signal-based sorting (CRITICAL first, then ACTIONABLE)

#### 1.6.2 Frontend Changes
- [ ] Context indicator in nav bar
- [ ] Signal level badges on items (color-coded)
- [ ] "Log" collapse group for low-signal items
- [ ] Expand/collapse Log group

---

### 1.7 Context Switcher [~30 min]

#### 1.7.1 UI Component
- [ ] Dropdown in nav bar showing available contexts
- [ ] Current context highlighted
- [ ] Click to switch context
- [ ] Visual indicator (icon + color accent)

#### 1.7.2 State Management
- [ ] Store selected context in localStorage
- [ ] All API calls include context parameter
- [ ] URL reflects context: `/personal/briefing`, `/work/briefing`

---

## Testing Checklist

- [ ] Gmail OAuth flow completes successfully
- [ ] Emails appear in graph database with classifications
- [ ] People entities created with correct email links
- [ ] Signal scores reflect sender importance and content
- [ ] NOISE emails auto-archived, not shown in Runway
- [ ] LOG emails collapsed in dedicated group
- [ ] Relationship Radar shows contacts needing attention
- [ ] Context switcher toggles between Work and Personal
- [ ] Work profile unchanged (regression test)

---

## Success Criteria

1. **Gmail Connected:** Can authenticate and fetch from jwells@gmail.com
2. **Signal Working:** CRITICAL/ACTIONABLE/LOG/NOISE classification is 80%+ accurate
3. **People Graph:** Senders resolved to Person entities
4. **Radar Functional:** Can see who I haven't responded to
5. **No Work Regression:** `/work/briefing` still works identically

---

## Files Created/Modified

### New Files
```
~/projects/decapoda-gmail/
├── app.py                      # Gmail gateway service
├── requirements.txt
└── data/
    └── tokens.json             # OAuth tokens

~/projects/mission-control/
├── graph.py                    # Graph database operations
├── brain.py                    # Signal classification logic
├── data/
│   └── graph.db               # SQLite database
├── static/
│   └── radar.js               # Radar component
└── templates/
    └── partials/
        └── radar.html         # Radar HTML
```

### Modified Files
```
~/projects/mission-control/
├── app.py                      # New routes, context parameter
├── briefing.py                 # Signal-based sorting, context filter
├── static/
│   ├── briefing.js            # Context switcher, signal badges
│   └── briefing.css           # Signal level colors
└── templates/
    └── briefing.html          # Radar pane, context switcher
```

---

## Google Cloud Setup Steps

1. Go to https://console.cloud.google.com/
2. Create new project: "Mission Control Personal"
3. Enable APIs:
   - Gmail API
   - Google Calendar API
4. Configure OAuth consent screen:
   - User type: External
   - App name: "Mission Control"
   - Scopes: 
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/calendar.readonly`
5. Create OAuth 2.0 credentials:
   - Application type: Desktop app
   - Download JSON
   - Save as `~/projects/decapoda-gmail/data/credentials.json`

---

## Rollback Plan

If issues arise:
1. Stop decapoda-gmail service
2. Remove `personal` context from contexts table
3. Mission Control falls back to work-only mode
4. No changes to existing work data

---

## Next Phase Preview (Phase 2: Satellite Contexts)

After Phase 1 is proven:
1. Add Startup email account
2. Add IEEE email account  
3. Cross-context entity linking UI
4. Project containers spanning contexts
5. Mode switching (hide contexts when focusing)
