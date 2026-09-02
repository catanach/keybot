#!/bin/bash
# Run periodically by a LaunchAgent (see com.rosy.keybot-updater.plist).
# Pulls the latest keybot code and rebuilds the webapp container if
# anything under webapp/ changed. Everything this script does is written
# to update.log next to it, so its status can be checked by just reading
# that file, no need to run anything or report back manually.

set -eo pipefail

# LaunchAgents run with a very bare PATH -- make sure docker and git are
# actually findable regardless of where they're installed.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root (this script lives in webapp/)
LOG="webapp/update.log"

{
  echo "=== $(date) ==="

  # First, ensure Docker Desktop is actually running
  if ! docker info > /dev/null 2>&1; then
    echo "Docker not responding. Running Docker startup script..."
    bash webapp/start-docker-and-app.sh 2>&1 | tail -20
    
    # Final check
    if ! docker info > /dev/null 2>&1; then
      echo "ERROR: Docker startup failed. Container will not be available."
      echo "Manual action required: Please ensure Docker Desktop is running on the Mac."
      exit 1
    fi
  fi
  
  echo "Docker is running, proceeding with update check..."

  BEFORE=$(git rev-parse HEAD)
  git fetch origin main --quiet
  git merge --ff-only origin/main --quiet
  AFTER=$(git rev-parse HEAD)
  
  # Check if there are local changes ahead of origin (unpushed commits)
  LOCAL_AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo 0)

  if [ "$BEFORE" != "$AFTER" ] || [ "$LOCAL_AHEAD" -gt 0 ]; then
    if [ "$BEFORE" != "$AFTER" ]; then
      echo "Updated $BEFORE -> $AFTER"
    fi
    if [ "$LOCAL_AHEAD" -gt 0 ]; then
      echo "Local branch is ahead of origin by $LOCAL_AHEAD commit(s)"
    fi
    # Check if webapp/ has any changes (either pulled or local)
    if git diff --name-only "$BEFORE" "$AFTER" | grep -q '^webapp/' || \
       ([ "$LOCAL_AHEAD" -gt 0 ] && git diff --name-only origin/main | grep -q '^webapp/'); then
      echo "webapp/ changed, rebuilding the container with fresh image..."
      (cd webapp && docker compose down --remove-orphans 2>&1 || true)
      echo "Building image without cache to ensure app.js is current..."
      (cd webapp && docker compose build --no-cache 2>&1 | tail -15)
      echo "Starting container..."
      (cd webapp && docker compose up -d 2>&1 | tail -5)
    else
      echo "No webapp/ changes in this update, skipping rebuild."
    fi
  else
    echo "Already up to date, ensuring container is running..."
    cd webapp
    # Make sure container is actually running
    if ! docker compose ps -q | grep -q .; then
      echo "Container not running, starting it..."
      docker compose up -d 2>&1 | tail -3
    fi
  fi

  cd webapp
  echo "Container status:"
  docker compose ps 2>&1
  
  # Wait for app to start
  sleep 3
  
  # Real verification: check what's actually being served
  echo ""
  echo "=== DEPLOYMENT VERIFICATION ==="
  
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/app.js 2>/dev/null || echo "000")
  
  if [ "$HTTP_STATUS" = "200" ]; then
    ACTUAL_SIZE=$(curl -s http://localhost:8000/static/app.js | wc -c)
    echo "✓ App is responding (HTTP 200)"
    echo "  app.js actual size: $ACTUAL_SIZE bytes"
    
    if [ $ACTUAL_SIZE -gt 30000 ]; then
      echo "  ✓ Size correct (>30KB) - NEW CODE is being served"
    else
      echo "  ✗ Size too small (<30KB) - OLD CODE is being served"
    fi
  else
    echo "✗ App not responding (HTTP $HTTP_STATUS)"
    echo "  Restarting container..."
    docker compose restart
    sleep 5
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/app.js 2>/dev/null || echo "000")
    echo "  Status after restart: HTTP $HTTP_STATUS"
  fi
  
  echo ""
  
} >> "$LOG" 2>&1

# Keep the log from growing forever.
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
