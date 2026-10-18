"""
Tests for for_loop_visualizer.py - a finished `for` loop drawn as a table of
its iterations, with buttons that add a step to the loop.

These tests follow TDD: written before the implementation.

Run this test file directly:
    python3 src/vs/platform/snc/node/visualizers/for_loop_visualizer_tests.py

Or use pytest with verbose output:
    python3 -m pytest src/vs/platform/snc/node/visualizers/for_loop_visualizer_tests.py -v
"""

import html
import re
import unittest

import visualizer_utils
from for_loop_visualizer import AddStep, can_visualize, init_model, update, visualize
from visualizer_utils import ForLoopTable, InsertLines


def table(**overrides):
    """The loop in

        1  count = 0
        2  for element in [1, 2]:
        3      count += 1

    as the runner logs it on line 3 once it ends."""
    fields = dict(
        line=2, end_line=3, indent='', body_indent='    ',
        columns=('element', 'count += 1'),
        rows=(('1', '1'), ('2', '2')),
        targets=('element',),
        defined=frozenset({'count', 'element'}),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


def click(step):
    """The event a press on the button for `step` sends."""
    return {'pythonEventStr': repr(step), 'eventJSON': {'type': 'MouseDown'}}


def events_in(html_text):
    """The Python event of every button, in order."""
    return [html.unescape(e) for e in re.findall(r'snc-mouse-down="([^"]*)"', html_text)]


class TestCanVisualize(unittest.TestCase):
    def test_visualizes_a_loop_table(self):
        self.assertTrue(can_visualize(table()))

    def test_does_not_visualize_ordinary_values(self):
        for value in ([['1', '1']], {'columns': []}, 'element', None):
            with self.subTest(value=value):
                self.assertFalse(can_visualize(value))


class TestVisualize(unittest.TestCase):
    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_row_per_iteration_numbered_from_one_under_the_column_labels(self):
        out = visualize(table(), init_model(table()))
        headers = [html.unescape(h) for h in re.findall(r'<th[^>]*>([^<]*)</th>', out)]
        self.assertEqual(headers, ['iteration', 'element', 'count += 1'])
        numbers = re.findall(r'<td class="row-index">([^<]*)</td>', out)
        self.assertEqual(numbers, ['1', '2'])
        cells = [html.unescape(c) for c in re.findall(r'<span class="snc-code">([^<]*)</span>', out)]
        self.assertEqual(cells, ['1', '1', '2', '2'])

    def test_is_drawn_as_a_table_so_it_gets_a_line_of_its_own(self):
        self.assertIn('list-table-scroll', visualize(table(), init_model(table())))

    def test_cells_are_escaped(self):
        out = visualize(table(columns=('s',), rows=(("'<b>'",),)), {})
        self.assertIn('&#x27;&lt;b&gt;&#x27;', out)
        self.assertNotIn('<b>', out)

    def test_an_iteration_that_never_reached_a_statement_shows_a_dash(self):
        out = visualize(table(rows=(('1', None),)), {})
        self.assertIn('<td class="list-table-cell">—</td>', out)

    def test_says_how_many_iterations_it_leaves_out(self):
        self.assertIn('3 more iterations', visualize(table(hidden_rows=3), {}))
        self.assertIn('1 more iteration<', visualize(table(hidden_rows=1), {}))
        self.assertNotIn('more iteration', visualize(table(), {}))

    def test_offers_count_and_a_sum_and_product_of_each_name_the_loop_binds(self):
        out = visualize(table(targets=('i', 'element')), {})
        self.assertEqual(events_in(out), [
            repr(AddStep('count', '1')),
            repr(AddStep('total', 'i')), repr(AddStep('total', 'element')),
            repr(AddStep('product', 'i')), repr(AddStep('product', 'element')),
        ])

    def test_buttons_work_without_the_table_being_focused(self):
        # The table only shows while the cursor is outside the loop, so it is
        # never the focused line: a press must not be spent pinning focus.
        out = visualize(table(), {}, small=True)
        buttons = re.findall(r'<span[^>]*snc-mouse-down[^>]*>', out)
        self.assertTrue(buttons)
        for button in buttons:
            self.assertIn('snc-unfocused-clickable', button)
            self.assertIn('draggable="false"', button)

    def test_each_button_says_the_code_it_writes(self):
        out = visualize(table(), {})
        tooltips = [html.unescape(t) for t in re.findall(r'data-tooltip="([^"]*)"', out)]
        self.assertEqual(tooltips, ['count += 1', 'total += element', 'product *= element'])

    def test_writes_no_buttons_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        out = visualize(table(), {})
        self.assertEqual(events_in(out), [])
        self.assertNotIn('action-button', out)


class TestUpdate(unittest.TestCase):
    def test_count_adds_to_an_accumulator_already_defined(self):
        model, cmds = update(click(AddStep('count', '1')), None, {}, table())
        self.assertEqual(cmds, [InsertLines(((3, '    count += 1'),))])

    def test_a_new_accumulator_is_initialized_above_the_loop(self):
        model, cmds = update(click(AddStep('total', 'element')), None, {}, table())
        self.assertEqual(cmds, [InsertLines(((1, 'total = 0'), (3, '    total += element')))])

    def test_a_product_starts_at_one(self):
        model, cmds = update(click(AddStep('product', 'element')), None, {}, table())
        self.assertEqual(cmds, [InsertLines(((1, 'product = 1'), (3, '    product *= element')))])

    def test_indentation_follows_the_loop(self):
        t = table(line=5, end_line=9, indent='    ', body_indent='        ', defined=frozenset())
        model, cmds = update(click(AddStep('count', '1')), None, {}, t)
        self.assertEqual(cmds, [InsertLines(((4, '    count = 0'), (9, '        count += 1')))])

    def test_ignores_a_step_over_a_name_the_loop_does_not_bind(self):
        model, cmds = update(click(AddStep('total', 'os.system')), None, {}, table())
        self.assertEqual(cmds, [])

    def test_ignores_events_it_does_not_know(self):
        for event in ({'pythonEventStr': 'MouseMove()'}, {'pythonEventStr': ''}, {}, None):
            with self.subTest(event=event):
                self.assertEqual(update(event, None, {}, table()), ({}, []))


if __name__ == '__main__':
    unittest.main()
