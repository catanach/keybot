#!/bin/bash
# Setup launchd agent for autonomous keybot webapp monitoring on macOS
# This ensures Docker stays running and restarts if it crashes

set -e

# This script lives in webapp/, so the repo root is one level up, not two.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP_DIR="$REPO_ROOT/webapp"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCHD_DIR/com.keybot.webapp.monitor.plist"
SCRIPT_PATH="$REPO_ROOT/health-check.sh"

echo "🔧 Setting up macOS launchd automation for keybot webapp"
echo "========================================================="
echo ""

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCHD_DIR"

# Create the plist file
cat > "$PLIST_FILE" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.keybot.webapp.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>SCRIPT_PLACEHOLDER</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>StandardOutPath</key>
    <string>/tmp/keybot-monitor.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/keybot-monitor.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

# Replace placeholder with actual script path
sed -i '' "s|SCRIPT_PLACEHOLDER|$SCRIPT_PATH|g" "$PLIST_FILE"

# Load the launchd agent
echo "📋 Installing launchd agent..."
launchctl load "$PLIST_FILE"

echo ""
echo "✅ Setup complete!"
echo ""
echo "The webapp will now be monitored automatically:"
echo "  • Runs every 60 seconds"
echo "  • Restarts Docker if app is not responding"
echo "  • Logs to /tmp/keybot-monitor.log"
echo ""
echo "Management commands:"
echo "  View logs:   tail -f /tmp/keybot-monitor.log"
echo "  Unload:      launchctl unload ~/Library/LaunchAgents/com.keybot.webapp.monitor.plist"
echo "  Reload:      launchctl load ~/Library/LaunchAgents/com.keybot.webapp.monitor.plist"
echo ""
echo "To start the webapp initially, run:"
echo "  cd $WEBAPP_DIR && make deploy"
