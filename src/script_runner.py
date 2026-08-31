"""Shared logic for running a scripted sequence of key-press actions.

Both code.py (running on the Pico) and dev/server.py (running on your Mac)
import this file and use it the same way. The only thing that differs
between the two is how a single key press actually happens: on the Pico it
presses a real key, and on your Mac it does nothing but wait the same
amount of time. That's why key presses are passed in as a function
(press_fn) instead of being hardcoded here, and the same goes for waiting
(sleep_fn) - the Pico needs to poll its web server while it waits, your Mac
doesn't.
"""

DEFAULT_SCRIPT = [
    ["press", "ENTER", 0.1],
    ["wait", 5.5],
    ["press", "ENTER", 0.1],
    ["wait", 1.5],
    ["press", "ONE", 0.1],
    ["wait", 3],
    ["press", "TWO", 0.1],
    ["wait", 3],
]


class ScriptRunner:
    def __init__(self, script, press_fn, sleep_fn):
        self.script = script
        self.press_fn = press_fn  # press_fn(keycode_name, hold_seconds)
        self.sleep_fn = sleep_fn  # sleep_fn(seconds), should return early if stop_requested becomes True

        self.running = False
        self.stop_requested = False
        self.loop_count = 0
        self.current_step = 0
        self.target_loops = None  # None means "loop forever until stopped"

    def start(self, times=None):
        self.target_loops = times
        self.loop_count = 0
        self.current_step = 0
        self.running = True
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def set_script(self, new_script):
        self.script = new_script

    def _step_duration(self, step):
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
        }

    def run_one_pass(self):
        """Runs the script once, start to finish (or until stopped).

        Call this repeatedly from your main loop whenever self.running is
        True. It updates loop_count, current_step, and running/stop_requested
        as it goes, and stops itself once target_loops is reached.
        """
        for i, step in enumerate(self.script):
            if self.stop_requested:
                break
            self.current_step = i
            if step[0] == "press":
                self.press_fn(step[1], step[2])
            elif step[0] == "wait":
                self.sleep_fn(step[1])
                if self.stop_requested:
                    break

        if self.stop_requested:
            self.running = False
            self.stop_requested = False
        else:
            self.loop_count += 1
            if self.target_loops is not None and self.loop_count >= self.target_loops:
                self.running = False
