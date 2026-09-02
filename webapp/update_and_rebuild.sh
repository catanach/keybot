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

  if [ "$BEFORE" != "$AFTER" ]; then
    echo "Updated $BEFORE -> $AFTER"
    if git diff --name-only "$BEFORE" "$AFTER" | grep -q '^webapp/'; then
      echo "webapp/ changed, rebuilding the container..."
      (cd webapp && docker compose up -d --build)
    else
      echo "No webapp/ changes in this update, skipping rebuild."
    fi
  else
    echo "Already up to date."
  fi

  echo "Container status:"
  (cd webapp && docker compose ps 2>&1)
  echo ""
} >> "$LOG" 2>&1

# Keep the log from growing forever.
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
