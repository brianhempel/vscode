"""
Tests for for_loop_visualizer.py - a finished `for` loop drawn as a table of
its iterations, with a (+) that writes a line of the user's own into it, and
headers that edit or delete the line a column is.

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
from for_loop_visualizer import (AddColumnClick, ColumnClick, ColumnInput, ColumnInputBlur, ColumnKeyDown,
                                 DeleteColumnClick, can_visualize, init_model, update, visualize)
from visualizer_utils import ForLoopTable, InsertLines, ReplaceLines


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
        spans=(None, (3, 3)),
        body_lines=(3, 3),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


def click(msg, detail=1):
    """The event a press on whatever sends `msg` sends; `detail` counts the
    clicks, 2 being a double-click."""
    return {'pythonEventStr': repr(msg), 'eventJSON': {'type': 'MouseDown', 'detail': detail}}


def events_in(html_text):
    """The Python event of every button, in order."""
    return [html.unescape(e) for e in re.findall(r'snc-mouse-down="([^"]*)"', html_text)]


def key(name):
    """The event a key pressed in the column box sends."""
    return {'pythonEventStr': repr(ColumnKeyDown()), 'eventJSON': {'type': 'KeyDown', 'key': name}}


def typed(text):
    """The event typing `text` into the column box sends, as the editor builds it."""
    box = re.search(r'<input[^>]*snc-input="([^"]*)"', visualize(table(), {'adding_column': True}))
    return {'pythonEventStr': html.unescape(box.group(1)), 'eventJSON': {'value': text}}


def adding(text):
    """The model while the box adding a column is open holding `text`."""
    return {'adding_column': True, 'editing_column': None, 'column_input': text}


def editing(col, text):
    """The model while column `col`'s box is open holding `text`."""
    return {'adding_column': False, 'editing_column': col, 'column_input': text}


def header_cells(html_text):
    """Each <th> of the header row."""
    return re.findall(r'<th[^>]*>.*?</th>', re.search(r'<thead.*?</thead>', html_text).group(0))


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

    def test_a_row_per_iteration_numbered_from_zero_under_the_column_labels(self):
        out = visualize(table(), init_model(table()))
        # A statement's label is in a span, beside its x.
        headers = [html.unescape(re.sub(r'<[^>]*>', '', re.sub(r'<span class="for-loop-col-delete".*?</span>', '', c)))
                   for c in header_cells(out)]
        self.assertEqual(headers, ['itr', 'element', 'count += 1'])
        numbers = re.findall(r'<td class="row-index">([^<]*)</td>', out)
        self.assertEqual(numbers, ['0', '1'])
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

    def test_has_no_bar_of_buttons_under_the_table(self):
        out = visualize(table(targets=('i', 'element')), {})
        self.assertNotIn('action-button', out)
        self.assertNotIn('AddStep', html.unescape(out))

    def test_the_plus_works_without_the_table_being_focused(self):
        # The table only shows while the cursor is outside the loop, so it is
        # never the focused line: a press must not be spent pinning focus.
        out = visualize(table(), {}, small=True)
        buttons = re.findall(r'<span[^>]*snc-mouse-down[^>]*>', out)
        self.assertTrue(buttons)
        for button in buttons:
            self.assertIn('snc-unfocused-clickable', button)
            self.assertIn('draggable="false"', button)

    def test_the_plus_is_a_bar_beside_the_table_drawn_focused_or_not(self):
        # A table's (+), except that a table only draws its own once it is
        # focused, and this one never is.
        for small in (True, False):
            with self.subTest(small=small):
                out = visualize(table(), {}, small=small)
                bar = re.search(r'</table></div>(<div class="snc-dropdown-trigger col-add-trigger">.*?</div>)', out)
                self.assertEqual(events_in(bar.group(1)), [repr(AddColumnClick())])
                self.assertIn('<div class="snc-tool-and-visualizer"><div class="list-table-scroll', out)
                self.assertNotIn('<input', out)

    def test_an_open_box_is_a_last_header_cell_holding_what_was_typed(self):
        out = visualize(table(), adding('doubled = element * 2'))
        box = re.search(r'<input[^>]*>', header_cells(out)[-1]).group(0)
        self.assertIn('value="doubled = element * 2"', box)
        # Takes the keyboard as it opens: the table never has the editor's
        # focus, and a click into it would move the cursor into the loop.
        self.assertIn('autofocus', box)
        self.assertIn('snc-unfocused-clickable', box)
        self.assertIn(f'snc-blur="{html.escape(repr(ColumnInputBlur()))}"', box)
        self.assertIn(f'snc-key-down="{html.escape(repr(ColumnKeyDown()))}"', out)

    def test_what_was_typed_is_escaped(self):
        out = visualize(table(), adding('s = "<b>"'))
        self.assertIn('value="s = &quot;&lt;b&gt;&quot;"', out)

    def test_no_plus_and_no_box_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        for model in ({}, adding('x = 1'), editing(1, 'count += 2')):
            with self.subTest(model=model):
                out = visualize(table(), model)
                self.assertNotIn('<input', out)
                self.assertEqual(events_in(out), [])


class TestUpdate(unittest.TestCase):
    def test_ignores_a_step_the_table_no_longer_offers(self):
        # The editor can still send an old button's event string.
        event = {'pythonEventStr': "AddStep(accumulator='count', value='1')", 'eventJSON': {}}
        self.assertEqual(update(event, None, {}, table()), ({}, []))

    def test_ignores_events_it_does_not_know(self):
        for event in ({'pythonEventStr': 'MouseMove()'}, {'pythonEventStr': ''}, {}, None):
            with self.subTest(event=event):
                self.assertEqual(update(event, None, {}, table()), ({}, []))


class TestAddColumn(unittest.TestCase):
    """The (+) opens a box; what is typed in it is written as a line at the end
    of the loop's body, where it becomes the table's last column."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_plus_opens_an_empty_box(self):
        model, cmds = update(click(AddColumnClick()), None, {}, table())
        self.assertEqual((model, cmds), (adding(''), []))

    def test_typing_fills_the_box(self):
        model, cmds = update(typed('doubled = element * 2'), None, adding('d'), table())
        self.assertEqual((model, cmds), (adding('doubled = element * 2'), []))

    def test_enter_writes_the_line_at_the_end_of_the_body_and_closes_the_box(self):
        model, cmds = update(key('Enter'), None, adding('  doubled = element * 2 '), table())
        self.assertEqual(cmds, [InsertLines(((3, '    doubled = element * 2'),))])
        self.assertFalse(model['adding_column'])

    def test_tab_writes_it_too(self):
        _, cmds = update(key('Tab'), None, adding('doubled = element * 2'), table())
        self.assertEqual(cmds, [InsertLines(((3, '    doubled = element * 2'),))])

    def test_the_line_is_indented_like_the_body_and_goes_in_before_an_else(self):
        t = table(line=5, end_line=9, indent='    ', body_indent='        ', body_lines=(6, 7))
        _, cmds = update(key('Enter'), None, adding('arr2.append(element)'), t)
        self.assertEqual(cmds, [InsertLines(((7, '        arr2.append(element)'),))])

    def test_a_blank_box_writes_nothing(self):
        model, cmds = update(key('Enter'), None, adding('   '), table())
        self.assertEqual(cmds, [])
        self.assertFalse(model['adding_column'])

    def test_a_line_that_is_not_python_is_not_written_and_the_box_stays(self):
        model, cmds = update(key('Enter'), None, adding('doubled = element *'), table())
        self.assertEqual((model, cmds), (adding('doubled = element *'), []))

    def test_escape_closes_the_box_without_writing(self):
        model, cmds = update(key('Escape'), None, adding('doubled = element * 2'), table())
        self.assertEqual(cmds, [])
        self.assertFalse(model['adding_column'])

    def test_leaving_the_box_closes_it_without_writing(self):
        # Unlike a table's column, which is only a view: this is code, and a
        # half-typed line written into the loop would break it.
        blur = {'pythonEventStr': repr(ColumnInputBlur()), 'eventJSON': {}}
        model, cmds = update(blur, None, adding('doubled = element * 2'), table())
        self.assertEqual(cmds, [])
        self.assertFalse(model['adding_column'])

    def test_keys_do_nothing_while_no_box_is_open(self):
        for name in ('Enter', 'Escape', 'ArrowDown'):
            with self.subTest(key=name):
                self.assertEqual(update(key(name), None, {}, table()), ({}, []))

    def test_writes_nothing_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        _, cmds = update(key('Enter'), None, adding('doubled = element * 2'), table())
        self.assertEqual(cmds, [])



class TestEditColumn(unittest.TestCase):
    """Double-clicking a column's header opens a box holding its statement, as
    a table's does; Enter writes what it then holds over the statement."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_statements_header_can_be_edited_and_deleted_and_a_bound_names_cannot(self):
        cells = header_cells(visualize(table(), {}))
        self.assertEqual([events_in(c) for c in cells], [
            [],
            [],
            [repr(ColumnClick(col=1, label='count += 1')), repr(DeleteColumnClick(col=1, label='count += 1'))],
        ])

    def test_a_double_click_opens_the_box_holding_the_statement(self):
        model, cmds = update(click(ColumnClick(col=1, label='count += 1'), detail=2), None, {}, table())
        self.assertEqual((model, cmds), (editing(1, 'count += 1'), []))

    def test_a_single_click_does_nothing(self):
        self.assertEqual(update(click(ColumnClick(col=1, label='count += 1')), None, {}, table()), ({}, []))

    def test_the_box_takes_the_header_it_edits_with_the_statement_selected(self):
        cells = header_cells(visualize(table(), editing(1, 'count += 2')))
        self.assertEqual(len(cells), 3)
        box = re.search(r'<input[^>]*>', cells[2]).group(0)
        self.assertIn('value="count += 2"', box)
        self.assertIn('autofocus', box)
        self.assertIn('snc-select-all', box)
        self.assertNotIn('<input', cells[1])

    def test_enter_writes_it_over_the_statement(self):
        model, cmds = update(key('Enter'), None, editing(1, ' count += 2 '), table())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    count += 2')])
        self.assertEqual(model['editing_column'], None)

    def test_a_statement_over_several_lines_is_written_over_whole(self):
        t = table(spans=(None, (3, 5)), body_lines=(3, 5))
        _, cmds = update(key('Enter'), None, editing(1, 'count += 2'), t)
        self.assertEqual(cmds, [ReplaceLines(3, 5, '    count += 2')])

    def test_an_unchanged_statement_is_not_rewritten(self):
        model, cmds = update(key('Enter'), None, editing(1, 'count += 1'), table())
        self.assertEqual(cmds, [])
        self.assertEqual(model['editing_column'], None)

    def test_a_line_that_is_not_python_is_not_written_and_the_box_stays(self):
        model, cmds = update(key('Enter'), None, editing(1, 'count +='), table())
        self.assertEqual((model, cmds), (editing(1, 'count +='), []))

    def test_escape_and_leaving_close_it_without_writing(self):
        blur = {'pythonEventStr': repr(ColumnInputBlur()), 'eventJSON': {}}
        for event in (key('Escape'), blur):
            with self.subTest(event=event):
                model, cmds = update(event, None, editing(1, 'count += 2'), table())
                self.assertEqual(cmds, [])
                self.assertEqual(model['editing_column'], None)

    def test_ignores_a_column_the_table_no_longer_has(self):
        # The click was drawn against the code as it was; the loop has since
        # changed under it.
        for msg in (ColumnClick(col=1, label='count += 5'), ColumnClick(col=0, label='element'),
                    ColumnClick(col=7, label='count += 1')):
            with self.subTest(msg=msg):
                self.assertEqual(update(click(msg, detail=2), None, {}, table()), ({}, []))

    def test_writes_nothing_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        _, cmds = update(key('Enter'), None, editing(1, 'count += 2'), table())
        self.assertEqual(cmds, [])


class TestDeleteColumn(unittest.TestCase):
    """The x on a column's header deletes the statement the column is."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def two_statements(self):
        return table(end_line=4, columns=('element', 'count += 1', 'twice = element * 2'),
                     rows=(('1', '1', '2'),), spans=(None, (3, 3), (4, 4)), body_lines=(3, 4))

    def test_deletes_the_statement(self):
        _, cmds = update(click(DeleteColumnClick(col=2, label='twice = element * 2')), None, {}, self.two_statements())
        self.assertEqual(cmds, [ReplaceLines(4, 4, None)])

    def test_the_last_statement_in_the_body_leaves_a_pass(self):
        _, cmds = update(click(DeleteColumnClick(col=1, label='count += 1')), None, {}, table())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    pass')])

    def test_ignores_a_bound_name_and_a_column_the_table_no_longer_has(self):
        for msg in (DeleteColumnClick(col=0, label='element'), DeleteColumnClick(col=1, label='count += 5')):
            with self.subTest(msg=msg):
                self.assertEqual(update(click(msg), None, {}, table()), ({}, []))

    def test_writes_nothing_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        _, cmds = update(click(DeleteColumnClick(col=1, label='count += 1')), None, {}, table())
        self.assertEqual(cmds, [])


class TestWhileTheLoopRuns(unittest.TestCase):
    """The table logged as the loop starts has no rows yet, and the finished
    one replaces it a moment later. Drawn empty, it would shrink and regrow the
    table on every run -- every key typed in its box -- so it draws the rows
    the loop had last time instead."""

    def test_a_running_table_draws_the_rows_the_finished_one_last_had(self):
        model = {}
        finished = visualize(table(hidden_rows=4), model)
        self.assertEqual(visualize(table(rows=(), running=True), model), finished)

    def test_remembered_rows_are_matched_to_the_columns_by_label(self):
        model = {}
        visualize(table(), model)
        out = visualize(table(columns=('element', 'twice = element * 2', 'count += 1'), rows=(),
                              spans=(None, (3, 3), (4, 4)), running=True), model)
        cells = re.findall(r'<td class="list-table-cell">(.*?)</td>', out)
        self.assertEqual([html.unescape(re.sub(r'<[^>]*>', '', c)) for c in cells],
                         ['1', '—', '1', '2', '—', '2'])

    def test_with_nothing_remembered_it_draws_no_rows(self):
        out = visualize(table(rows=(), running=True), {})
        self.assertNotIn('<td', out)


if __name__ == '__main__':
    unittest.main()
