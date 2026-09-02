"""Uncaught exception visualizer for Sculpt-n-Code.

When the user's program dies, the runner logs the exception on the line that
raised it, wrapped in an UncaughtError. It reads as an error, not as a value,
so it gets red text instead of the string visualizer's character grid.

Only the exception that ended the run. One the program caught and is holding is
an ordinary value and stays with the object visualizer.

Sorts first among the built-in visualizers, so it sees the wrapper before the
catch-all object visualizer does.
"""

from visualizer_utils import UncaughtError, error_html
from visualizer_utils import error_text as _error_text


def can_visualize(value):
    return isinstance(value, UncaughtError)


def error_text(value):
    """`TypeError: unsupported operand ...`, or a bare type name when the
    exception carries no message."""
    return _error_text(value.exception)


def visualize(value):
    # The drawing lives in visualizer_utils: a table cell or a tuple element
    # that raised draws the same thing, so an error reads the same everywhere.
    return error_html(value.exception)
