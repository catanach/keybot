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

  if ! docker info > /dev/null 2>&1; then
    echo "Docker doesn't seem to be running, trying to start Docker Desktop..."
    open -a Docker 2>/dev/null || true
    sleep 20
    if ! docker info > /dev/null 2>&1; then
      echo "Still not up. Skipping this check, will try again next run."
      echo ""
      exit 0
    fi
  fi

  BEFORE=$(git rev-parse HEAD)
  git fetch origin main --quiet
  git merge --ff-only origin/main --quiet
  AFTER=$(git rev-parse HEAD)
  
  # Check if there are local changes ahead of origin (unpushed commits)
  LOCAL_AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo 0)

  REBUILT=0
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
      (cd webapp && docker compose build --no-cache 2>&1 | tail -20)
      echo "Starting container..."
      (cd webapp && docker compose up -d 2>&1 | tail -5)
      REBUILT=1
    else
      echo "No webapp/ changes in this update, skipping rebuild."
    fi
  else
    echo "Already up to date."
  fi

  echo "Container status:"
  (cd webapp && docker compose ps 2>&1)
  
  # Wait a moment for the app to start
  sleep 3
  
  # Run comprehensive verification
  echo ""
  echo "Running deployment verification..."
  bash webapp/verify-deployment.sh 2>&1 | head -100
  
} >> "$LOG" 2>&1

# Keep the log from growing forever.
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
