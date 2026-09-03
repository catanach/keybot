"""Tests for the run history: what gets recorded, how a run's outcome is
decided, and that the file survives being written badly.

None of this needs a device or a running webapp.
"""

import json
from pathlib import Path

import pytest

from app import history


# ---------------------------------------------------------------------------
# What a record looks like
# ---------------------------------------------------------------------------


def test_no_history_file_yet_reads_as_no_runs():
    assert history.load() == []


def test_a_finished_run_records_what_happened(data_dir):
    record_id = history.open_record("a1b2c3d4", "Overnight farm", 500)
    history.close_record(record_id, 500, history.FINISHED)

    record = history.load()[0]
    assert record["script_id"] == "a1b2c3d4"
    assert record["script_name"] == "Overnight farm"
    assert record["target_loops"] == 500
    assert record["loops_done"] == 500
    assert record["outcome"] == history.FINISHED
    assert record["error"] is None
    assert record["started_at"] and record["ended_at"]
    assert (data_dir / "history.json").exists()


def test_a_run_still_going_has_no_outcome_yet():
    history.open_record("a1b2c3d4", "Overnight farm", 500)
    record = history.load()[0]
    assert record["outcome"] is None
    assert record["ended_at"] is None


def test_the_newest_run_comes_first():
    history.open_record("a1", "First", 1)
    history.open_record("a2", "Second", 1)
    assert [r["script_name"] for r in history.load()] == ["Second", "First"]


def test_closing_a_run_twice_keeps_the_first_answer():
    record_id = history.open_record("a1", "Overnight farm", 500)
    history.close_record(record_id, 500, history.FINISHED)
    history.close_record(record_id, 3, history.FAILED, "something later")

    record = history.load()[0]
    assert record["outcome"] == history.FINISHED
    assert record["loops_done"] == 500


# ---------------------------------------------------------------------------
# The four outcomes
# ---------------------------------------------------------------------------


def test_running_out_the_target_loop_count_is_finished():
    assert history.outcome_for(500, 500, None, False) == history.FINISHED


def test_a_stop_we_sent_is_you_stopped_it():
    assert history.outcome_for(88, 500, None, True) == history.STOPPED_BY_YOU


def test_an_error_the_device_reported_is_failed():
    problem = "stopped at step 4 of 9: there is no key called 'UP'"
    assert history.outcome_for(2, 500, problem, False) == history.FAILED


def test_an_error_beats_a_stop_we_sent():
    assert history.outcome_for(2, 500, "step 4 blew up", True) == history.FAILED


def test_a_run_with_no_target_that_ends_did_not_finish():
    # Nothing to finish -- an endless run only ever stops because
    # something stopped it.
    assert history.outcome_for(88, None, None, False) == history.STOPPED_BY_YOU


def test_losing_contact_mid_run_records_the_reason():
    record_id = history.open_record("a1", "Overnight farm", 500)
    history.close_record(
        record_id, 3, history.LOST_CONTACT, "can't reach device at http://192.168.10.22:5000"
    )

    record = history.load()[0]
    assert record["outcome"] == history.LOST_CONTACT
    assert record["loops_done"] == 3
    assert "can't reach device" in record["error"]


def test_a_board_that_went_quiet_after_a_stop_is_not_a_clean_stop():
    # We asked it to stop and then lost it. It may have stopped; it may
    # also still be running and still typing. Saying "you stopped it"
    # would claim something the board never confirmed.
    assert (
        history.outcome_for(147, 500, None, True, still_answering=False)
        == history.STOP_UNCONFIRMED
    )


def test_a_board_that_went_quiet_on_its_own_is_lost_contact():
    assert (
        history.outcome_for(147, 500, None, False, still_answering=False)
        == history.LOST_CONTACT
    )


def test_a_stop_the_board_confirmed_is_still_you_stopped_it():
    assert history.outcome_for(147, 500, None, True) == history.STOPPED_BY_YOU


def test_an_unconfirmed_stop_is_written_to_the_record():
    record_id = history.open_record("a1", "Overnight farm", 500)
    history.close_record(
        record_id, 147, history.STOP_UNCONFIRMED, "can't reach device at http://192.168.10.22:5000"
    )

    record = history.load()[0]
    assert record["outcome"] == history.STOP_UNCONFIRMED
    assert record["loops_done"] == 147


# ---------------------------------------------------------------------------
# Runs left open by a restart
# ---------------------------------------------------------------------------


def test_a_run_left_open_by_a_restart_is_closed_as_lost_contact():
    orphan_id = history.open_record("a1", "Overnight farm", 500)
    done_id = history.open_record("a2", "Gathering", 10)
    history.close_record(done_id, 10, history.FINISHED)

    assert history.close_open_records() == 1

    records = {r["id"]: r for r in history.load()}
    assert records[orphan_id]["outcome"] == history.LOST_CONTACT
    assert records[orphan_id]["ended_at"] is not None
    assert records[done_id]["outcome"] == history.FINISHED


def test_closing_orphans_when_there_are_none_leaves_everything_alone():
    record_id = history.open_record("a1", "Overnight farm", 500)
    history.close_record(record_id, 500, history.FINISHED)
    before = history.load()

    assert history.close_open_records() == 0
    assert history.load() == before


# ---------------------------------------------------------------------------
# Keeping the file small, and keeping it whole
# ---------------------------------------------------------------------------


def test_only_the_fifty_most_recent_runs_are_kept():
    for i in range(55):
        record_id = history.open_record("a1", "Run {}".format(i), 1)
        history.close_record(record_id, 1, history.FINISHED)

    records = history.load()
    assert history.MAX_RECORDS == 50
    assert len(records) == 50
    assert records[0]["script_name"] == "Run 54"
    assert records[-1]["script_name"] == "Run 5"


def test_a_write_that_dies_partway_leaves_the_last_good_history(data_dir, monkeypatch):
    """The poller rewrites this file every time a run starts or ends. If
    the container is killed mid-write, the records already on disk have to
    survive -- which is why the write goes to a temp file first."""
    record_id = history.open_record("a1", "Overnight farm", 500)
    history.close_record(record_id, 500, history.FINISHED)
    before = history.load()

    real_write_text = Path.write_text

    def die_halfway(self, text, *args, **kwargs):
        real_write_text(self, text[: len(text) // 2])
        raise OSError("the container was killed mid-write")

    monkeypatch.setattr(Path, "write_text", die_halfway)
    with pytest.raises(OSError):
        history.open_record("a2", "Gathering", 10)

    # Reading is untouched, so the file can be checked with the broken
    # write still in place.
    assert history.load() == before
    assert json.loads((data_dir / "history.json").read_text()) == before
