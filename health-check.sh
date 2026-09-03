#!/bin/bash
# Health check for keybot webapp
# Restarts Docker if the app is not responding

WEBAPP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/webapp" && pwd)"
PORT=8000
# Probe the webapp's own page. This used to ask /api/device/status, which
# reports on the *Pico*, so an unplugged or wedged board looked like a dead
# webapp and this script restarted a perfectly healthy container.
HEALTH_URL="http://localhost:$PORT/"
LOG_FILE="/tmp/keybot-health.log"

# Check if app is responding
if ! curl -s --max-time 10 "$HEALTH_URL" > /dev/null 2>&1; then
  echo "[$(date)] App not responding at $HEALTH_URL - restarting..." >> "$LOG_FILE"

  # Restart Docker
  cd "$WEBAPP_DIR"
  docker compose down 2>/dev/null || true
  sleep 2
  docker compose up -d

  # Wait for app to come back
  sleep 5

  # Log result
  if curl -s --max-time 10 "$HEALTH_URL" > /dev/null 2>&1; then
    echo "[$(date)] ✅ App recovered after restart" >> "$LOG_FILE"
  else
    echo "[$(date)] ❌ App still not responding after restart" >> "$LOG_FILE"
  fi
else
  echo "[$(date)] ✅ App is healthy" >> "$LOG_FILE"
fi
