"""For loop visualizer for Sculpt-n-Code.

When a `for` loop finishes, the runner logs a ForLoopTable on its last line:
a row per iteration, a column per value the loop computed. It logs one with
no rows there as the loop starts too, so a loop that never finishes still
shows its columns. The editor shows it
in place of the loop's body while the cursor is outside the loop, so a loop
reads as what it did rather than as one iteration of it.

    itr | element | count += 1
    0   | 1       | 1
    1   | 2       | 2

**The (+) opens the menu a table's does.** Add Column, then a box per name
the loop binds, then Show all and Hide all over a box per line of its body --
the shape of a table's, whose row columns are what every table has and whose
fields are what this one's rows turned out to hold. A loop's columns are code,
though, so a box only shows or hides a column of the table, by its label;
Remove, in the column's menu, is what deletes the line. Like a table's, the menu stays open as boxes are
ticked, and a click anywhere else puts it away.

**Add Column adds a column of the user's own.** It opens a box at the end of
the header row, as a table's does. A loop's column is a line of its
body rather than a table's view of its rows, so what is typed is a statement --
`doubled = element * 2` -- and Enter writes it at the end of the body, where the
next run draws it as the last column. That code lands away from the line this
visualizer sits on, so it goes out as InsertLines rather than a NewCode tuple.
Leaving the box closes it unwritten: a table's column box writes on blur, but
that is a view, and this is code. The (+) is a bar beside the table, as a
table's is, except that a table only draws its own once it is focused, and this
one draws it either way.

**A column is edited through its header.** Double-clicking a statement's
header opens the same box over it, holding the statement; Enter writes what it
then holds over the statement's lines. A name the loop binds has no statement
of its own, so its header has nothing to edit.

**A header underlines what its column shows.** A statement is not a value:
`arr2.append(x)` shows arr2 after the call, `total += x` shows total. The
underlined part is the start of the label (see ForLoopColumn.underline).

**The init row is where an accumulator starts.** A column whose statement reads
the value the iteration before left -- `total += x`, `arr2.append(x)` -- has a
cell above the first iteration: the value before the loop, or a `set…` when
there is none, which is why the loop died. Double-clicking it opens the box on
that value; Enter writes `name = value` over the line that set it right before
the loop, or as a new line above the loop when nothing there did. A column
added with the (+) that turns out to need one opens that box by itself once it
is back.

**A column's ▾ opens a table's column menu**, held open by the model as a
table's is (`col_menu`, and `submenu` for the one flying out of it), and put
away by a click anywhere else. What it does to a loop is write loop code:

- Remove deletes the statement, leaving a `pass` when nothing else would be
  left in the body. Insert Left / Right open the box beside the column, and
  Enter writes the line before or after its statement -- right of a name the
  loop binds is the top of the body, and there is nothing left of one.
- Group By opens the box on a name for a dict; Enter writes `name = {}` above
  the loop and `name.setdefault(subject, []).append(item)` at the end of its
  body, `item` being the names the loop binds.
- Change Type ticks a type to wrap a plain assignment's value in it (and
  unticking unwraps it); beside each, a button writes `subject_int =
  int(subject)` beside the column.
- Compute previews the table's catalog of answers off the column's values, and
  a tick keeps one under the table, as a table's does. Sum, Min and Max, and
  the Unique and Tally rows, also write what builds the answer up as the loop
  runs: a name set above it, and a line at the end of its body.
- Collect into List opens the box on a name for the list, and Enter writes
  `name = []` above the loop and `name.append(subject)` at the end of its
  body, which comes back as a column of its own, starting from []. A column
  that changes its name in place has one object in every row, so it offers
  none.

**Searching, sorting and tallying are views, as a table's are.** The footer's
search box takes a condition over the loop's names (`score > 5`), each row's
values bound to them; the iterations it holds for are marked and the rest
dimmed, and 1st keeps only the first. A column's menu opens with a search row
of its own, its value compared against what is typed, composed with the
searches before it; its tally, at the menu's foot, is the table's -- ticking
values writes them into that row as a table's does. Sort draws the iterations
in a column's order, still numbered by when they ran. None of it writes code:
a loop's iterations are not a list to filter, and all of it reads the values
the runner copied, so a loop still running has none to search.

**A cell is its value's own visualizer**, as a table's is: small until a
press focuses it (then routed its events, as a ChildEvent keyed by row and
column), nested so a table in one draws as its repr, and with nowhere to save
to -- a loop's line has no config for a cell's to go in. Only the page of rows
being drawn is visualized. Subcolumns, in a column's menu, spreads its values'
fields into columns of their own under its header, as a table's does: a view,
so nothing is written.

**What a table writes about its rows, a loop writes as loop code.** The
footer's buttons -- Count, Extract, Filter, Any, All -- turn the search into
a name set above the loop and a line at the end of its body building it up
(Filter: a `continue` at the top); under the pick tool, Extract collects the
picked columns. An iteration's ▾ writes `if score == 9: continue` or `break`
at the top of the body, or its cells as a dict after the loop. A header hands
over the name its column shows, and the line box suggests how to finish the
name being typed -- the loop's names, and the fields of what it binds. Not
the table's chain link: what a loop's buttons write lands in two places, and
a link is one line under the visualizer's own.

**While the loop runs, the rows of last time.** The table logged as the loop
starts has none of its own yet, and the finished one replaces it a moment
later. Drawn empty, it would shrink and regrow the table on every run -- every
key typed in its box -- and move everything under it with it. So a finished
table leaves its rows in the model, and the running one draws them, matched to
its columns by label.

**Focused by a click, as a table is.** The table only shows while the cursor
is outside the loop, so a press on it pins focus to the table itself and the
editor keeps the loop collapsed (see collapsedForLoops in snc.ts); the cursor
going into the loop's code is what opens it. Focused, it is drawn as a focused
table is -- a taller pane, and the rest of a table's chrome. Unfocused, the
(+), the headers, the init cells and the menus still work without spending
the press on focus: they are snc-unfocused-clickable. The box takes the
keyboard as it opens, for the same reason.

**A page of rows at a time.** Fifty, then the last three, with a row between
that loads the next fifty -- a table's paging. Columns drag wider by their
header's right edge, the width kept by label in the model.

Sorts before `z_object_visualizer` (which claims everything) so that the table
reaches it rather than being shown as a dataclass's fields.
"""

import ast
import html
import keyword
import math
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from table_visualizer import (COLUMN_SEARCH_COMPOSE, COLUMN_SEARCH_OPS, COMPUTE_AGGS, CONVERT_TYPES, NO_THING,
                               TALLY_COUNT_EXTREME_OPS, TALLY_COUNT_OPS, TALLY_SORTS, _TALLY_NOTES,
                               _TOOL_TOOLBAR_TOOLS, _agg_answer_html,
                               _agg_value, _column_search_value_label, _get_all_possible_columns, _in_tally_order,
                               _tally, _tally_count_op,
                               _tally_count_op_label, _tally_extreme, _tally_lists, _tally_rows, _tally_selection,
                               _tally_literal, _tally_shown, _tally_sort, _tally_sort_label)
from visualizer_utils import (EXPANDED_PANE_MAX_HEIGHT, ICONS, NO_VALUE, AddImports, ChildEvent, ForLoopColumn,
                              ForLoopTable, InsertLines, ReplaceLines, aggregate_handled_keys,
                              call_with_supported_kwargs, child_nesting_kwargs, error_html, eval_dollar_expr,
                              is_live_only, py_exp_attrs, render_tool_toolbar,
                              route_child_event, truncate_repr, wrap_child_prefix, wrap_child_suffix)


@dataclass(frozen=True)
class AddMenuToggle:
    """A press on the (+): open its menu, or put it away."""


@dataclass(frozen=True)
class AddMenuDismiss:
    """A press outside the open (+) menu: put it away."""


@dataclass(frozen=True)
class AddColumnClick:
    """Add Column, in the (+) menu: open the box a column is written in."""


@dataclass(frozen=True)
class ColumnToggle:
    """The box of the column labeled `label`, in the (+) menu: hide it, or
    show it again."""
    label: str


@dataclass(frozen=True)
class ColumnShowAll:
    """Show all, in the (+) menu: every line of the body gets its column back."""


@dataclass(frozen=True)
class ColumnHideAll:
    """Hide all, in the (+) menu: every line of the body's column goes, and the
    names the loop binds stay."""


@dataclass(frozen=True)
class ColumnClick:
    """A press on the header of column `col`, labeled `label` when it was
    drawn; a double-click opens the box over it."""
    col: int
    label: str


@dataclass(frozen=True)
class DeleteColumnClick:
    """A press on the x of column `col`, labeled `label` when it was drawn."""
    col: int
    label: str


@dataclass(frozen=True)
class InitCellClick:
    """A press on the init cell of column `col`, labeled `label` when it was
    drawn; a double-click opens the box setting where it starts."""
    col: int
    label: str


@dataclass(frozen=True)
class CollectClick:
    """Collect into List, in the menu of column `col`, labeled `label` when it
    was drawn: open the box naming the list."""
    col: int
    label: str


@dataclass(frozen=True)
class ColumnResize:
    """The column labeled `label` was dragged to `width` pixels. The width
    comes first: the editor writes it over the `width=0` it was drawn with."""
    width: Any
    label: str


@dataclass(frozen=True)
class LoadMoreRows:
    """The row standing in for the iterations not drawn: draw another page."""


@dataclass(frozen=True)
class ColumnMenuToggle:
    """A press on the ▾ of the column labeled `label`: open its menu, or put
    it away."""
    label: str


@dataclass(frozen=True)
class ColumnMenuDismiss:
    """A press outside the open column menu: put it away."""


@dataclass(frozen=True)
class SubmenuToggle:
    """A press on a row of the column menu that opens a submenu (`compute`,
    `convert`): open it, or put it away."""
    submenu: str


@dataclass(frozen=True)
class SubmenuDwell:
    """The pointer came to rest on a row of the column menu: open the
    submenu it has, or put away the open one when it has none (None)."""
    submenu: Optional[str]


@dataclass(frozen=True)
class InsertColumnClick:
    """Insert Left or Right, in the menu of column `col`: open the box, beside
    it, that writes a line before or after its statement."""
    col: int
    label: str
    after: bool


@dataclass(frozen=True)
class GroupByClick:
    """Group By, in the menu of column `col`: open the box naming the dict the
    loop's iterations are grouped into by the column's value."""
    col: int
    label: str


@dataclass(frozen=True)
class ConvertToggle:
    """A type ticked in the Change Type submenu of column `col`: its
    assignment reads its value as `to`, or stops reading it as one."""
    col: int
    label: str
    to: str


@dataclass(frozen=True)
class ConvertColumnClick:
    """A type's new-column button in the Change Type submenu: a line beside the
    column's that reads its value as `to`."""
    col: int
    label: str
    to: str


@dataclass(frozen=True)
class ComputeToggle:
    """An answer ticked in the Compute submenu of the column labeled `label`:
    keep it under the table, or stop."""
    label: str
    template: str


@dataclass(frozen=True)
class ComputeFreeInput:
    """The Compute submenu's own box, for an answer of the user's, now holds
    `value`."""
    label: str
    value: str


@dataclass(frozen=True)
class ComputeCodeClick:
    """A Compute row that writes code: what builds the answer up as the loop
    runs (`unique`, `tally`, `sum`, `min`, `max`)."""
    col: int
    label: str
    kind: str


@dataclass(frozen=True)
class SearchBoxInput:
    """The footer's search box now holds `value`: a condition over the loop's
    names, marking the iterations it holds for."""
    value: str


@dataclass(frozen=True)
class FirstMatchToggle:
    """The 1st beside the search box: mark only the first match, or every one."""


@dataclass(frozen=True)
class ColumnSearchInput:
    """The search row atop the menu of the column labeled `label` now holds
    `value`, what the column's value is compared against."""
    label: str
    value: str


@dataclass(frozen=True)
class ColumnSearchOpSelect:
    """The comparison a column's search makes."""
    label: str
    op: str


@dataclass(frozen=True)
class ColumnSearchComposeSelect:
    """How a column's search goes with the searches before it."""
    label: str
    compose: str


@dataclass(frozen=True)
class SortToggle:
    """Ascending or Descending, in the Sort submenu of the column labeled
    `label`: draw the iterations in that order, or in the loop's again."""
    label: str
    direction: str


@dataclass(frozen=True)
class TallyItemToggle:
    """A value in a column's tally: search for it too, or stop."""
    label: str
    literal: str


@dataclass(frozen=True)
class TallySelectAll:
    """All, in a column's tally: search for every value it shows."""
    label: str


@dataclass(frozen=True)
class TallySelectNone:
    """None, in a column's tally: search for none of the values it shows."""
    label: str


@dataclass(frozen=True)
class TallyExcludeToggle:
    """Exclude, in a column's tally: search for everything but its values."""
    label: str


@dataclass(frozen=True)
class TallyFilterInput:
    """The tally's own box now holds `value`: only values reading so are shown."""
    label: str
    value: str


@dataclass(frozen=True)
class TallyCountFilterInput:
    """The tally's count box now holds `value`: only values with so many
    iterations are shown."""
    label: str
    value: str


@dataclass(frozen=True)
class TallyCountOpSelect:
    """How the tally's count box compares."""
    label: str
    op: str


@dataclass(frozen=True)
class TallySortSelect:
    """The order the tally lists its values in."""
    sort: str


@dataclass(frozen=True)
class SubcolToggle:
    """A field ticked in the Subcolumns submenu of the column labeled `label`:
    spread it into a column of its own under the column's header, or stop."""
    label: str
    expr: str


@dataclass(frozen=True)
class SubcolShowAll:
    """Show all, in the Subcolumns submenu: every field the values have."""
    label: str


@dataclass(frozen=True)
class SubcolHideAll:
    """Hide all, in the Subcolumns submenu: none of them."""
    label: str


@dataclass(frozen=True)
class SubcolExprInput:
    """The Subcolumns submenu's own box, for a sub-column of the user's, now
    holds `value`: an expression in `$`, the column's value."""
    label: str
    value: str


@dataclass(frozen=True)
class ColumnSelect:
    """A suggestion under the line box: it finishes the name being typed."""
    text: str


@dataclass(frozen=True)
class ActionButtonClick:
    """A button in the footer: write what it names about the iterations the
    search holds for (`count`, `extract`, `filter`, `any`, `all`)."""
    action: str


@dataclass(frozen=True)
class RowMenuToggle:
    """The ▾ on iteration `row`'s number: open its menu, or put it away."""
    row: int


@dataclass(frozen=True)
class RowActionClick:
    """A row of iteration `row`'s menu: skip iterations like it, stop at the
    first, or write its cells after the loop (`skip`, `stop`, `extract`)."""
    row: int
    action: str


@dataclass(frozen=True)
class ToolSelect:
    """A tool in the corner's toolbar: `normal`, or `pick`."""
    tool: str


@dataclass(frozen=True)
class PickToggle:
    """Under the pick tool, a press on the column labeled `label`: pick it,
    or stop."""
    label: str


@dataclass(frozen=True)
class ColumnInput:
    """The column box now holds `value`."""
    value: str


@dataclass(frozen=True)
class ColumnKeyDown:
    """A key in the column box: Enter or Tab writes it, Escape closes it."""


@dataclass(frozen=True)
class ColumnInputBlur:
    """The column box lost the keyboard: it closes, unwritten."""


# A page of rows at a time, and the last few always, as a table draws them.
ROWS_PER_PAGE = 50
TAIL_ROWS = 3

# How tall the pane gets: a table's, on a line that isn't focused and on one
# that is.
SMALL_MAX_HEIGHT = 212


# What separates the parts of a cell's child key -- its row and its column --
# and a sub-column from the column it is spread out of.
CELL_KEY_SEP = '\x00'
SUBCOL_SEP = '\x01'

# The keys the table answers itself, before any its cells' visualizers do.
OWN_KEYS = ['Enter', 'Escape', 'Tab']

# How wide a cell's own visualizer may draw.
CELL_MAX_WIDTH = 400


def can_visualize(value):
    return isinstance(value, ForLoopTable)


def init_model(value, get_visualizer=None):
    return {}


def _column(value: ForLoopTable, col: int, label: str) -> Optional[ForLoopColumn]:
    """Column `col`, if it is still the one that was drawn as `label`. The
    event was drawn against the code as it was, and the loop may have changed
    under it."""
    if not 0 <= col < len(value.columns) or value.columns[col].label != label:
        return None
    return value.columns[col]


def _statement_span(value: ForLoopTable, col: int, label: str) -> Optional[Tuple[int, int]]:
    """The lines of column `col`'s statement, if it is still the column that
    was drawn as `label` and is a statement at all."""
    column = _column(value, col, label)
    return column.span if column is not None else None


def _accumulator(value: ForLoopTable, col: int, label: str) -> Optional[ForLoopColumn]:
    column = _column(value, col, label)
    return column if column is not None and column.accumulator and column.subject else None


def _collectable(value: ForLoopTable, col: int, label: str) -> Optional[ForLoopColumn]:
    column = _column(value, col, label)
    return column if column is not None and column.subject and not column.in_place else None


def _init_of(value: ForLoopTable, col: int) -> Optional[str]:
    return value.init[col] if col < len(value.init) else None


def _parses(statement: str) -> bool:
    try:
        ast.parse(statement)
    except SyntaxError:
        return False
    return True


def _is_value(text: str) -> bool:
    """Whether `text` is an expression alone, as a starting value must be."""
    try:
        ast.parse(text, mode='eval')
    except SyntaxError:
        return False
    return True


def _list_name(value: ForLoopTable, subject: str) -> str:
    """A name for the list `subject` is collected into, that nothing in the
    loop's scope has: `elements` for `element`, `items_list` for `items`."""
    base = f'{subject}_list' if subject.endswith('s') else f'{subject}s'
    name, n = base, 2
    while name in value.defined:
        name, n = f'{base}{n}', n + 1
    return name


BOX_KEYS = ('adding_column', 'editing_column', 'editing_init', 'collecting_column', 'grouping_column')

# What a box opening puts away: the menus it was opened from, and where an
# earlier Insert would have put the line.
MENU_KEYS = ('add_menu_open', 'col_menu', 'submenu', 'insert_at', 'row_menu')


def _box_open(model) -> bool:
    return bool(model.get('adding_column')) or any(model.get(k) is not None for k in BOX_KEYS[1:])


def _opened(model, key: str, col, text: str):
    """The model with one box open -- `key`, on column `col` -- holding
    `text`, and the (+) menu put away."""
    model = {k: v for k, v in model.items() if k not in MENU_KEYS}
    return {**model, 'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, 'grouping_column': None, key: col, 'column_input': text}


def _render_box(model, tag: str = 'th', select_all: bool = False, placeholder: str = 'Line of code',
                tooltip: str = 'Written at the end of the loop', span_attrs: str = '', suggestions=()) -> str:
    """The box code is typed in: a new column's, one being edited, a starting
    value, or the name of a list a column is collected into."""
    input_event = "lambda e: ColumnInput(value=e.get('value', ''))"
    select = ' snc-select-all' if select_all else ''
    return (f'<{tag}{span_attrs}><span class="snc-dropdown-trigger">'
            f'<input type="text" class="col-input" autofocus{select} snc-unfocused-clickable spellcheck="false" '
            f'snc-input="{html.escape(input_event)}" '
            f'snc-blur="{html.escape(repr(ColumnInputBlur()))}" '
            f'value="{html.escape(model.get("column_input", ""))}" '
            f'placeholder="{html.escape(placeholder)}" '
            f'data-tooltip="{html.escape(tooltip)}" />'
            f'{_render_suggestions(model, suggestions)}</span></{tag}>')


def _render_suggestions(model, suggestions) -> str:
    """What could finish the name being typed, under the box as a table's."""
    if not suggestions:
        return ''
    selected = model.get('selected_suggestion')
    items = ''.join(f'<div class="snc-dropdown-option col-suggestion{" selected" if n == selected else ""}"'
                    f'{_press(ColumnSelect(text=text))}>{html.escape(text)}</div>'
                    for n, text in enumerate(suggestions))
    return f'<div class="snc-dropdown-panel left col-suggest-panel" snc-dropdown-align="left">{items}</div>'


def _render_label(column: ForLoopColumn) -> str:
    """The column's label, the part of it that is the value shown underlined."""
    shown, rest = column.label[:column.underline], column.label[column.underline:]
    if not shown:
        return html.escape(column.label)
    return f'<span class="for-loop-col-subject">{html.escape(shown)}</span>{html.escape(rest)}'


# A column's search, before anything is typed into it: the same shape as a
# table's, which is what lets its tally read its selection back out of it.
COLUMN_SEARCH_DEFAULT = {'compose': 'and', 'op': '==', 'text': '', 'exclude': False}

# The submenu slot holds the chips on the search row and the tally too; resting
# on the row a chip belongs to is not a way of leaving it.
SEARCH_CHIPS = ('op', 'compose')
TALLY_CHIPS = ('tally-sort', 'tally-count-op')
SORT_DIRECTIONS = (('asc', 'Ascending'), ('desc', 'Descending'))


def _column_search(model, label: str) -> dict:
    return {**COLUMN_SEARCH_DEFAULT, **((model.get('col_search') or {}).get(label) or {})}


def _set_column_search(model, label: str, **fields) -> dict:
    """The model with the search of the column labeled `label` changed."""
    searches = dict(model.get('col_search') or {})
    searches[label] = {**_column_search(model, label), **fields}
    return {**model, 'col_search': searches}


def _write_selection(model, label: str, literals, exclude: bool) -> dict:
    """A tally's selection written as its column's search, as a table writes
    it: nothing selected is no search, one value compares, several are a
    membership."""
    if not literals:
        return _set_column_search(model, label, op='==', text='', exclude=exclude)
    if len(literals) == 1:
        return _set_column_search(model, label, op='!=' if exclude else '==', text=literals[0], exclude=exclude)
    return _set_column_search(model, label, op='not in' if exclude else 'in', text=f'[{", ".join(literals)}]',
                              exclude=exclude)


def _eval(code: str, names: dict):
    return eval(code, {'math': math}, names)


def _row_names(value: ForLoopTable, row: Tuple[Any, ...]) -> dict:
    """What each of the loop's names held in one iteration, for a search to
    read: the names it binds, and those its statements set."""
    return {column.subject: cell for column, cell in zip(value.columns, row)
            if column.subject and cell is not NO_VALUE}


def _holds(code: str, names: dict) -> bool:
    try:
        return bool(_eval(code, names))
    except Exception:
        return False


def _column_holds(search: dict, cell, names: dict) -> bool:
    """Whether a column's search holds for its value `cell`: compared with
    what was typed, or -- with no comparison -- what was typed, `$` being it."""
    if cell is NO_VALUE:
        return False
    text, op = search['text'].strip(), search['op']
    code = f'_v {op} ({text})' if op else text.replace('$', '_v')
    return _holds(code, {**names, '_v': cell})


def _active_searches(value: ForLoopTable, model) -> List[Tuple[int, dict]]:
    return [(col, _column_search(model, column.label)) for col, column in enumerate(value.columns)
            if _column_search(model, column.label)['text'].strip()]


def _matches(value: ForLoopTable, model) -> Optional[List[int]]:
    """The iterations every search holds for, the footer's then each column's
    in turn, composed as each says; None when nothing is being searched for.
    Read off the values, so a loop still running has none to search."""
    search = (model.get('search') or '').strip()
    columns = _active_searches(value, model)
    if not search and not columns:
        return None
    matched = []
    for i, row in enumerate(value.values):
        names = _row_names(value, row)
        held = _holds(search, names) if search else None
        for col, column_search in columns:
            this = _column_holds(column_search, row[col] if col < len(row) else NO_VALUE, names)
            if held is None:
                held = this
            elif column_search['compose'] == 'or':
                held = held or this
            else:
                held = held and this
        if held:
            matched.append(i)
    return matched[:1] if model.get('first_match') else matched


def _draw_order(value: ForLoopTable, model, n_rows: int) -> List[int]:
    """The iterations in the order they are drawn: the loop's, or a column's
    when it is sorted -- by value, or by how the values read when they won't
    order -- with the ones that never got to it last."""
    order = list(range(n_rows))
    sort = model.get('sort') or {}
    labels = [column.label for column in value.columns]
    if not sort or sort.get('label') not in labels or len(value.values) != n_rows:
        return order
    col = labels.index(sort['label'])
    have = [i for i in order if col < len(value.values[i]) and value.values[i][col] is not NO_VALUE]
    lacking = [i for i in order if i not in set(have)]
    reverse = sort.get('direction') == 'desc'
    try:
        have = sorted(have, key=lambda i: value.values[i][col], reverse=reverse)
    except Exception:
        have = sorted(have, key=lambda i: value.rows[i][col] or '', reverse=reverse)
    return have + lacking


def _subcols(model, value: ForLoopTable, shown: List[int]) -> dict:
    """The sub-columns of each drawn column that has any."""
    subs = model.get('subcols') or {}
    return {col: subs[value.columns[col].label] for col in shown if subs.get(value.columns[col].label)}


def _leaf_label(label: str, sub: Optional[str]) -> str:
    return label if sub is None else f'{label}{SUBCOL_SEP}{sub}'


def _cell_key(i: int, label: str, sub: Optional[str]) -> str:
    return f'{i}{CELL_KEY_SEP}{_leaf_label(label, sub)}'


def _cell_value(value: ForLoopTable, i: int, col: int, sub: Optional[str], eval_in_scope=None):
    """What one cell holds: the value its statement left in iteration `i`, or
    -- under a sub-column -- that read through the sub-column's expression.
    NO_VALUE where there is none; a sub-column that won't read raises."""
    row = value.values[i] if i < len(value.values) else ()
    cell = row[col] if col < len(row) else NO_VALUE
    if cell is NO_VALUE or sub is None:
        return cell
    return eval_dollar_expr(sub, cell, eval_in_scope)


def _child_value(value: ForLoopTable, key: str, eval_in_scope=None):
    """The value under a cell's child key, for an event routed to it."""
    i, leaf = key.split(CELL_KEY_SEP, 1)
    label, _, sub = leaf.partition(SUBCOL_SEP)
    col = next(n for n, column in enumerate(value.columns) if column.label == label)
    return _cell_value(value, int(i), col, sub or None, eval_in_scope)


def _subcol_candidates(value: ForLoopTable, col: int, get_visualizer) -> List[str]:
    """The fields a column's values have, as a table's Subcolumns finds them."""
    values = _column_values(value, col)
    if get_visualizer is None or not values:
        return []
    return _get_all_possible_columns(values, get_visualizer) or []


# The tools of the corner's toolbar: a table's Normal and Pick.
TOOLS = _TOOL_TOOLBAR_TOOLS

# The trailing name a suggestion would finish: a name, and what reads through it.
_TYPED_NAME_RE = re.compile(r"[A-Za-z_][\w\[\]'\".]*$")


def _suggestions(value: ForLoopTable, model, get_visualizer) -> List[str]:
    """What could finish the name at the end of the line box: the loop's names,
    and the fields of the values it binds (`person['name']`), as a table's
    box suggests columns. Nothing before a name is started, and nothing it
    already is."""
    if not (model.get('adding_column') or model.get('editing_column') is not None):
        return []
    typed = _TYPED_NAME_RE.search(model.get('column_input', ''))
    if typed is None:
        return []
    names = list(value.targets) + sorted(value.defined - set(value.targets))
    for col, column in enumerate(value.columns):
        if column.span is None and column.subject:
            names += [field.replace('$', column.subject, 1)
                      for field in _subcol_candidates(value, col, get_visualizer) if field.startswith('$')]
    prefix = typed.group(0)
    return [name for name in dict.fromkeys(names) if name.startswith(prefix) and name != prefix][:10]


def _finished(model, text: str) -> str:
    """The line box with the name at its end finished as `text`."""
    typed = model.get('column_input', '')
    found = _TYPED_NAME_RE.search(typed)
    return (typed[:found.start()] if found else typed) + text


def _condition(value: ForLoopTable, model) -> Optional[str]:
    """The search, as the condition loop code would test: the footer's, and
    each column's in turn, composed as it says. '' when nothing is searched for;
    None when it can't be written -- a search that isn't Python, or one on a
    column with no name to compare."""
    parts = []
    search = (model.get('search') or '').strip()
    if search:
        if not _is_value(search):
            return None
        parts.append(('and', search))
    for col, column_search in _active_searches(value, model):
        subject = value.columns[col].subject
        if not subject:
            return None
        text, op = column_search['text'].strip(), column_search['op']
        code = f'{subject} {op} ({text})' if op else text.replace('$', subject)
        if not _is_value(code):
            return None
        parts.append((column_search['compose'], code))
    if len(parts) == 1:
        return parts[0][1]
    condition = ''
    for compose, code in parts:
        condition = f'({code})' if not condition else f'{condition} {compose} ({code})'
    return condition


def _items(value: ForLoopTable, subjects: Optional[List[str]] = None) -> str:
    """What one iteration hands over: the names given, or those the loop binds
    -- a tuple of several."""
    names = subjects or list(value.targets) or [c.subject for c in value.columns if c.subject][:1]
    return names[0] if len(names) == 1 else f'({", ".join(names)})'


def _guarded(value: ForLoopTable, condition: str, step: str, negate: bool = False) -> str:
    """`step` at the end of the body, under the condition when there is one."""
    indent = value.body_indent
    if not condition:
        return f'{indent}{step}'
    test = f'not ({condition})' if negate else condition
    return f'{indent}if {test}:\n{indent}    {step}'


def _action_code(value: ForLoopTable, model, action: str) -> List[Any]:
    """What a footer button writes: a name above the loop and a line at the
    end of its body that builds it up over the iterations the search holds for
    -- or, for Filter, a line at the top skipping the rest."""
    condition = _condition(value, model)
    if condition is None or (not condition and action in ('filter', 'any', 'all')):
        return []
    picked = [c.subject for c in value.columns if c.label in (model.get('picked') or []) and c.subject]
    item = _items(value, picked if model.get('tool') == 'pick' else None)
    end = _body_end(value)
    above = value.line - 1
    if action == 'filter':
        return [InsertLines(((value.body_lines[0] - 1, _guarded(value, condition, 'continue', negate=True)),))]
    if action == 'count':
        name = _unique_name(value, 'n_matching' if condition else 'n_iterations')
        return [InsertLines(((above, f'{value.indent}{name} = 0'), (end, _guarded(value, condition, f'{name} += 1'))))]
    if action == 'extract' and model.get('first_match') and condition:
        name = _unique_name(value, 'first_matching')
        return [InsertLines(((above, f'{value.indent}{name} = None'),
                             (end, _guarded(value, f'{name} is None and {condition}', f'{name} = {item}'))))]
    if action == 'extract':
        name = _unique_name(value, 'matching')
        return [InsertLines(((above, f'{value.indent}{name} = []'),
                             (end, _guarded(value, condition, f'{name}.append({item})'))))]
    if action == 'any':
        name = _unique_name(value, 'any_matching')
        return [InsertLines(((above, f'{value.indent}{name} = False'),
                             (end, _guarded(value, condition, f'{name} = True'))))]
    if action == 'all':
        name = _unique_name(value, 'all_matching')
        return [InsertLines(((above, f'{value.indent}{name} = True'),
                             (end, _guarded(value, condition, f'{name} = False', negate=True))))]
    return []


def _row_literals(value: ForLoopTable, i: int, bound_only: bool) -> List[Tuple[str, str]]:
    """(name, literal) of each name iteration `i` held that can be written as
    Python: the names the loop binds, or every name it has."""
    row = value.values[i] if i < len(value.values) else ()
    out = []
    for column, cell in zip(value.columns, row):
        if not column.subject or cell is NO_VALUE or (bound_only and column.span is not None):
            continue
        literal = _tally_literal(cell)
        if literal is not None and column.subject not in dict(out):
            out.append((column.subject, literal))
    return out


def _row_condition(value: ForLoopTable, i: int) -> Optional[str]:
    literals = _row_literals(value, i, bound_only=True)
    if not literals or len(literals) < len([c for c in value.columns if c.span is None and c.subject]):
        return None
    return ' and '.join(f'{name} == {literal}' for name, literal in literals)


def _row_action_code(value: ForLoopTable, i: int, action: str) -> List[Any]:
    if action in ('skip', 'stop'):
        condition = _row_condition(value, i)
        if condition is None:
            return []
        step = 'continue' if action == 'skip' else 'break'
        return [InsertLines(((value.body_lines[0] - 1, f'{value.body_indent}if {condition}: {step}'),))]
    if action == 'extract':
        literals = _row_literals(value, i, bound_only=False)
        if not literals:
            return []
        name = _unique_name(value, f'row_{i}')
        cells = ', '.join(f'{n!r}: {literal}' for n, literal in literals)
        return [InsertLines(((value.end_line, f'{value.indent}{name} = {{{cells}}}'),))]
    return []


def _render_row_menu(value: ForLoopTable, model, i: int) -> str:
    """Iteration `i`'s ▾ and its menu, as a table row's."""
    is_open = model.get('row_menu') == i
    panel = ''
    if is_open:
        condition = _row_condition(value, i)
        options = [(f'Skip Iterations Where {condition}' if condition else 'Skip Iterations Like This',
                    'skip', condition is not None),
                   (f'Stop at the First Where {condition}' if condition else 'Stop at the First Like This',
                    'stop', condition is not None),
                   ('Extract Row Cells', 'extract', bool(_row_literals(value, i, bound_only=False)))]
        rows = ''.join(_render_option(model, text, RowActionClick(row=i, action=action) if enabled else None)
                       for text, action, enabled in options)
        panel = (f'<div class="snc-dropdown-panel flyout row-menu-panel" snc-dropdown-align="flyout" '
                 f'snc-dismiss="{html.escape(repr(ColumnMenuDismiss()))}">{rows}</div><!--/row-menu-->')
    open_class = ' open' if is_open else ''
    return (f'<span class="snc-dropdown-trigger row-menu-trigger{open_class}"><span class="row-menu{open_class}" '
            f'data-tooltip="Row actions"{_press(RowMenuToggle(row=i))}>▾</span>{panel}</span>')


def _render_pick_region(model, label: str, position: int, n_drawn: int) -> str:
    """One cell's piece of a picked column's outline, as a table draws its
    regions: the ends round off the stack, the middles only draw its sides."""
    edge = ('pick-region-only' if n_drawn == 1 else 'pick-region-first' if position == 0
            else 'pick-region-last' if position == n_drawn - 1 else 'pick-region-mid')
    selected = ' selected' if label in (model.get('picked') or []) else ''
    return (f'<span class="pick-region pick-band-all {edge}{selected}" data-pick-region="{html.escape(label)}" '
            f'snc-mouse-down="{html.escape(repr(PickToggle(label=label)))}"></span>')


def _press(event) -> str:
    """What a row of a menu sends when pressed, focused or not."""
    return f' snc-unfocused-clickable draggable="false" snc-mouse-down="{html.escape(repr(event))}"'


def _dwell(model, opens: Optional[str] = None, owns=()) -> str:
    """What resting on a row of the column menu does, as a table's: a row with
    a submenu opens it, the rest put away the one open -- unless it is one of
    the chips the row `owns`. Only where that would change something -- every
    event costs a run."""
    if model.get('submenu') == opens or (opens is None and model.get('submenu') in owns):
        return ''
    return f' snc-dwell="{html.escape(repr(SubmenuDwell(submenu=opens)))}"'


def _render_option(model, text: str, event, tooltip: str = '') -> str:
    """A plain row of the column menu: inert without an event."""
    tip = f' data-tooltip="{html.escape(tooltip)}"' if tooltip else ''
    if event is None:
        return (f'<div class="snc-dropdown-option unselectable"{_dwell(model)}{tip}>'
                f'<span class="snc-dropdown-option-label">{html.escape(text)}</span></div>')
    return (f'<div class="snc-dropdown-option"{_dwell(model)}{tip}>'
            f'<span class="snc-dropdown-option-label"{_press(event)}>{html.escape(text)}</span></div>')


def _render_submenu_row(model, submenu: str, text: str, tooltip: str, panel) -> str:
    """A row of the column menu that opens a submenu flying out of it."""
    is_open = model.get('submenu') == submenu
    return (f'<div class="snc-dropdown-trigger col-compute col-{submenu}"{_dwell(model, submenu)}>'
            f'<div class="snc-dropdown-option col-compute-trigger{" open" if is_open else ""}" '
            f'data-tooltip="{html.escape(tooltip)}"{_press(SubmenuToggle(submenu=submenu))}>'
            f'<span class="snc-dropdown-option-label col-compute-title">{html.escape(text)}</span>'
            f'<span class="submenu-right-arrow">▸</span></div>'
            f'{panel() if is_open else ""}</div>')


def _render_column_menu(value: ForLoopTable, model, col: int, get_visualizer=None) -> str:
    """What can be done to a whole column, in a table's order: Remove and
    Insert, then the rows that ask about its values."""
    column = value.columns[col]
    label = column.label
    statement = column.span is not None
    rows = [
        _render_search_row(model, label),
        _render_option(model, 'Remove', DeleteColumnClick(col=col, label=label) if statement else None,
                       '' if statement else 'A name the loop binds has no line to remove'),
        _render_option(model, 'Insert Left', InsertColumnClick(col=col, label=label, after=False)
                       if statement else None),
        _render_option(model, 'Insert Right', InsertColumnClick(col=col, label=label, after=True)),
        '<div class="col-compute-sep"></div>',
        _render_submenu_row(model, 'subcols', 'Subcolumns', 'Spread this column across several',
                            lambda: _render_subcol_panel(value, model, col, get_visualizer)),
        _render_submenu_row(model, 'sort', 'Sort', 'Draw the iterations in this column\'s order',
                            lambda: _render_sort_panel(model, label)),
        _render_option(model, 'Group By', GroupByClick(col=col, label=label) if column.subject else None,
                       f'Every iteration, grouped by {column.subject}' if column.subject else ''),
        _render_submenu_row(model, 'convert', 'Change Type', "Read this column's values as another type",
                            lambda: _render_convert_panel(value, col)),
        _render_submenu_row(model, 'compute', 'Compute', 'Summarize this column',
                            lambda: _render_compute_panel(value, model, col)),
        _render_option(model, 'Collect into List', CollectClick(col=col, label=label)
                       if _collectable(value, col, label) is not None else None,
                       f'A list of every {column.subject}, built as the loop runs' if column.subject else ''),
        '<div class="col-compute-sep"></div>',
        _render_tally(value, model, col),
    ]
    return (f'<div class="snc-dropdown-panel flyout col-menu-panel" snc-dropdown-align="flyout" '
            f'snc-dismiss="{html.escape(repr(ColumnMenuDismiss()))}">{"".join(rows)}</div><!--/col-menu-->')


def _render_chip(model, chip: str, current: str, options, make_event, chip_class: str, tooltip: str = '',
                 label=_column_search_value_label) -> str:
    """One of the small drop-downs in a column's menu -- the search row's two,
    and the tally's -- held open by the submenu slot, as a table's are."""
    is_open = model.get('submenu') == chip
    panel = ''
    if is_open:
        rows = ''.join(f'<div class="snc-dropdown-option{" selected" if option == current else ""}"'
                       f'{_press(make_event(option))}>{label(option)}</div>' for option in options)
        panel = f'<div class="snc-dropdown-panel flyout col-search-chip-panel" snc-dropdown-align="flyout">{rows}</div>'
    tip = f' data-tooltip="{html.escape(tooltip)}"' if tooltip else ''
    return (f'<span class="snc-dropdown-trigger"><span class="col-search-chip {chip_class}{" open" if is_open else ""}"'
            f'{tip}{_press(SubmenuToggle(submenu=chip))}>{label(current)}'
            f'<span class="col-search-chip-arrow">▾</span></span>{panel}</span>')


def _render_search_row(model, label: str) -> str:
    """A column's search, atop its menu as a table's is: what its value is
    compared against, the comparison, and how it goes with the searches
    before it. Escape in it walks out of the menu a level at a time."""
    search = _column_search(model, label)
    op = _render_chip(model, 'op', search['op'], COLUMN_SEARCH_OPS,
                      lambda v: ColumnSearchOpSelect(label=label, op=v), 'col-search-op', 'Search Operation')
    compose = _render_chip(model, 'compose', search['compose'], COLUMN_SEARCH_COMPOSE,
                           lambda v: ColumnSearchComposeSelect(label=label, compose=v), 'col-search-compose',
                           "How this composes with the other searches")
    input_event = f"lambda e: ColumnSearchInput(label={label!r}, value=e.get('value', ''))"
    return (f'<div class="col-search-area"{_dwell(model, owns=SEARCH_CHIPS)}><div class="search-box-wrapper">'
            f'<input type="text" class="col-search-input search-box" snc-unfocused-clickable spellcheck="false" '
            f'snc-input="{html.escape(input_event)}" snc-key-down="{html.escape(repr(ColumnKeyDown()))}" '
            f'value="{html.escape(search["text"])}" placeholder="Search" '
            f'data-tooltip="$ is this column\'s value" />'
            f'<span class="col-search-chips-right">{op}{compose}</span></div></div>')


def _render_subcol_panel(value: ForLoopTable, model, col: int, get_visualizer=None) -> str:
    """Show all and Hide all, a box per field the column's values have, then
    the sub-columns of the user's own and a box to write another."""
    label = value.columns[col].label
    subs = (model.get('subcols') or {}).get(label) or []
    candidates = _subcol_candidates(value, col, get_visualizer)

    def row(text: str, event, checked: Optional[bool]) -> str:
        check = '<span class="col-compute-nocheck"></span>' if checked is None else _check(checked)
        return (f'<div class="col-compute-row col-subcol-row{" checked" if checked else ""}">'
                f'<span class="col-compute-toggle"{_press(event)}>{check}'
                f'<span class="col-compute-name">{html.escape(text)}</span></span></div>')

    rows = [row('Show all', SubcolShowAll(label=label), None), row('Hide all', SubcolHideAll(label=label), None)]
    if candidates:
        rows.append('<div class="col-compute-sep"></div>')
        rows += [row(expr, SubcolToggle(label=label, expr=expr), expr in subs) for expr in candidates]
    rows.append('<div class="col-compute-sep"></div>')
    rows += [row(expr, SubcolToggle(label=label, expr=expr), True) for expr in subs if expr not in candidates]
    free = model.get('subcol_free') or {}
    text = free.get('text', '') if free.get('label') == label else ''
    input_event = f"lambda e: SubcolExprInput(label={label!r}, value=e.get('value', ''))"
    rows.append(f'<div class="col-compute-row col-subcol-row col-subcol-free">'
                f'<input type="text" class="col-compute-expr search-box" snc-unfocused-clickable spellcheck="false" '
                f'snc-input="{html.escape(input_event)}" snc-key-down="{html.escape(repr(ColumnKeyDown()))}" '
                f'value="{html.escape(text)}" placeholder="Subcolumn" '
                f'data-tooltip="$ is this column\'s value" /></div>')
    return _submenu('subcol', rows)


def _render_sort_panel(model, label: str) -> str:
    """Ascending and Descending, ticked while the iterations are drawn so."""
    sort = model.get('sort') or {}
    rows = []
    for direction, name in SORT_DIRECTIONS:
        checked = sort.get('label') == label and sort.get('direction') == direction
        rows.append(f'<div class="col-compute-row col-sort-row{" checked" if checked else ""}">'
                    f'<span class="col-compute-toggle"{_press(SortToggle(label=label, direction=direction))}>'
                    f'{_check(checked)}<span class="col-compute-name">{name}</span></span></div>')
    return _submenu('sort', rows)


def _render_tally(value: ForLoopTable, model, col: int) -> str:
    """Each value the column took and how many iterations took it, as a
    table's tally: ticked to search for them, narrowed by what they read as
    or how often they occur, and listed in the order picked."""
    label = value.columns[col].label
    values = _column_values(value, col)
    tally = _tally(values) if values is not None else None
    dwell = _dwell(model, owns=TALLY_CHIPS)
    if tally is None:
        return ''
    if not isinstance(tally, dict):
        return f'<div class="col-tally"{dwell}><div class="col-tally-note">{_TALLY_NOTES[tally]}</div></div>'
    selected, exclude = _tally_selection(_column_search(model, label))
    rows = _tally_rows(tally, model)
    extreme = _tally_extreme(model, rows)
    items = []
    for text, count, literal in rows:
        if not _tally_lists(model, text, count, extreme):
            continue
        shown = html.escape(text if len(text) <= 60 else text[:59] + '…')
        if literal is None:
            items.append(f'<div class="col-tally-row unselectable">{_check(False, disabled=True)}'
                         f'<span class="col-tally-item snc-code">{shown}</span>'
                         f'<span class="col-tally-count">{count}</span></div>')
            continue
        checked = literal in selected
        items.append(f'<div class="col-tally-row{" checked" if checked else ""}"'
                     f'{_press(TallyItemToggle(label=label, literal=literal))}>{_check(checked)}'
                     f'<span class="col-tally-item snc-code">{shown}</span>'
                     f'<span class="col-tally-count">{count}</span></div>')
    filter_event = f"lambda e: TallyFilterInput(label={label!r}, value=e.get('value', ''))"
    count_event = f"lambda e: TallyCountFilterInput(label={label!r}, value=e.get('value', ''))"
    count_op = _tally_count_op(model)
    extreme_op = count_op in TALLY_COUNT_EXTREME_OPS
    count_box = (f'<div class="search-box-wrapper col-tally-count-box">'
                 f'<input type="text" class="col-tally-count-filter search-box" snc-unfocused-clickable '
                 f'snc-input="{html.escape(count_event)}" '
                 f'value="{"" if extreme_op else html.escape(model.get("tally_count_filter") or "")}" '
                 f'placeholder="{"" if extreme_op else "N"}" spellcheck="false"{" disabled" if extreme_op else ""} />'
                 f'<span class="col-search-chips">'
                 + _render_chip(model, 'tally-count-op', count_op, TALLY_COUNT_OPS,
                                lambda v: TallyCountOpSelect(label=label, op=v), 'col-tally-count-op',
                                label=_tally_count_op_label)
                 + '</span></div>')
    sort = _render_chip(model, 'tally-sort', _tally_sort(model), TALLY_SORTS, lambda v: TallySortSelect(sort=v),
                        'col-tally-sort', 'Order the values are listed in', _tally_sort_label)
    controls = (f'<div class="col-tally-controls">'
                f'<span class="col-search-chip" data-tooltip="Select every value shown"'
                f'{_press(TallySelectAll(label=label))}>All</span>'
                f'<span class="col-search-chip" data-tooltip="Select none of the values shown"'
                f'{_press(TallySelectNone(label=label))}>None</span>'
                f'<span class="col-tally-exclude{" checked" if exclude else ""}" '
                f'data-tooltip="Search for everything but the selected values"'
                f'{_press(TallyExcludeToggle(label=label))}>Exclude</span>'
                f'<div class="col-tally-sort-box"><div class="col-tally-sort-icon">{ICONS["sort"]}</div>{sort}</div>'
                f'</div>')
    body = (f'<div class="col-tally-list-header"><span class="col-tally-item-header">Tally</span>'
            f'<span class="col-tally-count-header">Counts {count_box}</span></div>')
    body += (f'<div class="col-tally-list">{"".join(items)}</div>' if items
             else '<div class="col-tally-note">No values match</div>')
    filter_box = (f'<div class="col-tally-filter-wrapper"><input type="text" class="col-tally-filter search-box" '
                  f'snc-unfocused-clickable snc-input="{html.escape(filter_event)}" '
                  f'value="{html.escape(model.get("tally_filter") or "")}" placeholder="Search tally" '
                  f'data-tooltip="Show only values containing this text" spellcheck="false" /></div>')
    return f'<div class="col-tally"{dwell}>{filter_box}{controls}{body}</div>'


def _render_action_buttons(value: ForLoopTable, model, count: int) -> str:
    """The footer's buttons, as a table's: each writes what it names about the
    iterations the search holds for. Those that need a search to say anything
    are dimmed without one, and all of them while it isn't Python."""
    condition = _condition(value, model)
    buttons = []
    for action, label, title, needs_search in (
            ('count', f'Count: {count}', 'Count of matches', False),
            ('extract', 'Extract', 'Every matching iteration\'s names', False),
            ('filter', 'Filter', 'Skip the iterations that don\'t match', True),
            ('any', 'Any', 'Whether any iteration matches', True),
            ('all', 'All', 'Whether every iteration matches', True)):
        enabled = condition is not None and (bool(condition) or not needs_search)
        press = _press(ActionButtonClick(action=action)) if enabled else ''
        buttons.append(f'<span class="action-button{"" if enabled else " dimmed"}" title="{html.escape(title)}"'
                       f'{press}><span class="text">{html.escape(label)}</span></span>')
    return ''.join(buttons)


def _render_footer(value: ForLoopTable, model, matches: Optional[List[int]], n_rows: int, hidden_rows: int) -> str:
    """A focused table's footer, as a table's: the search box and its 1st,
    how many iterations matched, and a tab counting every one the loop ran."""
    input_event = "lambda e: SearchBoxInput(value=e.get('value', ''))"
    first = bool(model.get('first_match'))
    names = ', '.join(column.subject for column in value.columns if column.subject)
    count = n_rows if matches is None else len(matches)
    ran = n_rows + hidden_rows
    return (f'<div class="search-div toolbar-anchor">'
            f'<div class="search-div-row"><div class="search-replace-container"><div class="search-box-wrapper">'
            f'<input type="text" tabindex="0" snc-input="{html.escape(input_event)}" '
            f'value="{html.escape(model.get("search") or "")}" placeholder="Search" '
            f'data-tooltip="{html.escape(f"A condition over {names}" if names else "A condition")}" '
            f'spellcheck="false" class="search-box" />'
            f'<span class="search-toggles-container">'
            f'<span class="search-button {"active" if first else "inactive"}" data-tooltip="First match only"'
            f'{_press(FirstMatchToggle())}>{ICONS["match-first"]}</span></span>'
            f'</div></div></div>'
            f'<div class="search-div-row"><div class="action-buttons">{_render_action_buttons(value, model, count)}'
            f'</div></div>'
            f'<div class="auxiliary-attributes"><div class="tiny-len">{ran} iteration{"" if ran == 1 else "s"}</div>'
            f'</div></div>')


def _check(checked: bool, disabled: bool = False) -> str:
    """A menu row's box, which only reports `checked`: the click is the row's."""
    return (f'<input type="checkbox" class="col-tally-check"{" checked" if checked else ""}'
            f'{" disabled" if disabled else ""} />')


def _submenu(kind: str, rows: List[str]) -> str:
    return (f'<div class="snc-dropdown-panel flyout col-compute-panel col-{kind}-panel" '
            f'snc-dropdown-align="flyout">{"".join(rows)}</div><!--/submenu-->')


def _render_convert_panel(value: ForLoopTable, col: int) -> str:
    """A box per type, ticked while the column's assignment reads its value as
    that type, and beside each a button writing a line that reads it so."""
    column = value.columns[col]
    assignment = _plain_assignment(column.label) if column.span is not None else None
    current = _converted(assignment[1])[0] if assignment else None
    rows = []
    for to in CONVERT_TYPES:
        checked = current == to
        toggle = '' if assignment is None else _press(ConvertToggle(col=col, label=column.label, to=to))
        row = (f'<div class="col-compute-row col-convert-row{" checked" if checked else ""}'
               f'{"" if assignment else " unselectable"}">'
               f'<span class="col-compute-toggle"{toggle}>{_check(checked, disabled=assignment is None)}'
               f'<span class="col-compute-name">{to}</span></span></div>')
        aside_press = '' if not column.subject else _press(ConvertColumnClick(col=col, label=column.label, to=to))
        aside = (f'<div class="col-compute-row col-convert-row col-compute-row-aside'
                 f'{"" if column.subject else " unselectable"}">'
                 f'<span class="col-compute-toggle"{aside_press} data-tooltip="Insert as a new column">'
                 f'{ICONS["column-right"]}</span></div>')
        rows.append(f'<div class="col-convert-wrapper">{row}{aside}</div>')
    return _submenu('convert', rows)


# The Compute rows that also write what builds their answer up as the loop runs.
COMPUTE_CODE_KINDS = {'sum($)': 'sum', 'min($)': 'min', 'max($)': 'max'}
COMPUTE_CODE_ROWS = (('Unique', 'unique'), ('Tally', 'tally'))


def _column_values(value: ForLoopTable, col: int) -> Optional[list]:
    """Every value column `col` had, in order, skipping the iterations that
    never got to it; None while the loop runs and there are none yet."""
    if not value.values:
        return None
    return [row[col] for row in value.values if col < len(row) and row[col] is not NO_VALUE]


def _answer(template: str, values: Optional[list]):
    return NO_THING if values is None else _agg_value(template, values)


def _compute_label(template: str) -> str:
    return next((name for name, t in COMPUTE_AGGS if t == template), template)


def _render_compute_panel(value: ForLoopTable, model, col: int) -> str:
    """The table's catalog of answers, each previewed from the column's values
    and ticked to keep it under the table; the rows that write what builds an
    answer up as the loop runs; and the answers of the user's own, with a box
    at the foot to write another."""
    column = value.columns[col]
    label = column.label
    values = _column_values(value, col)
    kept = (model.get('computes') or {}).get(label, [])
    catalog = {t for _, t in COMPUTE_AGGS}

    def answer_row(name: str, template: str, classes: str = '') -> str:
        answer = _answer(template, values)
        checked = template in kept
        inert = answer is NO_THING and not checked
        press = '' if inert else _press(ComputeToggle(label=label, template=template))
        preview = '' if answer is NO_THING else _agg_answer_html(template, answer)
        return (f'<div class="col-compute-row{classes}{" checked" if checked else ""}{" unselectable" if inert else ""}">'
                f'<span class="col-compute-toggle"{press}>{_check(checked, disabled=inert)}'
                f'<span class="col-compute-name">{html.escape(name)}</span>'
                f'<span class="col-compute-preview">{preview}</span></span></div>')

    def code_button(kind: str, inner: str, tooltip: str, aside: bool) -> str:
        press = '' if not column.subject else _press(ComputeCodeClick(col=col, label=label, kind=kind))
        classes = ' col-compute-row-aside' if aside else ' col-compute-code'
        return (f'<div class="col-compute-row{classes}{"" if column.subject else " unselectable"}">'
                f'<span class="col-compute-toggle"{press} data-tooltip="{html.escape(tooltip)}">{inner}</span></div>')

    rows = []
    for name, template in COMPUTE_AGGS:
        row = answer_row(name, template)
        if template in COMPUTE_CODE_KINDS:
            row = (f'<div class="col-convert-wrapper">{row}'
                   f'{code_button(COMPUTE_CODE_KINDS[template], ICONS["plus"], "Insert as new code", True)}</div>')
        rows.append(row)
    rows.append('<div class="col-compute-sep"></div>')
    rows += [code_button(kind, f'<span class="col-compute-nocheck"></span><span class="col-compute-name">{name}</span>',
                         f'Write what builds this up as the loop runs', False)
             for name, kind in COMPUTE_CODE_ROWS]
    rows.append('<div class="col-compute-sep"></div>')
    rows += [answer_row(template, template, ' col-compute-free') for template in kept if template not in catalog]
    free = (model.get('compute_free') or {})
    text = free.get('text', '') if free.get('label') == label else ''
    input_event = f"lambda e: ComputeFreeInput(label={label!r}, value=e.get('value', ''))"
    rows.append(f'<div class="col-compute-row col-compute-free">'
                f'<input type="text" class="col-compute-expr search-box" snc-unfocused-clickable spellcheck="false" '
                f'snc-input="{html.escape(input_event)}" snc-key-down="{html.escape(repr(ColumnKeyDown()))}" '
                f'value="{html.escape(text)}" placeholder="Expr" '
                f'data-tooltip="$ is every value of this column" /></div>')
    return _submenu('compute', rows)


def _render_agg_rows(value: ForLoopTable, model, shown: List[int], spans=None) -> str:
    """The answers kept under the table, a row per level, as a table's: each
    column's answers stacked in the order they were ticked."""
    computes = model.get('computes') or {}
    asked = [computes.get(value.columns[col].label) or [] for col in shown]
    levels = max((len(templates) for templates in asked), default=0)
    if not levels:
        return ''
    rows = []
    for level in range(levels):
        cells = []
        for col, templates in zip(shown, asked):
            span = f' colspan="{spans[col]}"' if spans and spans.get(col, 1) > 1 else ''
            if level >= len(templates):
                cells.append(f'<td class="col-agg-blank"{span}></td>')
                continue
            template = templates[level]
            answer = _answer(template, _column_values(value, col))
            text = '' if answer is NO_THING else _agg_answer_html(template, answer)
            cells.append(f'<td class="col-agg-cell"{span}{_col_attrs(model, value.columns[col].label)}>'
                         f'<div class="col-agg"><span class="col-agg-label">{html.escape(_compute_label(template))}'
                         f'</span><div class="col-agg-value">{text}</div></div></td>')
        rows.append(f'<tr class="col-agg-row"><td class="row-index col-agg-blank"></td>{"".join(cells)}</tr>')
    return f'<tfoot class="col-agg-rows">{"".join(rows)}</tfoot>'


def _plain_assignment(label: str) -> Optional[Tuple[str, str]]:
    """(name, right-hand side) of `name = value`, or None for any other
    statement: the only kind whose value can be read as another type in place."""
    try:
        tree = ast.parse(label)
    except SyntaxError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        return None
    stmt = tree.body[0]
    if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
        return None
    return stmt.targets[0].id, ast.get_source_segment(label, stmt.value)


def _converted(rhs: str) -> Tuple[Optional[str], str]:
    """(type, what it converts) when `rhs` is a conversion to one of the
    types, else (None, rhs)."""
    try:
        node = ast.parse(rhs, mode='eval').body
    except SyntaxError:
        return None, rhs
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CONVERT_TYPES
            and len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred)):
        return node.func.id, ast.get_source_segment(rhs, node.args[0])
    return None, rhs


def _unique_name(value: ForLoopTable, base: str) -> str:
    """`base`, or `base2`, ... -- whichever nothing in the loop's scope has."""
    name, n = base, 2
    while name in value.defined:
        name, n = f'{base}{n}', n + 1
    return name


def _beside(value: ForLoopTable, column: ForLoopColumn, after: bool) -> int:
    """The line a new statement goes after to be drawn beside `column`: a
    bound name's right is the top of the body."""
    if column.span is None:
        return value.body_lines[0] - 1
    return column.span[1] if after else column.span[0] - 1


def _body_end(value: ForLoopTable) -> int:
    return value.body_lines[1] or value.end_line


def _valid_width(width) -> Optional[int]:
    """A dragged width in whole pixels, or None when it is not one (a bool is
    an int, so it is refused by name)."""
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
        return None
    return round(width)


def _width_style(model, label: str, clip: bool = True) -> str:
    """The style pinning a column to the width it was dragged to, as a table's
    does: a body cell clips to it, a header cell can't, since its resize
    handle hangs past its edge (.col-header-inner clips instead)."""
    width = _valid_width((model.get('widths') or {}).get(label))
    if width is None:
        return ''
    overflow = ' overflow: hidden;' if clip else ''
    return f' style="min-width: {width}px; max-width: {width}px;{overflow}"'


def _col_attrs(model, label: str, clip: bool = True) -> str:
    """What ties a cell to its column for the editor: which cells a resize
    drags along with the header, and the width it was left at."""
    return f' data-col="{html.escape(repr(label))}"{_width_style(model, label, clip)}'


def _render_header(value: ForLoopTable, model, col: int, live_only: bool, span_attrs: str = '',
                   get_visualizer=None) -> str:
    """A column's header, marked up as a table's: its label, then the ▾ and
    the x, then the handle on its right edge that drags it wider."""
    column = value.columns[col]
    label = column.label
    if not live_only and column.span is not None and model.get('editing_column') == col:
        return _render_box(model, select_all=True, tooltip='Written over this line of the loop',
                           span_attrs=span_attrs)
    resize = (f'<span snc-resize-col="{html.escape(repr(ColumnResize(width=0, label=label)))}" '
              f'data-tooltip="Resize" class="col-handle col-resize-handle col-resize-right"></span>')
    if live_only:
        inner = _render_label(column)
    elif column.span is None:
        inner = (f'<span class="col-name"{py_exp_attrs(column.subject)}>{_render_label(column)}</span>'
                 f'{_render_menu_trigger(value, model, col, get_visualizer)}')
    else:
        edit = repr(ColumnClick(col=col, label=label))
        inner = (f'<span class="col-name for-loop-col-label" snc-unfocused-clickable '
                 f'snc-mouse-down="{html.escape(edit)}" data-tooltip="Double-click to edit"'
                 f'{py_exp_attrs(column.subject) or ' draggable="false"'}>'
                 f'{_render_label(column)}</span>'
                 f'{_render_menu_trigger(value, model, col, get_visualizer)}')
    filtered = ' col-filtered' if _column_search(model, label)['text'].strip() else ''
    return (f'<th class="snc-hover-hidden-parent col-header for-loop-col{filtered}"{span_attrs}'
            f'{_col_attrs(model, label, clip=False)}><span class="col-header-inner">{inner}{resize}</span></th>')


def _render_subheader(model, label: str, sub: str) -> str:
    """The header of a sub-column, in the header row under its column's."""
    leaf = _leaf_label(label, sub)
    resize = (f'<span snc-resize-col="{html.escape(repr(ColumnResize(width=0, label=leaf)))}" '
              f'data-tooltip="Resize" class="col-handle col-resize-handle col-resize-right"></span>')
    return (f'<th class="col-header col-subheader"{_col_attrs(model, leaf, clip=False)}>'
            f'<span class="col-header-inner"><span class="col-name">{html.escape(sub)}</span>{resize}</span></th>')


def _render_menu_trigger(value: ForLoopTable, model, col: int, get_visualizer=None) -> str:
    """The ▾ at a header's right end, and the menu it opens, as a table's: lit
    while open, since the panel is lifted out of the header and the pointer
    leaves it to reach it."""
    label = value.columns[col].label
    menu_open = model.get('col_menu') == label
    classes = 'col-menu snc-hover-hidden full-opacity-on-hover' + (' open' if menu_open else '')
    return (f'<span class="snc-dropdown-trigger col-menu-trigger">'
            f'<span snc-mouse-down="{html.escape(repr(ColumnMenuToggle(label=label)))}" snc-unfocused-clickable '
            f'draggable="false" data-tooltip="Column actions" class="{classes}">▾</span>'
            f'{_render_column_menu(value, model, col, get_visualizer) if menu_open else ""}</span>')


def _render_add_bar(value: ForLoopTable, model) -> str:
    """The (+), a bar down the table's right edge, and the menu it opens, as a
    table's are. The open menu pins the (+) lit, as a table's does: the panel
    is lifted out of the table, so the pointer leaves the bar to reach it."""
    menu_open = bool(model.get('add_menu_open'))
    icon_classes = 'col-add-icon full-opacity-on-hover' + (' open' if menu_open else '')
    return (f'<div class="snc-dropdown-trigger col-add-trigger">'
            f'<span class="{icon_classes}" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(repr(AddMenuToggle()))}" '
            f'data-tooltip="Add or hide columns">+</span>'
            f'{_render_add_menu(value, model) if menu_open else ""}</div>')


def _render_menu_row(text: str, event, checked: Optional[bool] = None, classes: str = '') -> str:
    """A row of the (+) menu, drawn as a table's: a box when it has one, which
    only reports `checked` -- the click is the row's."""
    check = ('<span class="col-compute-nocheck"></span>' if checked is None else
             f'<input type="checkbox" class="col-tally-check"{" checked" if checked else ""} />')
    return (f'<div class="col-compute-row col-add-row{classes}{" checked" if checked else ""}">'
            f'<span class="col-compute-toggle" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(repr(event))}">'
            f'{check}<span class="col-compute-name">{html.escape(text)}</span></span></div>')


def _render_add_menu(value: ForLoopTable, model) -> str:
    """Add Column, the names the loop binds, then Show all and Hide all over
    the lines of the body: the pair acts on the section below it, as a
    table's acts on its fields. A box is ticked while its column is shown."""
    hidden = set(model.get('hidden_columns') or [])
    sep = '<div class="col-compute-sep"></div>'

    def check_row(column: ForLoopColumn) -> str:
        return _render_menu_row(column.label, ColumnToggle(label=column.label), column.label not in hidden)

    bound = [column for column in value.columns if column.span is None]
    statements = [column for column in value.columns if column.span is not None]
    rows = [_render_menu_row('Add Column', AddColumnClick(), classes=' col-add-write'), sep,
            *(check_row(column) for column in bound), sep,
            _render_menu_row('Show all', ColumnShowAll(), classes=' col-add-all'),
            _render_menu_row('Hide all', ColumnHideAll(), classes=' col-add-all')]
    if statements:
        rows += [sep, *(check_row(column) for column in statements)]
    return (f'<div class="snc-dropdown-panel left col-compute-panel col-add-panel" snc-dropdown-align="left" '
            f'snc-dismiss="{html.escape(repr(AddMenuDismiss()))}">{"".join(rows)}</div>')


def _render_cell(model, label: str, text) -> str:
    attrs = _col_attrs(model, label)
    if text is None:
        return f'<td class="list-table-cell"{attrs}>—</td>'
    return f'<td class="list-table-cell"{attrs}><span class="snc-code">{html.escape(text)}</span></td>'


def _render_leaf(value: ForLoopTable, model, i: int, col: int, sub: Optional[str], text, has_values: bool,
                 get_visualizer, eval_in_scope, small: bool) -> str:
    """One cell: its value drawn by the value's own visualizer, as a table's
    cells are -- small until a press focuses it -- or, with no visualizer to
    ask or no value kept, its repr."""
    label = value.columns[col].label
    leaf = _leaf_label(label, sub)
    if not has_values:
        return _render_cell(model, leaf, text if sub is None else None)
    try:
        cell = _cell_value(value, i, col, sub, eval_in_scope)
    except Exception as e:
        return f'<td class="list-table-cell"{_col_attrs(model, leaf)}>{error_html(e)}</td>'
    if cell is NO_VALUE:
        return _render_cell(model, leaf, None)
    if get_visualizer is None:
        return _render_cell(model, leaf, text if sub is None else truncate_repr(cell, 120))
    key = _cell_key(i, label, sub)
    try:
        vis = get_visualizer(cell)
        child_model = (model.get('children') or {}).get(key)
        if child_model is None:
            # Nested, as a table's cells are -- so a table in one draws as its
            # repr until pressed -- and with nowhere to save to: a loop's line
            # has no config of its own for a cell's to go in.
            nesting = child_nesting_kwargs({'_config_persist': False}, leaf, vis.init_model)
            child_model = call_with_supported_kwargs(vis.init_model, cell, get_visualizer,
                                                     eval_in_scope=eval_in_scope, **nesting)
            if model.get('focused_child') == key:
                # Kept, so the events it is about to be sent reach this one.
                model['children'] = {**(model.get('children') or {}), key: child_model}
        drawn = call_with_supported_kwargs(vis.visualize, cell, child_model, get_visualizer,
                                           eval_in_scope=eval_in_scope, max_width=CELL_MAX_WIDTH, max_height=200,
                                           small=small or model.get('focused_child') != key, var_and_exp=None)
    except Exception as e:
        return f'<td class="list-table-cell"{_col_attrs(model, leaf)}>{error_html(e)}</td>'
    return (f'<td class="list-table-cell"{_col_attrs(model, leaf)}>'
            f'{wrap_child_prefix(key)}{drawn}{wrap_child_suffix}</td>')


def _hidden_page(n_rows: int, model) -> Optional[Tuple[int, int]]:
    """The rows left out, as [start, stop), or None when every row is drawn:
    a page, then however many more were loaded, then the last few -- nothing
    held back when the gap would be empty."""
    stop = n_rows - TAIL_ROWS
    shown = model.get('shown_rows', ROWS_PER_PAGE)
    return (shown, stop) if stop > shown else None


def _render_load_more_row(n_hidden: int, colspan: int, small: bool) -> str:
    """The row standing in for the rows not drawn, as a table's: what a click
    does and how much is behind it. Unfocused it acts on the press."""
    next_n = min(ROWS_PER_PAGE, n_hidden)
    label = f'Load {next_n} more' + (f' ({n_hidden} hidden)' if n_hidden > next_n else '')
    preview_attrs = ' draggable="false" snc-unfocused-clickable' if small else ''
    return (f'<tr class="row-load-more"><td class="load-more" colspan="{colspan}"{preview_attrs} '
            f'snc-mouse-down="{html.escape(repr(LoadMoreRows()))}">{label}</td></tr>')


def _render_init_cell(value: ForLoopTable, model, col: int, live_only: bool, span_attrs: str = '') -> str:
    """Where column `col` starts: blank unless it is an accumulator."""
    column = value.columns[col]
    attrs = span_attrs + _col_attrs(model, column.label)
    if not column.accumulator or not column.subject:
        return f'<td class="list-table-cell"{attrs}></td>'
    if not live_only and model.get('editing_init') == col:
        return _render_box(model, tag='td', select_all=True, placeholder='Starting value',
                           tooltip=f'Sets {column.subject} before the loop')
    init = _init_of(value, col)
    if init is None:
        text = '' if live_only else '<span class="for-loop-init-unset">set…</span>'
    else:
        text = f'<span class="snc-code">{html.escape(init)}</span>'
    if live_only:
        return f'<td class="list-table-cell"{attrs}>{text}</td>'
    click = repr(InitCellClick(col=col, label=column.label))
    return (f'<td class="list-table-cell for-loop-init-cell"{attrs}>'
            f'<span snc-unfocused-clickable draggable="false" snc-mouse-down="{html.escape(click)}" '
            f'data-tooltip="Double-click to set where it starts">{text}</span></td>')


def _rows_to_draw(value: ForLoopTable, model) -> Tuple[Tuple[Tuple[Optional[str], ...], ...], int]:
    """The rows to draw, and how many iterations go without one: the table's
    own once the loop has finished, which are remembered; the ones remembered
    from last time while it is still running."""
    labels = [column.label for column in value.columns]
    if not value.running:
        model['last_rows'] = [dict(zip(labels, row)) for row in value.rows]
        model['last_hidden_rows'] = value.hidden_rows
        return value.rows, value.hidden_rows
    if value.rows:
        return value.rows, value.hidden_rows
    rows = tuple(tuple(row.get(label) for label in labels) for row in model.get('last_rows') or [])
    return rows, model.get('last_hidden_rows', 0)


def _open_pending_init(value: ForLoopTable, model) -> None:
    """Open the starting value box of a column just added with the (+), once
    it is back and turns out to be an accumulator with nothing to start from.
    The run the Enter came in on still draws the loop as it was, so only a
    finished table whose columns changed some other way gives up on it."""
    pending = model.get('pending_init')
    if not pending:
        return
    labels = [column.label for column in value.columns]
    if pending['label'] in labels:
        model.pop('pending_init')
        col = labels.index(pending['label'])
        if value.columns[col].accumulator and _init_of(value, col) is None and not _box_open(model):
            model.update(_opened(model, 'editing_init', col, ''))
    elif not value.running and labels != pending['labels']:
        model.pop('pending_init')


def visualize(value: ForLoopTable, model=None, get_visualizer=None, small=False, eval_in_scope=None):
    if model is None:
        model = {}
    live_only = is_live_only()
    rows, hidden_rows = _rows_to_draw(value, model)
    if not live_only:
        _open_pending_init(value, model)
    key_handler = '' if live_only else f' snc-key-down="{html.escape(repr(ColumnKeyDown()))}"'
    small_class = ' small' if small else ''
    max_height = SMALL_MAX_HEIGHT if small else EXPANDED_PANE_MAX_HEIGHT
    pick = model.get('tool') == 'pick' and not small and not live_only
    tool_class = '' if small else f' {"pick" if pick else "normal"}-tool-selected'
    strs = [f'<div class="visualizer-container list-visualizer for-loop-visualizer{small_class}{tool_class}"'
            f'{key_handler}>',
            '<div class="snc-tool-and-visualizer">']
    if not small and not live_only:
        strs.append(render_tool_toolbar(TOOLS, model.get('tool', 'normal'), lambda tool: repr(ToolSelect(tool=tool))))
    strs += [
            f'<div class="list-table-scroll snc-base-visualizer" style="max-height: {max_height}px;">',
            '<table><thead class="col-header-rows"><tr>']
    hidden = set(model.get('hidden_columns') or [])
    shown = [col for col, column in enumerate(value.columns) if column.label not in hidden]
    # A column spread into sub-columns spans them, and they get a header row
    # of their own, which everything else in the first reaches down past.
    subcols = _subcols(model, value, shown)
    tall = ' rowspan="2"' if subcols else ''
    spans = {col: len(subs) for col, subs in subcols.items()}
    leaves = [(col, sub) for col in shown for sub in (subcols.get(col) or [None])]
    strs.append(f'<th class="row-index-header"{tall} data-tooltip="itr is the iteration, counting from 0">itr</th>')
    # Insert Left / Right put the box beside its column; anywhere else, or
    # once that column is gone, it ends the row.
    insert_at = model.get('insert_at') if not live_only and model.get('adding_column') else None
    beside = next((col for col in shown if insert_at and value.columns[col].label == insert_at['label']), None)
    for col in shown:
        if col == beside and not insert_at['after']:
            strs.append(_render_box(model, span_attrs=tall, suggestions=_suggestions(value, model, get_visualizer)))
        span = f' colspan="{spans[col]}"' if spans.get(col, 1) > 1 else ('' if col in subcols else tall)
        strs.append(_render_header(value, model, col, live_only, span, get_visualizer))
        if col == beside and insert_at['after']:
            strs.append(_render_box(model, span_attrs=tall, suggestions=_suggestions(value, model, get_visualizer)))
    # Every column it adds is code, so live-only leaves it out.
    suggested = _suggestions(value, model, get_visualizer) if not live_only else []
    if not live_only and model.get('adding_column') and beside is None:
        strs.append(_render_box(model, span_attrs=tall, suggestions=suggested))
    collecting = model.get('collecting_column')
    if not live_only and collecting is not None and 0 <= collecting < len(value.columns):
        subject = value.columns[collecting].subject
        strs.append(_render_box(model, select_all=True, placeholder='List name',
                                tooltip=f'Every {subject}, collected into this list', span_attrs=tall))
    grouping = model.get('grouping_column')
    if not live_only and grouping is not None and 0 <= grouping < len(value.columns):
        subject = value.columns[grouping].subject
        strs.append(_render_box(model, select_all=True, placeholder='Dict name',
                                tooltip=f'Every iteration, grouped by {subject}', span_attrs=tall))
    strs.append('</tr>')
    if subcols:
        strs.append('<tr>')
        strs += [_render_subheader(model, value.columns[col].label, sub) for col, sub in leaves if sub is not None]
        strs.append('</tr>')
    strs.append('</thead><tbody>')
    if any(value.columns[col].accumulator and value.columns[col].subject for col in shown):
        strs.append('<tr class="for-loop-init-row"><td class="row-index">init</td>')
        strs += [_render_init_cell(value, model, col, live_only,
                                   f' colspan="{spans[col]}"' if spans.get(col, 1) > 1 else '') for col in shown]
        strs.append('</tr>')
    has_values = not value.running and len(value.values) == len(rows)
    gap = _hidden_page(len(rows), model)
    matches = None if small or live_only and not model.get('search') else _matches(value, model)
    marked = set(matches) if matches else set()
    order = _draw_order(value, model, len(rows))
    drawn = [p for p in range(len(order)) if gap is None or not gap[0] <= p < gap[1]]
    for position, i in enumerate(order):
        row = rows[i]
        if gap is not None and gap[0] <= position < gap[1]:
            if position == gap[0]:
                strs.append(_render_load_more_row(gap[1] - gap[0], len(leaves) + 1, small))
            continue
        row_class = '' if not marked else (' class="row-match"' if i in marked else ' class="row-dim"')
        if small or live_only:
            strs.append(f'<tr{row_class}><td class="row-index">{i}</td>')
        else:
            # The number and its ▾ in a wrapper inside the cell, as a table's.
            strs.append(f'<tr{row_class}><td class="row-index"><div class="row-index-inner">{i}'
                        f'{_render_row_menu(value, model, i)}</div></td>')
        for col, sub in leaves:
            cell = _render_leaf(value, model, i, col, sub, row[col] if col < len(row) else None, has_values,
                                get_visualizer, eval_in_scope, small)
            if pick and sub is None:
                overlay = _render_pick_region(model, value.columns[col].label, drawn.index(position), len(drawn))
                cell = cell[:-len('</td>')] + overlay + '</td>'
            strs.append(cell)
        strs.append('</tr>')
    strs.append('</tbody>')
    strs.append(_render_agg_rows(value, model, shown, spans))
    strs.append('</table></div>')
    if not live_only:
        strs.append(_render_add_bar(value, model))
    strs.append('</div>')
    if hidden_rows:
        noun = 'iteration' if hidden_rows == 1 else 'iterations'
        strs.append(f'<div class="for-loop-note">{hidden_rows} more {noun}</div>')
    if not small and not live_only:
        strs.append(_render_footer(value, model, matches, len(rows), hidden_rows))
    strs.append('</div>')
    # What the editor stops from reaching itself while a key is pressed in the
    # table: its own, and whatever its cells' visualizers answer.
    model['handledKeys'] = aggregate_handled_keys(model.get('children') or {}, OWN_KEYS)
    return ''.join(strs)


def update(event, var_and_exp, model, value: ForLoopTable, get_visualizer=None,
           eval_in_scope=None) -> Tuple[Any, List[Any]]:
    if not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])
    event_json = event.get('eventJSON') or {}
    try:
        make_event = eval(event['pythonEventStr'])
        msg = make_event(event_json) if callable(make_event) else make_event
    except Exception:
        return (model, [])
    model = dict(model or {})
    if isinstance(msg, ChildEvent):
        # A cell's own visualizer: the first press focuses it, as a table's.
        return route_child_event(event, model, value, lambda key: _child_value(value, key, eval_in_scope),
                                 get_visualizer, None, eval_in_scope)
    double_click = event_json.get('detail', 1) >= 2
    match msg:
        case LoadMoreRows():
            return ({**model, 'shown_rows': model.get('shown_rows', ROWS_PER_PAGE) + ROWS_PER_PAGE}, [])
        case ColumnResize(width=width, label=label):
            width = _valid_width(width)
            if width is not None and label in (column.label for column in value.columns):
                return ({**model, 'widths': {**(model.get('widths') or {}), label: width}}, [])
        case AddMenuToggle():
            others = {k: v for k, v in model.items() if k not in ('col_menu', 'submenu')}
            return ({**others, 'add_menu_open': not model.get('add_menu_open')}, [])
        case ColumnMenuToggle(label=label):
            opening = model.get('col_menu') != label
            # The tally's view belongs to the menu it was narrowed in.
            others = {k: v for k, v in model.items() if k not in ('tally_filter', 'tally_count_filter')}
            return ({**others, 'add_menu_open': False, 'col_menu': label if opening else None, 'submenu': None}, [])
        case SearchBoxInput(value=text):
            return ({**model, 'search': text or None}, [])
        case FirstMatchToggle():
            return ({**model, 'first_match': not model.get('first_match')}, [])
        case ColumnSearchInput(label=label, value=text):
            return (_set_column_search(model, label, text=text), [])
        case ColumnSearchOpSelect(label=label, op=op) if op in COLUMN_SEARCH_OPS:
            return ({**_set_column_search(model, label, op=op), 'submenu': None}, [])
        case ColumnSearchComposeSelect(label=label, compose=compose) if compose in COLUMN_SEARCH_COMPOSE:
            return ({**_set_column_search(model, label, compose=compose), 'submenu': None}, [])
        case SortToggle(label=label, direction=direction):
            same = model.get('sort') == {'label': label, 'direction': direction}
            return ({**model, 'sort': None if same else {'label': label, 'direction': direction}}, [])
        case TallyItemToggle(label=label, literal=literal):
            col = next((i for i, c in enumerate(value.columns) if c.label == label), None)
            if col is not None:
                selected, exclude = _tally_selection(_column_search(model, label))
                selected = [lit for lit in selected if lit != literal] if literal in selected else selected + [literal]
                return (_write_selection(model, label, _in_tally_order(selected, _tally_order(value, model, col)),
                                         exclude), [])
        case TallySelectAll(label=label) | TallySelectNone(label=label):
            col = next((i for i, c in enumerate(value.columns) if c.label == label), None)
            if col is not None:
                selected, exclude = _tally_selection(_column_search(model, label))
                rows = _tally_rows_of(value, model, col)
                shown = _tally_shown(model, rows)
                kept = [lit for lit in selected if lit not in set(shown)]
                if isinstance(msg, TallySelectAll):
                    kept = kept + shown
                return (_write_selection(model, label, _in_tally_order(kept, _tally_order(value, model, col)),
                                         exclude), [])
        case TallyExcludeToggle(label=label):
            selected, exclude = _tally_selection(_column_search(model, label))
            return (_write_selection(model, label, selected, not exclude), [])
        case SubcolToggle(label=label, expr=expr):
            subs = dict(model.get('subcols') or {})
            kept = list(subs.get(label) or [])
            if expr in kept:
                kept.remove(expr)
            elif label in (column.label for column in value.columns):
                kept.append(expr)
            subs[label] = kept
            return ({**model, 'subcols': subs}, [])
        case SubcolShowAll(label=label) | SubcolHideAll(label=label):
            col = next((i for i, c in enumerate(value.columns) if c.label == label), None)
            if col is not None:
                subs = dict(model.get('subcols') or {})
                candidates = _subcol_candidates(value, col, get_visualizer)
                kept = [expr for expr in subs.get(label) or [] if expr not in candidates]
                subs[label] = (kept + candidates) if isinstance(msg, SubcolShowAll) else kept
                return ({**model, 'subcols': subs}, [])
        case SubcolExprInput(label=label, value=text):
            return ({**model, 'subcol_free': {'label': label, 'text': text}}, [])
        case ColumnKeyDown() if not _box_open(model) and (model.get('subcol_free') or {}).get('text'):
            free = model['subcol_free']
            if event_json.get('key') == 'Enter':
                subs = dict(model.get('subcols') or {})
                kept = list(subs.get(free['label']) or [])
                if free['text'].strip() not in kept:
                    kept.append(free['text'].strip())
                subs[free['label']] = kept
                return ({**model, 'subcols': subs, 'subcol_free': None}, [])
            if event_json.get('key') == 'Escape':
                return ({**model, 'subcol_free': None}, [])
        case TallyFilterInput(value=text):
            return ({**model, 'tally_filter': text}, [])
        case TallyCountFilterInput(value=text):
            return ({**model, 'tally_count_filter': text}, [])
        case TallyCountOpSelect(op=op) if op in TALLY_COUNT_OPS:
            return ({**model, 'tally_count_op': op, 'submenu': None}, [])
        case TallySortSelect(sort=sort) if sort in TALLY_SORTS:
            return ({**model, 'tally_sort': sort, 'submenu': None}, [])
        case ColumnMenuDismiss():
            return (_menus_closed(model), [])
        case SubmenuToggle(submenu=submenu):
            return ({**model, 'submenu': None if model.get('submenu') == submenu else submenu}, [])
        case SubmenuDwell(submenu=submenu):
            return ({**model, 'submenu': submenu}, [])
        case InsertColumnClick(col=col, label=label, after=after):
            column = _column(value, col, label)
            if column is not None and (after or column.span is not None) and not is_live_only():
                return ({**_opened(model, 'adding_column', True, ''), 'insert_at': {'label': label, 'after': after}},
                        [])
        case GroupByClick(col=col, label=label):
            column = _column(value, col, label)
            if column is not None and column.subject and not is_live_only():
                return (_opened(model, 'grouping_column', col, _unique_name(value, f'by_{column.subject}')), [])
        case ConvertToggle(col=col, label=label, to=to):
            column = _column(value, col, label)
            assignment = _plain_assignment(label) if column is not None and column.span else None
            if assignment is not None and to in CONVERT_TYPES and not is_live_only():
                name, rhs = assignment
                current, inner = _converted(rhs)
                new_rhs = inner if current == to else f'{to}({inner})'
                return (_menus_closed(model),
                        [ReplaceLines(column.span[0], column.span[1], f'{value.body_indent}{name} = {new_rhs}')])
        case ConvertColumnClick(col=col, label=label, to=to):
            column = _column(value, col, label)
            if column is not None and column.subject and to in CONVERT_TYPES and not is_live_only():
                name = _unique_name(value, f'{column.subject}_{to}')
                line = f'{value.body_indent}{name} = {to}({column.subject})'
                return (_menus_closed(model), [InsertLines(((_beside(value, column, True), line),))])
        case ComputeToggle(label=label, template=template):
            computes = dict(model.get('computes') or {})
            kept = list(computes.get(label, []))
            if template in kept:
                kept.remove(template)
            elif label in (column.label for column in value.columns):
                kept.append(template)
            else:
                return (model, [])
            computes[label] = kept
            return ({**model, 'computes': computes}, [])
        case ComputeFreeInput(label=label, value=text):
            return ({**model, 'compute_free': {'label': label, 'text': text}}, [])
        case ColumnKeyDown() if not _box_open(model) and model.get('col_menu') and event_json.get('key') == 'Escape' \
                and not (model.get('compute_free') or {}).get('text') and not (model.get('subcol_free') or {}).get('text'):
            # Out a level at a time, as a table's menu walks out.
            if model.get('submenu'):
                return ({**model, 'submenu': None}, [])
            return (_menus_closed(model), [])
        case ColumnKeyDown() if not _box_open(model) and (model.get('compute_free') or {}).get('text'):
            free = model['compute_free']
            if event_json.get('key') == 'Enter':
                computes = dict(model.get('computes') or {})
                kept = list(computes.get(free['label'], []))
                if free['text'].strip() not in kept:
                    kept.append(free['text'].strip())
                computes[free['label']] = kept
                return ({**model, 'computes': computes, 'compute_free': None}, [])
            if event_json.get('key') == 'Escape':
                return ({**model, 'compute_free': None}, [])
        case ComputeCodeClick(col=col, label=label, kind=kind):
            column = _column(value, col, label)
            if column is not None and column.subject and not is_live_only():
                code = _compute_code(value, column.subject, kind)
                if code:
                    return (_menus_closed(model), code)
        case AddMenuDismiss():
            return ({**model, 'add_menu_open': False}, [])
        case ColumnToggle(label=label):
            hidden = list(model.get('hidden_columns') or [])
            if label in hidden:
                hidden.remove(label)
            elif label in (column.label for column in value.columns):
                hidden.append(label)
            return ({**model, 'hidden_columns': hidden}, [])
        case ColumnShowAll():
            statements = {column.label for column in value.columns if column.span is not None}
            return ({**model, 'hidden_columns': [h for h in model.get('hidden_columns') or []
                                                 if h not in statements]}, [])
        case ColumnHideAll():
            hidden = list(model.get('hidden_columns') or [])
            hidden += [column.label for column in value.columns if column.span is not None and column.label not in hidden]
            return ({**model, 'hidden_columns': hidden}, [])
        case AddColumnClick():
            return (_opened(model, 'adding_column', True, ''), [])
        case ColumnClick(col=col, label=label):
            if double_click and _statement_span(value, col, label) is not None:
                return (_opened(model, 'editing_column', col, label), [])
        case InitCellClick(col=col, label=label):
            if double_click and _accumulator(value, col, label) is not None and not is_live_only():
                return (_opened(model, 'editing_init', col, _init_of(value, col) or ''), [])
        case CollectClick(col=col, label=label):
            column = _collectable(value, col, label)
            if column is not None and not is_live_only():
                return (_opened(model, 'collecting_column', col, _list_name(value, column.subject)), [])
        case DeleteColumnClick(col=col, label=label):
            span = _statement_span(value, col, label)
            if span is not None and not is_live_only():
                # A body can't be empty: the last statement in it leaves a pass.
                text = f'{value.body_indent}pass' if span == value.body_lines else None
                return (_menus_closed(model), [ReplaceLines(span[0], span[1], text)])
        case ColumnInput(value=typed) if _box_open(model):
            others = {k: v for k, v in model.items() if k != 'selected_suggestion'}
            return ({**others, 'column_input': typed}, [])
        case ColumnSelect(text=text) if _box_open(model):
            others = {k: v for k, v in model.items() if k != 'selected_suggestion'}
            return ({**others, 'column_input': _finished(model, text)}, [])
        case ColumnKeyDown() if _box_open(model) and event_json.get('key') in ('ArrowDown', 'ArrowUp'):
            offered = _suggestions(value, model, get_visualizer)
            if offered:
                at = model.get('selected_suggestion')
                if event_json['key'] == 'ArrowDown':
                    at = 0 if at is None else min(at + 1, len(offered) - 1)
                else:
                    at = None if not at else at - 1
                return ({**model, 'selected_suggestion': at}, [])
        case ColumnKeyDown() if _box_open(model) and event_json.get('key') == 'Enter' \
                and model.get('selected_suggestion') is not None:
            offered = _suggestions(value, model, get_visualizer)
            at = model['selected_suggestion']
            if at < len(offered):
                return ({**model, 'column_input': _finished(model, offered[at]), 'selected_suggestion': None}, [])
        case ActionButtonClick(action=action) if not is_live_only():
            code = _action_code(value, model, action)
            if code:
                return (model, code)
        case RowMenuToggle(row=row):
            return ({**_menus_closed(model), 'add_menu_open': False,
                     'row_menu': None if model.get('row_menu') == row else row}, [])
        case RowActionClick(row=row, action=action) if not is_live_only():
            code = _row_action_code(value, row, action)
            if code:
                return (_menus_closed(model), code)
        case ToolSelect(tool=tool) if tool in ('normal', 'pick'):
            return ({**model, 'tool': tool}, [])
        case PickToggle(label=label):
            picked = list(model.get('picked') or [])
            if label in picked:
                picked.remove(label)
            elif label in (column.label for column in value.columns):
                picked.append(label)
            return ({**model, 'picked': picked}, [])
        case ColumnKeyDown() if _box_open(model):
            key = event_json.get('key')
            if key in ('Enter', 'Tab'):
                return _write_box(model, value)
            if key == 'Escape':
                return (_closed(model), [])
        case ColumnInputBlur() if _box_open(model):
            return (_closed(model), [])
    return (model, [])


def _closed(model):
    model = {k: v for k, v in model.items() if k != 'insert_at'}
    return {**model, 'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, 'grouping_column': None, 'column_input': ''}


def _menus_closed(model):
    """The model with the column menu put away, as anything it did does."""
    return {**model, 'col_menu': None, 'submenu': None, 'row_menu': None}


def _tally_rows_of(value: ForLoopTable, model, col: int):
    tally = _tally(_column_values(value, col) or [])
    return _tally_rows(tally, model) if isinstance(tally, dict) else []


def _tally_order(value: ForLoopTable, model, col: int) -> List[str]:
    """Every literal a column's tally can search for, in the order it lists them."""
    return [literal for _text, _count, literal in _tally_rows_of(value, model, col) if literal is not None]


def _compute_code(value: ForLoopTable, subject: str, kind: str) -> List[Any]:
    """What builds an answer about `subject` up as the loop runs: a name set
    above the loop, and a line at the end of its body adding to it."""
    lines = {
        'unique': ('unique', 'set()', '{n}.add({s})'),
        'tally': ('tally', 'Counter()', '{n}[{s}] += 1'),
        'sum': ('sum', '0', '{n} += {s}'),
        'min': ('min', 'None', '{n} = {s} if {n} is None else min({n}, {s})'),
        'max': ('max', 'None', '{n} = {s} if {n} is None else max({n}, {s})'),
    }.get(kind)
    if lines is None:
        return []
    prefix, start, step = lines
    name = _unique_name(value, f'{prefix}_{subject}')
    insert = InsertLines(((value.line - 1, f'{value.indent}{name} = {start}'),
                          (_body_end(value), f'{value.body_indent}{step.format(n=name, s=subject)}')))
    return [AddImports(('from collections import Counter',)), insert] if kind == 'tally' else [insert]


def _write_box(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in the box: write what it holds, as whatever the box is for."""
    if model.get('editing_init') is not None:
        return _write_init(model, value)
    if model.get('collecting_column') is not None:
        return _write_collect(model, value)
    if model.get('grouping_column') is not None:
        return _write_group_by(model, value)
    statement = model.get('column_input', '').strip()
    if statement and not _parses(statement):
        # Left open, as typed: written, it would break the whole file.
        return (model, [])
    col = model.get('editing_column')
    if not statement or is_live_only():
        return (_closed(model), [])
    if col is None:
        after = _body_end(value)
        insert_at = model.get('insert_at')
        column = next((c for c in value.columns if insert_at and c.label == insert_at['label']), None)
        if column is not None:
            after = _beside(value, column, insert_at['after'])
        # If it comes back an accumulator with nothing to start from, its
        # starting value is the next thing to type.
        pending = {'label': ' '.join(statement.split()), 'labels': [column.label for column in value.columns]}
        return ({**_closed(model), 'pending_init': pending},
                [InsertLines(((after, f'{value.body_indent}{statement}'),))])
    label = value.columns[col].label if 0 <= col < len(value.columns) else ''
    span = _statement_span(value, col, label)
    if span is None or statement == label:
        return (_closed(model), [])
    return (_closed(model), [ReplaceLines(span[0], span[1], f'{value.body_indent}{statement}')])


def _write_init(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in an init cell: `name = value` over the line that set the
    accumulator right before the loop, or as a new line above the loop."""
    typed = model.get('column_input', '').strip()
    if typed and not _is_value(typed):
        return (model, [])
    col = model['editing_init']
    column = value.columns[col] if 0 <= col < len(value.columns) else None
    if (not typed or is_live_only() or column is None or _accumulator(value, col, column.label) is None
            or typed == _init_of(value, col)):
        return (_closed(model), [])
    text = f'{value.indent}{column.subject} = {typed}'
    if column.init_span is not None:
        return (_closed(model), [ReplaceLines(column.init_span[0], column.init_span[1], text)])
    return (_closed(model), [InsertLines(((value.line - 1, text),))])


def _write_group_by(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in the box naming a dict: the dict above the loop, and the line
    at the end of its body putting each iteration's names under its value of
    the column."""
    name = model.get('column_input', '').strip()
    col = model['grouping_column']
    column = value.columns[col] if 0 <= col < len(value.columns) else None
    if not name or is_live_only() or column is None or not column.subject:
        return (_closed(model), [])
    if not name.isidentifier() or keyword.iskeyword(name) or name in value.defined:
        return (model, [])
    targets = value.targets or (column.subject,)
    item = targets[0] if len(targets) == 1 else f'({", ".join(targets)})'
    return (_closed(model), [InsertLines(((value.line - 1, f'{value.indent}{name} = {{}}'),
                                          (_body_end(value),
                                           f'{value.body_indent}{name}.setdefault({column.subject}, [])'
                                           f'.append({item})')))])


def _write_collect(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in the box naming a list: the list above the loop, and the line
    appending to it at the end of the body."""
    name = model.get('column_input', '').strip()
    col = model['collecting_column']
    column = value.columns[col] if 0 <= col < len(value.columns) else None
    if not name or is_live_only() or column is None or _collectable(value, col, column.label) is None:
        return (_closed(model), [])
    if not name.isidentifier() or keyword.iskeyword(name) or name in value.defined:
        # Left open, as typed: a name already in use would be overwritten.
        return (model, [])
    after = value.body_lines[1] or value.end_line
    return (_closed(model), [InsertLines(((value.line - 1, f'{value.indent}{name} = []'),
                                          (after, f'{value.body_indent}{name}.append({column.subject})')))])
