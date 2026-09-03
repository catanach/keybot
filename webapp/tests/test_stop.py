"""Tests for stopping a run.

Two things matter here. Asking the board to stop a second time, after it
failed to confirm the first, must not look like a second thing happening
to the run. And a stop the board never confirmed must not be written down
as a clean stop -- the board may still be running and still typing.

None of this needs a device or a running webapp: the request handlers are
called directly, with the device layer replaced by a stand-in.
"""

import asyncio

import pytest

from app import device, history, main, settings


def call(coro):
    """Runs one request handler and hands back its response."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def no_run_in_progress():
    # The record of the run in progress is module state, so each test
    # starts and finishes with a clean one.
    main._forget_open_run()
    yield
    main._forget_open_run()


@pytest.fixture(autouse=True)
def runs_cleared(monkeypatch):
    """Catches the "don't resume this later" write instead of letting it
    reach the real settings file, and remembers that it happened."""
    cleared = []
    monkeypatch.setattr(settings, "clear_last_run", lambda: cleared.append(True))
    return cleared


@pytest.fixture
def stops_sent(monkeypatch):
    """A device that answers every stop, and remembers being asked."""
    sent = []

    async def fake_stop(after_current=False):
        sent.append(after_current)

    monkeypatch.setattr(device, "stop", fake_stop)
    return sent


@pytest.fixture
def silent_device(monkeypatch):
    """A device that has stopped answering anything."""

    async def gone(*args, **kwargs):
        raise device.DeviceError("can't reach device at http://192.168.10.22:5000")

    monkeypatch.setattr(device, "get_status", gone)
    monkeypatch.setattr(device, "stop", gone)


# ---------------------------------------------------------------------------
# Asking twice
# ---------------------------------------------------------------------------


def test_a_stop_is_remembered_as_one_we_sent(stops_sent):
    main.open_run["record_id"] = "r1"

    call(main.api_device_stop(None))

    assert stops_sent == [False]
    assert main.open_run["we_stopped_it"] is True


def test_asking_again_sends_the_stop_to_the_board_again(stops_sent):
    main.open_run["record_id"] = "r1"

    call(main.api_device_stop(None))
    call(main.api_device_stop(None))

    assert stops_sent == [False, False]


def test_asking_again_does_not_repeat_the_bookkeeping(stops_sent, runs_cleared):
    main.open_run["record_id"] = "r1"

    call(main.api_device_stop(None))
    call(main.api_device_stop(None))

    assert runs_cleared == [True]


def test_asking_again_does_not_add_a_second_run_to_the_history(stops_sent):
    record_id = history.open_record("a1", "Overnight farm", 500)
    main.open_run["record_id"] = record_id

    call(main.api_device_stop(None))
    call(main.api_device_stop(None))

    records = history.load()
    assert len(records) == 1
    assert records[0]["id"] == record_id
    assert records[0]["outcome"] is None


def test_a_stop_that_never_reaches_the_board_says_so(silent_device):
    response = call(main.api_device_stop(None))

    assert response.status_code == 502


# ---------------------------------------------------------------------------
# A stop the board never confirmed
# ---------------------------------------------------------------------------


def _run_in_progress(we_stopped_it):
    record_id = history.open_record("a1", "Overnight farm", 500)
    main.open_run.update(
        {
            "record_id": record_id,
            "loops_done": 147,
            "we_stopped_it": we_stopped_it,
            "failed_polls": 0,
        }
    )
    return record_id


def test_losing_the_board_after_a_stop_is_recorded_as_unconfirmed(silent_device):
    _run_in_progress(we_stopped_it=True)

    for _ in range(main.LOST_CONTACT_AFTER_FAILED_POLLS):
        call(main._poll_device_once())

    record = history.load()[0]
    assert record["outcome"] == history.STOP_UNCONFIRMED
    assert record["loops_done"] == 147
    assert "can't reach device" in record["error"]


def test_losing_the_board_with_no_stop_pending_is_still_lost_contact(silent_device):
    _run_in_progress(we_stopped_it=False)

    for _ in range(main.LOST_CONTACT_AFTER_FAILED_POLLS):
        call(main._poll_device_once())

    assert history.load()[0]["outcome"] == history.LOST_CONTACT


def test_a_couple_of_missed_polls_do_not_end_the_run(silent_device):
    _run_in_progress(we_stopped_it=True)

    for _ in range(main.LOST_CONTACT_AFTER_FAILED_POLLS - 1):
        call(main._poll_device_once())

    assert history.load()[0]["outcome"] is None


def test_a_stop_the_board_confirms_is_recorded_as_your_stop(monkeypatch):
    record_id = _run_in_progress(we_stopped_it=True)

    async def stopped():
        return {"running": False, "loop_count": 147, "target_loops": 500, "last_error": None}

    monkeypatch.setattr(device, "get_status", stopped)
    call(main._poll_device_once())

    record = history.load()[0]
    assert record["id"] == record_id
    assert record["outcome"] == history.STOPPED_BY_YOU
