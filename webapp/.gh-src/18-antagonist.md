**Antagonist review.**

Process point (shipping without grooming) already named by Product, agree, not re-litigating.

On the actual mechanism, one thing survives scrutiny: **the "take the drive back" direction of `/host_writes` cannot ever work when it's the one thing that matters, and it lies about it.**

`src/code.py:160-172`:

```python
if wanted:
    with open("/HOST_WRITES", "w") as f:
        f.write("")
else:
    try:
        os.remove("/HOST_WRITES")
    except OSError:
        pass
...
return Response(request, "ok")
```

The `enabled=false` branch swallows `OSError` locally and always returns `ok`. That's fine when the file simply doesn't exist. But the one time this branch is actually needed — clearing `HOST_WRITES` while it's set — is exactly the state where `boot.py` has *not* remounted the filesystem writable for the board (that's the whole point of the marker), so the board's own `os.remove` on `/` fails with a read-only-filesystem `OSError`. The exception is caught, nothing is removed, and the handler still answers `ok`. `main.py:614-618` then tells Rosy "Done... the board takes its drive back" — false. On the next power cycle `boot.py` still finds `HOST_WRITES` and hands the drive to the Mac again, and Rosy has no reason to suspect it, because the API told her it worked.

This isn't reachable from the current UI — `app.js:1954-1958` only ever POSTs `enabled: true`; the reverse is done by dragging the file off CIRCUITPY by hand. So it's dormant today. But it's a real, currently-shipped defect in an endpoint whose name and doc comment (`device.py:140-145`, "the recovery path that does not need safe mode") promise a working reversal. Anyone who calls this endpoint directly, or a future "take it back" button someone adds without re-reading `boot.py`, gets a silent no-op dressed as success, with no error surfaced until the next deploy fails for a reason nothing points them back to.

Cheap fix: don't swallow the exception, or check the postcondition (`"HOST_WRITES" not in os.listdir("/")`) before claiming success. Small enough to land with the `deploy.sh:69` fix in the same pass — this one actually needs it, since the `deploy.sh` text fix is comment-only and can't regress behavior, while this one is untested code that will lie the moment it's exercised.

Nothing else here — the boot.py try/except, the HOST_WRITES to "hand to Mac" direction, and the #16/#17 sequencing all check out against the actual files.
