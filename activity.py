#!/usr/bin/env python3
"""
Activity Log Module - Agent Activity Tracking

Reads JSONL activity logs from workspace memory directories and provides
APIs for querying, filtering, and aggregating agent activity.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# Activity log directories to scan
ACTIVITY_DIRS = [
    Path.home() / "clawd" / "memory" / "activity",
    # Add other agent workspaces if needed
]

# Action type categories for grouping
ACTION_CATEGORIES = {
    "file": ["file_read", "file_write", "file_edit"],
    "exec": ["exec"],
    "web": ["web_search", "web_fetch"],
    "communication": ["message_send", "spawn"],
    "task": ["task_create", "task_update"],
    "system": ["cron_add", "session_start", "session_end", "decision", "error"],
}

@dataclass
class ActivityEntry:
    """Single activity log entry"""
    ts: str
    action: str
    summary: str
    agent: str
    target: Optional[str] = None
    session: Optional[str] = None
    duration_ms: Optional[int] = None
    metadata: Optional[Dict] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ActivityEntry":
        return cls(
            ts=data.get("ts", ""),
            action=data.get("action", ""),
            summary=data.get("summary", ""),
            agent=data.get("agent", "unknown"),
            target=data.get("target"),
            session=data.get("session"),
            duration_ms=data.get("duration_ms"),
            metadata=data.get("metadata"),
        )
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def get_log_files(days: int = 7) -> List[Path]:
    """Get activity log files for the last N days"""
    files = []
    today = datetime.now()
    
    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        
        for activity_dir in ACTIVITY_DIRS:
            log_file = activity_dir / f"{date_str}.jsonl"
            if log_file.exists():
                files.append(log_file)
    
    return files


def read_log_file(path: Path) -> List[ActivityEntry]:
    """Read and parse a JSONL activity log file"""
    entries = []
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        entries.append(ActivityEntry.from_dict(data))
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines
    except Exception as e:
        print(f"[activity] Error reading {path}: {e}")
    return entries


def get_activity(
    days: int = 7,
    agent: Optional[str] = None,
    action: Optional[str] = None,
    action_category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get activity log entries with filtering
    
    Args:
        days: Number of days to look back
        agent: Filter by agent ID
        action: Filter by specific action type
        action_category: Filter by action category (file, exec, web, etc.)
        search: Search in summary and target
        limit: Max entries to return
        offset: Pagination offset
    
    Returns:
        Dict with entries, total count, and metadata
    """
    all_entries = []
    
    # Read log files
    for log_file in get_log_files(days):
        all_entries.extend(read_log_file(log_file))
    
    # Sort by timestamp descending (most recent first)
    all_entries.sort(key=lambda e: e.ts, reverse=True)
    
    # Filter
    filtered = []
    for entry in all_entries:
        # Agent filter
        if agent and entry.agent != agent:
            continue
        
        # Action filter
        if action and entry.action != action:
            continue
        
        # Category filter
        if action_category:
            category_actions = ACTION_CATEGORIES.get(action_category, [])
            if entry.action not in category_actions:
                continue
        
        # Search filter
        if search:
            search_lower = search.lower()
            searchable = f"{entry.summary} {entry.target or ''}".lower()
            if search_lower not in searchable:
                continue
        
        filtered.append(entry)
    
    total = len(filtered)
    
    # Paginate
    paginated = filtered[offset:offset + limit]
    
    return {
        "entries": [e.to_dict() for e in paginated],
        "total": total,
        "limit": limit,
        "offset": offset,
        "days": days,
        "filters": {
            "agent": agent,
            "action": action,
            "action_category": action_category,
            "search": search,
        }
    }


def get_activity_stats(days: int = 7) -> Dict[str, Any]:
    """Get activity statistics for dashboard"""
    all_entries = []
    
    for log_file in get_log_files(days):
        all_entries.extend(read_log_file(log_file))
    
    # Count by action type
    by_action = {}
    for entry in all_entries:
        by_action[entry.action] = by_action.get(entry.action, 0) + 1
    
    # Count by agent
    by_agent = {}
    for entry in all_entries:
        by_agent[entry.agent] = by_agent.get(entry.agent, 0) + 1
    
    # Count by day
    by_day = {}
    for entry in all_entries:
        if entry.ts:
            day = entry.ts[:10]  # YYYY-MM-DD
            by_day[day] = by_day.get(day, 0) + 1
    
    # Count by category
    by_category = {cat: 0 for cat in ACTION_CATEGORIES}
    for entry in all_entries:
        for cat, actions in ACTION_CATEGORIES.items():
            if entry.action in actions:
                by_category[cat] += 1
                break
    
    return {
        "total": len(all_entries),
        "days": days,
        "by_action": dict(sorted(by_action.items(), key=lambda x: -x[1])),
        "by_agent": dict(sorted(by_agent.items(), key=lambda x: -x[1])),
        "by_day": dict(sorted(by_day.items(), reverse=True)),
        "by_category": by_category,
    }


def get_agents() -> List[str]:
    """Get list of unique agents from activity logs"""
    agents = set()
    for log_file in get_log_files(days=30):
        for entry in read_log_file(log_file):
            agents.add(entry.agent)
    return sorted(agents)


def get_action_types() -> Dict[str, List[str]]:
    """Get available action types grouped by category"""
    return ACTION_CATEGORIES


# Test
if __name__ == "__main__":
    print("Activity Stats (7 days):")
    stats = get_activity_stats(7)
    print(json.dumps(stats, indent=2))
    
    print("\nRecent Activity:")
    result = get_activity(days=7, limit=5)
    for entry in result["entries"]:
        print(f"  [{entry['ts']}] {entry['agent']}: {entry['action']} - {entry['summary']}")
