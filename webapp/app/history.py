"""Run history: one record per run of a script on the device.

A record is opened when the device starts running and closed when it
stops. That work is done by the background poller in main.py rather than
by the Start button, because the Start button isn't the only thing that
starts a run -- a firmware deploy puts the previous script back by itself
-- and because a run has to be recorded whether or not a browser is open.

Records live in one JSON file next to the scripts, newest first, capped
at MAX_RECORDS. Every write goes to a temp file that is then renamed into
place, so the container being killed mid-write can't leave a half-written
file behind and lose the lot.

A record looks like:
{
    "id": "9f2c1a4b",
    "script_id": "a1b2c3d4",
    "script_name": "Overnight farm",
    "started_at": "2026-09-02T22:29:00Z",
    "ended_at": "2026-09-03T02:41:00Z",
    "loops_done": 500,
    "target_loops": 500,
    "outcome": "finished",
    "error": null
}

A record with outcome None is still open: the run was going when it was
written. ended_at, loops_done and outcome are filled in when it closes.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MAX_RECORDS = 50

# The four things that can happen to a run. Nothing else is ever written
# to a record's "outcome".
FINISHED = "finished"
STOPPED_BY_YOU = "stopped_by_you"
FAILED = "failed"
LOST_CONTACT = "lost_contact"


def _history_file() -> Path:
    # Read at call time, not import time, so the data dir can be pointed
    # somewhere else (a temp dir in the tests) without reimporting.
    return Path(os.environ.get("KEYBOT_DATA_DIR", "/data")) / "history.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load() -> list[dict]:
    """Every record, newest first. An unreadable file reads as empty
    rather than taking the app down with it."""
    path = _history_file()
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(records, list):
        return []
    return records


def _save(records: list[dict]) -> None:
    """Writes the history file in one move. json.dumps first so a bad
    record raises before the old file is touched, then a temp file in the
    same directory and os.replace, which either lands whole or not at
    all."""
    path = _history_file()
    text = json.dumps(records[:MAX_RECORDS], indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text)
    os.replace(temp, path)


def open_record(script_id: Optional[str], script_name: str, target_loops) -> str:
    """Starts a record for a run that has just begun. Returns its id, to
    hand back to close_record when the run ends."""
    record_id = uuid.uuid4().hex[:12]
    records = load()
    records.insert(
        0,
        {
            "id": record_id,
            "script_id": script_id,
            "script_name": script_name,
            "started_at": _now(),
            "ended_at": None,
            "loops_done": 0,
            "target_loops": target_loops,
            "outcome": None,
            "error": None,
        },
    )
    _save(records)
    return record_id


def close_record(record_id: str, loops_done: int, outcome: str, error: Optional[str] = None) -> None:
    """Fills in how a run ended. Does nothing if the record has already
    been closed or has fallen off the end of the list."""
    records = load()
    for record in records:
        if record.get("id") == record_id and record.get("outcome") is None:
            record["ended_at"] = _now()
            record["loops_done"] = loops_done
            record["outcome"] = outcome
            record["error"] = error
            _save(records)
            return


def close_open_records(outcome: str = LOST_CONTACT) -> int:
    """Closes every record still open, and says how many there were.

    Called on startup: an open record means the app stopped while a run
    was going -- a container restart, a crash -- and nobody is ever going
    to close it now. Leaving it open would strand it exactly the way a
    closed browser tab used to."""
    records = load()
    closed = 0
    for record in records:
        if record.get("outcome") is None:
            record["ended_at"] = _now()
            record["outcome"] = outcome
            closed += 1
    if closed:
        _save(records)
    return closed


def outcome_for(loops_done: int, target_loops, last_error, we_stopped_it: bool) -> str:
    """Which of the four outcomes a run that just ended gets.

    An error the device reported wins, because it's the most specific
    thing we know. Otherwise, our own /stop is what ended it. Otherwise
    it ran out its target. A run with no target only ever ends because
    something stopped it, so that lands on "you stopped it" too.
    """
    if last_error:
        return FAILED
    if we_stopped_it:
        return STOPPED_BY_YOU
    if target_loops is not None and loops_done >= target_loops:
        return FINISHED
    return STOPPED_BY_YOU
