#!/bin/bash
# Robust Docker and app startup script
# Ensures Docker Desktop is running and the webapp container is started

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

KEYBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP_DIR="$KEYBOT_DIR/webapp"

{
  echo "=== Docker Startup Script $(date) ==="
  
  # Check if Docker is actually running by looking for the process
  if pgrep -f "Docker.app" > /dev/null; then
    echo "Docker Desktop process found"
  else
    echo "Docker Desktop not running, attempting to start..."
    # Use open command which works on macOS
    open -a Docker > /dev/null 2>&1 &
    
    # Wait up to 90 seconds for Docker to start
    echo "Waiting for Docker Desktop to start..."
    for i in {1..30}; do
      if docker info > /dev/null 2>&1; then
        echo "Docker started successfully"
        break
      fi
      echo "  Attempt $i/30... waiting"
      sleep 3
    done
  fi
  
  # Final check
  if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not responding after 90 seconds"
    echo "Manual intervention required: Please start Docker Desktop manually"
    exit 1
  fi
  
  echo "Docker is confirmed running"
  echo ""
  echo "Container status before start:"
  cd "$WEBAPP_DIR"
  docker compose ps
  
  echo ""
  echo "Starting webapp container..."
  docker compose up -d
  
  echo ""
  echo "Waiting for app to initialize..."
  sleep 5
  
  echo ""
  echo "Container status after start:"
  docker compose ps
  
  echo ""
  echo "Verifying app is responding..."
  for i in {1..10}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/app.js 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
      SIZE=$(curl -s http://localhost:8000/static/app.js | wc -c)
      echo "✓ App is responding. app.js size: $SIZE bytes"
      if [ $SIZE -gt 30000 ]; then
        echo "✓ NEW CODE is being served (size > 30KB)"
      else
        echo "✗ OLD CODE being served (size < 30KB)"
      fi
      break
    else
      echo "  Attempt $i/10: HTTP $HTTP_CODE, waiting..."
      sleep 1
    fi
  done
  
  echo ""
  echo "Done"
  
} 2>&1
