"""Tests for the two requests a saved recording goes through (issue #19).

The rules themselves are tested without a webapp in dev/test_recording_save.py.
These are about what a browser is actually told: the status code, and the
message on it.

Run them from the repo root with:

    python3 -m pytest webapp/tests
"""

import asyncio
import json
import os

import pytest

from app import main, storage


class FakeRequest:
    """Enough of a request for the handlers: a JSON body and path params."""

    def __init__(self, body=None, **path_params):
        self._body = body if body is not None else {}
        self.path_params = path_params

    async def json(self):
        return self._body


def call(coro):
    return asyncio.run(coro)


def body_of(response):
    return json.loads(response.body)


@pytest.fixture(autouse=True)
def firmware_source(monkeypatch):
    """The step limit is read from the firmware source, which the container
    has mounted at /firmware_src and a test run from the repo does not."""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import flatten

    monkeypatch.setattr(flatten, "FIRMWARE_DIR", __import__("pathlib").Path(repo) / "src")
    monkeypatch.setattr(flatten, "_max_program_nodes", None)


def recorded():
    return [["press", "A", 0.1], ["wait", 0.5]]


def test_a_recording_with_no_target_is_saved_on_its_own():
    response = call(
        main.api_save_recording(
            FakeRequest({"name": "Recording 1", "steps": recorded()})
        )
    )
    assert response.status_code == 200
    saved = body_of(response)["script"]
    assert storage.get_script(saved["id"])["steps"] == recorded()


def test_the_next_free_name_is_offered():
    storage.save_script(None, "Recording 1", "", recorded())
    storage.save_script(None, "Recording 3", "", recorded())
    response = call(main.api_recording_next_name(FakeRequest()))
    assert body_of(response)["name"] == "Recording 2"


def test_a_deleted_target_is_a_404_that_says_the_recording_was_kept():
    response = call(
        main.api_save_recording(
            FakeRequest(
                {
                    "name": "Recording 2",
                    "steps": recorded(),
                    "target_id": "gone",
                    "target_name": "Gathering",
                }
            )
        )
    )
    assert response.status_code == 404
    answer = body_of(response)
    assert "Saved as “Recording 2” on its own" in answer["detail"]
    assert storage.get_script(answer["script"]["id"])["steps"] == recorded()


def test_a_stale_rev_is_a_409_and_nothing_is_written():
    target = storage.save_script(None, "Gathering", "", [["press", "ENTER", 0.1]])
    storage.save_script(target["id"], "Gathering", "", [["press", "B", 0.1]])

    response = call(
        main.api_save_recording(
            FakeRequest(
                {
                    "name": "Recording 1",
                    "steps": recorded(),
                    "target_id": target["id"],
                    "target_name": "Gathering",
                    "target_rev": target["rev"],
                }
            )
        )
    )
    assert response.status_code == 409
    assert body_of(response)["detail"] == (
        "“Gathering” changed in another tab, reload before saving"
    )
    assert [s["name"] for s in storage.list_scripts()] == ["Gathering"]
    assert storage.get_script(target["id"])["steps"] == [["press", "B", 0.1]]


def test_saving_a_script_over_a_newer_one_is_refused():
    script = storage.save_script(None, "Gathering", "", [["press", "ENTER", 0.1]])
    storage.save_script(script["id"], "Gathering", "", [["press", "B", 0.1]])

    response = call(
        main.api_update_script(
            FakeRequest(
                {"name": "Gathering", "steps": [["press", "C", 0.1]], "rev": script["rev"]},
                script_id=script["id"],
            )
        )
    )
    assert response.status_code == 409
    assert storage.get_script(script["id"])["steps"] == [["press", "B", 0.1]]


def test_saving_a_script_from_the_rev_it_was_loaded_at_goes_through():
    script = storage.save_script(None, "Gathering", "", [["press", "ENTER", 0.1]])
    response = call(
        main.api_update_script(
            FakeRequest(
                {"name": "Gathering", "steps": [["press", "C", 0.1]], "rev": script["rev"]},
                script_id=script["id"],
            )
        )
    )
    assert response.status_code == 200
    assert body_of(response)["rev"] == script["rev"] + 1


def test_unsaved_steps_can_be_measured_against_the_boards_limit():
    response = call(
        main.api_preview_steps(
            FakeRequest({"steps": [["press", "A", 0.1], ["wait", 1.0]], "name": "draft"})
        )
    )
    answer = body_of(response)
    assert answer["ok"] is True
    assert answer["step_count"] == 2
    assert answer["limit"] == 500
