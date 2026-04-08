#!/usr/bin/env python3
"""
Briefing Generation Module for Mission Control
=============================================
Generates the Running Briefing page data with 6 blocks + snooze system.

Blocks:
1. Decisions Waiting on You - High-priority emails needing response
2. Today's Runway - Calendar timeline + tasks for today/tomorrow
3. Active Threads - LLM-generated project/conversation clusters
4. Incoming Tasks & Action Items - Lower-priority emails needing attention
5. This Week's Pulse - LLM-generated narrative summary
6. Stale/Aging - Items that have been sitting too long

The briefing is cached and regenerated every 15 minutes by a background task
in app.py (periodic_briefing_refresh). Manual refresh bypasses cache.

Data Flow:
- Reads from: processed_emails.json, tasks.json, contacts.json, snoozed.json
- Writes to: briefing_cache.json (LLM blocks), briefing_full_cache.json (full briefing)
- LLM calls: Uses the primary local OpenAI-compatible runtime from openclaw.json
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import httpx
import pytz

from openclaw_runtime import get_primary_chat_runtime, run_primary_chat_completion

# =============================================================================
# Configuration
# =============================================================================

DATA_DIR = "data"

# Cache files - briefing data is cached to reduce LLM calls
BRIEFING_CACHE_FILE = os.path.join(DATA_DIR, "briefing_cache.json")      # LLM block cache (threads, pulse)
BRIEFING_FULL_CACHE_FILE = os.path.join(DATA_DIR, "briefing_full_cache.json")  # Full briefing cache
BRIEFING_FULL_CACHE_SCHEMA_VERSION = 2  # Adds decisions.items[].received_at for detailed elapsed time

# Data files
SNOOZED_FILE = os.path.join(DATA_DIR, "snoozed.json")
PROCESSED_EMAILS_FILE = os.path.join(DATA_DIR, "processed_emails.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
CONTACTS_FILE = os.path.join(DATA_DIR, "contacts.json")

# Pacific timezone for display
PT = pytz.timezone('America/Los_Angeles')

# Trusted sender tags from deterministic Stage 1 filtering
_TRUST_TAG_ALIASES = {
    "t1": "tier1",
    "t2": "tier2",
    "int": "internal",
    "ptr": "partner",
}
_TRUSTED_SENDER_TAGS = {
    "internal",
    "tier1",
    "tier2",
    "partner",
    "whitelist",
    "whitelist_domain",
    "sent_recipient",
}
_ACCOUNT_INDEX_CACHE: Optional[Tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]] = None

def load_json_file(filename: str, default: Any = None) -> Any:
    """Load JSON file with error handling"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}

def save_json_file(filename: str, data: Any) -> None:
    """Save data to JSON file"""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def get_cached_briefing() -> Optional[Dict]:
    """Get cached briefing if it exists"""
    try:
        with open(BRIEFING_FULL_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)

        if cache_data.get("schema_version") != BRIEFING_FULL_CACHE_SCHEMA_VERSION:
            try:
                os.remove(BRIEFING_FULL_CACHE_FILE)
            except Exception:
                pass
            return None

        return cache_data
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading briefing cache: {e}")
        return None

# Patterns for room/resource mailboxes to filter from attendees
_ROOM_PATTERNS = {"room", "conf", "board", "lobby", "lounge", "auditorium", "kitchen", "lab"}
_SELF_EMAIL = "wells@novvi.com"

def _is_real_person(att: Dict) -> bool:
    """Return True if attendee looks like a real person (not self, not a room/resource)."""
    addr = att.get("address", "").lower()
    if not addr or addr == _SELF_EMAIL:
        return False
    if att.get("type", "").lower() == "resource":
        return False
    # Heuristic: local part or name contains room-like keywords
    local = addr.split("@")[0]
    name = att.get("name", "").lower()
    if any(p in local for p in _ROOM_PATTERNS) or any(p in name for p in _ROOM_PATTERNS):
        return False
    # Name equals the email address → likely a resource, not a person
    if name == addr:
        return False
    return True

def get_contact_tier(email_address: str, contacts: Dict) -> str:
    """
    Get contact tier for an email address.
    
    Tier hierarchy (affects prioritization in briefing blocks):
    - T1: Top 20 critical contacts (highest priority)
    - T2: Top 100 important contacts
    - INT: Internal (novvi.com domain)
    - PTR: Partners/vendors
    - UNK: Unknown (lowest priority, often filtered out)
    
    Args:
        email_address: The sender's email address
        contacts: Loaded contacts.json data
    
    Returns:
        Tier code string (T1, T2, INT, PTR, or UNK)
    """
    email_lower = email_address.lower()
    
    # Check Top 20 (highest priority)
    for contact in contacts.get("top20", []):
        if contact.get("email", "").lower() == email_lower:
            return "T1"
    
    # Check Top 100
    for contact in contacts.get("top100", []):
        if contact.get("email", "").lower() == email_lower:
            return "T2"
    
    # Check if internal (novvi.com domain)
    if email_lower.endswith("@novvi.com"):
        return "INT"
    
    # Check partners/vendors
    for contact in contacts.get("partners", []):
        if contact.get("email", "").lower() == email_lower:
            return "PTR"
    
    return "UNK"

def calculate_tier_weight(tier: str) -> int:
    """Calculate numerical weight for sorting"""
    weights = {"T1": 10, "T2": 7, "INT": 8, "PTR": 5, "UNK": 1}
    return weights.get(tier, 1)

def days_since(date_str: str) -> int:
    """Calculate days since a given date string"""
    try:
        if isinstance(date_str, str):
            # Handle multiple datetime formats
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                dt = datetime.fromisoformat(date_str)
        else:
            dt = date_str
        
        now = datetime.now(timezone.utc)
        return (now - dt).days
    except:
        return 0

def get_pt_time_str(dt: datetime = None) -> str:
    """Get Pacific time string"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    pt_time = dt.astimezone(PT)
    return pt_time.strftime("%Y-%m-%d %I:%M %p PT")

def _normalize_trust_tag(tag: Optional[str]) -> str:
    """Normalize tier/trust tags across legacy and current formats."""
    raw = str(tag or "").strip().lower()
    return _TRUST_TAG_ALIASES.get(raw, raw)

def _is_trusted_sender(email_info: Dict) -> bool:
    """Require deterministic trusted sender tags for briefing email inclusion."""
    stage1_tag = (
        email_info.get("stages", {})
        .get("stage1", {})
        .get("tag")
    )
    contact_tier = email_info.get("contact_tier")

    # Prefer Stage 1 deterministic tag when present.
    trust_tag = _normalize_trust_tag(stage1_tag or contact_tier)
    return trust_tag in _TRUSTED_SENDER_TAGS

def _get_account_index() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]:
    """
    Build account lookup maps:
    - account_email -> account_id
    - account_id -> account_email
    - account_id -> contexts[]
    """
    global _ACCOUNT_INDEX_CACHE
    if _ACCOUNT_INDEX_CACHE is not None:
        return _ACCOUNT_INDEX_CACHE

    email_to_id: Dict[str, str] = {}
    id_to_email: Dict[str, str] = {}
    id_to_contexts: Dict[str, List[str]] = {}

    try:
        from context_aggregator import get_accounts
        accounts = get_accounts()
    except Exception:
        accounts = []

    for account in accounts:
        account_id = str(account.get("id") or "").strip()
        account_email = str(account.get("email") or "").lower().strip()
        contexts = list(account.get("contexts") or [])

        if not account_id:
            continue
        if account_email:
            email_to_id[account_email] = account_id
            id_to_email[account_id] = account_email
        id_to_contexts[account_id] = contexts

    _ACCOUNT_INDEX_CACHE = (email_to_id, id_to_email, id_to_contexts)
    return _ACCOUNT_INDEX_CACHE

def _infer_account_id(email_id: str, email_data: Dict) -> Optional[str]:
    """Infer account_id for filtered briefing rows."""
    explicit_id = str(email_data.get("account_id") or "").strip()
    if explicit_id:
        return explicit_id

    raw_account = str(email_data.get("_account") or "").lower().strip()
    source = str(email_data.get("_source") or "").lower().strip()
    source_url = str(email_data.get("webLink") or "").lower().strip()
    msg_id = str(email_data.get("id") or email_id or "")

    email_to_id, _, _ = _get_account_index()
    if raw_account and raw_account in email_to_id:
        return email_to_id[raw_account]

    # Legacy Exchange/Office365 messages often lacked account metadata.
    if (
        source == "office365"
        or "outlook.office365.com" in source_url
        or msg_id.startswith("AAMk")
    ):
        return "novvi-outlook"

    if source == "gmail" or "mail.google.com" in source_url:
        return email_to_id.get(raw_account, "personal-gmail")

    return None

def _infer_context_id(email_data: Dict, account_id: Optional[str]) -> Optional[str]:
    """Infer context_id from explicit fields, classifier, then account defaults."""
    explicit_ctx = str(email_data.get("context_id") or "").strip()
    if explicit_ctx:
        return explicit_ctx

    email_to_id, id_to_email, id_to_contexts = _get_account_index()
    account_email = id_to_email.get(account_id or "", "")

    # Use existing deterministic classifier rules where available.
    try:
        from context_aggregator import get_aggregator
        classifier_input = {
            "from": email_data.get("from", {}),
            "subject": email_data.get("subject", ""),
            "_source": email_data.get("_source", ""),
            "_account": email_data.get("_account", "") or account_email,
        }
        ctx = get_aggregator().classify_email(classifier_input)
        if ctx and ctx != "unknown":
            return ctx
    except Exception:
        pass

    # Fallback: if account maps to a single context, use that.
    if account_id:
        contexts = id_to_contexts.get(account_id, [])
        if len(contexts) == 1:
            return contexts[0]

    return None

def _email_metadata(email_id: str, email_info: Dict) -> Tuple[Optional[str], Optional[str]]:
    """Return (account_id, context_id) for briefing item filtering."""
    email_data = email_info.get("email_data", {}) or {}
    account_id = _infer_account_id(email_id, email_data)
    context_id = _infer_context_id(email_data, account_id)
    return account_id, context_id

def invalidate_briefing_cache() -> None:
    """Invalidate full briefing cache after mutations."""
    try:
        os.remove(BRIEFING_FULL_CACHE_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[BRIEFING] Failed to invalidate cache: {e}")

async def call_llm(prompt: str, timeout: int = 30) -> Optional[str]:
    """
    Call the primary local OpenAI-compatible runtime for briefing generation.
    """
    runtime = get_primary_chat_runtime()
    try:
        return await run_primary_chat_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            timeout=float(timeout),
            runtime=runtime,
        )
    except httpx.TimeoutException:
        print(f"[BRIEFING] {runtime.label} timeout after {timeout}s")
        return None
    except httpx.ConnectError:
        print(f"[BRIEFING] {runtime.label} connection error at {runtime.base_url}")
        return None
    except Exception as e:
        print(f"[BRIEFING] {runtime.label} API error: {e}")
        return None

# =============================================================================
# Snooze System
# =============================================================================
# Snooze allows users to temporarily hide items from the briefing.
# Items are stored in snoozed.json with a wake_at timestamp.
# When wake_at passes, the item reappears in its original block.

def load_snoozed_items() -> Dict:
    """Load snoozed items from disk."""
    return load_json_file(SNOOZED_FILE, {"items": []})

def save_snoozed_items(data: Dict) -> None:
    """Persist snoozed items to disk."""
    save_json_file(SNOOZED_FILE, data)

def check_and_unsnooze() -> List[str]:
    """
    Check for items whose wake_at time has passed and remove them from snooze.
    
    Called at the start of each briefing generation. Items that are "woken up"
    will automatically reappear in their original block on next briefing load.
    
    Returns:
        List of snooze IDs that were removed (now active again)
    """
    snoozed_data = load_snoozed_items()
    now = datetime.now(timezone.utc)
    unsnooze_ids = []
    
    # Separate still-snoozed from woken items
    updated_items = []
    for item in snoozed_data["items"]:
        wake_time = datetime.fromisoformat(item["wake_at"].replace('Z', '+00:00'))
        if wake_time <= now:
            unsnooze_ids.append(item["id"])
        else:
            updated_items.append(item)
    
    # Only write if something changed
    if unsnooze_ids:
        snoozed_data["items"] = updated_items
        save_snoozed_items(snoozed_data)
    
    return unsnooze_ids

def is_item_snoozed(item_id: str, item_type: str) -> bool:
    """
    Check if an item is currently snoozed (should be hidden from briefing).
    
    Args:
        item_id: The source ID (email ID or task ID)
        item_type: "email" or "task"
    
    Returns:
        True if item is snoozed and should be hidden
    """
    snoozed_data = load_snoozed_items()
    for item in snoozed_data["items"]:
        if item["source_id"] == item_id and item["type"] == item_type:
            return True
    return False

# =============================================================================
# Calendar Integration
# =============================================================================

async def get_calendar_events() -> List[Dict]:
    """
    Fetch calendar events from Decapoda-Lite API.
    
    Fetches 48-hour lookahead (today + tomorrow) to populate the runway timeline.
    Filters out:
    - Cancelled events
    - All-day events (they clutter the timeline)
    - Events with "Canceled:" prefix (sometimes not marked isCancelled)
    
    Returns:
        List of event dicts with id, title, start, end, attendees, location, webLink
    """
    DECAPODA_CALENDAR_URL = "http://localhost:8766/v1/calendar/today?days=2&limit=50"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(DECAPODA_CALENDAR_URL)
            response.raise_for_status()
            data = response.json()
            
            events = []
            for event in data.get("value", []):
                # Skip cancelled events
                if event.get("isCancelled", False):
                    continue
                
                # Skip events with "Canceled:" in title (sometimes not marked isCancelled)
                subject = event.get("subject", "")
                if subject.lower().startswith("canceled:") or subject.lower().startswith("cancelled:"):
                    continue
                
                # Skip all-day events (start at midnight) - they clutter the timeline
                start = event.get("start", "")
                if "T00:00:00" in start:
                    continue
                
                events.append({
                    "id": event.get("id"),
                    "title": event.get("subject"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "attendees": event.get("attendees", []),
                    "location": event.get("location"),
                    "webLink": event.get("webLink")
                })
            
            return events
    except Exception as e:
        print(f"[BRIEFING] Failed to fetch calendar events: {e}")
        return []

async def generate_active_threads(emails: List[Dict], tasks: List[Dict]) -> List[Dict]:
    """Generate active threads using LLM"""
    cache = load_json_file(BRIEFING_CACHE_FILE, {})
    cache_key = "active_threads"
    
    # Check cache (30 min expiry)
    if cache_key in cache:
        cached_time = datetime.fromisoformat(cache["active_threads"]["timestamp"])
        if datetime.now(timezone.utc) - cached_time < timedelta(minutes=30):
            return cache["active_threads"]["data"]
    
    # Prepare data for LLM
    thread_data = []
    
    # Add recent emails (past 7 days) 
    for email_id, email_info in emails.items() if isinstance(emails, dict) else enumerate(emails):
        email_data = email_info.get("email_data", email_info) if isinstance(emails, dict) else email_info
        analysis = email_info.get("analysis", {}) if isinstance(emails, dict) else {}
        
        if days_since(email_data.get("received", "")) <= 7:
            thread_data.append({
                "type": "email",
                "id": email_id if isinstance(emails, dict) else email_data.get("id", str(email_id)),
                "subject": email_data.get("subject", ""),
                "from": email_data.get("from", {}).get("name", ""),
                "date": email_data.get("received", ""),
                "summary": analysis.get("summary", "")
            })
    
    # Add recent tasks
    for task in tasks:
        if task.get("source_type") != "email" and days_since(task.get("created_at", "")) <= 7:
            thread_data.append({
                "type": "task",
                "id": task["id"],
                "title": task["title"],
                "description": task.get("description", ""),
                "date": task.get("created_at", "")
            })
    
    if not thread_data:
        return []
    
    prompt = f"""Given these emails and tasks from the past week, identify distinct projects or conversation threads. 
    Group related items by project, company, or theme. For each thread, provide a JSON object with:
    - title: Descriptive thread name (e.g., "MCPP Patent Opposition", "BioBlend Technical Partnership")
    - participants: List of person names (not email addresses)
    - status: One-line status description
    - next_action: One-line next action needed
    - items: List of item IDs that belong to this thread
    - last_activity: Most recent date from items in thread
    
    Data: {json.dumps(thread_data, indent=2)}
    
    Return only a JSON array of thread objects. If no clear threads emerge, return empty array."""
    
    try:
        llm_response = await call_llm(prompt)
        if llm_response:
            # Try to parse JSON response
            import re
            json_match = re.search(r'\[.*\]', llm_response, re.DOTALL)
            if json_match:
                threads = json.loads(json_match.group())
                
                # Add calculated fields
                for thread in threads:
                    if "last_activity" in thread:
                        thread["days_since_activity"] = days_since(thread["last_activity"])
                
                # Cache result
                cache["active_threads"] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": threads
                }
                save_json_file(BRIEFING_CACHE_FILE, cache)
                
                return threads
    except Exception as e:
        print(f"Thread generation error: {e}")
    
    return []

PULSE_STATE_FILE = os.path.join(DATA_DIR, "pulse_state.json")

def load_pulse_state() -> Dict:
    """Load accumulated pulse state"""
    return load_json_file(PULSE_STATE_FILE, {"entries": {}, "week_start": None})

def save_pulse_state(state: Dict) -> None:
    """Save pulse state"""
    save_json_file(PULSE_STATE_FILE, state)

def reset_pulse_state() -> None:
    """Reset pulse state for new week"""
    save_pulse_state({"entries": {}, "week_start": datetime.now(timezone.utc).isoformat()})

async def generate_weekly_pulse(emails: List[Dict]) -> str:
    """Generate weekly pulse - stateful, accumulates each weekday until reset"""
    
    # Load existing state
    state = load_pulse_state()
    today = datetime.now(timezone.utc).strftime("%A")  # e.g., "Monday"
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Check if we already have today's entry (cache for 4 hours)
    if today_key in state.get("entries", {}):
        entry = state["entries"][today_key]
        try:
            entry_time = datetime.fromisoformat(entry.get("timestamp", ""))
            if datetime.now(timezone.utc) - entry_time < timedelta(hours=4):
                # Return accumulated pulse
                return _format_accumulated_pulse(state)
        except:
            pass
    
    # Get emails from past 7 days
    week_emails = []
    action_items = 0
    decisions_needed = 0
    
    if isinstance(emails, dict):
        for email_id, email_info in emails.items():
            email_data = email_info.get("email_data", {})
            analysis = email_info.get("analysis", {})
            
            if days_since(email_data.get("received", "")) <= 7:
                classification = analysis.get("classification", "")
                if classification == "action_item":
                    action_items += 1
                elif classification == "needs_response":
                    decisions_needed += 1
                    
                week_emails.append({
                    "subject": email_data.get("subject", ""),
                    "from": email_data.get("from", {}).get("name", ""),
                    "summary": analysis.get("summary", ""),
                    "classification": classification
                })
    else:
        for email_info in emails:
            email_data = email_info.get("email_data", email_info)
            analysis = email_info.get("analysis", {})
            
            if days_since(email_data.get("received", "")) <= 7:
                classification = analysis.get("classification", "")
                if classification == "action_item":
                    action_items += 1
                elif classification == "needs_response":
                    decisions_needed += 1
                    
                week_emails.append({
                    "subject": email_data.get("subject", ""),
                    "from": email_data.get("from", {}).get("name", ""),
                    "summary": analysis.get("summary", ""),
                    "classification": classification
                })
    
    # Get calendar events from past 7 days
    calendar_summary = ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("http://localhost:8766/v1/calendar/today?days=7&limit=50")
            if response.status_code == 200:
                events = response.json().get("value", [])
                meeting_count = len([e for e in events if not e.get("isCancelled", False)])
                calendar_summary = f"You had {meeting_count} meetings scheduled this week."
    except:
        calendar_summary = ""
    
    if not week_emails:
        return f"Quiet week on email. {calendar_summary}"
    
    # Build narrative prompt
    stats = f"Stats: {len(week_emails)} emails processed, {action_items} action items, {decisions_needed} needing response."
    
    prompt = f"""Write a brief weekly executive summary for a CTO in narrative style.

{stats}
{calendar_summary}

Key emails this week:
{json.dumps(week_emails[:15], indent=2)}

Write 2-3 short paragraphs covering:
1. Key business activities (customers, partners, deals)
2. Administrative/operational items (legal, finance, HR)
3. What needs attention going forward

Be concise and direct. No fluff. Start with "This week..." """
    
    try:
        llm_response = await call_llm(prompt, timeout=45)
        if llm_response:
            pulse = llm_response.strip()
            
            # Save to stateful pulse (accumulates by day)
            state["entries"][today_key] = {
                "day": today,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "summary": pulse,
                "stats": {"emails": len(week_emails), "action_items": action_items, "decisions": decisions_needed}
            }
            save_pulse_state(state)
            
            return _format_accumulated_pulse(state)
    except Exception as e:
        print(f"Pulse generation error: {e}")
    
    return "Unable to generate weekly pulse at this time."

def _format_accumulated_pulse(state: Dict) -> str:
    """Format accumulated pulse entries into a single display"""
    entries = state.get("entries", {})
    if not entries:
        return "No pulse data yet this week."
    
    # Sort entries by date
    sorted_entries = sorted(entries.items(), key=lambda x: x[0])
    
    parts = []
    for date_key, entry in sorted_entries:
        day = entry.get("day", "")
        summary = entry.get("summary", "")
        stats = entry.get("stats", {})
        
        # Format: **Monday** (12 emails, 3 action items)\n summary
        stat_line = f"({stats.get('emails', 0)} emails, {stats.get('action_items', 0)} action items)"
        parts.append(f"**{day}** {stat_line}\n{summary}")
    
    return "\n\n---\n\n".join(parts)

# =============================================================================
# Block Builders
# =============================================================================
# Each block builder creates data for one section of the briefing UI.
# Items are filtered (skip snoozed) and sorted by priority/urgency.

def build_decisions_block(emails: Dict, contacts: Dict) -> List[Dict]:
    """
    Build Block 1: Decisions Waiting on You.
    
    Shows high-priority emails (T1/T2/INT contacts) that need response or action.
    These are the "red alert" items - decisions only you can make.
    
    Sorting: Urgency (high → low), then days waiting (oldest first)
    """
    decisions = []
    
    for email_id, email_info in emails.items():
        # Briefing should only include deterministic trusted senders.
        if not _is_trusted_sender(email_info):
            continue

        if is_item_snoozed(email_id, "email"):
            continue
        
        # Skip items already marked as done/archived
        if email_info.get("briefing_handled"):
            continue
        if email_info.get("status") in ("done", "archived"):
            continue
            
        email_data = email_info.get("email_data", {})
        analysis = email_info.get("analysis", {})
        
        # Check if needs response or action item from high-priority contacts
        classification = analysis.get("classification", "")
        contact_tier = _normalize_trust_tag(email_info.get("contact_tier"))
        
        # Accept both old format (T1/T2/INT) and new format (tier1/tier2/internal)
        high_priority_tiers = ["t1", "t2", "int", "tier1", "tier2", "internal"]
        if classification in ["needs_response", "action_item"] and contact_tier in high_priority_tiers:
            from_info = email_data.get("from", {})
            account_id, context_id = _email_metadata(email_id, email_info)
            
            # Normalize tier badge for display
            tier_display = {"tier1": "T1", "tier2": "T2", "internal": "INT", "t1": "T1", "t2": "T2", "int": "INT"}.get(contact_tier, contact_tier.upper())
            
            received_raw = email_data.get("received", "")
            try:
                received_dt = datetime.fromisoformat(received_raw.replace("Z", "+00:00")) if received_raw else None
                received_display = received_dt.strftime("%b %d") if received_dt else ""
            except (ValueError, AttributeError):
                received_display = ""
            
            decisions.append({
                "id": email_id,  # Use the email_id from the loop
                "type": "email",
                "sender_name": from_info.get("name", "Unknown"),
                "tier_badge": tier_display,
                "subject": email_data.get("subject", "No subject"),
                "days_waiting": days_since(received_raw),
                "received_date": received_display,
                "received_at": received_raw,
                "summary": analysis.get("summary", "No summary"),
                "urgency": analysis.get("urgency", "low"),
                "source_url": email_data.get("webLink", ""),
                "account_id": account_id,
                "context_id": context_id,
            })
    
    # Sort by urgency then days waiting
    urgency_order = {"high": 3, "medium": 2, "low": 1}
    decisions.sort(key=lambda x: (urgency_order.get(x["urgency"], 1), x["days_waiting"]), reverse=True)
    
    return decisions

async def build_runway_block(tasks: List[Dict]) -> Dict:
    """
    Build Block 2: Today's Runway.
    
    Shows a horizontal timeline of calendar events for today and tomorrow,
    plus a collapsible section of tasks in todo/inprogress columns.
    
    The timeline shows:
    - Meeting blocks sized by duration
    - NOW marker with red line
    - Overlap detection (yellow = overlap, red = triple-booked)
    - Clickable blocks to open in Office 365
    
    Returns dict with:
    - timeline_items: List of meeting dicts with time, duration, title, etc.
    - today_tasks: List of task dicts (non-time-specific work)
    - work_windows: (TODO) Gaps between meetings for focused work
    - current_time: Current time in HH:MM format
    """
    today = datetime.now(PT).date()
    
    # Get calendar events for today
    calendar_events = await get_calendar_events()
    
    # Get tasks due today
    today_tasks = []
    for task in tasks:
        if is_item_snoozed(task["id"], "task"):
            continue
            
        # Only show "inprogress" tasks in Briefing (todo stays in Kanban)
        if task["column"] == "inprogress":
            today_tasks.append({
                "id": task["id"],
                "type": "task",
                "title": task["title"],
                "time": None,  # Tasks don't have specific times
                "energy": task.get("energy", "low_stakes")
            })
    
    # Build timeline items (today only)
    timeline_items = []
    
    # Add calendar events (meetings)
    for event in calendar_events:
        raw_start = event["start"].replace('Z', '+00:00')
        start_time = datetime.fromisoformat(raw_start)
        # Graph API returns UTC times (often without tz marker) — assume UTC if naive
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        # Convert to Pacific for date comparison and display
        start_pt = start_time.astimezone(PT)
        event_date = start_pt.date()
        
        # Include today only (Tomorrow removed to simplify timeline)
        if event_date == today:
            attendees = event.get("attendees", [])
            # Filter to real human attendees (exclude self, rooms, resources)
            other_attendees = [
                att for att in attendees 
                if _is_real_person(att)
            ]
            attendee_names = [att.get("name", "Unknown") for att in other_attendees if att.get("name")]
            
            day_label = "Today"
            
            # Parse end time
            raw_end = event.get("end", event["start"]).replace('Z', '+00:00')
            end_time = datetime.fromisoformat(raw_end)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            end_pt = end_time.astimezone(PT)
            
            # Calculate duration in minutes
            duration_mins = int((end_pt - start_pt).total_seconds() / 60)
            if duration_mins <= 0 or duration_mins > 480:  # Cap at 8 hours
                duration_mins = 60  # Default 1 hour
            
            timeline_items.append({
                "type": "meeting",
                "day": day_label,
                "date": event_date.isoformat(),
                "time": start_pt.strftime("%H:%M"),
                "end_time": end_pt.strftime("%H:%M"),
                "duration_mins": duration_mins,
                "title": event["title"],
                "attendees_count": len(other_attendees),
                "attendee_names": attendee_names,
                "location": event.get("location", ""),
                "webLink": event.get("webLink", "")
            })
    
    # Add work windows calculation
    work_windows = []
    # TODO: Calculate work windows between meetings
    
    # Sort by date first, then time
    return {
        "timeline_items": sorted(timeline_items, key=lambda x: (x.get("date", ""), x.get("time", "00:00"))),
        "today_tasks": today_tasks,
        "work_windows": work_windows,
        "current_time": datetime.now(PT).strftime("%H:%M")
    }

def build_people_waiting_block(emails: Dict, contacts: Dict, decisions_ids: List[str]) -> List[Dict]:
    """Build Block 4: Incoming Tasks & Action Items"""
    people_waiting = []
    
    for email_id, email_info in emails.items():
        # Briefing should only include deterministic trusted senders.
        if not _is_trusted_sender(email_info):
            continue

        if email_id in decisions_ids or is_item_snoozed(email_id, "email"):
            continue
        
        # Skip items already marked as done/archived
        if email_info.get("briefing_handled"):
            continue
        if email_info.get("status") in ("done", "archived"):
            continue
            
        email_data = email_info.get("email_data", {})
        analysis = email_info.get("analysis", {})
        
        # Check if needs response and from known contact
        if not email_data.get("isRead", True):  # Unread emails
            contact_tier = _normalize_trust_tag(email_info.get("contact_tier"))
            from_info = email_data.get("from", {})
            days_waiting = days_since(email_data.get("received", ""))
            tier_weight = calculate_tier_weight(contact_tier)
            account_id, context_id = _email_metadata(email_id, email_info)

            people_waiting.append({
                "id": email_id,
                "type": "email",
                "name": from_info.get("name", "Unknown"),
                "tier": contact_tier.upper() if contact_tier else "",
                "subject": email_data.get("subject", "No subject"),
                "days_waiting": days_waiting,
                "action_needed": analysis.get("action_needed", "Review email"),
                "sort_weight": tier_weight * days_waiting,
                "source_url": email_data.get("webLink", ""),
                "account_id": account_id,
                "context_id": context_id,
            })
    
    # Sort by weight (tier × days)
    people_waiting.sort(key=lambda x: x["sort_weight"], reverse=True)
    
    return people_waiting

def build_stale_block(tasks: List[Dict], emails: Dict) -> List[Dict]:
    """Build Block 6: Stale/Aging items"""
    stale_items = []
    
    # Stale tasks (in todo/inprogress for >3 days)
    for task in tasks:
        if is_item_snoozed(task["id"], "task"):
            continue
            
        if task["column"] in ["todo", "inprogress"]:
            days_stale = days_since(task.get("stuck_since", task.get("updated_at", "")))
            if days_stale > 3:
                stale_items.append({
                    "id": task["id"],
                    "type": "task",
                    "title": task["title"],
                    "days_stale": days_stale,
                    "source": "Kanban task",
                    "source_url": None
                })
    
    # Old action items without tasks (>2 days)
    for email_id, email_info in emails.items():
        # Briefing should only include deterministic trusted senders.
        if not _is_trusted_sender(email_info):
            continue

        if is_item_snoozed(email_id, "email") or email_info.get("converted_to_task", False):
            continue
            
        analysis = email_info.get("analysis", {})
        email_data = email_info.get("email_data", {})
        
        if analysis.get("classification") in ["action_item", "needs_response"]:
            days_old = days_since(email_data.get("received", ""))
            if days_old > 2:
                account_id, context_id = _email_metadata(email_id, email_info)
                stale_items.append({
                    "id": email_id,
                    "type": "email",
                    "title": email_data.get("subject", "No subject"),
                    "days_stale": days_old,
                    "source": "Email action item",
                    "source_url": email_data.get("webLink", ""),
                    "account_id": account_id,
                    "context_id": context_id,
                })
    
    # Sort by days stale
    stale_items.sort(key=lambda x: x["days_stale"], reverse=True)
    
    return stale_items

async def generate_full_briefing() -> Dict:
    """Generate the complete briefing data"""
    try:
        print(f"[DEBUG] Starting briefing generation...")
        
        # Check and unsnooze items
        check_and_unsnooze()
        
        # Load data
        processed_emails = load_json_file(PROCESSED_EMAILS_FILE, {})
        emails = processed_emails.get("emails", {})
        print(f"[DEBUG] Loaded {len(emails)} emails")
        
        tasks = load_json_file(TASKS_FILE, [])
        print(f"[DEBUG] Loaded {len(tasks)} tasks")
        
        contacts = load_json_file(CONTACTS_FILE, {})
        snoozed_data = load_snoozed_items()
        
        # Build blocks
        print(f"[DEBUG] Building decision block...")
        decisions = build_decisions_block(emails, contacts)
        
        print(f"[DEBUG] Building runway block...")
        runway = await build_runway_block(tasks)
        
        print(f"[DEBUG] Building people waiting block...")
        people_waiting = build_people_waiting_block(emails, contacts, [d["id"] for d in decisions])
        
        print(f"[DEBUG] Building stale block...")
        stale_items = build_stale_block(tasks, emails)
        
        # Generate LLM-powered content with timeouts and fallbacks
        print(f"[DEBUG] Generating threads...")
        try:
            threads = await generate_active_threads(emails, tasks)
        except Exception as e:
            print(f"[DEBUG] Thread generation failed: {e}")
            threads = []
            
        print(f"[DEBUG] Generating pulse...")
        try:
            pulse = await generate_weekly_pulse(emails)
        except Exception as e:
            print(f"[DEBUG] Pulse generation failed: {e}")
            pulse = "Unable to generate weekly pulse - LLM service unavailable"
        
        print(f"[DEBUG] Briefing generation completed")
        
        briefing_result = {
            "generated_at": get_pt_time_str(),
            "blocks": {
                "decisions": {
                    "title": "DECISIONS WAITING ON YOU",
                    "items": decisions,
                    "count": len(decisions),
                    "always_expanded": True
                },
                "runway": {
                    "title": "TODAY'S RUNWAY",
                    "data": runway,
                    "count": len(runway.get("timeline_items", [])) + len(runway.get("today_tasks", []))
                },
                "threads": {
                    "title": "ACTIVE THREADS", 
                    "items": threads,
                    "count": len(threads)
                },
                "people": {
                    "title": "INCOMING TASKS & ACTION ITEMS",
                    "items": people_waiting,
                    "count": len(people_waiting)
                },
                "pulse": {
                    "title": "THIS WEEK'S PULSE",
                    "content": pulse,
                    "generated_at": get_pt_time_str()
                },
                "stale": {
                    "title": "STALE / AGING",
                    "items": stale_items,
                    "count": len(stale_items),
                    "collapsed": True
                }
            },
            "snoozed": {
                "items": snoozed_data["items"],
                "count": len(snoozed_data["items"])
            }
        }
        
        # Save to cache with timestamp
        cache_data = {
            "briefing": briefing_result,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": BRIEFING_FULL_CACHE_SCHEMA_VERSION,
        }
        try:
            save_json_file(BRIEFING_FULL_CACHE_FILE, cache_data)
            print(f"[DEBUG] Briefing saved to cache")
        except Exception as e:
            print(f"[ERROR] Failed to save briefing cache: {e}")
        
        return briefing_result
    except Exception as e:
        print(f"[ERROR] Briefing generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def snooze_item(item_id: str, item_type: str, source_id: str, title: str, 
                context: str, wake_at: str, original_block: str) -> str:
    """Snooze an item"""
    snoozed_data = load_snoozed_items()
    
    snooze_id = str(uuid.uuid4())
    snoozed_item = {
        "id": snooze_id,
        "type": item_type,
        "source_id": source_id,
        "title": title,
        "context": context,
        "snoozed_at": datetime.now(timezone.utc).isoformat(),
        "wake_at": wake_at,
        "snooze_label": "custom",  # TODO: Determine label based on wake_at
        "original_block": original_block
    }
    
    snoozed_data["items"].append(snoozed_item)
    save_snoozed_items(snoozed_data)
    invalidate_briefing_cache()
    
    return snooze_id

def unsnooze_item(snooze_id: str) -> bool:
    """Unsnooze an item"""
    snoozed_data = load_snoozed_items()
    
    updated_items = [item for item in snoozed_data["items"] if item["id"] != snooze_id]
    
    if len(updated_items) < len(snoozed_data["items"]):
        snoozed_data["items"] = updated_items
        save_snoozed_items(snoozed_data)
        invalidate_briefing_cache()
        return True
    
    return False

def mark_item_done(item_id: str, item_type: str, archived: bool = False) -> bool:
    """Mark an item as done/handled or archived"""
    status = "archived" if archived else "done"
    
    if item_type == "email":
        # Mark email as handled in processed_emails.json
        processed_emails = load_json_file(PROCESSED_EMAILS_FILE, {})
        emails = processed_emails.get("emails", {})
        
        if item_id in emails:
            emails[item_id]["briefing_handled"] = True
            emails[item_id]["handled_at"] = datetime.now(timezone.utc).isoformat()
            emails[item_id]["status"] = status
            
            processed_emails["emails"] = emails
            save_json_file(PROCESSED_EMAILS_FILE, processed_emails)
            invalidate_briefing_cache()
            return True
            
    elif item_type == "task":
        # Move task to done/archived column
        tasks = load_json_file(TASKS_FILE, [])
        updated = False
        for task in tasks:
            if task["id"] == item_id:
                task["column"] = status
                task["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated = True
                break

        if updated:
            save_json_file(TASKS_FILE, tasks)
            invalidate_briefing_cache()
            return True
        return False
    
    return False
