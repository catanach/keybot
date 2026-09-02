#!/bin/bash
# Posts queued GitHub issues and comments on Rosy's behalf.
#
# The agent shells run in a sandboxed VM with no route to github.com, so
# they cannot post directly. This script runs from the LaunchAgent, which
# runs natively on the Mac where the gh CLI is already signed in. Agents
# drop a job file into .gh-queue/ and this drains it.
#
# Job file is JSON:
#   {"type":"issue",   "title":"...", "body":"...", "labels":"a,b"}
#   {"type":"comment", "issue":12,    "body":"..."}
#
# Results, including the URL of anything created, go to gh-bridge.log.

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
QUEUE="webapp/.gh-queue"
LOG="webapp/gh-bridge.log"
REPO="catanach/keybot"

mkdir -p "$QUEUE/done"

# Nothing queued: stay silent so the log doesn't fill with noise.
shopt -s nullglob
jobs=("$QUEUE"/*.json)
[ ${#jobs[@]} -eq 0 ] && exit 0

{
  echo "=== $(date) ==="
  if ! command -v gh > /dev/null 2>&1; then
    echo "gh CLI is not installed. Install it with: brew install gh"
    echo "Leaving ${#jobs[@]} job(s) queued."
    exit 0
  fi
  if ! gh auth status > /dev/null 2>&1; then
    echo "gh is installed but not signed in. Run: gh auth login"
    echo "Leaving ${#jobs[@]} job(s) queued."
    exit 0
  fi

  for job in "${jobs[@]}"; do
    name="$(basename "$job")"
    type=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('type',''))" "$job" 2>/dev/null)
    body_file="$QUEUE/.body.tmp"
    python3 -c "import json,sys;open(sys.argv[2],'w').write(json.load(open(sys.argv[1])).get('body',''))" "$job" "$body_file" 2>/dev/null

    if [ "$type" = "issue" ]; then
      title=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('title',''))" "$job")
      labels=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('labels',''))" "$job")
      args=(issue create --repo "$REPO" --title "$title" --body-file "$body_file")
      [ -n "$labels" ] && args+=(--label "$labels")
      if url=$(gh "${args[@]}" 2>&1); then
        echo "$name -> created $url"
      else
        echo "$name -> FAILED: $url"
        continue
      fi
    elif [ "$type" = "comment" ]; then
      num=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('issue',''))" "$job")
      if url=$(gh issue comment "$num" --repo "$REPO" --body-file "$body_file" 2>&1); then
        echo "$name -> commented on #$num $url"
      else
        echo "$name -> FAILED: $url"
        continue
      fi
    else
      echo "$name -> skipped, unknown job type '$type'"
      continue
    fi

    mv "$job" "$QUEUE/done/$name"
  done
  rm -f "$body_file" 2>/dev/null
} >> "$LOG" 2>&1

tail -n 400 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
