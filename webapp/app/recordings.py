"""Saving a recording into a script -- a new one, or the end of one that
already exists.

Both writes happen here rather than in the browser, so the order they
happen in and what a half-done save leaves behind are decided in one
place. The order is deliberate: the recording is written first, so a
failure to add the Run step afterwards still leaves the keys she typed
saved and named. Nothing here ever deletes a script to fake a rollback --
a recording cannot be typed again.

"Part of X" does not mean pasting the keys onto the end of X. It means
saving the recording as its own named script and adding a step to X that
runs it, so the recording stays something she can run, rename and reuse
on its own. Pasting the raw steps in is still available, and is what
add_run_step=False does.
"""

import re

from . import flatten, storage

# What goes between whatever X already did and the recorded keys. There is
# always something to wait for -- a menu closing, an animation -- and a
# gap that is visible and editable is easier to get right than a join with
# no gap at all, which never works and never says why.
JOINING_WAIT_SECONDS = 1.0

_RECORDING_NAME = re.compile(r"^Recording (\d+)$")


class SaveError(Exception):
    """A save that could not go ahead. status is what the browser is told;
    script is the recording, when one was written before the failure and
    is being kept."""

    def __init__(self, message: str, status: int = 400, script: dict = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.script = script


def next_recording_name(existing_names) -> str:
    """The first "Recording N" nobody is using.

    Counted from the names that exist rather than from a stored counter:
    a counter drifts every time one is deleted, and then offers a name
    that is already taken."""
    used = set()
    for name in existing_names:
        match = _RECORDING_NAME.match(name or "")
        if match:
            used.add(int(match.group(1)))
    number = 1
    while number in used:
        number += 1
    return f"Recording {number}"


def nodes_after_adding(target: dict, recorded_steps: list, add_run_step: bool) -> int:
    """How many steps the board would have to hold for the target once the
    recording is on the end of it.

    Worked out rather than compiled, because the recording does not exist
    yet at the point this is asked. A run step compiles to one repeat
    holding the recording's own steps, and a recording is only ever presses
    and waits, so its cost is exactly its length."""
    program = flatten.compile_steps(target["steps"], target["name"], target["id"])
    total = flatten.count_steps(program) + 1  # + the joining wait
    if add_run_step:
        return total + 1 + len(recorded_steps)
    return total + len(recorded_steps)


def save_recording(
    steps: list,
    name: str,
    description: str = "",
    target_id: str = None,
    target_name: str = None,
    target_rev: int = None,
    add_run_step: bool = True,
) -> dict:
    """Saves a recording, optionally onto the end of an existing script.

    Returns {"script": the recording or None, "target": the script it was
    added to or None, "warning": a message when the recording was saved but
    the step could not be added}. Raises SaveError when nothing usable
    happened."""
    if not steps:
        raise SaveError("There are no recorded keys to save.")
    if target_id is None:
        return {
            "script": storage.save_script(None, name, description, steps),
            "target": None,
            "warning": "",
        }

    shown_name = target_name or target_id
    target = storage.get_script(target_id)
    if target is None:
        if not add_run_step:
            raise SaveError(
                f"“{shown_name}” no longer exists, so nothing was saved. Your "
                "recording is still here -- save it as its own script instead.",
                404,
            )
        script = storage.save_script(None, name, description, steps)
        raise SaveError(
            f"Saved as “{name}” on its own. “{shown_name}” no longer exists, so "
            "nothing was added to it.",
            404,
            script,
        )

    current_rev = target["rev"]
    if target_rev is not None and target_rev != current_rev:
        raise SaveError(
            f"“{target['name']}” changed in another tab, reload before saving", 409
        )

    try:
        nodes = nodes_after_adding(target, steps, add_run_step)
        limit = flatten.max_program_nodes()
    except flatten.FlattenError as e:
        raise SaveError(f"“{target['name']}” can't be compiled as it is: {e}")
    if nodes > limit:
        raise SaveError(
            f"That would leave “{target['name']}” at {nodes} steps, and the Pico "
            f"can hold {limit}. Nothing was saved. Shorten the recording, or take "
            f"something out of “{target['name']}” first."
        )

    if add_run_step:
        script = storage.save_script(None, name, description, steps)
        added = [["wait", JOINING_WAIT_SECONDS], ["run", script["id"], 1]]
    else:
        script = None
        added = [["wait", JOINING_WAIT_SECONDS]] + steps

    try:
        saved_target = storage.save_script(
            target_id,
            target["name"],
            target.get("description", ""),
            target["steps"] + added,
            expected_rev=current_rev,
        )
    except (storage.RevMismatch, OSError):
        # The second write is the one that can fail with the first already
        # done. The recording stays exactly as it is -- deleting it to make
        # the two writes look atomic would throw away the only copy of
        # something that cannot be typed again.
        if script is None:
            raise SaveError(
                f"“{target['name']}” changed while this was being saved, so nothing "
                "was written. Your recording is still here -- try again.",
                409,
            )
        return {
            "script": script,
            "target": None,
            "warning": (
                f"Saved as “{name}”, but couldn't add the Run step to "
                f"“{target['name']}”. The recording is safe, add the step yourself."
            ),
        }

    return {"script": script, "target": saved_target, "warning": ""}
