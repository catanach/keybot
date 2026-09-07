"""Turns a script's "run" steps (references to other scripts) into a program
the Pico can run.

Firmware that advertises the "repeat" feature understands nesting, so a
"run script B 1000 times" step compiles to one ["repeat", 1000, [...]] step
and the device does the repeating. The 1000 copies are never made, here or
there -- which is the whole point of issue #3.

Older firmware doesn't, so flatten_script() still writes every step out in
full for it. That path is capped, because writing out a long run is exactly
what the board has no room for.

Either way the script graph stays here: cycles, missing references and bad
steps are caught before anything is sent, and the device never learns that
scripts can refer to each other.
"""

import importlib.util

from . import storage
from .firmware import FIRMWARE_DIR, FirmwareError

# Only used on the fallback path, for a board too old to repeat by itself.
MAX_LEGACY_FLATTENED_STEPS = 2000

_max_program_nodes = None


def max_program_nodes() -> int:
    """The most steps a board can hold. Read from the same
    src/script_runner.py the Pico runs rather than copied here: the number
    was measured on the board, and a copy is how two numbers drift apart."""
    global _max_program_nodes
    if _max_program_nodes is None:
        path = FIRMWARE_DIR / "script_runner.py"
        spec = importlib.util.spec_from_file_location("keybot_script_runner", path)
        if spec is None or spec.loader is None:
            raise FirmwareError(f"can't read the step limit from {path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except OSError as e:
            raise FirmwareError(f"can't read the step limit from {path}: {e}")
        _max_program_nodes = module.MAX_PROGRAM_NODES
    return _max_program_nodes


class FlattenError(Exception):
    """Raised when a script can't be compiled: a cycle, a missing
    reference, a bad step, or too many resulting steps."""


def _script_for(script_id: str, _stack: tuple):
    """The script, with the cycle and missing-script checks that both
    compiling and flattening need."""
    if script_id in _stack:
        chain = " -> ".join(_stack + (script_id,))
        raise FlattenError(f"circular reference: {chain}")
    script = storage.get_script(script_id)
    if script is None:
        raise FlattenError(f"script not found: {script_id}")
    return script


def compile_script(script_id: str, _stack: tuple = ()) -> list:
    """The program to send to a board that understands repeats.

    A run step becomes one repeat step holding the referenced script's
    program -- including ["run", id, 1], which becomes a repeat of 1 rather
    than being inlined, so that part numbering matches what the run panel
    and any error message say.
    """
    script = _script_for(script_id, _stack)
    return compile_steps(script.get("steps", []), script["name"], script_id, _stack)


def compile_steps(
    steps: list, name: str = "this script", own_id: str = None, _stack: tuple = ()
) -> list:
    """The same, for a list of steps that is not (or not yet) a saved
    script -- the rows open in the editor, say. Everything the steps refer
    to is still looked up and checked exactly as it would be on the way to
    the device."""
    stack = _stack + ((own_id,) if own_id is not None else ())
    program = []

    for step in steps:
        if not step:
            continue
        kind = step[0]

        if kind == "press":
            if len(step) != 3:
                raise FlattenError(f"malformed press step in '{name}': {step}")
            program.append(["press", step[1], step[2]])

        elif kind == "wait":
            if len(step) != 2:
                raise FlattenError(f"malformed wait step in '{name}': {step}")
            program.append(["wait", step[1]])

        elif kind == "run":
            if len(step) != 3:
                raise FlattenError(f"malformed run step in '{name}': {step}")
            ref_id, ref_times = step[1], step[2]
            if not isinstance(ref_times, int) or isinstance(ref_times, bool) or ref_times < 1:
                raise FlattenError(
                    f"run step in '{name}' must repeat a whole number of "
                    f"times, at least once -- got {ref_times}"
                )
            body = compile_script(ref_id, stack)
            if not body:
                raise FlattenError(f"'{name}' runs a script with no steps in it")
            program.append(["repeat", ref_times, body])

        else:
            raise FlattenError(f"unknown step type '{kind}' in '{name}'")

    return program


def part_names(script_id: str) -> list:
    """One name per top-level part of the compiled program, or None for a
    part that is a plain press or wait.

    The device reports positions as numbers -- it has never heard of script
    names -- so this is what the webapp uses to say "part 2" as "Gathering".
    Built when the program is compiled and kept with the run, so a webapp
    restart part way through a run doesn't lose the names.
    """
    script = storage.get_script(script_id)
    if script is None:
        return []
    names = []
    for step in script.get("steps", []):
        if not step:
            continue
        if step[0] == "run" and len(step) == 3:
            referenced = storage.get_script(step[1])
            names.append(referenced["name"] if referenced else None)
        else:
            names.append(None)
    return names


def flatten_script(script_id: str, _stack: tuple = ()) -> list:
    """Every step written out in full, for firmware that can't repeat by
    itself. Capped: a long run written out is what the board has no room
    for, which is why newer firmware doesn't get one."""
    script = _script_for(script_id, _stack)
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

        if len(result) > MAX_LEGACY_FLATTENED_STEPS:
            raise FlattenError(
                f"this script writes out to more than {MAX_LEGACY_FLATTENED_STEPS} "
                "steps, which is more than the firmware on this Pico can hold. "
                "Deploy the current firmware from the Firmware panel and it will "
                "run the repeats itself, or reduce a repeat count somewhere."
            )

    return result


def step_duration(step) -> float:
    """How long one step takes. A repeat is its count times what is inside
    it, worked out rather than counted out -- the same sum the device does,
    so the estimate on screen matches the one on the board."""
    if step[0] == "press":
        return step[2]
    if step[0] == "wait":
        return step[1]
    if step[0] == "repeat":
        return step[1] * sum(step_duration(s) for s in step[2])
    return 0


def count_steps(program) -> int:
    """How many steps a program holds, a repeat counting as one plus what is
    inside it -- what gets sent to the board, not what gets run."""
    total = 0
    for step in program:
        total += 1
        if step[0] == "repeat":
            total += count_steps(step[2])
    return total


def preview(script_id: str) -> dict:
    """Step count and estimated duration for one pass, or why the script
    can't be run."""
    try:
        program = compile_script(script_id)
    except FlattenError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "step_count": count_steps(program),
        "duration_seconds": sum(step_duration(s) for s in program),
    }


def preview_steps(steps: list, name: str = "this script", own_id: str = None) -> dict:
    """The same for steps that have not been saved, plus the limit they are
    measured against. This is how the page can ask what the rows currently
    on screen would cost the board, which is the only honest question when
    the server has never seen them."""
    try:
        program = compile_steps(steps, name, own_id)
        limit = max_program_nodes()
    except (FlattenError, FirmwareError) as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "step_count": count_steps(program),
        "duration_seconds": sum(step_duration(s) for s in program),
        "limit": limit,
    }
