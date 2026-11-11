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
import json
import re
import unittest
from dataclasses import replace

import visualizer_utils
from for_loop_visualizer import (AddColumnClick, AddMenuDismiss, AddMenuToggle, CollectClick, ColumnClick,
                                 ColumnHideAll, ColumnInput, ColumnInputBlur, ColumnKeyDown, ColumnMenuDismiss,
                                 ColumnMenuToggle, ColumnResize, ColumnShowAll, ColumnToggle, ComputeCodeClick,
                                 ComputeFreeInput, ComputeToggle, ConvertColumnClick, ConvertToggle,
                                 DeleteColumnClick, GroupByClick, InitCellClick, InsertColumnClick, LoadMoreRows,
                                 SubmenuDwell, SubmenuToggle, can_visualize, init_model, update, visualize,
                                 ColumnSearchInput, ColumnSearchOpSelect, ColumnSearchComposeSelect,
                                 FirstMatchToggle, SearchBoxInput, SortToggle, TallyExcludeToggle,
                                 TallyFilterInput, TallyItemToggle, TallySelectAll, TallySelectNone,
                                 TallySortSelect, SubcolExprInput, SubcolHideAll, SubcolShowAll, SubcolToggle,
                                 ActionButtonClick, PickToggle, RowActionClick, RowMenuToggle,
                                 ToolSelect)
from visualizer_utils import (CHILD_SOURCE_BINDER, NO_VALUE, AddImports, ChildEvent, ForLoopColumn, ForLoopTable,
                              InsertLines, Phantom, ReplaceLines)
from string_visualizer import CopyToClipboard
from table_visualizer import (DeselectChildren, ComputeHoleInput, ComputeExprInput,
                              _agg_child_key, ROW_AGGS, HISTOGRAM_AGG)


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
        values=((1, 1), (2, 2)),
        targets=('element',),
        defined=frozenset({'count', 'element'}),
        body_lines=(3, 3),
        init=(None, '0'),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


def plain(**overrides):
    """A loop with no accumulator, so an init row with nothing in it:

        1  for element in [1, 2]:
        2      twice = element * 2
    """
    fields = dict(line=1, end_line=2, columns=(bound('element'), statement('twice = element * 2', 2, 'twice')),
                  rows=(('1', '2'), ('2', '4')), values=((1, 2), (2, 4)),
                  defined=frozenset({'element', 'twice'}), body_lines=(2, 2),
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
            'collecting_column': None, 'grouping_column': None, 'column_input': text}


def editing(col, text):
    """The model while column `col`'s box is open holding `text`."""
    return {'adding_column': False, 'editing_column': col, 'editing_init': None,
            'collecting_column': None, 'grouping_column': None, 'column_input': text}


def header_cells(html_text):
    """Each <th> of the header row, an open menu and all."""
    return re.findall(r'<th[^>]*>.*?</th>', re.search(r'<thead.*?</thead>', html_text).group(0))


def col_menu_of(html_text):
    """The open column menu's panel, submenus and all, or None while shut."""
    found = re.search(r'<div class="snc-dropdown-panel flyout col-menu-panel[^"]*".*?</div><!--/col-menu-->', html_text, re.S)
    return found.group(0) if found else None


def menu_options(html_text):
    """The rows of the open column menu, as (text, selectable)."""
    menu = col_menu_of(html_text)
    return [(text_of(label), 'unselectable' not in cls)
            for cls, label in re.findall(
                r'<div class="snc-dropdown-option([^"]*)"[^>]*><span class="snc-dropdown-option-label[^"]*"[^>]*>'
                r'(.*?)</span>', menu)]


def submenu_rows(html_text):
    """The rows of the open submenu, as (text, checked, selectable)."""
    panel = re.search(r'<div class="snc-dropdown-panel flyout col-compute-panel[^"]*".*?</div><!--/submenu-->',
                      col_menu_of(html_text), re.S).group(0)
    rows = []
    for cls, body in re.findall(r'<div class="col-compute-row([^"]*)"[^>]*>(.*?)</div>', panel, re.S):
        if 'col-compute-row-aside' in cls:
            continue
        name = re.search(r'<span class="col-compute-name">(.*?)</span>', body)
        rows.append((text_of(name.group(1)) if name else '', ' checked' in cls, 'unselectable' not in cls))
    return rows


def header_labels(html_text):
    """The text of each header, without its ▾."""
    return [text_of(re.sub(r'<span class="snc-dropdown-trigger col-menu-trigger">.*', '', c))
            for c in header_cells(html_text)]


def body_rows(html_text):
    """Each <tr> of the body, as the text of its cells, without a row's ▾."""
    body = re.search(r'<tbody>(.*?)</tbody>', html_text, re.S).group(1)
    body = re.sub(r'<span class="snc-dropdown-trigger row-menu-trigger[^"]*">.*?</span></span>', '', body)
    return [[html.unescape(re.sub(r'<[^>]*>', '', c)) for c in re.findall(r'<td[^>]*>.*?</td>', tr)]
            for tr in re.findall(r'<tr[^>]*>.*?</tr>', body)]


def iteration_rows(html_text):
    """The body's rows after the init row, which is always the first."""
    rows = body_rows(html_text)
    assert rows[0][0] == 'init', rows[0]
    return rows[1:]


def text_of(html_text):
    return html.unescape(re.sub(r'<[^>]*>', '', html_text))


def init_editing(col, text):
    """The model while column `col`'s starting value box is open holding `text`."""
    return {'adding_column': False, 'editing_column': None, 'editing_init': col,
            'collecting_column': None, 'grouping_column': None, 'column_input': text}


def collecting(col, text):
    """The model while the box naming the list column `col` is collected into
    is open holding `text`."""
    return {'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': col, 'grouping_column': None, 'column_input': text}


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
        self.assertEqual(body_rows(out), [['init', '', ''], ['0', '1', '2'], ['1', '2', '4']])

    def test_is_drawn_as_a_table_so_it_gets_a_line_of_its_own(self):
        self.assertIn('list-table-scroll', visualize(table(), init_model(table())))

    def test_cells_are_escaped(self):
        out = visualize(table(columns=(bound('s'),), rows=(("'<b>'",),), init=(None,)), {})
        self.assertIn('&#x27;&lt;b&gt;&#x27;', out)
        self.assertNotIn('<b>', out)

    def test_an_iteration_that_never_reached_a_statement_shows_a_dash(self):
        out = visualize(table(rows=(('1', None),)), {})
        self.assertEqual(body_rows(out)[-1], ['0', '1', '—'])

    def test_says_how_many_iterations_it_leaves_out(self):
        self.assertIn('3 more iterations', visualize(table(hidden_rows=3), {}))
        self.assertIn('1 more iteration<', visualize(table(hidden_rows=1), {}))
        self.assertNotIn('more iteration', visualize(table(), {}))

    def test_has_no_step_buttons_under_the_table(self):
        out = visualize(table(targets=('i', 'element')), {})
        self.assertNotIn('AddStep', html.unescape(out))

    def test_the_plus_and_its_menu_work_without_the_table_being_focused(self):
        # The table only shows while the cursor is outside the loop, so it is
        # never the focused line: a press must not be spent pinning focus.
        for model in ({}, {'add_menu_open': True}):
            with self.subTest(model=model):
                out = visualize(table(), model, small=True)
                buttons = re.findall(r'<span[^>]*snc-mouse-down[^>]*>', out)
                self.assertTrue(buttons)
                for button in buttons:
                    self.assertIn('snc-unfocused-clickable', button)
                    # A header is a drag handle too: the editor holds its
                    # press until the mouseup says no drag happened.
                    self.assertIn('draggable="true"' if 'snc-py-exps' in button else 'draggable="false"', button)

    def test_the_plus_is_a_bar_beside_the_table_drawn_focused_or_not(self):
        # A table's (+), except that a table only draws its own once it is
        # focused, and this one never is.
        for small in (True, False):
            with self.subTest(small=small):
                out = visualize(table(), {}, small=small)
                bar = re.search(r'</table></div>(<div class="snc-dropdown-trigger col-add-trigger">.*?</div>)', out)
                self.assertEqual(events_in(bar.group(1)), [repr(AddMenuToggle())])
                self.assertIn('<div class="list-table-scroll', out)
                self.assertNotIn('<input', re.search(r'<thead.*?</thead>', out).group(0))

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

    def test_add_column_in_the_plus_menu_puts_the_menu_away_and_opens_an_empty_box(self):
        model, cmds = update(click(AddColumnClick()), None, {'add_menu_open': True}, table())
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



def words():
    """`table()` over strings: `for element in ['a', 'b']`."""
    return table(rows=(("'a'", '1'), ("'b'", '2')), values=(('a', 1), ('b', 2)))


class TestAnExpressionAloneIsNamed(unittest.TestCase):
    """A column shows the value a line leaves in a name, and an expression
    alone leaves it nowhere: Enter writes it assigned to a fresh name."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def test_an_expression_is_written_assigned_to_result(self):
        model, cmds = update(key('Enter'), None, adding(' element * 2 '), table())
        self.assertEqual((cmds, model['pending_init']['label']),
                         ([InsertLines(((3, '    result = element * 2'),))], 'result = element * 2'))

    def test_the_name_steps_past_one_the_loop_already_has(self):
        t = table(defined=frozenset({'count', 'element', 'result', 'result2'}))
        _, cmds = update(key('Enter'), None, adding('len(str(element))'), t)
        self.assertEqual(cmds, [InsertLines(((3, '    result3 = len(str(element))'),))])

    def test_a_method_called_on_a_name_holding_a_string_is_named(self):
        # A string can't change, so the name after the call is the name before it.
        _, cmds = update(key('Enter'), None, adding('element.upper()'), words())
        self.assertEqual(cmds, [InsertLines(((3, '    result = element.upper()'),))])

    def test_what_is_left_as_written(self):
        # A method called on a name that can change is a column already --
        # the name after the call -- and a print is there for what it prints.
        t = table(values=(([1], 1), ([2], 2)))
        for line in ('element.append(1)', 'arr2.append(element)', 'print(element)', 'total = element', '...'):
            with self.subTest(line=line):
                _, cmds = update(key('Enter'), None, adding(line), t)
                self.assertEqual(cmds, [InsertLines(((3, f'    {line}'),))])

    def test_editing_a_column_into_an_expression_names_it(self):
        _, cmds = update(key('Enter'), None, editing(1, 'count * 2'), table())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    result = count * 2')])


def menu_of(html_text):
    """The panel the (+) opens, or None while it is shut."""
    found = re.search(r'<div class="snc-dropdown-panel[^"]*col-add-panel".*?</div>(?=</div></div>)', html_text)
    return found.group(0) if found else None


def menu_rows(html_text):
    """Each row of the (+) menu as (text, checked), checked being None for a
    row with no box; a separator is '--'."""
    rows = []
    for row in re.findall(r'<div class="col-compute-(?:row[^"]*"><span.*?</span></div>|sep"></div>)',
                          menu_of(html_text)):
        if 'col-compute-sep' in row:
            rows.append('--')
        elif 'col-tally-check' in row:
            rows.append((text_of(row), ' checked' in re.search(r'<input[^>]*>', row).group(0)))
        else:
            rows.append((text_of(row), None))
    return rows


class TestAddMenu(unittest.TestCase):
    """The (+) opens the menu a table's does: Add Column, then the names the
    loop binds, then Show all and Hide all over the lines of its body. A box
    shows or hides a column of the table; the code is the x's to delete."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_plus_opens_and_shuts_the_menu(self):
        model, cmds = update(click(AddMenuToggle()), None, {}, table())
        self.assertEqual((model, cmds), ({'add_menu_open': True}, []))
        model, cmds = update(click(AddMenuToggle()), None, model, table())
        self.assertEqual((model, cmds), ({'add_menu_open': False}, []))

    def test_shut_until_the_plus_is_pressed(self):
        self.assertIsNone(menu_of(visualize(table(), {})))

    def test_add_column_then_the_bound_names_then_show_and_hide_all_over_the_statements(self):
        t = table(columns=(bound('i'), bound('element'), COUNT, statement('twice = element * 2', 4, 'twice')),
                  rows=(('0', '1', '1', '2'),), init=(None, None, '0', None))
        out = visualize(t, {'add_menu_open': True, 'hidden_columns': ['twice = element * 2']})
        self.assertEqual(menu_rows(out), [
            ('Add Column', None), ('Add If', None), '--',
            ('i', True), ('element', True), '--',
            ('Show all', None), ('Hide all', None), '--',
            ('count += 1', True), ('twice = element * 2', False)])
        from for_loop_visualizer import AddIfClick
        self.assertEqual(events_in(menu_of(out)), [
            repr(AddColumnClick()), repr(AddIfClick()),
            repr(ColumnToggle(label='i')), repr(ColumnToggle(label='element')),
            repr(ColumnShowAll()), repr(ColumnHideAll()),
            repr(ColumnToggle(label='count += 1')), repr(ColumnToggle(label='twice = element * 2'))])

    def test_a_loop_with_no_statement_of_its_own_has_nothing_under_the_pair(self):
        t = table(columns=(bound('element'),), rows=(('1',),), init=(None,))
        self.assertEqual(menu_rows(visualize(t, {'add_menu_open': True})),
                         [('Add Column', None), ('Add If', None), '--', ('element', True), '--', ('Show all', None),
                          ('Hide all', None)])

    def test_the_menu_is_put_away_by_a_click_anywhere_else_and_lights_the_plus(self):
        out = visualize(table(), {'add_menu_open': True})
        self.assertIn(f'snc-dismiss="{html.escape(repr(AddMenuDismiss()))}"', menu_of(out))
        self.assertIn('col-add-icon full-opacity-on-hover open', out)
        model, _ = update({'pythonEventStr': repr(AddMenuDismiss()), 'eventJSON': {}}, None,
                          {'add_menu_open': True}, table())
        self.assertFalse(model['add_menu_open'])

    def test_unticking_a_column_hides_it_and_its_init_cell_and_ticking_it_brings_it_back(self):
        model, cmds = update(click(ColumnToggle(label='count += 1')), None, {'add_menu_open': True}, table())
        # Left open, as a table's is: ticking several in a row is what a list
        # of boxes is for.
        self.assertEqual((model, cmds), ({'add_menu_open': True, 'hidden_columns': ['count += 1']}, []))
        out = visualize(table(), model)
        self.assertEqual(header_labels(out), ['itr', 'element'])
        self.assertEqual(body_rows(out), [['init', ''], ['0', '1'], ['1', '2']])
        model, _ = update(click(ColumnToggle(label='count += 1')), None, model, table())
        self.assertEqual(model['hidden_columns'], [])
        self.assertEqual(header_labels(visualize(table(), model)), ['itr', 'element', 'count += 1'])

    def test_a_bound_name_can_be_hidden_too(self):
        model, _ = update(click(ColumnToggle(label='element')), None, {}, table())
        out = visualize(table(), model)
        self.assertEqual(header_labels(out), ['itr', 'count += 1'])
        self.assertEqual(body_rows(out), [['init', '0'], ['0', '1'], ['1', '2']])

    def test_hide_all_and_show_all_reach_the_statements_and_leave_the_bound_names(self):
        t = plain(columns=(bound('element'), statement('twice = element * 2', 2, 'twice'),
                           statement('print(twice)', 3)), rows=(('1', '2', 'None'),), init=(None, None, None))
        model, _ = update(click(ColumnHideAll()), None, {'add_menu_open': True}, t)
        self.assertEqual(header_labels(visualize(t, model)), ['itr', 'element'])
        self.assertTrue(model['add_menu_open'])
        model, _ = update(click(ColumnToggle(label='element')), None, model, t)
        model, _ = update(click(ColumnShowAll()), None, model, t)
        self.assertEqual(header_labels(visualize(t, model)), ['itr', 'twice = element * 2', 'print(twice)'])

    def test_a_hidden_column_is_known_by_its_label_so_an_edited_line_comes_back(self):
        model = {'hidden_columns': ['count += 1']}
        t = table(columns=(bound('element'), statement('count += 2', 3, 'count', accumulator=True)))
        self.assertEqual(header_labels(visualize(t, model)), ['itr', 'element', 'count += 2'])

    def test_events_on_hidden_columns_still_name_the_column_they_were_drawn_for(self):
        t = plain(columns=(bound('element'), statement('twice = element * 2', 2, 'twice'),
                           statement('print(twice)', 3)), rows=(('1', '2', 'None'),), init=(None, None, None))
        out = visualize(t, {'hidden_columns': ['twice = element * 2']})
        self.assertIn(repr(ColumnClick(col=2, label='print(twice)')), events_in(out))

    def test_no_menu_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        out = visualize(table(), {'add_menu_open': True})
        self.assertIsNone(menu_of(out))
        self.assertEqual(events_in(out), [])


def many(n):
    """plain(), run for `n` iterations."""
    return plain(rows=tuple((str(i), str(2 * i)) for i in range(n)))


class TestChrome(unittest.TestCase):
    """What a table has around its rows: a pane as tall as a table's, focused
    or not, a count of what is in it, a page of rows at a time, and columns
    that can be dragged wider."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_pane_is_as_tall_as_a_tables_focused_or_not(self):
        self.assertIn('max-height: 600px', visualize(table(), {}, small=False))
        self.assertIn('max-height: 212px', visualize(table(), {}, small=True))

    def test_the_iteration_column_says_what_it_counts(self):
        out = visualize(table(), {})
        self.assertIn('<th class="row-index-header" data-tooltip="itr is the iteration, counting from 0">itr</th>', out)

    def test_a_page_of_rows_then_a_row_that_loads_more_then_the_last_few(self):
        out = visualize(many(60), {})
        rows = iteration_rows(out)
        self.assertEqual([r[0] for r in rows], [str(i) for i in range(50)] + ['Load 7 more'] + ['57', '58', '59'])
        self.assertIn(f'snc-mouse-down="{html.escape(repr(LoadMoreRows()))}"', out)

    def test_the_load_more_row_says_how_many_are_left_when_more_than_a_page(self):
        rows = body_rows(visualize(many(200), {}))
        self.assertIn(['Load 50 more (147 hidden)'], rows)

    def test_load_more_draws_another_page(self):
        model, cmds = update(click(LoadMoreRows()), None, {}, many(200))
        self.assertEqual((model, cmds), ({'shown_rows': 100}, []))
        rows = iteration_rows(visualize(many(200), model))
        self.assertEqual(len(rows), 100 + 1 + 3)

    def test_a_short_loop_draws_every_row(self):
        self.assertEqual(len(iteration_rows(visualize(many(52), {}))), 52)

    def test_load_more_works_unfocused(self):
        out = visualize(many(60), {}, small=True)
        cell = re.search(r'<td class="load-more"[^>]*>', out).group(0)
        self.assertIn('snc-unfocused-clickable', cell)

    def test_every_column_has_a_handle_to_drag_it_wider(self):
        out = visualize(table(), {})
        self.assertEqual(
            [html.unescape(e) for e in re.findall(r'snc-resize-col="([^"]*)"', out)],
            [repr(ColumnResize(width=0, label='element')), repr(ColumnResize(width=0, label='count += 1'))])

    def test_a_dragged_width_sticks_to_the_column_by_its_label(self):
        msg = {'pythonEventStr': repr(ColumnResize(width=120, label='count += 1')), 'eventJSON': {}}
        model, cmds = update(msg, None, {}, table())
        self.assertEqual((model, cmds), ({'widths': {'count += 1': 120}}, []))
        out = visualize(table(), model)
        styled = re.findall(r'<t[hd][^>]*min-width: 120px; max-width: 120px;[^>]*>', out)
        # Its header, its init cell and both its rows.
        self.assertEqual(len(styled), 4)

    def test_a_width_that_is_not_one_is_ignored(self):
        for width in (0, -5, True, 'wide'):
            with self.subTest(width=width):
                msg = {'pythonEventStr': repr(ColumnResize(width=width, label='element')), 'eventJSON': {}}
                self.assertEqual(update(msg, None, {}, table()), ({}, []))


def grouping(col, text):
    """The model while the box naming the dict column `col` groups by is open
    holding `text`."""
    return {'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, 'grouping_column': col, 'column_input': text}


def two_lines():
    """A loop with two statements of its own:

        1  total = 0
        2  for element in [1, 2]:
        3      twice = element * 2
        4      total += twice
    """
    return table(line=2, end_line=4, columns=(bound('element'), statement('twice = element * 2', 3, 'twice'),
                                              statement('total += twice', 4, 'total', accumulator=True,
                                                        init_span=(1, 1))),
                 rows=(('1', '2', '2'), ('2', '4', '6')), values=((1, 2, 2), (2, 4, 6)),
                 defined=frozenset({'element', 'twice', 'total'}), body_lines=(3, 4), init=(None, None, '0'))


class TestColumnMenu(unittest.TestCase):
    """A column's ▾ opens the menu a table's does -- Remove, Insert Left and
    Right, Group By, Change Type, Compute -- with Collect into List among them.
    A press opens it, as a table's does, and a click anywhere else puts it
    away."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_toggle_opens_one_columns_menu_and_puts_the_plus_menu_away(self):
        model, cmds = update(click(ColumnMenuToggle(label='count += 1')), None, {'add_menu_open': True}, table())
        self.assertEqual((model, cmds), ({'add_menu_open': False, 'col_menu': 'count += 1', 'submenu': None}, []))
        model, _ = update(click(ColumnMenuToggle(label='count += 1')), None, model, table())
        self.assertIsNone(model['col_menu'])
        model, _ = update(click(ColumnMenuToggle(label='element')), None, {'col_menu': 'count += 1'}, table())
        self.assertEqual(model['col_menu'], 'element')

    def test_a_click_anywhere_else_puts_it_away(self):
        out = visualize(table(), {'col_menu': 'count += 1'})
        self.assertIn(f'snc-dismiss="{html.escape(repr(ColumnMenuDismiss()))}"', col_menu_of(out))
        model, _ = update({'pythonEventStr': repr(ColumnMenuDismiss()), 'eventJSON': {}}, None,
                          {'col_menu': 'count += 1', 'submenu': 'compute'}, table())
        self.assertEqual((model['col_menu'], model['submenu']), (None, None))

    def test_shut_until_its_toggle_is_pressed_and_the_toggle_lights_while_open(self):
        self.assertIsNone(col_menu_of(visualize(table(), {})))
        self.assertIn('col-menu snc-hover-hidden full-opacity-on-hover open',
                      visualize(table(), {'col_menu': 'count += 1'}))

    def test_a_statements_menu(self):
        self.assertEqual(menu_options(visualize(table(), {'col_menu': 'count += 1'})), [
            ('Remove', True), ('Insert Left', True), ('Insert Right', True),
            ('Subcolumns', True), ('Sort', True), ('Group By', True), ('Change Type', True), ('Compute', True),
            ('Collect into List', True)])

    def test_a_bound_name_has_no_line_to_remove_or_put_anything_before(self):
        self.assertEqual(menu_options(visualize(table(), {'col_menu': 'element'})), [
            ('Remove', False), ('Insert Left', False), ('Insert Right', True),
            ('Subcolumns', True), ('Sort', True), ('Group By', True), ('Change Type', True), ('Compute', True),
            ('Collect into List', True)])

    def test_a_menu_works_without_the_table_being_focused(self):
        out = visualize(table(), {'col_menu': 'count += 1', 'submenu': 'compute'}, small=True)
        for button in re.findall(r'<(?:span|div)[^>]*snc-mouse-down[^>]*>', out):
            self.assertIn('snc-unfocused-clickable', button)

    def test_no_menu_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        out = visualize(table(), {'col_menu': 'count += 1'})
        self.assertIsNone(col_menu_of(out))
        self.assertNotIn('ColumnMenuToggle', html.unescape(out))

    def test_a_menu_for_a_column_the_table_no_longer_has_draws_shut(self):
        self.assertIsNone(col_menu_of(visualize(table(), {'col_menu': 'count += 2'})))

    # -- Insert Left / Right --------------------------------------------------

    def test_insert_opens_a_box_beside_the_column(self):
        for after, cells in ((True, ['itr', 'element', 'twice = element * 2', '', 'total += twice']),
                             (False, ['itr', 'element', '', 'twice = element * 2', 'total += twice'])):
            with self.subTest(after=after):
                model, cmds = update(click(InsertColumnClick(col=1, label='twice = element * 2', after=after)),
                                     None, {'col_menu': 'twice = element * 2'}, two_lines())
                self.assertEqual(cmds, [])
                self.assertIsNone(model.get('col_menu'))
                out = visualize(two_lines(), model)
                self.assertEqual(header_labels(out), cells)
                self.assertIn('autofocus', header_cells(out)[cells.index('')])

    def test_enter_writes_the_line_beside_the_statement(self):
        for after, line in ((True, 3), (False, 2)):
            with self.subTest(after=after):
                model, _ = update(click(InsertColumnClick(col=1, label='twice = element * 2', after=after)),
                                  None, {}, two_lines())
                model, _ = update(typed('half = element / 2'), None, model, two_lines())
                model, cmds = update(key('Enter'), None, model, two_lines())
                self.assertEqual(cmds, [InsertLines(((line, '    half = element / 2'),))])
                self.assertFalse(model['adding_column'])

    def test_right_of_a_bound_name_is_the_top_of_the_body(self):
        model, _ = update(click(InsertColumnClick(col=0, label='element', after=True)), None, {}, two_lines())
        model, _ = update(typed('half = element / 2'), None, model, two_lines())
        _, cmds = update(key('Enter'), None, model, two_lines())
        self.assertEqual(cmds, [InsertLines(((2, '    half = element / 2'),))])

    def test_left_of_a_bound_name_is_nowhere(self):
        self.assertEqual(update(click(InsertColumnClick(col=0, label='element', after=False)), None, {},
                                two_lines()), ({}, []))

    # -- Group By ---------------------------------------------------------------

    def test_group_by_opens_a_box_naming_the_dict(self):
        model, cmds = update(click(GroupByClick(col=1, label='twice = element * 2')), None,
                             {'col_menu': 'twice = element * 2'}, two_lines())
        self.assertEqual((model, cmds), (grouping(1, 'by_twice'), []))
        self.assertIn('value="by_twice"', visualize(two_lines(), model))

    def test_enter_writes_the_dict_above_the_loop_and_what_goes_in_it_at_the_end_of_the_body(self):
        _, cmds = update(key('Enter'), None, grouping(1, 'by_twice'), two_lines())
        self.assertEqual(cmds, [InsertLines(((1, 'by_twice = {}'),
                                             (4, '    by_twice.setdefault(twice, []).append(element)')))])

    def test_a_loop_binding_several_names_groups_all_of_them(self):
        t = two_lines()
        t = table(**{**{f: getattr(t, f) for f in ('line', 'end_line', 'rows', 'body_lines', 'init')},
                     'columns': (bound('i'), *t.columns), 'targets': ('i', 'element'),
                     'defined': t.defined | {'i'}})
        _, cmds = update(key('Enter'), None, grouping(2, 'by_twice'), t)
        self.assertEqual(cmds[0].lines[1], (4, '    by_twice.setdefault(twice, []).append((i, element))'))

    def test_a_name_already_taken_is_not_written(self):
        self.assertEqual(update(key('Enter'), None, grouping(1, 'total'), two_lines()),
                         (grouping(1, 'total'), []))

    # -- Change Type ------------------------------------------------------------

    def test_change_type_is_a_submenu_that_opens_on_a_press_or_a_rest(self):
        model, _ = update(click(SubmenuToggle(submenu='convert')), None, {'col_menu': 'element'}, table())
        self.assertEqual(model['submenu'], 'convert')
        model, _ = update(click(SubmenuToggle(submenu='convert')), None, model, table())
        self.assertIsNone(model['submenu'])
        model, _ = update({'pythonEventStr': repr(SubmenuDwell(submenu='compute')), 'eventJSON': {}}, None,
                          {'col_menu': 'element', 'submenu': 'convert'}, table())
        self.assertEqual(model['submenu'], 'compute')

    def test_resting_on_a_row_without_a_submenu_puts_the_open_one_away(self):
        out = visualize(table(), {'col_menu': 'count += 1', 'submenu': 'convert'})
        self.assertIn(f'snc-dwell="{html.escape(repr(SubmenuDwell(submenu=None)))}"', col_menu_of(out))
        # And nothing to do while none is.
        self.assertNotIn('SubmenuDwell(submenu=None)', html.unescape(col_menu_of(
            visualize(table(), {'col_menu': 'count += 1'}))))

    def test_an_assignments_types_and_which_one_it_reads_as(self):
        t = two_lines()
        out = visualize(t, {'col_menu': 'twice = element * 2', 'submenu': 'convert'})
        self.assertEqual(submenu_rows(out), [('int', False, True), ('float', False, True),
                                             ('str', False, True), ('bool', False, True)])
        t = table(**{**{f: getattr(t, f) for f in ('line', 'end_line', 'rows', 'body_lines', 'init', 'defined')},
                     'columns': (bound('element'), statement('twice = int(element * 2)', 3, 'twice'), t.columns[2])})
        out = visualize(t, {'col_menu': 'twice = int(element * 2)', 'submenu': 'convert'})
        self.assertEqual(submenu_rows(out)[0], ('int', True, True))

    def test_ticking_a_type_wraps_the_assignment_and_unticking_unwraps_it(self):
        _, cmds = update(click(ConvertToggle(col=1, label='twice = element * 2', to='int')), None, {}, two_lines())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    twice = int(element * 2)')])
        t = table(**{**{f: getattr(two_lines(), f) for f in ('line', 'end_line', 'rows', 'body_lines', 'init')},
                     'columns': (bound('element'), statement('twice = int(element * 2)', 3, 'twice'))})
        for to, line in (('int', '    twice = element * 2'), ('float', '    twice = float(element * 2)')):
            with self.subTest(to=to):
                _, cmds = update(click(ConvertToggle(col=1, label='twice = int(element * 2)', to=to)), None, {}, t)
                self.assertEqual(cmds, [ReplaceLines(3, 3, line)])

    def test_what_is_not_a_plain_assignment_cannot_be_wrapped(self):
        out = visualize(two_lines(), {'col_menu': 'total += twice', 'submenu': 'convert'})
        self.assertEqual([selectable for _, _, selectable in submenu_rows(out)], [False] * 4)
        self.assertEqual(update(click(ConvertToggle(col=2, label='total += twice', to='int')), None, {},
                                two_lines()), ({}, []))

    def test_the_new_column_rows_write_a_converted_copy_beside_it(self):
        _, cmds = update(click(ConvertColumnClick(col=2, label='total += twice', to='str')), None, {}, two_lines())
        self.assertEqual(cmds, [InsertLines(((4, '    total_str = str(total)'),))])
        _, cmds = update(click(ConvertColumnClick(col=0, label='element', to='float')), None, {}, two_lines())
        self.assertEqual(cmds, [InsertLines(((2, '    element_float = float(element)'),))])

    # -- Compute ----------------------------------------------------------------

    def test_compute_previews_every_answer_from_the_columns_values(self):
        out = visualize(two_lines(), {'col_menu': 'total += twice', 'submenu': 'compute'})
        rows = dict((name, selectable) for name, _, selectable in submenu_rows(out))
        self.assertTrue(rows['Sum'])
        preview = re.search(r'>Sum</span><span class="col-compute-preview">(.*?)</span>', out).group(1)
        self.assertEqual(text_of(preview), '8')

    def test_ticking_an_answer_keeps_it_under_the_table(self):
        model, cmds = update(click(ComputeToggle(label='total += twice', template='sum($)')), None,
                             {'col_menu': 'total += twice', 'submenu': 'compute'}, two_lines())
        self.assertEqual((model['computes'], cmds), ({'total += twice': ['sum($)']}, []))
        foot = re.search(r'<tfoot class="col-agg-rows">(.*?)</tfoot>', visualize(two_lines(), model)).group(1)
        cells = [text_of(c) for c in re.findall(r'<td[^>]*>.*?</td>', foot)]
        self.assertEqual(cells, ['', '', '', 'Sum✕8'])
        model, _ = update(click(ComputeToggle(label='total += twice', template='sum($)')), None, model, two_lines())
        self.assertEqual(model['computes'], {'total += twice': []})
        self.assertNotIn('<tfoot', visualize(two_lines(), model))

    def test_an_answer_of_your_own(self):
        model, _ = update({'pythonEventStr': repr(ComputeFreeInput(label='twice = element * 2', value='')),
                           'eventJSON': {}}, None, {}, two_lines())
        event = {'pythonEventStr': f"lambda e: ComputeFreeInput(label={'twice = element * 2'!r}, "
                                   f"value=e.get('value', ''))", 'eventJSON': {'value': 'max($) - min($)'}}
        model, _ = update(event, None, {'col_menu': 'twice = element * 2', 'submenu': 'compute'}, two_lines())
        model, _ = update(key('Enter'), None, model, two_lines())
        self.assertEqual(model['computes'], {'twice = element * 2': ['max($) - min($)']})
        self.assertIn('max($) - min($)', visualize(two_lines(), model))

    def test_compute_holes_and_labels_edit_in_place_even_with_stale_events(self):
        expr = 'np.percentile($, {{10}})'
        model = {'computes': {'element': [expr, 'sum($)']}}
        for previous, text in [('10', '2'), ('2', '25')]:
            model, commands = update(click(ComputeHoleInput('element', expr, 0, text, previous)),
                                     None, model, table())
            self.assertEqual(commands, [])
        self.assertEqual(model['computes']['element'], ['sum($)', 'np.percentile($, {{25}})'])
        out = visualize(table(), {**model, 'col_menu': 'element', 'submenu': 'compute'})
        self.assertIn('col-compute-hole search-box', out)
        self.assertIn('col-agg-hole', out)
        self.assertIn('value="25"', out)
        model, _ = update(click(ComputeExprInput('element', 'sum($)', 'max($) - min($)')),
                          None, model, table())
        out = visualize(table(), model)
        self.assertIn('col-agg-label col-agg-expr', out)
        self.assertIn('col-agg-x snc-hover-hidden', out)
        model, _ = update(click(ComputeExprInput('element', 'max($) - min($)', '')),
                          None, model, table())
        self.assertEqual(model['computes']['element'], ['np.percentile($, {{25}})'])

    def test_histogram_hole_can_be_edited_before_checking(self):
        model, _ = update(click(ComputeHoleInput('element', HISTOGRAM_AGG, 0, '2')),
                          None, {}, table())
        self.assertEqual(model['computes']['element'], [HISTOGRAM_AGG.replace('{{10}}', '{{2}}')])
        self.assertIn('col-agg-hist', visualize(table(), model, cells_of))

    def test_compute_answers_are_children_and_route_their_events(self):
        model = {'computes': {'element': ['sum($)']}}
        out = visualize(table(), model, cells_of)
        child = _agg_child_key('element', 'sum($)', 'element')
        child_event = {'pythonEventStr': repr(ChildEvent(child, 'Bump()')), 'eventJSON': {'type': 'mousedown'}}
        self.assertIn('<b class="fake">3:0:small</b>', out)
        model, _ = update(child_event, None, model, table(), cells_of)
        model, _ = update(child_event, None, model, table(), cells_of)
        out = visualize(table(), model, cells_of)
        self.assertIn('<b class="fake">3:1:big</b>', out)
        remove = html.unescape(re.search(r'class="col-agg-x[^>]*snc-mouse-down="([^"]+)"', out).group(1))
        model, commands = update({'pythonEventStr': remove, 'eventJSON': {}}, None, model, table(), cells_of)
        self.assertEqual(commands, [])
        self.assertEqual(model['computes']['element'], [])
        self.assertNotIn(child, model['children'])

    def test_min_max_item_return_bound_item_including_subcolumns(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"]}, 'computes': {leaf: list(ROW_AGGS)}}
        out = visualize(people(), model, cells_of)
        self.assertIn("{'name': 'Ann', 'age': 3}:0:small", out)
        self.assertIn("{'name': 'Bo', 'age': 5}:0:small", out)
        model, _ = update(click(ComputeHoleInput(leaf, 'np.percentile($, {{10}})', 0, '50')),
                          None, model, people())
        self.assertIn('np.percentile($, {{50}})', model['computes'][leaf])
        model, _ = update(click(ComputeExprInput(leaf, '', 'sum($)')),
                          None, model, people())
        self.assertIn('sum($)', model['computes'][leaf])
        t = table(columns=(bound('i'), bound('element'), COUNT), targets=('i', 'element'),
                  rows=(('0', '7', '1'), ('1', '3', '2')),
                  values=((0, 7, 1), (1, 3, 2)), init=(None, None, '0'))
        out = visualize(t, {'computes': {'element': list(ROW_AGGS)}}, cells_of)
        self.assertIn('(1, 3):0:small', out)
        self.assertIn('(0, 7):0:small', out)

    def test_unique_and_tally_write_what_collects_them(self):
        _, cmds = update(click(ComputeCodeClick(col=1, label='twice = element * 2', kind='unique')), None, {},
                         two_lines())
        self.assertEqual(cmds, [InsertLines(((1, 'unique_twice = set()'), (4, '    unique_twice.add(twice)')))])
        _, cmds = update(click(ComputeCodeClick(col=1, label='twice = element * 2', kind='tally')), None, {},
                         two_lines())
        self.assertEqual(cmds, [AddImports(('from collections import Counter',)),
                                InsertLines(((1, 'tally_twice = Counter()'), (4, '    tally_twice[twice] += 1')))])

    def test_sum_min_and_max_write_an_accumulator(self):
        for kind, lines in (('sum', ('sum_twice = 0', '    sum_twice += twice')),
                            ('min', ('min_twice = None',
                                     '    min_twice = twice if min_twice is None else min(min_twice, twice)')),
                            ('max', ('max_twice = None',
                                     '    max_twice = twice if max_twice is None else max(max_twice, twice)'))):
            with self.subTest(kind=kind):
                _, cmds = update(click(ComputeCodeClick(col=1, label='twice = element * 2', kind=kind)), None, {},
                                 two_lines())
                self.assertEqual(cmds, [InsertLines(((1, lines[0]), (4, lines[1])))])

    def test_a_column_with_no_name_of_its_own_computes_but_writes_nothing(self):
        t = two_lines()
        t = table(**{**{f: getattr(t, f) for f in ('line', 'end_line', 'rows', 'body_lines', 'init', 'defined',
                                                    'values')},
                     'columns': (*t.columns[:2], statement('d[element] = 1', 4, None, underline=10))})
        out = visualize(t, {'col_menu': 'd[element] = 1', 'submenu': 'compute'})
        rows = dict((name, selectable) for name, _, selectable in submenu_rows(out))
        self.assertEqual((rows['Sum'], rows['Unique'], rows['Tally']), (True, False, False))
        self.assertIn(('Group By', False), menu_options(out))
        self.assertEqual(update(click(ComputeCodeClick(col=2, label='d[element] = 1', kind='unique')), None, {}, t),
                         ({}, []))

    def test_a_running_table_has_no_values_to_compute_with(self):
        out = visualize(table(rows=(), values=(), running=True), {'col_menu': 'count += 1', 'submenu': 'compute'})
        rows = dict((name, selectable) for name, _, selectable in submenu_rows(out))
        self.assertFalse(rows['Sum'])


def scores():
    """A loop over five scores, counting the high ones:

        1  high = 0
        2  for score in [3, 9, 4, 9, 1]:
        3      high += score > 5
    """
    vals = [3, 9, 4, 9, 1]
    highs = [0, 1, 1, 2, 2]
    return table(line=2, end_line=3, columns=(bound('score'), statement('high += score > 5', 3, 'high',
                                                                       accumulator=True, init_span=(1, 1))),
                 rows=tuple((repr(v), repr(h)) for v, h in zip(vals, highs)),
                 values=tuple(zip(vals, highs)), targets=('score',), defined=frozenset({'score', 'high'}),
                 body_lines=(3, 3), init=(None, '0'))


def row_classes(html_text):
    """The class of each iteration's row, '' for none."""
    body = re.search(r'<tbody>(.*?)</tbody>', html_text, re.S).group(1)
    return [cls for cls, first in re.findall(r'<tr(?: class="([^"]*)")?><td class="row-index">(?:<div[^>]*>)?([^<]*)',
                                             body)
            if first != 'init']


def typed_into(event_lambda_attr, html_text, text):
    """The event typing `text` into the box whose snc-input starts as given."""
    found = re.search(r'snc-input="(' + re.escape(html.escape(event_lambda_attr)) + r'[^"]*)"', html_text)
    return {'pythonEventStr': html.unescape(found.group(1)), 'eventJSON': {'value': text}}


class TestSearch(unittest.TestCase):
    """A focused table's footer, as a table's: a search box that marks the
    iterations it matches and dims the rest, a 1st that keeps only the first,
    the count of what matched, and a tab counting every iteration. Nothing it
    does is written: a loop's iterations are not a list to filter."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_focused_table_has_a_search_box_and_counts_the_iterations(self):
        out = visualize(scores(), {}, small=False)
        self.assertIn('class="search-box"', out)
        self.assertIn('<div class="tiny-len">5 iterations</div>', out)
        self.assertIn('Count: 5', out)
        self.assertIn('1 iteration<', visualize(table(rows=(('1', '1'),), values=((1, 1),)), {}))
        self.assertIn('7 iterations', visualize(table(hidden_rows=5), {}))

    def test_not_while_small_or_live_only(self):
        self.assertNotIn('search-box', visualize(scores(), {}, small=True))
        visualizer_utils.set_live_only(True)
        self.assertNotIn('search-box', visualize(scores(), {}))

    def test_typing_a_condition_over_the_loops_names_marks_what_it_matches(self):
        model, cmds = update(typed_into('lambda e: SearchBoxInput', visualize(scores(), {}), 'score > 5'), None,
                             {}, scores())
        self.assertEqual((model, cmds), ({'search': 'score > 5'}, []))
        out = visualize(scores(), model)
        self.assertEqual(row_classes(out), ['row-dim', 'row-match', 'row-dim', 'row-match', 'row-dim'])
        self.assertIn('Count: 2', out)

    def test_it_reads_a_statements_name_too(self):
        out = visualize(scores(), {'search': 'high == 1'})
        self.assertEqual(row_classes(out), ['row-dim', 'row-match', 'row-match', 'row-dim', 'row-dim'])

    def test_first_match_keeps_only_the_first(self):
        model, _ = update(click(FirstMatchToggle()), None, {'search': 'score > 5'}, scores())
        self.assertTrue(model['first_match'])
        out = visualize(scores(), model)
        self.assertEqual(row_classes(out), ['row-dim', 'row-match', 'row-dim', 'row-dim', 'row-dim'])
        self.assertIn('search-button active', out)

    def test_a_search_that_matches_nothing_or_does_not_run_dims_nothing(self):
        for search in ('score > 100', 'score >', 'nope == 1'):
            with self.subTest(search=search):
                self.assertEqual(set(row_classes(visualize(scores(), {'search': search}))), {''})

    def test_an_empty_box_is_no_search(self):
        model, _ = update({'pythonEventStr': repr(SearchBoxInput(value='')), 'eventJSON': {}}, None,
                          {'search': 'score > 5'}, scores())
        self.assertIsNone(model['search'])


class TestColumnSearch(unittest.TestCase):
    """The search row atop a column's menu: an operator, what to compare the
    column's value against, and how it goes with the other columns' -- folded
    into the footer's search, as a table's are."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_menu_opens_with_a_search_row(self):
        out = visualize(scores(), {'col_menu': 'score'})
        self.assertIn('class="col-search-input search-box"', col_menu_of(out))
        self.assertNotIn('col-menu-no-search', col_menu_of(out))

    def test_typing_compares_the_columns_value(self):
        out = visualize(scores(), {'col_menu': 'score'})
        model, _ = update(typed_into('lambda e: ColumnSearchInput', out, '9'), None, {'col_menu': 'score'}, scores())
        self.assertEqual(model['col_search'], {'score': {'compose': 'and', 'op': '==', 'text': '9', 'exclude': False}})
        self.assertEqual(row_classes(visualize(scores(), model)),
                         ['row-dim', 'row-match', 'row-dim', 'row-match', 'row-dim'])

    def test_the_operator_and_how_it_composes_are_chips(self):
        model = {'col_menu': 'score', 'col_search': {'score': {'compose': 'and', 'op': '==', 'text': '4',
                                                               'exclude': False}}}
        model, _ = update(click(ColumnSearchOpSelect(label='score', op='>=')), None, model, scores())
        self.assertEqual(row_classes(visualize(scores(), model)),
                         ['row-dim', 'row-match', 'row-match', 'row-match', 'row-dim'])
        model['search'] = 'score == 1'
        model, _ = update(click(ColumnSearchComposeSelect(label='score', compose='or')), None, model, scores())
        self.assertEqual(row_classes(visualize(scores(), model)),
                         ['row-dim', 'row-match', 'row-match', 'row-match', 'row-match'])

    def test_escape_in_the_search_row_walks_out_a_level(self):
        model, _ = update(key('Escape'), None, {'col_menu': 'score', 'submenu': 'sort'}, scores())
        self.assertEqual((model['col_menu'], model['submenu']), ('score', None))
        model, _ = update(key('Escape'), None, model, scores())
        self.assertIsNone(model['col_menu'])

    def test_a_filtered_columns_header_says_so(self):
        model = {'col_search': {'score': {'compose': 'and', 'op': '==', 'text': '9', 'exclude': False}}}
        self.assertIn('col-filtered', header_cells(visualize(scores(), model))[1])


class TestSort(unittest.TestCase):
    """Sort, in a column's menu: the iterations drawn in the column's order,
    still numbered by when they ran. A view of the loop, so nothing is
    written."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_sort_is_a_submenu_of_ascending_and_descending(self):
        out = visualize(scores(), {'col_menu': 'score', 'submenu': 'sort'})
        self.assertEqual(submenu_rows(out), [('Ascending', False, True), ('Descending', False, True)])
        self.assertIn(('Sort', True), menu_options(out))

    def test_ticking_an_order_draws_the_rows_in_it(self):
        model, cmds = update(click(SortToggle(label='score', direction='asc')), None, {'col_menu': 'score'}, scores())
        self.assertEqual((model['sort'], cmds), ({'label': 'score', 'direction': 'asc'}, []))
        self.assertEqual([r[:2] for r in body_rows(visualize(scores(), model))[1:]],
                         [['4', '1'], ['0', '3'], ['2', '4'], ['1', '9'], ['3', '9']])
        model, _ = update(click(SortToggle(label='score', direction='desc')), None, model, scores())
        self.assertEqual([r[1] for r in body_rows(visualize(scores(), model))[1:]], ['9', '9', '4', '3', '1'])

    def test_ticking_it_again_puts_the_loops_order_back(self):
        model, _ = update(click(SortToggle(label='score', direction='asc')), None,
                          {'sort': {'label': 'score', 'direction': 'asc'}}, scores())
        self.assertIsNone(model['sort'])

    def test_the_checked_order_is_the_one_drawn(self):
        out = visualize(scores(), {'col_menu': 'score', 'submenu': 'sort',
                                   'sort': {'label': 'score', 'direction': 'desc'}})
        self.assertEqual(submenu_rows(out), [('Ascending', False, True), ('Descending', True, True)])

    def test_values_of_different_kinds_sort_by_how_they_read(self):
        t = table(columns=(bound('x'),), rows=(("'b'",), ('2',), ("'a'",)), values=(('b',), (2,), ('a',)),
                  init=(None,))
        out = visualize(t, {'sort': {'label': 'x', 'direction': 'asc'}})
        self.assertEqual([r[1] for r in iteration_rows(out)], ["'a'", "'b'", '2'])

    def test_a_running_table_has_no_values_to_sort_by(self):
        t = table(rows=(), values=(), running=True)
        model = {'last_rows': [{'element': '2', 'count += 1': '1'}, {'element': '1', 'count += 1': '2'}],
                 'sort': {'label': 'element', 'direction': 'asc'}}
        self.assertEqual([r[1] for r in body_rows(visualize(t, model))[1:]], ['2', '1'])


class TestTally(unittest.TestCase):
    """The foot of a column's menu: each value it took and how many
    iterations took it, ticked to search for them, as a table's."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    @staticmethod
    def tally_rows(html_text):
        return [(text_of(item), int(count), ' checked' in cls) for cls, item, count in re.findall(
            r'<div class="col-tally-row([^"]*)"[^>]*>.*?<span class="col-tally-item snc-code">(.*?)</span>'
            r'<span class="col-tally-count">(\d+)</span>', col_menu_of(html_text), re.S)]

    def test_every_value_and_how_often(self):
        self.assertEqual(self.tally_rows(visualize(scores(), {'col_menu': 'score'})),
                         [('3', 1, False), ('9', 2, False), ('4', 1, False), ('1', 1, False)])

    def test_ticking_values_searches_for_them(self):
        model, _ = update(click(TallyItemToggle(label='score', literal='9')), None, {'col_menu': 'score'}, scores())
        self.assertEqual(model['col_search']['score']['op'], '==')
        model, _ = update(click(TallyItemToggle(label='score', literal='1')), None, model, scores())
        self.assertEqual((model['col_search']['score']['op'], model['col_search']['score']['text']), ('in', '[9, 1]'))
        out = visualize(scores(), model)
        self.assertEqual(row_classes(out), ['row-dim', 'row-match', 'row-dim', 'row-match', 'row-match'])
        self.assertEqual([checked for _, _, checked in self.tally_rows(out)], [False, True, False, True])

    def test_exclude_all_and_none(self):
        model, _ = update(click(TallyItemToggle(label='score', literal='9')), None, {'col_menu': 'score'}, scores())
        model, _ = update(click(TallyExcludeToggle(label='score')), None, model, scores())
        self.assertEqual(row_classes(visualize(scores(), model)),
                         ['row-match', 'row-dim', 'row-match', 'row-dim', 'row-match'])
        model, _ = update(click(TallySelectNone(label='score')), None, model, scores())
        self.assertEqual(model['col_search']['score']['text'], '')
        model, _ = update(click(TallySelectAll(label='score')), None, model, scores())
        self.assertEqual(model['col_search']['score']['text'], '[3, 9, 4, 1]')

    def test_the_filter_box_and_the_order(self):
        out = visualize(scores(), {'col_menu': 'score'})
        model, _ = update(typed_into('lambda e: TallyFilterInput', out, '9'), None, {'col_menu': 'score'}, scores())
        self.assertEqual(self.tally_rows(visualize(scores(), model)), [('9', 2, False)])
        model, _ = update(click(TallySortSelect(sort='common')), None, {'col_menu': 'score'}, scores())
        self.assertEqual(self.tally_rows(visualize(scores(), model))[0], ('9', 2, False))

    def test_a_column_of_values_that_cannot_be_counted_says_so(self):
        t = table(columns=(bound('x'),), rows=(('[1]',),), values=(([1],),), init=(None,))
        self.assertIn('not counted', col_menu_of(visualize(t, {'col_menu': 'x'})))


class FakeCell:
    """A cell's visualizer: draws its value and whether it was drawn small,
    counts the Bump()s it is sent, and has a field per key of a dict."""
    drawn = []

    @staticmethod
    def can_visualize(value):
        return True

    @staticmethod
    def init_model(value, get_visualizer=None, eval_in_scope=None):
        return {'bumps': 0}

    @staticmethod
    def visualize(value, model, get_visualizer=None, eval_in_scope=None, max_width=None, max_height=None,
                  small=False, var_and_exp=None):
        FakeCell.drawn.append(value)
        return f'<b class="fake">{value!r}:{model["bumps"]}:{"small" if small else "big"}</b>'

    @staticmethod
    def update(event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        if event['pythonEventStr'] == 'Bump()':
            return ({**model, 'bumps': model['bumps'] + 1}, [])
        return (model, [])

    @staticmethod
    def get_fields(value):
        return [f'$[{k!r}]' for k in value] if isinstance(value, dict) else None


def cells_of(value):
    return FakeCell


def people():
    """for person in [{'name': 'Ann', 'age': 3}, {'name': 'Bo', 'age': 5}]: ..."""
    ps = [{'name': 'Ann', 'age': 3}, {'name': 'Bo', 'age': 5}]
    return table(line=1, end_line=2, columns=(bound('person'),), rows=tuple((repr(p),) for p in ps),
                 values=tuple((p,) for p in ps), targets=('person',), defined=frozenset({'person'}),
                 body_lines=(2, 2), init=(None,))


def child(key, inner, type_='mousedown'):
    return {'pythonEventStr': repr(ChildEvent(key, inner)), 'eventJSON': {'type': type_}}


class TestCellsAreVisualized(unittest.TestCase):
    """Each drawn cell is its value's own visualizer, as a table's is: small
    until a press focuses it, and only on the page of rows being drawn."""

    def setUp(self):
        visualizer_utils.set_live_only(False)
        FakeCell.drawn = []

    def test_a_cell_is_drawn_by_its_values_visualizer_keyed_by_row_and_column(self):
        out = visualize(table(), {}, cells_of)
        self.assertEqual(re.findall(r'snc-child-key="([^"]*)"', out),
                         [html.escape(repr(f'{i}\x00{label}')) for i in (0, 1) for label in ('element', 'count += 1')])
        self.assertIn('<b class="fake">1:0:small</b>', out)

    def test_an_oversized_cell_shows_why_its_value_is_unavailable(self):
        text = '[value too large to record] [[0, 1, ...]]'
        t = table(rows=(('1', text),), values=((1, NO_VALUE),))
        out = visualize(t, {}, cells_of)
        self.assertIn(text, out)
        self.assertEqual(FakeCell.drawn, [1])

    def test_a_press_focuses_a_cell_and_later_events_reach_it(self):
        key = '1\x00count += 1'
        model, _ = update(child(key, 'Bump()'), None, {}, table(), cells_of)
        self.assertEqual(model['focused_child'], key)
        model, _ = update(child(key, 'Bump()', 'keydown'), None, model, table(), cells_of)
        self.assertEqual(model['children'][key], {'bumps': 1})
        self.assertIn('<b class="fake">2:1:big</b>', visualize(table(), model, cells_of))

    def test_a_cell_with_no_value_to_keep_is_a_dash_and_a_running_table_its_reprs(self):
        out = visualize(table(values=((1, NO_VALUE), (2, 2))), {}, cells_of)
        self.assertEqual(body_rows(out)[1][2], '—')
        out = visualize(table(rows=(), values=(), running=True), {'last_rows': [{'element': '7', 'count += 1': '8'}]},
                        cells_of)
        self.assertEqual(body_rows(out)[1], ['0', '7', '8'])

    def test_a_cell_is_nested_with_nowhere_to_save_and_a_focused_ones_model_is_kept(self):
        seen = []

        class Nested(FakeCell):
            @staticmethod
            def init_model(value, get_visualizer=None, eval_in_scope=None, slots_config=None, config_path=None,
                           persist=True):
                seen.append((config_path, persist))
                return {'bumps': 0}

        model = {'focused_child': '0\x00element'}
        visualize(table(), model, lambda v: Nested)
        self.assertEqual(seen[0], (['element'], False))
        self.assertEqual(list(model['children']), ['0\x00element'])

    def test_an_event_for_a_cell_the_table_lacks_goes_nowhere(self):
        # A row that didn't run, a column since taken away, or a table that
        # has no values yet (the runner holds those events for the finished
        # one): nothing to send it to.
        model = {}
        for t, key in ((table(), '7\x00count += 1'), (table(), '0\x00gone'),
                       (table(rows=(), values=(), running=True), '0\x00element')):
            for type_ in ('mousedown', 'keydown'):
                model, cmds = update(child(key, 'Bump()', type_), None, model, t, cells_of)
                self.assertEqual(cmds, [])
        self.assertEqual(model.get('children') or {}, {})


    def test_only_the_page_drawn_is_visualized(self):
        t = many(60)
        visualize(table(**{**{f: getattr(t, f) for f in ('columns', 'rows', 'init', 'defined', 'body_lines',
                                                          'line', 'end_line')},
                           'values': tuple((i, 2 * i) for i in range(60))}), {}, cells_of)
        self.assertEqual(len(FakeCell.drawn), 53 * 2)


class TestCellCode(unittest.TestCase):
    """A cell's value is handed to its visualizer bound to a name, as a
    table's is; what one of its action buttons writes becomes a line in the
    loop's body, beside the statement that made the value, reading the name
    the column shows."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def wrote(self, key, inner, answer, t=None):
        """(what the cell was told its value is called, the commands the
        loop sent), for a cell answering the event `inner` with `answer`."""
        told = []

        class Acting(FakeCell):
            @staticmethod
            def update(event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
                told.append(var_and_exp)
                return (model, answer)

        t = t or table()
        model, _ = update(child(key, 'PinFocus()'), None, {}, t, lambda v: Acting)
        _, cmds = update(child(key, inner, 'mousedown'), None, model, t, lambda v: Acting)
        return told, cmds

    FINDALL = ('_snc_cell__strings', "re.findall(r'a', _snc_cell_)", ('import re',))
    PRESS = "ActionButtonClick(action='match_strings', copy=False)"

    def test_a_button_writes_its_code_beside_the_column_against_the_name_it_shows(self):
        self.assertEqual(
            [self.wrote(key, self.PRESS, [Phantom(self.FINDALL)]) for key in ('1\x00count += 1', '0\x00element')],
            [([(None, CHILD_SOURCE_BINDER)],
              [AddImports(('import re',)), InsertLines(((3, "    count_strings = re.findall(r'a', count)"),))]),
             ([(None, CHILD_SOURCE_BINDER)],
              [AddImports(('import re',)), InsertLines(((2, "    element_strings = re.findall(r'a', element)"),))])])

    def test_the_name_written_steps_past_one_the_loop_has_and_a_binder_capturing_the_column_is_renamed(self):
        t = table(defined=frozenset({'count', 'element', 'count_strings'}))
        code = ('_snc_cell__indices', '[element.start() for element in re.finditer(r"a", _snc_cell_)]')
        _, cmds = self.wrote('0\x00element', self.PRESS, [code], t)
        self.assertEqual(len(cmds), 1)
        name, _, written = cmds[0].lines[0][1].strip().partition(' = ')
        self.assertEqual((name, written.endswith('re.finditer(r"a", element)]'), 'for element in' in written),
                         ('element_indices', True, False))
        _, cmds = self.wrote('1\x00count += 1', self.PRESS, [Phantom(self.FINDALL)], t)
        self.assertEqual(cmds[1].lines[0][1].split(' = ')[0].strip(), 'count_strings2')

    def test_a_preview_from_anything_but_a_button_writes_nothing(self):
        # A drag over the string previews what it would write, which a table
        # draws as a column to commit; a loop has no such column to draw.
        self.assertEqual(self.wrote('1\x00count += 1', 'MouseUp(2)', [Phantom(self.FINDALL)])[1], [])

    def test_real_string_buttons_write_expressions_and_loop_blocks(self):
        import string_visualizer
        t = table(values=(('apple', 1), ('pear', 2)))
        key = '0\x00element'
        for action in ('match_strings', 'loop', 'loop_match_strings'):
            with self.subTest(action=action):
                model = {'focused_child': key}
                model, _ = update(child(key, "SearchBoxInput(value=\"r'a'\")", 'input'),
                                  None, model, t, lambda v: string_visualizer)
                _, commands = update(child(key, f"ActionButtonClick(action={action!r}, copy=False)", 'mousedown'),
                                     None, model, t, lambda v: string_visualizer)
                lines = [text for c in commands if isinstance(c, InsertLines) for _, text in c.lines]
                self.assertTrue(lines)
                source = 'for element in ["apple"]:\n    pass\n' + '\n'.join(lines)
                compile(source, '<test>', 'exec')

    def test_array_inside_loop_cell_can_write_another_loop(self):
        import table_visualizer
        t = table(values=((['apple', 'pear'], 1), (['peach'], 2)))
        key = '0\x00element'
        for action in ('loop_no_idx', 'loop_orig_idx', 'loop_new_idx'):
            with self.subTest(action=action):
                model = {'focused_child': key}
                _, commands = update(child(key, f"ActionButtonClick(action={action!r}, copy=False)", 'mousedown'),
                                     None, model, t, lambda v: table_visualizer)
                lines = [text for c in commands if isinstance(c, InsertLines) for _, text in c.lines]
                self.assertTrue(lines)
                self.assertIn('element', lines[0])
                compile('for element in [["apple"]]:\n    pass\n' + '\n'.join(lines), '<test>', 'exec')

    def test_a_copy_names_the_column(self):
        self.assertEqual(self.wrote('1\x00count += 1', self.PRESS,
                                    [CopyToClipboard(text="re.findall(r'a', _snc_cell_)")])[1],
                         [CopyToClipboard(text="re.findall(r'a', count)")])

    def test_a_cell_with_no_name_to_read_is_told_none_and_writes_nothing(self):
        # A condition's cell is its truth, not a name the body can read.
        t = table(columns=(bound('element'), statement('x > 1', 3, cond=True, path=((3, 0, 'if x > 1', 3, 4),))),
                  rows=(('1', 'False'), ('2', 'True')), values=((1, False), (2, True)))
        self.assertEqual(self.wrote('1\x00x > 1', self.PRESS, [Phantom(self.FINDALL)], t), ([None], []))

    def test_a_press_off_the_cells_puts_the_focused_one_away(self):
        container = r'<div class="visualizer-container[^>]*>'
        held = [html.escape(repr(DeselectChildren())) in re.search(container, visualize(table(), m, cells_of)).group(0)
                for m in ({}, {'focused_child': '0\x00element'})]
        self.assertEqual(held, [False, True])
        model, _ = update(click(DeselectChildren()), None, {'focused_child': '0\x00element'}, table(), cells_of)
        self.assertIsNone(model['focused_child'])


class TestSubcolumns(unittest.TestCase):
    """Subcolumns, in a column's menu: a value's fields spread across columns
    of their own under its header, as a table's are. A view of the values, so
    nothing is written."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def test_subheader_has_its_own_view_menu(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"]}, 'col_menu': leaf}
        out = visualize(people(), model, cells_of)
        self.assertIn(html.escape(repr(ColumnMenuToggle(label=leaf))), out)
        options = dict(menu_options(out))
        for name in ('Subcolumns', 'Sort', 'Compute'):
            self.assertTrue(options[name])
        for name in ('Remove', 'Insert Left', 'Insert Right', 'Change Type'):
            self.assertNotIn(name, options)

    def test_subcolumn_search_sort_tally_and_compute(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"]}, 'col_menu': leaf,
                 'sort': {'label': leaf, 'direction': 'desc'},
                 'col_search': {leaf: {'text': '4', 'op': '>'}}}
        out = visualize(people(), model)
        self.assertEqual([r[0] for r in iteration_rows(out)], ['1', '0'])
        self.assertIn('row-match', out)
        self.assertIn(html.escape(repr(TallyItemToggle(label=leaf, literal='3'))), out)
        model, _ = update(click(ComputeToggle(label=leaf, template='sum($)')), None, model, people())
        self.assertEqual(model['computes'][leaf], ['sum($)'])
        self.assertIn('col-agg-value">8', visualize(people(), model))

    def test_nested_subcolumns_are_full_columns(self):
        parent = "person\x01$['name']"
        model = {'subcols': {'person': ["$['name']"], parent: ['$.upper()']}}
        out = visualize(people(), model)
        self.assertEqual(header_labels(out), ['itr', 'person', "$['name']", '$.upper()'])
        self.assertEqual([r[1] for r in iteration_rows(out)], ["'ANN'", "'BO'"])
        self.assertIn(html.escape(repr(ColumnMenuToggle(label=parent + '\x01$.upper()'))), out)

    def test_pick_parent_and_subcolumn_extracts_their_subjects(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"]}, 'tool': 'pick'}
        out = visualize(people(), model)
        for label in ('person', leaf):
            self.assertIn(html.escape(repr(PickToggle(label=label))), out)
            picked, _ = update(click(PickToggle(label=label)), None, model, people())
            _, commands = update(click(ActionButtonClick(action='extract')), None, picked, people())
            subject = 'person' if label == 'person' else "person['age']"
            self.assertIn('matching.append(' + subject + ')', repr(commands))

    def test_subcolumn_resize_is_kept(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"]}}
        model, _ = update(click(ColumnResize(label=leaf, width=123)), None, model, people())
        self.assertEqual(model['widths'][leaf], 123)

    def test_subcolumn_header_edits_its_expression_as_a_view(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']", "$['name']"]}}
        model, _ = update({'pythonEventStr': repr(ColumnClick(col=leaf, label=leaf)),
                           'eventJSON': {'detail': 2}}, None, model, people())
        self.assertEqual(model['column_input'], "$['age']")
        model, _ = update(click(ColumnInput(value="$['age'] * 2")), None, model, people())
        model, commands = update(key('Enter'), None, model, people())
        self.assertEqual(model['subcols']['person'], ["$['age'] * 2", "$['name']"])
        self.assertEqual(commands, [])

    def test_hiding_a_subcolumn_removes_it_from_its_parent(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']", "$['name']"]}}
        model, commands = update(click(ColumnToggle(label=leaf)), None, model, people())
        self.assertEqual(model['subcols']['person'], ["$['name']"])
        self.assertEqual(commands, [])

    def test_edit_on_blur_keeps_nested_columns_and_answers(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"], leaf: ['$ + 1']},
                 'computes': {leaf: ['sum($)']}}
        model, _ = update(click(ColumnClick(col=leaf, label=leaf), detail=2), None, model, people())
        model, _ = update(click(ColumnInput(value="$['age'] * 2")), None, model, people())
        model, commands = update(click(ColumnInputBlur()), None, model, people())
        renamed = "person\x01$['age'] * 2"
        self.assertEqual(model['subcols'][renamed], ['$ + 1'])
        self.assertEqual(model['computes'][renamed], ['sum($)'])
        self.assertEqual(commands, [])

    def test_nested_parent_compute_answers_are_under_that_parent(self):
        leaf = "person\x01$['age']"
        model = {'subcols': {'person': ["$['age']"], leaf: ['$ + 1']},
                 'computes': {leaf: ['sum($)']}}
        out = visualize(people(), model)
        self.assertIn('col-agg-value">8', out)
        self.assertEqual(out.count('<tfoot'), 1)

    def test_extract_composes_expression_precedence(self):
        leaf = "person\x01$['age'] + 1"
        nested = leaf + '\x01$ * 2'
        model = {'subcols': {'person': ["$['age'] + 1"], leaf: ['$ * 2']},
                 'tool': 'pick', 'picked': [nested]}
        _, commands = update(click(ActionButtonClick(action='extract')), None, model, people())
        code = commands[0].lines[-1][1]
        scope = {'person': {'age': 3}, 'matching': []}
        exec(code.strip(), scope)
        self.assertEqual(scope['matching'], [8])

    def test_the_submenu_offers_the_fields_the_values_have(self):
        out = visualize(people(), {'col_menu': 'person', 'submenu': 'subcols'}, cells_of)
        self.assertIn(('Subcolumns', True), menu_options(out))
        self.assertEqual(submenu_rows(out), [('Show all', False, True), ('Hide all', False, True),
                                             ("$['name']", False, True), ("$['age']", False, True),
                                             ('', False, True)])

    def test_ticking_a_field_spreads_it_under_the_columns_header(self):
        model, cmds = update(click(SubcolToggle(label='person', expr="$['name']")), None, {}, people(), cells_of)
        self.assertEqual((model['subcols'], cmds), ({'person': ["$['name']"]}, []))
        model, _ = update(click(SubcolToggle(label='person', expr="$['age']")), None, model, people(), cells_of)
        out = visualize(people(), model)
        self.assertEqual(header_labels(out), ['itr', 'person', "$['name']", "$['age']"])
        self.assertIn('colspan="2"', header_cells(out)[1])
        self.assertEqual(body_rows(out), [['init', ''], ['0', "'Ann'", '3'], ['1', "'Bo'", '5']])

    def test_show_all_hide_all_and_one_of_your_own(self):
        model, _ = update(click(SubcolShowAll(label='person')), None, {}, people(), cells_of)
        self.assertEqual(model['subcols'], {'person': ["$['name']", "$['age']"]})
        model, _ = update(click(SubcolHideAll(label='person')), None, model, people(), cells_of)
        self.assertEqual(model['subcols'], {'person': []})
        model, _ = update({'pythonEventStr': f"lambda e: SubcolExprInput(label='person', value=e.get('value', ''))",
                           'eventJSON': {'value': "$['age'] * 2"}}, None, {'col_menu': 'person'}, people(), cells_of)
        model, _ = update(key('Enter'), None, model, people(), cells_of)
        self.assertEqual(model['subcols'], {'person': ["$['age'] * 2"]})
        self.assertEqual([r[1] for r in iteration_rows(visualize(people(), model))], ['6', '10'])

    def test_show_all_and_hide_all_on_the_running_table_wait_for_its_values(self):
        # The runner answers events with the table logged as the loop starts,
        # which has no values to find the fields in yet.
        running = replace(people(), rows=(), values=(), running=True)
        model, _ = update(click(SubcolShowAll(label='person')), None, {'subcols': {'person': ['$.mine']}},
                          running, cells_of)
        visualize(running, model, cells_of)
        visualize(people(), model, cells_of)
        shown = model['subcols']
        model, _ = update(click(SubcolHideAll(label='person')), None, model, running, cells_of)
        visualize(people(), model, cells_of)
        self.assertEqual((shown, model['subcols']),
                         ({'person': ['$.mine', "$['name']", "$['age']"]}, {'person': ['$.mine']}))

    def test_a_field_that_does_not_read_shows_its_error(self):
        out = visualize(people(), {'subcols': {'person': ["$['nope']"]}})
        self.assertIn('KeyError', iteration_rows(out)[0][1])


class TestDragOut(unittest.TestCase):
    """A header hands over the name its column shows, as a table's hands over
    its column."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_header_drags_out_the_name_it_shows(self):
        cells = header_cells(visualize(table(), {}))
        exps = [re.findall(r'snc-py-exps="([^"]*)"', c) for c in cells]
        self.assertEqual([[json.loads(html.unescape(e))[0]['expr'] for e in found] for found in exps],
                         [[], ['element'], ['count']])

    def test_not_live_only(self):
        visualizer_utils.set_live_only(True)
        self.assertNotIn('snc-py-exps', visualize(table(), {}))


class TestActionButtons(unittest.TestCase):
    """The footer's buttons, as a table's: each writes what its name says
    about the iterations the search holds for -- as loop code, a name set
    above the loop and a line at the end of its body."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def buttons(self, model):
        return [(text_of(label), 'dimmed' not in cls) for cls, label in re.findall(
            r'<span class="(action-button[^"]*)"[^>]*>(.*?)</span>(?=<span class="action-button|</div>)',
            visualize(scores(), model))]

    def test_the_buttons_and_which_need_a_search(self):
        self.assertEqual(self.buttons({}), [('Count: 5', True), ('Extract', True), ('Filter', False),
                                            ('Any', False), ('All', False)])
        self.assertEqual(self.buttons({'search': 'score > 5'}),
                         [('Count: 2', True), ('Extract', True), ('Filter', True), ('Any', True), ('All', True)])

    def test_each_writes_its_code(self):
        for action, lines in (
                ('count', ((1, 'n_matching = 0'), (3, '    if score > 5:\n        n_matching += 1'))),
                ('extract', ((1, 'matching = []'), (3, '    if score > 5:\n        matching.append(score)'))),
                ('any', ((1, 'any_matching = False'), (3, '    if score > 5:\n        any_matching = True'))),
                ('all', ((1, 'all_matching = True'), (3, '    if not (score > 5):\n        all_matching = False')))):
            with self.subTest(action=action):
                _, cmds = update(click(ActionButtonClick(action=action)), None, {'search': 'score > 5'}, scores())
                self.assertEqual(cmds, [InsertLines(lines)])

    def test_filter_skips_the_rest_at_the_top_of_the_body(self):
        _, cmds = update(click(ActionButtonClick(action='filter')), None, {'search': 'score > 5'}, scores())
        self.assertEqual(cmds, [InsertLines(((2, '    if not (score > 5):\n        continue'),))])

    def test_with_no_search_count_and_extract_take_every_iteration(self):
        _, cmds = update(click(ActionButtonClick(action='count')), None, {}, scores())
        self.assertEqual(cmds, [InsertLines(((1, 'n_iterations = 0'), (3, '    n_iterations += 1')))])

    def test_first_match_extracts_the_first_one(self):
        _, cmds = update(click(ActionButtonClick(action='extract')), None, {'search': 'score > 5', 'first_match': True},
                         scores())
        self.assertEqual(cmds, [InsertLines(((1, 'first_matching = None'),
                                             (3, '    if first_matching is None and score > 5:\n'
                                                 '        first_matching = score')))])

    def test_column_searches_are_folded_into_the_condition(self):
        model = {'search': 'score > 2', 'col_search': {'high += score > 5': {'compose': 'and', 'op': '>=',
                                                                            'text': '1', 'exclude': False}}}
        _, cmds = update(click(ActionButtonClick(action='count')), None, model, scores())
        self.assertEqual(cmds[0].lines[1], (3, '    if (score > 2) and (high >= (1)):\n        n_matching += 1'))

    def test_a_search_that_is_not_python_writes_nothing(self):
        self.assertEqual(update(click(ActionButtonClick(action='count')), None, {'search': 'score >'}, scores())[1],
                         [])


class TestRowMenu(unittest.TestCase):
    """The ▾ on an iteration's number, as on a table's row: what can be
    written about iterations like it."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_menu_opens_on_its_number(self):
        model, _ = update(click(RowMenuToggle(row=1)), None, {}, scores())
        self.assertEqual(model['row_menu'], 1)
        out = visualize(scores(), model)
        labels = [text_of(x) for x in re.findall(r'<span class="snc-dropdown-option-label"[^>]*>(.*?)</span>',
                                                 re.search(r'row-menu-panel.*?</div><!--/row-menu-->', out).group(0))]
        self.assertEqual(labels, ['Skip Iterations Where score == 9', 'Stop at the First Where score == 9',
                                  'Extract Row Cells'])

    def test_skip_and_stop_guard_the_top_of_the_body(self):
        for action, line in (('skip', '    if score == 9: continue'), ('stop', '    if score == 9: break')):
            with self.subTest(action=action):
                model, cmds = update(click(RowActionClick(row=1, action=action)), None, {'row_menu': 1}, scores())
                self.assertEqual(cmds, [InsertLines(((2, line),))])
                self.assertIsNone(model['row_menu'])

    def test_extract_row_cells_writes_them_after_the_loop(self):
        _, cmds = update(click(RowActionClick(row=1, action='extract')), None, {}, scores())
        self.assertEqual(cmds, [InsertLines(((3, "row_1 = {'score': 9, 'high': 1}"),))])

    def test_values_with_no_literal_have_nothing_to_compare_with(self):
        t = table(columns=(bound('x'),), rows=(('<object>',),), values=((object(),),), init=(None,))
        self.assertEqual(update(click(RowActionClick(row=0, action='skip')), None, {}, t), ({}, []))


class TestPickTool(unittest.TestCase):
    """The toolbar in a focused table's corner, as a table's: Pick marks
    whole columns, and Extract then collects what they show."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_focused_table_has_the_toolbar(self):
        out = visualize(scores(), {})
        self.assertIn('class="tool-toolbar', out)
        self.assertIn(html.escape(repr(ToolSelect(tool='pick'))), out)
        self.assertNotIn('tool-toolbar', visualize(scores(), {}, small=True))

    def test_pick_draws_a_region_down_every_column_and_picking_one_marks_it(self):
        model, _ = update(click(ToolSelect(tool='pick')), None, {}, scores())
        out = visualize(scores(), model)
        self.assertIn('pick-tool-selected', out)
        self.assertEqual(out.count(html.escape(repr(PickToggle(label='score')))), 5)
        model, _ = update(click(PickToggle(label='score')), None, model, scores())
        self.assertEqual(model['picked'], ['score'])
        self.assertIn('pick-region pick-band-all pick-region-first selected', visualize(scores(), model))

    def test_extract_collects_the_picked_columns(self):
        model = {'tool': 'pick', 'picked': ['score', 'high += score > 5']}
        _, cmds = update(click(ActionButtonClick(action='extract')), None, model, scores())
        self.assertEqual(cmds, [InsertLines(((1, 'matching = []'), (3, '    matching.append((score, high))')))])


class TestEditColumn(unittest.TestCase):
    """Double-clicking a column's header opens a box holding its statement, as
    a table's does; Enter writes what it then holds over the statement."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_a_statements_header_can_be_edited_and_a_bound_names_cannot(self):
        cells = header_cells(visualize(table(), {}))
        self.assertEqual([events_in(c) for c in cells], [
            [],
            [repr(ColumnMenuToggle(label='element'))],
            [repr(ColumnClick(col=1, label='count += 1')), repr(ColumnMenuToggle(label='count += 1'))],
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
    """Remove, in a column's menu, deletes the statement the column is."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def two_statements(self):
        return table(end_line=4, columns=(bound('element'), COUNT, statement('twice = element * 2', 4, 'twice')),
                     rows=(('1', '1', '2'),), body_lines=(3, 4), init=(None, '0', None))

    def test_deletes_the_statement_and_puts_the_menu_away(self):
        model, cmds = update(click(DeleteColumnClick(col=2, label='twice = element * 2')), None,
                             {'col_menu': 'twice = element * 2'}, self.two_statements())
        self.assertEqual(cmds, [ReplaceLines(4, 4, None)])
        self.assertIsNone(model['col_menu'])

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


IF_BRANCH = (3, 0, 'if x % 2 == 0', 4, 4)
ELIF_BRANCH = (3, 1, 'elif x > 4', 6, 6)
ELSE_BRANCH = (3, 2, 'else', 8, 8)


def branched(**overrides):
    """The loop in

        1  total = 0
        2  for x in [3, 8, 5]:
        3      if x % 2 == 0:
        4          tag = 'even'
        5      elif x > 4:
        6          tag = 'big'
        7      else:
        8          total += x

    as the runner logs it: a column per condition and per statement in a
    branch, each knowing its branch by `path`."""
    fields = dict(
        line=2, end_line=8, indent='', body_indent='    ',
        columns=(bound('x'),
                 ForLoopColumn('if x % 2 == 0', path=(IF_BRANCH,), cond=True, indent='    '),
                 statement("tag = 'even'", 4, 'tag', path=(IF_BRANCH,), indent='        '),
                 ForLoopColumn('elif x > 4', path=(ELIF_BRANCH,), cond=True, indent='    '),
                 statement("tag = 'big'", 6, 'tag', path=(ELIF_BRANCH,), indent='        '),
                 statement('total += x', 8, 'total', accumulator=True, init_span=(1, 1),
                           path=(ELSE_BRANCH,), indent='        ')),
        rows=(('3', 'False', None, 'False', None, '3'),
              ('8', 'True', "'even'", None, None, None),
              ('5', 'False', None, 'True', "'big'", None)),
        values=((3, False, NO_VALUE, False, NO_VALUE, 3),
                (8, True, 'even', NO_VALUE, NO_VALUE, NO_VALUE),
                (5, False, NO_VALUE, True, 'big', NO_VALUE)),
        targets=('x',),
        defined=frozenset({'tag', 'total', 'x'}),
        body_lines=(3, 8),
        init=(None, None, None, None, None, '0'),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


class TestIfBranches(unittest.TestCase):
    """What every drawing of an `if` in a loop needs to know: which branch of
    a chain each iteration took, and so which cells' statements ran. Code
    written into a branch keeps its indentation."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_each_iteration_took_one_branch_of_the_chain(self):
        from for_loop_visualizer import branch_ran
        t = branched()
        self.assertEqual([branch_ran(t, i, 3) for i in range(3)], [2, 0, 1])

    def test_with_no_else_every_condition_false_takes_none_and_a_chain_never_reached_is_none(self):
        from for_loop_visualizer import NO_BRANCH, branch_ran
        t = branched(columns=branched().columns[:5], rows=(('3', 'False', None, 'False', None),
                                                           ('8', None, None, None, None)),
                     values=((3, False, NO_VALUE, False, NO_VALUE), (8,) + (NO_VALUE,) * 4))
        self.assertEqual([branch_ran(t, i, 3) for i in range(2)], [NO_BRANCH, None])

    def test_a_condition_is_read_off_its_repr_while_the_loop_runs(self):
        from for_loop_visualizer import branch_ran
        t = branched(values=(), running=True)
        self.assertEqual([branch_ran(t, i, 3) for i in range(3)], [2, 0, 1])

    def test_a_cell_ran_when_every_branch_it_is_in_did(self):
        from for_loop_visualizer import cell_ran
        t = branched()
        self.assertEqual([[cell_ran(t, i, col) for col in range(6)] for i in range(3)], [
            [True, True, False, True, False, True],
            [True, True, True, False, False, False],
            [True, True, False, True, True, False],
        ])

    def test_editing_a_statement_in_a_branch_keeps_its_indentation(self):
        _, cmds = update(key('Enter'), None, editing(2, "tag = 'EVEN'"), branched())
        self.assertEqual(cmds, [ReplaceLines(4, 4, "        tag = 'EVEN'")])

    def test_removing_the_last_statement_in_a_branch_leaves_a_pass_there(self):
        _, cmds = update(click(DeleteColumnClick(col=2, label="tag = 'even'")), None, {}, branched())
        self.assertEqual(cmds, [ReplaceLines(4, 4, '        pass')])

    def test_a_condition_has_no_statement_to_edit_or_remove(self):
        for msg in (click(ColumnClick(col=1, label='if x % 2 == 0'), detail=2),
                    click(DeleteColumnClick(col=1, label='if x % 2 == 0'))):
            with self.subTest(msg=msg):
                self.assertEqual(update(msg, None, {}, branched()), ({}, []))

    def test_inserting_beside_a_statement_in_a_branch_writes_into_that_branch(self):
        t = branched()
        model, _ = update(click(InsertColumnClick(col=2, label="tag = 'even'", after=True)), None, {}, t)
        _, cmds = update(key('Enter'), None, {**model, 'column_input': 'y = 1'}, t)
        self.assertEqual(cmds, [InsertLines(((4, '        y = 1'),))])

    def test_inserting_right_of_a_condition_writes_at_the_top_of_its_branch(self):
        t = branched()
        model, _ = update(click(InsertColumnClick(col=3, label='elif x > 4', after=True)), None, {}, t)
        _, cmds = update(key('Enter'), None, {**model, 'column_input': 'y = 1'}, t)
        self.assertEqual(cmds, [InsertLines(((5, '        y = 1'),))])


OUTER_IF = (3, 0, 'if x > 4', 4, 6)
INNER_IF = (4, 0, 'if x % 2 == 0', 5, 5)
OUTER_ELSE = (3, 1, 'else', 8, 8)


def nested(**overrides):
    """The loop in

        1  total = 0
        2  for x in [3, 8, 5]:
        3      if x > 4:
        4          if x % 2 == 0:
        5              tag = 'even'
        6          total += x
        7      else:
        8          tag = 'small'
        9      done = True

    an `if` in an `if`, an accumulator in a branch, and a statement after the
    chain."""
    fields = dict(
        line=2, end_line=9, indent='', body_indent='    ',
        columns=(bound('x'),
                 ForLoopColumn('if x > 4', path=(OUTER_IF,), cond=True, indent='    '),
                 ForLoopColumn('if x % 2 == 0', path=(OUTER_IF, INNER_IF), cond=True, indent='        '),
                 statement("tag = 'even'", 5, 'tag', path=(OUTER_IF, INNER_IF), indent='            '),
                 statement('total += x', 6, 'total', accumulator=True, init_span=(1, 1), path=(OUTER_IF,),
                           indent='        '),
                 statement("tag = 'small'", 8, 'tag', path=(OUTER_ELSE,), indent='        '),
                 statement('done = True', 9, 'done', indent='    ')),
        rows=(('3', 'False', None, None, None, "'small'", 'True'),
              ('8', 'True', 'True', "'even'", '8', None, 'True'),
              ('5', 'True', 'False', None, '13', None, 'True')),
        values=((3, False, NO_VALUE, NO_VALUE, NO_VALUE, 'small', True),
                (8, True, True, 'even', 8, NO_VALUE, True),
                (5, True, False, NO_VALUE, 13, NO_VALUE, True)),
        targets=('x',),
        defined=frozenset({'tag', 'total', 'x', 'done'}),
        body_lines=(3, 9),
        init=(None, None, None, None, '0', None, None),
    )
    fields.update(overrides)
    return ForLoopTable(**fields)


def header_grid(html_text):
    """Each header row, as (text, colspan, rowspan) per cell, without a
    column's ▾ or an elif's ⣿."""
    thead = re.search(r'<thead.*?</thead>', html_text).group(0)
    thead = re.sub(r'<span [^>]*class="col-handle col-drag-handle">⣿</span>', '', thead)
    return [[(text_of(re.sub(r'<span class="snc-dropdown-trigger col-menu-trigger">.*', '', th)),
              int((re.search(r'^<th[^>]*colspan="(\d+)"', th) or [0, 1])[1]),
              int((re.search(r'^<th[^>]*rowspan="(\d+)"', th) or [0, 1])[1]))
             for th in re.findall(r'<th[^>]*>.*?</th>', tr)]
            for tr in re.findall(r'<tr[^>]*>.*?</tr>', thead)]


def cell_grid(html_text):
    """The iterations' cells after `itr`: their text, or `///` for one whose
    statement a branch not taken skipped."""
    body = re.search(r'<tbody>(.*?)</tbody>', html_text, re.S).group(1)
    return [['///' if 'for-loop-skipped' in cls else html.unescape(re.sub(r'<[^>]*>', '', inner))
             for cls, inner in re.findall(r'<td class="([^"]*)"[^>]*>(.*?)</td>', tr)[1:]]
            for tr in re.findall(r'<tr[^>]*>.*?</tr>', body)[1:]]


def edges_of(cells_html):
    """Each cell's chain edges, as the classes that draw them."""
    return [' '.join(re.findall(r'for-loop-(chain-start|chain-end|branch-start)', cls))
            for cls in re.findall(r'<t[dh] class="([^"]*)"', cells_html)]


def add_menu_rows(html_text):
    """The (+) menu's rows below Show all and Hide all, as (text, checked,
    depth) -- checked None for a row with no box."""
    rows = []
    for row in re.findall(r'<div class="col-compute-row[^"]*">.*?</div>', menu_of(html_text).split('Hide all')[1]):
        box = re.search(r'<input[^>]*>', row)
        depth = re.search(r'--for-loop-depth: (\d+)', row)
        rows.append((text_of(row), None if box is None else ' checked' in box.group(0),
                     int(depth.group(1)) if depth else 0))
    return rows


# The model with every chain in nested() unfolded.
UNFOLDED = {'chains': {'4': True}}


class TestIfColumnGroups(unittest.TestCase):
    """Design A: each branch of an `if` chain heads a group of the columns in
    it -- its condition, its statements, the chains in it -- a header row per
    level of nesting, and what ran in another branch is hatched. Drawn with
    every chain unfolded (see TestCollapsingAnIfChain)."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_each_branch_heads_a_group_over_its_columns(self):
        self.assertEqual(header_grid(visualize(branched(), {})), [
            [('itr', 1, 2), ('x', 1, 2), ('if x % 2 == 0', 2, 1), ('elif x > 4', 2, 1), ('else', 1, 1)],
            [('cond', 1, 1), ("tag = 'even'", 1, 1), ('cond', 1, 1), ("tag = 'big'", 1, 1),
             ('total += x', 1, 1)]])

    def test_a_nested_chain_is_another_row_and_columns_outside_any_branch_reach_down(self):
        self.assertEqual(header_grid(visualize(nested(), UNFOLDED)), [
            [('itr', 1, 3), ('x', 1, 3), ('if x > 4', 4, 1), ('else', 1, 1), ('done = True', 1, 3)],
            [('cond', 1, 2), ('if x % 2 == 0', 2, 1), ('total += x', 1, 2), ("tag = 'small'", 1, 2)],
            [('cond', 1, 1), ("tag = 'even'", 1, 1)]])

    def test_a_conditions_header_is_short_with_the_condition_in_its_tooltip(self):
        cond = header_cells(visualize(branched(), {}))[7]
        self.assertEqual(re.findall(r'<span class="col-name[^"]*"[^>]*data-tooltip="([^"]*)"', html.unescape(cond)), ['elif x > 4'])

    def test_a_branchs_header_says_how_many_iterations_took_it(self):
        group = header_cells(visualize(branched(), {}))[2]
        self.assertIn('data-tooltip="Taken in 1 of 3 iterations"', group)

    def test_subcolumns_are_one_more_level_under_a_column_in_a_branch(self):
        out = visualize(branched(), {'subcols': {"tag = 'even'": ['$.upper()']}})
        self.assertEqual(header_grid(out), [
            [('itr', 1, 3), ('x', 1, 3), ('if x % 2 == 0', 2, 1), ('elif x > 4', 2, 1), ('else', 1, 1)],
            [('cond', 1, 2), ("tag = 'even'", 1, 1), ('cond', 1, 2), ("tag = 'big'", 1, 2), ('total += x', 1, 2)],
            [('$.upper()', 1, 1)]])
        self.assertEqual(cell_grid(out)[1][:3], ['8', 'True', "'EVEN'"])

    def test_a_branch_with_every_column_hidden_has_no_group_and_a_chain_none_takes_no_row(self):
        out = visualize(branched(), {'hidden_columns': ['elif x > 4', "tag = 'big'"]})
        self.assertEqual(header_grid(out), [
            [('itr', 1, 2), ('x', 1, 2), ('if x % 2 == 0', 2, 1), ('else', 1, 1)],
            [('cond', 1, 1), ("tag = 'even'", 1, 1), ('total += x', 1, 1)]])
        everything = [column.label for column in branched().columns[1:]]
        self.assertEqual(header_grid(visualize(branched(), {'hidden_columns': everything})), [[('itr', 1, 1),
                                                                                               ('x', 1, 1)]])

    def test_a_cell_another_branch_skipped_is_hatched_and_one_never_reached_a_dash(self):
        t = branched(rows=branched().rows + (('9', None, None, None, None, None),),
                     values=branched().values + ((9,) + (NO_VALUE,) * 5,))
        self.assertEqual(cell_grid(visualize(t, {})), [
            ['3', 'False', '///', 'False', '///', '3'],
            ['8', 'True', "'even'", '///', '///', '///'],
            ['5', 'False', '///', 'True', "'big'", '///'],
            ['9', '—', '—', '—', '—', '—']])

    def test_a_branch_not_taken_hatches_the_chains_inside_it(self):
        self.assertEqual(cell_grid(visualize(nested(), UNFOLDED)), [
            ['3', 'False', '///', '///', '///', "'small'", 'True'],
            ['8', 'True', 'True', "'even'", '8', '///', 'True'],
            ['5', 'True', 'False', '///', '13', '///', 'True']])

    def test_while_the_loop_runs_the_rows_of_last_time_are_hatched_by_their_reprs(self):
        t = branched()
        last = [dict(zip([column.label for column in t.columns], row)) for row in t.rows]
        out = visualize(branched(rows=(), values=(), running=True), {'last_rows': last})
        self.assertEqual(cell_grid(out)[0], ['3', 'False', '///', 'False', '///', '3'])

    def test_a_conditions_cells_say_whether_it_held(self):
        rows = re.findall(r'<tr[^>]*>.*?</tr>', re.search(r'<tbody>(.*?)</tbody>', visualize(branched(), {})).group(1))
        self.assertEqual([re.findall(r'for-loop-cond-(true|false)', tr) for tr in rows[1:]],
                         [['false', 'false'], ['true'], ['false', 'true']])

    def test_the_init_row_lines_up_blank_under_conditions_with_a_branchs_accumulator_starting_there(self):
        out = visualize(nested(), UNFOLDED)
        self.assertEqual(body_rows(out)[0], ['init', '', '', '', '', '0', '', ''])
        row = re.search(r'<tr class="for-loop-init-row">.*?</tr>', out).group(0)
        self.assertEqual(events_in(row), [repr(InitCellClick(col=4, label='total += x'))])

    def test_a_chain_is_edged_where_it_starts_and_ends_and_between_its_branches(self):
        out = visualize(nested(), UNFOLDED)
        first = re.search(r'<tbody>.*?</tr>(<tr[^>]*>.*?</tr>)', out).group(1)
        self.assertEqual(edges_of(first), ['', '', 'chain-start', 'chain-start', 'chain-end', '', 'branch-start chain-end', ''])
        self.assertEqual(edges_of(''.join(header_cells(out))), [
            '', '', 'chain-start', 'branch-start chain-end', '',
            'chain-start', 'chain-start chain-end', '', 'branch-start chain-end', 'chain-start', 'chain-end'])

    def test_the_plus_menu_lists_a_branchs_columns_under_it_as_the_code_reads(self):
        out = visualize(nested(), {**UNFOLDED, 'add_menu_open': True})
        self.assertEqual(menu_rows(out)[:4], [('Add Column', None), ('Add If', None), '--', ('x', True)])
        self.assertEqual(add_menu_rows(out), [
            ('if x > 4', True, 0), ('if x % 2 == 0', True, 1), ("tag = 'even'", True, 2), ('total += x', True, 1),
            ('else', None, 0), ("tag = 'small'", True, 1), ('done = True', True, 0)])
        self.assertIn(repr(ColumnToggle(label='if x > 4')), events_in(menu_of(out)))

    def test_hide_all_hides_conditions_too(self):
        model, _ = update(click(ColumnHideAll()), None, {}, branched())
        self.assertEqual(header_grid(visualize(branched(), model)), [[('itr', 1, 1), ('x', 1, 1)]])
        model, _ = update(click(ColumnShowAll()), None, model, branched())
        self.assertEqual(model['hidden_columns'], [])

    def test_a_conditions_menu_leaves_out_what_needs_a_statement_or_a_name(self):
        self.assertEqual(menu_options(visualize(branched(), {'col_menu': 'if x % 2 == 0'})), [
            ('Insert Right', True), ('Sort', True), ('Compute', True)])

    def test_the_insert_box_beside_a_column_in_a_branch_stays_in_its_group(self):
        model, _ = update(click(InsertColumnClick(col=2, label="tag = 'even'", after=True)), None, {}, branched())
        grid = header_grid(visualize(branched(), model))
        self.assertEqual(grid[0][2], ('if x % 2 == 0', 3, 1))
        self.assertEqual([text for text, _, _ in grid[1]], ['cond', "tag = 'even'", '', 'cond', "tag = 'big'",
                                                            'total += x'])

    def test_live_only_draws_the_groups_with_nothing_to_press_but_their_menus(self):
        from for_loop_visualizer import ChainMenuToggle
        visualizer_utils.set_live_only(True)
        out = visualize(nested(), UNFOLDED)
        self.assertEqual(len(header_grid(out)), 3)
        self.assertEqual(events_in(out), [repr(ChainMenuToggle(chain=3, branch=0)), repr(ChainMenuToggle(chain=3, branch=1)),
                                          repr(ChainMenuToggle(chain=4, branch=0))])


class TestCollapsingAnIfChain(unittest.TestCase):
    """Design B: Collapse, in the menu of the ▾ on a chain's first branch, folds the whole chain -- its
    branches and every chain in them -- into one column saying which branch
    each iteration took. A chain directly in the loop starts unfolded, one in
    a branch folded. A view, so nothing is written."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_toggle_folds_a_chain_and_unfolds_it_and_writes_nothing(self):
        from for_loop_visualizer import ChainToggle
        self.assertIn(repr(ChainToggle(chain=3)), events_in(visualize(branched(), {'chain_menu': [3, 0]})))
        model, cmds = update(click(ChainToggle(chain=3)), None, {}, branched())
        self.assertEqual((model, cmds), ({'chains': {'3': False}}, []))
        model, _ = update(click(ChainToggle(chain=3)), None, model, branched())
        self.assertEqual(model, {'chains': {'3': True}})

    def test_a_nested_chain_starts_folded_and_unfolds(self):
        from for_loop_visualizer import ChainToggle
        model, _ = update(click(ChainToggle(chain=4)), None, {}, nested())
        self.assertEqual(model, {'chains': {'4': True}})

    def test_a_toggle_for_a_chain_that_is_gone_does_nothing(self):
        from for_loop_visualizer import ChainToggle
        self.assertEqual(update(click(ChainToggle(chain=7)), None, {}, branched()), ({}, []))

    def test_folded_each_iteration_shows_the_branch_it_took(self):
        out = visualize(branched(), {'chains': {'3': False}})
        self.assertEqual((header_grid(out), cell_grid(out)), (
            [[('itr', 1, 1), ('x', 1, 1), ('if x % 2 == 0 … else', 1, 1)]],
            [['3', 'else'], ['8', 'if'], ['5', 'elif x > 4']]))

    def test_folded_no_branch_taken_is_a_dash_and_never_reached_is_blank(self):
        t = branched(columns=branched().columns[:5], rows=(('3', 'False', None, 'False', None),
                                                           ('8', None, None, None, None)),
                     values=((3, False, NO_VALUE, False, NO_VALUE), (8,) + (NO_VALUE,) * 4),
                     init=(None,) * 5)
        out = visualize(t, {'chains': {'3': False}})
        self.assertEqual((header_grid(out)[0][-1][0], cell_grid(out)),
                         ('if x % 2 == 0 … elif x > 4', [['3', '—'], ['8', '']]))

    def test_a_nested_chain_starts_folded_inside_its_branch_and_hatched_where_that_didnt_run(self):
        out = visualize(nested(), {})
        self.assertEqual((header_grid(out), cell_grid(out)), ([
            [('itr', 1, 2), ('x', 1, 2), ('if x > 4', 3, 1), ('else', 1, 1), ('done = True', 1, 2)],
            [('cond', 1, 1), ('if x % 2 == 0', 1, 1), ('total += x', 1, 1), ("tag = 'small'", 1, 1)]], [
            ['3', 'False', '///', '///', "'small'", 'True'],
            ['8', 'True', 'if', '8', '///', 'True'],
            ['5', 'True', '—', '13', '///', 'True'],
        ]))

    def test_folding_the_outer_chain_folds_the_one_in_it_too(self):
        out = visualize(nested(), {'chains': {'3': False, '4': True}})
        self.assertEqual(header_grid(out), [[('itr', 1, 1), ('x', 1, 1), ('if x > 4 … else', 1, 1),
                                             ('done = True', 1, 1)]])

    def test_a_folded_chain_edges_like_a_chain(self):
        out = visualize(branched(), {'chains': {'3': False}})
        row = re.findall(r'<tr[^>]*>.*?</tr>', re.search(r'<tbody>(.*?)</tbody>', out, re.S).group(1))[1]
        self.assertEqual(edges_of(row), ['', '', 'chain-start chain-end'])

    def test_a_folded_chains_init_cell_is_where_its_accumulators_start(self):
        out = visualize(branched(), {'chains': {'3': False}})
        self.assertEqual(body_rows(out)[0], ['init', '', 'total = 0'])
        self.assertIn(repr(InitCellClick(col=5, label='total += x')), events_in(out))

    def test_live_only_still_folds_chains_since_that_is_a_view(self):
        from for_loop_visualizer import ChainToggle
        visualizer_utils.set_live_only(True)
        self.assertIn(repr(ChainToggle(chain=3)), events_in(visualize(nested(), {'chain_menu': [3, 0]})))


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

    def test_a_loop_without_an_accumulator_still_has_an_init_row_with_nothing_in_it(self):
        self.assertEqual(body_rows(visualize(plain(), {}))[0], ['init', '', ''])

    def test_hiding_every_accumulator_keeps_the_init_row(self):
        self.assertEqual(body_rows(visualize(table(), {'hidden_columns': ['count += 1']}))[0], ['init', ''])

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

    def test_the_menu_of_every_column_showing_a_name_it_can_collect_offers_it(self):
        t = table(columns=(bound('element'), COUNT, statement('arr2.append(element)', 4, 'arr2', in_place=True,
                                                              accumulator=True),
                           statement('d[element] = 1', 5, None, underline=10)),
                  init=(None, '0', '[]', None), values=())
        # A list appended to in place is one object in every row; there is
        # no name to collect in d[element].
        for col, label, offered in ((0, 'element', True), (1, 'count += 1', True),
                                    (2, 'arr2.append(element)', False), (3, 'd[element] = 1', False)):
            with self.subTest(label=label):
                out = visualize(t, {'col_menu': label})
                self.assertEqual(('Collect into List', True) in menu_options(out), offered)
                self.assertEqual(repr(CollectClick(col=col, label=label)) in events_in(col_menu_of(out)), offered)

    def test_no_menu_when_visualizers_are_live_only(self):
        visualizer_utils.set_live_only(True)
        self.assertNotIn('CollectClick', html.unescape(visualize(table(), {})))

    def test_collect_opens_a_box_naming_the_list(self):
        model, cmds = update(click(CollectClick(col=0, label='element')), None, {'col_menu': 'element'}, table())
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


def no_else(**overrides):
    """branched()'s chain without its `else`: lines 1-6 of it."""
    fields = dict(columns=branched().columns[:5], end_line=6, body_lines=(3, 6),
                  rows=(('3', 'False', None, 'False', None), ('8', 'True', "'even'", None, None)),
                  values=((3, False, NO_VALUE, False, NO_VALUE), (8, True, 'even', NO_VALUE, NO_VALUE)),
                  init=(None,) * 5)
    fields.update(overrides)
    return branched(**fields)


ELSE_PASS = (3, 1, 'else', 6, 6)


def else_pass(**overrides):
    """A chain whose `else` is only a `pass`, as Add Else writes it:

        2  for x in [3, 8]:
        3      if x % 2 == 0:
        4          tag = 'even'
        5      else:
        6          pass
    """
    fields = dict(columns=(bound('x'),
                           ForLoopColumn('if x % 2 == 0', path=(IF_BRANCH,), cond=True, indent='    '),
                           statement("tag = 'even'", 4, 'tag', path=(IF_BRANCH,), indent='        '),
                           ForLoopColumn('pass', span=(6, 6), path=(ELSE_PASS,), indent='        ',
                                         placeholder=True)),
                  end_line=6, body_lines=(3, 6),
                  rows=(('3', 'False', None, None), ('8', 'True', "'even'", None)),
                  values=((3, False, NO_VALUE, NO_VALUE), (8, True, 'even', NO_VALUE)),
                  defined=frozenset({'tag', 'x'}), init=(None,) * 4)
    fields.update(overrides)
    return branched(**fields)


def chain_menu_of(html_text):
    """The open `if` menu's rows, as (label, whether it does anything)."""
    found = re.search(r'<div class="snc-dropdown-panel[^"]*for-loop-chain-menu.*?</div><!--/chain-menu-->',
                      html_text, re.S)
    if found is None:
        return None
    return [(text_of(label), 'unselectable' not in cls)
            for cls, label in re.findall(r'<div class="(snc-dropdown-option[^"]*)"[^>]*>(.*?)</div>', found.group(0))]


class TestWritingIfBranches(unittest.TestCase):
    """The (+) menu's Add If writes a new `if` from a box reading `if
    [condition]`. Every chain's ▾ opens a menu: Collapse (or Expand), Add Elif,
    whose box sits where the branch will be drawn, and Add Else. A new branch
    is a `pass`, drawn as a placeholder column, which what is next written
    into the branch replaces."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_add_menu_offers_add_if(self):
        from for_loop_visualizer import AddIfClick
        out = visualize(table(), {'add_menu_open': True})
        self.assertIn('Add If', text_of(out))
        self.assertIn(repr(AddIfClick()), events_in(out))

    def test_add_if_puts_the_menu_away_and_opens_a_box_reading_if(self):
        from for_loop_visualizer import AddIfClick
        model, cmds = update(click(AddIfClick()), None, {'add_menu_open': True}, table())
        self.assertEqual((model.get('adding_if'), model.get('add_menu_open'), cmds), (True, None, []))
        box = header_cells(visualize(table(), model))[-1]
        self.assertEqual((text_of(box).strip(), re.search(r'placeholder="([^"]*)"', box).group(1)),
                         ('if', 'Condition'))

    def test_enter_writes_the_if_at_the_end_of_the_body_holding_a_pass(self):
        model = {'adding_if': True, 'column_input': 'element > 1'}
        model, cmds = update(key('Enter'), None, model, table())
        self.assertEqual((model.get('adding_if'), cmds),
                         (None, [InsertLines(((3, '    if element > 1:\n        pass'),))]))

    def test_a_condition_that_doesnt_parse_stays_open_unwritten(self):
        model = {'adding_if': True, 'column_input': 'element >'}
        self.assertEqual(update(key('Enter'), None, model, table()), (model, []))

    def test_escape_closes_the_if_box_unwritten(self):
        model, cmds = update(key('Escape'), None, {'adding_if': True, 'column_input': 'x'}, table())
        self.assertEqual((model.get('adding_if'), cmds), (None, []))

    def test_a_chains_menu_has_no_room_for_a_search_row_it_doesnt_have(self):
        """A column's menu pads its top for the search row laid over it; an
        if's has none, so it says so and isn't padded."""
        for branch in (0, 1):
            out = visualize(branched(), {'chain_menu': [3, branch]})
            self.assertRegex(out, r'class="snc-dropdown-panel flyout col-menu-panel col-menu-no-search for-loop-chain-menu"')

    def test_a_chains_arrow_opens_its_menu(self):
        from for_loop_visualizer import ChainMenuToggle
        self.assertIn(repr(ChainMenuToggle(chain=3, branch=0)), events_in(visualize(no_else(), {})))
        model, cmds = update(click(ChainMenuToggle(chain=3, branch=0)), None, {}, no_else())
        self.assertEqual((model.get('chain_menu'), cmds), ([3, 0], []))
        model, _ = update(click(ChainMenuToggle(chain=3, branch=0)), None, model, no_else())
        self.assertIsNone(model.get('chain_menu'))

    def test_the_menu_collapses_and_adds_an_elif_or_an_else(self):
        from for_loop_visualizer import AddElifClick, AddElseClick, ChainToggle
        out = visualize(no_else(), {'chain_menu': [3, 0]})
        self.assertEqual(chain_menu_of(out), [('Collapse', True), ('Add Elif', True), ('Add Else', True),
                                              ('Remove', True)])
        for msg in (ChainToggle(chain=3), AddElifClick(chain=3), AddElseClick(chain=3)):
            self.assertIn(repr(msg), events_in(out))

    def test_a_folded_chains_menu_expands_it(self):
        out = visualize(no_else(), {'chains': {'3': False}, 'chain_menu': [3, 0]})
        self.assertEqual(chain_menu_of(out)[0], ('Expand', True))

    def test_a_chain_with_an_else_has_no_second_to_add(self):
        from for_loop_visualizer import AddElseClick
        out = visualize(branched(), {'chain_menu': [3, 0]})
        self.assertEqual(chain_menu_of(out)[2], ('Add Else', False))
        self.assertNotIn(repr(AddElseClick(chain=3)), events_in(out))

    def test_collapse_folds_and_puts_the_menu_away(self):
        from for_loop_visualizer import ChainToggle
        self.assertEqual(update(click(ChainToggle(chain=3)), None, {'chain_menu': [3, 0]}, branched()),
                         ({'chains': {'3': False}}, []))

    def test_add_else_writes_an_else_holding_a_pass_after_the_chain(self):
        from for_loop_visualizer import AddElseClick
        model, cmds = update(click(AddElseClick(chain=3)), None, {'chain_menu': [3, 0]}, no_else())
        self.assertEqual((model.get('chain_menu'), cmds),
                         (None, [InsertLines(((6, '    else:\n        pass'),))]))

    def test_add_else_on_a_chain_that_has_one_writes_nothing(self):
        from for_loop_visualizer import AddElseClick
        self.assertEqual(update(click(AddElseClick(chain=3)), None, {}, branched())[1], [])

    def test_add_elif_unfolds_the_chain_and_opens_a_box_where_the_branch_goes(self):
        from for_loop_visualizer import AddElifClick
        model, cmds = update(click(AddElifClick(chain=3)), None,
                             {'chain_menu': [3, 0], 'chains': {'3': False}}, branched())
        self.assertEqual((model.get('adding_elif'), model.get('chains'), model.get('chain_menu'), cmds),
                         (3, {'3': True}, None, []))
        heads = [text_of(th).strip('⣿▾ ') for th in header_cells(visualize(branched(), model))]
        # Between the last elif's columns and the else's.
        self.assertEqual(heads[heads.index('elif'):heads.index('else') + 1], ['elif', 'else'])
        self.assertLess(heads.index('elif x > 4'), heads.index('elif'))

    def test_enter_writes_the_elif_after_the_last_one_before_the_else(self):
        model = {'adding_elif': 3, 'column_input': 'x > 6'}
        model, cmds = update(key('Enter'), None, model, branched())
        self.assertEqual((model.get('adding_elif'), cmds),
                         (None, [InsertLines(((6, '    elif x > 6:\n        pass'),))]))

    def test_with_only_an_if_the_elif_follows_it(self):
        t = no_else(columns=branched().columns[:3], rows=(('3', 'False', None), ('8', 'True', "'even'")),
                    values=((3, False, NO_VALUE), (8, True, 'even')), init=(None,) * 3, end_line=4)
        cmds = update(key('Enter'), None, {'adding_elif': 3, 'column_input': 'x > 6'}, t)[1]
        self.assertEqual(cmds, [InsertLines(((4, '    elif x > 6:\n        pass'),))])

    def test_live_only_a_chains_menu_only_folds(self):
        visualizer_utils.set_live_only(True)
        out = visualize(no_else(), {'chain_menu': [3, 0]})
        self.assertEqual(chain_menu_of(out), [('Collapse', True), ('Add Elif', False), ('Add Else', False),
                                              ('Remove', False)])

    def test_a_pass_is_drawn_empty_and_hatched_where_its_branch_didnt_run(self):
        out = visualize(else_pass(), {})
        self.assertEqual(cell_grid(out), [['3', 'False', '///', ''], ['8', 'True', "'even'", '///']])
        self.assertIn('for-loop-placeholder', header_cells(out)[-1])

    def test_writing_beside_a_pass_writes_over_it(self):
        model = {**adding("tag = 'odd'"), 'insert_at': {'label': 'pass', 'after': True}}
        cmds = update(key('Enter'), None, model, else_pass())[1]
        self.assertEqual(cmds, [ReplaceLines(6, 6, "        tag = 'odd'")])

    def with_new_if(self):
        """table() once Enter wrote `if element > 1:` and its pass after
        line 3, as the next run draws it."""
        branch = (4, 0, 'if element > 1', 5, 5)
        return table(columns=(bound('element'), COUNT,
                              ForLoopColumn('if element > 1', path=(branch,), cond=True, indent='    '),
                              ForLoopColumn('pass', span=(5, 5), path=(branch,), indent='        ',
                                            placeholder=True)),
                     end_line=5, body_lines=(3, 5), rows=(('1', '1', 'False', None), ('2', '2', 'True', None)),
                     values=((1, 1, False, NO_VALUE), (2, 2, True, NO_VALUE)), init=(None, '0', None, None))

    def test_once_the_if_is_back_its_pass_opens_for_what_it_runs(self):
        model, _ = update(key('Enter'), None, {'adding_if': True, 'column_input': 'element > 1'}, table())
        # The run the Enter came in on still draws the loop as it was.
        visualize(table(), model)
        self.assertIsNone(model.get('editing_column'))
        out = visualize(self.with_new_if(), model)
        self.assertEqual((model.get('editing_column'), model.get('column_input'), 'pending_branch' in model),
                         (3, '', False))
        self.assertIn('placeholder="Runs when element &gt; 1"', header_cells(out)[-1])

    def test_what_is_typed_there_writes_over_the_pass(self):
        model, _ = update(key('Enter'), None, {'adding_if': True, 'column_input': 'element > 1'}, table())
        visualize(self.with_new_if(), model)
        model = {**model, 'column_input': 'big = element'}
        self.assertEqual(update(key('Enter'), None, model, self.with_new_if())[1],
                         [ReplaceLines(5, 5, '        big = element')])

    def test_a_loop_that_comes_back_without_the_branch_gives_up_on_it(self):
        model, _ = update(key('Enter'), None, {'adding_if': True, 'column_input': 'element > 1'}, table())
        visualize(plain(), model)
        self.assertEqual((model.get('editing_column'), 'pending_branch' in model), (None, False))

    def test_a_new_elif_or_else_opens_its_pass_too(self):
        from for_loop_visualizer import AddElseClick
        model, _ = update(key('Enter'), None, {'adding_elif': 3, 'column_input': 'x > 6'}, branched())
        self.assertEqual(model.get('pending_branch', {}).get('line'), 8)
        model, _ = update(click(AddElseClick(chain=3)), None, {}, no_else())
        self.assertEqual(model.get('pending_branch', {}).get('line'), 8)
        # An else's pass, back on its line, says when it runs.
        model = {**model, 'pending_branch': {**model['pending_branch'], 'line': 6}}
        out = visualize(else_pass(), model)
        self.assertEqual(model.get('editing_column'), 3)
        self.assertIn('placeholder="Runs when no condition holds"', header_cells(out)[-1])

    def test_a_branchs_arrow_is_drawn_as_a_columns_is(self):
        """At the header's right end, after its condition, shown on hover, and
        muted as every other table's ▾ is."""
        heads = [th for th in header_cells(visualize(branched(), {})) if 'for-loop-branch-header' in th]
        for th in heads:
            self.assertIn('snc-hover-hidden-parent', th)
            trigger = re.search(r'<span class="snc-dropdown-trigger col-menu-trigger"><span [^>]*'
                                r'class="col-menu snc-hover-hidden full-opacity-on-hover">▾</span>', th)
            self.assertIsNotNone(trigger)
            self.assertLess(th.index('class="col-name"'), trigger.start())
        folded = header_cells(visualize(branched(), {'chains': {'3': False}}))[-1]
        self.assertLess(folded.index('class="col-name"'), folded.index('col-menu-trigger'))

    def test_every_branch_of_a_chain_has_the_menu(self):
        from for_loop_visualizer import ChainMenuToggle
        events = events_in(visualize(branched(), {}))
        self.assertEqual([e for e in events if e.startswith('ChainMenuToggle')],
                         [repr(ChainMenuToggle(chain=3, branch=b)) for b in range(3)])
        heads = header_grid(visualize(branched(), {}))[0]
        self.assertEqual([text for text, _, _ in heads[2:]], ['if x % 2 == 0', 'elif x > 4', 'else'])

    def test_an_elifs_or_an_elses_menu_only_removes_it(self):
        from for_loop_visualizer import ChainMenuToggle, RemoveBranchClick
        for branch in (1, 2):
            model, _ = update(click(ChainMenuToggle(chain=3, branch=branch)), None, {}, branched())
            out = visualize(branched(), model)
            self.assertEqual(chain_menu_of(out), [('Remove', True)])
            self.assertIn(repr(RemoveBranchClick(chain=3, branch=branch)), events_in(out))

    def test_removing_an_elif_or_an_else_deletes_only_its_lines(self):
        from for_loop_visualizer import RemoveBranchClick
        model, cmds = update(click(RemoveBranchClick(chain=3, branch=1)), None, {'chain_menu': [3, 1]}, branched())
        self.assertEqual((model.get('chain_menu'), cmds), (None, [ReplaceLines(5, 6, None)]))
        self.assertEqual(update(click(RemoveBranchClick(chain=3, branch=2)), None, {}, branched())[1],
                         [ReplaceLines(7, 8, None)])

    def test_removing_the_if_removes_the_whole_chain(self):
        from for_loop_visualizer import RemoveBranchClick
        self.assertEqual(update(click(RemoveBranchClick(chain=3, branch=0)), None, {}, nested())[1],
                         [ReplaceLines(3, 8, None)])
        # One in a branch, with more of the branch after it.
        self.assertEqual(update(click(RemoveBranchClick(chain=4, branch=0)), None, {}, nested())[1],
                         [ReplaceLines(4, 5, None)])

    def test_removing_a_chain_that_is_all_of_its_block_leaves_a_pass(self):
        from for_loop_visualizer import RemoveBranchClick
        self.assertEqual(update(click(RemoveBranchClick(chain=3, branch=0)), None, {}, branched())[1],
                         [ReplaceLines(3, 8, '    pass')])

    def test_a_folded_chains_remove_removes_all_of_it(self):
        from for_loop_visualizer import RemoveBranchClick
        out = visualize(nested(), {'chains': {'3': False}, 'chain_menu': [3, 0]})
        self.assertIn(repr(RemoveBranchClick(chain=3, branch=0)), events_in(out))

    def test_removing_a_branch_that_is_gone_writes_nothing(self):
        from for_loop_visualizer import RemoveBranchClick
        self.assertEqual(update(click(RemoveBranchClick(chain=3, branch=5)), None, {}, branched())[1], [])

    def test_double_clicking_a_pass_writes_over_it(self):
        model, _ = update(click(ColumnClick(col=3, label='pass'), detail=2), None, {}, else_pass())
        model = {**model, 'column_input': "tag = 'odd'"}
        self.assertEqual(update(key('Enter'), None, model, else_pass())[1],
                         [ReplaceLines(6, 6, "        tag = 'odd'")])


BRANCHED_SOURCE = (
    "for x in [3, 8, 5]:",
    "    if x % 2 == 0:",
    "        tag = 'even'",
    "    elif x > 4:",
    "        tag = 'big'",
    "    else:",
    "        total += x",
)


def two_elifs(**overrides):
    """A chain with two elifs to reorder:

        2  for x in xs:
        3      if a:
        4          p = 1
        5      elif b:
        6          p = 2
        7      elif c:
        8          p = 3
        9      else:
        10         p = 4
    """
    steps = [(3, 0, 'if a', 4, 4), (3, 1, 'elif b', 6, 6), (3, 2, 'elif c', 8, 8), (3, 3, 'else', 10, 10)]
    columns = [bound('x')]
    for step in steps:
        if step[2] != 'else':
            columns.append(ForLoopColumn(step[2], path=(step,), cond=True, indent='    '))
        columns.append(statement(f'p = {step[1] + 1}', step[3], 'p', path=(step,), indent='        '))
    fields = dict(line=2, end_line=10, columns=tuple(columns), rows=(), values=(), targets=('x',),
                  defined=frozenset({'p', 'x'}), body_lines=(3, 10), init=(None,) * len(columns),
                  source=('for x in xs:', '    if a:', '        p = 1', '    elif b:', '        p = 2',
                          '    elif c:', '        p = 3', '    else:', '        p = 4'))
    fields.update(overrides)
    return branched(**fields)


def moved(msg, buttons=1):
    """The event the mouse moving over what sends `msg` sends, a button held."""
    return {'pythonEventStr': repr(msg), 'eventJSON': {'type': 'MouseMove', 'buttons': buttons}}


class TestReorderingAnIfsBranches(unittest.TestCase):
    """An elif's header has a ⣿ to drag it by, as a table's column has: dropped
    on another conditional branch of its chain -- the `if` or an `elif`, not
    the `else`, which is always last -- it is tested in that one's place.
    Whichever branch ends up first is the `if`."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_only_an_elif_has_a_handle(self):
        from for_loop_visualizer import BranchDragStart
        starts = [e for e in events_in(visualize(two_elifs(), {})) if e.startswith('BranchDragStart')]
        self.assertEqual(starts, [repr(BranchDragStart(chain=3, branch=1)), repr(BranchDragStart(chain=3, branch=2))])

    def test_while_dragging_the_conditional_branches_are_where_it_can_go(self):
        from for_loop_visualizer import BranchDragOver, BranchDragStart
        model, cmds = update(click(BranchDragStart(chain=3, branch=2)), None, {}, two_elifs())
        self.assertEqual((model.get('branch_drag'), cmds), ({'chain': 3, 'from': 2, 'over': 2}, []))
        out = visualize(two_elifs(), model)
        overs = re.findall(r'snc-mouse-move="([^"]*)"', out)
        self.assertEqual([html.unescape(e) for e in overs],
                         [repr(BranchDragOver(chain=3, branch=b)) for b in range(3)])

    def test_dragging_over_a_branch_marks_where_it_lands(self):
        from for_loop_visualizer import BranchDragOver
        model = {'branch_drag': {'chain': 3, 'from': 2, 'over': 2}}
        model, _ = update(moved(BranchDragOver(chain=3, branch=1)), None, model, two_elifs())
        self.assertEqual(model['branch_drag'], {'chain': 3, 'from': 2, 'over': 1})
        heads = header_cells(visualize(two_elifs(), model))
        self.assertIn('col-drag-before', next(th for th in heads if 'elif b' in th))
        self.assertIn('col-drag-source', next(th for th in heads if 'elif c' in th))

    def test_the_mouse_up_somewhere_else_ends_the_drag(self):
        from for_loop_visualizer import BranchDragOver
        model = {'branch_drag': {'chain': 3, 'from': 2, 'over': 1}}
        model, _ = update(moved(BranchDragOver(chain=3, branch=0), buttons=0), None, model, two_elifs())
        self.assertIsNone(model.get('branch_drag'))

    def test_dropping_an_elif_earlier_tests_it_first(self):
        from for_loop_visualizer import BranchDragEnd
        model = {'branch_drag': {'chain': 3, 'from': 2, 'over': 1}}
        model, cmds = update(click(BranchDragEnd(chain=3, branch=1)), None, model, two_elifs())
        self.assertEqual((model.get('branch_drag'), cmds), (None, [ReplaceLines(3, 8, '\n'.join((
            '    if a:', '        p = 1', '    elif c:', '        p = 3', '    elif b:', '        p = 2')))]))

    def test_dropping_an_elif_later_tests_it_after(self):
        from for_loop_visualizer import BranchDragEnd
        cmds = update(click(BranchDragEnd(chain=3, branch=2)), None,
                      {'branch_drag': {'chain': 3, 'from': 1, 'over': 2}}, two_elifs())[1]
        self.assertEqual(cmds, [ReplaceLines(3, 8, '\n'.join((
            '    if a:', '        p = 1', '    elif c:', '        p = 3', '    elif b:', '        p = 2')))])

    def test_dropped_on_the_if_it_becomes_the_if(self):
        from for_loop_visualizer import BranchDragEnd
        cmds = update(click(BranchDragEnd(chain=3, branch=0)), None,
                      {'branch_drag': {'chain': 3, 'from': 1, 'over': 0}}, branched(source=BRANCHED_SOURCE))[1]
        self.assertEqual(cmds, [ReplaceLines(3, 6, '\n'.join((
            '    if x > 4:', "        tag = 'big'", '    elif x % 2 == 0:', "        tag = 'even'")))])

    def test_dropped_on_itself_or_the_else_it_stays(self):
        from for_loop_visualizer import BranchDragEnd
        for over in (2, 3):
            model, cmds = update(click(BranchDragEnd(chain=3, branch=over)), None,
                                 {'branch_drag': {'chain': 3, 'from': 2, 'over': over}}, two_elifs())
            self.assertEqual((model.get('branch_drag'), cmds), (None, []))

    def test_live_only_has_no_handle(self):
        visualizer_utils.set_live_only(True)
        self.assertNotIn('BranchDragStart', visualize(two_elifs(), {}))


GUARD = (2, 0, 'if x == 1', 2, 2)


def guard(**overrides):
    """A guard the row menu writes, on one line:

        1  for x in [1, 2]:
        2      if x == 1: continue
        3      y = x
    """
    fields = dict(line=1, end_line=3, indent='', body_indent='    ',
                  columns=(bound('x'),
                           ForLoopColumn('if x == 1', path=(GUARD,), cond=True, indent='    '),
                           ForLoopColumn('continue', span=(2, 2), path=(GUARD,), indent='    ', placeholder=True),
                           statement('y = x', 3, 'y', indent='    ')),
                  rows=(('1', 'True', None, None), ('2', 'False', None, '2')),
                  values=((1, True, NO_VALUE, NO_VALUE), (2, False, NO_VALUE, 2)),
                  targets=('x',), defined=frozenset({'x', 'y'}), body_lines=(2, 3), init=(None,) * 4,
                  source=('for x in [1, 2]:', '    if x == 1: continue', '    y = x'))
    fields.update(overrides)
    return ForLoopTable(**fields)


class TestGuards(unittest.TestCase):
    """A guard -- `if cond: continue` or `break` -- is drawn as any `if` is, so
    it can be changed: its continue says which iterations it skipped. Written
    on one line, as the row menu writes it, it opens out into a block before
    anything is written into it, so the `if` sharing its line survives."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_its_continue_marks_the_iterations_it_skipped(self):
        self.assertEqual(cell_grid(visualize(guard(), {})), [['1', 'True', 'continue', '—'],
                                                             ['2', 'False', '///', '2']])

    def test_writing_over_its_continue_opens_it_out(self):
        model = editing(2, 'skipped += 1')
        self.assertEqual(update(key('Enter'), None, model, guard())[1],
                         [ReplaceLines(2, 2, '    if x == 1:\n        skipped += 1')])

    def test_inserting_beside_its_continue_opens_it_out(self):
        before = {**adding('skipped += 1'), 'insert_at': {'label': 'continue', 'after': False}}
        self.assertEqual(update(key('Enter'), None, before, guard())[1],
                         [ReplaceLines(2, 2, '    if x == 1:\n        skipped += 1\n        continue')])
        after = {**adding('print(x)'), 'insert_at': {'label': 'continue', 'after': True}}
        self.assertEqual(update(key('Enter'), None, after, guard())[1],
                         [ReplaceLines(2, 2, '    if x == 1:\n        continue\n        print(x)')])

    def test_inserting_right_of_its_condition_writes_at_the_top_of_the_branch(self):
        model = {**adding('skipped += 1'), 'insert_at': {'label': 'if x == 1', 'after': True}}
        self.assertEqual(update(key('Enter'), None, model, guard())[1],
                         [ReplaceLines(2, 2, '    if x == 1:\n        skipped += 1\n        continue')])

    def test_removing_its_continue_leaves_a_pass_on_the_line(self):
        cmds = update(click(DeleteColumnClick(col=2, label='continue')), None, {}, guard())[1]
        self.assertEqual(cmds, [ReplaceLines(2, 2, '    if x == 1: pass')])

    def test_its_menu_is_an_ifs(self):
        out = visualize(guard(), {'chain_menu': [2, 0]})
        self.assertEqual([label for label, _ in chain_menu_of(out)], ['Collapse', 'Add Elif', 'Add Else', 'Remove'])


def only_pass(**overrides):
    """A loop as written new, its body only the `pass` holding its place:

        1  count = 0
        2  for element in [1, 2]:
        3      pass
    """
    fields = dict(columns=(bound('element'),), rows=(('1',), ('2',)), values=((1,), (2,)),
                  defined=frozenset({'count', 'element'}), init=(None,),
                  source=('for element in [1, 2]:', '    pass'))
    fields.update(overrides)
    return table(**fields)


class TestAPassOnlyHoldsTheBodysPlace(unittest.TestCase):
    """A body that is only a `pass` has nothing in it yet: the first line
    written into it goes over the pass rather than beside it."""

    def setUp(self):
        visualizer_utils.set_live_only(False)

    def tearDown(self):
        visualizer_utils.set_live_only(False)

    def test_the_first_column_writes_over_the_pass(self):
        _, cmds = update(key('Enter'), None, adding('twice = element * 2'), only_pass())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    twice = element * 2')])

    def test_so_does_one_inserted_right_of_a_bound_name(self):
        model = {**adding('twice = element * 2'), 'insert_at': {'label': 'element', 'after': True}}
        self.assertEqual(update(key('Enter'), None, model, only_pass())[1],
                         [ReplaceLines(3, 3, '    twice = element * 2')])

    def test_a_new_if_writes_over_it_and_its_own_pass_is_waited_for_a_line_up(self):
        model, cmds = update(key('Enter'), None, {'adding_if': True, 'column_input': 'element > 1'}, only_pass())
        self.assertEqual((cmds, model['pending_branch']['line']),
                         ([ReplaceLines(3, 3, '    if element > 1:\n        pass')], 4))

    def test_what_goes_above_the_loop_still_does_once_the_pass_is_written_over(self):
        """The pass first: the line going in above the loop would move it."""
        _, cmds = update(click(ActionButtonClick(action='count')), None, {}, only_pass())
        self.assertEqual(cmds, [ReplaceLines(3, 3, '    n_iterations += 1'), InsertLines(((1, 'n_iterations = 0'),))])

    def test_a_line_after_the_loop_leaves_the_pass_alone(self):
        _, cmds = update(click(RowActionClick(row=1, action='extract')), None, {}, only_pass())
        self.assertEqual(cmds, [InsertLines(((3, "row_1 = {'element': 2}"),))])

    def test_a_pass_on_the_loops_own_line_is_left_alone(self):
        t = only_pass(line=3, body_lines=(3, 3), source=('for element in [1, 2]: pass',))
        self.assertEqual(update(key('Enter'), None, adding('twice = element * 2'), t)[1],
                         [InsertLines(((3, '    twice = element * 2'),))])

    def test_a_body_with_more_than_a_pass_is_written_beside(self):
        t = only_pass(end_line=4, body_lines=(3, 4), source=('for element in [1, 2]:', '    pass', '    print(element)'))
        self.assertEqual(update(key('Enter'), None, adding('twice = element * 2'), t)[1],
                         [InsertLines(((4, '    twice = element * 2'),))])


class TestValueDependentEvents(unittest.TestCase):
    def test_only_value_dependent_events_wait_for_the_finished_table(self):
        import for_loop_visualizer as vis
        for msg in (RowActionClick(0, 'skip'), TallySelectAll('x'), TallySelectNone('x'),
                    TallyItemToggle('x', '1'), ChildEvent('0\x00x', 'PinFocus()')):
            with self.subTest(msg=msg):
                self.assertTrue(vis.needs_values(click(msg), {}))
        for msg in (AddColumnClick(), ColumnMenuToggle('x'), ColumnInput('x.upper()'),
                    ColumnToggle('x')):
            with self.subTest(msg=msg):
                self.assertFalse(vis.needs_values(click(msg), {}))

    def test_method_submissions_need_values_but_other_box_events_do_not(self):
        import for_loop_visualizer as vis
        for key in ('Enter', 'Tab', 'Escape'):
            for text in ('word.upper()', 'result = word.upper()', 'word * 2', 'broken('):
                with self.subTest(key=key, text=text):
                    self.assertEqual(vis.needs_values(
                        {'pythonEventStr': 'ColumnKeyDown()', 'eventJSON': {'key': key}},
                        {'adding_column': True, 'column_input': text}),
                        key != 'Escape' and text == 'word.upper()')


if __name__ == '__main__':
    unittest.main()
