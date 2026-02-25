#!/usr/bin/env python3
"""
Agent Work Queue - Task management for human-AI collaboration
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

DATA_DIR = "data"
QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")
CLAWD_WORKSPACE = os.path.expanduser("~/clawd")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


class QueueItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    column: str  # urgent, active, review, queued, ideas
    project: Optional[str] = None  # parent project id
    complexity: Optional[str] = "medium"  # quick, medium, deep
    agent: Optional[str] = None  # assigned agent id (overrides auto-routing)
    doc_path: Optional[str] = None  # link to plan/project doc
    session_id: Optional[str] = None  # sub-agent session if running
    session_status: Optional[str] = None  # running, done, failed
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    notes: Optional[str] = ""
    tags: List[str] = []
    priority: int = 0  # higher = more important in queued column


class QueueItemCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    column: Optional[str] = "queued"
    project: Optional[str] = None
    complexity: Optional[str] = "medium"
    agent: Optional[str] = None
    doc_path: Optional[str] = None
    notes: Optional[str] = ""
    tags: List[str] = []
    priority: int = 0


class QueueItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    project: Optional[str] = None
    complexity: Optional[str] = None
    agent: Optional[str] = None
    doc_path: Optional[str] = None
    session_id: Optional[str] = None
    session_status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    priority: Optional[int] = None


def load_queue() -> Dict[str, Any]:
    """Load queue data from file"""
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    return {"items": [], "projects": []}


def save_queue(data: Dict[str, Any]):
    """Save queue data to file"""
    with open(QUEUE_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_all_items() -> List[Dict]:
    """Get all queue items"""
    data = load_queue()
    return data.get("items", [])


def get_item(item_id: str) -> Optional[Dict]:
    """Get a specific item by ID"""
    items = get_all_items()
    for item in items:
        if item["id"] == item_id:
            return item
    return None


def create_item(item: QueueItemCreate) -> Dict:
    """Create a new queue item"""
    data = load_queue()
    now = datetime.now(timezone.utc).isoformat()
    
    new_item = {
        "id": f"q_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(data.get('items', []))}",
        "title": item.title,
        "description": item.description or "",
        "column": item.column or "queued",
        "project": item.project,
        "complexity": item.complexity or "medium",
        "agent": item.agent,
        "doc_path": item.doc_path,
        "session_id": None,
        "session_status": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "notes": item.notes or "",
        "tags": item.tags or [],
        "priority": item.priority or 0
    }
    
    if "items" not in data:
        data["items"] = []
    data["items"].append(new_item)
    save_queue(data)
    return new_item


def update_item(item_id: str, update: QueueItemUpdate) -> Optional[Dict]:
    """Update an existing queue item"""
    data = load_queue()
    items = data.get("items", [])
    
    for i, item in enumerate(items):
        if item["id"] == item_id:
            # Update fields that are provided
            update_dict = update.dict(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    item[key] = value
            
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            # Set completed_at if moving to review/done
            if update.column in ["review", "done"] and not item.get("completed_at"):
                item["completed_at"] = item["updated_at"]
            
            data["items"][i] = item
            save_queue(data)
            return item
    
    return None


def delete_item(item_id: str) -> bool:
    """Delete a queue item"""
    data = load_queue()
    items = data.get("items", [])
    
    for i, item in enumerate(items):
        if item["id"] == item_id:
            del data["items"][i]
            save_queue(data)
            return True
    
    return False


def move_item(item_id: str, column: str) -> Optional[Dict]:
    """Move an item to a different column"""
    return update_item(item_id, QueueItemUpdate(column=column))


def open_in_helix(file_path: str) -> Dict[str, Any]:
    """Open a file in Helix via tmux session"""
    # Resolve path relative to clawd workspace if not absolute
    if not file_path.startswith("/"):
        full_path = os.path.join(CLAWD_WORKSPACE, file_path)
    else:
        full_path = file_path
    
    # Check file exists
    if not os.path.exists(full_path):
        return {"success": False, "error": f"File not found: {full_path}"}
    
    # Generate session name from filename
    basename = os.path.basename(file_path).replace(".", "-")
    session_name = f"edit-{basename}"
    
    try:
        # Check if session already exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True
        )
        
        if result.returncode == 0:
            # Session exists, just return info
            return {
                "success": True,
                "session": session_name,
                "message": f"Session already exists. Attach with: tmux attach -t {session_name}",
                "existing": True
            }
        
        # Create new tmux session with helix
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "hx", full_path],
            check=True
        )
        
        return {
            "success": True,
            "session": session_name,
            "message": f"Opened in tmux. Attach with: tmux attach -t {session_name}",
            "existing": False
        }
    
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except FileNotFoundError:
        return {"success": False, "error": "tmux or hx not found in PATH"}


def get_projects() -> List[Dict]:
    """Get all projects (items that are containers)"""
    data = load_queue()
    return data.get("projects", [])


def get_items_by_column() -> Dict[str, List[Dict]]:
    """Get items organized by column"""
    items = get_all_items()
    columns = {
        "urgent": [],
        "active": [],
        "review": [],
        "queued": [],
        "ideas": []
    }
    
    for item in items:
        col = item.get("column", "queued")
        if col in columns:
            columns[col].append(item)
    
    # Sort queued by priority (descending)
    columns["queued"].sort(key=lambda x: x.get("priority", 0), reverse=True)
    
    return columns


def get_stats() -> Dict[str, Any]:
    """Get queue statistics"""
    items = get_all_items()
    by_column = get_items_by_column()
    
    return {
        "total": len(items),
        "urgent": len(by_column["urgent"]),
        "active": len(by_column["active"]),
        "review": len(by_column["review"]),
        "queued": len(by_column["queued"]),
        "ideas": len(by_column["ideas"]),
        "running_sessions": len([i for i in items if i.get("session_status") == "running"])
    }
