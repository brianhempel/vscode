"""
Tests for error_visualizer.py - uncaught exceptions rendered as red text.

These tests follow TDD: written before the implementation.

Run this test file directly:
    python3 src/vs/platform/snc/node/visualizers/error_visualizer_tests.py

Or use pytest with verbose output:
    python3 -m pytest src/vs/platform/snc/node/visualizers/error_visualizer_tests.py -v
"""

import unittest

from error_visualizer import can_visualize, visualize
from visualizer_utils import ERROR_RED, UncaughtError


def uncaught(exc_type, *args):
    """What the runner logs when the user's program dies of this: an exception
    that actually went through a raise, wrapped as the one that got away."""
    try:
        raise exc_type(*args)
    except BaseException as e:
        return UncaughtError(e)


class TestCanVisualize(unittest.TestCase):
    def test_visualizes_the_uncaught_exception(self):
        self.assertTrue(can_visualize(uncaught(ZeroDivisionError, "division by zero")))
        self.assertTrue(can_visualize(uncaught(TypeError, "unsupported operand")))

    def test_visualizes_user_defined_exceptions(self):
        class MyError(Exception):
            pass

        self.assertTrue(can_visualize(uncaught(MyError, "boom")))

    def test_visualizes_non_exception_baseexceptions(self):
        """KeyboardInterrupt/SystemExit don't inherit from Exception but still
        end the run."""
        self.assertTrue(can_visualize(uncaught(KeyboardInterrupt)))
        self.assertTrue(can_visualize(uncaught(SystemExit, 1)))

    def test_does_not_visualize_a_caught_exception_held_as_a_value(self):
        """`except ValueError as e` leaves the program holding an ordinary
        value; it belongs to the object visualizer, not to red text."""
        self.assertFalse(can_visualize(ValueError("nope")))
        try:
            raise ZeroDivisionError("division by zero")
        except ZeroDivisionError as e:
            caught = e
        self.assertFalse(can_visualize(caught))

    def test_does_not_visualize_the_error_message_string(self):
        """The string visualizer keeps ordinary strings, even ones that read
        like an error."""
        self.assertFalse(can_visualize("ZeroDivisionError: division by zero"))

    def test_does_not_visualize_exception_classes(self):
        self.assertFalse(can_visualize(ValueError))
        self.assertFalse(can_visualize(Exception))

    def test_does_not_visualize_ordinary_values(self):
        self.assertFalse(can_visualize(None))
        self.assertFalse(can_visualize(0))
        self.assertFalse(can_visualize([1, 2, 3]))
        self.assertFalse(can_visualize({"error": "x"}))


class TestVisualize(unittest.TestCase):
    def test_shows_type_and_message(self):
        html = visualize(uncaught(ZeroDivisionError, "division by zero"))
        self.assertIn("ZeroDivisionError: division by zero", html)

    def test_is_red(self):
        html = visualize(uncaught(ZeroDivisionError, "division by zero"))
        self.assertIn(ERROR_RED, html)

    def test_bare_type_name_when_there_is_no_message(self):
        """No dangling colon on `raise ValueError`."""
        html = visualize(uncaught(ValueError))
        self.assertIn("ValueError", html)
        self.assertNotIn("ValueError:", html)

    def test_uses_the_exception_class_name_not_the_wrapper_one(self):
        class MyError(Exception):
            pass

        html = visualize(uncaught(MyError, "boom"))
        self.assertIn("MyError: boom", html)
        self.assertNotIn("UncaughtError", html)

    def test_escapes_html_in_the_message(self):
        html = visualize(uncaught(TypeError, "'<' not supported between 'int' & 'str'"))
        self.assertIn("&lt;", html)
        self.assertNotIn("<'", html)
        self.assertIn("&amp;", html)

    def test_escapes_html_in_the_type_name(self):
        cls = type("Bad<Name>", (Exception,), {})
        html = visualize(UncaughtError(cls("x")))
        self.assertIn("Bad&lt;Name&gt;", html)

    def test_survives_an_exception_whose_str_raises(self):
        """A broken __str__ must not turn an error item into a visualizer crash."""

        class Hostile(Exception):
            def __str__(self):
                raise RuntimeError("no str for you")

        html = visualize(UncaughtError(Hostile()))
        self.assertIn("Hostile", html)
        self.assertIn(ERROR_RED, html)

    def test_multiline_messages_keep_their_line_breaks(self):
        html = visualize(uncaught(AssertionError, "expected:\n  1\ngot:\n  2"))
        self.assertIn("pre-wrap", html)
        self.assertIn("expected:\n", html)


if __name__ == '__main__':
    unittest.main()
