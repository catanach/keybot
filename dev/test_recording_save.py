"""Tests for saving a recording into a script (issue #19).

Run them with:
    python3 -m unittest discover -s dev

This writes to Rosy's real scripts when it runs for real, so the awkward
halves are checked here rather than found later: a second write that fails
after the first one worked, a script that changed in another tab, a script
that has been deleted, and a join that would not fit on the board.

No webapp, no Docker and no device: each test gets its own empty data
directory and calls the saving code directly.
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


class RecordingSaveTestCase(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="keybot-test-")
        os.environ["KEYBOT_DATA_DIR"] = self.data_dir
        # In the container the firmware source is mounted at /firmware_src.
        # Here it is the repo's own src/, which is the same files.
        os.environ["KEYBOT_FIRMWARE_DIR"] = os.path.join(REPO, "src")

        from webapp.app import firmware as firmware_module

        self.firmware = importlib.reload(firmware_module)
        from webapp.app import storage as storage_module

        self.storage = importlib.reload(storage_module)
        from webapp.app import flatten as flatten_module

        self.flatten = importlib.reload(flatten_module)
        from webapp.app import recordings as recordings_module

        self.recordings = importlib.reload(recordings_module)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)
        os.environ.pop("KEYBOT_DATA_DIR", None)
        os.environ.pop("KEYBOT_FIRMWARE_DIR", None)

    def save(self, name, steps):
        return self.storage.save_script(None, name, "", steps)

    def recorded(self, count=2):
        return [["press", "A", 0.1], ["wait", 0.5]][:count]

    def names(self):
        return [s["name"] for s in self.storage.list_scripts()]


class SaveOnItsOwnTest(RecordingSaveTestCase):
    def test_a_recording_with_no_target_becomes_one_new_script(self):
        result = self.recordings.save_recording(self.recorded(), "Recording 1")
        self.assertIsNone(result["target"])
        self.assertEqual(result["warning"], "")
        saved = self.storage.get_script(result["script"]["id"])
        self.assertEqual(saved["name"], "Recording 1")
        self.assertEqual(saved["steps"], self.recorded())

    def test_the_description_is_left_empty(self):
        result = self.recordings.save_recording(self.recorded(), "Recording 1")
        self.assertEqual(result["script"]["description"], "")

    def test_nothing_is_saved_for_a_recording_with_no_keys(self):
        with self.assertRaises(self.recordings.SaveError):
            self.recordings.save_recording([], "Recording 1")
        self.assertEqual(self.names(), [])


class NextNameTest(RecordingSaveTestCase):
    def test_the_first_recording_is_recording_1(self):
        self.assertEqual(self.recordings.next_recording_name([]), "Recording 1")

    def test_the_gap_left_by_a_deleted_recording_is_used_next(self):
        names = ["Recording 1", "Recording 3", "Overnight farm"]
        self.assertEqual(self.recordings.next_recording_name(names), "Recording 2")

    def test_names_that_only_look_like_recordings_are_left_alone(self):
        names = ["Recording 1", "Recording 2b", "Recording two", "Recording"]
        self.assertEqual(self.recordings.next_recording_name(names), "Recording 2")

    def test_it_counts_what_exists_rather_than_how_many_there_are(self):
        # Two scripts, but 1 and 2 are taken, so a counter of "how many"
        # would offer a name that is already in use.
        names = ["Recording 1", "Recording 2"]
        self.assertEqual(self.recordings.next_recording_name(names), "Recording 3")


class JoinOntoAnotherScriptTest(RecordingSaveTestCase):
    def test_the_target_gets_a_gap_and_a_run_step_not_the_raw_keys(self):
        target = self.save("Overnight farm", [["press", "ENTER", 0.1]])
        result = self.recordings.save_recording(
            self.recorded(), "Recording 1", target_id=target["id"],
            target_name="Overnight farm", target_rev=target["rev"],
        )
        recording_id = result["script"]["id"]
        self.assertEqual(
            self.storage.get_script(target["id"])["steps"],
            [["press", "ENTER", 0.1], ["wait", 1.0], ["run", recording_id, 1]],
        )
        # And the recording is a script in its own right, runnable on its own.
        self.assertEqual(self.storage.get_script(recording_id)["steps"], self.recorded())

    def test_the_targets_rev_goes_up_by_one(self):
        target = self.save("Overnight farm", [["press", "ENTER", 0.1]])
        self.recordings.save_recording(
            self.recorded(), "Recording 1", target_id=target["id"],
            target_rev=target["rev"],
        )
        self.assertEqual(self.storage.get_script(target["id"])["rev"], target["rev"] + 1)

    def test_without_the_run_step_the_raw_steps_are_appended_instead(self):
        target = self.save("Overnight farm", [["press", "ENTER", 0.1]])
        result = self.recordings.save_recording(
            self.recorded(), "Recording 1", target_id=target["id"],
            target_rev=target["rev"], add_run_step=False,
        )
        self.assertIsNone(result["script"])
        self.assertEqual(
            self.storage.get_script(target["id"])["steps"],
            [["press", "ENTER", 0.1], ["wait", 1.0]] + self.recorded(),
        )
        self.assertEqual(self.names(), ["Overnight farm"])

    def test_the_joined_script_still_compiles_for_the_device(self):
        target = self.save("Overnight farm", [["press", "ENTER", 0.1]])
        self.recordings.save_recording(
            self.recorded(), "Recording 1", target_id=target["id"],
            target_rev=target["rev"],
        )
        program = self.flatten.compile_script(target["id"])
        self.assertEqual(
            program,
            [["press", "ENTER", 0.1], ["wait", 1.0],
             ["repeat", 1, [["press", "A", 0.1], ["wait", 0.5]]]],
        )


class SecondWriteFailsTest(RecordingSaveTestCase):
    def test_the_recording_survives_a_failure_to_add_the_run_step(self):
        target = self.save("Gathering", [["press", "ENTER", 0.1]])
        real_save = self.storage.save_script
        calls = []

        def save_then_fail(*args, **kwargs):
            calls.append(args)
            if len(calls) > 1:
                raise OSError("disk full")
            return real_save(*args, **kwargs)

        self.storage.save_script = save_then_fail
        try:
            result = self.recordings.save_recording(
                self.recorded(), "Recording 3", target_id=target["id"],
                target_name="Gathering", target_rev=target["rev"],
            )
        finally:
            self.storage.save_script = real_save

        self.assertEqual(
            result["warning"],
            "Saved as “Recording 3”, but couldn't add the Run step to "
            "“Gathering”. The recording is safe, add the step yourself.",
        )
        self.assertIsNone(result["target"])
        # The recording is on disk, and nothing was deleted to make the two
        # writes look like one.
        kept = self.storage.get_script(result["script"]["id"])
        self.assertEqual(kept["steps"], self.recorded())
        self.assertEqual(kept["name"], "Recording 3")
        # The target is exactly as it was.
        self.assertEqual(
            self.storage.get_script(target["id"])["steps"], [["press", "ENTER", 0.1]]
        )


class ChangedInAnotherTabTest(RecordingSaveTestCase):
    def test_a_stale_rev_is_refused_and_writes_nothing(self):
        target = self.save("Gathering", [["press", "ENTER", 0.1]])
        # Someone else saves it in between.
        self.storage.save_script(
            target["id"], "Gathering", "", [["press", "B", 0.1]],
            expected_rev=target["rev"],
        )

        with self.assertRaises(self.recordings.SaveError) as caught:
            self.recordings.save_recording(
                self.recorded(), "Recording 1", target_id=target["id"],
                target_name="Gathering", target_rev=target["rev"],
            )

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            caught.exception.message,
            "“Gathering” changed in another tab, reload before saving",
        )
        self.assertIsNone(caught.exception.script)
        # Nothing at all was written: no recording, and the other tab's
        # steps are still there.
        self.assertEqual(self.names(), ["Gathering"])
        self.assertEqual(
            self.storage.get_script(target["id"])["steps"], [["press", "B", 0.1]]
        )

    def test_the_editors_own_save_is_refused_on_a_stale_rev_too(self):
        script = self.save("Gathering", [["press", "ENTER", 0.1]])
        self.storage.save_script(
            script["id"], "Gathering", "", [["press", "B", 0.1]],
            expected_rev=script["rev"],
        )
        with self.assertRaises(self.storage.RevMismatch):
            self.storage.save_script(
                script["id"], "Gathering", "", [["press", "C", 0.1]],
                expected_rev=script["rev"],
            )
        self.assertEqual(
            self.storage.get_script(script["id"])["steps"], [["press", "B", 0.1]]
        )


class DeletedTargetTest(RecordingSaveTestCase):
    def test_the_recording_is_saved_on_its_own_and_the_target_is_a_404(self):
        target = self.save("Gathering", [["press", "ENTER", 0.1]])
        self.storage.delete_script(target["id"])

        with self.assertRaises(self.recordings.SaveError) as caught:
            self.recordings.save_recording(
                self.recorded(), "Recording 2", target_id=target["id"],
                target_name="Gathering", target_rev=target["rev"],
            )

        self.assertEqual(caught.exception.status, 404)
        self.assertIn("Saved as “Recording 2” on its own", caught.exception.message)
        self.assertIn("“Gathering” no longer exists", caught.exception.message)
        kept = self.storage.get_script(caught.exception.script["id"])
        self.assertEqual(kept["steps"], self.recorded())
        self.assertEqual(self.names(), ["Recording 2"])

    def test_appending_raw_steps_to_a_deleted_script_saves_nothing(self):
        target = self.save("Gathering", [["press", "ENTER", 0.1]])
        self.storage.delete_script(target["id"])
        with self.assertRaises(self.recordings.SaveError) as caught:
            self.recordings.save_recording(
                self.recorded(), "Recording 2", target_id=target["id"],
                target_name="Gathering", target_rev=target["rev"],
                add_run_step=False,
            )
        self.assertEqual(caught.exception.status, 404)
        self.assertIsNone(caught.exception.script)
        self.assertEqual(self.names(), [])


class NodeBudgetTest(RecordingSaveTestCase):
    """Adding a Run step can push a script past what the board can hold.
    Finding that out at run time means finding it out at 3am."""

    def limit(self):
        return self.flatten.max_program_nodes()

    def test_the_limit_is_the_one_the_firmware_was_measured_at(self):
        self.assertEqual(self.limit(), 500)

    def test_a_join_that_just_fits_is_saved_and_compiles_under_the_limit(self):
        # The join costs three: the gap, the run step, and the one recorded
        # key inside it.
        target = self.save("Gathering", [["press", "A", 0.1]] * (self.limit() - 3))
        result = self.recordings.save_recording(
            [["press", "A", 0.1]], "Recording 1", target_id=target["id"],
            target_rev=target["rev"],
        )
        self.assertEqual(result["warning"], "")
        program = self.flatten.compile_script(target["id"])
        self.assertEqual(self.flatten.count_steps(program), self.limit())

    def test_one_step_too_many_is_refused_before_anything_is_written(self):
        target = self.save("Gathering", [["press", "A", 0.1]] * (self.limit() - 2))
        with self.assertRaises(self.recordings.SaveError) as caught:
            self.recordings.save_recording(
                [["press", "A", 0.1]], "Recording 1", target_id=target["id"],
                target_rev=target["rev"],
            )
        message = caught.exception.message
        self.assertIn(str(self.limit() + 1), message)
        self.assertIn(str(self.limit()), message)
        self.assertIn("Nothing was saved", message)
        # No recording, and the target is untouched.
        self.assertEqual(self.names(), ["Gathering"])
        self.assertEqual(self.storage.get_script(target["id"])["rev"], target["rev"])

    def test_the_nested_steps_of_the_target_are_counted_too(self):
        inner = self.save("Inner", [["press", "A", 0.1]] * 10)
        target = self.save("Gathering", [["run", inner["id"], 50]])
        # One repeat plus its ten steps, plus the gap, the run step and the
        # one recorded key.
        self.assertEqual(
            self.recordings.nodes_after_adding(
                self.storage.get_script(target["id"]), [["press", "A", 0.1]], True
            ),
            11 + 3,
        )


if __name__ == "__main__":
    unittest.main()
