#!/bin/bash
# Real verification script - checks ACTUAL HTTP response, not just logs

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

KEYBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP_DIR="$KEYBOT_DIR/webapp"
VERIFY_LOG="$WEBAPP_DIR/verify.log"

{
  echo "=== DEPLOYMENT VERIFICATION $(date) ==="
  
  # Check if Docker is running
  if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running"
    exit 1
  fi
  
  echo ""
  echo "=== CONTAINER STATUS ==="
  docker ps | grep keybot || echo "ERROR: keybot container not found!"
  
  echo ""
  echo "=== CHECKING ACTUAL HTTP RESPONSE ==="
  
  # Get actual file size of app.js being served
  RESPONSE=$(curl -s http://localhost:8000/static/app.js)
  ACTUAL_SIZE=$(echo "$RESPONSE" | wc -c)
  
  echo "Actual app.js size from HTTP response: $ACTUAL_SIZE bytes"
  echo ""
  
  # Check what version is actually being served
  echo "First 500 chars of served app.js:"
  echo "$RESPONSE" | head -c 500
  echo ""
  echo ""
  
  # Look for specific features in the response
  if echo "$RESPONSE" | grep -q "countdownState"; then
    echo "✓ GOOD: countdownState found (new code is being served)"
  else
    echo "✗ BAD: countdownState NOT found (old code is being served)"
  fi
  
  if echo "$RESPONSE" | grep -q "device-indicator-dot"; then
    echo "✓ GOOD: device-indicator-dot found"
  else
    echo "✗ BAD: device-indicator-dot NOT found"
  fi
  
  if echo "$RESPONSE" | grep -q "unreachable"; then
    echo "✓ GOOD: unreachable status code found"
  else
    echo "✗ BAD: unreachable status code NOT found"
  fi
  
  echo ""
  echo "=== COMPARING WITH DISK VERSION ==="
  
  DISK_SIZE=$(wc -c < "$WEBAPP_DIR/app/static/app.js" 2>/dev/null)
  echo "app.js size on disk: $DISK_SIZE bytes"
  echo "app.js size in HTTP response: $ACTUAL_SIZE bytes"
  
  if [ "$ACTUAL_SIZE" -gt 30000 ]; then
    echo "✓ Response size looks correct (>30KB)"
  else
    echo "✗ Response size is wrong (<30KB)"
  fi
  
  echo ""
  echo "=== DOCKER IMAGE INSPECTION ==="
  
  # Get running container ID
  CONTAINER_ID=$(docker ps -q --filter "name=keybot" | head -1)
  if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: Could not find running keybot container"
    exit 1
  fi
  
  echo "Container ID: $CONTAINER_ID"
  
  # Check volume mounts
  echo ""
  echo "Volume mounts in container:"
  docker inspect "$CONTAINER_ID" --format='{{range .Mounts}}{{.Type}} {{.Source}} => {{.Destination}}{{println}}{{end}}'
  
  # Check if app/ volume is mounted
  if docker inspect "$CONTAINER_ID" --format='{{range .Mounts}}{{.Destination}}{{println}}{{end}}' | grep -q '/app/app'; then
    echo "✓ Volume mount /app/app is present"
  else
    echo "✗ Volume mount /app/app is NOT present"
  fi
  
  echo ""
  echo "=== CONTAINER LOGS (last 20 lines) ==="
  docker logs "$CONTAINER_ID" 2>&1 | tail -20
  
} | tee -a "$VERIFY_LOG"

# Keep log from growing
tail -n 1000 "$VERIFY_LOG" > "$VERIFY_LOG.tmp" 2>/dev/null && mv "$VERIFY_LOG.tmp" "$VERIFY_LOG"
