"""Tests for turning a script and the scripts it runs into a program for
the device (issue #3).

Run them with:
    python3 -m unittest discover -s dev

These exercise the webapp's compiler without a webapp, a device or Docker:
each test gets its own empty data directory, writes a few scripts into it,
and compiles them.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class CompileTestCase(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="keybot-test-")
        os.environ["KEYBOT_DATA_DIR"] = self.data_dir
        # Imported after KEYBOT_DATA_DIR is set, and reloaded each time,
        # because storage reads the directory when it is imported.
        import importlib

        from webapp.app import storage as storage_module

        self.storage = importlib.reload(storage_module)
        from webapp.app import flatten as flatten_module

        self.flatten = importlib.reload(flatten_module)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)
        os.environ.pop("KEYBOT_DATA_DIR", None)

    def save(self, name, steps):
        return self.storage.save_script(None, name, "", steps)["id"]


class CompileTest(CompileTestCase):
    def test_a_run_step_becomes_one_repeat_step(self):
        inner = self.save("Gathering", [["press", "A", 0.1], ["wait", 2]])
        outer = self.save("Overnight", [["run", inner, 1000]])

        program = self.flatten.compile_script(outer)

        self.assertEqual(
            program, [["repeat", 1000, [["press", "A", 0.1], ["wait", 2]]]]
        )
        # A thousand iterations, three steps sent to the board.
        self.assertEqual(self.flatten.count_steps(program), 3)

    def test_rosys_script_is_three_parts_and_stays_small(self):
        a = self.save("Warm up", [["press", "A", 0.1]])
        b = self.save("Gathering", [["press", "B", 0.1], ["wait", 6]])
        c = self.save("Cash out", [["press", "C", 0.1]])
        job = self.save(
            "Overnight farm", [["run", a, 1], ["run", b, 1000], ["run", c, 1]]
        )

        program = self.flatten.compile_script(job)

        self.assertEqual(len(program), 3)
        self.assertTrue(all(step[0] == "repeat" for step in program))
        self.assertEqual(program[1][1], 1000)
        # Three repeats wrapping four steps in all: seven, not 6002.
        self.assertEqual(self.flatten.count_steps(program), 7)

    def test_running_a_script_once_still_becomes_a_repeat(self):
        # So that part numbers mean the same thing whatever the count is.
        inner = self.save("Warm up", [["press", "A", 0.1]])
        outer = self.save("Job", [["run", inner, 1]])
        self.assertEqual(
            self.flatten.compile_script(outer), [["repeat", 1, [["press", "A", 0.1]]]]
        )

    def test_nesting_is_kept_rather_than_multiplied_out(self):
        deepest = self.save("Deepest", [["press", "A", 0.1]])
        middle = self.save("Middle", [["run", deepest, 50]])
        top = self.save("Top", [["run", middle, 40]])

        program = self.flatten.compile_script(top)

        self.assertEqual(program, [["repeat", 40, [["repeat", 50, [["press", "A", 0.1]]]]]])
        self.assertEqual(self.flatten.count_steps(program), 3)

    def test_a_circular_reference_is_still_caught(self):
        first = self.save("First", [])
        second = self.save("Second", [["run", first, 1]])
        self.storage.save_script(first, "First", "", [["run", second, 1]])
        with self.assertRaises(self.flatten.FlattenError) as caught:
            self.flatten.compile_script(first)
        self.assertIn("circular reference", str(caught.exception))

    def test_a_missing_script_is_still_caught(self):
        job = self.save("Job", [["run", "nope", 2]])
        with self.assertRaises(self.flatten.FlattenError) as caught:
            self.flatten.compile_script(job)
        self.assertIn("script not found", str(caught.exception))

    def test_running_a_script_with_no_steps_is_refused(self):
        # The device refuses an empty repeat body, because it would spin
        # through its iterations doing nothing. Say so here, by name.
        empty = self.save("Empty", [])
        job = self.save("Job", [["run", empty, 500]])
        with self.assertRaises(self.flatten.FlattenError) as caught:
            self.flatten.compile_script(job)
        self.assertIn("no steps in it", str(caught.exception))

    def test_a_repeat_count_below_one_is_refused(self):
        inner = self.save("Inner", [["press", "A", 0.1]])
        job = self.save("Job", [["run", inner, 0]])
        with self.assertRaises(self.flatten.FlattenError):
            self.flatten.compile_script(job)


class DurationTest(CompileTestCase):
    def test_a_compiled_program_lasts_as_long_as_the_written_out_one(self):
        inner = self.save("Inner", [["press", "A", 0.25], ["wait", 1.5]])
        job = self.save("Job", [["press", "S", 0.5], ["run", inner, 40]])

        compiled = self.flatten.compile_script(job)
        written_out = self.flatten.flatten_script(job)

        self.assertAlmostEqual(
            sum(self.flatten.step_duration(s) for s in compiled),
            sum(self.flatten.step_duration(s) for s in written_out),
        )

    def test_the_preview_of_a_thousand_repeats_is_the_real_duration(self):
        inner = self.save("Inner", [["wait", 6]])
        job = self.save("Job", [["run", inner, 1000]])

        preview = self.flatten.preview(job)

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["duration_seconds"], 6000)
        self.assertEqual(preview["step_count"], 2)


class PartNamesTest(CompileTestCase):
    def test_each_part_is_named_after_the_script_it_runs(self):
        a = self.save("Warm up", [["press", "A", 0.1]])
        b = self.save("Gathering", [["press", "B", 0.1]])
        job = self.save("Job", [["run", a, 1], ["run", b, 1000]])
        self.assertEqual(self.flatten.part_names(job), ["Warm up", "Gathering"])

    def test_a_part_that_is_a_plain_step_has_no_name(self):
        a = self.save("Warm up", [["press", "A", 0.1]])
        job = self.save("Job", [["press", "X", 0.1], ["run", a, 2]])
        self.assertEqual(self.flatten.part_names(job), [None, "Warm up"])


class LegacyFlattenTest(CompileTestCase):
    """The fallback for a board too old to repeat by itself."""

    def test_it_still_writes_every_step_out(self):
        inner = self.save("Inner", [["press", "A", 0.1], ["wait", 1]])
        job = self.save("Job", [["run", inner, 3]])
        self.assertEqual(len(self.flatten.flatten_script(job)), 6)

    def test_rosys_script_is_refused_with_the_fix_in_the_message(self):
        inner = self.save("Gathering", [["press", "A", 0.1]] * 6)
        job = self.save("Job", [["run", inner, 1000]])
        with self.assertRaises(self.flatten.FlattenError) as caught:
            self.flatten.flatten_script(job)
        message = str(caught.exception)
        self.assertIn("more than the firmware on this Pico can hold", message)
        self.assertIn("Firmware panel", message)


if __name__ == "__main__":
    unittest.main()
