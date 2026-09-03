"""Shared setup for the webapp's tests.

Run them from the repo root with:

    python3 -m pytest webapp/tests

pytest is a development tool only -- it is deliberately not in
webapp/requirements.txt, so it never ships inside the container image.

Every test gets its own empty data directory via KEYBOT_DATA_DIR, so
nothing here can read or overwrite the real history file or scripts.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYBOT_DATA_DIR", str(tmp_path))
    return tmp_path
