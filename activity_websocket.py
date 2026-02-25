#!/usr/bin/env python3
"""
Activity WebSocket Module - Real-time activity log streaming

Provides WebSocket endpoints for real-time activity log updates.
Monitors JSONL activity log files for changes and broadcasts updates to connected clients.
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import aiofiles

from activity import ActivityEntry, get_log_files, read_log_file

logger = logging.getLogger(__name__)

@dataclass
class ActivityUpdate:
    """Real-time activity update message"""
    type: str  # "activity_added", "activity_stats_updated"
    entry: Optional[ActivityEntry] = None
    stats: Optional[Dict] = None
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        result = {
            "type": self.type,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat()
        }
        if self.entry:
            result["entry"] = self.entry.to_dict()
        if self.stats:
            result["stats"] = self.stats
        return result


class ActivityFileWatcher(FileSystemEventHandler):
    """Watches activity log files for changes"""
    
    def __init__(self, activity_broadcaster):
        self.broadcaster = activity_broadcaster
        self.last_processed = {}  # File path -> last processed size
        
    def on_modified(self, event):
        if event.is_directory:
            return
            
        if event.src_path.endswith('.jsonl'):
            # Schedule async processing
            asyncio.create_task(self._process_file_change(Path(event.src_path)))
    
    async def _process_file_change(self, file_path: Path):
        """Process changes in activity log file"""
        try:
            # Check if file size increased (new entries added)
            current_size = file_path.stat().st_size
            last_size = self.last_processed.get(str(file_path), 0)
            
            if current_size <= last_size:
                return  # File didn't grow
            
            # Read new entries from the end of file
            new_entries = await self._read_new_entries(file_path, last_size)
            
            # Update last processed size
            self.last_processed[str(file_path)] = current_size
            
            # Broadcast new entries
            for entry in new_entries:
                await self.broadcaster.broadcast_activity_update(entry)
                
        except Exception as e:
            logger.error(f"Error processing activity file change {file_path}: {e}")
    
    async def _read_new_entries(self, file_path: Path, from_byte: int) -> List[ActivityEntry]:
        """Read new JSONL entries from file starting from specific byte position"""
        entries = []
        
        try:
            async with aiofiles.open(file_path, 'r') as f:
                await f.seek(from_byte)
                async for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            entries.append(ActivityEntry.from_dict(data))
                        except json.JSONDecodeError:
                            pass  # Skip malformed lines
        except Exception as e:
            logger.error(f"Error reading new entries from {file_path}: {e}")
        
        return entries


class ActivityWebSocketBroadcaster:
    """Manages WebSocket connections for activity log broadcasting"""
    
    def __init__(self):
        self.connections: Set[Any] = set()  # WebSocket connections
        self.file_watcher: Optional[ActivityFileWatcher] = None
        self.observer: Optional[Observer] = None
        self.stats_cache = {}
        self.stats_last_update = 0
        
    async def start(self):
        """Start the activity monitoring system"""
        logger.info("Starting activity WebSocket broadcaster...")
        
        # Initialize file watcher
        self.file_watcher = ActivityFileWatcher(self)
        self.observer = Observer()
        
        # Watch activity log directories
        from activity import ACTIVITY_DIRS
        for activity_dir in ACTIVITY_DIRS:
            if activity_dir.exists():
                self.observer.schedule(self.file_watcher, str(activity_dir), recursive=False)
                logger.info(f"Watching activity directory: {activity_dir}")
        
        self.observer.start()
        logger.info("Activity file watcher started")
        
        # Initialize file sizes for existing files
        await self._initialize_file_sizes()
    
    async def stop(self):
        """Stop the activity monitoring system"""
        logger.info("Stopping activity WebSocket broadcaster...")
        if self.observer:
            self.observer.stop()
            self.observer.join()
        logger.info("Activity file watcher stopped")
    
    async def _initialize_file_sizes(self):
        """Initialize tracking of existing file sizes"""
        try:
            log_files = get_log_files(days=1)  # Only track today's files
            for file_path in log_files:
                if file_path.exists():
                    self.file_watcher.last_processed[str(file_path)] = file_path.stat().st_size
        except Exception as e:
            logger.error(f"Error initializing file sizes: {e}")
    
    def add_connection(self, websocket):
        """Add a WebSocket connection"""
        self.connections.add(websocket)
        logger.info(f"Activity WebSocket connection added. Total: {len(self.connections)}")
    
    def remove_connection(self, websocket):
        """Remove a WebSocket connection"""
        self.connections.discard(websocket)
        logger.info(f"Activity WebSocket connection removed. Total: {len(self.connections)}")
    
    async def broadcast_activity_update(self, entry: ActivityEntry):
        """Broadcast a new activity entry to all connected clients"""
        if not self.connections:
            return
        
        update = ActivityUpdate(
            type="activity_added",
            entry=entry
        )
        
        message = update.to_dict()
        
        # Send to all connected clients
        disconnected = set()
        for websocket in self.connections.copy():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send activity update to WebSocket: {e}")
                disconnected.add(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            self.remove_connection(websocket)
    
    async def broadcast_stats_update(self):
        """Broadcast updated activity statistics"""
        if not self.connections:
            return
        
        try:
            from activity import get_activity_stats
            stats = get_activity_stats(days=7)
            
            update = ActivityUpdate(
                type="activity_stats_updated",
                stats=stats
            )
            
            message = update.to_dict()
            
            # Send to all connected clients
            disconnected = set()
            for websocket in self.connections.copy():
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send stats update to WebSocket: {e}")
                    disconnected.add(websocket)
            
            # Clean up disconnected clients
            for websocket in disconnected:
                self.remove_connection(websocket)
                
        except Exception as e:
            logger.error(f"Error broadcasting stats update: {e}")
    
    async def send_recent_activity(self, websocket, limit: int = 20):
        """Send recent activity to a newly connected client"""
        try:
            from activity import get_activity
            result = get_activity(days=1, limit=limit, offset=0)
            
            message = {
                "type": "activity_history",
                "entries": result["entries"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            await websocket.send_json(message)
            
        except Exception as e:
            logger.error(f"Error sending recent activity: {e}")


# Global broadcaster instance
activity_broadcaster = ActivityWebSocketBroadcaster()


async def handle_activity_websocket(websocket):
    """Handle a WebSocket connection for activity log updates"""
    activity_broadcaster.add_connection(websocket)
    
    try:
        # Send recent activity on connect
        await activity_broadcaster.send_recent_activity(websocket)
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages (though we don't expect many for activity logs)
                message = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
                
                # Handle client requests
                if message.get("type") == "request_stats":
                    await activity_broadcaster.broadcast_stats_update()
                elif message.get("type") == "request_recent":
                    limit = message.get("limit", 20)
                    await activity_broadcaster.send_recent_activity(websocket, limit)
                    
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
                
    except Exception as e:
        logger.info(f"Activity WebSocket connection closed: {e}")
    finally:
        activity_broadcaster.remove_connection(websocket)