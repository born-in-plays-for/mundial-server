#!/bin/bash
# start.sh — Start ngrok + backend, auto-publish the ngrok URL to GitHub Pages.
#
# Usage:
#   ./start.sh
#
# The API key is read from .env (API_FOOTBALL_KEY=...).
# For mock mode, set API_FOOTBALL_KEY=mock in .env.

set -e

SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
MUNDIAL_REPO="${MUNDIAL_REPO:-$(cd "$SERVER_DIR/../mundial" && pwd)}"
NGROK_PORT=5002
CONFIG_FILE="backend_config.json"

# Load API key from .env
ENV_FILE="$SERVER_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

if [ -z "$API_FOOTBALL_KEY" ]; then
    echo "ERROR: API_FOOTBALL_KEY not set. Add it to .env"
    exit 1
fi

# Kill any process already on the backend port
lsof -ti :$NGROK_PORT | xargs kill -9 2>/dev/null || true

# Start backend in background
echo "Starting backend on port $NGROK_PORT..."
python3 "$SERVER_DIR/backend.py" &
BACKEND_PID=$!
sleep 2

# Start ngrok, capturing JSON logs to a temp file so we can extract the URL
NGROK_LOG="/tmp/ngrok-log-$$.txt"
echo "Starting ngrok tunnel..."
ngrok http $NGROK_PORT --log=stdout --log-format=json --log-level=info > "$NGROK_LOG" 2>&1 &
NGROK_PID=$!

# Wait for the public URL to appear in the log (up to 15s)
NGROK_URL=""
for i in $(seq 1 15); do
    sleep 1
    NGROK_URL=$(python3 -c "
import json, sys
try:
    with open('$NGROK_LOG') as f:
        for line in f:
            try:
                d = json.loads(line)
                url = d.get('url', '')
                if url.startswith('https://'):
                    print(url)
                    sys.exit(0)
            except: pass
except: pass
" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
        break
    fi
done

if [ -z "$NGROK_URL" ]; then
    echo "ERROR: Could not get ngrok URL. ngrok log:"
    cat "$NGROK_LOG" 2>/dev/null || true
    kill $BACKEND_PID $NGROK_PID 2>/dev/null
    exit 1
fi

echo ""
echo "=========================================="
echo "  ngrok URL: $NGROK_URL"
echo "=========================================="
echo ""

# Update backend_config.json in the mundial repo and push to GitHub Pages
if [ -d "$MUNDIAL_REPO/.git" ]; then
    echo "{\"backend_url\": \"$NGROK_URL\"}" > "$MUNDIAL_REPO/$CONFIG_FILE"
    cd "$MUNDIAL_REPO"
    git add "$CONFIG_FILE"
    git commit -m "config: update backend URL to $NGROK_URL" --allow-empty 2>/dev/null || true
    git push 2>/dev/null || echo "WARNING: git push failed — update backend_config.json manually"
    cd "$SERVER_DIR"
else
    echo "WARNING: mundial repo not found at $MUNDIAL_REPO — update backend_config.json manually"
fi

echo ""
echo "Login:  $NGROK_URL/login"
echo "Admin:  $NGROK_URL/admin"
echo ""
echo "Remember to add $NGROK_URL to Google OAuth authorized JavaScript origins"
echo ""
echo "Press Ctrl+C to stop everything."

# Wait and cleanup on exit
trap "kill $BACKEND_PID $NGROK_PID 2>/dev/null; rm -f '$NGROK_LOG'; echo 'Stopped.'" EXIT
wait
