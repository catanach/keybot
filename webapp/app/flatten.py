"""Resolves a script's "run" steps (references to other scripts) into a
single flat list of plain press/wait steps that the Pico can run.

The Pico itself knows nothing about script composition -- it only ever
runs a flat list of ["press", ...] / ["wait", ...] steps, exactly like
before. All of the "run script A once, then script B 10 times" logic
happens here, before anything is sent to the device.
"""

from . import storage

MAX_FLATTENED_STEPS = 2000


class FlattenError(Exception):
    """Raised when a script can't be flattened: a cycle, a missing
    reference, a bad step, or too many resulting steps."""


def flatten_script(script_id: str, _stack: tuple = ()) -> list:
    if script_id in _stack:
        chain = " -> ".join(_stack + (script_id,))
        raise FlattenError(f"circular reference: {chain}")

    script = storage.get_script(script_id)
    if script is None:
        raise FlattenError(f"script not found: {script_id}")

    stack = _stack + (script_id,)
    result = []

    for step in script.get("steps", []):
        if not step:
            continue
        kind = step[0]

        if kind == "press":
            if len(step) != 3:
                raise FlattenError(f"malformed press step in '{script['name']}': {step}")
            result.append(["press", step[1], step[2]])

        elif kind == "wait":
            if len(step) != 2:
                raise FlattenError(f"malformed wait step in '{script['name']}': {step}")
            result.append(["wait", step[1]])

        elif kind == "run":
            if len(step) != 3:
                raise FlattenError(f"malformed run step in '{script['name']}': {step}")
            ref_id, ref_times = step[1], step[2]
            if ref_times < 1:
                raise FlattenError(
                    f"run step in '{script['name']}' must repeat at least once, got {ref_times}"
                )
            sub = flatten_script(ref_id, stack)
            result.extend(sub * ref_times)

        else:
            raise FlattenError(f"unknown step type '{kind}' in '{script['name']}'")

        if len(result) > MAX_FLATTENED_STEPS:
            raise FlattenError(
                f"this script expands to more than {MAX_FLATTENED_STEPS} steps -- "
                "reduce a repeat count somewhere"
            )

    return result


def step_duration(step) -> float:
    if step[0] == "press":
        return step[2]
    if step[0] == "wait":
        return step[1]
    return 0


def preview(script_id: str) -> dict:
    """Returns flattened step count and total estimated duration for one
    pass, or an error message if the script can't be flattened."""
    try:
        flat = flatten_script(script_id)
    except FlattenError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "step_count": len(flat),
        "duration_seconds": sum(step_duration(s) for s in flat),
    }
