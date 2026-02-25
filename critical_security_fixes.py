#!/usr/bin/env python3
"""
Mission Control Critical Security Fixes
Manually apply authentication to the most critical unprotected endpoints
"""

import sys
import re

def apply_critical_fixes():
    """Apply authentication to critical endpoints"""
    
    app_file = "/home/jwells/projects/mission-control/app.py"
    
    with open(app_file, 'r') as f:
        content = f.read()
    
    # Most critical endpoints that need immediate protection
    critical_fixes = [
        # Agent management endpoints - HIGHEST RISK
        {
            'pattern': r'(@app\.get\("/api/agents"\)\s*\n)(async def api_get_agents\(\):)',
            'replacement': r'\1async def api_get_agents(username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.post\("/api/sessions/spawn"\)\s*\n)(async def api_sessions_spawn\(request: Request\):)',
            'replacement': r'\1async def api_sessions_spawn(request: Request, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.post\("/api/sessions/send"\)\s*\n)(async def api_sessions_send\(request: Request\):)',
            'replacement': r'\1async def api_sessions_send(request: Request, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.get\("/api/sessions/list"\)\s*\n)(async def api_sessions_list\(\):)',
            'replacement': r'\1async def api_sessions_list(username: str = Depends(require_auth)):'
        },
        
        # System information endpoints
        {
            'pattern': r'(@app\.get\("/api/system-metrics"\)\s*\n)(async def api_system_metrics\(\):)',
            'replacement': r'\1async def api_system_metrics(username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.get\("/api/synapse/fleet"\)\s*\n)(async def api_synapse_fleet\(\):)',
            'replacement': r'\1async def api_synapse_fleet(username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.get\("/api/synapse/agent/\{agent_id\}/config"\)\s*\n)(async def api_get_agent_config\(agent_id: str\):)',
            'replacement': r'\1async def api_get_agent_config(agent_id: str, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.put\("/api/synapse/agent/\{agent_id\}/config"\)\s*\n)(async def api_save_agent_config\(agent_id: str, config: dict\):)',
            'replacement': r'\1async def api_save_agent_config(agent_id: str, config: dict, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.put\("/api/synapse/agent/\{agent_id\}/model"\)\s*\n)(async def api_update_agent_model\(agent_id: str, request: Request\):)',
            'replacement': r'\1async def api_update_agent_model(agent_id: str, request: Request, username: str = Depends(require_auth)):'
        },
        
        # Queue management
        {
            'pattern': r'(@app\.get\("/api/queue"\)\s*\n)(async def api_get_queue\(\):)',
            'replacement': r'\1async def api_get_queue(username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.post\("/api/queue"\)\s*\n)(async def api_create_queue_item\(item: QueueItemCreate\):)',
            'replacement': r'\1async def api_create_queue_item(item: QueueItemCreate, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.patch\("/api/queue/\{item_id\}"\)\s*\n)(async def api_update_queue_item\(item_id: str, updates: QueueItemUpdate\):)',
            'replacement': r'\1async def api_update_queue_item(item_id: str, updates: QueueItemUpdate, username: str = Depends(require_auth)):'
        },
        {
            'pattern': r'(@app\.delete\("/api/queue/\{item_id\}"\)\s*\n)(async def api_delete_queue_item\(item_id: str\):)',
            'replacement': r'\1async def api_delete_queue_item(item_id: str, username: str = Depends(require_auth)):'
        },
    ]
    
    modified_content = content
    applied_fixes = 0
    
    for fix in critical_fixes:
        pattern = fix['pattern']
        replacement = fix['replacement']
        
        if re.search(pattern, modified_content):
            modified_content = re.sub(pattern, replacement, modified_content)
            applied_fixes += 1
            print(f"✅ Applied fix for pattern: {pattern[:50]}...")
        else:
            print(f"⚠️  Pattern not found: {pattern[:50]}...")
    
    if applied_fixes > 0:
        with open(app_file, 'w') as f:
            f.write(modified_content)
        print(f"\n🔒 Applied {applied_fixes} critical security fixes")
        return True
    else:
        print("❌ No fixes were applied")
        return False

if __name__ == "__main__":
    print("🚨 Applying Critical Security Fixes to Mission Control...")
    print("=" * 60)
    
    success = apply_critical_fixes()
    
    if success:
        print("=" * 60)
        print("✅ Critical security fixes applied!")
        print("🔄 Restart Mission Control to apply changes")
        print("⚠️  Additional endpoints may still need protection")
    else:
        print("❌ Failed to apply security fixes")
        sys.exit(1)