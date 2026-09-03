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
REPO_ROOT="$(pwd)"
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

  # Post anything the agents have queued for GitHub. Runs here because the
  # LaunchAgent is the only part of this system with both network access
  # and signed-in credentials.
  bash webapp/gh-bridge.sh || echo "gh-bridge failed, continuing"

  # Fire a pending firmware deploy if the Pico has come back on the network.
  bash webapp/deploy-when-back.sh || echo "deploy-when-back failed, continuing"

  BEFORE=$(git rev-parse HEAD)
  git fetch origin main --quiet
  git merge --ff-only origin/main --quiet
  AFTER=$(git rev-parse HEAD)
  
  # Check if there are local changes ahead of origin (unpushed commits)
  LOCAL_AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo 0)

  # Work out what changed BEFORE pushing. Pushing resets the ahead-count,
  # so deciding on a rebuild afterwards would miss local webapp changes
  # and quietly leave the old container running.
  CHANGED_FILES=$( { git diff --name-only "$BEFORE" "$AFTER"; \
                     git diff --name-only origin/main HEAD; } | sort -u )
  NEEDS_REBUILD=0
  if echo "$CHANGED_FILES" | grep -q '^webapp/'; then
    NEEDS_REBUILD=1
  fi

  # Push any local commits made by the agent team. The LaunchAgent runs
  # natively on the Mac, so it has the network access and credentials that
  # the sandboxed agent shells do not. This is what makes autonomous
  # deploys possible without asking the director to run git commands.
  if [ "$LOCAL_AHEAD" -gt 0 ]; then
    echo "Pushing $LOCAL_AHEAD local commit(s) to origin/main..."
    if git push origin main 2>&1; then
      echo "Push succeeded."
      git fetch origin main --quiet
      LOCAL_AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo 0)
    else
      echo "Push failed. Leaving commits local."
    fi
  fi

  if [ "$NEEDS_REBUILD" -eq 1 ]; then
    if [ "$BEFORE" != "$AFTER" ]; then
      echo "Updated $BEFORE -> $AFTER"
    fi
    if [ "$LOCAL_AHEAD" -gt 0 ]; then
      echo "Local branch is ahead of origin by $LOCAL_AHEAD commit(s)"
    fi
    if [ "$NEEDS_REBUILD" -eq 1 ]; then
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
    cd "$REPO_ROOT/webapp"
    # Make sure container is actually running
    if ! docker compose ps -q | grep -q .; then
      echo "Container not running, starting it..."
      docker compose up -d 2>&1 | tail -3
    fi
  fi

  cd "$REPO_ROOT/webapp"
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
