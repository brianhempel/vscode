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
from for_loop_visualizer import (AddColumnClick, AddMenuDismiss, AddMenuToggle, CollectClick, ColumnClick,
                                 ColumnHideAll, ColumnInput, ColumnInputBlur, ColumnKeyDown, ColumnMenuDismiss,
                                 ColumnMenuToggle, ColumnResize, ColumnShowAll, ColumnToggle, ComputeCodeClick,
                                 ComputeFreeInput, ComputeToggle, ConvertColumnClick, ConvertToggle,
                                 DeleteColumnClick, GroupByClick, InitCellClick, InsertColumnClick, LoadMoreRows,
                                 SubmenuDwell, SubmenuToggle, can_visualize, init_model, update, visualize)
from visualizer_utils import AddImports, ForLoopColumn, ForLoopTable, InsertLines, ReplaceLines


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
    """A loop with no accumulator, so no init row:

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
    """Each <tr> of the body, as the text of its cells."""
    body = re.search(r'<tbody>(.*?)</tbody>', html_text).group(1)
    return [[html.unescape(re.sub(r'<[^>]*>', '', c)) for c in re.findall(r'<td[^>]*>.*?</td>', tr)]
            for tr in re.findall(r'<tr[^>]*>.*?</tr>', body)]


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
        self.assertEqual(body_rows(out), [['0', '1', '2'], ['1', '2', '4']])

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

    def test_has_no_bar_of_buttons_under_the_table(self):
        out = visualize(table(targets=('i', 'element')), {})
        self.assertNotIn('action-button', out)
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
                    self.assertIn('draggable="false"', button)

    def test_the_plus_is_a_bar_beside_the_table_drawn_focused_or_not(self):
        # A table's (+), except that a table only draws its own once it is
        # focused, and this one never is.
        for small in (True, False):
            with self.subTest(small=small):
                out = visualize(table(), {}, small=small)
                bar = re.search(r'</table></div>(<div class="snc-dropdown-trigger col-add-trigger">.*?</div>)', out)
                self.assertEqual(events_in(bar.group(1)), [repr(AddMenuToggle())])
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
            ('Add Column', None), '--',
            ('i', True), ('element', True), '--',
            ('Show all', None), ('Hide all', None), '--',
            ('count += 1', True), ('twice = element * 2', False)])
        self.assertEqual(events_in(menu_of(out)), [
            repr(AddColumnClick()),
            repr(ColumnToggle(label='i')), repr(ColumnToggle(label='element')),
            repr(ColumnShowAll()), repr(ColumnHideAll()),
            repr(ColumnToggle(label='count += 1')), repr(ColumnToggle(label='twice = element * 2'))])

    def test_a_loop_with_no_statement_of_its_own_has_nothing_under_the_pair(self):
        t = table(columns=(bound('element'),), rows=(('1',),), init=(None,))
        self.assertEqual(menu_rows(visualize(t, {'add_menu_open': True})),
                         [('Add Column', None), '--', ('element', True), '--', ('Show all', None), ('Hide all', None)])

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
        self.assertEqual(body_rows(out), [['0', '1'], ['1', '2']])
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
        rows = body_rows(out)
        self.assertEqual([r[0] for r in rows], [str(i) for i in range(50)] + ['Load 7 more'] + ['57', '58', '59'])
        self.assertIn(f'snc-mouse-down="{html.escape(repr(LoadMoreRows()))}"', out)

    def test_the_load_more_row_says_how_many_are_left_when_more_than_a_page(self):
        rows = body_rows(visualize(many(200), {}))
        self.assertIn(['Load 50 more (147 hidden)'], rows)

    def test_load_more_draws_another_page(self):
        model, cmds = update(click(LoadMoreRows()), None, {}, many(200))
        self.assertEqual((model, cmds), ({'shown_rows': 100}, []))
        rows = body_rows(visualize(many(200), model))
        self.assertEqual(len(rows), 100 + 1 + 3)

    def test_a_short_loop_draws_every_row(self):
        self.assertEqual(len(body_rows(visualize(many(52), {}))), 52)

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
            ('Group By', True), ('Change Type', True), ('Compute', True), ('Collect into List', True)])

    def test_a_bound_name_has_no_line_to_remove_or_put_anything_before(self):
        self.assertEqual(menu_options(visualize(table(), {'col_menu': 'element'})), [
            ('Remove', False), ('Insert Left', False), ('Insert Right', True),
            ('Group By', True), ('Change Type', True), ('Compute', True), ('Collect into List', True)])

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
        self.assertEqual(cells, ['', '', '', 'Sum8'])
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


if __name__ == '__main__':
    unittest.main()
