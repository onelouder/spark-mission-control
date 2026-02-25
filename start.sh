#!/bin/bash

# Mission Control Launch Script
# Starts the Kanban dashboard at localhost:3000

cd "$(dirname "$0")"

echo "🚀 Starting Mission Control..."

# Check if Decapoda is running
if ! curl -s localhost:8766/v1/email/inbox > /dev/null 2>&1; then
    echo "⚠️  Warning: Decapoda-Lite API not detected at localhost:8766"
    echo "   Please ensure Decapoda is running for full functionality"
    echo ""
fi

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Start the server
echo "🌟 Mission Control starting at http://localhost:3000"
echo "   Press Ctrl+C to stop"
echo ""

python app.py