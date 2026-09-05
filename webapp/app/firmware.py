"""Reads the Pico's firmware source (keycodes.py, script_runner.py and
code.py) from the repo's src/ folder, which the webapp is given read-only
access to as a Docker volume, takes the comments out, and does a basic
sanity check before any of it is sent to the device.

Why the comments come out: each file is sent to the board in one request,
and the board has to hold that whole request in memory to parse it. It was
measured -- a 600-step program (a ~12.6KB body) arrives fine, 900 steps
(~18.9KB) fails with a MemoryError, and the allocation that fails is
smaller than the body, so it is fragmentation rather than a clean limit.
script_runner.py with its explanations in it sits in that failing range.

So the repo keeps the readable file and the board gets the small one.
Comments and docstrings are blanked where they stand rather than deleted,
so every remaining line keeps the line number it has in the repo: a
traceback or an error from the board still points at the right line of the
source you are reading.
"""

import ast
import io
import os
import tokenize
from pathlib import Path

FIRMWARE_DIR = Path(os.environ.get("KEYBOT_FIRMWARE_DIR", "/firmware_src"))
# The order matters, because the files are sent one at a time and the board
# restarts after each one: there is a moment when they do not all match, and
# the board has to boot anyway.
#
# keycodes.py first: code.py imports it, and imports it in a way that
# survives the file not being there yet, so it is safe either way round --
# but sending it first means the board is only ever missing it once.
#
# script_runner.py before code.py: old code.py with new script_runner.py is
# fine, because the new arguments are optional. New code.py with old
# script_runner.py is not: it passes an argument the old one does not take,
# the import fails outside the error handler, and the board reboot-loops
# with no server.
DEPLOY_FILES = ["keycodes.py", "script_runner.py", "code.py"]


class FirmwareError(Exception):
    """Raised when the firmware source can't be read, or doesn't even parse
    as valid Python. The message is meant to be shown to the user."""


def _docstring_spans(tree, source_lines):
    """Where every docstring is: (line, column, end line, end column, what
    to put in its place). A docstring that is the whole of a function or
    class body becomes "pass", because a body cannot be empty."""
    spans = []
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        alone = len(body) == 1 and not isinstance(node, ast.Module)
        spans.append(
            (
                first.lineno,
                first.col_offset,
                first.end_lineno,
                first.end_col_offset,
                "pass" if alone else "",
            )
        )
    return spans


def _comment_spans(source):
    spans = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            spans.append((token.start[0], token.start[1], token.end[0], token.end[1], ""))
    return spans


def strip_for_the_board(source: str) -> str:
    """The same code with its comments and docstrings taken out, and every
    other line still on the line it was on."""
    lines = source.split("\n")
    spans = _docstring_spans(ast.parse(source), lines) + _comment_spans(source)
    # Back to front, so removing one span can't move the next one.
    for start_line, start_col, end_line, end_col, replacement in sorted(spans, reverse=True):
        opening = lines[start_line - 1]
        closing = lines[end_line - 1]
        lines[start_line - 1] = opening[:start_col] + replacement
        for i in range(start_line, end_line - 1):
            # A line wholly inside a docstring: emptied, but still a line.
            lines[i] = ""
        if end_line == start_line:
            lines[start_line - 1] += closing[end_col:]
        else:
            lines[end_line - 1] = closing[end_col:]
    return "\n".join(line.rstrip() for line in lines)


def _prepared():
    """Every deployed file as (name, what gets sent, its size in the repo).
    Raises FirmwareError if a file can't be read, doesn't parse, or doesn't
    still parse once the comments are out."""
    prepared = []
    for name in DEPLOY_FILES:
        path = FIRMWARE_DIR / name
        try:
            content = path.read_text()
        except OSError as e:
            raise FirmwareError(f"can't read {name} from the repo: {e}")
        try:
            stripped = strip_for_the_board(content)
        except SyntaxError as e:
            raise FirmwareError(f"{name} has a syntax error and won't be sent: {e}")
        try:
            # Checked on the stripped text, because that is what lands.
            ast.parse(stripped, filename=name)
        except SyntaxError as e:
            raise FirmwareError(
                f"{name} stopped being valid Python when its comments were "
                f"taken out, so it won't be sent: {e}"
            )
        prepared.append((name, stripped, len(content.encode())))
    return prepared


def load_firmware_files() -> dict:
    """Each deployed file, as the text the board will actually receive."""
    return {name: sent for name, sent, _repo_size in _prepared()}


def firmware_sizes() -> list:
    """(name, bytes in the repo, bytes sent) for each file, so the margin
    against what the board can hold is visible rather than assumed."""
    return [
        (name, repo_size, len(sent.encode())) for name, sent, repo_size in _prepared()
    ]
