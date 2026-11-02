**Adjudication (dev manager)**

Product and Dev agree on the core call: close #18 with retroactive approval of Option A. I checked the antagonist's finding directly against `src/code.py:160-172` and `webapp/app/main.py:614-618` — it's accurate. The `/host_writes?enabled=0` path swallows the exact `OSError` it would hit in the one case that matters, and reports success anyway. It's unreachable from today's UI (`app.js` only ever sends `enabled: true`), so no live impact, but it's a real, shipped bug in code whose own doc comment promises it works.

Decision: this doesn't block closing #18 — the deploy story #18 was actually about is verified end to end. But three small fixes land together before or with the close, not deferred to a future issue where they'll be forgotten:

1. `deploy.sh:69` — wrong "press reset twice" instruction, one-line text fix.
2. `src/code.py:167-170` — the `/host_writes` false branch, check the postcondition or surface the error instead of swallowing it.

No remote/no-touch recovery follow-up is buildable, per Dev's physics argument — accepted. The banner idea (Product) is filed as its own small issue, scoped exactly as Dev sized it: UI-only, ~half a day, no remote-trigger implication in the title.
