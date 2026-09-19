#!/bin/bash
# Pushes the teaim working tree to its own GitHub repo.
#
# teaim lives at ~/src/teaim and is a separate repo from keybot. The agent
# shells have no route to github.com, so they commit locally and this
# script, which runs from the keybot LaunchAgent natively on the Mac,
# does the push. Same arrangement as gh-bridge.sh, same reason.
#
# Silent when there is nothing to push, so update.log stays readable.

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
TEAIM="$HOME/src/teaim"

[ -d "$TEAIM/.git" ] || exit 0
cd "$TEAIM" || exit 0

AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo unknown)

if [ "$AHEAD" = "unknown" ]; then
  # No upstream yet. First push sets it, if there is anything to push.
  git rev-parse HEAD > /dev/null 2>&1 || exit 0
  echo "teaim: pushing initial commits and setting upstream..."
  git push -u origin main 2>&1 || echo "teaim: initial push failed"
  exit 0
fi

[ "$AHEAD" -eq 0 ] && exit 0

echo "teaim: pushing $AHEAD commit(s) to origin/main..."
git push origin main 2>&1 || echo "teaim: push failed, will retry next cycle"
