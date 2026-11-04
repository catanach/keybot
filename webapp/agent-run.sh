#!/bin/bash
# Runs a queued shell snippet natively on the Mac.
#
# The agent shells have no network interfaces at all, so they cannot reach
# the Pico or the webapp on localhost. This is the one bridge: the agent
# writes webapp/.agent-cmd.sh, the LaunchAgent runs it here, output goes to
# webapp/agent-run.log. The command file is removed first, so a snippet
# that hangs or crashes never runs twice.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
CMD="webapp/.agent-cmd.sh"
LOG="webapp/agent-run.log"
[ -f "$CMD" ] || exit 0
cp "$CMD" webapp/.agent-cmd.running
rm -f "$CMD"
: > "$LOG"
{
  echo "=== agent-run $(date) ==="
  bash webapp/.agent-cmd.running 2>&1
  echo "=== exit $? ==="
} >> "$LOG" 2>&1
rm -f webapp/.agent-cmd.running
