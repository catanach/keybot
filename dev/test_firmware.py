"""Tests for taking the comments out of the firmware before it is sent.

Run them with:
    python3 -m unittest discover -s dev

The board has to hold a whole file in memory to receive it, and it was
measured failing at around 18.9KB and succeeding at around 12.6KB. So the
repo keeps its explanations and the board gets the small version. That is
only safe if the small version is the same program: these check that it
still parses, that nothing moved to a different line, and that stripping an
already-stripped file changes nothing.
"""

import ast
import io
import os
import sys
import tokenize
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "webapp"))
os.environ.setdefault("KEYBOT_FIRMWARE_DIR", os.path.join(REPO, "src"))

from app import firmware  # noqa: E402


def definitions(source):
    """Every function and class, with the line it starts on."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append((node.name, node.lineno))
    return sorted(found)


def has_a_comment(source):
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            return True
    return False


SAMPLE = '''"""A module docstring.

Spread over several lines.
"""

# A comment on its own line.
VALUE = 1  # and one after some code


def documented(x):
    """Says what it does."""
    return x + 1  # a trailing comment


def only_a_docstring():
    """Nothing but this."""


class Thing:
    """A class docstring."""

    def method(self):
        # A comment inside a method.
        return "# not a comment"
'''


class StrippingTest(unittest.TestCase):
    def test_the_stripped_source_still_parses(self):
        ast.parse(firmware.strip_for_the_board(SAMPLE))

    def test_nothing_moves_to_a_different_line(self):
        stripped = firmware.strip_for_the_board(SAMPLE)
        self.assertEqual(len(stripped.split("\n")), len(SAMPLE.split("\n")))
        self.assertEqual(definitions(stripped), definitions(SAMPLE))

    def test_the_comments_and_docstrings_are_gone(self):
        stripped = firmware.strip_for_the_board(SAMPLE)
        self.assertFalse(has_a_comment(stripped))
        tree = ast.parse(stripped)
        self.assertIsNone(ast.get_docstring(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                self.assertIsNone(ast.get_docstring(node), node.name)

    def test_a_string_that_looks_like_a_comment_is_left_alone(self):
        self.assertIn('"# not a comment"', firmware.strip_for_the_board(SAMPLE))

    def test_a_function_that_was_only_a_docstring_still_has_a_body(self):
        stripped = firmware.strip_for_the_board(SAMPLE)
        self.assertIn("def only_a_docstring():\n    pass", stripped)

    def test_stripping_twice_changes_nothing_the_second_time(self):
        once = firmware.strip_for_the_board(SAMPLE)
        self.assertEqual(firmware.strip_for_the_board(once), once)

    def test_it_actually_makes_the_file_smaller(self):
        self.assertLess(len(firmware.strip_for_the_board(SAMPLE)), len(SAMPLE))


class RealFirmwareTest(unittest.TestCase):
    """The same three checks against the files that really get deployed."""

    def setUp(self):
        self.prepared = firmware.load_firmware_files()

    def test_every_deployed_file_is_prepared(self):
        self.assertEqual(sorted(self.prepared), sorted(firmware.DEPLOY_FILES))

    def test_every_deployed_file_still_parses_once_stripped(self):
        for name, sent in self.prepared.items():
            ast.parse(sent, filename=name)

    def test_no_deployed_file_has_anything_move_line(self):
        for name, sent in self.prepared.items():
            source = (firmware.FIRMWARE_DIR / name).read_text()
            self.assertEqual(definitions(sent), definitions(source), name)

    def test_stripping_the_real_files_is_idempotent(self):
        for name, sent in self.prepared.items():
            self.assertEqual(firmware.strip_for_the_board(sent), sent, name)

    def test_what_is_sent_is_smaller_than_what_is_in_the_repo(self):
        for name, repo_size, sent_size in firmware.firmware_sizes():
            self.assertLess(sent_size, repo_size, name)

    def test_every_file_sent_is_within_what_the_board_has_taken(self):
        # This bounds the over-the-air deploy, where the whole file arrives
        # as one string held in RAM. 12.6KB arrived and ran on the real
        # board; 18.9KB failed with a MemoryError. The limit is the proven
        # figure, not a round number below it, and anything above it is
        # untested rather than known bad.
        #
        # It does not bound a USB deploy, which is how firmware actually
        # reaches the board now: there the board only imports the file, and
        # a freshly flashed board reports 98KB of free heap. If this starts
        # blocking real work, the thing to do is measure the real ceiling on
        # the hardware rather than nudge the number.
        for name, _repo_size, sent_size in firmware.firmware_sizes():
            self.assertLess(sent_size, 12600, name + " is too big to send")


class CodeAndRunnerStayCompatibleTest(unittest.TestCase):
    """The board was once left unbootable by a deploy that wrote two of its
    three files: a new code.py called ScriptRunner with a keyword the old
    script_runner.py did not accept, so startup raised before the web server
    started and the only way back was physical access to the board.

    Deploys are not atomic, so the two files have to stay compatible in both
    directions. These check that code.py never asks ScriptRunner for
    anything the shipped ScriptRunner does not take.
    """

    def setUp(self):
        import ast
        import inspect

        self.ast = ast
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
        sys.path.insert(0, src_dir)
        from script_runner import ScriptRunner

        self.params = set(inspect.signature(ScriptRunner.__init__).parameters)
        with open(os.path.join(src_dir, "code.py")) as f:
            self.tree = ast.parse(f.read())

    def runner_calls(self):
        found = []
        for node in self.ast.walk(self.tree):
            if isinstance(node, self.ast.Call):
                name = getattr(node.func, "id", None)
                if name == "ScriptRunner":
                    found.append(node)
        return found

    def test_code_py_builds_the_runner_exactly_once(self):
        self.assertEqual(len(self.runner_calls()), 1)

    def test_no_keyword_code_py_passes_is_unknown_to_script_runner(self):
        for call in self.runner_calls():
            for kw in call.keywords:
                self.assertIn(
                    kw.arg,
                    self.params,
                    "code.py passes {} but ScriptRunner does not take it, which "
                    "is what left the board unbootable before".format(kw.arg),
                )

    def test_not_more_positional_arguments_than_the_runner_accepts(self):
        for call in self.runner_calls():
            # minus self
            self.assertLessEqual(len(call.args), len(self.params) - 1)


class KeyUpReportsTheHoldTest(unittest.TestCase):
    """The recorder trusts the board's own measurement of a hold over the
    one it times in the browser, because playback reproduces whatever is in
    the script and the browser's figure is off by the difference between the
    two requests' latencies.

    code.py cannot be imported here: it needs wifi, usb_hid and the adafruit
    libraries. So these read the source, which is enough to catch the
    bookkeeping going out of step -- a press time recorded and never read, a
    release that reports nothing, a table that grows forever.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = (firmware.FIRMWARE_DIR / "code.py").read_text()
        cls.tree = ast.parse(cls.source)
        cls.handlers = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.FunctionDef)
        }

    def body_of(self, name):
        self.assertIn(name, self.handlers, name + " is gone from code.py")
        return ast.dump(self.handlers[name])

    def test_key_down_records_when_it_pressed(self):
        body = self.body_of("key_down_handler")
        self.assertIn("live_down_at", body, "nothing remembers when the key went down")
        self.assertIn("monotonic_ns", body, "the press time is not taken from the clock")

    def test_key_up_reports_the_hold_it_measured(self):
        body = self.body_of("key_up_handler")
        self.assertIn("live_down_at", body, "the release does not read the press time")
        self.assertIn("'held'", body, "the release does not report the hold")

    def test_key_up_does_not_leave_the_press_time_behind(self):
        # pop, not a plain read: a key pressed and released over and over
        # through a long take would otherwise grow this table forever on a
        # board with about 50KB of heap to spare.
        self.assertIn(
            "attr='pop'",
            self.body_of("key_up_handler"),
            "the press time is read without being removed",
        )

    def test_letting_go_of_everything_forgets_the_press_times_too(self):
        # release_live_keys runs when a script starts and on Stop. Clearing
        # the keys but not their press times would leave a stale time for a
        # key pressed again later.
        self.assertIn(
            "live_down_at",
            self.body_of("release_live_keys"),
            "release_live_keys clears the keys but not when they went down",
        )

    def test_the_running_build_is_reported(self):
        # Which firmware is on the board was once guesswork from which
        # routes answered, and that guess was wrong twice in one session.
        self.assertRegex(
            self.source,
            r'FW_VERSION\s*=\s*"[^"]+"',
            "code.py does not name its own version",
        )
        self.assertIn(
            "fw_version",
            self.body_of("status_handler"),
            "/status does not report the firmware version",
        )


MS = 1000000  # nanoseconds in a millisecond


class FakeClock:
    """Advances only when something takes time: a sleep, a poll, or a turn
    of a spin loop. A real spin burns real time, so reading the clock costs
    a microsecond, which is what lets the blackout spin terminate here.
    """

    def __init__(self):
        self.now = 1000 * MS
        self.slept = []

    def monotonic_ns(self):
        self.now += 1000  # a microsecond per turn of a spin
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += int(seconds * 1000000000)


class FakeServer:
    """A web server whose poll costs real time, which is the thing that was
    overrunning step deadlines."""

    def __init__(self, clock, cost_ns=0):
        self.clock = clock
        self.cost_ns = cost_ns
        self.polls = 0
        self.poll_times = []

    def poll(self):
        self.polls += 1
        self.poll_times.append(self.clock.now)
        self.clock.now += self.cost_ns


class FakeRunner:
    def __init__(self, stop_after_polls=None):
        self.stop_requested = False
        self.stop_after_polls = stop_after_polls


class StepsEndOnTimeTest(unittest.TestCase):
    """A step that overshoots its deadline is the whole of the drift Rosy
    saw: the same script from the same state gave slightly different
    results, because serving a status request on the last poll of a step
    stretched that step by ~50ms, in a different place each run.

    wait_until is lifted out of code.py and run against a fake clock, which
    is the only way to assert on this exactly. code.py itself cannot be
    imported here: it needs wifi, usb_hid and the adafruit libraries.
    """

    @classmethod
    def setUpClass(cls):
        source = (firmware.FIRMWARE_DIR / "code.py").read_text()
        tree = ast.parse(source)
        wanted = ("wait_until",)
        kept = [
            node
            for node in tree.body
            if (isinstance(node, ast.FunctionDef) and node.name in wanted)
            or (
                isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "POLL_BLACKOUT_NS"
            )
        ]
        cls.assertTrue(
            cls, len(kept) == 2, "wait_until and POLL_BLACKOUT_NS must be module level"
        )
        cls.module = ast.Module(body=kept, type_ignores=[])
        cls.code = compile(ast.fix_missing_locations(cls.module), "code.py", "exec")

    def load(self, clock):
        ns = {"time": clock}
        exec(self.code, ns)
        return ns["wait_until"], ns["POLL_BLACKOUT_NS"]

    def run_wait(self, duration_ns, poll_cost_ns=0):
        clock = FakeClock()
        wait_until, blackout = self.load(clock)
        server = FakeServer(clock, poll_cost_ns)
        runner = FakeRunner()
        started = clock.now
        end_time = started + duration_ns
        stopped = wait_until(server, runner, end_time, 100 * MS)
        return {
            "overshoot_ns": clock.now - end_time,
            "polls": server.polls,
            "server": server,
            "clock": clock,
            "blackout": blackout,
            "stopped": stopped,
            "end_time": end_time,
        }

    def test_a_wait_does_not_run_past_its_deadline(self):
        # The old loop slept a full 100ms slice without looking at how much
        # was left, so a wait ran 0 to 100ms long depending on where its
        # deadline fell between slice boundaries. Durations that are exact
        # multiples of the slice land on the deadline by luck and hide it,
        # so this sweeps: 1.4s is the lucky case, 1.37s is what a real
        # recording produces.
        for ms in (1400, 1370, 1230, 1050, 999, 760, 333, 150, 101):
            r = self.run_wait(ms * MS)
            self.assertLess(
                r["overshoot_ns"],
                MS,
                "a {}ms wait overshot by {}ms".format(ms, r["overshoot_ns"] / MS),
            )

    def test_a_hold_of_any_length_ends_on_time(self):
        for ms in (2060, 1240, 870, 450, 230, 100):
            clock = FakeClock()
            wait_until, _ = self.load(clock)
            server = FakeServer(clock, 50 * MS)
            end_time = clock.now + ms * MS
            wait_until(server, FakeRunner(), end_time, 2 * MS)
            overshoot = clock.now - end_time
            self.assertLess(
                overshoot,
                MS,
                "a {}ms hold overshot by {}ms".format(ms, overshoot / MS),
            )

    def test_a_hold_does_not_run_past_its_deadline(self):
        r = self.run_wait(100 * MS)
        self.assertLess(r["overshoot_ns"], MS)

    def test_a_slow_request_mid_step_costs_the_step_nothing(self):
        # A poll is free in the middle: the deadline is absolute, so the
        # loop simply has less left to wait afterwards.
        r = self.run_wait(2000 * MS, poll_cost_ns=50 * MS)
        self.assertLess(
            r["overshoot_ns"],
            MS,
            "a 50ms request stretched the step by {}ms".format(
                r["overshoot_ns"] / MS
            ),
        )
        self.assertGreater(r["polls"], 0, "it stopped serving the web server entirely")

    def test_nothing_is_served_once_the_deadline_is_close(self):
        # This is what stops the last poll overrunning: inside the blackout
        # there is no poll left to overrun with.
        r = self.run_wait(2000 * MS, poll_cost_ns=50 * MS)
        latest = max(r["server"].poll_times)
        self.assertLessEqual(
            latest,
            r["end_time"] - r["blackout"],
            "a request was served inside the blackout",
        )

    def test_it_never_sleeps_into_the_blackout(self):
        # A sleep that lands inside the blackout skips the spin, and the
        # overshoot comes straight back.
        r = self.run_wait(1400 * MS)
        for seconds in r["clock"].slept:
            self.assertGreater(seconds, 0, "slept for nothing, which is a busy loop")

    def test_the_web_server_still_gets_served_during_a_long_wait(self):
        r = self.run_wait(5000 * MS)
        self.assertGreater(
            r["polls"], 10, "only {} polls in a 5s wait".format(r["polls"])
        )

    def test_stop_is_obeyed_and_said_so(self):
        clock = FakeClock()
        wait_until, _ = self.load(clock)
        server = FakeServer(clock)
        runner = FakeRunner()

        real_poll = server.poll

        def poll_then_stop():
            real_poll()
            runner.stop_requested = True

        server.poll = poll_then_stop
        stopped = wait_until(server, runner, clock.now + 10000 * MS, 100 * MS)
        self.assertTrue(stopped, "a stop during a step was not reported")

    def test_a_deadline_already_passed_returns_at_once(self):
        clock = FakeClock()
        wait_until, _ = self.load(clock)
        server = FakeServer(clock)
        wait_until(server, FakeRunner(), clock.now - 500 * MS, 100 * MS)
        self.assertEqual(server.polls, 0, "it served requests on a step already due")


if __name__ == "__main__":
    unittest.main()
