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

**While the loop runs, the rows of last time.** The table logged as the loop
starts has none of its own yet, and the finished one replaces it a moment
later. Drawn empty, it would shrink and regrow the table on every run -- every
key typed in its box -- and move everything under it with it. So a finished
table leaves its rows in the model, and the running one draws them, matched to
its columns by label.

**Never focused.** The table only shows while the cursor is elsewhere, so the
(+) and the headers are snc-unfocused-clickable; a press on the table itself expands it like
any other small visualizer, which moves the cursor into the loop. The box takes
the keyboard as it opens, for the same reason.

Sorts before `z_object_visualizer` (which claims everything) so that the table
reaches it rather than being shown as a dataclass's fields.
"""

import ast
import html
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from visualizer_utils import EXPANDED_PANE_MAX_HEIGHT, ForLoopTable, InsertLines, ReplaceLines, is_live_only


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


def _statement_span(value: ForLoopTable, col: int, label: str) -> Optional[Tuple[int, int]]:
    """The lines of column `col`'s statement, if it is still the column that
    was drawn as `label` and is a statement at all. The event was drawn
    against the code as it was, and the loop may have changed under it."""
    if not 0 <= col < min(len(value.columns), len(value.spans)) or value.columns[col] != label:
        return None
    return value.spans[col]


def _parses(statement: str) -> bool:
    try:
        ast.parse(statement)
    except SyntaxError:
        return False
    return True


def _box_open(model) -> bool:
    return bool(model.get('adding_column')) or model.get('editing_column') is not None


def _render_box(model, editing: bool) -> str:
    """The box a column is written in: a new one's, or one being edited."""
    input_event = "lambda e: ColumnInput(value=e.get('value', ''))"
    select = ' snc-select-all' if editing else ''
    tooltip = 'Written over this line of the loop' if editing else 'Written at the end of the loop'
    return (f'<th><span class="snc-dropdown-trigger">'
            f'<input type="text" class="col-input" autofocus{select} snc-unfocused-clickable spellcheck="false" '
            f'snc-input="{html.escape(input_event)}" '
            f'snc-blur="{html.escape(repr(ColumnInputBlur()))}" '
            f'value="{html.escape(model.get("column_input", ""))}" '
            f'placeholder="Line of code" '
            f'data-tooltip="{tooltip}" />'
            f'</span></th>')


def _render_header(value: ForLoopTable, model, col: int, live_only: bool) -> str:
    label = value.columns[col]
    if live_only or _statement_span(value, col, label) is None:
        return f'<th>{html.escape(label)}</th>'
    if model.get('editing_column') == col:
        return _render_box(model, editing=True)
    edit = repr(ColumnClick(col=col, label=label))
    delete = repr(DeleteColumnClick(col=col, label=label))
    return (f'<th class="for-loop-col">'
            f'<span class="for-loop-col-label" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(edit)}" data-tooltip="Double-click to edit">{html.escape(label)}</span>'
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


def _rows_to_draw(value: ForLoopTable, model) -> Tuple[Tuple[Tuple[Optional[str], ...], ...], int]:
    """The rows to draw, and how many iterations go without one: the table's
    own once the loop has finished, which are remembered; the ones remembered
    from last time while it is still running."""
    if not value.running:
        model['last_rows'] = [dict(zip(value.columns, row)) for row in value.rows]
        model['last_hidden_rows'] = value.hidden_rows
        return value.rows, value.hidden_rows
    if value.rows:
        return value.rows, value.hidden_rows
    rows = tuple(tuple(row.get(label) for label in value.columns) for row in model.get('last_rows') or [])
    return rows, model.get('last_hidden_rows', 0)


def visualize(value: ForLoopTable, model=None, get_visualizer=None, small=False):
    if model is None:
        model = {}
    live_only = is_live_only()
    rows, hidden_rows = _rows_to_draw(value, model)
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
        strs.append(_render_box(model, editing=False))
    strs.append('</tr></thead><tbody>')
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
    match msg:
        case AddColumnClick():
            return ({**model, 'adding_column': True, 'editing_column': None, 'column_input': ''}, [])
        case ColumnClick(col=col, label=label):
            if event_json.get('detail', 1) >= 2 and _statement_span(value, col, label) is not None:
                return ({**model, 'adding_column': False, 'editing_column': col, 'column_input': label}, [])
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
    return {**model, 'adding_column': False, 'editing_column': None, 'column_input': ''}


def _write_box(model, value: ForLoopTable) -> Tuple[Any, List[Any]]:
    """Enter in the box: a new line at the end of the body, or the edited
    statement over its old lines."""
    statement = model.get('column_input', '').strip()
    if statement and not _parses(statement):
        # Left open, as typed: written, it would break the whole file.
        return (model, [])
    col = model.get('editing_column')
    if not statement or is_live_only():
        return (_closed(model), [])
    if col is None:
        after = value.body_lines[1] or value.end_line
        return (_closed(model), [InsertLines(((after, f'{value.body_indent}{statement}'),))])
    label = value.columns[col] if 0 <= col < len(value.columns) else ''
    span = _statement_span(value, col, label)
    if span is None or statement == label:
        return (_closed(model), [])
    return (_closed(model), [ReplaceLines(span[0], span[1], f'{value.body_indent}{statement}')])
