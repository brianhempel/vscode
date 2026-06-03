"""
Tests for python_runner.py.

Run:
    python3 -m pytest src/vs/platform/snc/node/python_runner_tests.py -v
"""

import unittest

from python_runner import (
    GenericVisualizer,
    VisualizerOfStaticVisualizer,
    _build_new_code_edits,
    split_leading_imports,
)


class TestSplitLeadingImports(unittest.TestCase):
    def test_bare_string_after_imports_stays_in_body(self):
        source_code = 'import re\n\n"hello world"\n'
        import_code, body_code = split_leading_imports(source_code)

        logged = []
        globals_dict = {
            "__name__": "__main__",
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None: logged.append((line, value)),
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
            "_log_value": lambda line, value, last_line_in_containing_loop=None, eval_in_scope=None: logged.append((line, value)),
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


class _StaticVisStub:
    """Minimal static visualizer module: visualize(value) -> str."""
    def can_visualize(self, value):
        return True

    def visualize(self, value):
        return f'<b>{value}</b>'


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
        self.assertEqual(out, '42')

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


