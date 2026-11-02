## Grooming complete. Plan for approval.

Issue #18 shipped before grooming happened: Option A (`storage.remount` in `boot.py`) was implemented, tested on the board, and verified across commits dfa42e0, 7091437, 08f842b. Recommend closing #18 with retroactive approval rather than re-litigating a decision already on the board.

Grooming found two small bugs the shipping report missed:

- `deploy.sh:69` still says "press reset twice" — a Pico W has no reset button. Text-only fix.
- `src/code.py:160-172`: asking the board to "take its drive back" silently does nothing if it can't write to itself yet, but still reports success. Not reachable from the app today, so no live impact, but a live trap for whenever it is used.

Land both fixes in one small pass, then close #18.

What's deferred: a recovery path that never needs you to touch the board isn't buildable — once the board stops answering, no channel is left to reach it. Filing a separate small issue instead: a plain-language banner showing the two physical recovery steps when the board stops responding (about half a day, no new device code).

Needs you: okay to close #18, and to open the banner as its own issue rather than reopening this one?
