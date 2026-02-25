"""
Task Dispatch — Wire Agent Queue to Moltbot agents

Integration pattern:
1. Mission Control sends task to orchestrator agent (Jarvis) via Gateway
2. Jarvis uses sessions_spawn to create sub-agent session
3. Sub-agent works on task
4. Queue item updated with session status

For now, we send tasks directly to agents and let them handle the work.
Future: Orchestrator-mediated spawning for complex tasks.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from agent_router import GatewayClient, AGENT_REGISTRY
from agent_queue import get_item, update_item, QueueItemUpdate

logger = logging.getLogger(__name__)


class TaskDispatcher:
    """Dispatch queue tasks to agents via Gateway."""
    
    def __init__(self):
        self.gateway = GatewayClient()
        self._connected = False
    
    async def connect(self):
        if not self._connected:
            await self.gateway.connect()
            self._connected = True
    
    async def disconnect(self):
        if self._connected:
            await self.gateway.disconnect()
            self._connected = False
    
    async def dispatch_task(
        self,
        task_id: str,
        agent_id: str,
        custom_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dispatch a queue task to an agent.
        
        Args:
            task_id: Queue item ID
            agent_id: Target agent (jarvis, aria, peter, etc.)
            custom_prompt: Override task prompt (optional)
        
        Returns:
            Dict with dispatch result (runId, status, etc.)
        """
        # Get task details
        task = get_item(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        # Validate agent
        if agent_id not in AGENT_REGISTRY:
            return {"success": False, "error": f"Unknown agent: {agent_id}"}
        
        agent_info = AGENT_REGISTRY[agent_id]
        session_key = agent_info["sessionKey"]
        
        # Build prompt from task
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = self._build_task_prompt(task)
        
        await self.connect()
        
        try:
            # Send task to agent
            result = await self.gateway.send_message(session_key, prompt)
            
            if result.get("ok"):
                run_id = result.get("payload", {}).get("runId")
                
                # Update queue item with session info
                update_item(task_id, QueueItemUpdate(
                    session_id=run_id,
                    session_status="running",
                    column="active",
                    notes=self._append_note(
                        task.get("notes", ""),
                        f"Dispatched to {agent_id} (run: {run_id[:8]})"
                    )
                ))
                
                return {
                    "success": True,
                    "runId": run_id,
                    "agent": agent_id,
                    "sessionKey": session_key
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error")
                }
                
        except Exception as e:
            logger.error(f"Task dispatch failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_task_status(self, task_id: str) -> Dict[str, Any]:
        """Check status of a dispatched task by looking at session."""
        task = get_item(task_id)
        if not task:
            return {"status": "not_found"}
        
        session_id = task.get("session_id")
        if not session_id:
            return {"status": "not_dispatched"}
        
        await self.connect()
        
        try:
            sessions = await self.gateway.list_sessions()
            
            # Find session by runId (stored in session_id)
            for sess in sessions:
                # Check if this session matches
                if sess.get("runId") == session_id:
                    return {
                        "status": "running" if sess.get("activeRun") else "idle",
                        "contextPercent": sess.get("contextPercent", 0),
                        "lastActivity": sess.get("updatedAt")
                    }
            
            # Session not found in active list - might be complete
            return {"status": "complete_or_unknown"}
            
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_agent_for_task(self, task: Dict) -> str:
        """Suggest best agent for a task based on tags/complexity."""
        tags = task.get("tags", [])
        title = task.get("title", "").lower()
        
        # Simple tag-based routing
        if "research" in tags or "analysis" in tags:
            return "aria"
        if "finance" in tags or "budget" in tags:
            return "peter"
        if "medical" in tags or "health" in tags:
            return "watson"
        
        # Novvi routing: JC for BD/external, Will B. for internal/technical
        if "novvi" in tags or "company" in tags:
            # JC handles customer-facing, BD, marketing, social
            if any(kw in tags for kw in ["bd", "sales", "marketing", "social", "linkedin", "email", "outreach", "lead"]):
                return "jc"
            if any(kw in title for kw in ["linkedin", "email draft", "outreach", "lead", "customer", "prospect"]):
                return "jc"
            # Will B. handles internal technical work
            return "willb"
        
        # JC for explicit BD tasks
        if any(kw in tags for kw in ["bd", "sales", "marketing", "social", "linkedin"]):
            return "jc"
            
        if "startup" in tags or "product" in tags:
            return "elon"
        
        # Default to orchestrator for complex/untagged tasks
        complexity = task.get("complexity", "medium")
        if complexity == "deep":
            return "jarvis"
        
        return "jarvis"  # Default orchestrator
    
    def _build_task_prompt(self, task: Dict) -> str:
        """Build agent prompt from task details."""
        title = task.get("title", "Untitled task")
        description = task.get("description", "")
        doc_path = task.get("doc_path")
        notes = task.get("notes", "")
        
        prompt_parts = [
            f"## Task: {title}",
            "",
        ]
        
        if description:
            prompt_parts.append(description)
            prompt_parts.append("")
        
        if doc_path:
            prompt_parts.append(f"Reference doc: {doc_path}")
            prompt_parts.append("")
        
        if notes:
            # Only include recent notes (last 500 chars)
            recent_notes = notes[-500:] if len(notes) > 500 else notes
            prompt_parts.append(f"Previous notes:\n{recent_notes}")
            prompt_parts.append("")
        
        prompt_parts.extend([
            "Work on this task. When complete or blocked, update the notes with your progress.",
            "If you need to spawn a sub-agent for part of the work, do so.",
        ])
        
        return "\n".join(prompt_parts)
    
    def _append_note(self, existing: str, new_note: str) -> str:
        """Append timestamped note to existing notes."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = f"\n---\n[{timestamp}] {new_note}"
        return existing + entry


# Convenience function for testing
async def dispatch_task_to_agent(task_id: str, agent_id: str) -> Dict:
    """One-shot dispatch helper."""
    dispatcher = TaskDispatcher()
    try:
        return await dispatcher.dispatch_task(task_id, agent_id)
    finally:
        await dispatcher.disconnect()


# Test the dispatcher
if __name__ == "__main__":
    async def test():
        dispatcher = TaskDispatcher()
        
        # Test connection
        await dispatcher.connect()
        print(f"✅ Connected: {dispatcher._connected}")
        
        # Test agent routing
        test_task = {"tags": ["research"], "complexity": "medium"}
        agent = await dispatcher.get_agent_for_task(test_task)
        print(f"✅ Agent for research task: {agent}")
        
        test_task = {"tags": ["finance"], "complexity": "deep"}
        agent = await dispatcher.get_agent_for_task(test_task)
        print(f"✅ Agent for finance task: {agent}")
        
        await dispatcher.disconnect()
        print("✅ Tests passed")
    
    asyncio.run(test())
