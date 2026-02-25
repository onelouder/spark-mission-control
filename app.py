#!/usr/bin/env python3
"""
Mission Control - Kanban Dashboard with Email/Calendar Integration
FastAPI backend that connects to Decapoda-Lite API
"""

import json
import os
import time
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import asdict

import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, WebSocket, WebSocketDisconnect, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Import emergency authentication
from auth import (
    require_auth, verify_session, create_session, get_login_page, 
    setup_default_password, hash_password, verify_password,
    AUTH_USERNAME, AUTH_PASSWORD_HASH
)

# Import our new email modules
from contacts import refresh_contact_rankings, load_contacts
from pipeline import sync_and_process_emails, get_dashboard_data, load_processed_emails
from analyzer import test_llm_connection

# Import briefing module
from briefing import (
    generate_full_briefing, generate_active_threads, generate_weekly_pulse,
    snooze_item, unsnooze_item, mark_item_done, load_json_file, get_cached_briefing,
    reset_pulse_state
)

# Import context aggregator for multi-source email/calendar
from context_aggregator import (
    get_aggregator, get_contexts, set_context_filter, get_context_filter,
    get_accounts, set_account_filter, get_account_filter, get_accounts_for_context
)

# Import queue module for agent task management
from agent_queue import (
    get_all_items, get_item, create_item, update_item, delete_item,
    get_items_by_column, get_stats, open_in_helix,
    QueueItemCreate, QueueItemUpdate
)

# Import agent router for Synapse WebSocket
from agent_router import (
    router as agent_router,
    synapse_websocket_endpoint,
    get_fleet_status,
    get_agent_config,
    save_agent_config
)

# Import activity WebSocket broadcaster
from activity_websocket import activity_broadcaster

# Import X-Cognis Venture Engine integration
try:
    from venture_integration import register_venture_routes
    VENTURE_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Venture Engine not available: {e}")
    VENTURE_ENGINE_AVAILABLE = False

app = FastAPI(title="Mission Control", description="Kanban Dashboard with Email/Calendar Integration")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ============================================================================
# EMERGENCY AUTHENTICATION SETUP
# ============================================================================

# Setup default password if not configured
CURRENT_PASSWORD_HASH = setup_default_password()

@app.get("/login")
async def login_page():
    """Emergency login page"""
    return HTMLResponse(content=get_login_page())

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Process login"""
    if username == AUTH_USERNAME and verify_password(password, CURRENT_PASSWORD_HASH):
        session_token = create_session(username)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="session_token", 
            value=session_token,
            max_age=8*60*60,  # 8 hours
            httponly=True,
            secure=False  # Set to True in production with HTTPS
        )
        return response
    else:
        return HTMLResponse(content=get_login_page().replace(
            '</form>',
            '<div class="error">Invalid username or password</div></form>'
        ))

@app.get("/logout")
async def logout():
    """Logout endpoint"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response

# Register X-Cognis Venture Engine routes
if VENTURE_ENGINE_AVAILABLE:
    register_venture_routes(app)

# Background task for periodic briefing refresh
async def periodic_briefing_refresh():
    """Background task that refreshes briefing cache every 15 minutes"""
    while True:
        try:
            await asyncio.sleep(15 * 60)  # 15 minutes
            print(f"[BACKGROUND] Starting periodic briefing refresh...")
            await generate_full_briefing()
            print(f"[BACKGROUND] Briefing refresh completed at {datetime.now()}")
        except Exception as e:
            print(f"[BACKGROUND] Briefing refresh failed: {e}")
            # Continue the loop even on failure

# Background task for periodic email pipeline sync
async def periodic_email_sync():
    """Background task that syncs email pipeline every 30 minutes"""
    # Initial delay to let system stabilize
    await asyncio.sleep(60)
    
    while True:
        try:
            print(f"[BACKGROUND] Starting periodic email pipeline sync...")
            result = await sync_and_process_emails(max_emails=50)
            new_count = result.get("new_processed", 0)
            print(f"[BACKGROUND] Email sync completed: {new_count} new emails processed")
            
            # Refresh briefing if we got new emails
            if new_count > 0:
                print(f"[BACKGROUND] Refreshing briefing with new emails...")
                await generate_full_briefing()
                
        except Exception as e:
            print(f"[BACKGROUND] Email sync failed: {e}")
        
        await asyncio.sleep(30 * 60)  # 30 minutes

@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    print(f"[STARTUP] Starting background briefing refresh task...")
    asyncio.create_task(periodic_briefing_refresh())
    
    print(f"[STARTUP] Starting background email sync task (every 30 min)...")
    asyncio.create_task(periodic_email_sync())
    
    print(f"[STARTUP] Bot activity monitoring disabled (dependency issue)")
    # monitor = get_monitor()
    # asyncio.create_task(monitor.start_monitoring(check_interval=30))  # Check every 30 seconds
    
    # Start Synapse agent router for WebSocket multiplexing
    print(f"[STARTUP] Starting Synapse agent router...")
    await agent_router.start()
    
    # Start activity WebSocket broadcaster for real-time updates
    print(f"[STARTUP] Starting activity WebSocket broadcaster...")
    await activity_broadcaster.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown"""
    print(f"[SHUTDOWN] Bot activity monitoring was disabled")
    # monitor = get_monitor()
    # monitor.stop_monitoring()
    
    print(f"[SHUTDOWN] Stopping Synapse agent router...")
    await agent_router.stop()
    
    print(f"[SHUTDOWN] Stopping activity WebSocket broadcaster...")
    await activity_broadcaster.stop()

# Configuration
DECAPODA_BASE_URL = "http://localhost:8766"
DATA_DIR = "data"
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
FOCUS_FILE = os.path.join(DATA_DIR, "focus.json")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Models
class Task(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    column: str  # unsorted, todo, inprogress, done, archive
    energy: Optional[str] = None  # high_burn, low_stakes, brain_dead
    source_type: Optional[str] = None  # email, calendar, manual
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    created_at: str
    updated_at: str
    stuck_since: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    energy: Optional[str] = None
    notes: Optional[str] = None
    position: Optional[int] = None

class TaskReorder(BaseModel):
    task_id: str
    column: str
    position: int

class QuickTask(BaseModel):
    title: str
    column: Optional[str] = "unsorted"

class FocusSession(BaseModel):
    task_id: str
    started_at: str
    mode: str  # "timer" or "pomodoro"

class EmailAction(BaseModel):
    action: str  # "archive", "snooze", "create-task"
    
class EmailToTask(BaseModel):
    task_title: Optional[str] = None
    task_description: Optional[str] = None

# Briefing models
class SnoozeRequest(BaseModel):
    item_id: str
    type: str  # email, task, thread
    source_id: str
    title: str
    context: str
    wake_at: str
    original_block: str

class ItemDoneRequest(BaseModel):
    item_id: str
    type: str

# Data persistence
def load_tasks() -> List[Dict]:
    """Load tasks from JSON file"""
    try:
        with open(TASKS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_tasks(tasks: List[Dict]) -> None:
    """Save tasks to JSON file"""
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)

def load_focus_session() -> Optional[Dict]:
    """Load current focus session"""
    try:
        with open(FOCUS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def save_focus_session(session: Optional[Dict]) -> None:
    """Save focus session to JSON file"""
    if session is None:
        # Remove file if no active session
        try:
            os.remove(FOCUS_FILE)
        except FileNotFoundError:
            pass
    else:
        with open(FOCUS_FILE, 'w') as f:
            json.dump(session, f, indent=2)

# =============================================================================
# Helper Functions
# =============================================================================
# Note: Email classification is handled by analyzer.py (LLM-based via Ollama).
# The functions here are for task/Kanban operations only.

def get_energy_for_task(title: str) -> str:
    """Assign energy level based on task content"""
    title_lower = title.lower()
    
    if any(word in title_lower for word in ["urgent", "critical", "deadline", "important", "complex", "meeting", "decision"]):
        return "high_burn"
    elif any(word in title_lower for word in ["update", "check", "review", "organize", "file", "simple"]):
        return "brain_dead"
    else:
        return "low_stakes"

async def fetch_from_decapoda(endpoint: str) -> Dict:
    """Fetch data from Decapoda API"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{DECAPODA_BASE_URL}{endpoint}")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Decapoda API: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Decapoda API error: {str(e)}")

# Routes
@app.get("/")
async def dashboard(request: Request, username: str = Depends(require_auth)):
    """Serve the main dashboard (Kanban)"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/email")
async def email_dashboard(request: Request, username: str = Depends(require_auth)):
    """Serve the email dashboard"""
    return templates.TemplateResponse("email.html", {"request": request})

def is_priority_contact(email_address: str, contacts: Dict) -> bool:
    """Check if email is from a priority contact (top20, top100, or partner domain)"""
    email_lower = email_address.lower()
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""
    
    # Check top20
    for contact in contacts.get("top20", []):
        contact_email = contact.get("email", "").lower() if isinstance(contact, dict) else str(contact).lower()
        if contact_email == email_lower:
            return True
    
    # Check top100
    for contact in contacts.get("top100", []):
        contact_email = contact.get("email", "").lower() if isinstance(contact, dict) else str(contact).lower()
        if contact_email == email_lower:
            return True
    
    # Check partner domains
    if domain in contacts.get("partner_domains", []):
        return True
    
    # Check pinned contacts (can be strings or dicts)
    for contact in contacts.get("pinned_contacts", []):
        contact_email = contact.get("email", "").lower() if isinstance(contact, dict) else str(contact).lower()
        if contact_email == email_lower:
            return True
    
    return False


def should_auto_archive(email: Dict, config: Dict) -> bool:
    """Check if an email matches auto-archive patterns"""
    patterns = config.get("auto_archive_patterns", [])
    subject = email.get("subject", "").lower()
    from_info = email.get("from", {})
    from_addr = from_info.get("address", "").lower() if isinstance(from_info, dict) else str(from_info).lower()
    
    for pattern in patterns:
        subject_match = pattern.get("subject_contains", "").lower()
        from_match = pattern.get("from_contains", "").lower()
        is_reply = pattern.get("is_reply", False)
        
        # Check subject pattern
        if subject_match and subject_match not in subject:
            continue
        
        # Check from pattern (if specified)
        if from_match and from_match not in from_addr:
            continue
        
        # Check if it's a reply (Re: prefix)
        if is_reply and not subject.startswith("re:"):
            continue
        
        # All conditions matched
        return True
    
    return False


@app.get("/api/sync/email")
async def sync_email():
    """Fetch emails from Decapoda - only create tasks for priority contacts"""
    email_data = await fetch_from_decapoda("/v1/email/inbox")
    
    # Load contacts for priority check
    contacts_path = os.path.join(DATA_DIR, "contacts.json")
    contacts = {}
    if os.path.exists(contacts_path):
        with open(contacts_path) as f:
            contacts = json.load(f)
    
    # Load config for auto-archive patterns
    config_path = os.path.join(DATA_DIR, "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    
    tasks = load_tasks()
    existing_email_ids = {task["source_id"] for task in tasks if task["source_type"] == "email"}
    
    new_tasks = []
    auto_archived = 0
    current_time = datetime.now(timezone.utc).isoformat()
    
    for email in email_data.get("value", []):
        if email["id"] not in existing_email_ids and not email.get("isRead", False):
            sender_email = email["from"]["address"]
            
            # ONLY create tasks for priority contacts
            if not is_priority_contact(sender_email, contacts):
                continue
            
            # Check if this should be auto-archived
            column = "done" if should_auto_archive(email, config) else "unsorted"
            if column == "done":
                auto_archived += 1
            
            # Create task for priority contact email
            task = {
                "id": str(uuid.uuid4()),
                "title": f"📧 {email['subject']}",
                "description": f"From: {email['from']['name']} <{email['from']['address']}>",
                "column": column,
                "energy": get_energy_for_task(email["subject"]),
                "source_type": "email",
                "source_id": email["id"],
                "source_url": email.get("webLink", ""),
                "created_at": current_time,
                "updated_at": current_time,
                "stuck_since": current_time,
                "priority_contact": True,
                "auto_archived": column == "done"
            }
            new_tasks.append(task)
    
    # Add new tasks to existing tasks
    all_tasks = tasks + new_tasks
    save_tasks(all_tasks)
    
    return {"new_tasks": len(new_tasks), "auto_archived": auto_archived, "tasks": new_tasks}

@app.get("/api/sync/calendar")
async def sync_calendar():
    """Fetch calendar events from Decapoda and return timeline events"""
    calendar_data = await fetch_from_decapoda("/v1/calendar/next")
    
    events = []
    for event in calendar_data.get("value", []):
        if not event.get("isCancelled", False):
            events.append({
                "id": event["id"],
                "title": event["subject"],
                "start": event["start"],
                "end": event["end"],
                "location": event.get("location", ""),
                "organizer": event["organizer"]["name"] if event.get("organizer") else "",
                "url": event.get("webLink", "")
            })
    
    return {"events": events}

@app.get("/api/tasks")
async def get_tasks():
    """Get all tasks"""
    tasks = load_tasks()
    
    # Update stuck_since for tasks that haven't moved
    current_time = datetime.now(timezone.utc).isoformat()
    for task in tasks:
        if not task.get("stuck_since"):
            task["stuck_since"] = task["updated_at"]
        # Ensure position exists
        if task.get("position") is None:
            task["position"] = 0
    
    # Sort by position within each column
    tasks.sort(key=lambda t: (t.get("column", "unsorted"), t.get("position", 0)))
    
    return {"tasks": tasks}

@app.post("/api/tasks")
async def create_task(task_data: QuickTask):
    """Create a new task (from quick-add or inline add)"""
    tasks = load_tasks()
    
    # Accept any column string (frontend manages custom columns)
    # Only fall back to unsorted if column is None/empty
    column = task_data.column if task_data.column else "unsorted"
    
    # Calculate position (insert at top of target column)
    column_tasks = [t for t in tasks if t.get("column") == column]
    position = 0  # Top of column
    # Shift existing tasks down
    for t in column_tasks:
        t["position"] = t.get("position", 0) + 1
    
    current_time = datetime.now(timezone.utc).isoformat()
    new_task = {
        "id": str(uuid.uuid4()),
        "title": task_data.title,
        "description": "",
        "column": column,
        "position": position,
        "energy": get_energy_for_task(task_data.title),
        "source_type": "manual",
        "source_id": None,
        "source_url": None,
        "created_at": current_time,
        "updated_at": current_time,
        "stuck_since": current_time
    }
    
    tasks.append(new_task)
    save_tasks(tasks)
    
    return new_task

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task_update: TaskUpdate):
    """Update a task"""
    tasks = load_tasks()
    
    task_index = None
    for i, task in enumerate(tasks):
        if task["id"] == task_id:
            task_index = i
            break
    
    if task_index is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Update task
    current_time = datetime.now(timezone.utc).isoformat()
    task = tasks[task_index]
    old_column = task.get("column")
    
    if task_update.title is not None:
        task["title"] = task_update.title
    if task_update.description is not None:
        task["description"] = task_update.description
    if task_update.energy is not None:
        task["energy"] = task_update.energy
    if task_update.notes is not None:
        task["notes"] = task_update.notes
    
    # If column changed, reset stuck_since and position
    if task_update.column is not None and task_update.column != old_column:
        task["column"] = task_update.column
        task["stuck_since"] = current_time
        # Put at top of new column
        task["position"] = 0
        # Shift other tasks in new column down
        for t in tasks:
            if t["id"] != task_id and t.get("column") == task_update.column:
                t["position"] = t.get("position", 0) + 1
    
    if task_update.position is not None:
        task["position"] = task_update.position
    
    task["updated_at"] = current_time
    tasks[task_index] = task
    
    save_tasks(tasks)
    return task

@app.post("/api/tasks/reorder")
async def reorder_tasks(reorder_data: TaskReorder):
    """Reorder a task within or between columns"""
    tasks = load_tasks()
    
    # Find the task
    task = None
    for t in tasks:
        if t["id"] == reorder_data.task_id:
            task = t
            break
    
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    old_column = task.get("column")
    new_column = reorder_data.column
    new_position = reorder_data.position
    
    # Get tasks in the target column (excluding the moved task)
    column_tasks = [t for t in tasks if t.get("column") == new_column and t["id"] != reorder_data.task_id]
    column_tasks.sort(key=lambda t: t.get("position", 0))
    
    # Insert the task at the new position
    column_tasks.insert(new_position, task)
    
    # Reassign positions
    for i, t in enumerate(column_tasks):
        t["position"] = i
    
    # Update task column if changed
    if old_column != new_column:
        task["column"] = new_column
        task["stuck_since"] = datetime.now(timezone.utc).isoformat()
    
    task["position"] = new_position
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    save_tasks(tasks)
    return {"success": True, "task": task}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task"""
    tasks = load_tasks()
    
    tasks = [task for task in tasks if task["id"] != task_id]
    save_tasks(tasks)
    
    return {"deleted": True}

@app.post("/api/tasks/{task_id}/to-kanban")
async def task_to_kanban(task_id: str):
    """Move task to kanban inbox (unsorted column)"""
    tasks = load_tasks()
    
    for task in tasks:
        if task["id"] == task_id:
            task["column"] = "unsorted"
            task["show_in_briefing"] = False
            break
    
    save_tasks(tasks)
    return {"moved": True, "column": "unsorted"}

@app.post("/api/tasks/{task_id}/snooze")
async def snooze_task_endpoint(task_id: str, snooze_data: dict):
    """Snooze a task for specified hours"""
    from datetime import datetime, timezone, timedelta
    
    hours = snooze_data.get("hours", 1)
    wake_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["snoozed_until"] = wake_at.isoformat()
            task["show_in_briefing"] = False
            break
    
    save_tasks(tasks)
    return {"snoozed": True, "wake_at": wake_at.isoformat()}

@app.delete("/api/tasks/column/{column}")
async def delete_column_tasks(column: str):
    """Delete all tasks in a column"""
    tasks = load_tasks()
    original_count = len(tasks)
    
    tasks = [task for task in tasks if task.get("column") != column]
    deleted_count = original_count - len(tasks)
    
    save_tasks(tasks)
    
    return {"deleted": deleted_count, "column": column}


@app.post("/api/tasks/auto-archive")
async def bulk_auto_archive():
    """Apply auto-archive rules to existing unsorted tasks"""
    # Load config
    config_path = os.path.join(DATA_DIR, "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    
    tasks = load_tasks()
    archived = []
    current_time = datetime.now(timezone.utc).isoformat()
    
    for task in tasks:
        # Only process unsorted email tasks
        if task.get("column") != "unsorted" or task.get("source_type") != "email":
            continue
        
        # Simulate email dict for should_auto_archive
        email = {
            "subject": task.get("title", "").replace("📧 ", ""),
            "from": {"address": task.get("description", "").split("<")[-1].rstrip(">")}
        }
        
        if should_auto_archive(email, config):
            task["column"] = "done"
            task["updated_at"] = current_time
            task["auto_archived"] = True
            archived.append(task["title"])
    
    save_tasks(tasks)
    return {"archived": len(archived), "items": archived}


@app.post("/api/focus/start")
async def start_focus(focus_data: FocusSession):
    """Start focus mode on a task"""
    # Verify task exists
    tasks = load_tasks()
    task = next((t for t in tasks if t["id"] == focus_data.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Save focus session
    session = {
        "task_id": focus_data.task_id,
        "task_title": task["title"],
        "started_at": focus_data.started_at,
        "mode": focus_data.mode
    }
    save_focus_session(session)
    
    return session

@app.post("/api/focus/stop")
async def stop_focus():
    """End focus mode"""
    save_focus_session(None)
    return {"stopped": True}

@app.get("/api/focus/status")
async def get_focus_status():
    """Get current focus session status"""
    session = load_focus_session()
    if session:
        # Calculate elapsed time
        started = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        elapsed = datetime.now(timezone.utc) - started
        session["elapsed_seconds"] = int(elapsed.total_seconds())
    
    return {"session": session}

# Email API Routes
@app.get("/api/email/dashboard")
async def get_email_dashboard():
    """Get processed emails organized for dashboard display"""
    try:
        dashboard_data = get_dashboard_data()
        return dashboard_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard data: {str(e)}")

@app.post("/api/email/sync")
async def sync_emails():
    """Trigger email sync and processing pipeline"""
    try:
        config_data = {}
        try:
            with open(os.path.join(DATA_DIR, "config.json"), 'r') as f:
                config_data = json.load(f)
        except FileNotFoundError:
            pass
        
        max_emails = config_data.get("max_emails_per_sync", 100)
        result = await sync_and_process_emails(max_emails)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email sync failed: {str(e)}")

@app.get("/api/email/filtered")
async def get_filtered_emails():
    """Get filtered/dropped emails for audit"""
    try:
        processed_data = load_processed_emails()
        filtered_emails = processed_data.get("filtered", {})
        
        # Format for display
        audit_data = []
        for email_id, email_data in filtered_emails.items():
            audit_data.append({
                "id": email_id,
                "subject": email_data["email_data"].get("subject", "No subject"),
                "from": email_data["email_data"].get("from", {}),
                "received": email_data["email_data"].get("received"),
                "filter_reason": email_data.get("filter_reason", "Unknown"),
                "stage": email_data.get("stages", {})
            })
        
        return {"filtered_emails": audit_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get filtered emails: {str(e)}")


@app.get("/api/triage")
async def get_triage_queue():
    """Get emails for triage mode - one at a time processing"""
    try:
        # Get unread emails from Decapoda
        email_data = await fetch_from_decapoda("/v1/email/inbox?unread=true")
        
        # Load contacts for priority marking
        contacts_path = os.path.join(DATA_DIR, "contacts.json")
        contacts = {}
        if os.path.exists(contacts_path):
            with open(contacts_path) as f:
                contacts = json.load(f)
        
        # Load already processed/snoozed email IDs
        processed_data = load_processed_emails()
        processed_ids = set(processed_data.get("triaged", {}).keys())
        
        # Filter and enrich emails
        queue = []
        for email in email_data.get("value", []):
            if email["id"] in processed_ids:
                continue
                
            sender_email = email.get("from", {}).get("address", "")
            is_priority = is_priority_contact(sender_email, contacts)
            
            queue.append({
                "id": email["id"],
                "subject": email.get("subject", "(No subject)"),
                "from_name": email.get("from", {}).get("name", "Unknown"),
                "from_email": sender_email,
                "preview": email.get("bodyPreview", "")[:200],
                "received": email.get("receivedDateTime"),
                "is_priority": is_priority,
                "web_link": email.get("webLink", "")
            })
        
        # Sort: priority contacts first, then by date
        queue.sort(key=lambda x: (not x["is_priority"], x.get("received", "")))
        
        return {
            "queue": queue,
            "total": len(queue),
            "priority_count": sum(1 for e in queue if e["is_priority"])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get triage queue: {str(e)}")


@app.post("/api/triage/{email_id}")
async def triage_email(email_id: str, action: str, snooze_until: Optional[str] = None):
    """Process a triaged email - archive, snooze, task, or skip"""
    try:
        processed_data = load_processed_emails()
        processed_data.setdefault("triaged", {})
        
        # Record the triage action
        processed_data["triaged"][email_id] = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "snooze_until": snooze_until
        }
        
        # Save processed data
        processed_file = os.path.join(DATA_DIR, "processed_emails.json")
        with open(processed_file, "w") as f:
            json.dump(processed_data, f, indent=2)
        
        # Execute action via Decapoda if needed
        if action == "archive":
            # Mark as read in Outlook
            await fetch_from_decapoda(f"/v1/email/{email_id}/read", method="POST")
        
        return {"success": True, "action": action}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Triage action failed: {str(e)}")


@app.post("/api/email/{email_id}/action")
async def email_action(email_id: str, action_data: EmailAction):
    """Mark email action (archive, snooze, create-task)"""
    try:
        processed_data = load_processed_emails()
        emails = processed_data.get("emails", {})
        
        if email_id not in emails:
            raise HTTPException(status_code=404, detail="Email not found")
        
        # Update email with action
        emails[email_id]["action"] = action_data.action
        emails[email_id]["action_at"] = datetime.now(timezone.utc).isoformat()
        
        # Save back to file
        processed_data["emails"] = emails
        with open(os.path.join(DATA_DIR, "processed_emails.json"), 'w') as f:
            json.dump(processed_data, f, indent=2)
        
        return {"success": True, "action": action_data.action}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark email action: {str(e)}")

@app.post("/api/email/{email_id}/spam")
async def mark_email_spam(email_id: str):
    """Mark email as spam and add sender to blocklist"""
    try:
        # Load processed emails
        processed_data = load_processed_emails()
        emails = processed_data.get("emails", {})
        
        if email_id not in emails:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_info = emails[email_id]
        email_data = email_info["email_data"]
        from_info = email_data.get("from", {})
        
        if isinstance(from_info, dict):
            sender_address = from_info.get("address", "")
        else:
            sender_address = str(from_info)
        
        if not sender_address:
            raise HTTPException(status_code=400, detail="No sender address found")
        
        # Extract domain
        domain = sender_address.split("@")[-1] if "@" in sender_address else None
        
        # Load config
        config_path = os.path.join(DATA_DIR, "config.json")
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        
        blocked_domains = config.get("blocked_domains", [])
        blocked_patterns = config.get("blocked_patterns", [])
        
        result = {"email_id": email_id, "sender": sender_address}
        
        # Add domain to blocklist (prefer domain over full address)
        if domain and domain not in blocked_domains:
            blocked_domains.append(domain)
            config["blocked_domains"] = blocked_domains
            result["blocked_domain"] = domain
        elif sender_address not in blocked_patterns:
            # Fall back to blocking the full address pattern
            blocked_patterns.append(sender_address)
            config["blocked_patterns"] = blocked_patterns
            result["blocked_pattern"] = sender_address
        
        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Mark email as spam/deleted
        emails[email_id]["action"] = "spam"
        emails[email_id]["action_at"] = datetime.now(timezone.utc).isoformat()
        
        # Move to filtered
        filtered = processed_data.get("filtered", {})
        email_info["filter_reason"] = f"Manually marked as spam (blocked: {domain or sender_address})"
        filtered[email_id] = email_info
        del emails[email_id]
        
        processed_data["emails"] = emails
        processed_data["filtered"] = filtered
        
        with open(os.path.join(DATA_DIR, "processed_emails.json"), 'w') as f:
            json.dump(processed_data, f, indent=2)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark as spam: {str(e)}")

@app.post("/api/email/{email_id}/draft")
async def draft_email_response(email_id: str):
    """Generate a draft reply for an email using local Ollama LLM."""
    try:
        processed_data = load_processed_emails()
        emails = processed_data.get("emails", {})

        if email_id not in emails:
            raise HTTPException(status_code=404, detail="Email not found in processed emails")

        email_info = emails[email_id]
        email_data = email_info.get("email_data", email_info)

        from_info = email_data.get("from", {})
        sender_name = from_info.get("name", "") if isinstance(from_info, dict) else ""
        sender_addr = from_info.get("address", "") if isinstance(from_info, dict) else str(from_info)
        subject     = email_data.get("subject", "(no subject)")
        summary     = email_info.get("summary", email_data.get("bodyPreview", ""))[:500]
        action      = email_info.get("action_needed", "")
        deadline    = email_info.get("deadline", "")

        deadline_line = f"Deadline/urgency noted: {deadline}." if deadline else ""
        action_line   = f"Required action: {action}." if action else ""

        prompt = f"""You are drafting a professional email reply on behalf of Jason Wells (engineer, founder at Novvi).

ORIGINAL EMAIL
From: {sender_name} <{sender_addr}>
Subject: {subject}
Summary: {summary}
{action_line}
{deadline_line}

Write a concise, professional reply. Be direct. Do not use filler phrases like "I hope this email finds you well." Do not include a subject line. Just the body of the reply, signed "Jason".

DRAFT:"""

        # Call local Ollama (llama3.1:8b — fast, avoids gateway contention)
        ollama_url = "http://localhost:11434/api/generate"
        timeout    = httpx.Timeout(45.0)
        draft_text = None

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ollama_url, json={
                "model":  "llama3.1:8b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 300}
            })
            if response.status_code == 200:
                draft_text = response.json().get("response", "").strip()

        if not draft_text:
            raise HTTPException(status_code=503, detail="LLM unavailable — try again shortly")

        return {
            "draft":   draft_text,
            "subject": f"Re: {subject}",
            "to":      sender_addr,
            "to_name": sender_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Draft generation failed: {str(e)}")

@app.post("/api/email/{email_id}/to-task")
async def email_to_task(email_id: str, task_data: EmailToTask):
    """Create a Kanban task from an email"""
    try:
        processed_data = load_processed_emails()
        emails = processed_data.get("emails", {})
        
        if email_id not in emails:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_info = emails[email_id]
        email_data = email_info["email_data"]
        analysis = email_info.get("analysis", {})
        
        # Create task from email
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Build task title and description
        task_title = task_data.task_title or f"📧 {email_data.get('subject', 'Email Task')}"
        
        description_parts = []
        if task_data.task_description:
            description_parts.append(task_data.task_description)
        else:
            description_parts.append(analysis.get("summary", ""))
            if analysis.get("action_needed"):
                description_parts.append(f"Action: {analysis['action_needed']}")
        
        from_info = email_data.get("from", {})
        if isinstance(from_info, dict):
            from_display = f"{from_info.get('name', '')} <{from_info.get('address', '')}>"
        else:
            from_display = str(from_info)
        description_parts.append(f"From: {from_display}")
        
        # Map urgency to energy level
        urgency = analysis.get("urgency", "low")
        energy_map = {"high": "high_burn", "medium": "low_stakes", "low": "brain_dead"}
        energy = energy_map.get(urgency, "low_stakes")
        
        new_task = {
            "id": str(uuid.uuid4()),
            "title": task_title,
            "description": "\n".join(description_parts),
            "column": "unsorted",
            "energy": energy,
            "source_type": "email",
            "source_id": email_id,
            "source_url": email_data.get("webLink", ""),
            "created_at": current_time,
            "updated_at": current_time,
            "stuck_since": current_time
        }
        
        # Add to tasks
        tasks = load_tasks()
        tasks.append(new_task)
        save_tasks(tasks)
        
        # Mark email as converted to task
        emails[email_id]["converted_to_task"] = True
        emails[email_id]["task_id"] = new_task["id"]
        emails[email_id]["converted_at"] = current_time
        
        processed_data["emails"] = emails
        with open(os.path.join(DATA_DIR, "processed_emails.json"), 'w') as f:
            json.dump(processed_data, f, indent=2)
        
        return {"success": True, "task": new_task}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task from email: {str(e)}")

@app.get("/api/contacts")
async def get_contacts():
    """Get current contact rankings"""
    try:
        contacts = load_contacts()
        return contacts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get contacts: {str(e)}")

@app.post("/api/contacts/refresh")
async def refresh_contacts():
    """Rebuild contact rankings"""
    try:
        contacts = await refresh_contact_rankings()
        return {"success": True, "contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh contacts: {str(e)}")


class ContactUpdate(BaseModel):
    list_type: str  # "top20", "top100", "pinned_contacts", "partner_domains"
    email: Optional[str] = None
    domain: Optional[str] = None
    name: Optional[str] = None


@app.post("/api/contacts/add")
async def add_contact(contact: ContactUpdate):
    """Add a contact to a priority list"""
    contacts_path = os.path.join(DATA_DIR, "contacts.json")
    with open(contacts_path) as f:
        contacts = json.load(f)
    
    if contact.list_type == "partner_domains":
        if contact.domain and contact.domain not in contacts.get("partner_domains", []):
            contacts.setdefault("partner_domains", []).append(contact.domain)
    elif contact.list_type in ["top20", "top100", "pinned_contacts"]:
        if contact.email:
            new_contact = {
                "email": contact.email.lower(),
                "name": contact.name or contact.email.split("@")[0],
                "count": 0,
                "domain": contact.email.split("@")[-1] if "@" in contact.email else ""
            }
            contacts.setdefault(contact.list_type, []).append(new_contact)
    
    with open(contacts_path, "w") as f:
        json.dump(contacts, f, indent=2)
    
    return {"success": True, "contacts": contacts}


@app.delete("/api/contacts/remove")
async def remove_contact(list_type: str, email: str = None, domain: str = None):
    """Remove a contact from a priority list"""
    contacts_path = os.path.join(DATA_DIR, "contacts.json")
    with open(contacts_path) as f:
        contacts = json.load(f)
    
    if list_type == "partner_domains" and domain:
        contacts["partner_domains"] = [d for d in contacts.get("partner_domains", []) if d != domain]
    elif list_type in ["top20", "top100", "pinned_contacts"] and email:
        contacts[list_type] = [c for c in contacts.get(list_type, []) if c.get("email", "").lower() != email.lower()]
    
    with open(contacts_path, "w") as f:
        json.dump(contacts, f, indent=2)
    
    return {"success": True, "contacts": contacts}


@app.get("/api/config")
async def get_config(username: str = Depends(require_auth)):
    """Get pipeline configuration"""
    try:
        config_file = os.path.join(DATA_DIR, "config.json")
        with open(config_file, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Configuration not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}")

@app.put("/api/config")
async def update_config(config: dict, username: str = Depends(require_auth)):
    """Update pipeline configuration"""
    try:
        config_file = os.path.join(DATA_DIR, "config.json")
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        return {"success": True, "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")

@app.get("/api/brief")
async def get_morning_brief():
    """
    Generate morning brief summary.
    
    Returns a quick overview of today's meetings, tasks by column,
    and identified work windows (gaps between meetings).
    
    Note: This is a legacy endpoint. The /api/briefing endpoint provides
    a more comprehensive briefing with LLM-generated content.
    """
    # Get today's date for the brief
    today = datetime.now(timezone.utc).date()
    
    # Get tasks by column
    tasks = load_tasks()
    task_counts = {}
    for task in tasks:
        column = task["column"]
        task_counts[column] = task_counts.get(column, 0) + 1
    
    # Get calendar events (48-hour lookahead: today + tomorrow, including past events)
    calendar_data = await fetch_from_decapoda("/v1/calendar/today?days=2")
    today_events = []
    
    for event in calendar_data.get("value", []):
        if not event.get("isCancelled", False):
            today_events.append(event)
    
    # Calculate work windows (simplified for MVP)
    # Finds gaps between meetings longer than 1 hour
    work_windows = []
    if today_events:
        sorted_events = sorted(today_events, key=lambda x: x["start"])
        for i in range(len(sorted_events) - 1):
            end_current = datetime.fromisoformat(sorted_events[i]["end"].replace("Z", "+00:00"))
            start_next = datetime.fromisoformat(sorted_events[i + 1]["start"].replace("Z", "+00:00"))
            gap_hours = (start_next - end_current).seconds // 3600
            if gap_hours >= 1:
                work_windows.append(f"{gap_hours}-hour window at {end_current.strftime('%I %p')}")
    
    brief = {
        "date": today.isoformat(),
        "task_counts": task_counts,
        "meeting_count": len(today_events),
        "work_windows": work_windows,
        "summary": f"Today: {len(today_events)} meetings, {sum(task_counts.values())} tasks. " + 
                  (f"{work_windows[0]} for deep work." if work_windows else "No significant work windows.")
    }
    
    return brief

# Triage Mode
@app.get("/triage")
async def triage_page(request: Request):
    """Serve the triage mode page"""
    return templates.TemplateResponse("triage.html", {"request": request})


# Contacts Management
@app.get("/contacts")
async def contacts_page(request: Request):
    """Serve the contacts management page"""
    return templates.TemplateResponse("contacts.html", {"request": request})


# Briefing Routes
@app.get("/briefing")
async def briefing_page(request: Request):
    """Serve the briefing HTML page"""
    return templates.TemplateResponse("briefing.html", {"request": request})

@app.get("/nexus")
async def nexus_page(request: Request):
    """Nexus multi-agent chat interface (Performance Optimized)"""
    return templates.TemplateResponse("nexus.html", {"request": request})

@app.get("/nexus-enhanced")
async def nexus_enhanced_page(request: Request):
    """Nexus Enhanced - Multi-agent chat with agent spawning and management"""
    return templates.TemplateResponse("nexus-enhanced.html", {"request": request})

@app.get("/nexus-v2")
async def nexus_v2_page(request: Request):
    """Nexus v2 - Multi-pane agent interface with adaptive grid (Phase 1)"""
    return templates.TemplateResponse("nexus-v2.html", {"request": request})

# Removed duplicate route - synapse now serves synapse.html below

@app.get("/cockpit")
async def cockpit_page():
    """Redirect cockpit to queue (chat panel integrated there)"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/queue", status_code=302)

@app.get("/api/briefing")
async def get_briefing_data():
    """Get briefing data (from cache if available, otherwise generate fresh)
    
    Runway/Tasks are always fresh (read from tasks.json).
    LLM blocks (pulse, threads) use cache to avoid expensive regeneration.
    """
    from briefing import build_runway_block
    
    try:
        # First check for cached briefing
        cached_briefing = get_cached_briefing()
        if cached_briefing:
            result = cached_briefing["briefing"]
            result["cached"] = True
            result["cached_at"] = cached_briefing["cached_at"]
            
            # Always refresh runway/tasks (real-time, cheap operation)
            tasks = load_tasks()
            fresh_runway = await build_runway_block(tasks)
            result["blocks"]["runway"]["data"] = fresh_runway
            result["blocks"]["runway"]["count"] = len(fresh_runway.get("timeline_items", [])) + len(fresh_runway.get("today_tasks", []))
            
            return result
        
        # No cache exists, generate fresh (blocking)
        briefing_data = await generate_full_briefing()
        briefing_data["cached"] = False
        return briefing_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get briefing: {str(e)}")

@app.post("/api/briefing/refresh")
async def refresh_briefing_data():
    """Force refresh briefing data (bypassing cache)"""
    try:
        # Generate fresh briefing (this saves to cache internally)
        briefing_data = await generate_full_briefing()
        briefing_data["cached"] = False
        return briefing_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh briefing: {str(e)}")

@app.get("/api/briefing/threads")
async def get_briefing_threads():
    """Generate active threads (LLM call)"""
    try:
        processed_emails = load_json_file(os.path.join(DATA_DIR, "processed_emails.json"), {})
        emails = list(processed_emails.get("emails", {}).values())
        tasks = load_json_file(os.path.join(DATA_DIR, "tasks.json"), [])
        
        threads = await generate_active_threads(emails, tasks)
        return {"threads": threads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate threads: {str(e)}")

@app.get("/api/briefing/pulse")
async def get_briefing_pulse():
    """Generate this week's pulse (LLM call)"""
    try:
        processed_emails = load_json_file(os.path.join(DATA_DIR, "processed_emails.json"), {})
        emails = processed_emails.get("emails", {})
        
        pulse = await generate_weekly_pulse(emails)
        return {"pulse": pulse, "generated_at": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate pulse: {str(e)}")

@app.post("/api/briefing/pulse/reset")
async def reset_briefing_pulse():
    """Reset weekly pulse state - clears accumulated entries"""
    try:
        reset_pulse_state()
        return {"status": "ok", "message": "Pulse reset. Will regenerate on next refresh."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset pulse: {str(e)}")

@app.get("/api/briefing/runway")
async def get_briefing_runway():
    """Today's calendar + task timeline"""
    try:
        tasks = load_json_file(os.path.join(DATA_DIR, "tasks.json"), [])
        from briefing import build_runway_block
        runway_data = await build_runway_block(tasks)
        return runway_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate runway: {str(e)}")

@app.get("/api/agents/status")
async def get_agent_status():
    """Get status of all configured agents from cached status file"""
    try:
        # Read from status file updated by cron jobs
        status_file = os.path.join(DATA_DIR, "agent_status.json")
        
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
                return data
        
        # Return default agents if no status file exists yet
        default_agents = [
            {"id": "jarvis", "model": "claude-opus-4-5", "context_pct": 0, "status": "idle", "channel": "unknown"},
            {"id": "aria", "model": "claude-sonnet-4", "context_pct": 0, "status": "idle", "channel": "unknown"},
            {"id": "peter", "model": "claude-sonnet-4", "context_pct": 0, "status": "idle", "channel": "unknown"},
            {"id": "watson", "model": "claude-sonnet-4", "context_pct": 0, "status": "idle", "channel": "unknown"},
            {"id": "willb", "model": "claude-sonnet-4", "context_pct": 0, "status": "idle", "channel": "unknown"},
            {"id": "elon", "model": "claude-sonnet-4", "context_pct": 0, "status": "idle", "channel": "unknown"},
        ]
        
        return {
            "agents": default_agents,
            "total_sessions": 0,
            "fetched_at": datetime.now().isoformat(),
            "note": "Using defaults - status file not found"
        }
            
    except Exception as e:
        return {"agents": [], "error": str(e)}


@app.get("/api/cron/status")
async def get_cron_status():
    """Get recent cron job runs from cached status file"""
    try:
        status_file = os.path.join(DATA_DIR, "cron_runs.json")
        
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
                return data
        
        # Return empty if no runs logged yet
        return {
            "runs": [],
            "updated_at": None,
            "note": "No cron runs logged yet"
        }
            
    except Exception as e:
        return {"runs": [], "error": str(e)}


@app.post("/api/cron/log")
async def log_cron_run(request: Request):
    """Log a cron job run result (called by cron jobs)"""
    try:
        body = await request.json()
        status_file = os.path.join(DATA_DIR, "cron_runs.json")
        
        # Load existing runs
        runs = []
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
                runs = data.get("runs", [])
        
        # Update or add this run
        run_id = body.get("id")
        found = False
        for i, run in enumerate(runs):
            if run.get("id") == run_id:
                runs[i] = {**run, **body}
                found = True
                break
        
        if not found:
            runs.insert(0, body)
        
        # Keep only last 20 runs
        runs = runs[:20]
        
        # Save
        with open(status_file, 'w') as f:
            json.dump({
                "runs": runs,
                "updated_at": datetime.now().isoformat()
            }, f, indent=2)
        
        return {"success": True}
        
    except Exception as e:
        return {"error": str(e)}


# Weather cache (refresh every 30 minutes)
_weather_cache = {"data": None, "fetched_at": None}

@app.get("/api/weather")
async def get_weather():
    """Get current weather for San Jose, CA (Jason's location)"""
    import time
    
    # Return cached if less than 30 minutes old
    if _weather_cache["data"] and _weather_cache["fetched_at"]:
        age_seconds = time.time() - _weather_cache["fetched_at"]
        if age_seconds < 1800:  # 30 minutes
            return _weather_cache["data"]
    
    try:
        async with httpx.AsyncClient() as client:
            # Get compact weather data from wttr.in
            # Format: location, condition icon, temp, humidity, wind
            response = await client.get(
                "https://wttr.in/San+Jose,CA?format=%l:+%c+%t+%h+%w",
                timeout=10.0
            )
            compact = response.text.strip() if response.status_code == 200 else None
            
            # Also get JSON for more detail
            response2 = await client.get(
                "https://wttr.in/San+Jose,CA?format=j1",
                timeout=10.0
            )
            detailed = response2.json() if response2.status_code == 200 else None
            
            # Extract key fields from JSON
            forecast_summary = None
            if detailed and "weather" in detailed:
                today = detailed["weather"][0] if detailed["weather"] else None
                if today:
                    max_temp = today.get("maxtempF", "?")
                    min_temp = today.get("mintempF", "?")
                    forecast_summary = f"High {max_temp}°F, Low {min_temp}°F"
            
            result = {
                "location": "San Jose, CA",
                "compact": compact,
                "forecast": forecast_summary,
                "fetched_at": datetime.now().isoformat()
            }
            
            # Cache the result
            _weather_cache["data"] = result
            _weather_cache["fetched_at"] = time.time()
            
            return result
            
    except Exception as e:
        return {
            "location": "San Jose, CA",
            "compact": "Unable to fetch weather",
            "error": str(e),
            "fetched_at": datetime.now().isoformat()
        }


# System Health endpoint
@app.get("/api/health")
async def get_system_health():
    """Check status of critical services for the system health widget"""
    services = []
    
    async def check_port(name: str, host: str, port: int, description: str) -> dict:
        """Check if a service is responding on a port"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                # Try to connect - for HTTP services, hit a simple endpoint
                if port == 18789:  # Moltbot gateway
                    resp = await client.get(f"http://{host}:{port}/health")
                    return {"name": name, "status": "ok" if resp.status_code == 200 else "degraded", 
                            "description": description, "port": port}
                elif port == 8766:  # Decapoda-Lite
                    resp = await client.get(f"http://{host}:{port}/health")
                    return {"name": name, "status": "ok" if resp.status_code == 200 else "degraded",
                            "description": description, "port": port}
                elif port == 11434:  # Ollama
                    resp = await client.get(f"http://{host}:{port}/api/tags")
                    return {"name": name, "status": "ok" if resp.status_code == 200 else "degraded",
                            "description": description, "port": port}
                else:
                    # Generic TCP check via socket
                    import socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    return {"name": name, "status": "ok" if result == 0 else "down",
                            "description": description, "port": port}
        except Exception as e:
            return {"name": name, "status": "down", "description": description, 
                    "port": port, "error": str(e)[:50]}
    
    # Check services in parallel
    checks = await asyncio.gather(
        check_port("Moltbot Gateway", "localhost", 18789, "AI orchestration"),
        check_port("Decapoda-Lite", "localhost", 8766, "Email/Calendar API"),
        check_port("Wyoming STT", "localhost", 10300, "Speech-to-text"),
        check_port("Wyoming TTS", "localhost", 10200, "Text-to-speech"),
        check_port("Ollama", "localhost", 11434, "Local LLM"),
        return_exceptions=True
    )
    
    for check in checks:
        if isinstance(check, dict):
            services.append(check)
        else:
            services.append({"name": "Unknown", "status": "error", "error": str(check)[:50]})
    
    # Add Mission Control (always ok since we're serving this)
    services.insert(0, {"name": "Mission Control", "status": "ok", 
                        "description": "This dashboard", "port": 3000})
    
    # Add Rate Limit Proxy monitoring
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:18790/_health")
            if resp.status_code == 200:
                services.append({"name": "Rate Limit Proxy", "status": "ok", 
                               "description": "Anthropic API rate limiting", "port": 18790})
            else:
                services.append({"name": "Rate Limit Proxy", "status": "degraded", 
                               "description": "Anthropic API rate limiting", "port": 18790})
    except Exception:
        services.append({"name": "Rate Limit Proxy", "status": "down", 
                       "description": "Anthropic API rate limiting", "port": 18790})
    
    # Add Bot Activity Monitor status (disabled)
    try:
        # bot_status = await get_bot_activity_status()
        # active_alerts = bot_status.get("active_alerts", {}).get("total", 0)
        # monitoring_active = bot_status.get("monitoring_status") == "active"
        monitoring_active = False  # Temporarily disabled
        active_alerts = 0
        
        if monitoring_active:
            if active_alerts == 0:
                services.append({"name": "Bot Activity Monitor", "status": "ok", 
                               "description": f"No active alerts"})
            else:
                services.append({"name": "Bot Activity Monitor", "status": "warning", 
                               "description": f"{active_alerts} active alerts"})
        else:
            services.append({"name": "Bot Activity Monitor", "status": "down", 
                           "description": "Monitoring stopped"})
    except Exception:
        services.append({"name": "Bot Activity Monitor", "status": "unknown", 
                       "description": "Status check failed"})
    
    # Summary
    ok_count = sum(1 for s in services if s["status"] == "ok")
    total = len(services)
    
    return {
        "services": services,
        "summary": f"{ok_count}/{total} services healthy",
        "all_ok": ok_count == total,
        "checked_at": datetime.now().isoformat()
    }


# System Metrics endpoint (CPU, memory, disk for briefing widget)
@app.get("/api/system-metrics")
async def get_system_metrics(username: str = Depends(require_auth)):
    """Get system resource metrics for the briefing widget"""
    import subprocess
    
    metrics = {}
    
    try:
        # CPU usage (1-second sample)
        cpu_result = subprocess.run(
            ["sh", "-c", "top -bn1 | grep 'Cpu(s)' | awk '{print 100 - $8}'"],
            capture_output=True, text=True, timeout=5
        )
        if cpu_result.returncode == 0 and cpu_result.stdout.strip():
            metrics["cpu"] = {
                "percent": round(float(cpu_result.stdout.strip()), 1),
                "label": "CPU"
            }
    except:
        pass
    
    try:
        # Memory usage
        mem_result = subprocess.run(
            ["free", "-m"],
            capture_output=True, text=True, timeout=5
        )
        if mem_result.returncode == 0:
            lines = mem_result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 3:
                    total_mb = int(parts[1])
                    used_mb = int(parts[2])
                    percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0
                    metrics["memory"] = {
                        "percent": percent,
                        "used_gb": round(used_mb / 1024, 1),
                        "total_gb": round(total_mb / 1024, 1),
                        "label": "Memory"
                    }
    except:
        pass
    
    try:
        # Disk usage (root partition)
        disk_result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=5
        )
        if disk_result.returncode == 0:
            lines = disk_result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    metrics["disk"] = {
                        "percent": int(parts[4].replace('%', '')),
                        "used": parts[2],
                        "total": parts[1],
                        "label": "Disk"
                    }
    except:
        pass
    
    try:
        # Uptime
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            if days > 0:
                metrics["uptime"] = f"{days}d {hours}h"
            else:
                minutes = int((uptime_seconds % 3600) // 60)
                metrics["uptime"] = f"{hours}h {minutes}m"
    except:
        pass
    
    return {
        "metrics": metrics,
        "checked_at": datetime.now().isoformat()
    }


# Task Queue Summary endpoint (for briefing widget)
@app.get("/api/queue/summary")
async def get_queue_summary():
    """Get task queue summary for briefing widget"""
    try:
        items = get_all_items()
        # Count by column
        counts = {}
        for item in items:
            col = item.get("column", "uncategorized")
            counts[col] = counts.get(col, 0) + 1
        
        # Priority items (high priority in active/queued)
        priority_items = [
            item for item in items 
            if item.get("priority") == "high" and item.get("column") in ("active", "queued")
        ]
        
        return {
            "counts": counts,
            "total": len(items),
            "priority": len(priority_items),
            "active": counts.get("active", 0),
            "queued": counts.get("queued", 0),
            "review": counts.get("review", 0),
            "ideas": counts.get("ideas", 0),
            "checked_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "counts": {}, "total": 0}


@app.post("/api/snooze")
async def snooze_briefing_item(snooze_data: SnoozeRequest):
    """Snooze an item"""
    try:
        snooze_id = snooze_item(
            snooze_data.item_id,
            snooze_data.type,
            snooze_data.source_id,
            snooze_data.title,
            snooze_data.context,
            snooze_data.wake_at,
            snooze_data.original_block
        )
        return {"success": True, "snooze_id": snooze_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to snooze item: {str(e)}")

@app.delete("/api/snooze/{snooze_id}")
async def unsnooze_briefing_item(snooze_id: str):
    """Un-snooze an item"""
    try:
        success = unsnooze_item(snooze_id)
        if success:
            return {"success": True}
        else:
            raise HTTPException(status_code=404, detail="Snoozed item not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unsnooze item: {str(e)}")

@app.get("/api/snooze")
async def get_snoozed_items():
    """List all snoozed items"""
    try:
        from briefing import load_snoozed_items
        snoozed_data = load_snoozed_items()
        return snoozed_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get snoozed items: {str(e)}")

@app.post("/api/briefing/item/{item_id}/done")
async def mark_briefing_item_done(item_id: str, done_data: ItemDoneRequest):
    """Mark item as handled (remove from briefing)"""
    try:
        success = mark_item_done(item_id, done_data.type)
        if success:
            return {"success": True}
        else:
            raise HTTPException(status_code=404, detail="Item not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark item done: {str(e)}")

@app.post("/api/briefing/item/{item_id}/archive")
async def archive_briefing_item(item_id: str, archive_data: ItemDoneRequest):
    """Archive item (mark as not actionable, remove from briefing)"""
    try:
        # Use same logic as done - both remove from active briefing
        success = mark_item_done(item_id, archive_data.type, archived=True)
        if success:
            return {"success": True, "archived": True}
        else:
            raise HTTPException(status_code=404, detail="Item not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive item: {str(e)}")

# === Context (Life Domain) Routes ===

@app.get("/api/contexts")
async def list_contexts():
    """List all life domain contexts with status"""
    try:
        contexts = get_contexts()
        active = get_context_filter()
        return {
            "contexts": contexts,
            "active_filter": active
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get contexts: {str(e)}")

@app.post("/api/contexts/filter")
async def set_context_filter_endpoint(filter_data: dict):
    """Set active context filter (None = show all)"""
    try:
        context_id = filter_data.get("context_id")  # None means show all
        set_context_filter(context_id)
        return {"success": True, "active_filter": context_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set context filter: {str(e)}")

@app.get("/api/contexts/aggregated")
async def get_aggregated_emails_events():
    """Get emails and events from all sources with context tags"""
    try:
        aggregator = get_aggregator()
        data = await aggregator.get_aggregated_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get aggregated data: {str(e)}")

@app.get("/api/accounts")
async def list_accounts():
    """List all email accounts with status"""
    try:
        accounts = get_accounts()
        active = get_account_filter()
        return {
            "accounts": accounts,
            "active_filter": active
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get accounts: {str(e)}")

@app.post("/api/accounts/filter")
async def set_account_filter_endpoint(filter_data: dict):
    """Set active account filter (None = show all)"""
    try:
        account_id = filter_data.get("account_id")  # None means show all
        set_account_filter(account_id)
        return {"success": True, "active_filter": account_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set account filter: {str(e)}")

@app.get("/api/contexts/{context_id}/accounts")
async def get_context_accounts(context_id: str):
    """Get accounts that feed into a specific context"""
    try:
        accounts = get_accounts_for_context(context_id)
        return {"context_id": context_id, "accounts": accounts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get accounts for context: {str(e)}")

@app.get("/api/filters")
async def get_all_filters():
    """Get current filter state (both context and account)"""
    try:
        return {
            "contexts": get_contexts(),
            "accounts": get_accounts(),
            "active_context": get_context_filter(),
            "active_account": get_account_filter()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get filters: {str(e)}")

@app.post("/api/filters")
async def set_filters(filter_data: dict):
    """Set both context and account filters at once"""
    try:
        if "context_id" in filter_data:
            set_context_filter(filter_data.get("context_id"))
        if "account_id" in filter_data:
            set_account_filter(filter_data.get("account_id"))
        return {
            "success": True,
            "active_context": get_context_filter(),
            "active_account": get_account_filter()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set filters: {str(e)}")

@app.get("/api/gmail/test")
async def test_gmail_connection():
    """Test Gmail API connection"""
    try:
        from gmail_client import test_connection
        result = await test_connection()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gmail test failed: {str(e)}")

# === Health & Monitoring ===

@app.get("/api/health/detail")
async def health_check():
    """Detailed health check endpoint for monitoring"""
    import psutil
    import os
    
    checks = {
        "mission_control": "ok",
        "decapoda_lite": "unknown",
        "gmail": "unknown"
    }
    
    # Check decapoda-lite
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:8766/admin")
            checks["decapoda_lite"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["decapoda_lite"] = "down"
    
    # Check Gmail
    try:
        from gmail_client import get_client
        client = get_client()
        checks["gmail"] = "ok" if client.is_configured() else "not_configured"
    except Exception:
        checks["gmail"] = "error"
    
    # Memory usage
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    
    overall = "ok" if all(v in ("ok", "not_configured") for v in checks.values()) else "degraded"
    
    return {
        "status": overall,
        "checks": checks,
        "memory_mb": round(memory_mb, 1),
        "uptime_seconds": int(datetime.now(timezone.utc).timestamp() - process.create_time())
    }

@app.get("/api/gmail/emails")
async def get_gmail_emails(
    days: int = 7,
    limit: int = 50,
    unread_only: bool = False,
    sent_days: int = 30,
    raw: bool = False,
):
    """
    Get Gmail emails filtered by dynamic sent-mail whitelist.
    
    Whitelist = anyone you've emailed in the last `sent_days` days
              + partner domains + pinned contacts + Exchange top contacts.
    
    Set raw=true to bypass filtering (diagnostic use only).
    """
    try:
        if raw:
            from gmail_client import get_recent_emails
            emails = await get_recent_emails(days_back=days, max_results=limit)
        else:
            from gmail_client import get_filtered_emails
            emails = await get_filtered_emails(
                days_back=days,
                max_results=limit,
                unread_only=unread_only,
                sent_days_back=sent_days,
            )
        return {"emails": emails, "count": len(emails), "filtered": not raw}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get Gmail emails: {str(e)}")

@app.get("/api/gmail/whitelist")
async def get_gmail_whitelist(sent_days: int = 30):
    """
    Show the current dynamic Gmail whitelist — who's in it and why.
    Useful for debugging filter decisions.
    """
    try:
        from gmail_client import get_whitelist_summary
        summary = await get_whitelist_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get whitelist: {str(e)}")

@app.post("/api/gmail/whitelist/refresh")
async def refresh_gmail_whitelist():
    """Force a refresh of the sent-mail cache."""
    try:
        import gmail_client as gc
        gc._sent_cache["fetched_at"] = None  # invalidate
        summary = await gc.get_whitelist_summary()
        return {"refreshed": True, **summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh whitelist: {str(e)}")

@app.get("/api/gmail/events")
async def get_gmail_events(days: int = 7, limit: int = 50):
    """Get upcoming events from Google Calendar"""
    try:
        from gmail_client import get_upcoming_events
        events = await get_upcoming_events(days=days, max_results=limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get Gmail events: {str(e)}")

# === White Paper Index API ===

@app.get("/api/papers/index")
async def get_paper_index():
    """Get the white paper index"""
    try:
        from paper_index import load_index
        index = load_index()
        if not index:
            return {"status": "not_indexed", "message": "Run paper_index.py scan first"}
        return {
            "status": "ok",
            "stats": index.get("stats", {}),
            "by_domain": {k: len(v) for k, v in index.get("by_domain", {}).items()},
            "scanned_at": index.get("scanned_at")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/papers/search")
async def search_papers(q: str, limit: int = 20):
    """Search white papers"""
    try:
        from paper_index import load_index, search_papers
        index = load_index()
        if not index:
            return {"results": [], "message": "Index not found"}
        results = search_papers(index, q)[:limit]
        return {"query": q, "results": results, "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/papers/domain/{domain}")
async def get_papers_by_domain(domain: str):
    """Get papers in a specific domain"""
    try:
        from paper_index import load_index
        index = load_index()
        if not index:
            return {"papers": []}
        paper_ids = index.get("by_domain", {}).get(domain, [])
        papers = [index["papers"][pid] for pid in paper_ids if pid in index["papers"]]
        return {"domain": domain, "papers": papers, "count": len(papers)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/papers/rescan")
async def rescan_papers():
    """Rescan the papers directory"""
    try:
        from paper_index import scan_papers, save_index
        index = scan_papers()
        save_index(index)
        return {
            "status": "ok",
            "total_papers": index["stats"]["total_papers"],
            "scanned_at": index["scanned_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Agent Queue Routes
# ============================================================================

@app.get("/queue")
async def queue_page(request: Request):
    """Agent work queue page"""
    return templates.TemplateResponse("queue.html", {"request": request})


@app.get("/api/queue")
async def api_get_queue():
    """Get all queue items and stats"""
    return {
        "items": get_all_items(),
        "by_column": get_items_by_column(),
        "stats": get_stats()
    }


@app.post("/api/queue")
async def api_create_queue_item(item: QueueItemCreate):
    """Create a new queue item"""
    return create_item(item)


@app.get("/api/queue/{item_id}")
async def api_get_queue_item(item_id: str):
    """Get a specific queue item"""
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/queue/{item_id}")
async def api_update_queue_item(item_id: str, updates: QueueItemUpdate):
    """Update a queue item"""
    item = update_item(item_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.delete("/api/queue/{item_id}")
async def api_delete_queue_item(item_id: str):
    """Delete a queue item"""
    if not delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "deleted", "id": item_id}


# ============================================================================
# Task Dispatch Routes (Queue → Agent integration)
# ============================================================================

class DispatchRequest(BaseModel):
    agent_id: str
    custom_prompt: Optional[str] = None


@app.post("/api/queue/{item_id}/dispatch")
async def api_dispatch_task(item_id: str, request: DispatchRequest):
    """Dispatch a queue task to an agent via Gateway."""
    from task_dispatch import TaskDispatcher
    
    dispatcher = TaskDispatcher()
    try:
        result = await dispatcher.dispatch_task(
            item_id,
            request.agent_id,
            request.custom_prompt
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Dispatch failed"))
        return result
    finally:
        await dispatcher.disconnect()


@app.post("/api/queue/{item_id}/dispatch/auto")
async def api_dispatch_task_auto(item_id: str):
    """Auto-dispatch a queue task to the best-matched agent."""
    from task_dispatch import TaskDispatcher
    
    task = get_item(item_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    dispatcher = TaskDispatcher()
    try:
        agent_id = await dispatcher.get_agent_for_task(task)
        result = await dispatcher.dispatch_task(item_id, agent_id)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Dispatch failed"))
        return result
    finally:
        await dispatcher.disconnect()


@app.get("/api/queue/{item_id}/status")
async def api_task_status(item_id: str):
    """Check status of a dispatched task."""
    from task_dispatch import TaskDispatcher
    
    dispatcher = TaskDispatcher()
    try:
        return await dispatcher.check_task_status(item_id)
    finally:
        await dispatcher.disconnect()


class EditRequest(BaseModel):
    path: str


@app.post("/api/queue/edit")
async def api_open_in_editor(request: EditRequest):
    """Open a file in Helix via tmux"""
    result = open_in_helix(request.path)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to open editor"))
    return result


# ============================================================================
# Agent Orchestration Routes
# ============================================================================

MOLTBOT_GATEWAY = os.environ.get("MOLTBOT_GATEWAY", "http://localhost:18789")
MOLTBOT_TOKEN = os.environ.get("MOLTBOT_TOKEN", "1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c")
MOLTBOT_HOME = os.path.expanduser("~/.moltbot")

# Agent definitions (should match moltbot config)
AGENTS = {
    "jarvis": {"name": "Jarvis", "emoji": "🎩", "domain": "AI/Infra", "model": "opus"},
    "ares": {"name": "Ares", "emoji": "🛡️", "domain": "Security", "model": "sonnet"},
    "aria": {"name": "Aria", "emoji": "📚", "domain": "Research", "model": "sonnet"},
    "atlas": {"name": "Atlas", "emoji": "🏗️", "domain": "Infrastructure", "model": "sonnet"},
    "dewey": {"name": "Dewey", "emoji": "📖", "domain": "Library", "model": "sonnet"},
    "peter": {"name": "Peter", "emoji": "📈", "domain": "Finance", "model": "sonnet"},
    "watson": {"name": "Dr. Watson", "emoji": "🩺", "domain": "Medical", "model": "sonnet"},
    "willb": {"name": "Will B.", "emoji": "🏢", "domain": "CRM/Marketing", "model": "sonnet"},
    "elon": {"name": "ELon", "emoji": "🚀", "domain": "Startup", "model": "sonnet"},
    "jc": {"name": "JC", "emoji": "⚡", "domain": "General", "model": "sonnet"},
}

# Context limits by model
MODEL_CONTEXT_LIMITS = {
    "opus": 200000,
    "sonnet": 200000,
}


def get_agent_sessions(agent_id: str) -> dict:
    """Read agent's sessions.json file"""
    sessions_file = os.path.join(MOLTBOT_HOME, "agents", agent_id, "sessions", "sessions.json")
    if os.path.exists(sessions_file):
        try:
            with open(sessions_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_session_token_count(agent_id: str, session_key: str) -> Optional[int]:
    """Read session transcript to estimate token count (from file size as proxy)"""
    sessions = get_agent_sessions(agent_id)
    session_data = sessions.get(session_key, {})
    session_id = session_data.get("sessionId")
    
    if not session_id:
        return None
    
    transcript_file = os.path.join(MOLTBOT_HOME, "agents", agent_id, "sessions", f"{session_id}.jsonl")
    if os.path.exists(transcript_file):
        # Rough estimate: 4 chars per token on average
        file_size = os.path.getsize(transcript_file)
        return file_size // 4
    return None


@app.get("/api/agents")
async def api_get_agents():
    """Get all configured agents with their current status from local session files"""
    agents_status = []
    now = time.time() * 1000  # ms
    
    for agent_id, agent_info in AGENTS.items():
        status = {
            "id": agent_id,
            **agent_info,
            "status": "idle",
            "context_pct": None,
            "session_key": None,
            "updated_ago": None,
        }
        
        try:
            sessions = get_agent_sessions(agent_id)
            main_key = f"agent:{agent_id}:main"
            
            if main_key in sessions:
                session = sessions[main_key]
                status["session_key"] = main_key
                
                # Check if recently active (within 2 hours)
                updated_at = session.get("updatedAt", 0)
                age_ms = now - updated_at
                age_hours = age_ms / (1000 * 60 * 60)
                
                if age_hours < 2:
                    status["status"] = "active"
                    status["updated_ago"] = f"{int(age_ms / 60000)}m ago"
                else:
                    status["status"] = "idle"
                    status["updated_ago"] = f"{int(age_hours)}h ago"
                
                # Estimate context usage
                token_count = get_session_token_count(agent_id, main_key)
                if token_count:
                    context_limit = MODEL_CONTEXT_LIMITS.get(agent_info.get("model"), 200000)
                    status["context_pct"] = min(100, round(100 * token_count / context_limit))
                    
        except Exception as e:
            print(f"[AGENTS] Failed to get status for {agent_id}: {e}")
            status["status"] = "unknown"
        
        agents_status.append(status)
    
    return {"agents": agents_status}


class SpawnRequest(BaseModel):
    agent_id: str
    task: str
    queue_item_id: Optional[str] = None  # Link back to queue item


@app.post("/api/agents/spawn")
async def api_spawn_task(request: SpawnRequest):
    """
    Spawn a task to an agent.
    
    Currently marks the task as pending dispatch - the orchestrator cron job
    or manual /spawn command will pick it up.
    """
    if request.agent_id not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {request.agent_id}")
    
    # Update queue item to mark it for dispatch
    if request.queue_item_id:
        notes = f"[DISPATCH PENDING] Agent: {request.agent_id}\n---\n{request.task}"
        update_item(request.queue_item_id, QueueItemUpdate(
            column="active",
            session_status="pending",
            notes=notes
        ))
    
    # Create dispatch instruction file for orchestrator to pick up
    dispatch_dir = os.path.join(DATA_DIR, "dispatch_queue")
    os.makedirs(dispatch_dir, exist_ok=True)
    
    dispatch_id = f"d_{datetime.now().strftime('%Y%m%d%H%M%S')}_{request.agent_id}"
    dispatch_file = os.path.join(dispatch_dir, f"{dispatch_id}.json")
    
    with open(dispatch_file, 'w') as f:
        json.dump({
            "id": dispatch_id,
            "agent_id": request.agent_id,
            "task": request.task,
            "queue_item_id": request.queue_item_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending"
        }, f, indent=2)
    
    return {
        "status": "queued_for_dispatch",
        "dispatch_id": dispatch_id,
        "agent": request.agent_id,
        "message": f"Task queued for {AGENTS[request.agent_id]['name']}. Orchestrator will dispatch shortly."
    }


@app.get("/api/agents/sessions")
async def api_get_sessions():
    """Get all active agent sessions"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{MOLTBOT_GATEWAY}/api/sessions",
                headers={"Authorization": f"Bearer {MOLTBOT_TOKEN}"},
                params={"activeMinutes": 60, "messageLimit": 1}
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Gateway error")
            
            return response.json()
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Cron Job Routes (proxy to Moltbot gateway)
# ============================================================================

@app.get("/cron")
async def cron_page(request: Request):
    """Cron jobs control panel"""
    return templates.TemplateResponse("cron.html", {"request": request})


def read_cron_jobs_from_file() -> list:
    """Read cron jobs directly from Moltbot's cron state file"""
    cron_file = os.path.join(MOLTBOT_HOME, "cron", "jobs.json")
    if os.path.exists(cron_file):
        try:
            with open(cron_file, 'r') as f:
                data = json.load(f)
                return data.get("jobs", [])
        except Exception as e:
            print(f"[CRON] Failed to read cron file: {e}")
    return []


@app.get("/api/cron/jobs")
async def api_get_cron_jobs():
    """Get all cron jobs"""
    jobs = read_cron_jobs_from_file()
    return {"jobs": jobs}


class CronJobUpdate(BaseModel):
    enabled: Optional[bool] = None
    schedule: Optional[dict] = None


@app.patch("/api/cron/jobs/{job_id}")
async def api_update_cron_job(job_id: str, update: CronJobUpdate):
    """Update a cron job (enable/disable)"""
    # Use the gateway's internal cron API via WebSocket or file
    # For now, we'll update the file directly (simple approach)
    cron_file = os.path.join(MOLTBOT_HOME, "cron", "jobs.json")
    
    try:
        with open(cron_file, 'r') as f:
            data = json.load(f)
        
        jobs = data.get("jobs", [])
        found = False
        for job in jobs:
            if job.get("id") == job_id:
                if update.enabled is not None:
                    job["enabled"] = update.enabled
                    job["updatedAtMs"] = int(time.time() * 1000)
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        
        with open(cron_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        return {"status": "updated", "job_id": job_id}
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Cron state file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cron/jobs/{job_id}/run")
async def api_run_cron_job(job_id: str):
    """Trigger a cron job to run now"""
    # Update the job's nextRunAtMs to now to trigger immediate run
    cron_file = os.path.join(MOLTBOT_HOME, "cron", "jobs.json")
    
    try:
        with open(cron_file, 'r') as f:
            data = json.load(f)
        
        jobs = data.get("jobs", [])
        found = False
        for job in jobs:
            if job.get("id") == job_id:
                # Set next run to now
                now_ms = int(time.time() * 1000)
                if "state" not in job:
                    job["state"] = {}
                job["state"]["nextRunAtMs"] = now_ms
                job["updatedAtMs"] = now_ms
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        
        with open(cron_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        return {"status": "triggered", "job_id": job_id}
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Cron state file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== QUICK NOTES: Persistent Scratchpad =====

NOTES_FILE = os.path.join(DATA_DIR, "quick_notes.json")


class QuickNotesUpdate(BaseModel):
    content: str


@app.get("/api/notes")
async def get_quick_notes():
    """Get current quick notes"""
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"content": "", "updated_at": None}


@app.put("/api/notes")
async def update_quick_notes(notes: QuickNotesUpdate):
    """Update quick notes (auto-saved)"""
    data = {
        "content": notes.content,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    with open(NOTES_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return {"status": "saved", "updated_at": data["updated_at"]}


# ===== MORNING SUMMARY: AI-Generated Daily Briefing =====

MORNING_SUMMARY_CACHE_FILE = os.path.join(DATA_DIR, "morning_summary_cache.json")
_morning_summary_cache = {"data": None, "generated_at": 0}

@app.get("/api/morning-summary")
async def get_morning_summary(force: bool = False):
    """Generate AI morning summary combining calendar, weather, and tasks"""
    import pytz
    PT = pytz.timezone('America/Los_Angeles')
    now = datetime.now(PT)
    
    # Check cache (30 minute TTL unless forced)
    cache_age = time.time() - _morning_summary_cache["generated_at"]
    if not force and _morning_summary_cache["data"] and cache_age < 1800:
        return _morning_summary_cache["data"]
    
    # Gather context from various sources
    context_parts = []
    
    # 1. Current time context
    context_parts.append(f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')} Pacific")
    
    # 2. Weather
    try:
        weather = await get_weather()
        if weather.get("compact"):
            context_parts.append(f"Weather: {weather['compact']}, {weather.get('forecast', '')}")
    except:
        pass
    
    # 3. Calendar events today
    try:
        from context_aggregator import get_aggregator
        agg = get_aggregator()
        events = await agg.get_calendar_events(hours=12)
        if events:
            event_list = [f"- {e.get('title', 'Event')} at {e.get('start_time', '')}" for e in events[:5]]
            context_parts.append(f"Today's schedule ({len(events)} events):\n" + "\n".join(event_list))
        else:
            context_parts.append("Calendar: No events scheduled today")
    except:
        context_parts.append("Calendar: Unable to fetch")
    
    # 4. Task queue status
    try:
        items = get_all_items()
        active = [i for i in items if i.get("column") == "active"]
        queued = [i for i in items if i.get("column") == "queued"]
        context_parts.append(f"Tasks: {len(active)} active, {len(queued)} queued")
        if active:
            active_titles = [a.get("title", "?")[:40] for a in active[:3]]
            context_parts.append(f"Active tasks: {', '.join(active_titles)}")
    except:
        pass
    
    # 5. Check if it's early morning (before 9 AM) vs mid-day
    hour = now.hour
    time_context = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    
    # Build prompt for Ollama
    context_block = "\n".join(context_parts)
    prompt = f"""You are a concise executive assistant generating a morning briefing.
Given the following context, write a 2-3 sentence personalized summary for Jason to read at the start of his day.
Be warm but professional. Focus on what matters most. Don't repeat obvious information.
If there are meetings soon, mention prep time. If it's a light day, note the opportunity for focus work.

Context:
{context_block}

Write a brief, actionable morning summary (2-3 sentences max):"""

    # Call Ollama
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen3:30b-a3b",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False
                }
            )
            if resp.status_code == 200:
                result = resp.json()
                summary_text = result.get("message", {}).get("content", "").strip()
            else:
                summary_text = "Good morning. Unable to generate summary at this time."
    except Exception as e:
        summary_text = f"Good {time_context}. Check your calendar and queue for today's priorities."
    
    # Cache result
    result = {
        "summary": summary_text,
        "generated_at": now.isoformat(),
        "context_used": len(context_parts)
    }
    _morning_summary_cache["data"] = result
    _morning_summary_cache["generated_at"] = time.time()
    
    # Also persist to file for cold starts
    try:
        with open(MORNING_SUMMARY_CACHE_FILE, 'w') as f:
            json.dump(result, f, indent=2)
    except:
        pass
    
    return result


# ===== UPCOMING MEETINGS: Today's Calendar at a Glance =====

@app.get("/api/calendar/upcoming")
async def get_upcoming_meetings():
    """Get today's upcoming meetings for briefing display"""
    import pytz
    PT = pytz.timezone('America/Los_Angeles')
    now = datetime.now(PT)
    
    meetings = []
    
    try:
        # Fetch from Decapoda
        calendar_data = await fetch_from_decapoda("/v1/calendar/today?days=1")
        events = calendar_data.get("value", [])
        
        for event in events:
            try:
                title = event.get("subject", "")
                
                # Handle both direct string and nested dict formats for start/end
                start_raw = event.get("start", "")
                end_raw = event.get("end", "")
                start_str = start_raw.get("dateTime", "") if isinstance(start_raw, dict) else start_raw
                end_str = end_raw.get("dateTime", "") if isinstance(end_raw, dict) else end_raw
                
                # Handle location (can be string or dict)
                loc_raw = event.get("location", "")
                if isinstance(loc_raw, dict):
                    location = loc_raw.get("displayName", "")
                else:
                    location = loc_raw or ""
                
                # Handle organizer (can be string or dict)
                org_raw = event.get("organizer", "")
                if isinstance(org_raw, dict):
                    organizer = org_raw.get("name", org_raw.get("emailAddress", {}).get("name", ""))
                else:
                    organizer = org_raw or ""
                
                # Skip events without valid times
                if not start_str or not end_str:
                    continue
                
                # Parse times (remove trailing zeros from Microsoft format)
                start_str = start_str.replace('.0000000', '').replace('Z', '+00:00')
                end_str = end_str.replace('.0000000', '').replace('Z', '+00:00')
                
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                except:
                    continue
                
                # Calculate duration
                duration_hours = (end_dt - start_dt).total_seconds() / 3600
                
                # Skip all-day events (>= 23 hours)
                if duration_hours >= 23:
                    continue
                
                # Localize datetimes to Pacific
                if start_dt.tzinfo is None:
                    start_dt = PT.localize(start_dt)
                else:
                    start_dt = start_dt.astimezone(PT)
                
                if end_dt.tzinfo is None:
                    end_dt = PT.localize(end_dt)
                else:
                    end_dt = end_dt.astimezone(PT)
                
                # Skip events that have already ended
                if end_dt < now:
                    continue
                
                # Calculate minutes until start
                minutes_until = int((start_dt - now).total_seconds() / 60)
                
                # Determine status
                if minutes_until <= 0:
                    status = "now"
                elif minutes_until <= 15:
                    status = "soon"
                elif minutes_until <= 60:
                    status = "upcoming"
                else:
                    status = "later"
                
                meetings.append({
                    "title": title,
                    "start_time": start_dt.strftime("%I:%M %p").lstrip("0"),
                    "end_time": end_dt.strftime("%I:%M %p").lstrip("0"),
                    "location": location,
                    "organizer": organizer,
                    "status": status,
                    "minutes_until": max(0, minutes_until),
                    "duration_min": int((end_dt - start_dt).total_seconds() / 60)
                })
            except Exception as e:
                continue
        
        # Sort by start time
        meetings.sort(key=lambda x: x.get("minutes_until", 9999))
        
    except Exception as e:
        pass
    
    return {
        "meetings": meetings,
        "count": len(meetings),
        "fetched_at": now.isoformat()
    }


# ===== WEEKEND PREVIEW: Saturday/Sunday at a Glance =====

@app.get("/api/calendar/weekend")
async def get_weekend_preview():
    """Get weekend events (Saturday and Sunday) for briefing display"""
    import pytz
    from datetime import timedelta
    PT = pytz.timezone('America/Los_Angeles')
    now = datetime.now(PT)
    
    # Calculate days until Saturday
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    if weekday == 5:  # Saturday
        days_to_saturday = 0
        days_to_sunday = 1
    elif weekday == 6:  # Sunday
        days_to_saturday = -1  # Yesterday (skip)
        days_to_sunday = 0
    else:
        days_to_saturday = 5 - weekday
        days_to_sunday = 6 - weekday
    
    saturday = now.date() + timedelta(days=days_to_saturday) if days_to_saturday >= 0 else None
    sunday = now.date() + timedelta(days=days_to_sunday)
    
    weekend_events = {"saturday": [], "sunday": []}
    
    try:
        # Fetch next 7 days to ensure we cover the weekend
        calendar_data = await fetch_from_decapoda("/v1/calendar/today?days=7")
        events = calendar_data.get("value", [])
        
        for event in events:
            try:
                title = event.get("subject", "")
                
                # Handle both direct string and nested dict formats
                start_raw = event.get("start", "")
                end_raw = event.get("end", "")
                start_str = start_raw.get("dateTime", "") if isinstance(start_raw, dict) else start_raw
                end_str = end_raw.get("dateTime", "") if isinstance(end_raw, dict) else end_raw
                
                # Handle location
                loc_raw = event.get("location", "")
                if isinstance(loc_raw, dict):
                    location = loc_raw.get("displayName", "")
                else:
                    location = loc_raw or ""
                
                if not start_str or not end_str:
                    continue
                
                # Parse times
                start_str = start_str.replace('.0000000', '').replace('Z', '+00:00')
                end_str = end_str.replace('.0000000', '').replace('Z', '+00:00')
                
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                except:
                    continue
                
                # Calculate duration
                duration_hours = (end_dt - start_dt).total_seconds() / 3600
                
                # Localize to Pacific
                if start_dt.tzinfo is None:
                    start_dt = PT.localize(start_dt)
                else:
                    start_dt = start_dt.astimezone(PT)
                
                event_date = start_dt.date()
                
                # Determine if all-day event
                is_all_day = duration_hours >= 23
                
                event_data = {
                    "title": title,
                    "start_time": "All day" if is_all_day else start_dt.strftime("%I:%M %p").lstrip("0"),
                    "end_time": "" if is_all_day else end_dt.strftime("%I:%M %p").lstrip("0"),
                    "location": location,
                    "is_all_day": is_all_day
                }
                
                # Categorize by day
                if saturday and event_date == saturday:
                    weekend_events["saturday"].append(event_data)
                elif event_date == sunday:
                    weekend_events["sunday"].append(event_data)
                    
            except Exception:
                continue
        
        # Sort by start time (all-day first, then by time)
        for day in weekend_events:
            weekend_events[day].sort(key=lambda x: (not x["is_all_day"], x["start_time"]))
            
    except Exception:
        pass
    
    # Format dates for display
    saturday_str = saturday.strftime("%A, %b %d") if saturday else None
    sunday_str = sunday.strftime("%A, %b %d")
    
    return {
        "saturday": {
            "date": saturday_str,
            "events": weekend_events["saturday"] if saturday else []
        },
        "sunday": {
            "date": sunday_str,
            "events": weekend_events["sunday"]
        },
        "is_weekend": weekday in [5, 6],
        "fetched_at": now.isoformat()
    }


# ===== ACCOMPLISHMENTS: Daily Achievement Tracker =====

ACCOMPLISHMENTS_FILE = os.path.join(DATA_DIR, "accomplishments.json")

def load_accomplishments() -> Dict[str, Any]:
    """Load accomplishments from file"""
    if os.path.exists(ACCOMPLISHMENTS_FILE):
        with open(ACCOMPLISHMENTS_FILE, 'r') as f:
            return json.load(f)
    return {"items": [], "last_reset": None}

def save_accomplishments(data: Dict[str, Any]):
    """Save accomplishments to file"""
    with open(ACCOMPLISHMENTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.get("/api/accomplishments")
async def get_accomplishments():
    """Get today's accomplishments (auto-detected + manual)"""
    import pytz
    PT = pytz.timezone('America/Los_Angeles')
    now = datetime.now(PT)
    today_str = now.strftime("%Y-%m-%d")
    
    accomplishments = []
    
    # Load manual accomplishments
    data = load_accomplishments()
    
    # Auto-reset if new day
    if data.get("last_reset") != today_str:
        data = {"items": [], "last_reset": today_str}
        save_accomplishments(data)
    
    # Add manual accomplishments
    for item in data.get("items", []):
        accomplishments.append({
            "id": item.get("id"),
            "text": item.get("text"),
            "type": "manual",
            "added_at": item.get("added_at"),
            "icon": "✓"
        })
    
    # Auto-detect: Queue items completed today
    try:
        items = get_all_items()
        for item in items:
            if item.get("column") == "done":
                completed = item.get("completed_at", "")
                if completed.startswith(today_str):
                    accomplishments.append({
                        "id": f"queue_{item.get('id')}",
                        "text": item.get("title", "Task completed"),
                        "type": "queue",
                        "added_at": completed,
                        "icon": "📋"
                    })
    except:
        pass
    
    # Sort by time (newest first)
    accomplishments.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    
    return {
        "date": today_str,
        "count": len(accomplishments),
        "items": accomplishments
    }

@app.post("/api/accomplishments")
async def add_accomplishment(request: Request):
    """Add a manual accomplishment"""
    import pytz
    PT = pytz.timezone('America/Los_Angeles')
    now = datetime.now(PT)
    today_str = now.strftime("%Y-%m-%d")
    
    body = await request.json()
    text = body.get("text", "").strip()
    
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    
    data = load_accomplishments()
    
    # Auto-reset if new day
    if data.get("last_reset") != today_str:
        data = {"items": [], "last_reset": today_str}
    
    # Add new item
    new_item = {
        "id": str(uuid.uuid4())[:8],
        "text": text,
        "added_at": now.isoformat()
    }
    data["items"].append(new_item)
    save_accomplishments(data)
    
    return {"status": "added", "item": new_item}

@app.delete("/api/accomplishments/{item_id}")
async def delete_accomplishment(item_id: str):
    """Delete a manual accomplishment"""
    data = load_accomplishments()
    
    # Find and remove
    original_count = len(data.get("items", []))
    data["items"] = [i for i in data.get("items", []) if i.get("id") != item_id]
    
    if len(data["items"]) == original_count:
        raise HTTPException(status_code=404, detail="Item not found")
    
    save_accomplishments(data)
    return {"status": "deleted"}


# ===== GIT ACTIVITY WIDGET =====

# Cache for git activity
_git_activity_cache = {"data": None, "ts": 0}
GIT_ACTIVITY_CACHE_SECONDS = 600  # 10 minutes

# Repos to track (path, display name)
GIT_REPOS = [
    ("/home/jwells/projects/mission-control", "mission-control"),
    ("/home/jwells/clawd", "clawd"),
    ("/home/jwells/projects/hecl-memory", "hecl-memory"),
    ("/home/jwells/projects/moltbot", "moltbot"),
]

@app.get("/api/git-activity")
async def get_git_activity(force: bool = False):
    """Get recent git commits from tracked repos"""
    import subprocess
    
    global _git_activity_cache
    
    now = time.time()
    if not force and _git_activity_cache["data"] and (now - _git_activity_cache["ts"]) < GIT_ACTIVITY_CACHE_SECONDS:
        return _git_activity_cache["data"]
    
    commits = []
    
    for repo_path, repo_name in GIT_REPOS:
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            continue  # Skip non-git directories
            
        try:
            # Try last 24h first, then fall back to last 7 days, then any commits
            for since_arg in ["24 hours ago", "7 days ago", None]:
                cmd = ["git", "log", "--oneline", "-n", "5", "--format=%H|%h|%s|%ar|%an"]
                if since_arg:
                    cmd.insert(3, f"--since={since_arg}")
                
                result = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split("\n"):
                        parts = line.split("|", 4)
                        if len(parts) == 5:
                            commits.append({
                                "repo": repo_name,
                                "hash": parts[0],
                                "short_hash": parts[1],
                                "message": parts[2][:80],  # Truncate long messages
                                "relative_time": parts[3],
                                "author": parts[4]
                            })
                    break  # Got commits, don't try longer timeframes
        except Exception as e:
            # Skip repos with errors
            pass
    
    # Sort by recency (git log output is already sorted per-repo, but we need to interleave)
    # Simple heuristic: commits with "minutes" before "hours" before "days"
    def sort_key(c):
        t = c["relative_time"]
        if "second" in t or "minute" in t:
            return 0
        elif "hour" in t:
            return 1
        else:
            return 2
    
    commits.sort(key=sort_key)
    
    result = {
        "commits": commits[:15],  # Max 15 total
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
    
    _git_activity_cache = {"data": result, "ts": now}
    return result


# ===== WORKING CONTEXT WIDGET =====

AGENT_WORKSPACES = [
    ("/home/jwells/clawd", "jarvis", "🎩"),
    ("/home/jwells/clawd-research", "aria", "🔬"),
    ("/home/jwells/clawd-finance", "peter", "📈"),
    ("/home/jwells/clawd-medical", "watson", "🩺"),
    ("/home/jwells/clawd-novvi", "willb", "🏢"),
    ("/home/jwells/clawd-startup", "elon", "🚀"),
]

def parse_working_md(filepath: str) -> dict:
    """Extract key info from WORKING.md"""
    try:
        with open(filepath, "r") as f:
            content = f.read()
        
        lines = content.split("\n")
        result = {
            "last_updated": None,
            "context": None,
            "sections": []
        }
        
        # Find "Last updated:" line
        for line in lines[:10]:
            if line.lower().startswith("last updated:"):
                result["last_updated"] = line.replace("Last updated:", "").strip()
            elif line.lower().startswith("context:"):
                result["context"] = line.replace("Context:", "").replace("context:", "").strip()
        
        # Find section headers (## headings)
        current_section = None
        for i, line in enumerate(lines):
            if line.startswith("## "):
                section_name = line[3:].strip()
                # Skip very common/boring sections
                if section_name.lower() not in ["completed", "session health"]:
                    current_section = section_name
                    result["sections"].append(section_name)
        
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/working-context")
async def get_working_context():
    """Get working context from all agent WORKING.md files"""
    contexts = []
    
    for workspace, agent_name, emoji in AGENT_WORKSPACES:
        working_path = os.path.join(workspace, "WORKING.md")
        if os.path.exists(working_path):
            data = parse_working_md(working_path)
            contexts.append({
                "agent": agent_name,
                "emoji": emoji,
                "workspace": workspace,
                "last_updated": data.get("last_updated"),
                "context": data.get("context"),
                "active_sections": data.get("sections", [])[:5],  # Max 5 sections
                "error": data.get("error")
            })
    
    return {
        "agents": contexts,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


# ===== SYNAPSE: Multi-Agent Command Interface =====

# ===== EMAIL QUICK GLANCE WIDGET =====

@app.get("/api/email/quickview")
async def get_email_quickview():
    """Get quick email status for briefing widget"""
    try:
        with open(TASKS_FILE, "r") as f:
            tasks = json.load(f)
    except:
        return {"unsorted_count": 0, "priority_count": 0, "top_items": [], "error": "No tasks file"}
    
    # Filter to emails only (source_type == "email")
    emails = [t for t in tasks if t.get("source_type") == "email"]
    
    # Count unsorted emails
    unsorted = [e for e in emails if e.get("column") == "unsorted"]
    
    # Priority contact unsorted
    priority_unsorted = [e for e in unsorted if e.get("priority_contact")]
    
    # Top 5 unsorted items (priority first, then recent)
    def sort_key(e):
        # Priority contacts first, then by created_at (recent first)
        priority = 0 if e.get("priority_contact") else 1
        created = e.get("created_at", "")
        return (priority, -len(created), created)
    
    sorted_unsorted = sorted(unsorted, key=lambda e: (
        0 if e.get("priority_contact") else 1,
        e.get("created_at", "")
    ), reverse=True)
    
    top_items = []
    for e in sorted_unsorted[:5]:
        # Extract sender from description "From: Name <email>"
        desc = e.get("description", "")
        sender = desc.replace("From: ", "").split("<")[0].strip() if desc.startswith("From:") else "Unknown"
        
        top_items.append({
            "id": e.get("id"),
            "title": e.get("title", "").replace("📧 ", ""),
            "sender": sender,
            "priority": e.get("priority_contact", False),
            "stuck_since": e.get("stuck_since")
        })
    
    return {
        "unsorted_count": len(unsorted),
        "priority_count": len(priority_unsorted),
        "top_items": top_items,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@app.get("/synapse")
async def synapse_page(request: Request):
    """Synapse - Multi-agent command interface (Nexus v2)"""
    return templates.TemplateResponse("nexus-v2.html", {"request": request})


@app.websocket("/api/synapse/ws")
async def synapse_ws(websocket: WebSocket):
    """Synapse WebSocket endpoint - multiplexed agent communication"""
    client_id = str(uuid.uuid4())
    await synapse_websocket_endpoint(websocket, client_id)


@app.websocket("/api/activity/ws")
async def activity_ws(websocket: WebSocket):
    """Activity log WebSocket endpoint - real-time activity updates"""
    await websocket.accept()
    from activity_websocket import handle_activity_websocket
    await handle_activity_websocket(websocket)


@app.get("/api/synapse/fleet")
async def api_synapse_fleet(username: str = Depends(require_auth)):
    """Get current fleet status (REST alternative to WebSocket)"""
    return get_fleet_status()


@app.get("/api/synapse/agent/{agent_id}/config")
async def api_get_agent_config(agent_id: str, username: str = Depends(require_auth)):
    """Read SOUL.md, AGENTS.md, WORKING.md from agent workspace"""
    config = get_agent_config(agent_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Agent not found or workspace missing")
    return config


@app.put("/api/synapse/agent/{agent_id}/config")
async def api_save_agent_config(agent_id: str, request: Request, username: str = Depends(require_auth)):
    """Save SOUL.md and/or AGENTS.md to agent workspace (with versioning)"""
    body = await request.json()
    result = save_agent_config(agent_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent not found or workspace missing")
    return result


@app.get("/api/synapse/models")
async def api_get_models():
    """Return available models from gateway config (dynamic, not hardcoded)."""
    try:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        with open(config_path, 'r') as f:
            config = json.load(f)
        models_cfg = config.get("agents", {}).get("defaults", {}).get("models", {})
        # Explicit display names for clarity
        DISPLAY_NAMES = {
            "anthropic/claude-opus-4-5": "Claude Opus 4.5",
            "anthropic/claude-opus-4-6": "Claude Opus 4.6",
            "anthropic/claude-sonnet-4-20250514": "Claude Sonnet 4",
            "anthropic/claude-sonnet-4-6": "Claude Sonnet 4.6",
            "google/gemini-2.5-pro": "Gemini 2.5 Pro",
            "google/gemini-2.5-flash": "Gemini 2.5 Flash",
            "google/gemini-3-pro": "Gemini 3 Pro",
            "google/gemini-3-pro-preview": "Gemini 3 Pro (Preview)",
            "google/gemini-3-flash": "Gemini 3 Flash",
            "google/gemini-3-flash-preview": "Gemini 3 Flash (Preview)",
        }
        models = []
        seen_aliases = set()
        for model_id, info in models_cfg.items():
            alias = info.get("alias", "")
            # Skip duplicate aliases (keep last = most specific)
            label = DISPLAY_NAMES.get(model_id, "")
            if not label:
                label = alias.replace("-", " ").title() if alias else model_id.split("/")[-1].replace("-", " ").title()
            models.append({
                "id": model_id,
                "fullId": model_id,
                "label": label,
                "alias": alias,
            })
        return {"ok": True, "models": models}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.put("/api/synapse/agent/{agent_id}/model")
async def api_set_agent_model(agent_id: str, request: Request, username: str = Depends(require_auth)):
    """Set model override for an agent (sonnet or opus)"""
    body = await request.json()
    model = body.get("model", "")
    result = await agent_router.set_agent_model(agent_id, model)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


# ═══ SESSIONS API FOR NEXUS ENHANCED ═══

@app.post("/api/sessions/spawn")
async def api_sessions_spawn(request: Request, username: str = Depends(require_auth)):
    """Spawn a new agent session via sessions_spawn"""
    try:
        body = await request.json()
        
        # Use OpenClaw's sessions_spawn via command execution with full path
        import subprocess
        import os
        
        # Build openclaw command with full path
        cmd = ["/home/jwells/.npm-global/bin/openclaw", "sessions", "spawn"]
        if body.get("agentId"):
            cmd.extend(["--agent-id", body["agentId"]])
        if body.get("task"):
            cmd.extend(["--task", body["task"]])
        if body.get("model"):
            cmd.extend(["--model", body["model"]])
        if body.get("cleanup", "keep") == "keep":
            cmd.extend(["--cleanup", "keep"])
        
        # Execute command with proper environment
        env = os.environ.copy()
        env["PATH"] = f"/home/jwells/.npm-global/bin:{env.get('PATH', '')}"
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        
        if result.returncode == 0:
            return {"ok": True, "output": result.stdout.strip(), "agentId": body.get("agentId")}
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": result.stderr.strip() or "Failed to spawn session"}
            )
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)}
        )


@app.post("/api/sessions/send")
async def api_sessions_send(request: Request, username: str = Depends(require_auth)):
    """Send message to agent session via sessions_send"""
    try:
        body = await request.json()
        
        # Use OpenClaw's sessions_send via command execution with full path
        import subprocess
        import os
        
        cmd = ["/home/jwells/.npm-global/bin/openclaw", "sessions", "send"]
        if body.get("agentId"):
            cmd.extend(["--agent-id", body["agentId"]])
        elif body.get("sessionKey"):
            cmd.extend(["--session-key", body["sessionKey"]])
        
        if body.get("message"):
            cmd.extend(["--message", body["message"]])
        
        # Execute command with proper environment
        env = os.environ.copy()
        env["PATH"] = f"/home/jwells/.npm-global/bin:{env.get('PATH', '')}"
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        
        if result.returncode == 0:
            return {"ok": True, "output": result.stdout.strip()}
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": result.stderr.strip() or "Failed to send message"}
            )
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)}
        )


@app.get("/api/sessions/list")
async def api_sessions_list(username: str = Depends(require_auth)):
    """List active sessions via sessions_list"""
    try:
        import subprocess
        import json
        import os
        
        # Limit to recent sessions to prevent context bloat
        cmd = ["/home/jwells/.npm-global/bin/openclaw", "sessions", "--active", "120", "--json"]
        
        # Execute command with proper environment
        env = os.environ.copy()
        env["PATH"] = f"/home/jwells/.npm-global/bin:{env.get('PATH', '')}"
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        
        if result.returncode == 0:
            # Parse JSON output directly (--json flag used)
            try:
                data = json.loads(result.stdout)
                sessions = data if isinstance(data, list) else data.get("sessions", [])
                
                # Normalize session format for API consumers
                normalized = []
                for sess in sessions:
                    session_key = sess.get("key") or sess.get("sessionKey", "")
                    agent_id = "unknown"
                    if "agent:" in session_key:
                        try:
                            agent_id = session_key.split("agent:")[1].split(":")[0]
                        except (IndexError, AttributeError):
                            pass
                    
                    normalized.append({
                        "sessionKey": session_key,
                        "agentId": agent_id,
                        "model": sess.get("model", "unknown"),
                        "lastActive": sess.get("updatedAt", "unknown"),
                        "totalTokens": sess.get("totalTokens", 0),
                        "contextTokens": sess.get("contextTokens", 200000),
                    })
                
                return {"sessions": normalized}
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=500,
                    content={"ok": False, "error": "Failed to parse sessions JSON"}
                )
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": result.stderr.strip() or "Failed to list sessions"}
            )
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)}
        )


# ============================================================================
# Activity Log Routes
# ============================================================================

from activity import (
    get_activity, get_activity_stats, get_agents as get_activity_agents,
    get_action_types
)


@app.get("/activity")
async def activity_page(request: Request):
    """Activity log timeline page"""
    return templates.TemplateResponse("activity.html", {"request": request})


@app.get("/api/activity")
async def api_get_activity(
    days: int = 7,
    agent: Optional[str] = None,
    action: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Get activity log entries with optional filtering"""
    return get_activity(
        days=days,
        agent=agent,
        action=action,
        action_category=category,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/api/activity/stats")
async def api_activity_stats(days: int = 7):
    """Get activity statistics for dashboard"""
    return get_activity_stats(days)


@app.get("/api/activity/agents")
async def api_activity_agents():
    """Get list of agents with activity"""
    return {"agents": get_activity_agents()}


@app.get("/api/activity/actions")
async def api_activity_actions():
    """Get available action types grouped by category"""
    return {"categories": get_action_types()}


# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# EspoCRM API Bridge — /api/crm/* for agent access
# ═══════════════════════════════════════════════════════════════

import base64
_ESPO_AUTH = "Basic " + base64.b64encode(b"admin:NovviAdmin2026!CRM#Secure").decode()
_ESPO_BASE = "http://localhost:8081/api/v1"

async def _espo_get(endpoint: str, params: dict = None) -> dict:
    """GET from EspoCRM API"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_ESPO_BASE}{endpoint}",
            params=params,
            headers={"Authorization": _ESPO_AUTH, "Content-Type": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()

async def _espo_post(endpoint: str, data: dict) -> dict:
    """POST to EspoCRM API"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_ESPO_BASE}{endpoint}",
            json=data,
            headers={"Authorization": _ESPO_AUTH, "Content-Type": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()

async def _espo_put(endpoint: str, data: dict) -> dict:
    """PUT to EspoCRM API"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{_ESPO_BASE}{endpoint}",
            json=data,
            headers={"Authorization": _ESPO_AUTH, "Content-Type": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()

@app.get("/api/crm/summary")
async def crm_summary():
    """CRM dashboard summary — counts, recent activity, upcoming tasks"""
    import asyncio
    
    async def count_entity(entity):
        try:
            data = await _espo_get(f"/{entity}", {"maxSize": 0})
            return entity, data.get("total", 0)
        except Exception:
            return entity, 0
    
    counts = dict(await asyncio.gather(
        count_entity("Contact"),
        count_entity("Account"),
        count_entity("Lead"),
        count_entity("Opportunity"),
        count_entity("Task"),
        count_entity("Meeting"),
        count_entity("Call"),
    ))
    
    # Recent activities (last 7 days)
    try:
        tasks = await _espo_get("/Task", {
            "where[0][type]": "after",
            "where[0][attribute]": "dateEnd",
            "where[0][value]": (datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
            "orderBy": "dateEnd",
            "order": "asc",
            "maxSize": 10
        })
        upcoming_tasks = [
            {"id": t["id"], "name": t.get("name"), "status": t.get("status"),
             "dateEnd": t.get("dateEnd"), "priority": t.get("priority")}
            for t in tasks.get("list", [])
        ]
    except Exception:
        upcoming_tasks = []
    
    # Open opportunities
    try:
        opps = await _espo_get("/Opportunity", {
            "where[0][type]": "in",
            "where[0][attribute]": "stage",
            "where[0][value][]": ["Prospecting", "Qualification", "Proposal", "Negotiation"],
            "orderBy": "amount",
            "order": "desc",
            "maxSize": 10
        })
        open_opps = [
            {"id": o["id"], "name": o.get("name"), "stage": o.get("stage"),
             "amount": o.get("amount"), "accountName": o.get("accountName")}
            for o in opps.get("list", [])
        ]
    except Exception:
        open_opps = []
    
    return {
        "counts": counts,
        "upcoming_tasks": upcoming_tasks,
        "open_opportunities": open_opps,
        "fetched_at": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/crm/search")
async def crm_search(q: str, entity: str = "Contact", maxSize: int = 20):
    """Search CRM entities"""
    try:
        data = await _espo_get(f"/{entity}", {
            "where[0][type]": "textFilter",
            "where[0][value]": q,
            "maxSize": maxSize
        })
        return {"results": data.get("list", []), "total": data.get("total", 0)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/{entity}")
async def crm_list_entity(entity: str, maxSize: int = 50, offset: int = 0, orderBy: str = "createdAt", order: str = "desc"):
    """List CRM entities (Contact, Account, Lead, Opportunity, Task, Meeting, Call)"""
    allowed = {"Contact", "Account", "Lead", "Opportunity", "Task", "Meeting", "Call", "Email"}
    if entity not in allowed:
        raise HTTPException(status_code=400, detail=f"Entity must be one of: {allowed}")
    try:
        data = await _espo_get(f"/{entity}", {
            "maxSize": maxSize, "offset": offset,
            "orderBy": orderBy, "order": order
        })
        return {"list": data.get("list", []), "total": data.get("total", 0)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/{entity}/{item_id}")
async def crm_get_entity(entity: str, item_id: str):
    """Get a single CRM entity by ID"""
    try:
        return await _espo_get(f"/{entity}/{item_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/crm/{entity}")
async def crm_create_entity(entity: str, request: Request):
    """Create a CRM entity"""
    allowed = {"Contact", "Account", "Lead", "Opportunity", "Task", "Meeting", "Call"}
    if entity not in allowed:
        raise HTTPException(status_code=400, detail=f"Entity must be one of: {allowed}")
    try:
        body = await request.json()
        return await _espo_post(f"/{entity}", body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/crm/{entity}/{item_id}")
async def crm_update_entity(entity: str, item_id: str, request: Request):
    """Update a CRM entity"""
    try:
        body = await request.json()
        return await _espo_put(f"/{entity}/{item_id}", body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════
# Synapse CRM — iframe at /crm, proxy at /_crm/
# ═══════════════════════════════════════════════════════════════

CRM_UPSTREAM = "http://localhost:8081"
_crm_client = httpx.AsyncClient(base_url=CRM_UPSTREAM, timeout=60.0, follow_redirects=True)

@app.get("/crm")
@app.get("/crm/")
async def crm_root(request: Request):
    """Serve EspoCRM in a full-page iframe"""
    from starlette.responses import HTMLResponse
    
    # Use the same hostname the browser used to reach us, just swap port
    host = request.headers.get("host", "ether-spark:3000").split(":")[0]
    espo_url = f"http://{host}:8081"
    
    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mission Control — CRM</title>
<link rel="stylesheet" href="/static/ide-noir.css">
<link rel="stylesheet" href="/static/mission-control.css">
<style>
    body {{ margin: 0; overflow: hidden; }}
    .crm-iframe {{ width: 100%; height: calc(100vh - 48px); border: none; }}
</style>
</head>
<body>
    <nav class="nav-bar">
        <div class="nav-container">
            <div class="nav-left">
                <span class="nav-title">Mission Control</span>
                <div class="nav-tabs">
                    <a href="/" class="nav-tab">Kanban</a>
                    <a href="/briefing" class="nav-tab">Briefing</a>
                    <a href="/email" class="nav-tab">Email</a>
                    <a href="/queue" class="nav-tab">Agent Queue</a>
                    <a href="/crm" class="nav-tab active">CRM</a>
                    <a href="/cron" class="nav-tab">Cron Jobs</a>
                    <a href="/synapse" class="nav-tab">Synapse</a>
                    <a href="/activity" class="nav-tab">Activity</a>
                </div>
            </div>
        </div>
    </nav>
    <iframe class="crm-iframe" src="{espo_url}"></iframe>
</body></html>'''
    return HTMLResponse(content=html)

# ═══════════════════════════════════════════════════════════════
# Research Bot (Whitepaper Curator) — iframe at /rbot, proxy at /_r/
# The SPA runs inside an iframe. All its requests go to /_r/* which
# proxies transparently to localhost:5050. Simple, no path rewriting.
# ═══════════════════════════════════════════════════════════════

RESEARCH_UPSTREAM = "http://localhost:5050"
_research_client = httpx.AsyncClient(base_url=RESEARCH_UPSTREAM, timeout=60.0, follow_redirects=True)

@app.get("/rbot")
async def rbot_page(request: Request):
    from starlette.responses import HTMLResponse
    return HTMLResponse(content='''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Research Bot — Mission Control</title>
<style>*{margin:0;padding:0;box-sizing:border-box;}body{overflow:hidden;}iframe{width:100%;height:100vh;border:none;}</style>
</head><body><iframe src="/_r/" allowfullscreen></iframe></body></html>''')

@app.get("/_r/")
@app.get("/_r")
async def rbot_root(request: Request):
    """Serve Research Bot SPA (built with base=/_r/)"""
    try:
        resp = await _research_client.get("/")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Research Bot not running (port 5050)")
    from starlette.responses import HTMLResponse
    # Inject fetch interceptor so /api/* calls go through /_r/api/*
    html = resp.text.replace('<head>', '<head><script>var _f=window.fetch;window.fetch=function(u){var a=[].slice.call(arguments);if(typeof u==="string"&&u.startsWith("/api/"))a[0]="/_r"+u;return _f.apply(this,a);};</script>')
    return HTMLResponse(content=html)

@app.api_route("/_r/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def rbot_proxy(request: Request, path: str):
    url = f"/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection", "transfer-encoding")}
    try:
        resp = await _research_client.request(method=request.method, url=url, content=body if body else None, headers=headers)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Research Bot not running (port 5050)")
    from starlette.responses import Response
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding", "connection")}
    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)

# ═══════════════════════════════════════════════════════════════
#                    ATLAS KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════════════

ATLAS_UPSTREAM = "http://localhost:5000"
_atlas_client = httpx.AsyncClient(base_url=ATLAS_UPSTREAM, timeout=60.0, follow_redirects=True)

@app.get("/atlas")
async def atlas_page(request: Request):
    """Serve Atlas SPA directly (no iframe, works through Cloudflare Access)"""
    try:
        resp = await _atlas_client.get("/")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Atlas not running (port 5000)")
    from starlette.responses import HTMLResponse
    # Rewrite asset paths and API calls to go through /_atlas/
    html = resp.text
    html = html.replace('"/assets/', '"/_atlas/assets/')
    html = html.replace("'/assets/", "'/_atlas/assets/")
    html = html.replace('<head>', '<head><script>var _f=window.fetch;window.fetch=function(u){var a=[].slice.call(arguments);if(typeof u==="string"&&u.startsWith("/api/"))a[0]="/_atlas"+u;return _f.apply(this,a);};</script>')
    return HTMLResponse(content=html)

@app.get("/atlas/{path:path}")
async def atlas_spa_catchall(request: Request):
    """Catch-all for Atlas client-side routes"""
    return await atlas_page(request)

@app.get("/_atlas/")
@app.get("/_atlas")
async def atlas_root(request: Request):
    """Serve Atlas SPA"""
    try:
        resp = await _atlas_client.get("/")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Atlas not running (port 5000)")
    from starlette.responses import HTMLResponse
    html = resp.text.replace('<head>', '<head><script>var _f=window.fetch;window.fetch=function(u){var a=[].slice.call(arguments);if(typeof u==="string"&&u.startsWith("/api/"))a[0]="/_atlas"+u;return _f.apply(this,a);};</script>')
    return HTMLResponse(content=html)

@app.api_route("/_atlas/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def atlas_proxy(request: Request, path: str):
    url = f"/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection", "transfer-encoding")}
    try:
        resp = await _atlas_client.request(method=request.method, url=url, content=body if body else None, headers=headers)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Atlas not running (port 5000)")
    from starlette.responses import Response
    content_type = resp.headers.get("content-type", "application/octet-stream")
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding", "connection", "content-type")}
    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers, media_type=content_type)

# ═══════════════════════════════════════════════════════════════
#                    BOT ACTIVITY MONITORING API
# ═══════════════════════════════════════════════════════════════

# Import bot activity monitor
# TEMPORARILY DISABLED DUE TO DEPENDENCY ISSUE
# from bot_activity_monitor import (
#     get_bot_activity_status, record_bot_message, record_bot_auth_failure,
#     resolve_bot_alert, get_monitor
# )

# Bot activity tracking middleware
@app.middleware("http")
async def bot_activity_middleware(request: Request, call_next):
    """Middleware to automatically track bot API activity"""
    response = await call_next(request)
    
    try:
        # Track API calls that indicate bot activity
        path = request.url.path
        method = request.method
        
        # Track these endpoints as bot activity
        bot_endpoints = [
            "/api/tasks",
            "/api/queue", 
            "/api/email",
            "/api/briefing",
            "/api/synapse",
            "/api/cron",
            "/api/agents"
        ]
        
        # Check if this is a bot-related API call
        is_bot_call = any(path.startswith(endpoint) for endpoint in bot_endpoints)
        
        if is_bot_call and method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            # Extract client IP
            client_ip = request.client.host
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            
            # Record the activity (don't await to avoid blocking)
            # asyncio.create_task(record_bot_message(ip=client_ip))
            pass
            
        # Track authentication failures
        if response.status_code == 401 or response.status_code == 403:
            asyncio.create_task(record_bot_auth_failure())
            
    except Exception as e:
        # Don't let monitoring errors break the request
        print(f"[BOT_MONITOR] Error in middleware: {e}")
    
    return response

@app.get("/api/bot-activity/status")
async def api_get_bot_activity_status():
    """Get current bot activity monitoring status and alerts"""
    try:
        # return await get_bot_activity_status()
        return {"status": "disabled", "active": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bot activity status: {str(e)}")

@app.post("/api/bot-activity/message")
async def api_record_bot_message(request: Request):
    """Record a bot message/API call for monitoring"""
    try:
        # Extract client IP for monitoring
        client_ip = request.client.host
        
        # Check for forwarded IP headers (for proxied requests)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        # await record_bot_message(ip=client_ip)
        pass
        return {"status": "recorded", "ip": client_ip}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record bot message: {str(e)}")

@app.post("/api/bot-activity/auth-failure")
async def api_record_bot_auth_failure():
    """Record an authentication failure for monitoring"""
    try:
        # await record_bot_auth_failure()
        pass
        return {"status": "recorded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record auth failure: {str(e)}")

@app.post("/api/bot-activity/resolve-alert/{alert_id}")
async def api_resolve_bot_alert(alert_id: str):
    """Resolve a bot activity alert"""
    try:
        resolved = await resolve_bot_alert(alert_id)
        if resolved:
            return {"status": "resolved", "alert_id": alert_id}
        else:
            raise HTTPException(status_code=404, detail="Alert not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve alert: {str(e)}")

@app.get("/api/bot-activity/metrics")
async def api_get_bot_activity_metrics():
    """Get detailed bot activity metrics for dashboard"""
    try:
        monitor = get_monitor()
        metrics = monitor.get_current_metrics()
        return asdict(metrics) if hasattr(metrics, '__dict__') else metrics._asdict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bot activity metrics: {str(e)}")

@app.get("/api/bot-activity/alerts")
async def api_get_bot_activity_alerts():
    """Get current bot activity alerts"""
    try:
        monitor = get_monitor()
        return {
            "active_alerts": [asdict(alert) for alert in monitor.alerts.values()],
            "alert_history": [asdict(alert) for alert in list(monitor.alert_history)[-20:]]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bot activity alerts: {str(e)}")

@app.post("/api/bot-activity/test-alert")
async def api_test_bot_activity_alert():
    """Generate a test alert for development/testing"""
    try:
        monitor = get_monitor()
        
        # Simulate high message volume
        for i in range(10):
            monitor.record_message()
        
        # Generate auth failure
        monitor.record_auth_failure()
        
        # Trigger alert check
        new_alerts = await monitor.check_activity()
        
        return {
            "status": "test_completed",
            "new_alerts": len(new_alerts),
            "alerts": [asdict(alert) for alert in new_alerts] if new_alerts else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate test alert: {str(e)}")


# ============================================================================
# HECL ENRICHMENT API
# ============================================================================

class EnrichmentRequest(BaseModel):
    """Request model for HECL enrichment"""
    results: List[Dict[str, Any]]
    line_range: Optional[int] = 50

@app.post("/api/hecl/enrich")
async def api_hecl_enrich(request: EnrichmentRequest, username: str = Depends(require_auth)):
    """Enrich Moltbot memory_search results with HECL metadata"""
    try:
        import subprocess
        import json
        from pathlib import Path
        
        # Check if HECL is available
        hecl_bin = Path.home() / "bin" / "hecl"
        if not hecl_bin.exists():
            raise HTTPException(status_code=503, detail="HECL not available")
        
        enriched_results = []
        
        for result in request.results:
            if not result.get("path"):
                # If no path, return original result with empty HECL metadata
                enriched_results.append({
                    **result,
                    "hecl": {
                        "atom_count": 0,
                        "atom_ids": [],
                        "entities": [],
                        "types": [],
                        "min_confidence": None,
                        "has_superseded": False
                    }
                })
                continue
                
            # Use HECL CLI to enrich this result
            cmd = [
                str(hecl_bin), "enrich",
                "--path", result["path"],
                "--format", "json"
            ]
            
            if result.get("startLine") or result.get("start_line"):
                cmd.extend(["--line", str(result.get("startLine", result.get("start_line")))])
                
            if request.line_range:
                cmd.extend(["--range", str(request.line_range)])
            
            try:
                # Run HECL enrich command
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if proc.returncode == 0:
                    hecl_data = json.loads(proc.stdout)
                    
                    # Merge original result with HECL enrichment
                    enriched_result = {**result}
                    enriched_result["hecl"] = {
                        "atom_count": hecl_data.get("atom_count", 0),
                        "atom_ids": [atom["id"] for atom in hecl_data.get("atoms", [])],
                        "entities": hecl_data.get("entities", []),
                        "types": hecl_data.get("types", []),
                        "min_confidence": min([atom["confidence"] for atom in hecl_data.get("atoms", [])]) if hecl_data.get("atoms") else None,
                        "has_superseded": any("superseded" in atom.get("text", "").lower() for atom in hecl_data.get("atoms", []))
                    }
                    enriched_results.append(enriched_result)
                else:
                    # HECL command failed, return original with empty metadata
                    enriched_results.append({
                        **result,
                        "hecl": {
                            "atom_count": 0,
                            "atom_ids": [],
                            "entities": [],
                            "types": [],
                            "min_confidence": None,
                            "has_superseded": False,
                            "error": proc.stderr.strip() if proc.stderr else "HECL enrichment failed"
                        }
                    })
                    
            except subprocess.TimeoutExpired:
                enriched_results.append({
                    **result,
                    "hecl": {
                        "atom_count": 0,
                        "atom_ids": [],
                        "entities": [],
                        "types": [],
                        "min_confidence": None,
                        "has_superseded": False,
                        "error": "HECL enrichment timeout"
                    }
                })
            except Exception as e:
                enriched_results.append({
                    **result,
                    "hecl": {
                        "atom_count": 0,
                        "atom_ids": [],
                        "entities": [],
                        "types": [],
                        "min_confidence": None,
                        "has_superseded": False,
                        "error": f"HECL enrichment error: {str(e)}"
                    }
                })
        
        return {"enriched_results": enriched_results}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enrich results: {str(e)}")

@app.get("/api/hecl/status")
async def api_hecl_status(username: str = Depends(require_auth)):
    """Check HECL system status"""
    try:
        import subprocess
        from pathlib import Path
        
        status = {
            "available": False,
            "database_exists": False,
            "atom_count": 0,
            "entity_count": 0,
            "last_ingestion": None
        }
        
        # Check HECL binary
        hecl_bin = Path.home() / "bin" / "hecl"
        if not hecl_bin.exists():
            return status
            
        status["available"] = True
        
        # Check database
        clawd_path = Path.home() / "clawd"
        db_path = clawd_path / ".memory" / "index.sqlite"
        status["database_exists"] = db_path.exists()
        
        if status["database_exists"]:
            # Get basic stats using HECL doctor
            try:
                proc = subprocess.run([str(hecl_bin), "doctor"], 
                                    cwd=str(clawd_path), capture_output=True, text=True, timeout=10)
                if proc.returncode == 0:
                    # Parse doctor output for stats
                    output = proc.stdout
                    for line in output.split('\n'):
                        if 'atoms indexed' in line:
                            status["atom_count"] = int(line.split()[0])
                        elif 'entities tracked' in line:
                            status["entity_count"] = int(line.split()[0])
                            
            except Exception:
                pass  # Stats not critical
        
        return status
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check HECL status: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)