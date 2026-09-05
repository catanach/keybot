"""Tests for how the page itself is served.

The key picker looked completely broken in the browser for one reason: the
page was new and the JavaScript the browser ran was old, kept from an
earlier visit. These are the two things that stop that happening again --
each asset's URL carries the time that file last changed, and the page is
never reused without checking with the server first.

Run them from the repo root with:

    python3 -m pytest webapp/tests
"""

import asyncio
import re

from app import main


def test_asset_urls_carry_the_time_the_file_last_changed():
    html = '<link href="/static/style.css"><script src="/static/app.js"></script>'
    stamped = main.stamp_asset_versions(html)
    assert re.search(r'/static/app\.js\?v=\d+', stamped)
    assert re.search(r'/static/style\.css\?v=\d+', stamped)


def test_a_changed_file_gets_a_different_url(tmp_path, monkeypatch):
    asset = tmp_path / "static" / "app.js"
    asset.parent.mkdir()
    asset.write_text("first")
    monkeypatch.setattr(main, "APP_DIR", tmp_path)

    before = main.stamp_asset_versions('<script src="/static/app.js"></script>')
    import os
    os.utime(asset, (0, 0))
    after = main.stamp_asset_versions('<script src="/static/app.js"></script>')
    assert before != after


def test_the_page_is_never_reused_without_asking():
    response = asyncio.run(main.index(None))
    assert response.headers["cache-control"] == "no-cache"
    assert b"/static/app.js?v=" in response.body
