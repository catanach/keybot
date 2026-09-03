# How issues get groomed

Every new issue on this repo goes through a grooming conversation before any
code is written. The conversation happens in the issue itself so Rosy can read
how a decision was reached, not just what it was. She approves at the end.

An issue is "groomed" once it has a comment whose first line is
`## Grooming complete. Plan for approval.` Anything without that comment is
still waiting.

## The rounds, in order

1. **Dev manager** files the issue with a high-level design: the problem, where
   it shows up in the code, and the shape of the fix. Enough for the others to
   argue with, not a specification.

2. **Product** refines it for usability. Literal UI text, not descriptions of
   text. What the user sees in the failure cases. Where the v1 line is drawn and
   what is explicitly out. Product says plainly if an issue is mis-scoped,
   should merge with another, or should be closed.

3. **Dev** responds with the implementation approach, the files touched, a size
   estimate, and anything product asked for that the code will not support or
   that costs more than they think. Dev also calls out ordering and
   dependencies between issues.

4. **Antagonist** attacks the agreement. Only where there is a real finding:
   silence on an issue is a useful signal, and a comment written to have written
   one is worse than none. Every point names a specific mechanism by which
   something breaks, and where.

5. **Dev manager** adjudicates any dispute, then posts the approval summary:
   `## Grooming complete. Plan for approval.` Under 200 words. What changes,
   what grooming changed about it, what is deferred, and anything that needs
   Rosy specifically. It ends by asking her to approve.

Rosy approves in the issue. Only then does implementation start, with QA
reviewing each PR.

## Posting from an agent

The agent shells have no route to github.com. The LaunchAgent on the Mac does,
and it drains a queue every two minutes via the `gh` CLI. Drop a JSON file into
`webapp/.gh-queue/`:

    {"type": "issue",   "title": "...", "body": "..."}
    {"type": "comment", "issue": 12,    "body": "..."}

Files are processed in filename order, so prefix them to control sequence.
Results, including the URL of anything created, land in `webapp/gh-bridge.log`,
and finished jobs move to `webapp/.gh-queue/done/`. See `webapp/gh-bridge.sh`.

## Writing style in issues

Rosy is a product manager, not an engineer, and she reads every one of these.
Name the file and the line when making a claim. Say what breaks and for whom.
Skip the throat-clearing.
