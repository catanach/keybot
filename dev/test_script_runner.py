"""Tests for the script-running logic both the Pico and the dev server use.

Run them with:
    python3 -m unittest discover -s dev

Most of these cover issue #2: a step that fails must stop that run, say
why, let go of the keys, and leave everything else working. Nothing here
needs the hardware.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from script_runner import ScriptRunner  # noqa: E402


class FakeKeyboard:
    """Stands in for the Pico's keyboard: records what was pressed, and
    can be told to fail on a given key the way a bad key name does."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.pressed = []
        self.releases = 0

    def press(self, keycode_name, hold):
        if keycode_name == self.fail_on:
            raise ValueError("there is no key called '{}'".format(keycode_name))
        self.pressed.append(keycode_name)

    def release_all(self):
        self.releases += 1


def make_runner(script, fail_on=None):
    keyboard = FakeKeyboard(fail_on)
    runner = ScriptRunner(script, keyboard.press, lambda seconds: None, keyboard.release_all)
    return runner, keyboard


class GoodScriptTest(unittest.TestCase):
    def test_a_normal_run_finishes_and_counts_its_passes(self):
        runner, keyboard = make_runner([["press", "ENTER", 0.1], ["wait", 0.1]])
        runner.start(2)
        runner.run_one_pass()
        runner.run_one_pass()
        self.assertFalse(runner.running)
        self.assertEqual(runner.loop_count, 2)
        self.assertIsNone(runner.status()["last_error"])
        self.assertEqual(keyboard.pressed, ["ENTER", "ENTER"])

    def test_keys_are_released_at_the_end_of_every_pass(self):
        runner, keyboard = make_runner([["press", "ENTER", 0.1]])
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(keyboard.releases, 1)


class FailingStepTest(unittest.TestCase):
    """Each of these used to end the run loop outright, which left the
    board silent until it was unplugged."""

    def assert_recovered(self, runner, keyboard, expected_text):
        self.assertFalse(runner.running, "the run should have stopped")
        self.assertFalse(runner.stop_requested)
        status = runner.status()
        self.assertIsNotNone(status["last_error"], "the failure was never reported")
        self.assertIn(expected_text, status["last_error"])
        self.assertEqual(keyboard.releases, 1, "the keys were left held down")

    def test_a_key_name_that_does_not_exist(self):
        runner, keyboard = make_runner([["press", "UP", 0.1]], fail_on="UP")
        runner.start(1)
        runner.run_one_pass()  # must not raise
        self.assert_recovered(runner, keyboard, "there is no key called 'UP'")

    def test_a_wait_step_with_no_duration(self):
        runner, keyboard = make_runner([["press", "ENTER", 0.1], ["wait"]])
        runner.start(1)
        runner.run_one_pass()
        self.assert_recovered(runner, keyboard, "step 2 of 2")

    def test_a_step_type_the_device_does_not_know(self):
        runner, keyboard = make_runner([["hold", "ENTER", 0.1]])
        runner.start(1)
        runner.run_one_pass()
        self.assert_recovered(runner, keyboard, "unknown step type 'hold'")

    def test_a_press_step_with_a_hold_time_that_is_not_a_number(self):
        runner, keyboard = make_runner([["press", "ENTER", "soon"]])
        runner.start(1)
        runner.run_one_pass()
        self.assert_recovered(runner, keyboard, "hold time")

    def test_a_step_that_is_not_a_list_at_all(self):
        runner, keyboard = make_runner(["press ENTER"])
        runner.start(1)
        runner.run_one_pass()
        self.assert_recovered(runner, keyboard, "expected a step")

    def test_a_new_run_starts_clean_after_a_failure(self):
        runner, keyboard = make_runner([["press", "UP", 0.1]], fail_on="UP")
        runner.start(1)
        runner.run_one_pass()
        runner.script = [["press", "ENTER", 0.1]]
        runner.start(1)
        self.assertIsNone(runner.status()["last_error"])
        runner.run_one_pass()
        self.assertEqual(runner.loop_count, 1)
        self.assertIsNone(runner.status()["last_error"])

    def test_failing_to_release_the_keys_is_reported_too(self):
        def explode():
            raise RuntimeError("USB went away")

        runner, _ = make_runner([["press", "ENTER", 0.1]])
        runner.release_fn = explode
        runner.start(1)
        runner.run_one_pass()
        self.assertFalse(runner.running)
        self.assertIn("couldn't release the keys", runner.status()["last_error"])


class StatusStillAnswersTest(unittest.TestCase):
    """/status has to keep working even when the loaded script is broken,
    or the webapp can't tell you anything about what went wrong."""

    def test_status_survives_a_malformed_script(self):
        runner, _ = make_runner([["press", "ENTER", 0.1], ["wait"], "nonsense"])
        runner.start(3)
        status = runner.status()
        self.assertEqual(status["total_steps"], 3)
        self.assertIsNotNone(status["estimated_seconds_remaining"])


class SetScriptTest(unittest.TestCase):
    def test_a_body_that_is_not_a_list_is_refused(self):
        runner, _ = make_runner([["press", "ENTER", 0.1]])
        with self.assertRaises(ValueError):
            runner.set_script({"steps": []})
        self.assertEqual(runner.script, [["press", "ENTER", 0.1]])


class StopTest(unittest.TestCase):
    def test_stopping_mid_run_releases_the_keys(self):
        runner, keyboard = make_runner([["press", "ENTER", 0.1], ["wait", 5]])
        runner.sleep_fn = lambda seconds: runner.stop()
        runner.start()
        runner.run_one_pass()
        self.assertFalse(runner.running)
        self.assertEqual(keyboard.releases, 1)
        self.assertIsNone(runner.status()["last_error"])


if __name__ == "__main__":
    unittest.main()


class YieldsBetweenSteps(unittest.TestCase):
    """Issue #16. A run of "press" steps never called sleep_fn, so on the
    board the HTTP server was only served once per pass. A recording typed
    at speed is exactly that shape, so Stop timed out and the Pico looked
    unreachable. The runner now yields before every step."""

    def _runner(self, script):
        self.ticks = 0
        self.pressed = []

        def press_fn(name, hold):
            self.pressed.append(name)

        def tick_fn():
            self.ticks += 1

        return ScriptRunner(script, press_fn, lambda s: None, None, tick_fn)

    def test_a_run_of_presses_yields_once_per_step(self):
        script = [["press", "A", 0.1]] * 20
        runner = self._runner(script)
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(self.ticks, 20)
        self.assertEqual(len(self.pressed), 20)

    def test_a_stop_arriving_during_a_press_run_is_noticed_next_step(self):
        script = [["press", "A", 0.1]] * 20
        runner = self._runner(script)

        # Stand in for the stop request arriving while the server is served.
        original = runner.tick_fn

        def tick_and_stop():
            original()
            if self.ticks == 5:
                runner.stop()

        runner.tick_fn = tick_and_stop
        runner.start(1)
        runner.run_one_pass()

        # It stopped promptly rather than running all twenty.
        self.assertEqual(len(self.pressed), 4)
        self.assertFalse(runner.running)

    def test_a_failure_while_yielding_does_not_kill_the_run(self):
        script = [["press", "A", 0.1], ["press", "B", 0.1]]
        runner = self._runner(script)

        def angry_tick():
            raise OSError("connection reset")

        runner.tick_fn = angry_tick
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(self.pressed, ["A", "B"])
        self.assertIsNone(runner.last_error)
