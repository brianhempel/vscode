"""
Tests for python_runner.py.

Run:
    python3 -m pytest src/vs/platform/snc/node/python_runner_tests.py -v
"""

import __future__
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as _mock
import urllib.request
from dataclasses import dataclass
from typing import Optional

import std_streams
import url_cache
import python_runner
from python_runner import (
    SEED,
    GenericVisualizer,
    VisualizerOfStaticVisualizer,
    _build_new_code_edits,
    _commands_to_dicts,
    drain_stdin_lines,
    execute_code,
    imports_match,
    install_url_cache,
    log_value,
    read_stdin_line,
    reseed,
    split_leading_imports,
    transform_code_to_ast,
    user_facing_traceback,
)
# python_runner puts the built-in visualizers on the path.
from visualizer_utils import (py_exp_attrs, AddImports, UncaughtError,
                              save_slots_at_path,
                              format_config_comment, config_sig)


def exp_attr(*exprs):
    """The `snc-py-exps` attribute a handle offering these expressions carries,
    as it reads inside the tag it was written into."""
    return py_exp_attrs(list(exprs), draggable=False).strip()


class _StreamMessages:
    """The NDJSON messages the runner wrote to the editor."""

    def __init__(self, buf):
        self._buf = buf

    def all(self):
        return [json.loads(line) for line in self._buf.getvalue().splitlines() if line.strip()]

    def output(self, stream=None):
        """(stream, text, stdin_offset) for each output chunk, in order."""
        return [(m['stream'], m['text'], m['stdin_offset'])
                for m in self.all()
                if m.get('type') == 'output' and (stream is None or m['stream'] == stream)]

    def text_of(self, stream):
        return ''.join(text for _, text, _ in self.output(stream))


@contextlib.contextmanager
def capture_stream_messages():
    """Redirect the runner's message channel into a buffer for the block."""
    buf = io.StringIO()
    old = python_runner._stream_out
    python_runner._stream_out = buf
    try:
        yield _StreamMessages(buf)
    finally:
        python_runner._stream_out = old


class TestSplitLeadingImports(unittest.TestCase):
    def test_bare_string_after_imports_stays_in_body(self):
        source_code = 'import re\n\n"hello world"\n'
        import_code, body_code = split_leading_imports(source_code)

        logged = []
        globals_dict = {
            "__name__": "__main__",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
        }

        exec(import_code, globals_dict)
        exec(body_code, globals_dict)

        self.assertEqual(logged, [(3, "hello world")])

    def test_only_initial_string_literal_counts_as_docstring(self):
        source_code = '"""module docstring"""\nimport re\n\n"hello world"\n'
        import_code, body_code = split_leading_imports(source_code)

        logged = []
        globals_dict = {
            "__name__": "__main__",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
        }

        exec(import_code, globals_dict)
        exec(body_code, globals_dict)

        self.assertEqual(logged, [(4, "hello world")])


class TestReseed(unittest.TestCase):
    """Every rerun is a fresh process, so unseeded randomness makes visualized
    values jump on each keystroke and under the user's cursor mid-interaction."""

    def _globals(self, logged):
        return {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
            "_log_and_return": lambda line, value, *a, **k: (logged.append((line, value)), value)[1],
        }

    def _run_checkpoint1(self, source_code):
        """Imports and body execute in one go, seeded in between."""
        logged = []
        import_code, body_code = split_leading_imports(source_code)
        execute_code(body_code, self._globals(logged), import_code=import_code)
        return logged

    def _run_checkpoint2(self, source_code):
        """Imports already ran during pre-warm; only the body executes now."""
        logged = []
        import_code, body_code = split_leading_imports(source_code)
        globals_dict = self._globals(logged)
        exec(import_code, globals_dict)
        execute_code(body_code, globals_dict)
        return logged

    def test_reseed_makes_stdlib_random_reproducible(self):
        reseed()
        first = [random.random() for _ in range(5)]
        reseed()
        self.assertEqual([random.random() for _ in range(5)], first)

    def test_reruns_of_the_same_code_agree(self):
        source_code = "import random\nx = random.random()\n"
        self.assertEqual(self._run_checkpoint2(source_code), self._run_checkpoint2(source_code))

    def test_checkpoint1_and_checkpoint2_agree(self):
        source_code = "import random\nx = random.random()\ny = random.randint(0, 1000)\n"
        self.assertEqual(self._run_checkpoint1(source_code), self._run_checkpoint2(source_code))

    def test_user_seed_still_wins(self):
        """Our seed lands before the body, so an explicit seed overrides it."""
        source_code = "import random\nrandom.seed(99)\nx = random.random()\n"
        random.seed(99)
        expected = random.random()
        self.assertEqual(self._run_checkpoint1(source_code)[-1][1], expected)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
    def test_numpy_is_seeded_after_its_import(self):
        """numpy isn't in sys.modules when checkpoint 1 starts, so this only
        holds because the seed lands after the import rather than before it."""
        source_code = "import numpy as np\nx = np.random.rand()\n"
        self.assertEqual(self._run_checkpoint1(source_code), self._run_checkpoint2(source_code))

    def test_reseed_survives_a_broken_numpy(self):
        """A shadowing `numpy.py` on the user's path must not fail their run.

        Patched rather than assigned: a plain `del` afterward would evict the
        real numpy another test already imported, and the re-import that
        provokes warns -- which the aggregations read as no answer at all.
        """
        with _mock.patch.dict(sys.modules, {"numpy": object()}):
            reseed()

    def test_import_errors_still_surface_inline(self):
        """Folding imports into execute_code must keep them inside the same
        error handling, so a bad import stays an inline item on its own line
        rather than taking down the run."""
        errors = []
        real_log_value = python_runner.log_value
        python_runner.log_value = lambda line, value, *args, **kwargs: errors.append((line, value))
        try:
            import_code, body_code = split_leading_imports("import nonexistent_module_xyz\nx = 1\n")
            with capture_stream_messages() as msgs:
                result = execute_code(body_code, self._globals([]), import_code=import_code)
        finally:
            python_runner.log_value = real_log_value

        self.assertEqual(result["exitCode"], 1)
        self.assertEqual(errors[0][0], 1)
        self.assertIsInstance(errors[0][1], UncaughtError)
        self.assertIsInstance(errors[0][1].exception, ModuleNotFoundError)
        self.assertIn("nonexistent_module_xyz", msgs.text_of('stderr'))


class TestUncaughtErrorItems(unittest.TestCase):
    """The exception that ends a run is logged wrapped, so error_visualizer
    claims it and it reads as an error rather than as a string the program
    produced. An exception the program caught is left an ordinary value."""

    def _logged(self, source_code):
        logged = []
        _, body_code = split_leading_imports(source_code)
        globals_dict = {
            "__name__": "__main__",
            "_log_value": lambda line, value, *args, **kwargs: logged.append((line, value)),
            "_log_and_return": lambda line, value, *args, **kwargs: value,
        }
        real_log_value = python_runner.log_value
        python_runner.log_value = lambda line, value, *args, **kwargs: logged.append((line, value))
        try:
            result = execute_code(body_code, globals_dict)
        finally:
            python_runner.log_value = real_log_value
        return logged, result

    def _visualize(self, value):
        def get_visualizer(v):
            return next(x for x in python_runner._visualizers() if x.can_visualize(v))

        vis = get_visualizer(value)
        model = vis.init_model(value, get_visualizer)
        return vis.visualize(value, model, get_visualizer, None)

    def test_the_wrapped_exception_is_logged_not_its_message(self):
        logged, result = self._logged("x = 1\ny = 1 / 0\n")

        self.assertEqual(result["exitCode"], 1)
        line, value = logged[-1]
        self.assertEqual(line, 2)
        self.assertIsInstance(value, UncaughtError)
        self.assertIsInstance(value.exception, ZeroDivisionError)

    def test_the_error_visualizer_claims_it_over_the_string_one(self):
        logged, _ = self._logged("y = 1 / 0\n")
        _, value = logged[-1]

        html = self._visualize(value)

        self.assertIn("snc-error-visualizer", html)
        self.assertIn("ZeroDivisionError: division by zero", html)

    def test_a_caught_exception_stays_an_ordinary_value(self):
        """The run survives, so nothing wraps the exception and the object
        visualizer gets it -- no red."""
        source_code = ("try:\n"
                       "    1 / 0\n"
                       "except ZeroDivisionError as err:\n"
                       "    e = err\n")
        logged, result = self._logged(source_code)

        self.assertEqual(result["exitCode"], 0)
        _, value = logged[-1]
        self.assertIsInstance(value, ZeroDivisionError)
        self.assertNotIsInstance(value, UncaughtError)
        self.assertNotIn("snc-error-visualizer", self._visualize(value))


class TestUserFacingTraceback(unittest.TestCase):
    """The traceback printed to stderr is the user's program's, not ours. The
    frames that got us into their code, and the `<string>` the exec'd body is
    named after, are scaffolding they never wrote and can't act on."""

    _RUNNER_FRAME = (
        f'  File "{os.path.join(os.path.dirname(python_runner.__file__), "python_runner.py")}", '
        'line 2292, in execute_code\n'
        '    exec(code_object, globals_dict)\n'
        '    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n')

    def test_the_runner_frame_goes_with_its_source_and_caret_lines(self):
        cleaned = user_facing_traceback(
            'Traceback (most recent call last):\n'
            + self._RUNNER_FRAME +
            '  File "<string>", line 9, in <module>\n'
            'NameError: name \'r\' is not defined\n')

        self.assertEqual(cleaned,
                         'Traceback (most recent call last):\n'
                         '  line 9, in <module>\n'
                         'NameError: name \'r\' is not defined\n')

    def test_every_frame_of_the_user_program_survives(self):
        cleaned = user_facing_traceback(
            'Traceback (most recent call last):\n'
            + self._RUNNER_FRAME +
            '  File "<string>", line 9, in <module>\n'
            '  File "<string>", line 6, in f\n'
            'NameError: name \'r\' is not defined. Did you mean: \'re\'?\n')

        self.assertEqual(cleaned,
                         'Traceback (most recent call last):\n'
                         '  line 9, in <module>\n'
                         '  line 6, in f\n'
                         'NameError: name \'r\' is not defined. Did you mean: \'re\'?\n')

    def test_a_frame_in_a_real_file_keeps_its_path_and_source(self):
        """Only `<string>` is a name the user can't act on. A module they
        imported is a place they can go look."""
        cleaned = user_facing_traceback(
            'Traceback (most recent call last):\n'
            '  File "<string>", line 3, in <module>\n'
            '  File "/Users/brian/proj/helpers.py", line 12, in go\n'
            '    return 1 / 0\n'
            'ZeroDivisionError: division by zero\n')

        self.assertEqual(cleaned,
                         'Traceback (most recent call last):\n'
                         '  line 3, in <module>\n'
                         '  File "/Users/brian/proj/helpers.py", line 12, in go\n'
                         '    return 1 / 0\n'
                         'ZeroDivisionError: division by zero\n')

    def test_a_frame_in_our_own_directory_goes_too(self):
        """std_streams is as much ours as the runner is; the user's `input()`
        call is the only part of that stack they wrote."""
        cleaned = user_facing_traceback(
            'Traceback (most recent call last):\n'
            '  File "<string>", line 1, in <module>\n'
            f'  File "{os.path.join(os.path.dirname(python_runner.__file__), "std_streams.py")}", '
            'line 40, in readline\n'
            'RuntimeError: boom\n')

        self.assertEqual(cleaned,
                         'Traceback (most recent call last):\n'
                         '  line 1, in <module>\n'
                         'RuntimeError: boom\n')

    def test_a_chained_traceback_is_cleaned_on_both_sides(self):
        cleaned = user_facing_traceback(
            'Traceback (most recent call last):\n'
            + self._RUNNER_FRAME +
            '  File "<string>", line 2, in <module>\n'
            'ValueError: first\n'
            '\n'
            'During handling of the above exception, another exception occurred:\n'
            '\n'
            'Traceback (most recent call last):\n'
            + self._RUNNER_FRAME +
            '  File "<string>", line 4, in <module>\n'
            'RuntimeError: second\n')

        self.assertEqual(cleaned,
                         'Traceback (most recent call last):\n'
                         '  line 2, in <module>\n'
                         'ValueError: first\n'
                         '\n'
                         'During handling of the above exception, another exception occurred:\n'
                         '\n'
                         'Traceback (most recent call last):\n'
                         '  line 4, in <module>\n'
                         'RuntimeError: second\n')

    def test_a_stack_that_is_all_ours_is_left_alone(self):
        """Nothing of the user's to show, so a bug in our own code stays
        reported in full rather than as a traceback with no frames."""
        original = ('Traceback (most recent call last):\n'
                    + self._RUNNER_FRAME +
                    'RuntimeError: boom\n')

        self.assertEqual(user_facing_traceback(original), original)

    def test_text_with_no_traceback_in_it_is_unchanged(self):
        self.assertEqual(user_facing_traceback('just a message\n'), 'just a message\n')


class TestTracebackReachesTheEditorCleaned(unittest.TestCase):
    """End to end: what a failing program actually writes to stderr."""

    def _stderr(self, source_code):
        logged = []
        import_code, body_code = split_leading_imports(source_code)
        globals_dict = {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
            "_log_and_return": lambda line, value, *a, **k: value,
        }
        real_log_value = python_runner.log_value
        python_runner.log_value = lambda line, value, *a, **k: logged.append((line, value))
        try:
            with capture_stream_messages() as msgs:
                execute_code(body_code, globals_dict, import_code=import_code)
        finally:
            python_runner.log_value = real_log_value
        return msgs.text_of('stderr')

    _SOURCE = ("import re\n"
               "\n"
               "def f():\n"
               "    s = \"abc\"\n"
               "    s_strings = re.findall(re.escape(r), s)\n"
               "\n"
               "f()\n")

    def test_the_runner_is_nowhere_in_it(self):
        stderr = self._stderr(self._SOURCE)
        self.assertNotIn('python_runner.py', stderr)
        self.assertNotIn('exec(code_object', stderr)

    def test_the_users_own_frames_are_still_there(self):
        stderr = self._stderr(self._SOURCE)
        self.assertIn('Traceback (most recent call last):', stderr)
        self.assertIn('line 7, in <module>', stderr)
        self.assertIn('line 5, in f', stderr)
        self.assertIn("NameError: name 'r' is not defined", stderr)

    def test_the_exec_scaffolding_name_is_gone(self):
        self.assertNotIn('<string>', self._stderr(self._SOURCE))


class TestFutureFlags(unittest.TestCase):
    """`from __future__ import ...` lands in the import half of the split, but
    future statements apply per compilation unit — so the body has to be
    compiled with the flags the imports declared or the feature silently
    doesn't apply to the user's code."""

    def _globals(self):
        return {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda *args, **kwargs: None,
            "_log_and_return": lambda line, value, *args, **kwargs: value,
        }

    def test_body_is_compiled_with_the_declared_future_flags(self):
        import_code, body_code = split_leading_imports("from __future__ import annotations\nx = 1\n")
        flag = __future__.annotations.compiler_flag
        self.assertTrue(import_code.co_flags & flag)
        self.assertTrue(body_code.co_flags & flag)

    def test_body_without_future_imports_gets_no_flags(self):
        _, body_code = split_leading_imports("import re\nx = 1\n")
        self.assertFalse(body_code.co_flags & __future__.annotations.compiler_flag)

    def test_postponed_annotations_actually_take_effect(self):
        """With the flag the annotation is left as a string; without it,
        resolving it raises NameError."""
        source_code = "from __future__ import annotations\ndef f(a: Undefined) -> Undefined:\n    return a\n"
        import_code, body_code = split_leading_imports(source_code)
        globals_dict = self._globals()
        exec(import_code, globals_dict)
        exec(body_code, globals_dict)

        self.assertEqual(globals_dict["f"].__annotations__, {"a": "Undefined", "return": "Undefined"})


class TestBuildNewCodeEdits(unittest.TestCase):
    """The insertion edit's text must carry the correct indentation for the
    location after `line`. When `line` is a block-header (its body is the
    deeper-indented next line), inserted code should match the body indent;
    otherwise it should match `line`'s own indent."""

    def _insert_text(self, source_code, line, expr='s.upper()', name='result'):
        edits = _build_new_code_edits(source_code, line, name, expr)
        # First edit is always the insertion at `line`; any later edits are imports.
        return edits[0]['text']

    def test_top_level_for_header_uses_body_indent(self):
        source = "strings = ['a', 'b']\nfor s in strings:\n    pass\n"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_nested_for_header_uses_body_indent(self):
        source = "def foo():\n    strings = ['a', 'b']\n    for s in strings:\n        pass\n"
        self.assertEqual(self._insert_text(source, line=3), "        result = s.upper()")

    def test_while_header_uses_body_indent(self):
        source = "i = 0\nwhile i < 3:\n    i += 1\n"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_if_header_uses_body_indent(self):
        source = "x = 1\nif x:\n    pass\n"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_def_header_uses_body_indent(self):
        source = "def foo():\n    return 1\n"
        self.assertEqual(self._insert_text(source, line=1), "    result = s.upper()")

    def test_regular_statement_keeps_own_indent(self):
        source = "def foo():\n    x = 1\n    y = 2\n"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_top_level_statement_keeps_zero_indent(self):
        source = "x = 1\ny = 2\n"
        self.assertEqual(self._insert_text(source, line=1), "result = s.upper()")

    def test_last_line_of_body_before_eof_keeps_body_indent(self):
        # Trigger on the last line of a for body with no line below.
        # Lookahead finds no next line; fallback to trigger line's own indent (4).
        source = "for s in strings:\n    x = s.upper()"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_last_line_of_body_before_dedent_keeps_body_indent(self):
        # Trigger on last for-body line; next line is dedented top-level code.
        # Next-line indent (0) is not > trigger indent (4), so stay in the loop.
        source = "for s in strings:\n    x = s.upper()\nprint('done')\n"
        self.assertEqual(self._insert_text(source, line=2), "    result = s.upper()")

    def test_for_with_single_body_statement_no_pass(self):
        # The "for loop with no pass" case: a single real body statement.
        # Iteration-variable visualizer (line=1, the for header) gets body indent.
        source = "for s in strings:\n    x = s.upper()\n"
        self.assertEqual(self._insert_text(source, line=1), "    result = s.upper()")

    def test_deeply_nested_for_header(self):
        # for at indent 8 (inside class method) — body should be 12.
        source = (
            "class C:\n"
            "    def m(self):\n"
            "        for s in strings:\n"
            "            pass\n"
        )
        self.assertEqual(self._insert_text(source, line=3), "            result = s.upper()")

    def test_tab_indentation(self):
        source = "for s in strings:\n\tpass\n"
        self.assertEqual(self._insert_text(source, line=1), "\tresult = s.upper()")

    def test_block_header_followed_by_blank_then_body(self):
        # Blank lines between header and body should be skipped during lookahead.
        source = "for s in strings:\n\n    pass\n"
        self.assertEqual(self._insert_text(source, line=1), "    result = s.upper()")

    def test_no_var_name_uses_bare_expr(self):
        # When no variable name is suggested, the bare expression is inserted
        # with the same indent rules.
        edits = _build_new_code_edits(
            "for s in strings:\n    pass\n", line=1, suggest_var_name=None, expr="s.upper()"
        )
        self.assertEqual(edits[0]['text'], "    s.upper()")


class TestBuildNewCodeEditsAddsBody(unittest.TestCase):
    """Visualizers generate bare headers; insertion supplies the `pass` body
    that makes the statement runnable, at the right depth for its position."""

    def _insert_text(self, source_code, line, expr):
        return _build_new_code_edits(source_code, line, None, expr)[0]['text']

    def test_top_level_header_gets_pass(self):
        source = "xs = [1, 2]\ny = 2\n"
        self.assertEqual(self._insert_text(source, 1, "for item in xs:"),
                         "for item in xs:\n    pass")

    def test_pass_indented_with_surrounding_block(self):
        source = "def f():\n    xs = [1, 2]\n    y = 2\n"
        self.assertEqual(self._insert_text(source, 2, "for item in xs:"),
                         "    for item in xs:\n        pass")

    def test_nested_header_gets_deeper_pass(self):
        source = "xs = [1, 2]\ny = 2\n"
        self.assertEqual(
            self._insert_text(source, 1, "for i, item in enumerate(xs):\n    if item > 1:"),
            "for i, item in enumerate(xs):\n    if item > 1:\n        pass")

    def test_expression_gets_no_body(self):
        source = "xs = [1, 2]\ny = 2\n"
        self.assertEqual(self._insert_text(source, 1, "[x for x in xs]"),
                         "[x for x in xs]")


class TestBuildNewCodeEditsReportsHeaderLines(unittest.TestCase):
    """The editor links the header and leaves the body to the user, so the
    insertion edit says how many of its lines are header."""

    def _edit(self, expr, name=None):
        return _build_new_code_edits("xs = [1, 2]\ny = 2\n", 1, name, expr)[0]

    def test_expression_is_one_line(self):
        self.assertEqual(self._edit("[x for x in xs]", "picked")['headerLines'], 1)

    def test_single_line_header(self):
        self.assertEqual(self._edit("for item in xs:")['headerLines'], 1)

    def test_nested_header_counts_both_lines(self):
        edit = self._edit("for i, item in enumerate(xs):\n    if item > 1:")
        self.assertEqual(edit['headerLines'], 2)
        self.assertEqual(len(edit['text'].split('\n')), 3)

    def test_the_generated_line_is_the_only_edit(self):
        # Whatever else the code needs -- an import it can't run without -- is
        # the editor's to place, since only the editor knows the file as it
        # stands now.
        edits = _build_new_code_edits("xs = [1, 2]\n", 1, "found",
                                      "re.findall(r'a', s)")
        self.assertEqual(len(edits), 1)


class TestNewCodeConfig(unittest.TestCase):
    """A visualizer can send the columns a new line opens with: they land as
    a `#%click` comment above the statement."""

    def test_the_comment_goes_in_above_the_statement(self):
        edits = _build_new_code_edits("xs = [1, 2]\n", 1, "grouped", "group(xs)",
                                      config=['$k', 'len($v)'])
        self.assertEqual(edits, [{
            'type': 'insert', 'afterLine': 1,
            'text': format_config_comment(['$k', 'len($v)']) + '\ngrouped = group(xs)',
            'headerLines': 1, 'leadingLines': 1}])

    def test_the_comment_takes_the_statements_indentation(self):
        edits = _build_new_code_edits("if True:\n    xs = [1]\n", 2, "g", "f(xs)",
                                      config=['$'])
        self.assertEqual(edits[0]['text'].split('\n')[0],
                         '    ' + format_config_comment(['$']))

    def test_no_config_means_no_comment(self):
        edits = _build_new_code_edits("xs = [1]\n", 1, "g", "f(xs)")
        self.assertNotIn('leadingLines', edits[0])
        self.assertEqual(edits[0]['text'], 'g = f(xs)')

    def test_the_command_carries_it_out(self):
        dicts = _commands_to_dicts([('g', 'f(xs)', (), ['$'])], line=1,
                                   idx_in_line=0, model=None, source_code="xs = [1]\n")
        self.assertEqual(dicts[0]['edits'][0]['leadingLines'], 1)
        self.assertEqual(dicts[0]['imports'], [])


class TestNewCodeImports(unittest.TestCase):
    """A visualizer says what its code needs imported. The runner carries that
    declaration out on the wire; it never reads the code to guess, and it never
    decides whether the file already has it."""

    def _dicts(self, command, source_code="s = 'a'\n"):
        return _commands_to_dicts([command], line=1, idx_in_line=0, model=None,
                                  source_code=source_code)

    def test_a_command_carries_what_it_declared(self):
        dicts = self._dicts(('found', "re.findall(r'a', s)", ('import re',)))
        self.assertEqual(dicts[0]['imports'], ['import re'])

    def test_a_command_declaring_nothing_needs_nothing(self):
        self.assertEqual(self._dicts(('picked', 'xs[1:]'))[0]['imports'], [])

    def test_the_runner_reads_the_declaration_and_not_the_code(self):
        # `re.` in the text says nothing on its own: the visualizer that wrote
        # it is what knows whether the module is really being used.
        dicts = self._dicts(('found', "re.findall(r'a', s)"))
        self.assertEqual(dicts[0]['imports'], [])
        self.assertEqual(len(dicts[0]['edits']), 1)

    def test_an_import_with_no_line_under_it_is_still_new_code(self):
        # A nested action keeps its code in the visualizer rather than the
        # file, so there is nothing to insert -- but the file still has to be
        # able to run it. The import is the whole edit.
        dicts = self._dicts(AddImports(imports=('import re',)))
        self.assertEqual(dicts[0]['type'], 'NewCode')
        self.assertEqual(dicts[0]['edits'], [])
        self.assertEqual(dicts[0]['imports'], ['import re'])
        self.assertEqual(dicts[0]['triggerLine'], 1)

    def test_an_import_command_with_nothing_to_add_is_not_sent(self):
        self.assertEqual(self._dicts(AddImports(imports=())), [])


@dataclass
class _FakeChangeCmd:
    """Stand-in for a dataclass command (e.g. ChangeSelectedText)."""
    expression: str
    suggested_var_name: Optional[str] = None


class TestCommandsToDicts(unittest.TestCase):
    """`_commands_to_dicts` converts visualizer commands to wire dicts."""

    def test_newcode_dedups_without_storing_concrete_name_in_model(self):
        # Source already binds str1, so a fresh `str1 = ...` must become `str2`.
        source = "str1 = open('f').read()\nstr1 = str1.upper()\n"
        model = {'linked_action': 'find_or_map'}
        dicts = _commands_to_dicts(
            [('str1', "str1.replace('a', 'b')")],
            line=2, idx_in_line=0, model=model, source_code=source,
        )
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]['type'], 'NewCode')
        # The inserted line uses the de-duplicated name.
        self.assertEqual(dicts[0]['edits'][0]['text'], "str2 = str1.replace('a', 'b')")
        self.assertNotIn('linked_prefix', model)

    def test_newcode_increments_past_existing_generated_names(self):
        # str1 and str2 already present -> next available is str3.
        source = "str1 = 'x'\nstr2 = 'y'\n"
        model = {'linked_action': 'find_or_map'}
        dicts = _commands_to_dicts(
            [('str1', "str1 + str2")],
            line=2, idx_in_line=0, model=model, source_code=source,
        )
        self.assertEqual(dicts[0]['edits'][0]['text'], "str3 = str1 + str2")
        self.assertNotIn('linked_prefix', model)

    def test_newcode_no_var_name_leaves_model_untouched(self):
        # Bare-expression insert (no assignment) must not touch linked_prefix.
        model = {'linked_action': 'loop'}
        dicts = _commands_to_dicts(
            [(None, "print(x)")],
            line=1, idx_in_line=0, model=model, source_code="x = 1\n",
        )
        self.assertEqual(dicts[0]['edits'][0]['text'], "print(x)")
        self.assertNotIn('linked_prefix', model)

    def test_dataclass_command_gets_trigger_identity(self):
        # Non-tuple commands must carry the emitting visualizer's identity so
        # the editor can route the update to that visualizer's own linked line.
        dicts = _commands_to_dicts(
            [_FakeChangeCmd(
                expression="str1.upper()",
                suggested_var_name='str2_upper',
            )],
            line=5, idx_in_line=1, model=None, source_code="",
        )
        self.assertEqual(len(dicts), 1)
        cmd = dicts[0]
        self.assertEqual(cmd['type'], '_FakeChangeCmd')
        self.assertEqual(cmd['expression'], "str1.upper()")
        self.assertEqual(cmd['suggested_var_name'], 'str2_upper')
        self.assertEqual(cmd['triggerLine'], 5)
        self.assertEqual(cmd['triggerVisIndex'], 1)


class _StaticVisStub:
    """Minimal static visualizer module: visualize(value) -> str."""
    def can_visualize(self, value):
        return True

    def visualize(self, value):
        return f'<b>{value}</b>'


class TestLogValueForwardsVarAndExp(unittest.TestCase):
    """log_value must pass var_and_exp into visualize so top-level generic
    values (e.g. stop_idx = 33) get an snc-py-exps drag handle. A generic
    visualizer has no interactions in either size, so its whole area is the
    handle; the interactive visualizers self-wrap only when small."""

    def _log_html(self, value, var_and_exp=None, focused_line=None):
        buf = io.StringIO()
        old_out = python_runner._stream_out
        old_counter = python_runner._run_models
        old_models = python_runner.models_and_events
        old_focused = python_runner._focused_line
        try:
            python_runner._stream_out = buf
            python_runner._run_models = {}
            python_runner.models_and_events = []
            python_runner._focused_line = focused_line
            log_value(1, value, var_and_exp=var_and_exp)
        finally:
            python_runner._stream_out = old_out
            python_runner._run_models = old_counter
            python_runner.models_and_events = old_models
            python_runner._focused_line = old_focused

        msgs = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        return next(m['item'] for m in msgs if m.get('type') == 'item')['html']

    def test_log_value_generic_int_emits_snc_py_exp(self):
        html_out = self._log_html(33, var_and_exp=('stop_idx', 'stop_idx'))
        self.assertIn(exp_attr('stop_idx'), html_out)
        self.assertIn('draggable="true"', html_out)
        self.assertIn('class="py-exp-grab"', html_out)
        self.assertIn('33', html_out)

    def test_log_value_generic_int_emits_snc_py_exp_when_small(self):
        # Another line is focused, so line 1 renders small.
        html_out = self._log_html(33, var_and_exp=('stop_idx', 'stop_idx'), focused_line=2)
        self.assertIn(exp_attr('stop_idx'), html_out)
        self.assertIn('class="py-exp-grab"', html_out)

    def test_log_value_without_var_and_exp_has_no_snc_py_exp(self):
        html_out = self._log_html(33)
        self.assertNotIn('snc-py-exps', html_out)
        self.assertIn('33', html_out)


class TestGenericVisualizerDrag(unittest.TestCase):
    """The generic/static visualizers should wrap their output in a draggable
    snc-py-exps grab span when given an access-path expression via var_and_exp,
    so nested (non-interactive) values are draggable to extract."""

    def test_generic_wraps_with_py_exp_when_var_and_exp_given(self):
        out = GenericVisualizer.visualize(
            42, None, None, None, var_and_exp=(None, 'x[0]'))
        self.assertIn(exp_attr('x[0]'), out)
        self.assertIn('draggable="true"', out)
        self.assertIn('class="py-exp-grab"', out)
        self.assertIn('42', out)

    def test_generic_no_wrap_without_var_and_exp(self):
        out = GenericVisualizer.visualize(42, None, None, None)
        self.assertNotIn('snc-py-exps', out)
        self.assertNotIn('py-exp-grab', out)
        self.assertEqual(out, '<span class="snc-generic-visualizer">42</span>')

    def test_generic_wraps_in_small_mode_too(self):
        out = GenericVisualizer.visualize(
            42, None, None, None, small=True, var_and_exp=(None, 'x[0]'))
        self.assertIn(exp_attr('x[0]'), out)
        self.assertIn('class="py-exp-grab"', out)

    def test_generic_escapes_expression_and_value(self):
        out = GenericVisualizer.visualize(
            '<a>', None, None, None, var_and_exp=(None, 'd["<k>"]'))
        # Expression is HTML-escaped inside the attribute.
        self.assertIn(exp_attr('d["<k>"]'), out)
        # repr value is escaped (note repr adds quotes).
        self.assertIn('&lt;a&gt;', out)
        self.assertNotIn('<a>', out)

    def test_static_visualizer_wraps_with_py_exp(self):
        vis = VisualizerOfStaticVisualizer(_StaticVisStub())
        out = vis.visualize(7, None, None, None, var_and_exp=(None, 'items[2]'))
        self.assertIn(exp_attr('items[2]'), out)
        self.assertIn('draggable="true"', out)
        self.assertIn('class="py-exp-grab"', out)
        # Inner static-visualizer output is preserved.
        self.assertIn('<b>7</b>', out)

    def test_static_visualizer_no_wrap_without_var_and_exp(self):
        vis = VisualizerOfStaticVisualizer(_StaticVisStub())
        out = vis.visualize(7, None, None, None)
        self.assertNotIn('snc-py-exps', out)
        self.assertEqual(out, '<b>7</b>')


class TestUrlCacheAcrossRuns(unittest.TestCase):
    """The network read cache has to see through the source transform: the
    logging wrappers must not hide the user's line from the cache key."""

    def setUp(self):
        self.fetches = []

        def fake_urlopen(url, *args, **kwargs):
            self.fetches.append(url)
            return io.BytesIO(b'weather report')

        original = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(urllib.request, 'urlopen', original))

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        python_runner._file_path = os.path.join(tmp.name, 'weather.py')
        self.addCleanup(lambda: setattr(python_runner, '_file_path', ''))
        self.addCleanup(lambda: setattr(python_runner, '_source_code', ''))

        self.addCleanup(install_url_cache())
        self.assertIsNot(urllib.request.urlopen, fake_urlopen, 'cache did not install')

    def _run(self, source_code):
        """Transform and execute source_code the way a worker run does."""
        python_runner._source_code = source_code
        code_object = compile(transform_code_to_ast(source_code), filename='<string>', mode='exec')
        globals_dict = {
            '__name__': '__main__',
            '__file__': '<string>',
            '_log_value': lambda *a, **k: None,
            '_log_and_return': lambda line, value, *a, **k: value,
        }
        exec(code_object, globals_dict)
        return globals_dict

    def test_rerunning_unchanged_code_does_not_refetch(self):
        source = (
            'import urllib.request\n'
            'str1 = urllib.request.urlopen("https://example.com/report.txt").read().decode()\n'
        )
        self.assertEqual(self._run(source)['str1'], 'weather report')
        self.assertEqual(self._run(source)['str1'], 'weather report')
        self.assertEqual(len(self.fetches), 1)

    def test_editing_the_line_does_not_refetch(self):
        # The entry is keyed on the URL alone, so edits elsewhere on the line
        # leave it valid.
        source = (
            'import urllib.request\n'
            'str1 = urllib.request.urlopen("https://example.com/report.txt").read().decode()\n'
        )
        self._run(source)
        edited = source.replace('str1', 'text')
        self.assertEqual(self._run(edited)['text'], 'weather report')
        self.assertEqual(len(self.fetches), 1)

    def test_the_cache_lands_beside_the_edited_file(self):
        self._run('import urllib.request\n'
                  'str1 = urllib.request.urlopen("https://example.com/report.txt").read()\n')
        cache_dir = os.path.join(os.path.dirname(python_runner._file_path), url_cache.CACHE_DIR_NAME)
        self.assertTrue(any(f.endswith('.body') for f in os.listdir(cache_dir)))




class TestSourceSpan(unittest.TestCase):
    """Where the expression a visualizer is showing sits in the source, so a
    visualizer that can rewrite it (the list visualizer's Sort) has something
    exact to rewrite. Only the sites where the visualized value IS an
    expression written on the line hand one over."""

    def spans(self, source_code):
        """{line: source_span} for every _log_value the transform emits."""
        spans = {}

        def record(line, value, site=0, eval_in_scope=None, var_and_exp=None,
                   source_span=None):
            spans[line] = source_span

        globals_dict = {
            **python_runner._runtime_hooks(),
            '__name__': '__main__',
            '_log_value': record,
            '_log_and_return': (lambda line, value, *a, **k: value),
        }
        exec(compile(transform_code_to_ast(source_code), '<test>', 'exec'),
             globals_dict)
        return spans

    def text_at(self, source_code, span):
        return python_runner._span_text(span)[0]

    def test_an_assignments_right_hand_side_is_rewritable(self):
        source = 'data = [3, 1, 2]\n'
        span = self.spans(source)[1]
        self.assertEqual(span, (1, 7, 1, 16))

    def test_a_bare_expression_statement_is(self):
        self.assertEqual(self.spans('[3, 1, 2]\n')[1], (1, 0, 1, 9))

    def test_a_return_covers_the_value_and_not_the_keyword(self):
        source = 'def f():\n    return [3, 1, 2]\nf()\n'
        self.assertEqual(self.spans(source)[2], (2, 11, 2, 20))

    def test_a_multi_line_expression_spans_to_its_end(self):
        source = 'data = [\n    3,\n    1,\n]\n'
        self.assertEqual(self.spans(source)[1], (1, 7, 4, 1))

    def test_a_loop_variable_has_no_expression_to_rewrite(self):
        # It is bound by the statement rather than written on it.
        source = 'rows = [[1], [2]]\nfor row in rows:\n    pass\n'
        self.assertIsNone(self.spans(source)[2])

    def test_an_augmented_assignment_has_none(self):
        # `node.value` there is the increment, not the visualized value.
        source = 'x = 1\nx += 2\n'
        self.assertIsNone(self.spans(source)[2])

    def test_an_if_test_has_none(self):
        # Nothing is rebound, so a rewrite would change nothing downstream.
        source = 'xs = [1]\nif xs:\n    pass\n'
        self.assertIsNone(self.spans(source)[2])

    def test_a_tuple_target_assignment_has_none(self):
        # No one of its names holds the value logged for the line.
        self.assertIsNone(self.spans('a, b = 1, 2\n')[1])


class TestSpanText(unittest.TestCase):
    """The span with the text it covers put in front of it."""

    def setUp(self):
        self.old_source = python_runner._source_code

    def tearDown(self):
        python_runner._source_code = self.old_source

    def text(self, source_code, span):
        python_runner._source_code = source_code
        got = python_runner._span_text(span)
        return got if got is None else got[0]

    def test_it_reads_the_expression_off_the_line(self):
        self.assertEqual(self.text('data = [3, 1, 2]\n', (1, 7, 1, 16)),
                         '[3, 1, 2]')

    def test_a_multi_line_expression_comes_back_whole(self):
        self.assertEqual(self.text('data = [\n    3,\n]\n', (1, 7, 3, 1)),
                         '[\n    3,\n]')

    def test_the_span_rides_along_unchanged(self):
        python_runner._source_code = 'data = [3, 1, 2]\n'
        self.assertEqual(python_runner._span_text((1, 7, 1, 16)),
                         ('[3, 1, 2]', 1, 7, 1, 16))

    def test_offsets_count_utf8_bytes_the_way_the_parser_does(self):
        # An accented name ahead of the expression pushes the byte offset past
        # the character one; slicing in characters would cut mid-expression.
        import ast
        source = 'café = [3, 1, 2]\n'
        span = ast.parse(source).body[0].value
        self.assertEqual(
            self.text(source, (span.lineno, span.col_offset,
                               span.end_lineno, span.end_col_offset)),
            '[3, 1, 2]')

    def test_nothing_to_read_reads_nothing(self):
        self.assertIsNone(self.text('data = 1\n', None))

    def test_a_line_that_is_no_longer_there_reads_nothing(self):
        self.assertIsNone(self.text('data = 1\n', (99, 0, 99, 3)))


class TestSourceSig(unittest.TestCase):
    """What counts as the same source for reusing a cached model."""

    class _Plain:
        pass

    class _Canonical:
        @staticmethod
        def canonical_source_expr(expr):
            return expr.removeprefix('sorted(').removesuffix(')')

    def test_a_visualizer_with_nothing_to_say_keeps_the_expression(self):
        self.assertEqual(
            python_runner._source_sig(self._Plain(), (None, 'sorted(xs)')),
            [None, 'sorted(xs)'])

    def test_one_that_rewrites_its_own_line_says_which_part_is_incidental(self):
        self.assertEqual(
            python_runner._source_sig(self._Canonical(), (None, 'sorted(xs)')),
            [None, 'xs'])

    def test_a_rename_is_still_a_different_source(self):
        self.assertNotEqual(
            python_runner._source_sig(self._Canonical(), ('x', 'x')),
            python_runner._source_sig(self._Canonical(), ('y', 'y')))

    def test_no_expression_at_all_signs_as_nothing(self):
        self.assertIsNone(python_runner._source_sig(self._Plain(), None))


class TestSourceSpanReachesTheVisualizer(unittest.TestCase):
    """Offered to the visualizers that name the parameter, and to no others."""

    class _Wants:
        def can_visualize(self, value):
            return True

        def init_model(self, value, get_visualizer, eval_in_scope=None,
                       var_and_exp=None):
            return {}

        def visualize(self, value, model, get_visualizer, eval_in_scope,
                      max_width=None, max_height=None, small=False,
                      var_and_exp=None, source_span=None):
            return f'<i>{source_span}</i>'

    class _DoesNot:
        def can_visualize(self, value):
            return True

        def init_model(self, value, get_visualizer, eval_in_scope=None,
                       var_and_exp=None):
            return {}

        def visualize(self, value, model, get_visualizer, eval_in_scope,
                      max_width=None, max_height=None, small=False,
                      var_and_exp=None):
            return '<i>no span asked for</i>'

    def html(self, vis, source_span):
        buf = io.StringIO()
        saved = (python_runner._stream_out, python_runner._run_models,
                 python_runner.models_and_events, python_runner._source_code,
                 python_runner._visualizers)
        try:
            python_runner._stream_out = buf
            python_runner._run_models = {}
            python_runner.models_and_events = []
            python_runner._source_code = 'data = [3, 1, 2]\n'
            python_runner._visualizers = lambda: [vis]
            log_value(1, [3, 1, 2], var_and_exp=('data', 'data'),
                      source_span=source_span)
        finally:
            (python_runner._stream_out, python_runner._run_models,
             python_runner.models_and_events, python_runner._source_code,
             python_runner._visualizers) = saved
        msgs = [json.loads(line) for line in buf.getvalue().splitlines()
                if line.strip()]
        return next(m['item'] for m in msgs if m.get('type') == 'item')['html']

    def test_one_that_asks_is_handed_the_text_and_the_span(self):
        self.assertIn("('[3, 1, 2]', 1, 7, 1, 16)",
                      self.html(self._Wants(), (1, 7, 1, 16)))

    def test_a_site_with_nothing_to_rewrite_hands_over_nothing(self):
        self.assertIn('None', self.html(self._Wants(), None))

    def test_one_that_does_not_ask_still_renders(self):
        self.assertIn('no span asked for',
                      self.html(self._DoesNot(), (1, 7, 1, 16)))


class TestConfigComment(unittest.TestCase):
    """A visualizer's saved config lives in a `#%click` comment above its line.
    The runner reads it for the visualizer and, when the visualizer saves,
    asks the editor to rewrite it."""

    class _Vis:
        """Is handed its config at init; saves on any event."""

        def can_visualize(self, value):
            return True

        def init_model(self, value, get_visualizer, eval_in_scope=None,
                       var_and_exp=None, slots_config=None, config_path=None):
            return {'loaded': slots_config, 'path': config_path, 'inits': 1}

        def update(self, event, var_and_exp, model, value, get_visualizer=None,
                   eval_in_scope=None):
            save_slots_at_path([], ['$.x'])
            return model, []

        def visualize(self, value, model, get_visualizer, eval_in_scope,
                      max_width=None, max_height=None, small=False,
                      var_and_exp=None):
            return '<i>vis</i>'

    def _log(self, source, line, models_and_events=None):
        buf = io.StringIO()
        saved = (python_runner._stream_out, python_runner._run_models,
                 python_runner.models_and_events, python_runner._source_code,
                 python_runner._visualizers)
        try:
            python_runner._stream_out = buf
            python_runner._run_models = {}
            python_runner.models_and_events = models_and_events or []
            python_runner._source_code = source
            python_runner._visualizers = lambda: [self._Vis()]
            log_value(line, [1], var_and_exp=('xs', 'xs'))
        finally:
            (python_runner._stream_out, python_runner._run_models,
             python_runner.models_and_events, python_runner._source_code,
             python_runner._visualizers) = saved
        msgs = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        self._last_msgs = msgs
        item = next(m['item'] for m in msgs if m.get('type') == 'item')
        cmds = item.get('commands', [])
        return item, cmds

    SRC = '#%click ["$.a"]\nxs = [1]\n'

    def test_the_comment_is_the_visualizers_config(self):
        item, cmds = self._log(self.SRC, 2)
        self.assertEqual(item['model']['loaded'], ['$.a'])
        self.assertEqual(item['model']['path'], [])
        self.assertEqual(item['model']['_config_sig'], config_sig(['$.a']))
        self.assertEqual(cmds, [])

    def test_a_line_with_no_comment_has_no_config(self):
        item, cmds = self._log('xs = [1]\n', 1)
        self.assertIsNone(item['model']['loaded'])
        self.assertEqual(item['model']['_config_sig'], config_sig(None))
        self.assertEqual(cmds, [])

    def test_a_save_asks_the_editor_to_rewrite_the_comment(self):
        item, _ = self._log(self.SRC, 2)
        cached = {'line': 2, 'visIndex': 0, 'model': item['model'],
                  'events': [{'pythonEventStr': 'X', 'eventJSON': {}}]}
        item, cmds = self._log(self.SRC, 2, [cached])
        expected = [{'expr': '$.x'}]
        self.assertEqual(cmds, [{
            'type': 'SetConfigComment',
            'comment': format_config_comment(expected),
            'triggerLine': 2, 'triggerVisIndex': 0}])
        # The model already reflects what the comment will say.
        self.assertEqual(item['model']['_config_sig'], config_sig(expected))

    def test_commands_ride_on_the_item_that_answered_the_event(self):
        # One message, not two: the item retires the event from the editor's
        # queue, and a run superseded between an item and a trailing command
        # message would lose the command with the event already retired.
        item, _ = self._log(self.SRC, 2)
        cached = {'line': 2, 'visIndex': 0, 'model': item['model'],
                  'events': [{'id': 7, 'pythonEventStr': 'X', 'eventJSON': {}}]}
        item, cmds = self._log(self.SRC, 2, [cached])
        self.assertEqual([m['type'] for m in self._last_msgs], ['item'])
        self.assertEqual(item['handledEventIds'], [7])
        self.assertEqual([c['type'] for c in cmds], ['SetConfigComment'])

    def test_a_model_survives_a_rerun_while_the_comment_is_what_it_reflects(self):
        item, _ = self._log(self.SRC, 2)
        model = dict(item['model'], inits=2)
        cached = {'line': 2, 'visIndex': 0, 'model': model}
        item, _ = self._log(self.SRC, 2, [cached])
        self.assertEqual(item['model']['inits'], 2)

    def test_a_hand_edited_comment_rebuilds_the_model(self):
        item, _ = self._log(self.SRC, 2)
        model = dict(item['model'], inits=2)
        cached = {'line': 2, 'visIndex': 0, 'model': model}
        edited = '#%click ["$.b"]\nxs = [1]\n'
        item, _ = self._log(edited, 2, [cached])
        self.assertEqual(item['model']['inits'], 1)
        self.assertEqual(item['model']['loaded'], ['$.b'])

    def test_the_config_does_not_leak_to_the_next_line(self):
        src = '#%click ["$.a"]\nxs = [1]\nys = [2]\n'
        item, _ = self._log(src, 3)
        self.assertIsNone(item['model']['loaded'])


class TestProgramIO(unittest.TestCase):
    """The user program's stdout/stderr stream to the editor, and its stdin is
    replayed from the console document rather than read from a live pipe."""

    def _globals(self, logged):
        return {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
            "_log_and_return": lambda line, value, *a, **k: (logged.append((line, value)), value)[1],
        }

    def _run(self, source_code, stdin_text='', stdin_eof=True, **kwargs):
        """Run through the checkpoint 1 path; returns (result, messages, logged)."""
        logged = []
        import_code, body_code = split_leading_imports(source_code)
        real_log_value = python_runner.log_value
        python_runner.log_value = lambda line, value, *a, **k: logged.append((line, value))
        try:
            with capture_stream_messages() as msgs:
                result = execute_code(body_code, self._globals(logged), import_code=import_code,
                                      stdin_text=stdin_text, stdin_eof=stdin_eof, **kwargs)
        finally:
            python_runner.log_value = real_log_value
        return result, msgs, logged

    def test_print_reaches_the_editor_as_a_stdout_chunk(self):
        _, msgs, _ = self._run("print('hi')\n")
        self.assertEqual(msgs.text_of('stdout'), 'hi\n')

    def test_the_result_no_longer_carries_the_output(self):
        # It streams instead; leaving a copy in the result would double-render.
        result, _, _ = self._run("print('hi')\n")
        self.assertEqual(result["stdout"], '')
        self.assertEqual(result["stderr"], '')

    def test_input_is_replayed_from_the_recorded_stdin(self):
        _, _, logged = self._run("name = input('Name? ')\n", stdin_text='Brian\n')
        self.assertIn('Brian', [value for _, value in logged])

    def test_prompts_and_output_carry_the_offset_they_were_written_at(self):
        _, msgs, _ = self._run(
            "a = input('Name? ')\nb = input('Age? ')\nprint('hi', a, b)\n",
            stdin_text='Brian\n30\n')
        self.assertEqual(msgs.output(), [
            ('stdout', 'Name? ', 0),
            ('stdout', 'Age? ', 6),
            ('stdout', 'hi Brian 30\n', 9),
        ])

    def test_the_result_reports_how_much_stdin_was_consumed(self):
        result, _, _ = self._run("input()\n", stdin_text='Brian\n30\n')
        self.assertEqual(result["stdinConsumed"], 6)

    def test_stderr_is_tagged_separately_from_stdout(self):
        _, msgs, _ = self._run("import sys\nprint('out')\nprint('err', file=sys.stderr)\n")
        self.assertEqual(msgs.text_of('stdout'), 'out\n')
        self.assertEqual(msgs.text_of('stderr'), 'err\n')

    def test_output_interleaves_across_the_two_streams(self):
        _, msgs, _ = self._run(
            "import sys\nprint('a')\nprint('b', file=sys.stderr)\nprint('c')\n")
        self.assertEqual([(stream, text) for stream, text, _ in msgs.output()],
                         [('stdout', 'a\n'), ('stderr', 'b\n'), ('stdout', 'c\n')])


class TestStarvedRuns(unittest.TestCase):
    """A read past the end of an unterminated stdin document ends the run
    waiting for the user, not in an error."""

    _SOURCE = "a = input('Name? ')\nb = 2\n"

    def _run(self, source_code, stdin_text='', stdin_eof=False):
        logged = []
        import_code, body_code = split_leading_imports(source_code)
        globals_dict = {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda line, value, *a, **k: logged.append((line, value)),
            "_log_and_return": lambda line, value, *a, **k: (logged.append((line, value)), value)[1],
        }
        real_log_value = python_runner.log_value
        python_runner.log_value = lambda line, value, *a, **k: logged.append((line, value))
        try:
            with capture_stream_messages() as msgs:
                result = execute_code(body_code, globals_dict, import_code=import_code,
                                      stdin_text=stdin_text, stdin_eof=stdin_eof)
        finally:
            python_runner.log_value = real_log_value
        return result, msgs, logged

    def test_the_run_reports_that_it_is_awaiting_input(self):
        result, _, _ = self._run(self._SOURCE)
        self.assertTrue(result["awaitingInput"])
        self.assertEqual(result["awaitingKind"], 'line')

    def test_waiting_is_not_a_failure(self):
        result, _, _ = self._run(self._SOURCE)
        self.assertEqual(result["exitCode"], 0)
        self.assertFalse(result["syntaxError"])

    def test_no_red_error_item_is_logged(self):
        _, _, logged = self._run(self._SOURCE)
        self.assertEqual([v for _, v in logged if isinstance(v, UncaughtError)], [])

    def test_no_traceback_is_printed(self):
        _, msgs, _ = self._run(self._SOURCE)
        self.assertEqual(msgs.text_of('stderr'), '')

    def test_the_prompt_still_reaches_the_editor(self):
        _, msgs, _ = self._run(self._SOURCE)
        self.assertEqual(msgs.text_of('stdout'), 'Name? ')

    def test_statements_after_the_starved_read_do_not_run(self):
        _, _, logged = self._run(self._SOURCE)
        self.assertNotIn(2, [value for _, value in logged])

    def test_earlier_statements_still_visualize(self):
        _, _, logged = self._run("x = 1\ny = input()\n")
        self.assertIn(1, [value for _, value in logged])

    def test_a_read_to_end_of_stream_asks_for_eof(self):
        result, _, _ = self._run("import sys\ntext = sys.stdin.read()\n", stdin_text='a\n')
        self.assertEqual(result["awaitingKind"], 'eof')

    def test_ending_the_stream_lets_a_read_to_end_complete(self):
        result, _, logged = self._run("import sys\ntext = sys.stdin.read()\n",
                                      stdin_text='a\n', stdin_eof=True)
        self.assertNotIn("awaitingInput", result)
        self.assertIn('a\n', [value for _, value in logged])

    def test_a_user_except_exception_cannot_swallow_the_wait(self):
        result, _, _ = self._run("try:\n    a = input()\nexcept Exception:\n    a = 'swallowed'\n")
        self.assertTrue(result["awaitingInput"])

    def test_reading_past_a_stream_that_did_end_is_an_ordinary_eof_error(self):
        # Once the user marks the end, `input()` failing is the program's bug
        # and belongs in red like any other exception.
        result, _, logged = self._run("a = input()\n", stdin_text='', stdin_eof=True)
        self.assertNotIn("awaitingInput", result)
        self.assertEqual(result["exitCode"], 1)
        self.assertTrue(any(isinstance(v, UncaughtError) and isinstance(v.exception, EOFError)
                            for _, v in logged))


class TestCheckpointsAgreeOnOutput(unittest.TestCase):
    """A file whose imports print must look the same whichever pool served it.

    Checkpoint 2 runs the imports during pre-warm, before there's a run to
    attribute their output to, so it holds the chunks and replays them ahead of
    the body's. The module below prints when it is imported, which is the only
    way to get output out of the import phase.
    """

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.mkdtemp()
        pathlib.Path(cls._dir, 'snc_noisy_import.py').write_text("print('from imports')\n")
        sys.path.insert(0, cls._dir)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls._dir)

    _SOURCE = "import snc_noisy_import\nprint('from body')\n"

    def setUp(self):
        # Each run has to import for real; a cached module wouldn't print again.
        sys.modules.pop('snc_noisy_import', None)

    def _globals(self):
        return {
            "__name__": "__main__",
            "__file__": "<string>",
            "_log_value": lambda line, value, *a, **k: None,
            "_log_and_return": lambda line, value, *a, **k: value,
        }

    def _checkpoint1(self):
        import_code, body_code = split_leading_imports(self._SOURCE)
        with capture_stream_messages() as msgs:
            execute_code(body_code, self._globals(), import_code=import_code)
        return msgs.output()

    def _checkpoint2(self):
        import_code, body_code = split_leading_imports(self._SOURCE)
        globals_dict = self._globals()
        held = []
        import_streams = std_streams.StdStreams('', True, lambda *chunk: held.append(chunk))
        with import_streams.installed():
            exec(import_code, globals_dict)
        with capture_stream_messages() as msgs:
            execute_code(body_code, globals_dict, replay_output=held)
        return msgs.output()

    def test_the_import_really_does_print(self):
        # Guards the fixture: without this the two paths could agree trivially.
        self.assertIn('from imports', ''.join(t for _, t, _ in self._checkpoint1()))

    def test_import_output_is_not_dropped_by_checkpoint_2(self):
        self.assertIn('from imports', ''.join(t for _, t, _ in self._checkpoint2()))

    def test_both_checkpoints_produce_the_same_transcript(self):
        first = ''.join(t for _, t, _ in self._checkpoint1())
        self.setUp()
        self.assertEqual(first, ''.join(t for _, t, _ in self._checkpoint2()))


class TestImportsMatch(unittest.TestCase):
    """Whether a worker warmed with one program's imports may serve another.
    Editing a line of the body is the common case and must stay a match --
    that is the whole reason a warmed worker survives a keystroke."""

    def test_a_body_edit_is_a_match(self):
        self.assertTrue(imports_match("import re\nx = 1\n", "import re\nx = 2\n"))

    def test_a_body_edit_that_adds_lines_is_a_match(self):
        self.assertTrue(imports_match("import re\nx = 1\n", "import re\nx = 1\ny = x + 1\n"))

    def test_an_added_import_is_not_a_match(self):
        self.assertFalse(imports_match("import re\nx = 1\n", "import re\nimport os\nx = 1\n"))

    def test_a_removed_import_is_not_a_match(self):
        self.assertFalse(imports_match("import re\nimport os\nx = 1\n", "import re\nx = 1\n"))

    def test_a_renamed_alias_is_not_a_match(self):
        self.assertFalse(imports_match("import re as r\nx = 1\n", "import re as e\nx = 1\n"))

    def test_a_from_import_is_compared_by_what_it_binds(self):
        self.assertFalse(imports_match("from os import path\n", "from os import sep\n"))
        self.assertTrue(imports_match("from os import path\nx = 1\n", "from os import path\nx = 2\n"))

    def test_comments_and_blank_lines_among_the_imports_do_not_count(self):
        # Nothing executable changed, so the warmed globals are still correct.
        self.assertTrue(imports_match(
            "import re\nimport os\nx = 1\n",
            "import re\n# pull in the os module\n\nimport os\nx = 1\n"))

    def test_an_import_below_the_body_is_not_part_of_the_prefix(self):
        # Only leading imports are pre-executed, so a later one is body code
        # and editing around it must not invalidate the worker.
        self.assertTrue(imports_match(
            "import re\nx = 1\nimport os\n", "import re\nx = 2\nimport os\n"))

    def test_a_changed_module_docstring_is_not_a_match(self):
        # The docstring is executed in the import half, so it has to agree.
        self.assertFalse(imports_match('"""one"""\nimport re\n', '"""two"""\nimport re\n'))

    def test_unparseable_code_never_matches(self):
        # The caller should go report the syntax error, not reuse globals.
        self.assertFalse(imports_match("import re\nx = 1\n", "import re\nx = (\n"))
        self.assertFalse(imports_match("import re\nx = (\n", "import re\nx = (\n"))


class TestPoolWorkerCheckpoint2(unittest.TestCase):
    """A checkpoint 2 worker pre-executes one program's imports, then is asked
    to run whatever the editor has by the time a run arrives. It may reuse the
    warmed globals only when the edit left the leading imports alone."""

    _RUNNER = os.path.join(os.path.dirname(os.path.abspath(python_runner.__file__)), 'python_runner.py')

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.mkdtemp()
        pathlib.Path(cls._dir, 'snc_chatty_import.py').write_text("print('from imports')\n")

    def _worker(self):
        env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONHASHSEED': '1234567'}
        env['PYTHONPATH'] = self._dir + os.pathsep + env.get('PYTHONPATH', '')
        return subprocess.Popen(
            [sys.executable, self._RUNNER, '--pool-worker', os.getcwd()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, text=True)

    def _messages_until(self, proc, done):
        """Yield the worker's messages until `done` says one ends the phase."""
        collected = []
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            collected.append(msg)
            if done(msg):
                return collected
        self.fail(f'worker exited early; got {collected}')

    def _warm_then_run(self, warm_code, run_code):
        """Warm a worker on warm_code's imports, then hand it run_code.

        Returns (stdout_text, end_result).
        """
        proc = self._worker()
        try:
            self._messages_until(proc, lambda m: m.get('type') == 'checkpoint_ready' and m.get('checkpoint') == 1)
            proc.stdin.write(json.dumps({'type': 'init_imports', 'code': warm_code}) + '\n')
            proc.stdin.flush()
            self._messages_until(proc, lambda m: m.get('type') == 'checkpoint_ready' and m.get('checkpoint') == 2)
            proc.stdin.write(json.dumps({
                'type': 'run', 'run_id': 'r1', 'code': run_code,
                'models_and_events': '', 'stdin': '', 'stdin_eof': True,
            }) + '\n')
            proc.stdin.flush()
            msgs = self._messages_until(proc, lambda m: m.get('type') == 'end')
            text = ''.join(m.get('text', '') for m in msgs if m.get('type') == 'output')
            return text, msgs[-1].get('result')
        finally:
            proc.kill()
            proc.wait()

    def test_unedited_code_still_runs(self):
        text, result = self._warm_then_run("import re\nprint('hello')\n", "import re\nprint('hello')\n")
        self.assertIn('hello', text)
        self.assertEqual(result['exitCode'], 0)

    def test_a_body_edit_runs_the_edited_body(self):
        text, result = self._warm_then_run("import re\nprint('old')\n", "import re\nprint('new')\n")
        self.assertIn('new', text)
        self.assertNotIn('old', text)
        self.assertEqual(result['exitCode'], 0)

    def test_a_body_edit_replays_the_warmed_import_output(self):
        # The import already ran and printed before this run existed; its output
        # still belongs at the top of the transcript.
        text, _ = self._warm_then_run(
            "import snc_chatty_import\nprint('old')\n",
            "import snc_chatty_import\nprint('new')\n")
        self.assertEqual(text, 'from imports\nnew\n')

    def test_an_edited_import_is_executed_for_real(self):
        # `json` is bound by nothing the worker warmed with, so output at all
        # proves the new import ran.
        text, result = self._warm_then_run(
            "import re\nprint('old')\n",
            "import json\nprint(json.dumps([1, 2]))\n")
        self.assertIn('[1, 2]', text)
        self.assertEqual(result['exitCode'], 0)

    def test_an_edited_import_does_not_replay_the_stale_import_output(self):
        # The warmed import printed, but it is not this program's import.
        text, _ = self._warm_then_run(
            "import snc_chatty_import\nprint('a')\n",
            "import os\nprint('b')\n")
        self.assertEqual(text, 'b\n')

    def test_an_edit_that_breaks_the_syntax_reports_it(self):
        _, result = self._warm_then_run("import re\nx = 1\n", "import re\nx = (\n")
        self.assertTrue(result['syntaxError'])
        self.assertEqual(result['exitCode'], 1)


PROBE_VISUALIZER = '''\
"""A visualizer for the checkpoint 3 tests: claims {"kind": "probe"} values,
counts the events replayed onto it, and emits a command for each one."""
from dataclasses import dataclass


@dataclass
class ProbeCommand:
    note: str


def can_visualize(value):
    return isinstance(value, dict) and value.get("kind") == "probe"


def init_model(value, get_visualizer):
    return {"clicks": 0}


def update(ui_event, var_and_exp, model, value, get_visualizer):
    return {"clicks": model["clicks"] + 1}, [ProbeCommand(value.get("name", ""))]


def visualize(value, model, get_visualizer):
    return '<div class="probe">%s:%d</div>' % (value.get("name", ""), model["clicks"])
'''


class TestPoolWorkerCheckpoint3(unittest.TestCase):
    """A checkpoint 3 worker runs the program up to one widget's log site and
    stops there holding its live state, so the run that arrives pays only for
    that visualizer and the tail of the program.

    Pre-pause items are dropped -- the editor already holds identical ones from
    the run that warmed this worker -- but output, loop counts, commands and
    warnings are held and replayed under the arriving run's id, because the
    front-end rebuilds all of those from scratch on every run.
    """

    _RUNNER = os.path.join(os.path.dirname(os.path.abspath(python_runner.__file__)), 'python_runner.py')

    # Five log sites, one per line; (3, 0) is the widget being interacted with.
    PROGRAM = (
        "print('prefix', flush=True)\n"                 # 1
        "a = {'kind': 'probe', 'name': 'a'}\n"          # 2
        "b = {'kind': 'probe', 'name': 'b'}\n"          # 3  <- the target
        "print('tail', flush=True)\n"                   # 4
        "c = {'kind': 'probe', 'name': 'c'}\n"          # 5
    )
    TARGET = (3, 0)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        vis_dir = pathlib.Path(self.dir, '.snc_visualizers')
        vis_dir.mkdir()
        (vis_dir / 'probe_visualizer.py').write_text(PROBE_VISUALIZER)

    # ---- talking to a worker ----------------------------------------------

    def _worker(self):
        """A pool worker whose cwd is this test's directory, so it finds the
        probe visualizer in `.snc_visualizers` and nothing else."""
        env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONHASHSEED': '1234567'}
        proc = subprocess.Popen(
            [sys.executable, self._RUNNER, '--pool-worker', self.dir],
            cwd=self.dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, text=True)
        self.addCleanup(self._stop, proc)
        return proc

    @staticmethod
    def _stop(proc):
        proc.kill()
        proc.wait()

    @staticmethod
    def _send(proc, msg):
        proc.stdin.write(json.dumps(msg) + '\n')
        proc.stdin.flush()

    @staticmethod
    def _messages_until(proc, done):
        """Every message the worker writes up to the one `done` accepts, or up
        to its exit if it never writes one."""
        collected = []
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            collected.append(msg)
            if done(msg):
                break
        return collected

    def _expect(self, proc, done, what):
        msgs = self._messages_until(proc, done)
        if not msgs or not done(msgs[-1]):
            self.fail(f'worker exited before the {what}; got {msgs}')
        return msgs

    @staticmethod
    def _checkpoint(n):
        return lambda m: m.get('type') == 'checkpoint_ready' and m.get('checkpoint') == n

    def _paused(self, msgs):
        return bool(msgs) and self._checkpoint(3)(msgs[-1])

    # ---- the checkpoint 3 handshake ---------------------------------------

    def _warm(self, proc, code, target, before_run=None, **extra):
        """Take a fresh worker to the pause before `target`, and return
        everything it wrote getting there -- which ends in checkpoint_ready(3)
        only if it got there at all."""
        self._expect(proc, self._checkpoint(1), 'first checkpoint')
        if before_run is not None:
            before_run()
        self._send(proc, {'type': 'init_imports', 'code': code})
        self._expect(proc, self._checkpoint(2), 'second checkpoint')
        self._send(proc, {'type': 'init_run', 'code': code, 'file_path': '',
                          'models_and_events': '', 'stdin': '', 'stdin_eof': True,
                          'checkpoint3': {'line': target[0], 'visIndex': target[1]},
                          **extra})
        return self._messages_until(proc, self._checkpoint(3))

    def _warm_then_run(self, code, target, warm=None, **run_extra):
        """Warm to the pause, then hand the paused worker a run.

        Returns (what it wrote while warming, what it wrote for the run).
        """
        proc = self._worker()
        warm_msgs = self._warm(proc, code, target, **(warm or {}))
        if not self._paused(warm_msgs):
            self.fail(f'worker never paused at checkpoint 3; got {warm_msgs}')
        self._send(proc, {'type': 'run', 'run_id': 'r1', 'models_and_events': '', **run_extra})
        return warm_msgs, self._expect(proc, lambda m: m.get('type') == 'end', 'end of the run')

    def _run_at_checkpoint1(self, code):
        """A plain run on a fresh worker -- what the editor does before any
        interaction, and where the models a warm is seeded with come from."""
        proc = self._worker()
        self._expect(proc, self._checkpoint(1), 'first checkpoint')
        self._send(proc, {'type': 'run', 'run_id': 'r0', 'code': code,
                          'models_and_events': '', 'stdin': '', 'stdin_eof': True})
        return self._expect(proc, lambda m: m.get('type') == 'end', 'end of the run')

    @staticmethod
    def _items(msgs):
        return [m['item'] for m in msgs if m.get('type') == 'item']

    @staticmethod
    def _of_type(msgs, kind):
        return [m for m in msgs if m.get('type') == kind]

    def _models_with_event(self, code, widget, event_id):
        """The editor's `models_and_events` after a run, with one event queued
        on `widget`. Real models, so the fingerprint matches and it replays."""
        entries = [{'line': it['line'], 'visIndex': it['visIndex'], 'model': it['model']}
                   for it in self._items(self._run_at_checkpoint1(code)) if 'model' in it]
        entry = next(e for e in entries if (e['line'], e['visIndex']) == widget)
        entry['events'] = [{'id': event_id, 'type': 'click'}]
        return json.dumps(entries)

    # ---- the prefix ------------------------------------------------------

    def test_the_prefix_runs_once_and_its_output_is_replayed_under_the_run_id(self):
        warm, run = self._warm_then_run(self.PROGRAM, self.TARGET)
        # Nothing goes out while warming: there is no run to attribute it to,
        # and the service drops what it can't attribute.
        self.assertEqual(self._of_type(warm, 'output'), [])
        chunks = self._of_type(run, 'output')
        self.assertEqual(''.join(c['text'] for c in chunks), 'prefix\ntail\n')
        self.assertEqual({c.get('run_id') for c in chunks}, {'r1'})

    def test_a_pre_pause_widget_emits_no_item(self):
        # The editor already holds an identical one from the run that warmed
        # this worker; re-sending it is IPC and a re-render for nothing.
        _, run = self._warm_then_run(self.PROGRAM, self.TARGET)
        self.assertEqual([it['line'] for it in self._items(run)], [3, 4, 5])

    def test_a_loop_that_closed_before_the_pause_is_replayed(self):
        # The editor rebuilds every slider from what this run reported, so a
        # loop that finished during the warm still has to be reported. The loop
        # *enclosing* the target isn't held at all -- it exits after the resume.
        code = ("for i in range(2):\n"                          # 1
                "    x = i\n"                                   # 2
                "for j in range(2):\n"                          # 3
                "    y = {'kind': 'probe', 'name': 'y'}\n")     # 4  <- target
        warm, run = self._warm_then_run(code, (4, 0), warm={'loop_selections': {'3': 0}})
        self.assertEqual(self._of_type(warm, 'loop'), [])
        self.assertEqual([(m['loop']['line'], m['loop']['count'], m.get('run_id'))
                          for m in self._of_type(run, 'loop')],
                         [(1, 2, 'r1'), (3, 2, 'r1')])

    def test_a_warning_from_the_warm_is_replayed_under_the_runs_id(self):
        # A warning with no run id is routed to the main process console, where
        # nobody sees it: a broken visualizer would report itself on checkpoint
        # 2 runs and go quiet on checkpoint 3 ones.
        broken = pathlib.Path(self.dir, '.snc_visualizers', 'aa_broken_visualizer.py')
        proc = self._worker()
        warm = self._warm(proc, self.PROGRAM, self.TARGET,
                          before_run=lambda: broken.write_text('raise RuntimeError("boom")\n'))
        self.assertTrue(self._paused(warm))
        self.assertEqual(self._of_type(warm, 'warning'), [])
        self._send(proc, {'type': 'run', 'run_id': 'r1', 'models_and_events': ''})
        run = self._expect(proc, lambda m: m.get('type') == 'end', 'end of the run')
        warnings = self._of_type(run, 'warning')
        self.assertEqual([w.get('run_id') for w in warnings], ['r1'])
        self.assertIn('aa_broken_visualizer.py', warnings[0]['warning'])

    def test_the_url_cache_lands_beside_the_file_path_given_to_the_warm(self):
        # cache_dir_for(_file_path, os.getcwd()) is read at fetch time, so a
        # warm that never learned the file path caches the program's network
        # reads where no real run will look for them.
        beside = tempfile.TemporaryDirectory()
        self.addCleanup(beside.cleanup)
        code = ("import urllib.request\n"                                   # 1
                "try:\n"                                                    # 2
                "    urllib.request.urlopen('http://127.0.0.1:9/none')\n"   # 3
                "except Exception:\n"                                       # 4
                "    pass\n"                                                # 5
                "x = {'kind': 'probe', 'name': 'x'}\n")                     # 6  <- target
        self._warm_then_run(code, (6, 0),
                            warm={'file_path': os.path.join(beside.name, 'program.py')})
        self.assertTrue(os.path.isdir(os.path.join(beside.name, url_cache.CACHE_DIR_NAME)))
        self.assertFalse(os.path.isdir(os.path.join(self.dir, url_cache.CACHE_DIR_NAME)))

    # ---- events ----------------------------------------------------------

    def test_the_target_renders_with_the_event_that_arrived_with_the_run(self):
        _, run = self._warm_then_run(
            self.PROGRAM, self.TARGET,
            models_and_events=self._models_with_event(self.PROGRAM, self.TARGET, 'e1'))
        target = next(it for it in self._items(run) if (it['line'], it['visIndex']) == self.TARGET)
        self.assertEqual(target['handledEventIds'], ['e1'])
        self.assertIn('b:1', target['html'])

    def test_a_worker_paused_early_serves_a_target_further_on(self):
        # A worker paused at W serves any widget at or after W by running
        # forward. Matching on the exact widget instead would drop everything
        # below the warmed one back to checkpoint 2.
        _, run = self._warm_then_run(
            self.PROGRAM, self.TARGET,
            models_and_events=self._models_with_event(self.PROGRAM, (5, 0), 'e5'))
        by_line = {it['line']: it for it in self._items(run)}
        self.assertEqual(by_line[5]['handledEventIds'], ['e5'])
        self.assertIn('c:1', by_line[5]['html'])
        self.assertIn('b:0', by_line[3]['html'])

    def _warm_having_handled_a_pre_pause_event(self):
        return self._warm_then_run(
            self.PROGRAM, self.TARGET,
            warm={'models_and_events': self._models_with_event(self.PROGRAM, (2, 0), 'e0')})

    def test_a_held_item_is_replayed_when_it_handled_events(self):
        # Dropping this one would strand 'e0' in the editor's queue: the item
        # is the only thing that tells it which events were answered.
        _, run = self._warm_having_handled_a_pre_pause_event()
        item = next((it for it in self._items(run) if it['line'] == 2), None)
        self.assertIsNotNone(item, 'a pre-pause item that handled events was dropped')
        self.assertEqual(item['handledEventIds'], ['e0'])
        self.assertIn('a:1', item['html'])

    def test_a_held_command_is_replayed_under_the_run_id(self):
        # Every run today re-renders every widget and re-emits its commands;
        # replaying is what keeps the stream the editor sees unchanged.
        warm, run = self._warm_having_handled_a_pre_pause_event()
        self.assertEqual([it for it in self._items(warm) if it.get('commands')], [])
        self.assertEqual([(c['type'], c['triggerLine'], m.get('run_id'))
                          for m in self._of_type(run, 'item')
                          for c in m['item'].get('commands', [])],
                         [('ProbeCommand', 2, 'r1')])

    # ---- the step counter ------------------------------------------------

    def test_the_pause_step_is_the_targets_own_step(self):
        warm, run = self._warm_then_run(self.PROGRAM, self.TARGET)
        target = next(it for it in self._items(run) if (it['line'], it['visIndex']) == self.TARGET)
        self.assertEqual(warm[-1]['step'], target['execution_step'])
        self.assertEqual((warm[-1]['line'], warm[-1]['visIndex']), self.TARGET)

    def test_unselected_iterations_still_advance_the_step_counter(self):
        # The count has to mean the same thing here as on the run that measured
        # it, so it counts the iterations the editor isn't showing too. Move the
        # increment below the `_path_selected` guard and this reports 2.
        code = ("for i in range(3):\n"                          # 1
                "    x = {'kind': 'probe', 'name': 'x'}\n")     # 2  <- target
        proc = self._worker()
        warm = self._warm(proc, code, (2, 0), loop_selections={'1': 2})
        self.assertTrue(self._paused(warm))
        # Six logged values: the loop variable and x, three times over.
        self.assertEqual(warm[-1]['step'], 6)

    def test_a_widget_hit_before_and_after_the_pause_reports_the_later_step(self):
        # The editor keeps the last emission's step, so this widget lands on
        # the far side of `execution_step < pauseStep` and is not carried.
        code = ("def f(v):\n"                                   # 1
                "    return v\n"                                # 2  hit either side
                "f(1)\n"                                        # 3
                "t = {'kind': 'probe', 'name': 't'}\n"          # 4  <- target
                "f(2)\n")                                       # 5
        warm, run = self._warm_then_run(code, (4, 0))
        emitted = [it for it in self._items(run) if (it['line'], it['visIndex']) == (2, 0)]
        self.assertEqual(len(emitted), 1)
        self.assertGreater(emitted[0]['execution_step'], warm[-1]['step'])

    def test_the_end_message_carries_the_runs_id(self):
        # _execute_run was handed an empty run id at warm time; the end has to
        # report the id of the run that actually arrived, or the service drops
        # it and the worker dies unaccounted for.
        _, run = self._warm_then_run(self.PROGRAM, self.TARGET)
        self.assertEqual(run[-1]['run_id'], 'r1')
        self.assertEqual(run[-1]['result']['exitCode'], 0)

    # ---- targets that never arrive ---------------------------------------

    def test_a_target_that_is_never_reached_discards_the_hold_and_exits(self):
        # Never reached means the widget doesn't render under this code and
        # loop selection -- both pinned by the pool's key -- so the user cannot
        # be interacting with it, and resuming would apply their gesture to a
        # program that has already finished and swallow it.
        code = ("print('before', flush=True)\n"                 # 1
                "if False:\n"                                   # 2
                "    x = {'kind': 'probe', 'name': 'x'}\n")     # 3  <- never runs
        proc = self._worker()
        msgs = self._warm(proc, code, (3, 0))
        self.assertFalse(self._paused(msgs), 'a worker that never reached the target offered itself')
        # Nothing was ever written, so nothing is owed to anyone.
        self.assertEqual([m for m in msgs if m.get('type') != 'meta'], [])
        self.assertEqual(proc.wait(timeout=10), 0)

    def test_an_uncaught_error_before_the_target_takes_the_same_exit(self):
        code = ("raise ValueError('boom')\n"                    # 1
                "x = {'kind': 'probe', 'name': 'x'}\n")         # 2  <- never runs
        proc = self._worker()
        msgs = self._warm(proc, code, (2, 0))
        self.assertFalse(self._paused(msgs))
        self.assertEqual([m for m in msgs if m.get('type') != 'meta'], [])
        self.assertEqual(proc.wait(timeout=10), 0)

    def test_the_error_handler_does_not_hijack_the_pause(self):
        # A crash is reported with log_value(error_line, UncaughtError(...)) at
        # site 0. Pausing there would hand back a worker whose only remaining
        # work is to finish erroring, while the editor carried its pre-pause
        # items forward on the strength of the step it reported.
        code = ("x = 1\n"                                       # 1
                "raise ValueError('boom')\n")                   # 2  <- reported at (2, 0)
        proc = self._worker()
        msgs = self._warm(proc, code, (2, 0))
        self.assertFalse(self._paused(msgs))
        self.assertEqual(proc.wait(timeout=10), 0)


class TestLoopIterations(unittest.TestCase):
    """A line inside a loop runs once per iteration. Each logged item carries
    the dynamic `path` it was logged under -- `[[loop_line, iteration], ...]`
    for the loops (and function calls) enclosing it -- and the editor can pin
    a loop to one iteration with `loop_selections`, in which case only items
    under that iteration are rendered at all."""

    def _run(self, source_code, loop_selections=None):
        import_code, body_code = split_leading_imports(source_code)
        with capture_stream_messages() as msgs:
            python_runner._execute_run(body_code, '', 'run-1', import_code=import_code,
                                       loop_selections=loop_selections)
        return msgs.all()

    @staticmethod
    def _items(msgs):
        """[(line, visIndex, path, value_text)] in emission order."""
        import re
        out = []
        for m in msgs:
            if m.get('type') != 'item':
                continue
            it = m['item']
            found = re.search(r'snc-generic-visualizer">(.*?)</span>', it['html'])
            out.append((it['line'], it['visIndex'], it['path'], found.group(1) if found else it['html']))
        return out

    @staticmethod
    def _loops(msgs):
        return [(m['loop']['line'], m['loop']['path'], m['loop']['count'])
                for m in msgs if m.get('type') == 'loop']

    def test_a_recursive_function_numbers_its_activations_in_entry_order(self):
        src = (
            "def fact(n):\n"
            "    if n == 0:\n"
            "        return 1\n"
            "    else:\n"
            "        return n * fact(n-1)\n"
            "fact(3)\n"
        )
        # Activation 2 is fact(1): its condition and its return.
        msgs = self._run(src, {'1': 2})
        self.assertEqual(self._items(msgs), [
            (1, 0, [[1, 0], [1, 1], [1, 2]], '1'),
            (2, 0, [[1, 0], [1, 1], [1, 2]], 'False'),
            (5, 0, [[1, 0], [1, 1], [1, 2]], '1'),
            (6, 0, [], '6'),
        ])
        # Every exit reports how many activations began; the outermost last.
        self.assertEqual(self._loops(msgs)[-1], (1, [], 4))
        self.assertEqual(self._run(src)[-1]['type'], 'end')
        kinds = {m['loop']['kind'] for m in self._run(src) if m.get('type') == 'loop'}
        self.assertEqual(kinds, {'call'})

    SRC = (
        "for i in range(3):\n"
        "    y = i * 10\n"
        "z = 1\n"
    )

    def test_every_iteration_is_emitted_when_the_loop_is_not_pinned(self):
        items = self._items(self._run(self.SRC))
        self.assertEqual(items, [
            (1, 0, [[1, 0]], '0'), (2, 0, [[1, 0]], '0'),
            (1, 0, [[1, 1]], '1'), (2, 0, [[1, 1]], '10'),
            (1, 0, [[1, 2]], '2'), (2, 0, [[1, 2]], '20'),
            (3, 0, [], '1'),
        ])

    def test_the_loop_reports_its_iteration_count_when_it_ends(self):
        self.assertEqual(self._loops(self._run(self.SRC)), [(1, [], 3)])

    def test_pinning_a_loop_renders_only_that_iteration(self):
        items = self._items(self._run(self.SRC, {'1': 1}))
        self.assertEqual(items, [(1, 0, [[1, 1]], '1'), (2, 0, [[1, 1]], '10'), (3, 0, [], '1')])

    def test_a_branch_not_taken_in_the_pinned_iteration_shows_nothing(self):
        src = (
            "for i in range(4):\n"
            "    if i % 2 == 0:\n"
            "        even = i\n"
        )
        items = self._items(self._run(src, {'1': 1}))
        self.assertEqual(items, [(1, 0, [[1, 1]], '1'), (2, 0, [[1, 1]], 'False')])

    def test_nested_loops_count_per_outer_iteration(self):
        src = (
            "for i in range(2):\n"
            "    for j in range(i + 1):\n"
            "        p = i * 10 + j\n"
        )
        msgs = self._run(src, {'1': 1, '2': 0})
        self.assertEqual(self._items(msgs), [
            (1, 0, [[1, 1]], '1'),
            (2, 0, [[1, 1], [2, 0]], '0'),
            (3, 0, [[1, 1], [2, 0]], '10'),
        ])
        # Only the pinned outer iteration's inner loop reports; the outer
        # loop itself reports once it ends.
        self.assertEqual(self._loops(msgs), [(2, [[1, 1]], 2), (1, [], 2)])

    def test_visindex_is_the_static_position_on_the_line(self):
        src = "for a, b in [(1, 2), (3, 4)]:\n    pass\n"
        items = self._items(self._run(src))
        self.assertEqual(items, [
            (1, 0, [[1, 0]], '1'), (1, 1, [[1, 0]], '2'),
            (1, 0, [[1, 1]], '3'), (1, 1, [[1, 1]], '4'),
        ])

    def test_a_function_is_a_loop_over_its_calls(self):
        src = (
            "def f(x):\n"
            "    return x + 1\n"
            "a = f(1)\n"
            "b = f(10)\n"
        )
        msgs = self._run(src, {'1': 1})
        self.assertEqual(self._items(msgs), [
            (3, 0, [], '2'),
            (1, 0, [[1, 1]], '10'),
            (2, 0, [[1, 1]], '11'),
            (4, 0, [], '11'),
        ])
        # Each call reports the count so far; the editor keeps the last.
        self.assertEqual(self._loops(msgs), [(1, [], 1), (1, [], 2)])

    def test_a_functions_parameters_are_logged_on_the_def_line(self):
        src = (
            "def f(a, b=2, *rest, k=3, **kw):\n"
            "    return a\n"
            "f(1, 5, 6, k=7, z=8)\n"
        )
        items = self._items(self._run(src))
        self.assertEqual([it[:3] for it in items[:5]], [
            (1, 0, [[1, 0]]), (1, 1, [[1, 0]]), (1, 2, [[1, 0]]), (1, 3, [[1, 0]]), (1, 4, [[1, 0]]),
        ])
        # (`rest` and `kw` are a tuple and a dict, which get real visualizers.)
        self.assertEqual([items[i][3] for i in (0, 1, 3)], ['1', '5', '7'])

    def test_a_break_still_pops_the_loop(self):
        src = (
            "for i in range(10):\n"
            "    if i == 1:\n"
            "        break\n"
            "after = 5\n"
        )
        msgs = self._run(src)
        self.assertEqual(self._loops(msgs), [(1, [], 2)])
        self.assertEqual(self._items(msgs)[-1], (4, 0, [], '5'))

    def test_a_while_loop_counts_too(self):
        src = "n = 0\nwhile n < 3:\n    n += 1\n"
        msgs = self._run(src, {'2': 2})
        self.assertEqual(self._items(msgs), [(1, 0, [], '0'), (3, 0, [[2, 2]], '3')])
        self.assertEqual(self._loops(msgs), [(2, [], 3)])

    def test_an_uncaught_error_belongs_to_the_iteration_that_raised_it(self):
        src = "for i in range(3):\n    x = 1 // (1 - i)\n"
        msgs = self._run(src)
        items = self._items(msgs)
        self.assertEqual(items[-1][:3], (2, 0, [[1, 1]]))
        self.assertEqual(self._loops(msgs), [(1, [], 2)])
        # Pinned elsewhere, the error isn't that iteration's to show.
        self.assertEqual([it[:3] for it in self._items(self._run(src, {'1': 0}))],
                         [(1, 0, [[1, 0]]), (2, 0, [[1, 0]])])

    def test_an_error_raised_in_a_call_belongs_to_that_call(self):
        src = "def f(n):\n    return 1 // n\nf(1)\nf(0)\n"
        items = self._items(self._run(src))
        # (Reported at the call site, as uncaught errors are; the path is the
        # call's.)
        self.assertEqual(items[-1][2], [[1, 1]])

    def test_events_replay_once_per_site_per_run(self):
        """A site logged three times in one run replays its pending events
        once and carries the resulting model forward, so a command a
        visualizer emits in response goes out once."""
        class Vis:
            def can_visualize(value): return isinstance(value, int)
            def init_model(value, get_visualizer): return {'n': 0}
            def visualize(value, model, get_visualizer, eval_in_scope): return f'<b>{model["n"]}</b>'
            def update(event, var_and_exp, model, value, get_visualizer): return ({'n': model['n'] + 1}, [])
        model = {'n': 5, '_type_fingerprint': python_runner._type_fingerprint(0),
                 '_source_expr_sig': ['y', 'y']}
        m_and_e = json.dumps([{'line': 2, 'visIndex': 0, 'model': model,
                               'events': [{'pythonEventStr': 'e', 'eventJSON': {}}]}])
        import_code, body_code = split_leading_imports(self.SRC)
        saved = python_runner._visualizers
        python_runner._visualizers = lambda: [Vis]
        try:
            with capture_stream_messages() as msgs:
                python_runner._execute_run(body_code, m_and_e, 'run-1', import_code=import_code)
        finally:
            python_runner._visualizers = saved
        htmls = [m['item']['html'] for m in msgs.all() if m.get('type') == 'item' and m['item']['line'] == 2]
        self.assertEqual(htmls, ['<b>6</b>'] * 3)


def fake_stdin(test):
    """Point the runner's protocol fd at a pipe for the duration of `test`.

    Restores the non-blocking flag too: leaving it set would let a later test
    drain the real fd 0, which blocks when pytest is run with a terminal.
    """
    r, w = os.pipe()
    saved = (python_runner._stdin_fd, python_runner._stdin_buf, python_runner._stdin_nonblocking)

    def restore():
        (python_runner._stdin_fd, python_runner._stdin_buf,
         python_runner._stdin_nonblocking) = saved
        for fd in (r, w):
            try:
                os.close(fd)
            except OSError:
                pass

    test.addCleanup(restore)
    python_runner._stdin_fd, python_runner._stdin_buf = r, b''
    python_runner._stdin_nonblocking = False
    return r, w


class TestStdinProtocolReader(unittest.TestCase):
    """One reader owns the protocol fd.

    The handshake used to use `sys.stdin.readline()`, whose TextIOWrapper reads
    ahead: bytes it buffers are invisible to a later raw read, so a message
    arriving hard behind another would vanish. These share one buffer instead.
    """

    def setUp(self):
        self.r, self.w = fake_stdin(self)

    def test_a_line_is_read_back(self):
        os.write(self.w, b'{"type": "run"}\n')
        self.assertEqual(read_stdin_line(), '{"type": "run"}')

    def test_a_message_arriving_behind_another_is_not_lost(self):
        # The two land in one read. The second must survive for the drain.
        os.write(self.w, b'{"type": "run"}\n{"type": "events"}\n')
        self.assertEqual(read_stdin_line(), '{"type": "run"}')
        python_runner.unblock_stdin()
        self.assertEqual(drain_stdin_lines(), ['{"type": "events"}'])

    def test_draining_an_empty_pipe_does_not_block(self):
        python_runner.unblock_stdin()
        self.assertEqual(drain_stdin_lines(), [])

    def test_a_partial_line_waits_for_its_newline(self):
        python_runner.unblock_stdin()
        os.write(self.w, b'{"type": "ev')
        self.assertEqual(drain_stdin_lines(), [])
        os.write(self.w, b'ents"}\n')
        self.assertEqual(drain_stdin_lines(), ['{"type": "events"}'])

    def test_the_drain_returns_everything_pending_in_order(self):
        python_runner.unblock_stdin()
        os.write(self.w, b'one\ntwo\nthree\n')
        self.assertEqual(drain_stdin_lines(), ['one', 'two', 'three'])


class TestHandledEventReporting(unittest.TestCase):
    """An item says which of the queued events it actually applied.

    The editor used to infer this from the snapshot it sent, which is wrong
    whenever the runner declines to replay -- the events were dropped from the
    queue having never reached a visualizer.
    """

    SRC = "x = 5\n"

    class SeenVis:
        def can_visualize(value):
            return isinstance(value, int)

        def init_model(value, get_visualizer):
            return {'seen': []}

        def visualize(value, model, get_visualizer):
            return f"<i>{','.join(model['seen'])}</i>"

        def update(event, var_and_exp, model, value, get_visualizer):
            return {'seen': model['seen'] + [event['eventJSON']['type']]}, []

    def _items(self, models_and_events):
        saved = python_runner._visualizers
        python_runner._visualizers = lambda: [self.SeenVis]
        try:
            import_code, body_code = split_leading_imports(self.SRC)
            with capture_stream_messages() as msgs:
                python_runner._execute_run(body_code, json.dumps(models_and_events), 'run-1',
                                           import_code=import_code)
        finally:
            python_runner._visualizers = saved
        return [m['item'] for m in msgs.all() if m.get('type') == 'item']

    def _event(self, event_id, kind):
        return {'line': 1, 'visIndex': 0, 'id': event_id,
                'pythonEventStr': 'lambda e: None', 'eventJSON': {'type': kind}}

    def test_a_run_with_no_events_reports_none_handled(self):
        item = self._items([])[0]
        self.assertEqual(item['handledEventIds'], [])

    def test_replayed_events_are_reported_by_id(self):
        # The model has to come from a real run, so its fingerprint matches.
        model = self._items([])[0]['model']
        item = self._items([{'line': 1, 'visIndex': 0, 'model': model,
                             'events': [self._event(7, 'mousemove'), self._event(8, 'mouseup')]}])[0]

        self.assertEqual(item['handledEventIds'], [7, 8])
        self.assertIn('mousemove,mouseup', item['html'])

    def test_an_event_queued_after_dispatch_is_picked_up(self):
        # The editor keeps sending while a run is in flight; a visualizer is
        # reached long before the program ends, so the run answers the newest
        # events rather than only the ones it launched with.
        model = self._items([])[0]['model']
        _, w = fake_stdin(self)
        python_runner.unblock_stdin()
        os.write(w, (json.dumps({'type': 'events', 'events': [self._event(9, 'mouseup')]}) + '\n').encode())

        item = self._items([{'line': 1, 'visIndex': 0, 'model': model}])[0]

        self.assertEqual(item['handledEventIds'], [9])
        self.assertIn('mouseup', item['html'])

    def test_a_late_event_for_an_unknown_widget_is_left_queued(self):
        # No model for that widget in this run, so nothing replays onto it and
        # the editor has to keep the event for next time.
        _, w = fake_stdin(self)
        python_runner.unblock_stdin()
        late = {**self._event(9, 'mouseup'), 'line': 99}
        os.write(w, (json.dumps({'type': 'events', 'events': [late]}) + '\n').encode())

        item = self._items([])[0]

        self.assertEqual(item['handledEventIds'], [])

    def test_events_the_runner_declines_to_replay_are_not_reported(self):
        # A model whose fingerprint no longer matches is rebuilt, and its
        # events belong to what was there before -- so they go unapplied and
        # must stay queued rather than being silently dropped.
        model = self._items([])[0]['model']
        stale = {**model, '_type_fingerprint': 'something else'}
        item = self._items([{'line': 1, 'visIndex': 0, 'model': stale,
                             'events': [self._event(7, 'mousemove')]}])[0]

        self.assertEqual(item['handledEventIds'], [])
        self.assertNotIn('mousemove', item['html'])


class TestReadOnly(unittest.TestCase):
    """A run asked for with `read_only` (clickacode.readOnlyVisualizers) renders no
    handles and sends the editor no command that would change the file."""

    SRC = "x = 5\n"

    def setUp(self):
        # The flag is process-wide and these tests end on a read-only run, so
        # without this every visualizer test that runs after them in the same
        # pytest process renders with its affordances suppressed.
        from visualizer_utils import set_read_only
        self.addCleanup(set_read_only, False)

    def _run(self, read_only, visualizers=None):
        import_code, body_code = split_leading_imports(self.SRC)
        saved = python_runner._visualizers
        if visualizers is not None:
            python_runner._visualizers = lambda: visualizers
        try:
            with capture_stream_messages() as msgs:
                python_runner._execute_run(body_code, '', 'run-1', import_code=import_code,
                                           read_only=read_only)
        finally:
            python_runner._visualizers = saved
        return msgs.all()

    def test_flag_is_reset_between_runs(self):
        from visualizer_utils import is_read_only
        self._run(True)
        self.assertTrue(is_read_only())
        self._run(False)
        self.assertFalse(is_read_only())

    def test_generic_visualizer_has_no_handle(self):
        html_with = [m['item']['html'] for m in self._run(False) if m.get('type') == 'item'][0]
        html_without = [m['item']['html'] for m in self._run(True) if m.get('type') == 'item'][0]
        self.assertIn('snc-py-exps', html_with)
        self.assertNotIn('snc-py-exps', html_without)
        self.assertIn('snc-generic-visualizer', html_without)

    def test_commands_that_change_code_are_dropped(self):
        class SavingVis:
            def can_visualize(value): return isinstance(value, int)
            def init_model(value, get_visualizer): return {}
            def visualize(value, model, get_visualizer, eval_in_scope):
                from visualizer_utils import save_slots_at_path
                save_slots_at_path([], ['$.a'])
                return 'v'
            def update(event, var_and_exp, model, value, get_visualizer):
                return (model, [])
        def commands(msgs):
            return [c['type'] for m in msgs if m.get('type') == 'item'
                    for c in m['item'].get('commands', [])]
        self.assertEqual(commands(self._run(False, [SavingVis])), ['SetConfigComment'])
        self.assertEqual(commands(self._run(True, [SavingVis])), [])
