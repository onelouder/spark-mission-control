#!/usr/bin/env python3
"""
Bot Activity Monitor CLI

Command-line interface for testing and managing the bot activity monitoring system.
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path
import httpx

# Add the mission control directory to path
sys.path.append(str(Path(__file__).parent))

from bot_activity_monitor import BotActivityMonitor, get_monitor

MISSION_CONTROL_URL = "http://localhost:3000"

async def status_command():
    """Show current monitoring status"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{MISSION_CONTROL_URL}/api/bot-activity/status")
            if response.status_code == 200:
                data = response.json()
                print("🛡️ Bot Activity Monitor Status")
                print("=" * 50)
                
                metrics = data.get("current_metrics", {})
                print(f"Messages (1min): {metrics.get('message_count_1min', 'N/A')}")
                print(f"Messages (1hour): {metrics.get('message_count_1hour', 'N/A')}")
                print(f"Rate limit (requests): {metrics.get('rate_limit_requests_used_pct', 'N/A')}%")
                print(f"Rate limit (tokens): {metrics.get('rate_limit_tokens_used_pct', 'N/A')}%")
                print(f"Auth failures (1hour): {metrics.get('auth_failures_1hour', 'N/A')}")
                print(f"Unique IPs (1hour): {metrics.get('unique_ips_1hour', 'N/A')}")
                print(f"Suspicious IPs: {metrics.get('suspicious_ips_1hour', 'N/A')}")
                
                alerts = data.get("active_alerts", {})
                print(f"\nActive Alerts: {alerts.get('total', 0)}")
                
                if alerts.get("by_severity"):
                    for severity, alert_list in alerts["by_severity"].items():
                        if alert_list:
                            print(f"  {severity.upper()}: {len(alert_list)}")
                            for alert in alert_list:
                                print(f"    - {alert['title']}")
                
                print(f"\nMonitoring Status: {data.get('monitoring_status', 'unknown')}")
                
            else:
                print(f"❌ Error getting status: HTTP {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

async def test_command():
    """Generate test activity and alerts"""
    print("🧪 Generating test activity...")
    
    try:
        async with httpx.AsyncClient() as client:
            # Generate test activity
            response = await client.post(f"{MISSION_CONTROL_URL}/api/bot-activity/test-alert")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Test completed")
                print(f"New alerts generated: {result['new_alerts']}")
                
                if result.get("alerts"):
                    print("\nGenerated alerts:")
                    for alert in result["alerts"]:
                        print(f"  [{alert['severity'].upper()}] {alert['title']}: {alert['description']}")
                        
            else:
                print(f"❌ Test failed: HTTP {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

async def alerts_command():
    """Show current alerts"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{MISSION_CONTROL_URL}/api/bot-activity/alerts")
            if response.status_code == 200:
                data = response.json()
                
                active = data.get("active_alerts", [])
                history = data.get("alert_history", [])
                
                print("🚨 Active Alerts")
                print("=" * 50)
                if active:
                    for alert in active:
                        print(f"[{alert['severity'].upper()}] {alert['title']}")
                        print(f"  Description: {alert['description']}")
                        print(f"  Time: {alert['timestamp']}")
                        print(f"  ID: {alert['id']}")
                        print()
                else:
                    print("No active alerts ✅")
                
                print(f"\n📜 Recent Alert History ({len(history)} items)")
                print("=" * 50)
                for alert in history[-5:]:  # Show last 5
                    status = "RESOLVED" if alert.get("resolved") else "ACTIVE"
                    print(f"[{alert['severity'].upper()}] {alert['title']} ({status})")
                    print(f"  Time: {alert['timestamp']}")
                    print()
                    
            else:
                print(f"❌ Error getting alerts: HTTP {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

async def resolve_command(alert_id: str):
    """Resolve an alert"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{MISSION_CONTROL_URL}/api/bot-activity/resolve-alert/{alert_id}")
            if response.status_code == 200:
                print(f"✅ Alert {alert_id} resolved")
            elif response.status_code == 404:
                print(f"❌ Alert {alert_id} not found")
            else:
                print(f"❌ Error resolving alert: HTTP {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

async def simulate_command(activity_type: str, count: int = 10):
    """Simulate bot activity for testing"""
    print(f"🎭 Simulating {count} {activity_type} events...")
    
    monitor = get_monitor()
    
    if activity_type == "messages":
        for i in range(count):
            monitor.record_message(ip="192.168.1.100")  # Simulate trusted IP
            await asyncio.sleep(0.1)  # Small delay
            
    elif activity_type == "auth_failures":
        for i in range(count):
            monitor.record_auth_failure()
            await asyncio.sleep(0.1)
            
    elif activity_type == "suspicious_ips":
        # Simulate activity from multiple suspicious IPs
        suspicious_ips = ["203.0.113.1", "198.51.100.1", "192.0.2.1"]
        for i in range(count):
            ip = suspicious_ips[i % len(suspicious_ips)]
            for _ in range(6):  # Generate enough requests to trigger threshold
                monitor.record_message(ip=ip)
            await asyncio.sleep(0.1)
            
    elif activity_type == "volume_spike":
        # Generate a sudden spike in message volume
        baseline = 5
        spike = count * 3
        
        # Establish baseline
        for i in range(baseline):
            monitor.record_message()
            await asyncio.sleep(1)
            
        # Generate spike
        for i in range(spike):
            monitor.record_message()
            await asyncio.sleep(0.05)  # Rapid fire
            
    else:
        print(f"❌ Unknown activity type: {activity_type}")
        return
    
    print(f"✅ Simulated {count} {activity_type} events")
    
    # Trigger alert check
    print("🔍 Checking for new alerts...")
    alerts = await monitor.check_activity()
    if alerts:
        print(f"🚨 Generated {len(alerts)} new alerts:")
        for alert in alerts:
            print(f"  [{alert.severity.upper()}] {alert.title}")
    else:
        print("No new alerts generated")

async def daemon_command():
    """Run monitoring daemon"""
    print("🛡️ Starting Bot Activity Monitoring Daemon...")
    print("Press Ctrl+C to stop")
    
    monitor = BotActivityMonitor()
    try:
        await monitor.start_monitoring(check_interval=30)
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitoring daemon...")
        monitor.stop_monitoring()

def main():
    parser = argparse.ArgumentParser(description="Bot Activity Monitor CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Status command
    subparsers.add_parser("status", help="Show monitoring status")
    
    # Test command
    subparsers.add_parser("test", help="Generate test alerts")
    
    # Alerts command
    subparsers.add_parser("alerts", help="Show current alerts")
    
    # Resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Resolve an alert")
    resolve_parser.add_argument("alert_id", help="Alert ID to resolve")
    
    # Simulate command
    simulate_parser = subparsers.add_parser("simulate", help="Simulate bot activity")
    simulate_parser.add_argument("type", choices=["messages", "auth_failures", "suspicious_ips", "volume_spike"],
                               help="Type of activity to simulate")
    simulate_parser.add_argument("--count", "-c", type=int, default=10,
                               help="Number of events to simulate")
    
    # Daemon command
    subparsers.add_parser("daemon", help="Run monitoring daemon")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == "status":
        asyncio.run(status_command())
    elif args.command == "test":
        asyncio.run(test_command())
    elif args.command == "alerts":
        asyncio.run(alerts_command())
    elif args.command == "resolve":
        asyncio.run(resolve_command(args.alert_id))
    elif args.command == "simulate":
        asyncio.run(simulate_command(args.type, args.count))
    elif args.command == "daemon":
        asyncio.run(daemon_command())

if __name__ == "__main__":
    main()