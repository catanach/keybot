"""Tests for the key list the editor's picker is built from.

The names come from src/keycodes.py, the same file the Pico runs. What is
checked here is the part the webapp adds: reading that file, splitting it
into the groups the picker shows, and serving it.

Run them from the repo root with:

    python3 -m pytest webapp/tests
"""

import asyncio
import json
from pathlib import Path

import pytest

from app import keycodes, main

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def firmware_dir(monkeypatch):
    """The container gets src/ mounted at /firmware_src. A test run does
    not, so point the loader at the repo's own src/ folder."""
    monkeypatch.setattr(keycodes, "FIRMWARE_DIR", REPO / "src")


def groups():
    return {group["name"]: group["keys"] for group in keycodes.grouped()}


def test_groups_come_back_in_the_agreed_order():
    order = [group["name"] for group in keycodes.grouped()]
    assert order == [
        "Common", "Letters", "Numbers", "Arrows", "Function keys",
        "Keypad", "Modifiers", "Punctuation", "Other",
    ]


def test_common_holds_the_everyday_keys_in_order():
    assert [key["name"] for key in groups()["Common"]] == [
        "ENTER", "SPACE", "TAB", "ESCAPE", "BACKSPACE", "DELETE",
    ]


def test_keys_carry_the_name_and_a_label_a_person_would_use():
    numbers = {key["name"]: key["label"] for key in groups()["Numbers"]}
    assert numbers["EIGHT"] == "8"
    arrows = {key["name"]: key["label"] for key in groups()["Arrows"]}
    assert arrows["UP_ARROW"] == "Up arrow"


def test_every_key_in_the_shared_list_lands_in_exactly_one_group():
    shared = [name for name, _label in keycodes.load_keycodes()]
    served = [key["name"] for group in keycodes.grouped() for key in group["keys"]]
    assert sorted(served) == sorted(shared)


def test_the_endpoint_serves_the_same_groups():
    response = asyncio.run(main.api_keycodes(None))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["groups"] == keycodes.grouped()
