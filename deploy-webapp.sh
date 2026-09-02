#!/bin/bash
# keybot webapp deployment script
# Restarts Docker with updated configuration and validates the app loads

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEBAPP_DIR="$REPO_ROOT/webapp"
PORT=5000
MAX_WAIT=30
HEALTH_CHECK_URL="http://localhost:$PORT/api/device/status"

echo "🚀 Keybot Webapp Deployment"
echo "======================================"
echo "Repo root: $REPO_ROOT"
echo "Webapp dir: $WEBAPP_DIR"
echo ""

# Step 1: Navigate to webapp directory
cd "$WEBAPP_DIR"

# Step 2: Stop existing container
echo "📋 Stopping existing Docker container..."
docker compose down 2>/dev/null || true
sleep 2

# Step 3: Start new container with updated configuration
echo "🐳 Starting Docker container with updated configuration..."
docker compose up -d

# Step 4: Wait for app to be ready
echo "⏳ Waiting for app to be ready (max ${MAX_WAIT}s)..."
WAIT_TIME=0
APP_READY=false

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  if curl -s "$HEALTH_CHECK_URL" > /dev/null 2>&1; then
    APP_READY=true
    break
  fi
  WAIT_TIME=$((WAIT_TIME + 1))
  sleep 1
  echo -n "."
done
echo ""

if [ "$APP_READY" = false ]; then
  echo "❌ App failed to start within ${MAX_WAIT} seconds"
  echo "Docker logs:"
  docker compose logs --tail=20
  exit 1
fi

# Step 5: Verify HTML page loads
echo "📄 Verifying HTML page loads..."
if curl -s "http://localhost:$PORT/" | grep -q "keybot"; then
  echo "✅ HTML page loaded successfully"
else
  echo "❌ HTML page not loading correctly"
  echo "Page content:"
  curl -s "http://localhost:$PORT/" | head -20
  exit 1
fi

# Step 6: Verify static files
echo "📦 Verifying static files..."
if curl -s "http://localhost:$PORT/static/app.js" | grep -q "updateDeviceIndicator\|addToRecentScripts"; then
  echo "✅ app.js loaded with new functions"
else
  echo "⚠️  app.js may not have new functions"
fi

if curl -s "http://localhost:$PORT/static/style.css" | grep -q "device-indicator\|recent-scripts"; then
  echo "✅ style.css loaded with new styles"
else
  echo "⚠️  style.css may not have new styles"
fi

# Summary
echo ""
echo "======================================"
echo "✅ Deployment successful!"
echo "======================================"
echo ""
echo "App is running at:"
echo "  • http://localhost:$PORT"
echo "  • http://localhost:8000"
echo ""
echo "To view logs:"
echo "  docker compose -f $WEBAPP_DIR/docker-compose.yml logs -f"
echo ""
echo "To stop:"
echo "  docker compose -f $WEBAPP_DIR/docker-compose.yml down"
