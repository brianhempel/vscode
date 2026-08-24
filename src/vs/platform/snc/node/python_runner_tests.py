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
    execute_code,
    install_url_cache,
    log_value,
    reseed,
    split_leading_imports,
    transform_code_to_ast,
)
# python_runner puts the built-in visualizers on the path.
from visualizer_utils import py_exp_attrs, AddImports, UncaughtError


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
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None, source_span=None: logged.append((line, value)),
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
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None, source_span=None: logged.append((line, value)),
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
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None, source_span=None: logged.append((line, value)),
            "_log_and_return": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None, source_span=None: (logged.append((line, value)), value)[1],
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
        old_counter = python_runner.line_emit_counter
        old_models = python_runner.models_and_events
        old_focused = python_runner._focused_line
        try:
            python_runner._stream_out = buf
            python_runner.line_emit_counter = {}
            python_runner.models_and_events = []
            python_runner._focused_line = focused_line
            log_value(1, value, var_and_exp=var_and_exp)
        finally:
            python_runner._stream_out = old_out
            python_runner.line_emit_counter = old_counter
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

    def test_editing_the_line_refetches(self):
        source = (
            'import urllib.request\n'
            'str1 = urllib.request.urlopen("https://example.com/report.txt").read().decode()\n'
        )
        self._run(source)
        edited = source.replace('str1', 'text')
        self.assertEqual(self._run(edited)['text'], 'weather report')
        self.assertEqual(len(self.fetches), 2)

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

        def record(line, value, last_line_in_containing_loop=None,
                   eval_in_scope=None, var_and_exp=None, source_span=None):
            spans[line] = source_span

        globals_dict = {
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
        saved = (python_runner._stream_out, python_runner.line_emit_counter,
                 python_runner.models_and_events, python_runner._source_code,
                 python_runner._visualizers)
        try:
            python_runner._stream_out = buf
            python_runner.line_emit_counter = {}
            python_runner.models_and_events = []
            python_runner._source_code = 'data = [3, 1, 2]\n'
            python_runner._visualizers = lambda: [vis]
            log_value(1, [3, 1, 2], var_and_exp=('data', 'data'),
                      source_span=source_span)
        finally:
            (python_runner._stream_out, python_runner.line_emit_counter,
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
