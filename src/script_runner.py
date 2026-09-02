"""Shared logic for running a scripted sequence of key-press actions.

Both code.py (running on the Pico) and dev/server.py (running on your Mac)
import this file and use it the same way. The only thing that differs
between the two is how a single key press actually happens: on the Pico it
presses a real key, and on your Mac it does nothing but wait the same
amount of time. That's why key presses are passed in as a function
(press_fn) instead of being hardcoded here, and the same goes for waiting
(sleep_fn) - the Pico needs to poll its web server while it waits, your Mac
doesn't - and for letting go of every key (release_fn), which runs whenever
a pass ends so a failure can't leave a key held down.

Nothing in here is allowed to raise while a script is running. A bad step
stops that run and gets reported through status()["last_error"] instead,
so the device stays reachable and the webapp can say what went wrong.
"""

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


class ScriptRunner:
    def __init__(self, script, press_fn, sleep_fn, release_fn=None):
        self.script = script
        self.press_fn = press_fn  # press_fn(keycode_name, hold_seconds)
        self.sleep_fn = sleep_fn  # sleep_fn(seconds), should return early if stop_requested becomes True
        self.release_fn = release_fn  # release_fn(), lets go of every held key. Optional.

        self.running = False
        self.stop_requested = False
        self.loop_count = 0
        self.current_step = 0
        self.target_loops = None  # None means "loop forever until stopped"
        self.last_error = None  # Why the last run stopped early, if it did.

    def start(self, times=None):
        self.target_loops = times
        self.loop_count = 0
        self.current_step = 0
        self.running = True
        self.stop_requested = False
        self.last_error = None

    def stop(self):
        self.stop_requested = True

    def finish_current_loop(self):
        """Let the pass currently in progress finish, then stop -- instead
        of cutting it off mid-step the way stop() does. Used before a
        firmware deploy so a step never gets interrupted partway through.
        If a target loop count is already set and would finish sooner,
        this leaves it alone."""
        if not self.running:
            return
        limit = self.loop_count + 1
        if self.target_loops is None or self.target_loops > limit:
            self.target_loops = limit

    def set_script(self, new_script):
        """Replaces the script. Raises ValueError if what came in isn't a
        list of steps at all -- that gets refused at the door rather than
        breaking the run loop later."""
        if not isinstance(new_script, (list, tuple)):
            raise ValueError("a script must be a list of steps")
        self.script = new_script

    def _step_problem(self, step):
        """Returns None if the step can be run, or a plain-language
        explanation of what's wrong with it."""
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
        """How long a step takes. A step that doesn't make sense counts as
        zero rather than raising, so /status keeps answering even when the
        loaded script is broken."""
        if self._step_problem(step) is not None:
            return 0
        if step[0] == "press":
            return step[2]
        if step[0] == "wait":
            return step[1]
        return 0

    def _loop_duration(self):
        return sum(self._step_duration(step) for step in self.script)

    def _estimated_seconds_remaining(self):
        # Only meaningful once running with a target loop count. An
        # indefinite run (no "times" given) has no estimate.
        if not self.running or self.target_loops is None:
            return None
        remaining_in_this_pass = sum(
            self._step_duration(step) for step in self.script[self.current_step :]
        )
        remaining_full_passes = max(self.target_loops - self.loop_count - 1, 0)
        return remaining_in_this_pass + remaining_full_passes * self._loop_duration()

    def status(self):
        return {
            "running": self.running,
            "loop_count": self.loop_count,
            "target_loops": self.target_loops,
            "current_step": self.current_step,
            "total_steps": len(self.script),
            "estimated_seconds_remaining": self._estimated_seconds_remaining(),
            "last_error": self.last_error,
        }

    def _release_keys(self):
        """Let go of everything at the end of a pass, so a run that stopped
        partway through can't leave a key held down. Returns None, or the
        reason releasing failed."""
        if self.release_fn is None:
            return None
        try:
            self.release_fn()
        except Exception as e:
            return "couldn't release the keys: {}: {}".format(type(e).__name__, e)
        return None

    def run_one_pass(self):
        """Runs the script once, start to finish (or until stopped).

        Call this repeatedly from your main loop whenever self.running is
        True. It updates loop_count, current_step, and running/stop_requested
        as it goes, and stops itself once target_loops is reached.

        A step that fails ends the run and records why in last_error. It
        never raises, so the caller's loop always keeps going.
        """
        failed = False

        for i, step in enumerate(self.script):
            if self.stop_requested:
                break
            self.current_step = i

            problem = self._step_problem(step)
            if problem is None:
                try:
                    if step[0] == "press":
                        self.press_fn(step[1], step[2])
                    else:
                        self.sleep_fn(step[1])
                except Exception as e:
                    problem = "{}: {}".format(type(e).__name__, e)

            if problem is not None:
                self.last_error = "stopped at step {} of {}: {}".format(
                    i + 1, len(self.script), problem
                )
                failed = True
                break

            if self.stop_requested:
                break

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
