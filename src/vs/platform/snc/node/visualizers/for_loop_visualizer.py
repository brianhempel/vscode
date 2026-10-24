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

**The (+) adds a column of the user's own.** It ends the header row, as a
table's does, and opens a box in its place. A loop's column is a line of its
body rather than a table's view of its rows, so what is typed is a statement --
`doubled = element * 2` -- and Enter writes it at the end of the body, where the
next run draws it as the last column. That code lands away from the line this
visualizer sits on, so it goes out as InsertLines rather than a NewCode tuple.
Leaving the box closes it unwritten: a table's column box writes on blur, but
that is a view, and this is code. The (+) is a bar beside the table, as a
table's is, except that a table only draws its own once it is focused, and this
one never is.

**A column is edited and deleted through its header.** Double-clicking a
statement's header opens the same box over it, holding the statement; Enter
writes what it then holds over the statement's lines. The x beside it deletes
them, leaving a `pass` when nothing else would be left in the body. A name the
loop binds has no statement of its own, so its header does neither.

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

**A column's ▾ collects it into a list.** A hover menu, so it needs no state of
its own; Collect into List opens the box on a name for the list, and Enter
writes `name = []` above the loop and `name.append(subject)` at the end of its
body, which comes back as a column of its own, starting from []. A column that
changes its name in place has one object in every row, so it offers none.

**While the loop runs, the rows of last time.** The table logged as the loop
starts has none of its own yet, and the finished one replaces it a moment
later. Drawn empty, it would shrink and regrow the table on every run -- every
key typed in its box -- and move everything under it with it. So a finished
table leaves its rows in the model, and the running one draws them, matched to
its columns by label.

**Never focused.** The table only shows while the cursor is elsewhere, so the
(+), the headers, the init cells and the menus are snc-unfocused-clickable; a press on the table itself expands it like
any other small visualizer, which moves the cursor into the loop. The box takes
the keyboard as it opens, for the same reason.

Sorts before `z_object_visualizer` (which claims everything) so that the table
reaches it rather than being shown as a dataclass's fields.
"""

import ast
import html
import keyword
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from visualizer_utils import (EXPANDED_PANE_MAX_HEIGHT, ForLoopColumn, ForLoopTable, InsertLines, ReplaceLines,
                              is_live_only)


@dataclass(frozen=True)
class AddColumnClick:
    """A press on the (+): open the box a column is written in."""


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
class ColumnInput:
    """The column box now holds `value`."""
    value: str


@dataclass(frozen=True)
class ColumnKeyDown:
    """A key in the column box: Enter or Tab writes it, Escape closes it."""


@dataclass(frozen=True)
class ColumnInputBlur:
    """The column box lost the keyboard: it closes, unwritten."""


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


BOX_KEYS = ('adding_column', 'editing_column', 'editing_init', 'collecting_column')


def _box_open(model) -> bool:
    return bool(model.get('adding_column')) or any(model.get(k) is not None for k in BOX_KEYS[1:])


def _opened(model, key: str, col, text: str):
    """The model with one box open -- `key`, on column `col` -- holding `text`."""
    return {**model, 'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, key: col, 'column_input': text}


def _render_box(model, tag: str = 'th', select_all: bool = False, placeholder: str = 'Line of code',
                tooltip: str = 'Written at the end of the loop') -> str:
    """The box code is typed in: a new column's, one being edited, a starting
    value, or the name of a list a column is collected into."""
    input_event = "lambda e: ColumnInput(value=e.get('value', ''))"
    select = ' snc-select-all' if select_all else ''
    return (f'<{tag}><span class="snc-dropdown-trigger">'
            f'<input type="text" class="col-input" autofocus{select} snc-unfocused-clickable spellcheck="false" '
            f'snc-input="{html.escape(input_event)}" '
            f'snc-blur="{html.escape(repr(ColumnInputBlur()))}" '
            f'value="{html.escape(model.get("column_input", ""))}" '
            f'placeholder="{html.escape(placeholder)}" '
            f'data-tooltip="{html.escape(tooltip)}" />'
            f'</span></{tag}>')


def _render_label(column: ForLoopColumn) -> str:
    """The column's label, the part of it that is the value shown underlined."""
    shown, rest = column.label[:column.underline], column.label[column.underline:]
    if not shown:
        return html.escape(column.label)
    return f'<span class="for-loop-col-subject">{html.escape(shown)}</span>{html.escape(rest)}'


def _render_menu(value: ForLoopTable, col: int) -> str:
    """The ▾ with what can be done to the whole column: a hover menu, which the
    editor lifts out of the table, so it needs no state of its own."""
    column = value.columns[col]
    if _collectable(value, col, column.label) is None:
        return ''
    collect = repr(CollectClick(col=col, label=column.label))
    return (f'<span class="snc-dropdown-trigger for-loop-col-menu" snc-unfocused-clickable draggable="false">'
            f'<span class="for-loop-col-menu-icon">▾</span>'
            f'<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
            f'<div class="snc-dropdown-option">'
            f'<span class="snc-dropdown-option-label" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(collect)}" '
            f'data-tooltip="{html.escape(f"A list of every {column.subject}, built as the loop runs")}">'
            f'Collect into List</span>'
            f'</div></div></span>')


def _render_header(value: ForLoopTable, model, col: int, live_only: bool) -> str:
    column = value.columns[col]
    label = column.label
    if live_only:
        return f'<th>{_render_label(column)}</th>'
    if column.span is None:
        return f'<th class="for-loop-col">{_render_label(column)}{_render_menu(value, col)}</th>'
    if model.get('editing_column') == col:
        return _render_box(model, select_all=True, tooltip='Written over this line of the loop')
    edit = repr(ColumnClick(col=col, label=label))
    delete = repr(DeleteColumnClick(col=col, label=label))
    return (f'<th class="for-loop-col">'
            f'<span class="for-loop-col-label" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(edit)}" data-tooltip="Double-click to edit">{_render_label(column)}</span>'
            f'{_render_menu(value, col)}'
            f'<span class="for-loop-col-delete" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(delete)}" data-tooltip="Delete this line">×</span>'
            f'</th>')


def _render_add_bar() -> str:
    """The (+), a bar down the table's right edge, as a table's is."""
    return (f'<div class="snc-dropdown-trigger col-add-trigger">'
            f'<span class="col-add-icon full-opacity-on-hover" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(repr(AddColumnClick()))}" '
            f'data-tooltip="Add a line to the loop">+</span></div>')


def _render_cell(text) -> str:
    if text is None:
        return '<td class="list-table-cell">—</td>'
    return f'<td class="list-table-cell"><span class="snc-code">{html.escape(text)}</span></td>'


def _render_init_cell(value: ForLoopTable, model, col: int, live_only: bool) -> str:
    """Where column `col` starts: blank unless it is an accumulator."""
    column = value.columns[col]
    if not column.accumulator or not column.subject:
        return '<td class="list-table-cell"></td>'
    if not live_only and model.get('editing_init') == col:
        return _render_box(model, tag='td', select_all=True, placeholder='Starting value',
                           tooltip=f'Sets {column.subject} before the loop')
    init = _init_of(value, col)
    if init is None:
        text = '' if live_only else '<span class="for-loop-init-unset">set…</span>'
    else:
        text = f'<span class="snc-code">{html.escape(init)}</span>'
    if live_only:
        return f'<td class="list-table-cell">{text}</td>'
    click = repr(InitCellClick(col=col, label=column.label))
    return (f'<td class="list-table-cell for-loop-init-cell">'
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


def visualize(value: ForLoopTable, model=None, get_visualizer=None, small=False):
    if model is None:
        model = {}
    live_only = is_live_only()
    rows, hidden_rows = _rows_to_draw(value, model)
    if not live_only:
        _open_pending_init(value, model)
    key_handler = '' if live_only else f' snc-key-down="{html.escape(repr(ColumnKeyDown()))}"'
    # Capped like a table nested in a cell: the loop's own code is right
    # above, and a long loop shouldn't push the rest of the file away.
    strs = [f'<div class="list-visualizer small for-loop-visualizer"{key_handler}>',
            '<div class="snc-tool-and-visualizer">',
            f'<div class="list-table-scroll snc-base-visualizer" style="max-height: {EXPANDED_PANE_MAX_HEIGHT // 2}px;">',
            '<table><thead class="col-header-rows"><tr>',
            '<th class="row-index-header">itr</th>']
    strs += [_render_header(value, model, col, live_only) for col in range(len(value.columns))]
    # Every column it adds is code, so live-only leaves it out.
    if not live_only and model.get('adding_column'):
        strs.append(_render_box(model))
    collecting = model.get('collecting_column')
    if not live_only and collecting is not None and 0 <= collecting < len(value.columns):
        subject = value.columns[collecting].subject
        strs.append(_render_box(model, select_all=True, placeholder='List name',
                                tooltip=f'Every {subject}, collected into this list'))
    strs.append('</tr></thead><tbody>')
    if any(column.accumulator and column.subject for column in value.columns):
        strs.append('<tr class="for-loop-init-row"><td class="row-index">init</td>')
        strs += [_render_init_cell(value, model, col, live_only) for col in range(len(value.columns))]
        strs.append('</tr>')
    for i, row in enumerate(rows):
        strs.append(f'<tr><td class="row-index">{i}</td>')
        strs += [_render_cell(text) for text in row]
        strs.append('</tr>')
    strs.append('</tbody></table></div>')
    if not live_only:
        strs.append(_render_add_bar())
    strs.append('</div>')
    if hidden_rows:
        noun = 'iteration' if hidden_rows == 1 else 'iterations'
        strs.append(f'<div class="for-loop-note">{hidden_rows} more {noun}</div>')
    strs.append('</div>')
    return ''.join(strs)


def update(event, var_and_exp, model, value: ForLoopTable, get_visualizer=None) -> Tuple[Any, List[Any]]:
    if not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])
    event_json = event.get('eventJSON') or {}
    try:
        make_event = eval(event['pythonEventStr'])
        msg = make_event(event_json) if callable(make_event) else make_event
    except Exception:
        return (model, [])
    model = dict(model or {})
    double_click = event_json.get('detail', 1) >= 2
    match msg:
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
                return (model, [ReplaceLines(span[0], span[1], text)])
        case ColumnInput(value=typed) if _box_open(model):
            return ({**model, 'column_input': typed}, [])
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
    return {**model, 'adding_column': False, 'editing_column': None, 'editing_init': None,
            'collecting_column': None, 'column_input': ''}


def _write_box(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in the box: write what it holds, as whatever the box is for."""
    if model.get('editing_init') is not None:
        return _write_init(model, value)
    if model.get('collecting_column') is not None:
        return _write_collect(model, value)
    statement = model.get('column_input', '').strip()
    if statement and not _parses(statement):
        # Left open, as typed: written, it would break the whole file.
        return (model, [])
    col = model.get('editing_column')
    if not statement or is_live_only():
        return (_closed(model), [])
    if col is None:
        after = value.body_lines[1] or value.end_line
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
