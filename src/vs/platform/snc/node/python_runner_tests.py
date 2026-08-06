"""
Tests for python_runner.py.

Run:
    python3 -m pytest src/vs/platform/snc/node/python_runner_tests.py -v
"""

import io
import json
import os
import tempfile
import unittest
import urllib.request
from dataclasses import dataclass
from typing import Optional

import io_cache
import python_runner
from python_runner import (
    GenericVisualizer,
    VisualizerOfStaticVisualizer,
    _build_new_code_edits,
    _commands_to_dicts,
    install_io_cache,
    log_value,
    split_leading_imports,
    transform_code_to_ast,
)


class TestSplitLeadingImports(unittest.TestCase):
    def test_bare_string_after_imports_stays_in_body(self):
        source_code = 'import re\n\n"hello world"\n'
        import_code, body_code = split_leading_imports(source_code)

        logged = []
        globals_dict = {
            "__name__": "__main__",
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None: logged.append((line, value)),
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
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None, var_and_exp=None: logged.append((line, value)),
        }

        exec(import_code, globals_dict)
        exec(body_code, globals_dict)

        self.assertEqual(logged, [(4, "hello world")])


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
        model = {'linked_action': 'find_or_map', 'linked_has_assignment': True}
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
        model = {'linked_action': 'find_or_map', 'linked_has_assignment': True}
        dicts = _commands_to_dicts(
            [('str1', "str1 + str2")],
            line=2, idx_in_line=0, model=model, source_code=source,
        )
        self.assertEqual(dicts[0]['edits'][0]['text'], "str3 = str1 + str2")
        self.assertNotIn('linked_prefix', model)

    def test_newcode_no_var_name_leaves_model_untouched(self):
        # Bare-expression insert (no assignment) must not touch linked_prefix.
        model = {'linked_action': 'loop', 'linked_has_assignment': False}
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
    values (e.g. stop_idx = 33) get an snc-py-exp drag handle. A generic
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
        self.assertIn('snc-py-exp="stop_idx"', html_out)
        self.assertIn('draggable="true"', html_out)
        self.assertIn('class="py-exp-grab"', html_out)
        self.assertIn('33', html_out)

    def test_log_value_generic_int_emits_snc_py_exp_when_small(self):
        # Another line is focused, so line 1 renders small.
        html_out = self._log_html(33, var_and_exp=('stop_idx', 'stop_idx'), focused_line=2)
        self.assertIn('snc-py-exp="stop_idx"', html_out)
        self.assertIn('class="py-exp-grab"', html_out)

    def test_log_value_without_var_and_exp_has_no_snc_py_exp(self):
        html_out = self._log_html(33)
        self.assertNotIn('snc-py-exp', html_out)
        self.assertIn('33', html_out)


class TestGenericVisualizerDrag(unittest.TestCase):
    """The generic/static visualizers should wrap their output in a draggable
    snc-py-exp grab span when given an access-path expression via var_and_exp,
    so nested (non-interactive) values are draggable to extract."""

    def test_generic_wraps_with_py_exp_when_var_and_exp_given(self):
        out = GenericVisualizer.visualize(
            42, None, None, None, var_and_exp=(None, 'x[0]'))
        self.assertIn('snc-py-exp="x[0]"', out)
        self.assertIn('draggable="true"', out)
        self.assertIn('class="py-exp-grab"', out)
        self.assertIn('42', out)

    def test_generic_no_wrap_without_var_and_exp(self):
        out = GenericVisualizer.visualize(42, None, None, None)
        self.assertNotIn('snc-py-exp', out)
        self.assertNotIn('py-exp-grab', out)
        self.assertEqual(out, '<span class="snc-generic-visualizer">42</span>')

    def test_generic_wraps_in_small_mode_too(self):
        out = GenericVisualizer.visualize(
            42, None, None, None, small=True, var_and_exp=(None, 'x[0]'))
        self.assertIn('snc-py-exp="x[0]"', out)
        self.assertIn('class="py-exp-grab"', out)

    def test_generic_escapes_expression_and_value(self):
        out = GenericVisualizer.visualize(
            '<a>', None, None, None, var_and_exp=(None, 'd["<k>"]'))
        # Expression is HTML-escaped inside the attribute.
        self.assertIn('snc-py-exp="d[&quot;&lt;k&gt;&quot;]"', out)
        # repr value is escaped (note repr adds quotes).
        self.assertIn('&lt;a&gt;', out)
        self.assertNotIn('<a>', out)

    def test_static_visualizer_wraps_with_py_exp(self):
        vis = VisualizerOfStaticVisualizer(_StaticVisStub())
        out = vis.visualize(7, None, None, None, var_and_exp=(None, 'items[2]'))
        self.assertIn('snc-py-exp="items[2]"', out)
        self.assertIn('draggable="true"', out)
        self.assertIn('class="py-exp-grab"', out)
        # Inner static-visualizer output is preserved.
        self.assertIn('<b>7</b>', out)

    def test_static_visualizer_no_wrap_without_var_and_exp(self):
        vis = VisualizerOfStaticVisualizer(_StaticVisStub())
        out = vis.visualize(7, None, None, None)
        self.assertNotIn('snc-py-exp', out)
        self.assertEqual(out, '<b>7</b>')


class TestIoCacheAcrossRuns(unittest.TestCase):
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

        self.addCleanup(install_io_cache())
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
        cache_dir = os.path.join(os.path.dirname(python_runner._file_path), io_cache.CACHE_DIR_NAME)
        self.assertTrue(any(f.endswith('.body') for f in os.listdir(cache_dir)))


