#!/bin/bash
# Health check and container restart script
# Runs automatically via the update LaunchAgent if container is down

set -e
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

KEYBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP_DIR="$KEYBOT_DIR/webapp"
LOG="$WEBAPP_DIR/health-check.log"

{
  echo "=== Health Check at $(date) ==="
  
  # Ensure Docker is running
  if ! docker info > /dev/null 2>&1; then
    echo "Docker not responding, starting Docker Desktop..."
    open -a Docker 2>/dev/null || true
    sleep 30
    
    if ! docker info > /dev/null 2>&1; then
      echo "ERROR: Docker failed to start"
      exit 1
    fi
    echo "Docker started successfully"
  fi
  
  # Check if container is running
  cd "$WEBAPP_DIR"
  
  CONTAINER_STATUS=$(docker compose ps -q 2>/dev/null | wc -l)
  
  if [ "$CONTAINER_STATUS" -eq 0 ]; then
    echo "Container not running, starting it..."
    docker compose up -d 2>&1 | tail -5
  else
    echo "Container is running"
    # Try to reach the app
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/app.js 2>/dev/null || echo "000")
    echo "HTTP status for app.js: $HTTP_STATUS"
    
    if [ "$HTTP_STATUS" != "200" ]; then
      echo "App not responding properly, restarting container..."
      docker compose restart 2>&1 | tail -3
    fi
  fi
  
  echo "Container status:"
  docker compose ps
  echo "Health check complete"
  
} >> "$LOG" 2>&1

# Keep log from growing forever
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" || true
