"""Tests for nested scripts with repeat counts (issue #3).

Run them with:
    python3 -m unittest discover -s dev

The point of the feature is that "run B a thousand times" is one step the
board holds, not a thousand steps it can't. These tests are written so that
they would be unbearably slow -- or run out of memory -- if it were ever
expanded again: a thousand iterations run here with a no-op sleep, in
milliseconds. None of this needs the hardware.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from script_runner import (  # noqa: E402
    MAX_DEPTH,
    MAX_PROGRAM_NODES,
    PROGRAM_FORMAT,
    ScriptRunner,
    program_for_saving,
    program_from_saved,
)


class Recorder:
    """Stands in for the keyboard: records presses, waits nothing at all."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.pressed = []
        self.waited = []
        self.releases = 0

    def press(self, keycode_name, hold):
        if keycode_name == self.fail_on:
            raise ValueError("there is no key called '{}'".format(keycode_name))
        self.pressed.append(keycode_name)

    def sleep(self, seconds):
        self.waited.append(seconds)

    def release_all(self):
        self.releases += 1


def make_runner(program, fail_on=None):
    recorder = Recorder(fail_on)
    runner = ScriptRunner(
        program, recorder.press, recorder.sleep, recorder.release_all
    )
    return runner, recorder


class RunningRepeatsTest(unittest.TestCase):
    def test_a_repeat_runs_its_steps_that_many_times(self):
        runner, recorder = make_runner([["repeat", 3, [["press", "A", 0.1]]]])
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(recorder.pressed, ["A", "A", "A"])
        self.assertIsNone(runner.status()["last_error"])

    def test_a_thousand_repeats_run_without_being_written_out(self):
        program = [
            ["press", "START", 0.1],
            ["repeat", 1000, [["press", "B", 0.1], ["wait", 2]]],
            ["press", "END", 0.1],
        ]
        runner, recorder = make_runner(program)
        runner.start(1)
        runner.run_one_pass()

        self.assertEqual(len(recorder.pressed), 1002)
        self.assertEqual(recorder.pressed[0], "START")
        self.assertEqual(recorder.pressed[-1], "END")
        self.assertEqual(len(recorder.waited), 1000)
        # The program itself never grew: three steps went in, three remain.
        self.assertEqual(len(runner.script), 3)
        self.assertEqual(runner.loop_count, 1)
        self.assertFalse(runner.running)

    def test_repeats_inside_repeats_run_in_the_right_order(self):
        program = [
            ["repeat", 2, [["press", "A", 0.1], ["repeat", 3, [["press", "B", 0.1]]]]]
        ]
        runner, recorder = make_runner(program)
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(recorder.pressed, list("ABBBABBB"))

    def test_a_stop_part_way_through_a_long_repeat_is_noticed(self):
        program = [["repeat", 1000, [["press", "A", 0.1]]]]
        runner, recorder = make_runner(program)

        def press_and_maybe_stop(name, hold):
            recorder.pressed.append(name)
            if len(recorder.pressed) == 5:
                runner.stop()

        runner.press_fn = press_and_maybe_stop
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(len(recorder.pressed), 5)
        self.assertFalse(runner.running)
        self.assertEqual(recorder.releases, 1)

    def test_the_keys_are_released_once_per_pass_not_once_per_iteration(self):
        runner, recorder = make_runner([["repeat", 100, [["press", "A", 0.1]]]])
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(recorder.releases, 1)


class ValidationTest(unittest.TestCase):
    """Refused when the program arrives, so the run loop never has to."""

    def test_an_empty_repeat_body_is_refused(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        with self.assertRaises(ValueError) as caught:
            runner.set_script([["repeat", 1000000, []]])
        self.assertIn("at least one step to repeat", str(caught.exception))

    def test_nesting_deeper_than_the_limit_is_refused(self):
        program = [["press", "A", 0.1]]
        for _ in range(MAX_DEPTH + 1):
            program = [["repeat", 2, program]]
        runner, _ = make_runner([["press", "A", 0.1]])
        with self.assertRaises(ValueError) as caught:
            runner.set_script(program)
        self.assertIn("nested more than {} deep".format(MAX_DEPTH), str(caught.exception))

    def test_nesting_up_to_the_limit_is_allowed(self):
        program = [["press", "A", 0.1]]
        for _ in range(MAX_DEPTH - 1):
            program = [["repeat", 2, program]]
        runner, _ = make_runner([["press", "A", 0.1]])
        runner.set_script(program)  # must not raise
        self.assertEqual(runner.script, program)

    def test_a_repeat_count_below_one_is_refused(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        with self.assertRaises(ValueError):
            runner.set_script([["repeat", 0, [["press", "A", 0.1]]]])

    def test_a_bad_step_inside_a_repeat_is_refused_at_the_door(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        with self.assertRaises(ValueError) as caught:
            runner.set_script([["repeat", 2, [["wait"]]]])
        self.assertIn("number of seconds", str(caught.exception))

    def test_a_program_with_more_steps_than_the_board_holds_is_refused(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        too_many = [["press", "A", 0.1]] * (MAX_PROGRAM_NODES + 1)
        with self.assertRaises(ValueError) as caught:
            runner.set_script(too_many)
        self.assertIn("this board can hold", str(caught.exception))

    def test_a_repeat_count_does_not_count_towards_the_step_limit(self):
        # The whole point: a million iterations of two steps is three steps.
        runner, _ = make_runner([["press", "A", 0.1]])
        runner.set_script(
            [["repeat", 1000000, [["press", "A", 0.1], ["wait", 1]]]]
        )  # must not raise
        self.assertEqual(len(runner.script), 1)

    def test_a_program_cannot_be_swapped_out_from_under_a_run(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        runner.start(1)
        with self.assertRaises(ValueError) as caught:
            runner.set_script([["press", "B", 0.1]])
        self.assertIn("stop it before", str(caught.exception))
        self.assertEqual(runner.script, [["press", "A", 0.1]])


class DurationTest(unittest.TestCase):
    def test_a_repeat_is_worth_the_same_as_the_same_steps_written_out(self):
        body = [["press", "A", 0.25], ["wait", 1.5]]
        nested = [["press", "S", 0.5], ["repeat", 40, body], ["wait", 2]]
        flat = [["press", "S", 0.5]] + body * 40 + [["wait", 2]]

        nested_runner, _ = make_runner(nested)
        flat_runner, _ = make_runner(flat)
        nested_runner.start(3)
        flat_runner.start(3)

        self.assertAlmostEqual(
            nested_runner.status()["estimated_seconds_remaining"],
            flat_runner.status()["estimated_seconds_remaining"],
        )

    def test_the_estimate_falls_as_a_long_repeat_works_through_it(self):
        program = [["repeat", 1000, [["wait", 6]]]]
        runner, _ = make_runner(program)
        seen = []

        def watch(seconds):
            seen.append(runner.status()["estimated_seconds_remaining"])
            if len(seen) == 3:
                runner.stop()

        runner.sleep_fn = watch
        runner.start(1)
        runner.run_one_pass()

        self.assertEqual(seen, [6000, 5994, 5988])

    def test_an_estimate_is_still_given_deep_inside_nested_repeats(self):
        program = [["repeat", 10, [["repeat", 10, [["wait", 1]]]]]]
        runner, _ = make_runner(program)
        answers = []

        def watch(seconds):
            answers.append(runner.status()["estimated_seconds_remaining"])
            if len(answers) == 2:
                runner.stop()

        runner.sleep_fn = watch
        runner.start(1)
        runner.run_one_pass()
        self.assertEqual(answers, [100, 99])


class PositionTest(unittest.TestCase):
    """What /status says about where a run has got to. Without this, "A,
    then B a thousand times, then C" reads as loop 0 of 1 for four hours."""

    def _positions(self, program, stop_after):
        runner, recorder = make_runner(program)
        seen = []

        def watch(name, hold):
            recorder.pressed.append(name)
            seen.append(runner.status())
            if len(seen) == stop_after:
                runner.stop()

        runner.press_fn = watch
        runner.start(1)
        runner.run_one_pass()
        return seen

    def test_it_says_which_part_and_which_iteration(self):
        program = [
            ["repeat", 1, [["press", "A", 0.1]]],
            ["repeat", 1000, [["press", "B", 0.1], ["press", "C", 0.1]]],
            ["repeat", 1, [["press", "D", 0.1]]],
        ]
        seen = self._positions(program, stop_after=6)

        first = seen[0]["position"]
        self.assertEqual(first["part"], 1)
        self.assertEqual(first["parts"], 3)
        self.assertEqual(first["iteration"], 1)
        self.assertEqual(first["iterations"], 1)

        # Second press of the second part: part 2, first time round.
        second = seen[1]["position"]
        self.assertEqual(second["part"], 2)
        self.assertEqual(second["iteration"], 1)
        self.assertEqual(second["iterations"], 1000)

        # Fourth press overall is the second iteration of part 2.
        fourth = seen[3]["position"]
        self.assertEqual(fourth["part"], 2)
        self.assertEqual(fourth["iteration"], 2)

    def test_step_numbers_are_the_ones_inside_the_repeat(self):
        program = [["repeat", 50, [["press", "A", 0.1], ["press", "B", 0.1]]]]
        seen = self._positions(program, stop_after=2)
        self.assertEqual(seen[0]["current_step"], 0)
        self.assertEqual(seen[0]["total_steps"], 2)
        self.assertEqual(seen[1]["current_step"], 1)

    def test_depth_is_reported(self):
        program = [["repeat", 2, [["repeat", 2, [["press", "A", 0.1]]]]]]
        seen = self._positions(program, stop_after=1)
        self.assertEqual(seen[0]["depth"], 3)

    def test_a_flat_script_has_no_iteration_to_report(self):
        seen = self._positions([["press", "A", 0.1]], stop_after=1)
        self.assertEqual(seen[0]["position"]["part"], 1)
        self.assertIsNone(seen[0]["position"]["iteration"])

    def test_nothing_is_running_so_there_is_no_position(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        self.assertIsNone(runner.status()["position"])
        self.assertEqual(runner.status()["depth"], 0)


class FailureInsideARepeatTest(unittest.TestCase):
    def test_a_failure_deep_in_a_repeat_says_where_it_was(self):
        program = [
            ["repeat", 1, [["press", "A", 0.1]]],
            ["repeat", 1000, [["wait", 0.1], ["press", "UP", 0.1]]],
        ]
        runner, recorder = make_runner(program, fail_on="UP")
        runner.start(1)
        runner.run_one_pass()

        error = runner.status()["last_error"]
        self.assertIn("part 2", error)
        self.assertIn("repeat 1 of 1000", error)
        self.assertIn("step 2", error)
        self.assertIn("there is no key called 'UP'", error)
        self.assertFalse(runner.running)
        self.assertEqual(recorder.releases, 1)

    def test_a_flat_script_still_reports_the_plain_step_number(self):
        runner, _ = make_runner([["press", "A", 0.1], ["press", "UP", 0.1]], fail_on="UP")
        runner.start(1)
        runner.run_one_pass()
        self.assertIn("stopped at step 2 of 2", runner.status()["last_error"])


class SavedProgramTest(unittest.TestCase):
    """script.json carries the format it was written in, so firmware that
    can't read it falls back instead of half-running it."""

    def test_what_is_saved_says_which_format_it_is(self):
        saved = program_for_saving([["press", "A", 0.1]])
        self.assertEqual(saved["v"], PROGRAM_FORMAT)
        self.assertEqual(saved["steps"], [["press", "A", 0.1]])

    def test_a_saved_program_reads_back_unchanged(self):
        program = [["repeat", 5, [["press", "A", 0.1]]]]
        self.assertEqual(program_from_saved(program_for_saving(program)), program)

    def test_the_plain_list_older_firmware_wrote_is_still_read(self):
        self.assertEqual(program_from_saved([["press", "A", 0.1]]), [["press", "A", 0.1]])

    def test_a_file_from_different_firmware_is_refused(self):
        with self.assertRaises(ValueError):
            program_from_saved({"v": PROGRAM_FORMAT + 1, "steps": []})


class FeatureTest(unittest.TestCase):
    def test_the_firmware_says_it_can_repeat(self):
        runner, _ = make_runner([["press", "A", 0.1]])
        self.assertIn("repeat", runner.status()["features"])


if __name__ == "__main__":
    unittest.main()
