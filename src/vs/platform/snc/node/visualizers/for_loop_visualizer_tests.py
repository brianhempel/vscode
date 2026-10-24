"""
Tests for for_loop_visualizer.py - a finished `for` loop drawn as a table of
its iterations, with a (+) that writes a line of the user's own into it,
headers that edit or delete the line a column is, an init row that sets where
an accumulator starts, and a column menu that collects a column into a list.

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
from for_loop_visualizer import (AddColumnClick, CollectClick, ColumnClick, ColumnInput, ColumnInputBlur,
                                 ColumnKeyDown, DeleteColumnClick, InitCellClick, can_visualize, init_model,
                                 update, visualize)
from visualizer_utils import ForLoopColumn, ForLoopTable, InsertLines, ReplaceLines


def bound(name):
    """The column of a name the loop binds."""
    return ForLoopColumn(name, subject=name)


def statement(label, line, subject=None, underline=None, **fields):
    """The column of a one-line statement on `line`, showing `subject`, which
    starts its label."""
    if underline is None:
        underline = len(subject) if subject else 0
    return ForLoopColumn(label, span=(line, line), subject=subject, underline=underline, **fields)


COUNT = statement('count += 1', 3, 'count', accumulator=True, init_span=(1, 1))


def table(**overrides):
    """The loop in

        1  count = 0
        2  for element in [1, 2]:
        3      count += 1

    as the runner logs it on line 3 once it ends."""
    fields = dict(
        line=2, end_line=3, indent='', body_indent='    ',
        columns=(bound('element'), COUNT),
        rows=(('1', '1'), ('2', '2')),
        targets=('element',),
        defined=frozenset({'count', 'element'}),
        body_lines=(3, 3),
        init=(None, '0'),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


def plain(**overrides):
    """A loop with no accumulator, so no init row:

        1  for element in [1, 2]:
        2      twice = element * 2
    """
    fields = dict(line=1, end_line=2, columns=(bound('element'), statement('twice = element * 2', 2, 'twice')),
                  rows=(('1', '2'), ('2', '4')), defined=frozenset({'element', 'twice'}), body_lines=(2, 2),
                  init=(None, None))
    fields.update(overrides)
    return table(**fields)


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
    return {'adding_column': True, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, 'column_input': text}


def editing(col, text):
    """The model while column `col`'s box is open holding `text`."""
    return {'adding_column': False, 'editing_column': col, 'editing_init': None,
            'collecting_column': None, 'column_input': text}


def header_cells(html_text):
    """Each <th> of the header row."""
    return re.findall(r'<th[^>]*>.*?</th>', re.search(r'<thead.*?</thead>', html_text).group(0))


def header_labels(html_text):
    """The text of each header, without its menu or its x."""
    return [text_of(re.sub(r'<span class="snc-dropdown-trigger for-loop-col-menu".*?</div></div></span>'
                           r'|<span class="for-loop-col-delete".*?</span>', '', c))
            for c in header_cells(html_text)]


def body_rows(html_text):
    """Each <tr> of the body, as the text of its cells."""
    body = re.search(r'<tbody>(.*?)</tbody>', html_text).group(1)
    return [[html.unescape(re.sub(r'<[^>]*>', '', c)) for c in re.findall(r'<td[^>]*>.*?</td>', tr)]
            for tr in re.findall(r'<tr[^>]*>.*?</tr>', body)]


def text_of(html_text):
    return html.unescape(re.sub(r'<[^>]*>', '', html_text))


def init_editing(col, text):
    """The model while column `col`'s starting value box is open holding `text`."""
    return {'adding_column': False, 'editing_column': None, 'editing_init': col,
            'collecting_column': None, 'column_input': text}


def collecting(col, text):
    """The model while the box naming the list column `col` is collected into
    is open holding `text`."""
    return {'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': col, 'column_input': text}


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
        out = visualize(plain(), init_model(plain()))
        self.assertEqual(header_labels(out), ['itr', 'element', 'twice = element * 2'])
        self.assertEqual(body_rows(out), [['0', '1', '2'], ['1', '2', '4']])

    def test_is_drawn_as_a_table_so_it_gets_a_line_of_its_own(self):
        self.assertIn('list-table-scroll', visualize(table(), init_model(table())))

    def test_cells_are_escaped(self):
        out = visualize(table(columns=(bound('s'),), rows=(("'<b>'",),), init=(None,)), {})
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
            [repr(CollectClick(col=0, label='element'))],
            [repr(ColumnClick(col=1, label='count += 1')), repr(CollectClick(col=1, label='count += 1')),
             repr(DeleteColumnClick(col=1, label='count += 1'))],
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
        t = table(columns=(bound('element'), ForLoopColumn('count += 1', span=(3, 5), subject='count')),
                  body_lines=(3, 5))
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
        return table(end_line=4, columns=(bound('element'), COUNT, statement('twice = element * 2', 4, 'twice')),
                     rows=(('1', '1', '2'),), body_lines=(3, 4), init=(None, '0', None))

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
        out = visualize(table(columns=(bound('element'), statement('twice = element * 2', 3, 'twice'),
                                       statement('count += 1', 4, 'count', accumulator=True)),
                              rows=(), running=True, init=(None, None, '0')), model)
        self.assertEqual(body_rows(out)[1:], [['0', '1', '—', '1'], ['1', '2', '—', '2']])

    def test_with_nothing_remembered_it_draws_no_rows_but_the_init_row(self):
        out = visualize(table(rows=(), running=True), {})
        self.assertEqual(body_rows(out), [['init', '', '0']])


class TestUnderline(unittest.TestCase):
    """A statement isn't a value, so its header underlines the part of it
    that is the value its column shows: what it assigns, or what it calls a
    method on."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_statements_header_underlines_what_it_shows(self):
        t = table(columns=(bound('element'), COUNT, statement('arr2.append(element)', 4, 'arr2', in_place=True),
                           statement('d[element] = 1', 5, None, underline=10)),
                  init=(None, '0', None, None))
        for live_only in (False, True):
            with self.subTest(live_only=live_only):
                visualizer_utils.set_live_only(live_only)
                cells = header_cells(visualize(t, {}))
                self.assertEqual([re.findall(r'<span class="for-loop-col-subject">([^<]*)</span>', c) for c in cells],
                                 [[], [], ['count'], ['arr2'], ['d[element]']])

    def test_a_name_the_loop_binds_is_not_underlined(self):
        cells = header_cells(visualize(table(), {}))
        self.assertNotIn('for-loop-col-subject', cells[1])

    def test_the_underlined_part_is_escaped(self):
        t = table(columns=(bound('element'), statement('d["<"] = 1', 3, None, underline=6)), init=(None, None))
        self.assertIn('<span class="for-loop-col-subject">d[&quot;&lt;&quot;]</span> = 1', visualize(t, {}))


class TestInitRow(unittest.TestCase):
    """Above the first iteration, a row for where each accumulator starts: its
    value before the loop. Double-clicking it sets that value, by rewriting
    the line that set it or writing one in above the loop."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_init_row_is_above_the_first_iteration_and_only_accumulators_have_one(self):
        self.assertEqual(body_rows(visualize(table(), {})), [['init', '', '0'], ['0', '1', '1'], ['1', '2', '2']])

    def test_a_loop_without_an_accumulator_has_no_init_row(self):
        self.assertNotIn('init', [row[0] for row in body_rows(visualize(plain(), {}))])

    def test_an_accumulator_with_no_starting_value_asks_for_one(self):
        out = visualize(table(init=(None, None)), {})
        self.assertEqual(body_rows(out)[0], ['init', '', 'set…'])
        self.assertIn('for-loop-init-unset', out)

    def test_an_accumulators_init_cell_is_clickable_unfocused(self):
        out = visualize(table(), {})
        row = re.search(r'<tr class="for-loop-init-row">.*?</tr>', out).group(0)
        self.assertEqual(events_in(row), [repr(InitCellClick(col=1, label='count += 1'))])
        self.assertIn('data-tooltip="Double-click to set where it starts"', row)

    def test_a_double_click_opens_the_box_holding_the_starting_value(self):
        model, cmds = update(click(InitCellClick(col=1, label='count += 1'), detail=2), None, {}, table())
        self.assertEqual((model, cmds), (init_editing(1, '0'), []))

    def test_with_no_starting_value_the_box_opens_empty(self):
        model, _ = update(click(InitCellClick(col=1, label='count += 1'), detail=2), None, {}, table(init=(None, None)))
        self.assertEqual(model, init_editing(1, ''))

    def test_a_single_click_does_nothing(self):
        self.assertEqual(update(click(InitCellClick(col=1, label='count += 1')), None, {}, table()), ({}, []))

    def test_the_box_takes_the_init_cell_with_the_value_selected(self):
        out = visualize(table(), init_editing(1, '5'))
        row = re.search(r'<tr class="for-loop-init-row">.*?</tr>', out).group(0)
        box = re.search(r'<input[^>]*>', row).group(0)
        self.assertIn('value="5"', box)
        self.assertIn('autofocus', box)
        self.assertIn('snc-select-all', box)
        self.assertIn('snc-unfocused-clickable', box)
        self.assertEqual(len(header_cells(out)), 3)

    def test_typing_fills_the_box(self):
        self.assertEqual(update(typed('5'), None, init_editing(1, ''), table()), (init_editing(1, '5'), []))

    def test_enter_rewrites_the_line_that_set_it(self):
        model, cmds = update(key('Enter'), None, init_editing(1, ' 5 '), table())
        self.assertEqual(cmds, [ReplaceLines(1, 1, 'count = 5')])
        self.assertIsNone(model['editing_init'])

    def test_with_no_such_line_enter_writes_one_above_the_loop_indented_like_it(self):
        t = table(line=5, end_line=6, indent='    ', body_indent='        ', body_lines=(6, 6),
                  columns=(bound('element'), statement('arr2.append(element)', 6, 'arr2', accumulator=True,
                                                       in_place=True)),
                  init=(None, None))
        _, cmds = update(key('Enter'), None, init_editing(1, '[]'), t)
        self.assertEqual(cmds, [InsertLines(((4, '    arr2 = []'),))])

    def test_what_is_not_a_value_is_not_written_and_the_box_stays(self):
        for text in ('5 +', 'x = 1', '0\nimport os'):
            with self.subTest(text=text):
                self.assertEqual(update(key('Enter'), None, init_editing(1, text), table()),
                                 (init_editing(1, text), []))

    def test_an_unchanged_or_blank_value_is_not_written(self):
        for text in ('0', '  '):
            with self.subTest(text=text):
                model, cmds = update(key('Enter'), None, init_editing(1, text), table())
                self.assertEqual(cmds, [])
                self.assertIsNone(model['editing_init'])

    def test_escape_and_leaving_close_it_without_writing(self):
        blur = {'pythonEventStr': repr(ColumnInputBlur()), 'eventJSON': {}}
        for event in (key('Escape'), blur):
            with self.subTest(event=event):
                model, cmds = update(event, None, init_editing(1, '5'), table())
                self.assertEqual(cmds, [])
                self.assertIsNone(model['editing_init'])

    def test_ignores_a_column_that_is_not_an_accumulator_or_is_no_longer_there(self):
        for msg in (InitCellClick(col=0, label='element'), InitCellClick(col=1, label='count += 5'),
                    InitCellClick(col=4, label='count += 1')):
            with self.subTest(msg=msg):
                self.assertEqual(update(click(msg, detail=2), None, {}, table()), ({}, []))

    def test_nothing_to_click_or_write_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        out = visualize(table(), {})
        self.assertEqual(body_rows(out)[0], ['init', '', '0'])
        self.assertEqual(events_in(out), [])
        self.assertEqual(update(key('Enter'), None, init_editing(1, '5'), table())[1], [])


class TestAddingAnAccumulatorAsksWhereItStarts(unittest.TestCase):
    """A column added with the (+) that updates a name nothing has set yet --
    `arr2.append(element)` with no arr2 -- dies on the loop's first iteration.
    When the table comes back with it, its starting value box is already open."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def with_arr2(self, init='[]', **overrides):
        column = statement('arr2.append(element)', 4, 'arr2', accumulator=True, in_place=True)
        return table(end_line=4, columns=(bound('element'), COUNT, column), body_lines=(3, 4),
                     init=(None, '0', init), **overrides)

    def added(self, text='  arr2.append(element) '):
        model, _ = update(key('Enter'), None, adding(text), table())
        return model

    def test_the_new_column_opens_its_box_when_it_has_no_starting_value(self):
        model = self.added()
        out = visualize(self.with_arr2(init=None, rows=()), model)
        self.assertEqual(model['editing_init'], 2)
        row = re.search(r'<tr class="for-loop-init-row">.*?</tr>', out).group(0)
        self.assertIn('autofocus', re.search(r'<input[^>]*>', row).group(0))
        # Once: closing it leaves it closed.
        model, _ = update(key('Escape'), None, model, self.with_arr2(init=None))
        visualize(self.with_arr2(init=None), model)
        self.assertIsNone(model['editing_init'])

    def test_not_when_it_already_has_one(self):
        model = self.added()
        visualize(self.with_arr2(), model)
        self.assertIsNone(model.get('editing_init'))
        visualize(self.with_arr2(init=None), model)
        self.assertIsNone(model.get('editing_init'))

    def test_not_for_a_column_that_does_not_carry_over(self):
        model = self.added('twice = element * 2')
        t = table(end_line=4, columns=(bound('element'), COUNT, statement('twice = element * 2', 4, 'twice')),
                  init=(None, '0', None))
        visualize(t, model)
        self.assertIsNone(model.get('editing_init'))

    def test_the_run_the_enter_came_in_on_does_not_forget_it(self):
        """That run goes on to draw the loop as it was, before the line is
        written: both its tables, running and finished, are the old ones."""
        model = self.added()
        visualize(table(rows=(), running=True), model)
        visualize(table(), model)
        visualize(self.with_arr2(init=None), model)
        self.assertEqual(model['editing_init'], 2)

    def test_a_finished_table_whose_columns_changed_some_other_way_forgets_it(self):
        model = self.added()
        visualize(plain(), model)
        visualize(self.with_arr2(init=None), model)
        self.assertIsNone(model.get('editing_init'))


class TestCollect(unittest.TestCase):
    """A column's menu collects the column into a list: one above the loop,
    and a line at the end of its body appending to it -- which comes back as
    a column of its own, starting from []."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_menu_is_on_every_column_showing_a_name_it_can_collect(self):
        t = table(columns=(bound('element'), COUNT, statement('arr2.append(element)', 4, 'arr2', in_place=True,
                                                              accumulator=True),
                           statement('d[element] = 1', 5, None, underline=10)),
                  init=(None, '0', '[]', None))
        cells = header_cells(visualize(t, {}))
        # A list appended to in place is one object in every row; there is
        # no name to collect in d[element].
        self.assertEqual([[e for e in events_in(c) if e.startswith('CollectClick')] for c in cells],
                         [[], [repr(CollectClick(col=0, label='element'))],
                          [repr(CollectClick(col=1, label='count += 1'))], [], []])
        menu = re.search(r'<span class="snc-dropdown-trigger for-loop-col-menu"[^>]*>.*?</span></div></div></span>',
                         cells[1]).group(0)
        self.assertIn('data-hover-menu', menu)
        self.assertIn('Collect into List', menu)
        self.assertIn('snc-unfocused-clickable', menu)

    def test_no_menu_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        self.assertNotIn('CollectClick', html.unescape(visualize(table(), {})))

    def test_collect_opens_a_box_naming_the_list(self):
        model, cmds = update(click(CollectClick(col=0, label='element')), None, {}, table())
        self.assertEqual((model, cmds), (collecting(0, 'elements'), []))
        cells = header_cells(visualize(table(), model))
        self.assertEqual(len(cells), 4)
        box = re.search(r'<input[^>]*>', cells[-1]).group(0)
        self.assertIn('value="elements"', box)
        self.assertIn('snc-select-all', box)
        self.assertIn('autofocus', box)

    def test_the_name_offered_is_one_not_already_taken(self):
        t = table(columns=(bound('items'), statement('count += 1', 3, 'count', accumulator=True)),
                  defined=frozenset({'items', 'count', 'counts'}))
        for col, label, name in ((0, 'items', 'items_list'), (1, 'count += 1', 'counts2')):
            with self.subTest(label=label):
                model, _ = update(click(CollectClick(col=col, label=label)), None, {}, t)
                self.assertEqual(model['column_input'], name)

    def test_enter_writes_the_list_above_the_loop_and_the_append_at_the_end_of_the_body(self):
        model, cmds = update(key('Enter'), None, collecting(1, ' totals '), table())
        self.assertEqual(cmds, [InsertLines(((1, 'totals = []'), (3, '    totals.append(count)')))])
        self.assertIsNone(model['collecting_column'])

    def test_indented_like_the_loop_and_its_body(self):
        t = table(line=5, end_line=7, indent='    ', body_indent='        ', body_lines=(6, 6))
        _, cmds = update(key('Enter'), None, collecting(0, 'elements'), t)
        self.assertEqual(cmds, [InsertLines(((4, '    elements = []'), (6, '        elements.append(element)')))])

    def test_a_name_that_is_not_one_or_is_taken_is_not_written_and_the_box_stays(self):
        for text in ('2x', 'for', 'a b', 'count'):
            with self.subTest(text=text):
                self.assertEqual(update(key('Enter'), None, collecting(0, text), table()),
                                 (collecting(0, text), []))

    def test_blank_escape_and_leaving_close_it_without_writing(self):
        blur = {'pythonEventStr': repr(ColumnInputBlur()), 'eventJSON': {}}
        for model, event in ((collecting(0, ' '), key('Enter')), (collecting(0, 'xs'), key('Escape')),
                             (collecting(0, 'xs'), blur)):
            with self.subTest(event=event):
                model, cmds = update(event, None, model, table())
                self.assertEqual(cmds, [])
                self.assertIsNone(model['collecting_column'])

    def test_ignores_a_column_the_table_no_longer_has_or_cannot_collect(self):
        t = table(columns=(bound('element'), statement('arr2.append(element)', 3, 'arr2', in_place=True)))
        for msg in (CollectClick(col=1, label='count += 1'), CollectClick(col=1, label='arr2.append(element)'),
                    CollectClick(col=3, label='element')):
            with self.subTest(msg=msg):
                self.assertEqual(update(click(msg), None, {}, t), ({}, []))

    def test_writes_nothing_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        self.assertEqual(update(key('Enter'), None, collecting(0, 'elements'), table())[1], [])


if __name__ == '__main__':
    unittest.main()
