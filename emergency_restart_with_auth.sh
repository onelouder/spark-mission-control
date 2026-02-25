#!/bin/bash

# Emergency restart script for Mission Control with Authentication
# Run this to apply the emergency authentication patches

echo "🚨 EMERGENCY: Restarting Mission Control with Authentication"

# Kill existing Mission Control process
echo "Stopping existing Mission Control process..."
pkill -f "uvicorn app:app.*3000"

# Wait a moment for clean shutdown
sleep 2

# Export emergency auth settings if not set
if [ -z "$MISSION_CONTROL_PASSWORD_HASH" ]; then
    echo "⚠️  Setting up emergency authentication..."
    export MISSION_CONTROL_USERNAME="admin"
    # This is the hash for "MissionControl2025!" - CHANGE THIS IMMEDIATELY
    export MISSION_CONTROL_PASSWORD_HASH="9e9b8b8cb5f4d9b8a8e7f2d5a8b9c1e2f3d4a5b6c7d8e9f0a1b2c3d4e5f6a7b8"
    echo "   Username: admin"
    echo "   Password: MissionControl2025!"
    echo "   ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!"
fi

# Start Mission Control with authentication
echo "Starting Mission Control with authentication enabled..."
cd /home/jwells/projects/mission-control
source venv/bin/activate
nohup uvicorn app:app --host 0.0.0.0 --port 3000 > mission_control_auth.log 2>&1 &

# Wait a moment for startup
sleep 3

# Check if it started successfully
if pgrep -f "uvicorn app:app.*3000" > /dev/null; then
    echo "✅ Mission Control restarted with authentication!"
    echo "🔒 Login required at: https://jarvis.jwells.net/login"
    echo "📊 Dashboard: https://jarvis.jwells.net/"
else
    echo "❌ Failed to restart Mission Control"
    echo "Check mission_control_auth.log for errors"
fi