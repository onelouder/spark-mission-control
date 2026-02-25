#!/usr/bin/env python3
"""
Test script for the email processing system
"""

import asyncio
import httpx
import json
from contacts import load_contacts, get_contact_tier

async def test_system():
    """Test the email processing system"""
    
    print("🧪 Testing Email Processing System")
    print("=" * 50)
    
    # Test 1: Contact system
    print("1. Testing contact system...")
    try:
        contacts = load_contacts()
        print(f"   ✅ Loaded {len(contacts.get('top100', []))} contacts")
        
        if contacts.get('top20'):
            test_email = contacts['top20'][0]['email']
            tier = get_contact_tier(test_email, contacts)
            print(f"   ✅ Contact tier test: {test_email} -> {tier}")
        
    except Exception as e:
        print(f"   ❌ Contact system error: {e}")
    
    # Test 2: Configuration
    print("\n2. Testing configuration...")
    try:
        with open('data/config.json', 'r') as f:
            config = json.load(f)
        print(f"   ✅ Config loaded: {config['company_domain']}")
    except Exception as e:
        print(f"   ❌ Config error: {e}")
    
    # Test 3: API endpoints (if server is running)
    print("\n3. Testing API endpoints...")
    try:
        async with httpx.AsyncClient() as client:
            # Test contacts endpoint
            response = await client.get("http://localhost:3000/api/contacts")
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Contacts API: {len(data.get('top20', []))} top contacts")
            else:
                print(f"   ⚠️  Server not running (status {response.status_code})")
                
    except Exception as e:
        print(f"   ⚠️  Server not running: {e}")
    
    # Test 4: Email dashboard data structure
    print("\n4. Testing dashboard data structure...")
    try:
        from pipeline import get_dashboard_data
        dashboard = get_dashboard_data()
        
        print(f"   ✅ Dashboard structure loaded:")
        print(f"      - Needs response: {len(dashboard['needs_response'])}")
        print(f"      - Action items: {len(dashboard['action_items'])}")
        print(f"      - Meeting requests: {len(dashboard['meeting_requests'])}")
        print(f"      - FYI: {len(dashboard['fyi'])}")
        
    except Exception as e:
        print(f"   ❌ Dashboard error: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Basic system test complete!")
    print("\nNext steps:")
    print("1. Start the server: cd ~/projects/mission-control && source venv/bin/activate && python app.py")
    print("2. Visit http://localhost:3000 for Kanban")
    print("3. Visit http://localhost:3000/email for Email Dashboard")
    print("4. Use the 'Process New Email' button to sync emails")

if __name__ == "__main__":
    asyncio.run(test_system())