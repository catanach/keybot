"""Runs a program of key presses. Shared by the Pico (code.py) and the dev
server (dev/server.py); pressing, waiting, releasing and yielding are passed
in, so both run identical logic.

A program is a list of steps:
    ["press", key_name, hold_seconds]
    ["wait", seconds]
    ["repeat", count, [ ...steps... ]]

A repeat holds its steps, not a copy per iteration, so "do this 1000 times"
is one step here and one frame while it runs.

Nothing here may raise while a script is running: a bad step stops that run
and is reported through status()["last_error"] instead.

This file is sent to the board in one request and has to fit in its memory,
so it is kept terse. The reasoning behind it is in README.md.
"""

# What this firmware can do, so the webapp can ask before sending a program
# this board could not run. Declared here rather than in code.py: the two
# deploy separately, and half an update must not claim the other half.
FEATURES = ["repeat"]

# The shape of script.json. Older firmware reads a v2 file as "not a list"
# and falls back to its built-in script, rather than half-run what it
# cannot read.
PROGRAM_FORMAT = 2

# How deeply scripts may nest. Each level costs one frame while running.
MAX_DEPTH = 8

# The most steps a program may hold -- a repeat counting as one step plus
# what is inside it, NOT once per iteration. Repeat counts themselves are
# deliberately not capped: that is the feature.
#
# Measured on the board, not guessed. Programs were pushed at increasing
# sizes: 600 steps (a ~12.6KB body) arrived and ran; 900 (~18.9KB) failed
# with a MemoryError, and so did everything larger. The allocation that
# fails is smaller than the body, so this is fragmentation rather than a
# clean free-bytes limit -- and free memory itself swings by ~14KB between
# collections. 500 is 600 with margin for that, for the overhead of nested
# JSON, and for a board busier than the one measured. Nesting means Rosy's
# real programs are around seven steps, so this is not a limit she will
# meet.
MAX_PROGRAM_NODES = 500

DEFAULT_SCRIPT = [
    ["press", "ENTER", 0.1],
    ["wait", 1.5],
    ["press", "ENTER", 0.1],
    ["wait", 1.5],
    ["press", "ONE", 0.1],
    ["wait", 3],
    ["press", "TWO", 0.1],
    ["wait", 6],
]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_repeat(step):
    return (
        isinstance(step, (list, tuple))
        and len(step) > 2
        and step[0] == "repeat"
        and isinstance(step[2], (list, tuple))
    )


def program_for_saving(script):
    """What to write to script.json: the program, plus its format."""
    return {"v": PROGRAM_FORMAT, "steps": script}


def program_from_saved(data):
    """The reverse. A plain list is what older firmware wrote and is still
    valid; anything else raises, so the caller falls back to the built-in
    script rather than run something half-understood."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data.get("v") == PROGRAM_FORMAT:
        steps = data.get("steps")
        if isinstance(steps, list):
            return steps
    raise ValueError("script.json was written by different firmware")


class ScriptRunner:
    def __init__(self, script, press_fn, sleep_fn, release_fn=None, tick_fn=None):
        self.script = script
        self.press_fn = press_fn  # press_fn(keycode_name, hold_seconds)
        self.sleep_fn = sleep_fn  # sleep_fn(seconds), returns early on stop
        self.release_fn = release_fn  # release_fn(), lets go of every key
        self.tick_fn = tick_fn  # before every step; serves the web server

        self.running = False
        self.stop_requested = False
        self.loop_count = 0
        self.current_step = 0
        self.current_total_steps = len(script)
        self.target_loops = None  # None means "loop forever until stopped"
        self.last_error = None  # Why the last run stopped early, if it did.
        # Frames of the run in progress, innermost last; None when idle. On
        # self because /status is served from inside the run loop.
        self._stack = None

        self._recompute_durations()

    def start(self, times=None):
        self.target_loops = times
        self.loop_count = 0
        self.current_step = 0
        self.current_total_steps = len(self.script)
        self.running = True
        self.stop_requested = False
        self.last_error = None

    def stop(self):
        self.stop_requested = True

    def finish_current_loop(self):
        """Let the pass in progress finish, then stop, instead of cutting it
        off mid-step. Used before a firmware deploy. Leaves an existing
        target alone if it would finish sooner."""
        if not self.running:
            return
        limit = self.loop_count + 1
        if self.target_loops is None or self.target_loops > limit:
            self.target_loops = limit

    def set_script(self, new_script):
        """Replaces the program. Raises ValueError if this board can't run
        it, or if something is running -- so a program can never be swapped
        out from under a run."""
        if self.running:
            raise ValueError(
                "a script is running on this device; stop it before sending another"
            )
        problem, steps = self._check(new_script)
        if problem is not None:
            raise ValueError(problem)
        if steps > MAX_PROGRAM_NODES:
            raise ValueError(
                "this program has {} steps and this board can hold {}".format(
                    steps, MAX_PROGRAM_NODES
                )
            )
        self.script = new_script
        self.current_total_steps = len(new_script)
        self._recompute_durations()

    def _check(self, steps, depth=1):
        """(what's wrong with this program or None, how many steps it holds).
        A repeat counts as one plus its contents, never once per iteration:
        what must fit in memory is the program, not the run. Runs when a
        program arrives, never in the run loop."""
        if not isinstance(steps, (list, tuple)):
            return "a script must be a list of steps", 0
        if depth > MAX_DEPTH:
            return "scripts are nested more than {} deep".format(MAX_DEPTH), 0
        count = 0
        for step in steps:
            count += 1
            if _is_repeat(step):
                if not isinstance(step[1], int) or isinstance(step[1], bool) or step[1] < 1:
                    return 'a "repeat" step needs a whole number of times, at least 1', count
                if not step[2]:
                    # Nothing to do, a million times over.
                    return 'a "repeat" step needs at least one step to repeat', count
                problem, inner = self._check(step[2], depth + 1)
                count += inner
            else:
                problem = self._step_problem(step)
            if problem is not None:
                return problem, count
        return None, count

    def _step_problem(self, step):
        """None if the step can be run, or what is wrong with it."""
        if not isinstance(step, (list, tuple)) or not step:
            return 'expected a step like ["press", "ENTER", 0.1] or ["wait", 2]'
        if step[0] == "press":
            if len(step) < 3 or not isinstance(step[1], str) or not _is_number(step[2]):
                return 'a "press" step needs a key name and a hold time in seconds'
            return None
        if step[0] == "wait":
            if len(step) < 2 or not _is_number(step[1]):
                return 'a "wait" step needs a number of seconds'
            return None
        return "unknown step type '{}'".format(step[0])

    def _step_duration(self, step):
        """A repeat takes its count times what is inside it -- worked out,
        never counted out. A nonsense step counts as zero, so /status keeps
        answering when the program is broken."""
        if _is_repeat(step):
            return step[1] * self._steps_duration(step[2])
        if self._step_problem(step) is not None:
            return 0
        if step[0] == "press":
            return step[2]
        if step[0] == "wait":
            return step[1]
        return 0

    def _steps_duration(self, steps):
        total = 0
        for step in steps:
            total += self._step_duration(step)
        return total

    def _recompute_durations(self):
        """Seconds left in a pass from each top-level step onward, worked out
        once when the program is set because several things poll /status.
        Entry 0 is a whole pass."""
        seconds_from_step = [0]
        for step in reversed(self.script):
            seconds_from_step.append(seconds_from_step[-1] + self._step_duration(step))
        seconds_from_step.reverse()
        self._seconds_from_step = seconds_from_step

    def _loop_duration(self):
        return self._seconds_from_step[0]

    def _remaining_in_pass(self):
        """Seconds left in the pass in progress, from the frames on the stack
        -- at most MAX_DEPTH of them. Each contributes the rest of the
        iteration it is in, plus its whole iterations still to come. Only
        the innermost frame counts the step it is on; in the frames above,
        that step is the repeat we are inside. Nothing walks an expanded
        program, because there isn't one."""
        if not self._stack:
            return self._loop_duration()
        innermost = len(self._stack) - 1
        total = 0
        for depth, frame in enumerate(self._stack):
            steps, index, done, times = frame
            for i in range(index if depth == innermost else index + 1, len(steps)):
                total += self._step_duration(steps[i])
            total += (times - done - 1) * self._steps_duration(steps)
        return total

    def _estimated_seconds_remaining(self):
        # An indefinite run (no "times" given) has no estimate.
        if not self.running or self.target_loops is None:
            return None
        remaining_passes = max(self.target_loops - self.loop_count - 1, 0)
        return self._remaining_in_pass() + remaining_passes * self._loop_duration()

    def _position(self):
        """Where the run has got to: which top-level part, which iteration."""
        if not self._stack:
            return None
        top = self._stack[0]
        position = {
            "part": top[1] + 1,
            "parts": len(top[0]),
            "iteration": None,
            "iterations": None,
        }
        if len(self._stack) > 1:
            repeat = self._stack[1]
            position["iteration"] = repeat[2] + 1
            position["iterations"] = repeat[3]
        return position

    def status(self):
        return {
            "running": self.running,
            "loop_count": self.loop_count,
            "target_loops": self.target_loops,
            "current_step": self.current_step,
            "total_steps": self.current_total_steps,
            "depth": len(self._stack) if self._stack else 0,
            "position": self._position(),
            "estimated_seconds_remaining": self._estimated_seconds_remaining(),
            "last_error": self.last_error,
            "features": FEATURES,
        }

    def _release_keys(self):
        """Let go of everything at the end of a pass, so a run that stopped
        partway can't leave a key down. None, or why it failed."""
        if self.release_fn is None:
            return None
        try:
            self.release_fn()
        except Exception as e:
            return "couldn't release the keys: {}: {}".format(type(e).__name__, e)
        return None

    def _where(self):
        """Where an error happened. Indices only: this file has never heard
        of script names, so the webapp puts those back."""
        if self._stack and len(self._stack) > 1:
            repeat = self._stack[1]
            return "stopped at part {}, repeat {} of {}, step {}: ".format(
                self._stack[0][1] + 1, repeat[2] + 1, repeat[3], self.current_step + 1
            )
        return "stopped at step {} of {}: ".format(
            self.current_step + 1, self.current_total_steps
        )

    def run_one_pass(self):
        """Runs the program once (or until stopped). Call it from your main
        loop whenever self.running is True. A failing step ends the run and
        records why in last_error; this never raises."""
        failed = False
        # A frame is [steps, index, iterations_done, total_iterations] and
        # holds a reference to its steps, never a copy, so a thousand
        # repeats cost one frame. index is the step being run right now, and
        # only moves on once that step is done -- so the time left always
        # counts the step in progress. The outermost frame is the program
        # itself, run once: that is what a pass is.
        self._stack = [[self.script, 0, 0, 1]]

        while self._stack:
            frame = self._stack[-1]
            steps = frame[0]
            index = frame[1]

            if index >= len(steps):
                # End of this frame's steps: go round again, or back out to
                # whatever asked for it and move that on past the repeat.
                frame[2] += 1
                if frame[2] >= frame[3]:
                    self._stack.pop()
                    if self._stack:
                        self._stack[-1][1] += 1
                else:
                    frame[1] = 0
                continue

            # Yield before every step, not only during waits, so a stop or a
            # status request is answered within one step.
            if self.tick_fn is not None:
                try:
                    self.tick_fn()
                except Exception:
                    # Serving a request must never take the run down with it.
                    pass

            if self.stop_requested:
                break

            step = steps[index]
            self.current_step = index
            self.current_total_steps = len(steps)

            if _is_repeat(step):
                if len(self._stack) >= MAX_DEPTH:
                    problem = "scripts are nested more than {} deep".format(MAX_DEPTH)
                else:
                    # This frame stays on the step it is on until the repeat
                    # below it finishes and moves it past.
                    self._stack.append([step[2], 0, 0, step[1]])
                    continue
            else:
                problem = self._step_problem(step)
                if problem is None:
                    try:
                        if step[0] == "press":
                            self.press_fn(step[1], step[2])
                        else:
                            self.sleep_fn(step[1])
                    except Exception as e:
                        problem = "{}: {}".format(type(e).__name__, e)
                if problem is None:
                    frame[1] = index + 1

            if problem is not None:
                self.last_error = self._where() + problem
                failed = True
                break

            if self.stop_requested:
                break

        self._stack = None

        release_problem = self._release_keys()
        if release_problem is not None:
            failed = True
            if not self.last_error:
                self.last_error = release_problem

        if failed or self.stop_requested:
            self.running = False
            self.stop_requested = False
        else:
            self.loop_count += 1
            if self.target_loops is not None and self.loop_count >= self.target_loops:
                self.running = False
