"""Uncaught exception visualizer for Sculpt-n-Code.

When the user's program dies, the runner logs the exception on the line that
raised it, wrapped in an UncaughtError. It reads as an error, not as a value,
so it gets red text instead of the string visualizer's character grid.

Only the exception that ended the run. One the program caught and is holding is
an ordinary value and stays with the object visualizer.

Sorts first among the built-in visualizers, so it sees the wrapper before the
catch-all object visualizer does.
"""

import html

from visualizer_utils import ERROR_RED, UncaughtError


def can_visualize(value):
    return isinstance(value, UncaughtError)


def error_text(value):
    """`TypeError: unsupported operand ...`, or a bare type name when the
    exception carries no message."""
    exception = value.exception
    type_name = type(exception).__name__
    try:
        message = str(exception)
    except Exception:
        # A broken __str__ shouldn't cost the user the name of what went wrong.
        message = ''
    return f'{type_name}: {message}' if message else type_name


def visualize(value):
    # pre-wrap inline rather than in snc.css: assertion messages arrive
    # multi-line, and a visualizer should render right on its own.
    return (f'<span class="snc-error-visualizer" '
            f'style="color: {ERROR_RED}; white-space: pre-wrap;">'
            f'{html.escape(error_text(value))}</span>')
