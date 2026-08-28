"""Table visualizer for Sculpt-n-Code -- claims both lists and dicts.

================================================================================
ARCHITECTURE OVERVIEW
================================================================================

This visualizer follows the Elm architecture with three core functions:

1. visualize(value, model) -> HTML string
   - Always renders lists as a table with configurable columns
   - Shows column management controls (add, edit, remove, reorder)

2. init_model(value) -> dict
   - Returns the initial model state
   - Auto-detects columns from item fields, or defaults to ['$'] (the item)
   - Loads the column configuration saved with the line (its #%click comment)

3. update(event, var_and_exp, model, value) -> (new_model, commands)
   - Processes UI events (click, input, keyboard, drag) and returns updated model
   - Routes child events to cell visualizers
   - Handles column management events

================================================================================
COLUMN CONFIGURATION
================================================================================

Columns shown in the table are configurable and persisted:

1. THE LINE'S #%click COMMENT (see visualizer_utils, "Per-line config"):
   - A slot list; the runner hands it to init_model as `slots_config`
   - Highest priority: user-customized columns, for this line only
   - A save goes into the line's config store; the runner turns it into a
     rewrite of the comment

2. The defaults, via _default_columns:
   - The row itself -- ['$'], or ['$k', '$v'] for a dict -- always
   - Its length where the rows are lists
   - The fields the rows spread into, where all sampled items support
     get_fields and there are no more than MAX_DEFAULT_FIELDS of them
   - So strings, ints, mixed types and empty lists open as ['$'] alone
   - Users can add computed columns via the (+) button
================================================================================
"""

import ast
import copy
import functools
import html
import itertools
import keyword
import math
import random
import re
import warnings
from dataclasses import dataclass, field, replace
from typing import Any, List, Tuple, Optional

from table_visualizer_grammar import parse_generated_code_or_assignment, _STATEMENT_ACTIONS
from visualizer_utils import is_read_only
from visualizer_utils import (
    ChildEvent, Unlink, Relink,
    route_child_event, aggregate_handled_keys,
    opens_block, with_pass_body,
    LinkConfig, handle_relink,
    wrap_child_prefix, wrap_child_suffix, defer_drag_grab, add_drag_readings,
    DOLLARS_RE, SIGILS, Dollar, DollarScope,
    eval_dollar_expr, replace_dollars_in_py_exp,
    py_exp_attrs, PyExp,
    CHILD_SOURCE_BINDER, nest_generated_expr, nest_child_command,
    new_code_command, is_new_code, imports_for_code, AddImports,
    dollar_expr_parses, dollar_expr_names_index, dollar_expr_sigils, is_nested,
    parse_slot_cols,
    get_full_class_name, truncate_str, truncate_repr, wrap_drag_grab,
    parse_slots, save_slots_at_path,
    child_nesting_kwargs, too_deep, wants_kwarg, compose_dollar_expr,
    nerd_font_icon, render_tool_toolbar,
    render_expand_toggle, EXPANDED_PANE_MAX_HEIGHT,
    ICONS,
)

CELL_KEY_SEP = '\x00'

# Inside the row half of an aggregation answer's child key; see _agg_child_key.
# A character of its own rather than SUBCOL_SEP's: a key holds column
# identities, a sub-column's identity is joined with SUBCOL_SEP, and the two
# sharing a character would leave the key unparseable exactly when a table has
# sub-columns.
AGG_KEY_SEP = '\x02'

# How many rows a table draws before it stops and offers to draw the next lot,
# and how many it always keeps at the end. The tail is kept because a list is as
# much its end as its beginning -- a short final record or a stray value tends
# to be down there -- and because the aggregations are drawn directly under the
# last row: a foot reporting on the whole list belongs under the list's own last
# row rather than under whichever row the paging happened to stop at.
ROWS_PER_PAGE = 50
TAIL_ROWS = 3

# === Event types ===

@dataclass(frozen=True, slots=True)
class AddColumnClick:
    """User picked Add Column in the (+) menu, which opens the box that writes
    one at the far right of the table."""
    pass

@dataclass(frozen=True, slots=True)
class ColumnToggle:
    """User checked or unchecked one of the (+) menu's rows, which puts a
    column of the table on or takes it off.

    Identified by the expression the row is showing rather than by a column,
    like SubcolToggle: an unchecked row names a column the table hasn't got, so
    there is nothing yet for `_named_column` to answer with.
    """
    expr: str

@dataclass(frozen=True, slots=True)
class ColumnShowAll:
    """User clicked Show all in the (+) menu, which puts on every field the
    rows have."""
    pass

@dataclass(frozen=True, slots=True)
class ColumnHideAll:
    """User clicked Hide all in the (+) menu, which takes those same fields
    away -- the ones they wrote as well as the ones detected, since the menu
    lists both in the one section this pair acts on.

    Not the row columns over it: `$` and `len($)` are true of every table rather
    than found in this one, so neither half of the pair is an ask about them.
    """
    pass

@dataclass(frozen=True, slots=True)
class AddColumnAtClick:
    """User picked Add Column Before / After in a column's ▾ menu.

    The same box the (+) opens, drawn beside the column it was asked for
    instead of at the far right -- and, over a sub-column, adding a sub-column
    of that column's parent rather than a column of the table.
    """
    col: str
    after: bool

@dataclass(frozen=True, slots=True)
class ColumnInput:
    """User typed in the column name input (add or edit mode)."""
    value: str

@dataclass(frozen=True, slots=True)
class ColumnSelect:
    """User clicked an autocomplete suggestion for a column."""
    name: str

@dataclass(frozen=True, slots=True)
class ColumnClick:
    """User clicked on an existing column header (double-click to edit)."""
    col: str

@dataclass(frozen=True, slots=True)
class ColumnResize:
    """User resized a column by dragging the resize handle."""
    col: str
    width: int

@dataclass(frozen=True, slots=True)
class RemoveColumnClick:
    """User clicked the (x) button to remove a column."""
    col: str

@dataclass(frozen=True, slots=True)
class ColumnDragStart:
    """User pressed mouse down on a column drag handle to start reordering."""
    col: str

@dataclass(frozen=True, slots=True)
class ColumnDragOver:
    """Mouse moved over a column header while dragging (reorder target)."""
    col: str

@dataclass(frozen=True, slots=True)
class ColumnDragEnd:
    """User released mouse to drop a column at the target position."""
    col: str

@dataclass(frozen=True, slots=True)
class ColumnKeyDown:
    """Keyboard event in column management (Enter to commit, Escape to cancel)."""
    pass

@dataclass(frozen=True, slots=True)
class ColumnSearchInput:
    """User typed in a column's search box (inside that column's ▾ menu)."""
    col: str
    value: str

@dataclass(frozen=True, slots=True)
class ColumnSearchOpSelect:
    """User picked a comparison operator for a column's search."""
    col: str
    op: str

@dataclass(frozen=True, slots=True)
class ColumnSearchComposeSelect:
    """User picked how a column's search composes with the other columns'."""
    col: str
    compose: str

@dataclass(frozen=True, slots=True)
class ColumnSearchDropdownToggle:
    """User toggled one of the two small chip menus on a column search row.

    Separate from DropdownToggle because these panels are nested INSIDE the open
    column menu: routing them through the single `openDropdown` slot would close
    the very menu they live in.
    """
    dropdown_id: str

@dataclass(frozen=True, slots=True)
class TallyItemToggle:
    """User clicked one of a column's tally rows.

    Identified by the value's literal rather than its position, so a click can't
    land on a different value than the one it was aimed at.
    """
    col: str
    literal: str

@dataclass(frozen=True, slots=True)
class TallySelectAll:
    """User clicked Select All on a column's tally."""
    col: str

@dataclass(frozen=True, slots=True)
class TallySelectNone:
    """User clicked Select None on a column's tally."""
    col: str

@dataclass(frozen=True, slots=True)
class TallyExcludeToggle:
    """User toggled Exclude on a column's tally, turning the values it has
    selected into the ones to leave out."""
    col: str

@dataclass(frozen=True, slots=True)
class TallyFilterInput:
    """User typed in a column tally's filter box, narrowing which of the
    column's values the menu lists."""
    col: str
    value: str

@dataclass(frozen=True, slots=True)
class TallySortSelect:
    """User picked the order a column tally lists its values in."""
    col: str
    sort: str

@dataclass(frozen=True, slots=True)
class TallyCountFilterInput:
    """User typed in a column tally's count box, narrowing the menu to the
    values of that frequency."""
    col: str
    value: str

@dataclass(frozen=True, slots=True)
class TallyCountOpSelect:
    """User picked how a column tally's count box compares."""
    col: str
    op: str

@dataclass(frozen=True, slots=True)
class ColumnMenuDismiss:
    """A click landed outside an open ▾ menu, so the menu is finished.

    What a menu anywhere else does. The ▾ still toggles, and Escape still walks
    out a level at a time; this is the third way out, and the one that needs no
    aiming.

    A row's menu is dismissed by the same event as a column's: both are held
    open by the one `openDropdown` slot, and "a click landed outside" says
    nothing about which of them it landed outside of.
    """
    pass

@dataclass(frozen=True, slots=True)
class RowActionClick:
    """User clicked a row of the ▾ menu on a row's number.

    One event for the three of them rather than one each, because they are one
    question asked three ways -- what line does this row write? -- and the
    catalog that answers it is what the menu draws itself from. So a row and
    its click cannot come to disagree about what the row writes.
    """
    row: int
    action: str

@dataclass(frozen=True, slots=True)
class ColumnSubmenuDwell:
    """Pointer came to rest on a row of a column's ▾ menu.

    Says which submenu should be open, rather than toggling one: dwelling is
    not a click, and the answer to "the pointer is here" can't depend on where
    it was. None means none of them.
    """
    dropdown_id: Optional[str] = None

@dataclass(frozen=True, slots=True)
class SortClick:
    """User clicked Asc or Desc in a column's Sort submenu, which sorts the
    line the table is already showing rather than writing a new one.

    Clicking the direction the line already sorts in takes the sort off, so one
    row is both the way in and the way out.
    """
    col: str
    direction: str

@dataclass(frozen=True, slots=True)
class SortCodeClick:
    """User clicked one of the Sort submenu's `(new code)` rows, which writes
    the sorted list as a line of its own and leaves the original alone."""
    col: str
    direction: str

@dataclass(frozen=True, slots=True)
class GroupByClick:
    """User clicked Group By in a column's ▾ menu, which writes the list cut up
    by that column as a line of its own.

    A line rather than a rewrite of the one the table is showing: sorting is the
    same rows in another order, but grouping changes what the value IS -- a list
    becomes a dict of lists -- so it is written beside the original rather than
    over it.
    """
    col: str

@dataclass(frozen=True, slots=True)
class ConvertTypeToggle:
    """User checked or unchecked one of a column's Convert Type rows, which
    rewrites the COLUMN's own expression rather than the line the table is
    showing -- a conversion is about how one column reads, where a sort is about
    the order the rows arrive in.

    Clicking the type the column already reads as takes the conversion off, so
    one row is both the way in and the way out -- the shape SortClick has.
    """
    col: str
    to: str

@dataclass(frozen=True, slots=True)
class ConvertTypeColumnClick:
    """User clicked one of the Convert Type submenu's `(new column)` rows, which
    puts the converted column beside the original instead of over it."""
    col: str
    to: str

@dataclass(frozen=True, slots=True)
class ComputeToggle:
    """User checked or unchecked one of a column's Compute rows.

    Identified by the expression it is showing rather than by a name for it, so
    an aggregation the user wrote themselves needs no event of its own.

    *per_group* is which box was ticked. The first asks the question of the
    whole column and keeps the answer in a cell under the table; the second asks
    it of each group, whose answer is a value per row of this table and so is
    kept as a COLUMN. It defaults to False so a table without a splat, where
    there are no groups to ask of, means what it always meant.
    """
    col: str
    expr: str
    per_group: bool = False

@dataclass(frozen=True, slots=True)
class ComputeHoleInput:
    """User typed in one of the boxes inside a Compute row's expression, e.g.
    the level of a percentile."""
    col: str
    expr: str
    hole: int
    value: str

@dataclass(frozen=True, slots=True)
class ComputeCodeClick:
    """User clicked one of the Compute submenu's code rows -- Unique, Tally --
    which answer with a whole list, so they write a line rather than keep a cell
    on screen."""
    col: str
    expr: str

@dataclass(frozen=True, slots=True)
class ComputeExprInput:
    """User typed an aggregation of their own: into the empty box at the foot of
    the Compute submenu, or into the box that labels the cell it made.

    Both boxes hold the whole expression rather than part of one, which is what
    tells this from ComputeHoleInput.
    """
    col: str
    expr: str
    value: str

@dataclass(frozen=True, slots=True)
class ComputeExprKeyDown:
    """Enter or Escape in a box holding a whole aggregation.

    Its own event rather than the container's ColumnKeyDown: Enter there means
    "filter on the search", which is not what Enter over an aggregation the user
    has just finished writing should mean.
    """
    pass

@dataclass(frozen=True, slots=True)
class SplatColumnClick:
    """User clicked Expand list items into rows, which turns a column of lists
    into a splat: the elements spread DOWN, a row each, where the column had
    one cell holding the lot.

    The same edit a `*` typed into the header box makes, offered as a row
    because the star is a spelling a reader has no way to guess.
    """
    col: str

@dataclass(frozen=True, slots=True)
class UnsplatColumnClick:
    """User clicked Collapse lists to single cells, which takes the star back
    off: the elements come home to one cell holding the whole list.

    Its own event rather than a direction on SplatColumnClick, so a stale click
    means what it says -- a menu drawn before the column was splatted cannot
    unsplat it by arriving late.
    """
    col: str

@dataclass(frozen=True, slots=True)
class SubcolToggle:
    """User checked or unchecked one of a column's Subcolumns rows, which
    spreads that column's value ACROSS -- one drawn column per field, where the
    column itself had one cell holding the lot.

    Identified by the expression it is showing, like a Compute row, so one the
    user wrote themselves needs no event of its own.
    """
    col: str
    expr: str

@dataclass(frozen=True, slots=True)
class SubcolShowAll:
    """User clicked Show all, which spreads every field the column's values
    have."""
    col: str

@dataclass(frozen=True, slots=True)
class SubcolHideAll:
    """User clicked Hide all, which takes every sub-column away -- the ones
    they wrote as well as the ones detected, since the menu lists both -- and
    so gives the column back its own cell."""
    col: str

@dataclass(frozen=True, slots=True)
class SubcolExprInput:
    """User typed a sub-column of their own into the empty box at the foot of
    the Subcolumns submenu, or edited one already there."""
    col: str
    expr: str
    value: str

@dataclass(frozen=True, slots=True)
class SubcolExprKeyDown:
    """Enter or Escape in a box holding a sub-column expression. Its own event
    for the same reason ComputeExprKeyDown is."""
    pass

@dataclass(frozen=True, slots=True)
class SearchBoxInput:
    """User typed in the search box."""
    value: str

@dataclass(frozen=True, slots=True)
class FirstMatchToggle:
    """User toggled the 1st (first-match) button."""
    pass

@dataclass(frozen=True, slots=True)
class ActionButtonClick:
    """User clicked an action button."""
    action: str
    copy: bool

@dataclass(frozen=True, slots=True)
class DropdownToggle:
    """User toggled a dropdown menu (e.g. the ? menu)."""
    dropdown_id: str

@dataclass(frozen=True, slots=True)
class ExpandToggle:
    """Expand/collapse the table pane (only offered when the pane clips it)."""
    pass

@dataclass(frozen=True, slots=True)
class LoadMoreRows:
    """User clicked the Load more row, which draws another page of rows."""
    pass

@dataclass(frozen=True, slots=True)
class PinFocus:
    """A click on the collapsed repr a nested table draws, which exists only to
    be one.

    route_child_event pins focus on the first mousedown an unfocused child
    receives and drops the payload unread, so this has no case in `update` on
    purpose: by the time a table would handle its own events it is focused, and
    a focused table draws the table rather than the repr that sends this."""
    pass

@dataclass(frozen=True, slots=True)
class JoinSeparatorInput:
    """User typed in the custom separator text box in the Join dropdown."""
    value: str

@dataclass(frozen=True, slots=True)
class ToolSelect:
    """User clicked a tool button in the upper-right tool toolbar."""
    tool: str  # 'normal' | 'pick'

@dataclass(frozen=True, slots=True)
class PickToggle:
    """User clicked a pickable region while the pick tool is active.

    region_id is '{band}_{column}', where band is 'pre' / 'match' / 'post'
    (rows before the first match, the match row, rows after) and column is
    'idx' (the row-index column) or 'col_<n>' (an index into model['columns']).
    """
    region_id: str

@dataclass(frozen=True, slots=True)
class DeselectChildren:
    """User deselected all children of table."""
    pass

# === Command types ===

@dataclass(frozen=True, slots=True)
class CopyToClipboard:
    text: str

@dataclass(frozen=True, slots=True)
class ChangeSelectedText:
    expression: str
    suggested_var_name: Optional[str] = None

@dataclass(frozen=True, slots=True)
class ChangeSourceExpr:
    """Rewrite the expression the visualizer's own line is showing.

    Unlike ChangeSelectedText, which edits a line this visualizer wrote and
    tracks by decoration, this replaces an exact range of the user's own source
    -- the span the runner handed over (see visualize). A range rather than a
    line, so a `return xs` or an `if xs:` could never have its keyword eaten,
    and so a multi-line expression needs no special case.
    """
    expression: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int

@dataclass(frozen=True, slots=True)
class SelectGroupedComputeTab:
    grouped: bool

# === Saved config (the line's #%click comment) ===

def save_columns_config(path, exprs):
    """Path-scoped writer: persist a (sub-)table's column exprs at its location.

    `path` is the list of slot exprs from the root. Kept as the single write
    entry point so tests can patch it for isolation.
    """
    save_slots_at_path(path, exprs)


def _save_slots(model: dict) -> None:
    """Persist a table model's columns at its config path (preserves nested
    children of surviving columns and other branches already saved).

    Not for a table that has nowhere to be saved -- an answer the table worked
    out (see _answer_nesting_kwargs).
    """
    if not model.get('_config_persist', True):
        return
    save_columns_config(model.get('_config_path') or [],
                        _slots_from_columns(model.get('columns') or {}))


# A default that is not None, since None is a real element: a splat padded
# short gives its cell None, and "no scope given" has to mean something else.
_UNSET = object()


# === Rows ===

@dataclass(frozen=True)
class Row:
    """One rendered row, however the container gave it up.

    `key` identifies the row in `children` and in a cell key. It is the root
    row's number today; under splat a row inside a group is "3.1", so two
    rendered rows of one root row never collide on one column.

    `bindings` is what the suffixed dollars stand for in this row, as VALUES --
    the eval-side twin of the expression map the column helpers thread.

    A root row that splats a list occupies several rendered rows: the first of
    them carries `span_start`, and draws the cells of every column that did NOT
    splat, with `rowspan=span`.

    Under nesting a row belongs to one group PER DEPTH, so the width and the
    flag are tuples indexed by it: `spans[0]` is the whole root row, `spans[d]`
    the depth-*d* group this row sits in, and the innermost is always 1. A leaf
    draws at the depth it was splatted to -- `span_starts[d]` says whether this
    is the row that draws it, `spans[d]` how far down it reaches.
    """
    key: str          # identity in `children`; "3" alone, "3.1.2" under splat
    index: int        # the root row's number -- what `$i` binds and what the
                      # row-index <td> shows
    item: Any         # what bare `$` binds to
    bindings: dict    # {'i': 0} for a list; {'i', 'k', 'v'} for a dict
    span_starts: tuple = (True,)  # per depth: owns the rowspan cells there
    spans: tuple = (1,)           # per depth: how many rendered rows it covers
    splats: dict = field(default_factory=dict)  # splat column -> this row's element

    @property
    def span_start(self) -> bool:
        """The depth-0 flag, which is the only one a flat table has."""
        return self.span_starts[0] if self.span_starts else True

    @property
    def span(self) -> int:
        """The depth-0 width, which is the only one a flat table has."""
        return self.spans[0] if self.spans else 1

    def starts_at(self, depth: int) -> bool:
        """Whether this row draws a leaf splatted to *depth*. Past the nesting
        a row actually has, every row is its own group of one."""
        return self.span_starts[depth] if depth < len(self.span_starts) else True

    def span_at(self, depth: int) -> int:
        return self.spans[depth] if depth < len(self.spans) else 1


# === columns ==================================================================
#
# `columns` is an ordered map of column EXPRESSION -> that column's config:
#
#     {'$k': {}, '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}
#
# One structure rather than a list beside a parallel map, so the two can never
# drift. Duplicate columns are impossible by construction -- which is what a
# duplicate always should have been, since cell identity is the column
# expression and two identical columns were always one identity. Order is
# insertion order, which JSON round-trips.
#
# A column with nothing configured is `{}`, so the common case reads as a plain
# ordered set. `cols` (this table's sub-columns, same shape recursively) sits
# beside `children` (a nested VISUALIZER's own config, keyed by the cell's
# type): different axes, named separately, neither able to overwrite the other.
#
# Iteration, len(), list() and `in` all do the right thing on a dict already;
# only positional access and mutation need these.


def _as_columns(columns) -> dict:
    """The columns map, from either shape.

    A plain list of expressions is still what a caller outside this module is
    likely to hand over -- a test building a model literal, or a model
    persisted before columns became a map -- so it is accepted and converted
    rather than crashing somewhere further in. Duplicates collapse, which is
    the same answer the map gives everywhere else.
    """
    if isinstance(columns, dict):
        return columns
    out = {}
    for col in (columns or []):
        _col_add(out, col)
    return out


def _col_at(columns, index: int) -> 'str | None':
    """The column at a position, or None.

    For the places that genuinely count -- rename and remove within one map,
    and the aggregation rows, which are drawn column by column. An EVENT names
    its column instead (see _named_column): a position it was given could only be
    checked for being in range, and one out of date would land on whichever
    column had since taken that place. Negative indices are out of range here
    rather than counting back from the end, for the same reason.
    """
    if index is None or index < 0:
        return None
    keys = list(columns or [])
    return keys[index] if index < len(keys) else None


def _col_subs(columns, col: str) -> dict:
    """A column's sub-columns, in the same shape as `columns` itself."""
    if not isinstance(columns, dict):
        return {}
    return (columns.get(col) or {}).get('cols') or {}


def _col_add(columns, col: str, config=None) -> bool:
    """Append a column. False when it is already there -- a duplicate would be
    a second cell with the first one's identity."""
    if col in columns:
        return False
    columns[col] = dict(config or {})
    return True


def _col_insert(columns, col: str, index: int, config=None) -> bool:
    """Add a column at a position rather than at the end.

    What Add Column Before / After needs, and the one place a position is the
    point rather than a way of naming a column: the box was drawn in a gap
    between two headers, and that gap is where what it writes belongs. Past the
    end is the end, so an index that ran ahead of a column removed under the
    open box still adds the column somewhere rather than losing it.
    """
    if col in columns:
        return False
    keys = list(columns)
    keys.insert(max(0, min(index, len(keys))), col)
    columns[col] = dict(config or {})
    rebuilt = {k: columns[k] for k in keys}
    columns.clear()
    columns.update(rebuilt)
    return True


def _col_remove_at(columns, index: int) -> 'str | None':
    """Remove the column at a position and hand back its expression."""
    col = _col_at(columns, index)
    if col is not None:
        del columns[col]
    return col


def _col_rename_at(columns, index: int, new_col: str) -> bool:
    """Rename in place, keeping the position and the column's config.

    A dict has no in-place key rename, so the map is rebuilt in order. False
    when the new name is already taken, which would silently merge two columns.
    """
    old = _col_at(columns, index)
    if old is None or new_col == old:
        return False
    if new_col in columns:
        return False
    rebuilt = {(new_col if k == old else k): v for k, v in columns.items()}
    columns.clear()
    columns.update(rebuilt)
    return True


def _col_move(columns, frm: int, to: int) -> bool:
    """Reorder, keeping every column's config with it."""
    keys = list(columns)
    if not (0 <= frm < len(keys)) or not (0 <= to <= len(keys)):
        return False
    col = keys.pop(frm)
    keys.insert(to, col)
    rebuilt = {k: columns[k] for k in keys}
    columns.clear()
    columns.update(rebuilt)
    return True


def _slots_from_columns(columns) -> list:
    """The columns map as the slot list the saved config stores.

    A plain column stays a bare string, so a table with no splat saves exactly
    what it always did; only a splat carrying sub-columns needs the object
    form.
    """
    slots = []
    for col, config in (columns or {}).items():
        subs = (config or {}).get('cols') or {}
        slots.append({'expr': col, 'cols': _slots_from_columns(subs)}
                     if subs else col)
    return slots


def _columns_from_slots(exprs, slot_cols, depth: int = 0) -> dict:
    """Build the columns map from what the saved config gave up.

    Recursive, because a splat's sub-column may splat in turn and `cols` has
    the same shape as `columns` itself. Capped at MAX_SPLAT_DEPTH: the depth is
    bounded by the config rather than by the data, so it cannot run away the
    way a deep value can -- but a hand-edited comment is a real input, and a cap
    is cheaper than the header arithmetic going wrong.
    """
    columns = {}
    for expr in exprs:
        subs = slot_cols.get(expr) or []
        config = {}
        if subs and depth < MAX_SPLAT_DEPTH:
            config['cols'] = _sub_columns_from_entries(subs, depth + 1)
        _col_add(columns, expr, config)
    return columns


def _sub_columns_from_entries(entries, depth: int) -> dict:
    """A splat's sub-columns as the saved config stores them: a bare expression, or
    -- when the sub-column splats in turn -- one carrying `cols` of its own."""
    out = {}
    for entry in entries:
        if isinstance(entry, str):
            _col_add(out, entry, {})
            continue
        if not isinstance(entry, dict) or 'expr' not in entry:
            continue
        expr = entry['expr']
        config = {}
        nested = entry.get('cols')
        if nested and depth < MAX_SPLAT_DEPTH:
            config['cols'] = _sub_columns_from_entries(nested, depth + 1)
        _col_add(out, expr, config)
    return out


# A leaf's identity has to tell two splats' identically-named sub-columns
# apart, or one column's children overwrite the other's. It is never shown --
# LeafColumn.header carries the display text -- so a character no expression
# contains is enough.
SUBCOL_SEP = '\x01'


@dataclass(frozen=True)
class LeafColumn:
    """One drawn column, after the splat groups are flattened.

    `columns` stays the shape the user configured -- top-level exprs, with a
    splat's sub-columns stored beside them -- and everything that draws or
    computes goes through this expansion instead. A leaf under a splat reads
    its value off the splatted ELEMENT, which is what `sub` is written against.
    """
    expr: str          # identity: the cell key and the per-column config key
    splat: str | None  # the INNERMOST splat this lives under, or None -- which
                       # is the one whose element the leaf reads off
    sub: str | None    # the expression against one element; None when not split
    header: tuple      # the header path, one entry per header row
    chain: tuple = ()  # every splat above it, outermost first
    depth: int = 0     # which grouping level it draws at; len(chain)


@dataclass(frozen=True)
class ColumnGroup:
    """A top-level column and how many leaves it draws -- what a header cell
    has to span."""
    col: str
    width: int
    subs: tuple


def _column_groups(columns) -> list:
    """The top-level columns, each with the leaves it covers.

    The width is a count of LEAVES rather than of sub-columns: a sub-column
    that splats again expands further than the one cell its own entry suggests,
    so counting entries would leave the header cell too narrow for what is
    drawn under it.
    """
    groups = []
    for col in (columns or {}):
        subs = tuple(_col_subs(columns, col))
        width = len(_leaf_columns({col: (columns or {})[col]}))
        groups.append(ColumnGroup(col, max(width, 1), subs))
    return groups


def _sub_expr(col: str, path: tuple, chain: tuple) -> 'str | None':
    """The expression a leaf reads by, in the scope its innermost splat names:
    off the element, or off the ROW when no splat is above it.

    Every PLAIN ancestor under that splat is folded in, innermost first -- a
    sub-column of a plain column is read off whatever its parent reads, which
    is all a plain parent ever meant. None when there is nothing to fold and no
    splat either: the leaf's identity is its expression, as it always was.
    """
    below = []
    for ancestor in reversed(path):
        if _split_splat(ancestor)[0]:
            break
        below.append(ancestor)
    if not below and not chain:
        return None
    out = col
    for parent in below:
        out = _compose_sub(out, parent)
    return out


def _leaf_columns(columns, path: tuple = (), chain: tuple = ()) -> list:
    """Every drawn column, in order.

    A column with no sub-columns is its own leaf; a splat with none is one leaf
    showing the whole element. A column WITH sub-columns is not drawn itself --
    its subs are, one leaf each, every one of them read off that column's value.

    Two tuples rather than one, because the nesting and the row grouping are
    different axes. *path* is every ancestor, which is what the identity and
    the header are made of and what keeps two identically-named sub-columns
    apart. *chain* is the SPLAT ancestors alone, since only a splat spreads a
    value into rows: a plain parent adds a header level without adding a
    grouping level, which is exactly the difference between the two.
    """
    leaves = []
    for col in (columns or {}):
        is_splat = _split_splat(col)[0]
        # A bare list of expressions is still a legal `columns`, and carries no
        # sub-columns at all -- _col_subs is what knows both shapes.
        subs = _col_subs(columns, col)
        here_path = path + (col,)
        identity = f'{SUBCOL_SEP}'.join(here_path)
        if not subs:
            here = chain + (col,) if is_splat else chain
            leaves.append(LeafColumn(
                expr=identity,
                splat=here[-1] if here else None,
                # A splat with no sub-columns shows the element itself.
                sub='$' if is_splat else _sub_expr(col, path, chain),
                header=here_path,
                chain=here,
                depth=len(here)))
            continue
        leaves.extend(_leaf_columns(subs, here_path,
                                    chain + (col,) if is_splat else chain))
    return leaves


# A hand-edited comment is a real input, and nesting depth is bounded by the
# config rather than by the data -- so it cannot run away the way a deep value
# can, but a cap is still cheaper than the header arithmetic going wrong. It
# caps sub-columns of any kind, not just splats: the splat levels it bounds are
# one nesting each. Named for the splat because that is what first needed it.
MAX_SPLAT_DEPTH = 5


def _header_depth(columns) -> int:
    """How many header rows the table needs: one per grouping level, plus one
    for the columns themselves."""
    return max((len(leaf.header) for leaf in _leaf_columns(columns)), default=1)


@dataclass(frozen=True)
class HeaderCell:
    """One cell of the header, wherever the nesting puts it."""
    expr: str        # its identity, and what its ▾ menu acts on
    label: str       # the column expression this cell shows
    colspan: int
    rowspan: int
    is_leaf: bool    # a drawn column, rather than a splat covering others


def _header_cells(columns) -> list:
    """The header, row by row.

    A splat carrying sub-columns spans them across and hands the row below to
    them; anything else is a drawn column and spans DOWN to the bottom, so
    every header, however deep the table, ends flush with the body.
    """
    n = _header_depth(columns)
    rows = [[] for _ in range(n)]

    def walk(cols, chain, level):
        for col in (cols or {}):
            subs = _col_subs(cols, col)
            path = chain + (col,)
            expr = f'{SUBCOL_SEP}'.join(path)
            if subs:
                width = len(_leaf_columns({col: cols[col]}))
                rows[level].append(HeaderCell(expr, col, max(width, 1), 1, False))
                walk(subs, path, level + 1)
            else:
                rows[level].append(HeaderCell(expr, col, 1, n - level, True))

    walk(columns, (), 0)
    return rows


def _splat_elem_name(depth: int) -> str:
    """What the element of the depth-*d* splat binds to in a derived
    whole-column expression.

    `item`, like the row, because that is what it is -- one item of the list the
    splat spread. Numbered by NESTING LEVEL, with the root row as level one:
    `for item in data for item2 in item['members'] for item3 in ...`. The row
    already holds the bare name, and two levels binding the same one would leave
    the inner loop reading its own list.
    """
    return f'item{depth + 2}'


def _fresh_elem_name(depth: int, *avoid) -> str:
    """The depth's element name, stepped down a level at a time until it is one
    the expressions it will sit beside don't already bind.

    A column expression can be a comprehension of its own -- a sub-column moved
    out of a splat is exactly that -- and `for item2 in [f(item2) for item2 in
    v]` is correct Python that reads like a bug. Stepping down rather than
    inventing a name keeps every element called what its level calls it.
    """
    text = ' '.join(a for a in avoid if a)
    n = depth
    while re.search(rf'\b{_splat_elem_name(n)}\b', text):
        n += 1
    return _splat_elem_name(n)


def _leaf_spread(leaf: LeafColumn, source_expr: str,
                 binds: 'dict | None' = None) -> tuple:
    """How a leaf's splats spread, as `(clauses, lists_expr, elem)`.

    One `for` clause per splat in the CHAIN, not just the innermost: a leaf two
    splats deep is two levels of spreading. *lists_expr* is the innermost
    level's own list and *elem* the name its clause -- always the last one --
    binds, so a caller wanting that level gathered rather than spread can take
    `clauses[:-1]` and rebuild it.
    """
    clauses, elem, lists_expr = [], None, None
    for depth, splat in enumerate(leaf.chain or (leaf.splat,)):
        inner = _split_splat(splat)[1]
        if elem is None:
            # The outermost splat's own list, written in root-row scope -- `v`
            # for a dict's value column, `item['members']` for a list of
            # records -- under the header that binds the row it is read off.
            lists_expr = _column_item_expr(inner, source_expr, binds=binds)
            if lists_expr is None:
                # `*$` over a list: the row itself is the list to spread.
                lists_expr = _default_item_expr(binds)
            clauses.append(f'for {_column_binding(inner, source_expr, binds)}')
        else:
            # A nested splat is read off the element of the splat it is inside,
            # which is the same scope rule its sub-columns follow. _key_ rather
            # than _item_, because a nested `*$` IS that element and the None a
            # bare `$` answers with is a whole-column protocol, not this one.
            lists_expr = _column_key_expr(inner, source_expr, item_expr=elem,
                                          binds=binds)
        elem = _fresh_elem_name(depth, lists_expr, leaf.sub)
        clauses.append(f'for {elem} in {lists_expr}')
    return clauses, lists_expr, elem


def _leaf_elem_body(leaf: LeafColumn, source_expr: str, elem: str) -> str:
    """What one element of a leaf's innermost splat reads as.

    The sub-column is written against one element, so its bare `$` is that
    element -- substituted rather than formatted, so a `$` inside a string
    literal stays string content.
    """
    return (elem if leaf.sub in (None, '$')
            else replace_dollars_in_py_exp(leaf.sub,
                                           _column_dollars(source_expr, elem)))


def _leaf_values_expr(leaf: LeafColumn, source_expr: str,
                      binds: 'dict | None' = None) -> str:
    """Every value a leaf column has, as one expression.

    What the header hands to a drag and what the tally and the aggregations
    read. A leaf under a splat is the flattened comprehension -- the splat's
    list spread into the outer loop, the sub-column read off each element:

        [item2['who'] for v in d.values() for item2 in v]

    Flattening only the innermost of two levels doesn't merely write the wrong
    code -- over lists of lists it evaluates, and answers the inner lists
    instead of what the cells show.

        [item3['n'] for item in data for item2 in item['members']
                                     for item3 in item2['scores']]

    A leaf that isn't under a splat is the ordinary whole-column expression --
    of the composition when a plain parent carries it, since that is the column
    it is, and of the identity otherwise.
    """
    if leaf.splat is None:
        return _column_values_expr(leaf.sub or leaf.expr, source_expr, binds)
    clauses, _lists_expr, elem = _leaf_spread(leaf, source_expr, binds)
    return f'[{_leaf_elem_body(leaf, source_expr, elem)} {" ".join(clauses)}]'


def _split_splat_leaf(columns, target: str) -> 'LeafColumn | None':
    """The leaf a SPLIT splat would be, or None when the target isn't one.

    A splat carrying sub-columns is not a leaf -- its sub-columns are the drawn
    columns -- but its header still spans them and still hands something over.
    What it spans is the elements, which is exactly the leaf a splat with NO
    sub-columns already is: one level of flattening, so the two shapes agree
    about what the column's values are.
    """
    path = tuple(target.split(SUBCOL_SEP))
    if not _split_splat(path[-1])[0] or _leaf_for(columns or {}, target):
        return None
    chain = tuple(p for p in path if _split_splat(p)[0])
    return LeafColumn(expr=target, splat=path[-1], sub='$', header=path,
                      chain=chain, depth=len(chain))


def _leaf_lists_leaf(leaf: LeafColumn) -> LeafColumn:
    """A splat's own lists as a leaf of their own: the splat's inner expression
    read one level out, as a column of the scope its own parent names."""
    outer = leaf.chain[:-1]
    return replace(leaf, splat=outer[-1] if outer else None,
                   sub=_split_splat(leaf.chain[-1])[1], chain=outer,
                   depth=len(outer))


def _leaf_lists_expr(leaf: LeafColumn, source_expr: str,
                     binds: 'dict | None' = None) -> str:
    """A splat's own lists, unflattened -- `[item['pets'] for item in data]`
    beside the elements they spread into.
    """
    return _leaf_values_expr(_leaf_lists_leaf(leaf), source_expr, binds)


def _column_whole_expr(columns, col: str, source_expr: str,
                       binds: 'dict | None' = None) -> str:
    """Every value a column has, as one expression -- for any column.

    A leaf under a splat is keyed by a composed identity that means nothing on
    its own, so it is resolved through the leaf and flattened; everything else
    is the ordinary whole-column expression. The one place that choice is made,
    so a header, a tally and an aggregation cannot disagree about what a
    column's values are.

    Keyed on `columns` rather than on the model because the callers who most
    need it -- an aggregation cell answering for a child key -- hold the
    columns and no model at all.
    """
    leaf = _leaf_for(columns or {}, col) or _split_splat_leaf(columns, col)
    # A leaf under a plain parent is keyed by a composed identity too, and its
    # `sub` is the column it actually is -- so both kinds go through the leaf.
    if leaf is not None and (leaf.splat is not None or leaf.sub is not None):
        return _leaf_values_expr(leaf, source_expr, binds)
    return _column_values_expr(col, source_expr, binds)


def _column_header_exps(columns, col: str, source_expr: str,
                        binds: 'dict | None' = None) -> list:
    """What a column header hands over.

    A column of a LIST that nothing spread has the one reading and says nothing
    about it -- a label on a lone expression is a distinction with nothing to
    distinguish it from. Every other shape reads more than one way.

    Over a DICT every column reads twice, because a dict's rows have keys and
    the list reading is exactly the one that drops them. The keys are on the
    screen beside the values, so the dict they make is no less what the column
    is than the list is.

    Anything a splat spread reads two ways again: FLAT, which is the column as
    drawn -- one row per element, the levels above it collapsed into `for`
    clauses -- and AS LISTS, which is the shape the column was made out of and
    what each root row still holds. The flattened one leads, because that is
    what the header spans. The splat's own header reads as the lists it spread;
    a sub-column under it reads as one list of that sub-column per root row,
    which is that same question asked of a column that is drawn rather than of
    the splat itself. Over a dict both of those keep a keyed reading too -- a
    dict of lists reads back as a dict of lists, which is also the shape Group
    By made, for a column that got here that way.
    """
    flat = _column_whole_expr(columns, col, source_expr, binds)
    leaf = _leaf_for(columns or {}, col) or _split_splat_leaf(columns, col)
    is_dict = _is_dict_binds(binds)
    if leaf is None or leaf.splat is None:
        reads = _column_row_expr(columns, col) or col
        # The keys alone are the one column with nothing to key by: `{k: k
        # ...}` is the keys twice. Anything READ off the key still keys by it.
        if not is_dict or reads.strip() == '$k':
            return [PyExp(flat)]
        return [PyExp(flat, label='List'),
                PyExp(_column_dict_expr(reads, source_expr, binds),
                      label='Dict')]
    # The splat's header is about the lists themselves, so it reads through the
    # leaf they are; a sub-column is about itself, read per root row.
    is_splat = _split_splat(col.split(SUBCOL_SEP)[-1])[0]
    row_leaf = _leaf_lists_leaf(leaf) if is_splat else leaf
    lists = (_leaf_lists_expr(leaf, source_expr, binds) if is_splat
             else _column_values_expr(_leaf_row_expr(leaf), source_expr, binds))
    exps = [PyExp(flat, label='Flattened'), PyExp(lists, label='As lists')]
    if is_dict:
        # Per ROOT row rather than one level out, whatever the depth: the root
        # keys are the only keys there are, so a deeper level stays a list
        # inside the value it belongs to.
        exps.append(PyExp(_column_dict_expr(_leaf_row_expr(row_leaf),
                                            source_expr, binds),
                          label='Dict of lists'))
    return exps


def _cell_inner_exps(columns, row_expr: str, source_expr: str,
                     binds: 'dict | None', sub_expr: str) -> list:
    """What a value drawn INSIDE a cell also reads as: the same reach, applied
    to every row.

    A column header answers that question for the cell -- `[item['n'] for item
    in x]` -- but a tuple element or an object field drawn inside a cell has no
    header of its own, and the one on screen names the cell rather than what is
    in it. So a cell hands its child the way to ask, and the child composes its
    own sub-expression onto the column on the way down; ask it with `$` and the
    answer is the column's own reading.

    Handed to `_column_header_exps` rather than built here, so a value inside a
    cell and the header of the column it would be cannot disagree -- and so a
    dict's second, keyed reading comes along without this knowing about it.
    """
    return _column_header_exps(columns, compose_dollar_expr(sub_expr, row_expr),
                               source_expr, binds)


def _cell_every_row(columns, col_row_expr, source_expr, binds,
                    outer_every_row, cell_is_row):
    """The callback a cell hands its child: every way a value inside it reads.

    This table's own answer first -- the same reach down THIS list -- and then,
    when this table is itself a cell, the same question asked of the table
    above, with the cell's own path composed in. A tuple two tables deep gets
    both: its element down the inner list, and that same element down the
    outer one.

    None when there is nothing to say, so a caller can test it and skip the
    kwarg entirely.
    """
    if col_row_expr is None and (outer_every_row is None or not cell_is_row):
        return None

    def readings(sub_expr):
        out = []
        if col_row_expr is not None:
            out += list(_cell_inner_exps(columns, col_row_expr, source_expr,
                                         binds, sub_expr))
        if outer_every_row is not None and cell_is_row:
            # One list per outer row, so it says so: two rows of the tooltip
            # both called `List` would be a distinction with nothing in it.
            out += [e._replace(label=e.label or 'List of lists')
                    for e in (r if isinstance(r, PyExp) else PyExp(r)
                              for r in outer_every_row(_mapped_over_rows(sub_expr)))]
        return out

    return readings


def _map_over_rows_code(code: str) -> str:
    """A child's generated code, asked of every row of the table it came from.

    The reading half of this is _mapped_over_rows; this is the code half, and
    the difference is only what stands for the value -- a binder on the way up
    rather than a dollar. Kept beside it so the tooltip and the column the
    button writes cannot drift apart.
    """
    elem = _fresh_elem_name(0, code)
    return (f'[{code.replace(CHILD_SOURCE_BINDER, elem)} '
            f'for {elem} in {CHILD_SOURCE_BINDER}]')


def _mapped_over_rows(sub_expr: str) -> str:
    """*sub_expr*, asked of every row of the list it was written against.

    What a nested table hands the table above. Reaching by POSITION -- the same
    index in each outer row -- is the wrong generalization for anything derived:
    a count made in one cell of an inner table is a count of THAT element, and
    every row's answer is a count per element, not the count of its fourth. So
    the inner list is mapped rather than indexed, and the result is one list per
    outer row.

    `$` stays the inner list, which is what the table above composes its column
    onto. The element binds by the same rule a splat's does, stepped past any
    name the expression already uses (see _fresh_elem_name), so the two
    comprehensions that end up nested don't both say `item`.
    """
    elem = _fresh_elem_name(0, sub_expr)
    return f'[{replace_dollars_in_py_exp(sub_expr, [elem])} for {elem} in $]'


def _column_row_expr(columns, col: str) -> 'str | None':
    """A column as one row reads it, or None when the target has 0..n values
    per row rather than one.

    A plain column is itself. A sub-column of a plain column is the composition
    its leaf already carries, since that is the column it actually is. Anything
    under -- or being -- a splat spreads into rows instead of having one value
    per row, and answers None: what makes Sort and Group By go inert there
    rather than write code that cannot run.

    The row-scoped half of the pair whose other half is _column_whole_expr.
    A leading star is not enough to recognise a splat by, either: a splat
    nested under a plain column is keyed `$['a']\x01*$['b']` and hasn't got
    one, so the question goes through the leaf.
    """
    if _split_splat(col)[0]:
        return None
    leaf = _leaf_for(columns or {}, col)
    if leaf is None:
        # Not a drawn column: a split splat's own menu target, or a plain
        # column carrying sub-columns -- which is still read once per row.
        return None if SUBCOL_SEP in col else col
    return None if leaf.splat is not None else (leaf.sub or leaf.expr)


def _is_leaf_identity(col: str) -> bool:
    """Whether a column key is a leaf's identity rather than an expression --
    a composed sub-column key, or a splat, neither of which means anything on
    its own and both of which are read through the leaf."""
    return SUBCOL_SEP in col or _split_splat(col)[0]


def _leaf_for(columns, expr: str) -> 'LeafColumn | None':
    """The leaf a composed column key names, or None.

    Walks that key's own path down `columns` rather than expanding the whole
    table and looking for a match: the key IS the path -- _leaf_columns joins
    it with SUBCOL_SEP, which no expression can contain -- so the answer is a
    few steps rather than a sweep. It is asked once per column by the header
    and again by everything the header asks, so a sweep here costs the table's
    width squared, which a wide table pays in seconds.

    The leaf it builds is _leaf_columns' own, made the same way from the same
    three things: the ancestors, the splats among them, and whether the column
    it lands on carries sub-columns (in which case it isn't drawn, and so isn't
    a leaf).
    """
    if not expr:
        return None
    path = tuple(expr.split(SUBCOL_SEP))
    cols = columns
    chain = ()
    for depth, col in enumerate(path):
        if not cols or col not in cols:
            return None
        if _col_subs(cols, col):
            # Not drawn itself: its sub-columns are the leaves. Only an
            # ancestor of the key can carry them.
            if depth == len(path) - 1:
                return None
            if _split_splat(col)[0]:
                chain += (col,)
            cols = _col_subs(cols, col)
            continue
        if depth != len(path) - 1:
            return None
        here = chain + (col,) if _split_splat(col)[0] else chain
        return LeafColumn(
            expr=expr,
            splat=here[-1] if here else None,
            sub=('$' if _split_splat(col)[0]
                 else _sub_expr(col, path[:depth], chain)),
            header=path,
            chain=here,
            depth=len(here))
    return None


def _leaf_cell_value(leaf: LeafColumn, row: Row, lst, source_expr=None,
                     eval_in_scope=None, read_through: bool = False):
    """One cell's value, for the row in hand.

    A leaf under a splat shows the ELEMENT this rendered row stands for --
    already worked out when the group was built -- with the leaf's own
    expression read off it when the splat carries sub-columns. Anything else is
    the column read off the row, through the source when that can be
    re-evaluated for free (see _is_pure_ref) and off the row itself otherwise.

    One description of it rather than three: the render, the child models
    init_model builds for those cells, and the lookup a child event comes back
    through all have to agree, and a child model built for one value and then
    asked about another goes wrong quietly.

    The row's whole binding map either way, rather than the splat's own `j`
    alone: `_leaf_cell_expr` writes the row NUMBER into the code the same cell
    hands to a drag, so a `$i` sub-column under a splat would otherwise show an
    error beside an expression that evaluates. Everything a rendered row knows
    about itself is in one place, and both sides read that place.
    """
    if leaf.splat is not None:
        element = row.splats.get(leaf.splat)
        if leaf.sub in (None, '$') or element is None:
            return element
        return eval_dollar_expr(leaf.sub, element, eval_in_scope, outer=(lst,),
                                bindings=row.bindings)
    reads = leaf.sub or leaf.expr
    if read_through and eval_in_scope is not None and source_expr is not None:
        return eval_in_scope(_column_cell_expr(reads, source_expr, row.index, lst))
    return eval_dollar_expr(reads, row.item, eval_in_scope, outer=(lst,),
                            bindings=row.bindings)


def _leaf_cell_expr(leaf: LeafColumn, source_expr: str, row: Row,
                    container=None, from_end: bool = False) -> str:
    """One cell of a leaf column, naming its row -- and, under a splat, its
    element -- concretely.

    What the cell hands to a drag, and what a child's own generated code is
    rebound through on the way to the clipboard. A splat cell names the ELEMENT
    it is showing rather than the starred column: the star is a display
    instruction, and what the user drags into their file has to be the value
    under the cursor.

        data[0]['pets'][1]['kind']

    The row key carries a position per splat level ("0.1.2"), so a leaf two
    splats deep is subscripted twice -- each level written against the element
    above it, which is the same scope rule the values follow.
    """
    if leaf.splat is None:
        return _column_cell_expr(leaf.sub or leaf.expr, source_expr,
                                 row.index, container, from_end)
    binds, _item_expr = _cell_binds(source_expr, row.index, container, from_end)
    positions = row.key.split('.')[1:]
    out = None
    for depth, splat in enumerate(leaf.chain):
        inner = _split_splat(splat)[1]
        if out is None:
            lists_expr = _column_cell_expr(inner, source_expr, row.index,
                                           container, from_end)
        else:
            lists_expr = replace_dollars_in_py_exp(
                inner, _column_dollars(source_expr, out), bindings=binds)
        j = positions[depth] if depth < len(positions) else 0
        out = f'{_atomize(lists_expr)}[{j}]'
    if leaf.sub in (None, '$'):
        return out
    return replace_dollars_in_py_exp(
        leaf.sub, _column_dollars(source_expr, out),
        bindings={**binds, 'j': str(row.bindings.get('j', 0))})


def _leaf_values(leaf: LeafColumn, lst, model, eval_in_scope=None) -> list:
    """Every value a leaf column has, in row order.

    Through the source expression when there is one, so the numbers on screen
    come from the same code the header hands over; otherwise off the rows in
    hand, which is what an unnamed list has to fall back to.
    """
    source_expr = _cell_source_expr(model, eval_in_scope)
    if source_expr is not None and eval_in_scope is not None:
        try:
            return list(eval_in_scope(
                _leaf_values_expr(leaf, source_expr, _binds_for(lst))))
        except Exception:
            pass
    if leaf.splat is None:
        # Nothing spread it into rows, so the composition is read off each row
        # the way any other column is.
        values = []
        for row in _rows(lst, model.get('columns') or {}):
            try:
                values.append(eval_dollar_expr(
                    leaf.sub or leaf.expr, row.item, eval_in_scope,
                    outer=(lst,), bindings=row.bindings))
            except Exception:
                pass
        return values
    values = []
    for row in _rows(lst, model.get('columns') or {}):
        element = row.splats.get(leaf.splat)
        if element is None:
            continue
        try:
            # The row's own bindings, as _leaf_cell_value reads them: a column
            # naming `$j` or `$i` has a value per row like any other, and one
            # gathered without them would quietly come back short.
            values.append(element if leaf.sub in (None, '$')
                          else eval_dollar_expr(leaf.sub, element,
                                                eval_in_scope, outer=(lst,),
                                                bindings=row.bindings))
        except Exception:
            pass
    return values


def _root_rows(value) -> list:
    """One Row per row of the container, before any splat."""
    if isinstance(value, dict):
        return [Row(str(n), n, (k, v), {'i': n, 'k': k, 'v': v}, (True,), (1,))
                for n, (k, v) in enumerate(value.items())]
    return [Row(str(i), i, item, {'i': i}, (True,), (1,))
            for i, item in enumerate(value)]


def _splat_columns(columns) -> list:
    """The columns carrying a `*`, in order."""
    return [c for c in (columns or []) if _split_splat(c)[0]]


def _splat_value(col: str, row: Row, container, scope=_UNSET) -> list | None:
    """The list a splat column produces for one row, or None when it produces
    something that isn't a list -- which splats to a single row, since there is
    nothing to spread.

    *scope* is what the splat's own `$` reads: the row's item for a top-level
    splat, and the enclosing splat's ELEMENT for one nested inside another,
    which is the same rule a sub-column already follows.
    """
    _is_splat, inner = _split_splat(col)
    item = row.item if scope is _UNSET else scope
    try:
        value = eval_dollar_expr(inner, item, outer=(container,),
                                 bindings=row.bindings)
    except Exception:
        return None
    return value if isinstance(value, list) else None


def _splat_elements(lst, columns, target: str) -> list:
    """Every element the splat a target names spreads, across the rows.

    What its own + asks about: a row here is the whole list a splat holds, and
    what a sub-column reads is one element of it -- so the fields to suggest
    are the elements', not the rows'.

    A top-level splat reads off the row and can be sampled without expanding
    anything; a nested one reads off the element of the splat it is inside,
    which is what the expanded rows already carry.
    """
    chain = target.split(SUBCOL_SEP)
    if len(chain) == 1:
        rows = [_row_at(lst, i) for i in _sample_indices(lst)] if lst else []
    else:
        rows = _rows(lst, columns)
    out = []
    for row in rows:
        scope = _UNSET if len(chain) == 1 else row.splats.get(chain[-2])
        if scope is None:
            continue
        out.extend(_splat_value(chain[-1], row, lst, scope) or [])
    return out


def _splat_levels(columns) -> list:
    """The splat chains by depth: level *d* holds every chain of *d+1* splats
    the columns reach, outermost first.

    All the chains at one level expand together -- they zip and pad against
    each other the way two top-level splats always have -- so the row count
    stays linear in the rows actually drawn rather than multiplying out.
    """
    chains = [leaf.chain for leaf in _leaf_columns(columns) if leaf.chain]
    levels = []
    for d in range(1, MAX_SPLAT_DEPTH + 1):
        at_d = list(dict.fromkeys(c[:d] for c in chains if len(c) >= d))
        if not at_d:
            break
        levels.append(at_d)
    return levels


def _rows(value, columns=None) -> list:
    """Every rendered row of a container, in order.

    A root row whose splat columns produce lists occupies one rendered row per
    element. Two splats zip and pad -- aligned by position, the short one blank
    -- so the group is as long as the longest of them and the row count stays
    linear in the data.

    A root row with no splat, an empty one, or one whose splat isn't a list
    still gets exactly one rendered row: a row must not vanish from the table
    for holding an empty list.
    """
    roots = _root_rows(value)
    levels = _splat_levels(columns)
    if not levels:
        return roots

    out = []
    for root in roots:
        group = _expand_row(root, value, levels, 0)
        out.extend(_stamp_span(group, 0))
    return out


def _shown_rows(model: dict) -> int:
    """How many leading root rows this table is drawing.

    Undeclared in the model defaults, the way `expanded` is: it is one page
    until the Load more row has been clicked, and every reader asks for it the
    same way rather than the model carrying a number nobody has chosen yet.
    """
    return model.get('shown_rows', ROWS_PER_PAGE)


def _hidden_rows(n_rows: int, shown: int) -> 'tuple | None':
    """The root rows a table leaves out, as `[start, stop)`, or None when it
    draws all of them.

    The window is over ROOT rows rather than rendered ones: a root row that
    splatted a list is drawn whole or not at all, or the rowspans of the columns
    that did NOT splat would reach past the rows still there.

    None whenever the gap would be empty -- a table a row or two over the page
    size has nothing between its head and its tail worth hiding, so it draws
    itself rather than offering to load two rows it is already holding back.
    """
    stop = n_rows - TAIL_ROWS
    return (shown, stop) if stop > shown else None


def _stamp_span(group: list, depth: int) -> list:
    """Tell every row of one group how wide that group is and which row starts
    it, at *depth*. Prepended, because a group is worked out from the inside
    out but read from the outside in."""
    return [replace(row,
                    spans=(len(group),) + row.spans,
                    span_starts=(n == 0,) + row.span_starts)
            for n, row in enumerate(group)]


def _expand_row(row: Row, container, levels: list, level: int) -> list:
    """One row spread into the rows its splats at *level* and below make of it.

    Returns them with the spans for every depth BELOW this one already stamped;
    the caller stamps its own. A row whose splats give nothing to spread -- no
    list, or an empty one -- still gets exactly one rendered row, because a row
    must not vanish from the table for holding an empty list.
    """
    if level >= len(levels):
        return [row]
    lists = {}
    for chain in levels[level]:
        col = chain[-1]
        # A nested splat reads off the element of the splat it is inside; a
        # top-level one reads off the row itself.
        scope = row.splats.get(chain[-2]) if len(chain) > 1 else _UNSET
        if scope is None:
            continue
        lists[col] = _splat_value(col, row, container, scope)
    width = max((len(v) for v in lists.values() if v is not None), default=0)
    if width == 0:
        return [row]
    out = []
    for j in range(width):
        # `$j` is the position within the INNERMOST group. `$i` stays the ROOT
        # row's number, so it rowspans like any other unsplatted value; the
        # flat rendered position and the outer groups' get no sigil, because
        # nothing in the data addresses them and no generated code binds them.
        child = replace(
            row,
            key=f'{row.key}.{j}',
            bindings={**row.bindings, 'j': j},
            splats={**row.splats,
                    **{c: (v[j] if v is not None and j < len(v) else None)
                       for c, v in lists.items()}},
        )
        out.extend(_stamp_span(_expand_row(child, container, levels, level + 1),
                               level + 1))
    return out


def _row_by_key(value, columns, row_key: str) -> Row:
    """The row a cell key names.

    Under splat two rendered rows of one root row have different values for the
    same leaf column, so the key is what distinguishes them and int() is not
    enough -- int("3.1") raises. A key with no dot is a root row and is reached
    without building the rest.
    """
    if '.' not in row_key:
        return _row_at(value, int(row_key))
    for row in _rows(value, columns):
        if row.key == row_key:
            return row
    raise KeyError(row_key)


def _row_at(value, i: int) -> Row:
    """One row without building the rest -- for the per-cell and sampling
    paths, which are the reason `_rows` must not be the only way in.

    islice is O(i) and stateless, and stays that way deliberately. An id()-keyed
    memo is not a safe alternative: a dict freed mid-render can have its address
    recycled and hand back another dict's items, and pinning the value to fix
    that means holding a strong reference to arbitrary user data in module state
    that nobody clears across init_model / visualize / update in a long-lived
    runner -- and it would still go stale on in-place mutation. A weakref-keyed
    one isn't available either: weakref.ref({}) raises TypeError. The only
    caller that cares about cost is _sample_indices, whose whole job is to touch
    at most ~12 rows.
    """
    if isinstance(value, dict):
        k, v = next(itertools.islice(value.items(), i, None))
        return Row(str(i), i, (k, v), {'i': i, 'k': k, 'v': v}, (True,), (1,))
    return Row(str(i), i, value[i], {'i': i}, (True,), (1,))


# === Column autocomplete helpers ===

def _sample_indices(lst):
    """Return a sorted set of representative row positions for sampling.

    The one caller that cares what _row_at costs: its whole job is to name at
    most ~12 rows, so an O(i) islice per row is not worth memoizing away.

    Drawn from a generator made here rather than from `random`'s own, and
    seeded from the length so that the same list always samples the same rows.
    The module-level generator belongs to the user: the runner seeds it once
    before their body so that their file gives under Sculpt-n-Code what plain
    python gives after a `random.seed(...)`, and visualizers run in between
    their statements -- so a draw taken from it here would land in the middle
    of their stream and shift every value after it. By an amount that moves,
    too: how many rows get sampled depends on the size of the table, on
    whether a cached model let init_model be skipped this run, and on whether
    a menu that asks what columns it could offer happens to be open."""
    indices = {0}
    if len(lst) > 1:
        indices.add(len(lst) - 1)
    if len(lst) > 2:
        middle = list(range(1, len(lst) - 1))
        indices.update(random.Random(len(lst)).sample(middle, min(10, len(middle))))
    return sorted(indices)


def _collect_fields_from_samples(lst, get_visualizer, require_all=False):
    """Collect the union of fields from sampled list items.

    If require_all is True, returns None when any sampled item lacks get_fields.
    Otherwise skips items without get_fields.
    """
    # Detecting a dict's columns is its own thing -- the key alongside the
    # values' fields -- and arrives with the column expressions. A dict's row
    # is a pair the table makes up rather than a value it holds, so there is
    # nothing here to sample the fields OF; it declines detection and takes the
    # ['$'] fallback rather than borrowing the list shape, which would address
    # it wrong rather than merely plainly.
    if isinstance(lst, dict):
        return None if require_all else []

    if not lst:
        return [] if not require_all else None

    columns = []
    seen = set()

    for idx in _sample_indices(lst):
        item = _row_at(lst, idx).item
        vis = get_visualizer(item)
        item_get_fields = getattr(vis, 'get_fields', None)
        if item_get_fields is None:
            if require_all:
                return None
            continue
        fields = item_get_fields(item)
        if fields is None:
            if require_all:
                return None
            continue
        for field in fields:
            if field not in seen:
                seen.add(field)
                columns.append(field)

    return columns


def _get_all_possible_columns(lst, get_visualizer):
    """Get union of all possible fields from sampled items in the list."""
    return _collect_fields_from_samples(lst, get_visualizer, require_all=False)


def _get_column_suggestions(lst, get_visualizer, current_columns, input_value):
    """Return autocomplete suggestions: possible columns not already shown, filtered by prefix."""
    all_cols = _get_all_possible_columns(lst, get_visualizer)
    existing = set(current_columns)
    suggestions = [c for c in all_cols if c not in existing]
    if input_value:
        suggestions = [c for c in suggestions if c.startswith(input_value)]
    return suggestions


# === Search parsing ===

_IMPLICIT_DOLLAR_RE = re.compile(
    r'^\s*(?:'
    r'>=|<=|!=|==|>|<'
    r'|in\b'
    r'|not\s+in\b'
    r'|is\s+not\b'
    r'|is\b'
    r'|\.'
    r')'
)


def needs_implicit_dollar(search: str) -> bool:
    """True if search text starts with a binary operator, meaning $ should be prepended."""
    return bool(_IMPLICIT_DOLLAR_RE.match(search))


SPLAT = '*'


def _split_splat(col: str) -> tuple:
    """(is_splat, the expression under it).

    A `*` prefix, evocative of `*my_list`: the column's value is a list, and
    its items become rows. The star has to LEAD -- `$ * 2` is arithmetic -- and
    `*$` is a SyntaxError in eval mode, so the sigil can never collide with a
    legitimate column expression. For that same reason every validator has to
    take it off before asking whether the rest parses.
    """
    text = col.strip()
    if text.startswith(SPLAT):
        return (True, text[len(SPLAT):].strip())
    return (False, text)


def _is_valid_python_expression(s: str) -> bool:
    is_splat, inner = _split_splat(s)
    if is_splat:
        # `*` alone splats nothing.
        return bool(inner) and dollar_expr_parses(inner)
    return dollar_expr_parses(s)


def parse_search_term(search: str | None) -> tuple | None:
    """Parse search into (kind, term) or None.

    Returns ('slice', (start, stop)) for slice expressions.
    Returns ('expr', text) for everything else.
    """
    if not search:
        return None
    for i, ch in enumerate(search):
        if ch == ':':
            left = search[:i]
            right = search[i + 1:]
            left_ok = (left == '' or _is_valid_python_expression(left))
            right_ok = (right == '' or _is_valid_python_expression(right))
            if left_ok and right_ok:
                return ('slice', (left, right))
    return ('expr', search)


# =============================================================================
# Per-column search
# =============================================================================
#
# Each column can carry its own search, edited in that column's ▾ menu as
#
#     [and|or] [>= > == != < <= in "not in" (code)] (text)
#
# The text is written in COLUMN scope, one level deeper than the main search
# box: $ is the column value (not necessarily the row, since a column can be
# computed), $$ is the row item, $$$ is the array.
#
# Nothing here filters rows or generates code. Every active column search is
# lifted into the main search box's scope and folded into one search string,
# which the existing matching and code generation then handle unchanged. That
# also makes the composition visible and editable as text.

COLUMN_SEARCH_OPS = ['>=', '>', '==', '!=', '<', '<=', 'in', 'not in', '']
COLUMN_SEARCH_COMPOSE = ['and', 'or']

# These two want a collection on the right, so choosing one hands the user the
# brackets rather than making them type both halves (see the op event handler).
COLUMN_SEARCH_MEMBERSHIP_OPS = ('in', 'not in')
COLUMN_SEARCH_COLLECTION_HINT = '[]'

# `exclude` belongs to the tally rather than the search row proper: which values
# are selected is read back out of `op` and `text`, but Exclude can be ticked
# before any value is picked, and then there is no operator to hold it.
_COLUMN_SEARCH_DEFAULT = {'compose': 'and', 'op': '==', 'text': '',
                          'exclude': False}

# An empty collection is the shape of a search, not a search: it's what's left
# when the brackets have been handed over but not filled in.
_EMPTY_COLLECTION_RE = re.compile(r'^(?:\[\s*\]|\(\s*\)|\{\s*\})$')

# Nodes that bind tighter than any operator, so a column expression built from
# one needs no parentheses when it is substituted into a predicate. Notably NOT
# ast.Tuple: `1, 2` parses as one but doesn't survive being nested.
_ATOMIC_NODES = (ast.Name, ast.Constant, ast.Call, ast.Subscript, ast.Attribute,
                 ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp,
                 ast.SetComp, ast.JoinedStr)


def _parse_dollar_expr(expr: str):
    """Parse a dollar-bearing expression, or None if it doesn't parse.

    Dollar runs stand in for values, so they're collapsed to a placeholder name
    (the same trick dollar_expr_parses uses) before parsing. `$i` collapses to
    `i` instead, which is what generated code calls the row's number -- so a
    question asked of the shape of the tree (_pick_needs_index) gets the same
    answer whether the index was written as `$i` or picked off the index column.
    The other sigils are values like any other, so they collapse like one.
    """
    try:
        collapsed = DOLLARS_RE.sub(lambda m: 'i' if m[2] == 'i' else '_crt_',
                                   expr)
        return ast.parse(collapsed, mode='eval').body
    except SyntaxError:
        return None


def _atomize(expr: str) -> str:
    """Parenthesize an expression unless it already binds tighter than any
    operator, so `len($)` composes as-is while `$ + 1` gets wrapped.

    An expression that doesn't parse is left alone: parens can't rescue it, and
    the user still has to recognize their own text in the main search box.
    """
    node = _parse_dollar_expr(expr)
    if node is None or isinstance(node, _ATOMIC_NODES):
        return expr
    return f'({expr})'


def _is_predicate_function(text: str, eval_in_scope=None) -> bool:
    """Whether a dollar-free column search names a function to call on $.

    A bare name or dotted name is the only shape that qualifies. When there's a
    scope to ask, it settles whether the name is a function (`isOdd`) or a value
    that stands on its own (`threshold`); without one, the shape decides.
    """
    node = _parse_dollar_expr(text)
    if not isinstance(node, (ast.Name, ast.Attribute)):
        return False
    if eval_in_scope is None:
        return True
    try:
        return callable(eval_in_scope(text))
    except Exception:
        # An unresolvable name is more useful read as a predicate: the error
        # surfaces as "no matches" instead of "matches everything".
        return True


def column_search_predicate(op: str, text: str, eval_in_scope=None) -> str | None:
    """One column search row as a predicate in column scope ($ = the column
    value), or None when the row is inactive.

    An operator alone is not a search: with no text there is nothing to compare
    against, whatever the dropdown says.
    """
    text = (text or '').strip()
    if not text or _EMPTY_COLLECTION_RE.match(text):
        return None
    if op:
        return f'$ {op} {text}'
    # Blank operator: the text is the whole predicate.
    if DOLLARS_RE.search(text):
        return text
    if needs_implicit_dollar(text):
        return f'${text.lstrip()}' if text.lstrip().startswith('.') else f'$ {text}'
    if _is_predicate_function(text, eval_in_scope):
        return f'{text}($)'
    return text


def lift_column_predicate(pred: str, col_expr: str) -> str:
    """Rewrite a column-scope predicate into item scope (what the main search
    box speaks): $ becomes the column expression, and every longer dollar run
    loses a level, so $$ (the item) becomes $ and $$$ (the array) becomes $$.

    Every sigil crosses untouched. None names a scope -- the column value and
    the row it was read off share one row number, one key, one position -- so
    there is no level for any of them to lose.
    """
    depth = max((len(m[1]) for m in DOLLARS_RE.finditer(pred)), default=1)
    # Substituted in two passes via dollar-free placeholders:
    # replace_dollars_in_py_exp tells code dollars from string-literal dollars by
    # re-parsing with the run restored, and a replacement that itself contains
    # dollars never parses -- which would make every run after the first look
    # like code even inside a string.
    holders = [f'_snc_lift{n}_' for n in range(1, depth + 1)]
    sigil_holders = {s: f'_snc_lift{s}_' for s in SIGILS}
    out = replace_dollars_in_py_exp(pred, holders, bindings=sigil_holders)
    for n, holder in enumerate(holders, start=1):
        out = out.replace(holder, _atomize(col_expr) if n == 1 else '$' * (n - 1))
    for sigil, holder in sigil_holders.items():
        out = out.replace(holder, f'${sigil}')
    return out


def _paren_if_loose(term: str) -> str:
    """Parenthesize a term whose top level would swallow a surrounding `and`."""
    node = _parse_dollar_expr(term)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return f'({term})'
    if isinstance(node, (ast.IfExp, ast.Lambda, ast.NamedExpr)):
        return f'({term})'
    return term


def _searchable_targets(columns) -> list:
    """Every column a search can be written on, as (target, expression) pairs.

    Keyed by the TARGET, because that is what the search is stored under and
    what the box was typed into; lifted through the EXPRESSION, because that is
    the column as one row reads it. The two are the same string until a column
    carries sub-columns.

    A target that spreads its value into rows is left out: a predicate on it
    would match no rows and quietly empty the table. Everything else comes in
    menu-target order, so every drawn column has its box.
    """
    columns = _as_columns(columns)
    pairs = []
    for target in _menu_targets(columns):
        reads = _column_row_expr(columns, target)
        if reads is not None:
            pairs.append((target, reads))
    return pairs


def compose_column_searches(columns, column_searches, eval_in_scope=None,
                            leftovers=None) -> str | None:
    """Fold every active column search into one main-search string.

    The `and` columns form a group in column order; the `or` columns are then
    or'd against it. Parentheses appear only where Python's precedence would
    otherwise read the result differently, so a lone column search comes out as
    exactly what the user typed.

    *leftovers* are the terms of a hand-written search that no column claimed
    (see decompose_search). Each names the group it was written in and where it
    sat among that group's terms, so a search the columns can only half explain
    still composes back the way it was written.
    """
    searches = column_searches or {}
    and_terms, or_terms = [], []
    for col, reads in _searchable_targets(columns):
        row = searches.get(col)
        if not row:
            continue
        pred = column_search_predicate(row.get('op', ''), row.get('text', ''),
                                       eval_in_scope)
        if not pred:
            continue
        term = lift_column_predicate(pred, reads)
        # A row that never said how it composes composes the way every other
        # default does. Only `or` is a choice; `and` is what not choosing means,
        # so a row built without the key reads as one rather than crashing here.
        compose = row.get('compose') or 'and'
        (or_terms if compose.lower() == 'or' else and_terms).append(term)

    # Ascending, so each index is read against the terms already in place --
    # which is the list the index was recorded against.
    for row in sorted(leftovers or [], key=lambda row: row.get('index') or 0):
        # Verbatim, spacing and all: a leftover is the user's own text, and the
        # only reason it is kept is to hand it back exactly as they wrote it.
        term = row.get('text') or ''
        if not term.strip():
            continue
        compose = row.get('compose') or 'and'
        group = or_terms if compose.lower() == 'or' else and_terms
        index = row.get('index')
        group.insert(len(group) if index is None else max(0, min(index, len(group))),
                     term)

    if not and_terms and not or_terms:
        return None
    # Parens only ever keep a join from reading a term differently, so a term
    # with nothing to be joined to stands exactly as it was written.
    if len(and_terms) > 1 or (and_terms and or_terms):
        group = ' and '.join(_paren_if_loose(t) for t in and_terms)
    else:
        group = and_terms[0] if and_terms else ''
    if not or_terms:
        return group
    # `and` binds tighter than `or`, so a single-term group needs no parens.
    if len(and_terms) > 1:
        group = f'({group})'
    return ' or '.join(([group] if and_terms else []) + or_terms)


# =============================================================================
# Reading the main search back into the columns
# =============================================================================
#
# The other direction. A search typed into the main box is read back as the
# column rows that would have written it, so both ends of the same filter say
# the same thing -- and so the tally, which reads its checkmarks out of those
# rows, lights up for a search that was typed by hand.
#
# Nothing is rewritten to make a reading work: one is only accepted when
# composing it back produces the search character for character. What no column
# claims is kept as a leftover -- verbatim, and in the place it was written --
# so the terms the columns can't express survive the next column edit instead of
# being silently dropped. Every search therefore reads back as something, in the
# worst case as one leftover holding the whole of it.

# Underscores stand in for the dollars while the search is parsed: one per
# dollar, so every offset the parse reports still points at the same character
# (and the same utf-8 byte) of the search itself.
def _underscore_dollars(text: str) -> str:
    return DOLLARS_RE.sub(lambda m: '_' * len(m[0]), text)


def _parse_search(text: str):
    """The search as an expression node, or None if it isn't one."""
    try:
        return ast.parse(_underscore_dollars(text), mode='eval').body
    except (SyntaxError, ValueError):
        return None


def _node_source(text: str, node) -> str | None:
    """The slice of *text* a node was parsed from, or None if it spans lines.

    Column offsets count utf-8 bytes, so the slice is taken in bytes too.
    """
    if getattr(node, 'lineno', 1) != 1 or getattr(node, 'end_lineno', 1) != 1:
        return None
    return text.encode()[node.col_offset:node.end_col_offset].decode()


def _search_readings(node, search: str) -> List[Tuple[List[str], List[str]]]:
    """Every way the search might have been composed, as (and terms, or terms),
    most terms first.

    The coarser readings follow the finer ones rather than replacing them: an
    `and` is as likely to be one column's search that says `and` as it is to be
    two columns joined, and only composing a reading back settles which.
    """
    def terms(nodes):
        return [_node_source(search, n) for n in nodes]

    readings = []
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        first, *rest = node.values
        # The and group leads, so only the first term can hold one.
        if isinstance(first, ast.BoolOp) and isinstance(first.op, ast.And):
            readings.append((terms(first.values), terms(rest)))
        readings.append((terms([first]), terms(rest)))
        readings.append(([], terms(node.values)))
    elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        readings.append((terms(node.values), []))
    readings.append(([search], []))
    return [r for r in readings if all(r[0] + r[1])]


# A character no keyboard produces, so marking with it can't collide with the
# search's own text.
_UNLIFT_MARK = '\x00'


def unlift_term(term: str, col: str) -> str | None:
    """The column-scope predicate a term of the main search would have been
    lifted from, or None when the column has no part in it.

    The inverse of lift_column_predicate: the column expression becomes $ again,
    and every dollar already in the term gains back the level it lost. A sigil
    had no level to lose, so it stays where it is -- run deepened, suffix kept,
    which is why this reads the two halves apart rather than the whole token.
    """
    atom = _atomize(col)
    if atom not in term:
        # A column that doesn't appear can't be what the term is about --
        # without this, `$['name']` would read `$ == 3` as a search on the row.
        return None
    marked = term.replace(atom, _UNLIFT_MARK)
    deepened = DOLLARS_RE.sub(
        lambda m: m[0] if m[2] else '$' * (len(m[1]) + 1), marked)
    pred = deepened.replace(_UNLIFT_MARK, '$')
    # Substituting on sight is a guess -- a column expression can turn up in a
    # term it didn't come from -- so it only counts if it lifts back verbatim.
    return pred if lift_column_predicate(pred, col) == term else None


def _search_row_from_predicate(pred: str, eval_in_scope=None) -> dict | None:
    """A column-scope predicate as the [op] + text that would have written it.

    The operator form is preferred over the blank one: the tally reads its
    checkmarks out of the operator, so a search that compares has to come back
    as a comparison rather than as one opaque expression.
    """
    node = _parse_search(pred)
    if node is None:
        # Half-typed text is not a column's search; it belongs to the box it was
        # typed into until it is an expression.
        return None
    if (isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.left, ast.Name) and node.left.id == '_'):
        for op in COLUMN_SEARCH_OPS:
            # Longer operators are offered first, so `>=` is never read as `>`.
            if op and pred.startswith(f'$ {op} '):
                text = pred[len(op) + 3:]
                if column_search_predicate(op, text, eval_in_scope) == pred:
                    return {'op': op, 'text': text}
                break
    if column_search_predicate('', pred, eval_in_scope) == pred:
        return {'op': '', 'text': pred}
    return None


def _claim_term(term: str, targets, first: int, used, eval_in_scope=None):
    """The column a term belongs to, as (column index, target, row) -- or None
    when no column claims it.

    Only columns from *first* on are eligible: a group is composed in column
    order, so a term can't belong to a column an earlier term already went past.
    Among the columns that fit, the longest expression wins, which is the most
    specific reading -- `$['a'] == 1` is the a column's search, not the row's.

    *targets* are (target, expression) pairs: the term is read against the
    expression, and claimed under the target it is stored by.
    """
    best, best_len = None, -1
    for index in range(first, len(targets)):
        col, reads = targets[index]
        if col in used:
            continue
        pred = unlift_term(term, reads)
        if pred is None:
            continue
        row = _search_row_from_predicate(pred, eval_in_scope)
        if row is not None and len(reads) > best_len:
            best, best_len = (index, col, row), len(reads)
    return best


def _read_terms(and_terms, or_terms, targets, eval_in_scope=None):
    """Hand each term to a column, keeping the ones nothing claims."""
    searches, leftovers, used = {}, [], set()
    for compose, terms in (('and', and_terms), ('or', or_terms)):
        first = 0
        for index, term in enumerate(terms):
            claim = _claim_term(term, targets, first, used, eval_in_scope)
            if claim is None:
                leftovers.append({'compose': compose, 'text': term,
                                  'index': index})
                continue
            col_index, col, row = claim
            first = col_index + 1
            used.add(col)
            searches[col] = {'compose': compose, **row}
    return searches, leftovers


def decompose_search(search: str | None, columns,
                     eval_in_scope=None) -> Tuple[dict, List[dict]]:
    """Read the main search box back as (column searches, leftovers).

    The reading that lights up the most columns wins, among those that compose
    back to exactly the search that was read.
    """
    if not search:
        return ({}, [])
    node = _parse_search(search)
    readings = _search_readings(node, search) if node is not None else [([search], [])]
    targets = _searchable_targets(columns)
    best = None
    for and_terms, or_terms in readings:
        searches, leftovers = _read_terms(and_terms, or_terms, targets,
                                          eval_in_scope)
        if compose_column_searches(columns, searches, eval_in_scope,
                                   leftovers) != search:
            continue
        if best is None or len(searches) > len(best[0]):
            best = (searches, leftovers)
    # Whatever is left unread is one term the columns don't explain, which
    # composes back verbatim -- the box keeps exactly what was typed into it.
    return best or ({}, [{'compose': 'and', 'text': search, 'index': 0}])


# The rows are keyed by column EXPRESSION, like _slot_children and the cell
# children, so reordering columns can't scramble which search belongs to which.

def _menu_targets(columns) -> list:
    """What a column event's index names, in order.

    The leaves first -- so a table with no sub-columns has exactly the index
    space it always had, and nothing about lists or plain dicts moves -- then
    one entry per splat that carries sub-columns. A split splat is not a leaf
    (its sub-columns are the drawn columns), but it is still a column: it can
    be renamed, removed and reordered, and its own group header points here.
    """
    targets = [leaf.expr for leaf in _leaf_columns(columns)]
    targets += [cell.expr for row in _header_cells(columns) for cell in row
                if not cell.is_leaf]
    return targets


def _menu_target_at(columns, index: int) -> 'str | None':
    if index is None or index < 0:
        return None
    targets = _menu_targets(columns)
    return targets[index] if index < len(targets) else None


def _drawn_positions(columns) -> dict:
    """Where each menu target sits horizontally: the index of the leftmost
    drawn column at or under it.

    `_menu_targets` orders by kind -- every leaf, then the parents that span
    them -- because that is the order an index named them in. Left to right is
    a different order, and a column carrying sub-columns is last in the first
    one however far left it is drawn. A parent sits where its first sub-column
    sits, which is where its header starts.
    """
    positions = {}
    for i, leaf in enumerate(_leaf_columns(columns)):
        parts = leaf.expr.split(SUBCOL_SEP)
        for n in range(1, len(parts) + 1):
            # setdefault: an ancestor keeps the first sub-column that claimed it.
            positions.setdefault(SUBCOL_SEP.join(parts[:n]), i)
    return positions


def _parent_of(columns, target: str) -> 'str | None':
    """The column a target lives under, or None when it is top-level."""
    if SUBCOL_SEP not in target:
        return None
    return target.split(SUBCOL_SEP, 1)[0]


def _subs_at(columns, target: str, create: bool = False) -> 'dict | None':
    """The sub-columns of the column a target names, or None when there is no
    such column -- which is what a stale index has to mean.

    A column carries no `cols` until something is put in it, since an empty one
    would read as a column that draws nothing; so the map is made on the way in
    for a caller that is about to add, and only then.
    """
    node = columns
    for name in target.split(SUBCOL_SEP):
        if not isinstance(node, dict):
            return None
        config = node.get(name)
        if not isinstance(config, dict):
            return None
        subs = config.get('cols')
        if subs is None:
            if not create:
                return None
            subs = config['cols'] = {}
        node = subs
    return node


def _add_derived_column(model, cell_col: str, expr: str) -> None:
    """Code made in a cell, as a column of the table.

    A cell's expression is one every row answers, so code derived from it is a
    column. A cell under a splat shows one ELEMENT, though, so code derived
    from that is a column of the ELEMENTS -- a sub-column of the splat rather
    than a column of the table, which is the scope it was written in and the
    only one it reads correctly in.
    """
    columns = model['columns']
    leaf = _leaf_for(columns, cell_col)
    if leaf is None or leaf.splat is None:
        _col_add(columns, expr)
        return
    path = cell_col.split(SUBCOL_SEP)
    # A splat drawing its own column is its new sub-column's parent; a
    # sub-column's parent is whatever it is itself a sub-column of.
    parent = (cell_col if path[-1] == leaf.splat
              else SUBCOL_SEP.join(path[:-1]))
    subs = _subs_at(columns, parent, create=True)
    _col_add(columns if subs is None else subs, expr)


def _subcol_candidates(col: str, lst, model, get_visualizer,
                       eval_in_scope=None) -> list:
    """The fields the Subcolumns submenu offers to spread a column into.

    Of whatever a sub-column of it would be READ against: the element for a
    splat, which spread its list over rows and whose subs are written against
    one of them, and the cell's own value for any other column. Sampled and
    unioned by the same helper the table's own + uses, so a field means the
    same thing wherever it is offered.
    """
    if get_visualizer is None:
        return []
    if _split_splat(col)[0]:
        values = _splat_elements(lst, model.get('columns') or {}, col)
    else:
        values = _column_values(col, lst, model, eval_in_scope)
    return _get_all_possible_columns(values, get_visualizer) or []


def _is_splat_column(col: str) -> bool:
    """Whether a column spreads its value down the rows -- read off its own
    last segment, since a splat nested under a plain column leads with the
    parent and has no star at the front to recognise it by."""
    return _split_splat(col.split(SUBCOL_SEP)[-1])[0]


def _restarred(col: str) -> str:
    """What a column is called on the other side of the star: the last segment
    with one added, or with the one it has taken off."""
    is_splat, inner = _split_splat(col.split(SUBCOL_SEP)[-1])
    return inner if is_splat else SPLAT + col.split(SUBCOL_SEP)[-1]


def _star_name_free(col: str, model) -> bool:
    """Whether the name on the other side of the star is going spare.

    Both spellings can be on screen at once -- a splat beside the column of
    lists it spread -- and a rename onto a name a sibling has would merge the
    two, taking one of them away without saying so. Asked before either row is
    drawn, so the menu offers no move that cannot be made.
    """
    siblings = _siblings_of(model.get('columns') or {}, col)
    return siblings is not None and _restarred(col) not in siblings


def _can_expand_column(col: str, lst, model, eval_in_scope=None) -> bool:
    """Whether Expand list items into rows has anything to do to *col*.

    Its cells have to be lists -- there is nothing to spread down otherwise --
    and it cannot already be a splat, whose cells are the elements it spread
    and which has no second star to gain.

    Sampled off the column's own values, the way the Subcolumns submenu samples
    them, so both rows of the menu are asking about the same thing.
    """
    if _is_splat_column(col) or not _star_name_free(col, model):
        return False
    return _rows_are_lists(_column_values(col, lst, model, eval_in_scope))


def _can_collapse_column(col: str, model) -> bool:
    """Whether Collapse lists to single cells has anything to do to *col*.

    Nothing to sample: a splat is spreading a list by the fact of being one, so
    being one is the whole question.
    """
    return _is_splat_column(col) and _star_name_free(col, model)


def _restar_column(model, col: str, eval_in_scope=None) -> 'str | None':
    """Move a column across the star, and hand back what it is called now.

    A rename, so the column keeps its place and everything keyed to it that
    still means something. Its sub-columns are not among those: on one side
    they are read off the whole list and on the other off one element, so the
    same text asks a different question either way it is crossed. They go, and
    each caller puts back what belongs on the side it landed.

    Nothing is torn down until the rename is known to be good, so a stale click
    on a name a sibling has taken leaves the column exactly as it was.
    """
    if not _star_name_free(col, model):
        return None
    columns = model.get('columns') or {}
    for expr in list(_subs_at(columns, col) or {}):
        _drop_subcolumn(model, col, expr, eval_in_scope)
    # The last one out takes the map with it: a column carries no `cols` until
    # something is put in it (see _subs_at), so one left empty here would be
    # the only plain column in the table wearing the shape of a parent.
    config = _siblings_of(columns, col).get(col)
    if isinstance(config, dict) and config.get('cols') == {}:
        del config['cols']
    if not _rename_column(model, col, _restarred(col), eval_in_scope):
        return None
    return SUBCOL_SEP.join(col.split(SUBCOL_SEP)[:-1] + [_restarred(col)])


def _expand_column_into_rows(model, col: str, lst, get_visualizer=None,
                             eval_in_scope=None) -> None:
    """Splat a column of lists, and open it with the sub-columns a table of its
    ELEMENTS would open with.

    A lone `$` is no sub-column at all: a splat with none already shows the
    element itself, so it would be the same cell drawn one row further down.
    """
    target = _restar_column(model, col, eval_in_scope)
    if target is None:
        return
    exprs = _default_columns(
        _splat_elements(lst, model['columns'], target), get_visualizer)
    if exprs != ['$']:
        subs = _subs_at(model['columns'], target, create=True)
        for expr in exprs:
            _col_add(subs, expr)
    _save_columns(model)


def _collapse_column_into_cells(model, col: str, eval_in_scope=None) -> None:
    """Take the star off a splat, giving the column back one cell holding the
    whole list.

    Nothing takes the sub-columns' place: `single cells` is the whole of what
    this promises, and spreading the list ACROSS on the way back would be the
    expansion again sideways. The rules that fill a new splat are one click
    away in Subcolumns for a reader who wants them.
    """
    if _restar_column(model, col, eval_in_scope) is not None:
        _save_columns(model)


# The (+) menu offers two kinds of column, in two sections, because Show all
# and Hide all reach one of them and not the other.
#
# The FIELDS are what this table's rows turn out to have -- detected, so they
# differ from table to table, and "show every field" is exactly what Show all
# means. That section is the one the pair acts on, and it is drawn directly
# under them.
#
# The ROW columns ask about the row itself rather than about anything read off
# it. They are true of every table rather than found in one, so a user asking
# for the fields is asking about neither, in either direction: ticking one is a
# separate thought and unticking it is another. They sit ABOVE Show all and Hide
# all, under Add Column, so that nothing between the pair and the list they
# reach is something they don't.


def _table_field_candidates(lst, get_visualizer) -> list:
    """The fields the (+) menu offers to show, which is what Show all reaches.

    What the box's autocomplete suggests -- so a field means the same thing
    whether it is ticked here or typed there. A dict's are its key alongside its
    VALUES' fields, since a dict's row is a pair and there is no tuple
    visualizer to ask for a pair's; that is `_dict_value_columns`, the same
    answer detection opened the table with.

    Unioned rather than required of every row (which is what detection asks,
    and why a ragged list opens as a single `$` column): a field only some rows
    have is still a column worth offering, and one that isn't there reads as a
    hole rather than an error.
    """
    if get_visualizer is None:
        return []
    if isinstance(lst, dict):
        fields = _dict_value_columns(lst, get_visualizer)
    else:
        fields = _get_all_possible_columns(lst, get_visualizer) or []
    # A `get_fields` is free to name the value it was asked about or to write
    # the length itself, and a column offered in both sections would be a row
    # that unticks the box the other one ticked. The row section is the one that
    # keeps it: that is where a reader is told these two are not Show all's.
    row_cols = set(_table_row_candidates(lst))
    return [f for f in fields if f not in row_cols]


def _table_row_candidates(lst) -> list:
    """The columns the (+) menu offers about the ROW rather than about a field
    read off it. Their own section at the top, which Show all and Hide all both
    leave alone.

    `$` always. It is the row itself, so it is nothing detection could turn up
    or fail to -- every table has it, whatever its rows are made of, and a list
    of numbers whose only column is `$` needs it here or Hide all would take
    away the one column the menu could put back.

    `len($)` where the rows have a length -- `len($v)` over a dict, whose row is
    a pair and so is two long whatever is in it; the VALUE is the thing with an
    interesting size, which over the dict of lists Group By writes is how big
    each group is. Asked of the values rather than of a visualizer, because
    having a length is a fact about the object rather than about how it draws.

    One sampled row with a length is enough, by the rule a field only some rows
    have goes by: the column means something wherever it is defined, and reads
    as a hole where it isn't. An empty container has no row to ask, so it is not
    offered one -- and must not be sampled, since row 0 of nothing is an error
    rather than an absence.
    """
    if not lst:
        return ['$']
    is_dict = isinstance(lst, dict)
    for idx in _sample_indices(lst):
        row = _row_at(lst, idx)
        if hasattr(row.bindings['v'] if is_dict else row.item, '__len__'):
            return ['$', 'len($v)' if is_dict else 'len($)']
    return ['$']


def _drop_subcolumn(model, col: str, expr: str, eval_in_scope=None) -> None:
    """Take one sub-column away, and everything that was keyed to it.

    A leaf is a column: it can have been searched on, and asked to compute --
    both keyed by the identity it had, which nothing else will ever answer to
    once it is gone. The same clean-up Remove Column does, for the same reason.
    """
    subs = _subs_at(model.get('columns') or {}, col)
    if subs is None or expr not in subs:
        return
    del subs[expr]
    target = f'{col}{SUBCOL_SEP}{expr}'
    _remove_column_children(model, target)
    _remove_column_search(model, target)
    _remove_column_compute(model, target)
    _recompose_search(model, eval_in_scope)


def _save_columns(model) -> None:
    """Persist a change to which columns the table has."""
    _save_slots(model)


def _save_subcolumns(model, col: str) -> None:
    """Persist a change to a column's sub-columns -- which is a change to the
    columns, since that is the one record of a sub-column."""
    _save_columns(model)


def _menu_id(kind: str, col: str) -> str:
    """The id of one of a column's menus or chips -- which names the COLUMN,
    not where it sits.

    Positions move under the menu that is open on them: a column that gains its
    first sub-column stops being a leaf, and the leaves come first in the target
    space. An id that moved with it would leave the open menu drawn on some
    other column, and would take the focus off a box the moment the first
    character typed into it added the column that did the moving.

    These ids are compared in Python and never reach the DOM -- the front end
    finds a panel by where it sits in the markup -- so an expression names one
    as well as a number does, and says which column it means.
    """
    return f'{kind}-{col}'


def _remove_target(columns, target: str) -> bool:
    """Remove a column, wherever it lives."""
    parent = _parent_of(columns, target)
    if parent is None:
        if target not in columns:
            return False
        del columns[target]
        return True
    subs = _col_subs(columns, parent)
    sub = target.split(SUBCOL_SEP, 1)[1]
    if sub not in subs:
        return False
    del subs[sub]
    return True


def _drop_column(model: dict, target: str, eval_in_scope=None) -> bool:
    """Take a column away, and everything that was keyed to it.

    A column's identity is its expression, and its children, its search and its
    aggregations are all keyed by it -- so removing one without them leaves
    state nothing will ever answer to again. The one description of what
    removing a column means, for the ▾ menu's own row and for the Compute box
    that takes its column back off the table.
    """
    if not _remove_target(model['columns'], target):
        return False
    _remove_column_children(model, target)
    _remove_column_search(model, target)
    _remove_column_compute(model, target)
    _recompose_search(model, eval_in_scope)
    return True


def _rename_column(model: dict, old: str, new: str, eval_in_scope=None) -> bool:
    """Rewrite a column in place, keeping its position and carrying what was
    keyed to it over.

    The search was written against the old expression, so it goes with it; the
    aggregations describe the column rather than filtering it, so they follow it
    over. The one description of what renaming a column means -- for the header
    box, for Enter in it, and for a level typed into a per-group answer.
    """
    if old == new or not _rename_target(model['columns'], old, new):
        return False
    _rename_column_children(model, old, new)
    _remove_column_search(model, old)
    _rename_column_compute(model, old, new)
    _recompose_search(model, eval_in_scope)
    return True


def _rename_target(columns, target: str, new_name: str) -> bool:
    """Rename a column in place, keeping its position and whatever it lives
    under. False when the name is taken among its own siblings."""
    parent = _parent_of(columns, target)
    if parent is None:
        index = list(columns).index(target) if target in columns else None
        return False if index is None else _col_rename_at(columns, index, new_name)
    subs = _col_subs(columns, parent)
    sub = target.split(SUBCOL_SEP, 1)[1]
    if sub not in subs or new_name in subs:
        return False
    index = list(subs).index(sub)
    return _col_rename_at(subs, index, new_name)


# A run left as written can't be a replacement (it wouldn't re-parse, and then
# every token after it would look like code) -- so the root row goes in as a
# placeholder and becomes a dollar afterwards, the two-pass idiom used wherever
# a substitution has to produce dollars.
_PROMOTE_ROOT = '_snc_root_'


def _promote_expr(sub: str, splat_col: str, elem: str = None) -> str:
    """A sub-column's expression, read per ROOT ROW instead of per element.

    Out of the splat the column is read once per root row, and the root row has
    a LIST where the sub had one element -- so the sub is applied across it.
    Inside the splat `$` was the element and `$$` the root row; outside, the
    element has no name and the root row is `$`.

    *elem* is the name to bind the element to, the outermost level's by default.
    Only a caller coming out of more than one splat needs to say: the levels
    nest, and two of them binding the same name would leave the inner one
    reading its own list.
    """
    inner = _split_splat(splat_col)[1]
    elem = elem if elem is not None else _fresh_elem_name(0, sub, inner)
    body = replace_dollars_in_py_exp(sub, [elem, _PROMOTE_ROOT])
    body = body.replace(_PROMOTE_ROOT, '$')
    return f'[{body} for {elem} in {inner}]'


def _leaf_row_expr(leaf: LeafColumn) -> str:
    """A leaf column as one ROOT row reads it: the one value for a leaf nothing
    spread into rows, and the LIST of them for one under a splat.

    What a row aggregation's row shows in a splat column. That row is one row of
    the list, and a splat column of one row is every value the splat spread out
    of it -- so the cell shows the list rather than nothing, or one arbitrary
    element of it.

    Not the same question as _column_row_expr, which asks whether the column has
    ONE value per row -- Sort and Group By need that and a list will not do.
    """
    expr = leaf.sub or leaf.expr if leaf.splat is None else (leaf.sub or '$')
    for depth in range(len(leaf.chain) - 1, -1, -1):
        expr = _promote_expr(expr, leaf.chain[depth], _splat_elem_name(depth))
    return expr


# The sub's own dollar goes in as a placeholder too, for the same reason the
# root row does: the parent expression it becomes has dollars of its own, and a
# replacement carrying one would be read again on the next pass.
_COMPOSE_PARENT = '_snc_parent_'


def _compose_sub(sub: str, parent: str) -> str:
    """A sub-column of a PLAIN column, as the ordinary column it is.

    Nothing spread it into rows, so the sub is simply read off what the parent
    reads: `$[0]` under `$.split(',')` is the column `$.split(',')[0]`. Inside
    the parent `$` was its value and `$$` the row; outside, the value has no
    name and the row is `$` -- the same scope rule a splat's sub-column
    follows, which is why the two compose the same way and differ only in what
    coming back OUT has to build (see _promote_expr).
    """
    out = replace_dollars_in_py_exp(sub, [_COMPOSE_PARENT, _PROMOTE_ROOT])
    return out.replace(_COMPOSE_PARENT, _atomize(parent)).replace(
        _PROMOTE_ROOT, '$')


def _adopt_expr(col: str) -> 'str | None':
    """A top-level column's expression, read per PARENT VALUE inside another
    column -- the splatted element of a splat, the cell value of a plain one.

    Inside, `$` is the parent's value and `$$` the root row, so every dollar
    run deepens by one -- the same substitution `unlift_term` performs. Which
    kind of parent it is makes no difference here: both bind `$` to what the
    parent reads, and a column being dragged in was written against the row.

    None when the column names a suffixed dollar. Suffixes bind at depth 1
    only, so `$k` would deepen to `$$k`, which names nothing by design; the
    drag is refused rather than turned into an expression that evaluates to
    silence.
    """
    if dollar_expr_sigils(col):
        return None
    # Through the substitution rather than a raw regex, so a `$` that is string
    # content stays string content. unlift_term deepens with a bare regex and
    # gets away with it only because its round-trip check rejects a bad
    # reading; there is no such check here.
    depth = max((len(m[1]) for m in DOLLARS_RE.finditer(col)), default=0)
    if depth == 0:
        return col
    holders = [f'_snc_deep{n}_' for n in range(1, depth + 1)]
    out = replace_dollars_in_py_exp(col, holders)
    for n, holder in enumerate(holders, start=1):
        out = out.replace(holder, '$' * (n + 1))
    return out


def _move_target(columns, from_target: str, to_target: str) -> bool:
    """Move a column to where another one lives, rewriting it on the way.

    Four cases, and only the two that cross a parent boundary rewrite anything:
    reordering within one parent is a reorder, and moving between two parents
    keeps `$` meaning the parent's value either way.

    Which rewrite is the parent's business rather than the splat's. Going IN
    always deepens, since `$` is the parent's value under any parent and the
    column being moved was written against the row. Coming OUT is where the two
    part: a splat spread its value over rows and has to collect it back into a
    list, where a plain column's was never spread and simply composes.
    """
    from_parent = _parent_of(columns, from_target)
    to_parent = _parent_of(columns, to_target)

    def _siblings(parent):
        return columns if parent is None else _col_subs(columns, parent)

    def _name(target):
        return target.split(SUBCOL_SEP, 1)[1] if SUBCOL_SEP in target else target

    src_map, dst_map = _siblings(from_parent), _siblings(to_parent)
    name = _name(from_target)

    if from_parent == to_parent:
        keys = list(src_map)
        if name not in keys:
            return False
        return _col_move(src_map, keys.index(name), keys.index(_name(to_target)))

    if from_parent is not None and to_parent is None:
        moved = (_promote_expr(name, from_parent)
                 if _split_splat(from_parent)[0]
                 else _compose_sub(name, from_parent))
    elif from_parent is None and to_parent is not None:
        moved = _adopt_expr(name)
    else:
        # Parent to parent: `$` is the parent's value on both sides.
        moved = name
    if moved is None or moved in dst_map:
        return False

    config = src_map.pop(name, None)
    _col_add(dst_map, moved, config)
    # Land it where it was dropped rather than at the end.
    keys = list(dst_map)
    _col_move(dst_map, len(keys) - 1, keys.index(_name(to_target)))
    return True


def _named_row_column(model: dict, col: 'str | None') -> 'str | None':
    """A named target as one row reads it -- _named_column and _column_row_expr
    in one, which is what every row-scoped menu action needs.

    None when the target is gone AND when it has no one value per row, so a
    click arriving from a panel drawn before the columns changed answers the
    same way the panel would have drawn.
    """
    target = _named_column(model, col)
    return (None if target is None
            else _column_row_expr(model.get('columns') or {}, target))


def _named_column(model: dict, col: 'str | None') -> 'str | None':
    """The column an event names, or None when the table no longer has it.

    Events carry the column's own expression rather than where it sat, so an
    event from a render the table has moved on from either names a column that
    is still there -- and means it -- or names nothing and does nothing. A
    position could only ever be checked for being in range, which is why a
    stale one used to land on whoever had taken that place.
    """
    if not isinstance(col, str):
        return None
    return col if col in _menu_targets(model.get('columns') or {}) else None


# Which side of which column the open box sits on, as one string, since
# `adding_column` is where that box is and a second key could come to disagree
# with it. True is the box the (+) opens, which goes at the far right and needs
# no column to say so. A character of its own rather than SUBCOL_SEP's: the
# column named is an identity, and a nested one already holds that separator.
ADD_ANCHOR_SEP = '\x03'


def _add_anchor(model: dict) -> 'tuple | None':
    """The column the open box was asked for and which side of it it sits on,
    or None when it is the far-right box the (+) opens.

    Says nothing about whether that column is still there -- see
    _add_beside_target, which asks.
    """
    at = model.get('adding_column')
    if not isinstance(at, str) or ADD_ANCHOR_SEP not in at:
        return None
    side, _, col = at.partition(ADD_ANCHOR_SEP)
    return (col, side == 'after')


def _add_anchor_value(col: str, after: bool) -> str:
    return f'{"after" if after else "before"}{ADD_ANCHOR_SEP}{col}'


def _add_beside_target(model: dict) -> 'tuple | None':
    """The anchor, once the table has been asked whether it still has it.

    An anchor names its column like every other column event, so one from a
    render the table has moved on from means nothing -- and the box falls back
    to the far right rather than throwing away what the user has typed.
    """
    anchor = _add_anchor(model)
    if anchor is None:
        return None
    target = _named_column(model, anchor[0])
    return None if target is None else (target, anchor[1])


def _siblings_of(columns, target: str) -> 'dict | None':
    """The map a column lives in: the table's own columns for a top-level one,
    its parent's `cols` for a sub-column, and None when there is no such column.

    Off the LAST separator rather than the first, so a sub-column of a
    sub-column is looked for where it actually sits.
    """
    path = target.split(SUBCOL_SEP)
    if len(path) == 1:
        return columns
    return _subs_at(columns, SUBCOL_SEP.join(path[:-1]))


def _add_beside(model: dict, expr: str) -> bool:
    """Put a new column in where the open box was drawn.

    Among the anchor's own SIBLINGS, which is what makes the row over a
    sub-column add a sub-column: the box sits in that column's header row, and
    a column of the table would be drawn somewhere the box never was.
    """
    columns = model['columns']
    beside = _add_beside_target(model)
    if beside is None:
        return _col_add(columns, expr)
    target, after = beside
    siblings = _siblings_of(columns, target)
    if siblings is None:
        return _col_add(columns, expr)
    return _col_insert(siblings, expr,
                       list(siblings).index(target.split(SUBCOL_SEP)[-1])
                       + (1 if after else 0))


def _add_box_leaf(model: dict, columns) -> 'tuple | None':
    """Where the open box sits among the DRAWN columns: which leaf it is drawn
    in front of, and how deep it hangs.

    The header cell is one thing and the space under it another -- the cells
    below have to leave the box a column's worth of room, or every column right
    of it slides off the values it names. None when there is nothing to leave
    room for: no box, the far-right one, or one past the last column, which has
    nothing to its right to push.
    """
    beside = _add_beside_target(model)
    if beside is None:
        return None
    target, after = beside
    leaves = _leaf_columns(columns)
    covered = [i for i, leaf in enumerate(leaves)
               if leaf.expr == target or leaf.expr.startswith(target + SUBCOL_SEP)]
    if not covered:
        return None
    at = covered[-1] + 1 if after else covered[0]
    if at >= len(leaves):
        return None
    # A new column has no splat of its own, so it is drawn at the depth its
    # ancestors put it at -- one grouping level per splat above it.
    path = target.split(SUBCOL_SEP)
    depth = sum(1 for name in path[:-1] if _split_splat(name)[0])
    return (at, depth)


def _column_search_row(model: dict, col: str) -> dict:
    """A column's search row, defaulted for display."""
    return {**_COLUMN_SEARCH_DEFAULT, **((model.get('column_searches') or {}).get(col) or {})}


def _column_search_active(model: dict, col: str, eval_in_scope=None) -> bool:
    """Whether a column is actually filtering (a row with no text is not)."""
    row = (model.get('column_searches') or {}).get(col)
    if not row:
        return False
    return column_search_predicate(row.get('op', ''), row.get('text', ''),
                                   eval_in_scope) is not None


def _set_column_search(model: dict, col: str, **fields) -> None:
    searches = dict(model.get('column_searches') or {})
    row = {**_COLUMN_SEARCH_DEFAULT, **(searches.get(col) or {}), **fields}
    if row == _COLUMN_SEARCH_DEFAULT:
        searches.pop(col, None)
    else:
        searches[col] = row
    model['column_searches'] = searches or None


def _remove_column_search(model: dict, col: str) -> None:
    searches = dict(model.get('column_searches') or {})
    searches.pop(col, None)
    model['column_searches'] = searches or None


def _column_computes(model: dict, col: str) -> List[str]:
    """The aggregations a column shows under the table, as the expressions they
    are.

    Every aggregation a column keeps, per-group answers being columns of their
    own rather than anything stored here (see _group_agg_column).
    """
    return list((model.get('column_computes') or {}).get(col) or [])


def _set_column_computes(model: dict, col: str, exprs) -> None:
    """Replace a column's aggregations, keeping them in the order the menu lists
    them so the cells under the column read the same way it does.

    A column showing none of them is dropped rather than stored empty, the way
    a search back at its default is.
    """
    computes = dict(model.get('column_computes') or {})
    # fromkeys rather than a set: asking for the same aggregation twice is one
    # cell, and the ones the ordering can't tell apart -- two percentiles --
    # keep the order they were asked in. An empty box is not an aggregation, so
    # it is dropped here rather than kept as a cell with nothing in it.
    ordered = sorted((expr for expr in dict.fromkeys(exprs) if expr.strip()),
                     key=_agg_order)
    if ordered:
        computes[col] = ordered
    else:
        computes.pop(col, None)
    model['column_computes'] = computes or None
    _drop_agg_children(model, col, set(ordered))


def _remove_column_compute(model: dict, col: str) -> None:
    computes = dict(model.get('column_computes') or {})
    computes.pop(col, None)
    model['column_computes'] = computes or None
    _drop_agg_children(model, col, ())


def _rename_column_compute(model: dict, old_name: str, new_name: str) -> None:
    computes = dict(model.get('column_computes') or {})
    if old_name in computes:
        computes[new_name] = computes.pop(old_name)
        model['column_computes'] = computes or None


def _reset_tally_view(model: dict) -> None:
    """Put the open tally's display controls back to how a menu opens.

    They belong to the menu that was open rather than to the next one, and
    every way of leaving a menu goes through here so none of them can forget
    one of them.
    """
    model['tally_filter'] = ''
    model['tally_sort'] = TALLY_SORT_DEFAULT
    model['tally_count_filter'] = ''
    model['tally_count_op'] = TALLY_COUNT_OP_DEFAULT


def _close_column_menus(model: dict) -> None:
    """Close the column ▾ menu along with any chip menu nested inside it.

    For the callers that have finished with the menu -- a line written, a
    column removed -- rather than to keep it honest: the ids name their column
    (see _menu_id), so moving one no longer leaves a menu open on whatever took
    its place. A rename is the one edit that changes an id, and one whose menu
    is left open simply finds nothing and draws closed.
    """
    model['openDropdown'] = None
    model['col_search_dropdown'] = None
    _reset_tally_view(model)


def _recompose_search(model: dict, eval_in_scope=None) -> None:
    """Push the column searches into the main search box.

    Half of the one thing this and _apply_search_to_columns maintain between
    them: the main search is always what the column rows and the leftovers
    compose to, whichever end of it was edited. A search typed by hand is a
    leftover like any other, so pushing the columns can no longer lose it.
    """
    composed = compose_column_searches(model.get('columns', []),
                                       model.get('column_searches') or {},
                                       eval_in_scope,
                                       model.get('search_leftovers'))
    previous = model.get('search')
    model['search'] = composed or None
    if model['search'] != previous:
        model['_scroll_to_match'] = True


def _apply_search_to_columns(model: dict, eval_in_scope=None) -> None:
    """Read the main search box back into the column rows: the other half.

    Exclude belongs to the tally rather than to the search text, so it stays as
    the menu left it -- the search says which values are picked out, never
    whether the box that picked them was ticked.
    """
    searches, leftovers = decompose_search(model.get('search'),
                                           model.get('columns', []),
                                           eval_in_scope)
    previous = model.get('column_searches') or {}
    for col, row in searches.items():
        row['exclude'] = bool((previous.get(col) or {}).get('exclude'))
    model['column_searches'] = searches or None
    model['search_leftovers'] = leftovers or None


# =============================================================================
# Column tally
# =============================================================================
#
# A column of few enough distinct values gets a tally in its ▾ menu: each value
# and how many rows have it, checkable to filter down to them (Apple Numbers
# calls this a Quick Filter).
#
# The tally holds no state of its own. Which rows are checked is read back out
# of the column search below it, and clicking one writes it -- so the search box
# stays the one place the filter lives, and one typed by hand simply leaves the
# boxes with nothing to say about it.

# Past this many distinct values a tally has stopped being a summary, and the
# menu says so instead of listing them.
TALLY_MAX_CARDINALITY = 100

TALLY_TOO_MANY = 'too_many'
TALLY_UNHASHABLE = 'unhashable'

# The operator pairs the tally speaks: one value compares, several use
# membership, and Exclude picks the negative of each.
_TALLY_SINGLE_OPS = ('==', '!=')
_TALLY_MEMBERSHIP_OPS = ('in', 'not in')
_TALLY_EXCLUDE_OPS = ('!=', 'not in')

# The orders the Sort by chip offers, in the order it offers them. Counting
# produces the first of them, so it costs nothing and leads.
TALLY_SORTS = ('first', 'common', 'rare', 'item asc', 'item desc')
TALLY_SORT_DEFAULT = 'first'

# The comparisons the count box offers. Fewer than the column search's, because
# a count is a whole number: `> 2` and `>= 3` are the same list, so offering
# both would only be two ways of saying it.
#
# Min and Max ask the same question without a number to ask it against -- the
# least and most common values, whatever counts those turn out to be -- so they
# read as words and leave the box with nothing to hold.
TALLY_COUNT_EXTREME_OPS = ('min', 'max')
TALLY_COUNT_OPS = ('>=', '==', '<=') + TALLY_COUNT_EXTREME_OPS
TALLY_COUNT_OP_DEFAULT = '>='


@functools.lru_cache(maxsize=None)
def _is_pure_ref(expr: 'str | None') -> bool:
    """Whether *expr* can be evaluated again for free.

    The table reads a cell by evaluating `<source>[i]` in the user's scope,
    which is exact for a name -- and which RUNS the user's code again for a
    source like `f()` or `json.load(open(p))`. Once per cell, on top of the
    once their program meant: their side effects happen again, and every value
    their function logged on the way gets another visualizer stacked on the one
    before it.

    So a source that isn't plainly a reference is not re-evaluated at all; the
    cell is read off the value already in hand, which is the value that line
    actually produced. Only evaluation is affected -- the code a header or a
    cell hands over still names the call, because that is still where the
    values came from.

    Attributes and subscripts count as references. A property doing work behind
    one is possible but not what anybody writes, whereas a call is exactly the
    thing this is here to catch.
    """
    if not expr:
        return False
    try:
        node = ast.parse(expr, mode='eval').body
    except (SyntaxError, ValueError):
        return False
    return not any(isinstance(sub, (ast.Call, ast.Await, ast.NamedExpr,
                                    ast.Yield, ast.YieldFrom))
                   for sub in ast.walk(node))


def _cell_source_expr(model: dict, eval_in_scope) -> 'str | None':
    """The source expression the cells may be read through, or None when they
    must be read off the rows in hand instead (see _is_pure_ref)."""
    source_expr = model.get('_source_expr')
    if eval_in_scope is None or not _is_pure_ref(source_expr):
        return None
    return source_expr


# === The binds seam ===============================================
#
# Every column helper below is a pure function of strings, so there is no
# parameter through which a dict could announce itself. `binds` is that
# parameter: a suffix -> EXPRESSION map, the string-side twin of Row.bindings.
#
# `'k' in binds` is what "this is a dict" means at the string layer -- one value
# threaded rather than a bool beside two names. It replaces the old `index_exp=`,
# which was only ever {'i': ...} written out longhand.

_LIST_BINDS = {'i': 'i'}
_DICT_BINDS = {'i': 'i', 'k': 'k', 'v': 'v'}

# How each sigil reads in a box's legend, per container. The binds dicts above
# say WHICH sigils a scope has; this says what they mean, and the two are read
# together by _sigil_dollars -- so a sigil added to a binds dict shows up in
# every legend that scope reaches, and one added without a word for it raises
# here rather than going quietly undocumented.
#
# One phrase per sigil rather than one per box: `$i` is the root row's number
# wherever it is written, and the boxes used to say that three different ways
# ("its index", "the index", "the row number") for no reason but that they were
# written at different times. A dict counts entries, since a root row that
# splats occupies several rendered rows and only the entry number is the one
# `$i` means.
_SIGIL_LABELS = {
    'i': {False: 'the row number', True: 'the entry number'},
    'j': {False: 'its position in the group',
          True: 'its position in the group'},
    'k': {True: 'the key'},
    'v': {True: 'the value'},
}

# The order sigils read in, which is not the order a binds dict happens to be
# written in: the halves of a pair read together, then the positions.
_SIGIL_ORDER = ('k', 'v', 'j', 'i')


def _sigil_dollars(binds: 'dict | None') -> list:
    """A Dollar per sigil the scope actually binds, in reading order.

    Driven by *binds* -- the same dict threaded to the substitution -- rather
    than by the order table, so the legend and the code can't disagree about
    which sigils exist. `_SIGIL_ORDER` only sorts what is already there, and a
    sigil it has never heard of sorts last and then fails the lookup below.

    A sigil with no phrase for this container raises: better a crash in a test
    than a box quietly promising less than it binds.
    """
    is_dict = _is_dict_binds(binds)
    binds = binds or {}
    order = lambda sigil: (_SIGIL_ORDER.index(sigil) if sigil in _SIGIL_ORDER
                           else len(_SIGIL_ORDER))
    return [Dollar(f'${sigil}', _SIGIL_LABELS[sigil][is_dict], binds[sigil])
            for sigil in sorted(binds, key=order)]


def _binds_for(value) -> dict:
    """The comprehension-scope binds for a container's rows."""
    return dict(_DICT_BINDS if isinstance(value, dict) else _LIST_BINDS)


def _model_binds(model) -> dict:
    """The same, for a render path that has the model but not the container.

    `_is_dict` is a fact about the value, not display state. init_model,
    visualize and update all receive the value, so it refreshes at every entry
    point and survives the relink round trip -- which is the point: the relink
    path rebuilds its context by parsing a source line and never holds the
    container at all.
    """
    return dict(_DICT_BINDS if (model or {}).get('_is_dict') else _LIST_BINDS)


def _is_dict_binds(binds: 'dict | None') -> bool:
    return 'k' in (binds or {})


def _default_item_expr(binds: 'dict | None') -> str:
    """What bare `$` stands for in a comprehension over these rows: the pair for
    a dict, the row itself for a list."""
    return '(k, v)' if _is_dict_binds(binds) else 'item'


_BARE_DOLLAR_PROBE = '_snc_bare_dollar_'


def _names_bare_dollar(col: str) -> bool:
    """Whether *col* reads the row ITSELF, as opposed to only naming things
    about it. `$v > 3` doesn't; `len($)` does.

    Asked through the substitution like every other question about a dollar
    expression, so a `$` inside a string literal answers no. What keeps
    _column_binding from narrowing a header to `v in d.values()` when the
    column also needs the key.
    """
    depth = max((len(m[1]) for m in DOLLARS_RE.finditer(col)), default=0)
    if depth == 0:
        return False
    holders = [_BARE_DOLLAR_PROBE] + [f'_snc_outer{n}_' for n in range(2, depth + 1)]
    return _BARE_DOLLAR_PROBE in replace_dollars_in_py_exp(
        col, holders, bindings={s: f'_snc_sig{s}_' for s in SIGILS})


def _row_scope(binds: 'dict | None' = None,
               source_expr: 'str | None' = None,
               item_expr: 'str | None' = None) -> DollarScope:
    """The scope a ROW expression is written in: the main search box, a column's
    code box, and every column expression the two of them produce.

    The one declaration of that scope. `_column_dollars` is its levels and the
    two boxes' tooltips are its prose, so a column that can name something the
    box never mentioned -- or a box that mentions something no column can name
    -- is not expressible.

    A source that can't be named drops `$$` from both halves at once: the run is
    left as written, which won't compile, and the box stops promising it.
    """
    is_dict = _is_dict_binds(binds)
    if item_expr is None:
        item_expr = _default_item_expr(binds)
    return DollarScope(
        Dollar('$', 'the (key, value) pair' if is_dict else 'the item from the list',
               item_expr),
        *_sigil_dollars(binds),
        Dollar('$$', 'the whole dict' if is_dict else 'the whole list',
               None if source_expr is None else _atomize(source_expr)),
    )


def _column_dollars(source_expr: 'str | None', item_expr: str = 'item') -> list:
    """What the dollars in a column expression stand for: the row, and -- when
    there is an expression for it -- the list the row came from.

    A column is written in row scope, but the box it is typed into says `$$` is
    the whole list, so a column may name it (`$ / max($$)`). The source is
    substituted into the user's own expression, so it is parenthesized to bind
    as tightly as the `$$` it replaces. A source that can't be named leaves the
    run as written, which won't compile -- the same as a column that names a
    variable the program doesn't have.

    The levels of _row_scope, taken off the same declaration the boxes read
    their tooltips off.
    """
    return _row_scope(source_expr=source_expr, item_expr=item_expr).replace_exps


def _column_item_expr(col: str, source_expr: 'str | None' = None,
                      item_expr: 'str | None' = None,
                      binds: 'dict | None' = None) -> str | None:
    """One row's value for a column, written against a row bound to `item` (or,
    for a dict, a pair bound to `k, v`) -- or None when the column is the item
    itself and the source already IS the values.

    That None is a list-only protocol. For a dict it would be a lie: `list(d)`
    is the keys, not the values, so a dict answers with a real expression and
    its five readers each get an explicit whole-column form instead.

    A caller that binds the row some other way says so: a row aggregation keyed
    over the row numbers reaches its row through one.
    """
    binds = _LIST_BINDS if binds is None else binds
    if item_expr is None:
        item_expr = _default_item_expr(binds)
    if col.strip() == '$':
        return item_expr if _is_dict_binds(binds) else None
    return replace_dollars_in_py_exp(col, _column_dollars(source_expr, item_expr),
                                     bindings=binds)


def _column_key_expr(col: str, source_expr: 'str | None' = None,
                     item_expr: 'str | None' = None,
                     binds: 'dict | None' = None) -> str:
    """The same, as a key to order the list by: `item` itself when the column
    is the row, which is what `min(lst, key=lambda item: item)` reads."""
    if item_expr is None:
        item_expr = _default_item_expr(binds)
    return _column_item_expr(col, source_expr, item_expr, binds) or item_expr


def _has_source_form(k) -> bool:
    """Whether repr(k) is a literal that reads back as k, so a cell can address
    its row by key rather than by position.

    Inside a try because literal_eval RAISES rather than answering False for a
    fair number of keys: float('nan') is a ValueError, and so is anything whose
    repr isn't a literal at all (str subclasses, most objects).
    """
    try:
        return ast.literal_eval(repr(k)) == k
    except Exception:
        return False


def _cell_binds(source_expr: str, i: int, container=None,
                from_end: bool = False) -> tuple:
    """(binds, item_expr) naming row *i*'s parts concretely.

    A cell stands on its own wherever it is dropped, so every part of it is a
    literal or a subscript rather than a comprehension variable. For a dict that
    means addressing by key -- what a user would write, and what is pleasant to
    drag into the editor -- with a fallback to positional addressing for a key
    that has no source form, which always works.

    *from_end* names the row `[-1]` instead of by its number, for the last row
    of a list (see _names_from_end). `$i` is left counting from the front: it
    is where the row SITS, and the last row of three sits at 2 however it was
    reached. It is a list-only question -- a dict's rows are addressed by key,
    which is already a name that survives the dict growing.
    """
    if not isinstance(container, dict):
        return {'i': str(i)}, f'{source_expr}[{-1 if from_end else i}]'
    key = _row_at(container, i).item[0]
    if _has_source_form(key):
        key_expr = repr(key)
        val_expr = f'{_atomize(source_expr)}[{key_expr}]'
        return ({'i': str(i), 'k': key_expr, 'v': val_expr},
                f'({key_expr}, {val_expr})')
    src = _atomize(source_expr)
    return ({'i': str(i), 'k': f'list({src})[{i}]',
             'v': f'list({src}.values())[{i}]'},
            f'list({src}.items())[{i}]')


def _column_cell_expr(col: str, source_expr: str, i: int, container=None,
                      from_end: bool = False) -> str:
    """One cell of a column, naming its row through the source rather than
    row-generically -- what a cell is read through and what it hands over.

    The row number is that row's own, for the same reason: a cell names one row
    concretely, so `$i` in it is a number rather than a variable, and the
    expression stands on its own wherever it is dropped.
    """
    binds, item_expr = _cell_binds(source_expr, i, container, from_end)
    return replace_dollars_in_py_exp(
        col, _column_dollars(source_expr, item_expr), bindings=binds)


def _column_binding(col: str, source_expr: str,
                    binds: 'dict | None' = None, *,
                    whole_row: bool = False) -> str:
    """How a comprehension over a column's rows binds them: the row alone, or
    the row and its number when the column asks for the number.

    The enumerate is only ever there because the column asked, so a column that
    doesn't hands over exactly the code it always did.

    For a dict, the tightest header the column actually asks for -- `$v` alone
    wants `v in d.values()`, `$k` alone `k in d`, anything reading the row
    itself `k, v in d.items()`. The index wraps whichever of those it was.

    *whole_row* is for a caller that keeps the row as well as the column: Group
    By puts whole rows in its groups, so it needs the pair through even where
    the key alone would have needed only half of it. A list has the one row to
    bind either way, so it is a dict-only distinction.
    """
    names_index = dollar_expr_names_index(col)
    if not _is_dict_binds(binds):
        return (f'i, item in enumerate({source_expr})'
                if names_index else f'item in {source_expr}')

    src = _atomize(source_expr)
    wants = dollar_expr_sigils(col) & {'k', 'v'}
    narrows = not whole_row and not _names_bare_dollar(col)
    if narrows and wants == {'v'}:
        target, iterable = 'v', f'{src}.values()'
    elif narrows and wants == {'k'}:
        target, iterable = 'k', src
    else:
        target, iterable = 'k, v', f'{src}.items()'

    if not names_index:
        return f'{target} in {iterable}'
    # A tuple target needs its own parens inside the enumerate pair.
    unpacked = f'({target})' if ',' in target else target
    return f'i, {unpacked} in enumerate({iterable})'


def _column_values_clause(col: str, source_expr: str,
                          binds: 'dict | None' = None) -> str | None:
    """A column's values as a comprehension body, `<value> for item in <source>`,
    for a caller that brackets it itself -- or None when the column is the item
    and the source already is the values.

    The one description of where a column's values come from: what the header
    hands to a drag, what the tally counts, and what the tally hands over in
    turn.
    """
    item_expr = _column_item_expr(col, source_expr, binds=binds)
    return (None if item_expr is None
            else f'{item_expr} for {_column_binding(col, source_expr, binds)}')


# A whole-column read of a dict has a short spelling a person would recognise,
# so the header hands over `list(d.values())` rather than a comprehension that
# means the same thing. Note list(d) is the KEYS -- the reason `$` cannot be
# answered with the source itself the way a list's is.
_DICT_WHOLE_COLUMN = {'$':  'list({src}.items())',
                      '$k': 'list({src})',
                      '$v': 'list({src}.values())'}


def _column_values_expr(col: str, source_expr: str,
                        binds: 'dict | None' = None) -> str:
    """The same as a list: the source itself when the column is the item, and a
    comprehension over it otherwise."""
    if _is_dict_binds(binds):
        short = _DICT_WHOLE_COLUMN.get(col.strip())
        if short is not None:
            return short.format(src=_atomize(source_expr))
    clause = _column_values_clause(col, source_expr, binds)
    return source_expr if clause is None else f'[{clause}]'


def _column_dict_expr(col: str, source_expr: str,
                      binds: 'dict | None' = None) -> str:
    """A column of a DICT, keyed the way the dict is: `{k: <col> for k, v in
    d.items()}`.

    The list reading of a dict's column drops the keys, and for a dict of lists
    they are half of what is on the screen. The pair through -- `whole_row` --
    even where the column reads only the value, because the key is the point.
    """
    item_expr = _column_item_expr(col, source_expr, binds=binds)
    if item_expr is None:
        item_expr = _default_item_expr(binds)
    binding = _column_binding(col, source_expr, binds, whole_row=True)
    return f'{{k: {item_expr} for {binding}}}'


def _column_values(col, lst, model, eval_in_scope=None) -> list:
    """Every row's value for one column, in row order.

    The table evaluates a cell at a time, but a tally wants the whole column, so
    ask for it in one comprehension -- the same expression the header hands to a
    drag. Rows the column can't be read from are dropped: a summary shouldn't
    cost the other n-1 rows.
    """
    binds = _binds_for(lst)
    # A leaf under a splat is identified by its composed key, not by an
    # expression that means anything on its own -- so it is read through the
    # leaf, flat, the same way the tally and the aggregations see it. A SPLIT
    # splat is not a leaf and is read through the one it would be, so the
    # values a menu summarises are the values its header hands over.
    if _is_leaf_identity(col):
        columns = model.get('columns') or {}
        leaf = _leaf_for(columns, col) or _split_splat_leaf(columns, col)
        if leaf is not None:
            return _leaf_values(leaf, lst, model, eval_in_scope)

    if col.strip() == '$':
        # For a list the source already IS the values. For a dict list(lst) is
        # the KEYS -- silently wrong for tally, sort and every aggregation --
        # so it goes the long way round, through the rows.
        if not _is_dict_binds(binds):
            return list(lst)
        return [row.item for row in _rows(lst)]

    source_expr = _cell_source_expr(model, eval_in_scope)
    if source_expr is not None:
        try:
            return list(eval_in_scope(
                _column_values_expr(col, source_expr, binds)))
        except Exception:
            # A comprehension is all or nothing, so one unreadable row lands
            # here too; the loop below gets the rest.
            pass

    values = []
    for row in _rows(lst):
        try:
            values.append(eval_dollar_expr(col, row.item, eval_in_scope,
                                           outer=(lst,), bindings=row.bindings))
        except Exception:
            pass
    return values


def _tally(values):
    """Distinct values and their counts, in first-seen order.

    None when there is nothing to count, or one of TALLY_TOO_MANY /
    TALLY_UNHASHABLE when there is a reason not to.
    """
    counts = {}
    try:
        for value in values:
            if value in counts:
                counts[value] += 1
            else:
                counts[value] = 1
                if len(counts) > TALLY_MAX_CARDINALITY:
                    return TALLY_TOO_MANY
    except TypeError:
        return TALLY_UNHASHABLE
    return counts or None


def _tally_literal(value) -> str | None:
    """A value as Python source the column search can compare against, or None
    when there's none to write.

    Most objects have none: their repr describes them rather than spelling them
    out. Nor does a value that isn't equal to itself, since a comparison against
    it would match nothing anyway.
    """
    text = repr(value)
    try:
        parsed = ast.literal_eval(text)
    except Exception:
        return None
    if type(parsed) is not type(value):
        return None
    try:
        return text if parsed == value else None
    except Exception:
        return None


def _as_literal(text: str) -> str | None:
    """Search text as the canonical literal for the value it names, so `"c"`
    typed by hand checks the row the tally rendered as `'c'`."""
    try:
        return repr(ast.literal_eval(text))
    except Exception:
        return None


def _as_literals(text: str) -> List[str]:
    """The same, for the collection on the right of `in` / `not in`."""
    try:
        values = ast.literal_eval(text)
    except Exception:
        return []
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return [repr(value) for value in values]


def _tally_selection(row) -> Tuple[List[str], bool]:
    """The values a column search row has picked out, and whether it keeps them
    or leaves them out.

    Only the shapes the tally itself writes are read back; a search that says
    anything else selects nothing.

    The operator settles Exclude whenever there are values for it to apply to,
    which keeps a search edited by hand authoritative. With nothing selected it
    has nothing to say, and the stored bit stands.
    """
    op = row.get('op', '')
    text = (row.get('text') or '').strip()
    if op in _TALLY_SINGLE_OPS:
        literal = _as_literal(text)
        literals = [literal] if literal is not None else []
    elif op in _TALLY_MEMBERSHIP_OPS:
        literals = _as_literals(text)
    else:
        literals = []
    if not literals:
        return ([], bool(row.get('exclude')))
    return (literals, op in _TALLY_EXCLUDE_OPS)


def _write_tally_selection(model: dict, col: str, literals, exclude: bool) -> None:
    """Write a selection back as the column's search: nothing selected is no
    filter, one value compares, several use membership.

    Every tally control writes through here, so none of them can disagree about
    that choice.
    """
    if not literals:
        _set_column_search(model, col, op='==', text='', exclude=exclude)
    elif len(literals) == 1:
        _set_column_search(model, col, op='!=' if exclude else '==',
                           text=literals[0], exclude=exclude)
    else:
        _set_column_search(model, col, op='not in' if exclude else 'in',
                           text=f'[{", ".join(literals)}]', exclude=exclude)


def _tally_sort(model: dict) -> str:
    """The order the open tally is listing its values in."""
    sort = model.get('tally_sort')
    return sort if sort in TALLY_SORTS else TALLY_SORT_DEFAULT


def _tally_comparable(tally: dict) -> bool:
    """Whether a column's values have an order of their own to be sorted by.

    A column of mixed types doesn't, and both the list on screen and the code
    the headers hand over fall back to sorting on how the rows read -- so they
    have to agree on when that is.
    """
    try:
        sorted(tally)
        return True
    except TypeError:
        return False


def _sorted_tally(tally: dict, sort: str) -> List[Tuple[Any, int]]:
    """A tally's values and counts in one of the orders the Sort by chip offers.

    Counting already produced first-seen order, and every other order is one
    stable sort away from it -- so values an order can't tell apart, like two
    equally common ones, stay in the order the column first showed them.
    """
    items = list(tally.items())
    if sort == 'common':
        return sorted(items, key=lambda item: -item[1])
    if sort == 'rare':
        return sorted(items, key=lambda item: item[1])
    if sort in ('item asc', 'item desc'):
        # A column of mixed types has no order of its own, but its rows still
        # read in some order: sorting how they read is at least an order the
        # user can see on screen.
        key = ((lambda item: item[0]) if _tally_comparable(tally)
               else (lambda item: repr(item[0])))
        return sorted(items, key=key, reverse=(sort == 'item desc'))
    return items


def _tally_rows(tally: dict, model: dict) -> List[Tuple[str, int, str | None]]:
    """A tally as the menu lists it: for each value, how it reads, how many rows
    have it, and the literal the column search compares against -- None for a
    value with no literal to write, which is a row the list still shows.

    The one description of the list, so the rows the menu puts on screen and the
    ones All and None act on are read off the same thing.
    """
    return [(repr(value), count, _tally_literal(value))
            for value, count in _sorted_tally(tally, _tally_sort(model))]


def _column_tally_rows(col, model, lst, eval_in_scope=None) -> List[Tuple[str, int, str | None]]:
    """The same, for a column that hasn't been counted yet."""
    tally = _tally(_column_values(col, lst, model, eval_in_scope))
    if not isinstance(tally, dict):
        return []
    return _tally_rows(tally, model)


def _tally_counted(col, model, lst, eval_in_scope=None) -> List[Tuple[str, int]]:
    """Every value a column's tally can filter on, with how many rows have it,
    in the order the tally shows them."""
    return [(literal, count)
            for _text, count, literal in _column_tally_rows(col, model, lst,
                                                            eval_in_scope)
            if literal is not None]


def _tally_literals(col, model, lst, eval_in_scope=None) -> List[str]:
    """Every value a column's tally can filter on, in the order it shows them."""
    return [literal
            for literal, _count in _tally_counted(col, model, lst, eval_in_scope)]


def _tally_shows(text: str, shown: str) -> bool:
    """Whether the tally's filter box leaves a row on show.

    A plain case-insensitive substring of how the row reads -- which is its
    untruncated repr, and so also its literal, so the rows the display keeps and
    the ones All and None act on can't come apart.

    Surrounding space is not part of the search: a trailing space shouldn't
    empty the list out from under someone still typing.
    """
    return text.strip().lower() in shown.lower()


def _tally_count_op(model: dict) -> str:
    """The comparison the open tally's count box is making."""
    op = model.get('tally_count_op')
    return op if op in TALLY_COUNT_OPS else TALLY_COUNT_OP_DEFAULT


def _tally_count_threshold(text: str, eval_in_scope=None) -> int | None:
    """The whole number the tally's count box is comparing against, or None
    when it isn't comparing against one.

    Digits are read as digits, so the common case asks the scope for nothing.
    Anything else is the user's own expression, evaluated where they wrote it:
    a count is a number like any other in the program, so the box can say
    `len(names) // 2` or name a threshold the program already worked out.

    Nothing but a whole number comes back. A count is one, so a number still
    being typed (`-`, `1.`), a name that never arrives, and `n / 2` for an odd
    n all say the same thing here -- there is nothing to compare against yet.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = (ast.literal_eval(text) if eval_in_scope is None
                 else eval_in_scope(text))
    except Exception:
        return None
    if isinstance(value, bool):
        # True == 1, but naming a flag is nobody's way of saying "one row".
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _tally_count_shows(op: str, text: str, count: int,
                       extreme: int | None = None, eval_in_scope=None) -> bool:
    """Whether the tally's count box leaves a value that many rows have on show.

    A box with no number to compare against filters nothing: an empty list is a
    poor answer to text the box can't read as a count.

    Min and Max compare against the list rather than against the box -- they
    disable it -- so they ask only whether this is one of the counts *extreme*
    named. With no extreme there was nothing to be least or most common among.
    """
    if op in TALLY_COUNT_EXTREME_OPS:
        return extreme is not None and count == extreme
    threshold = _tally_count_threshold(text, eval_in_scope)
    if threshold is None:
        return True
    if op == '>=':
        return count >= threshold
    if op == '==':
        return count == threshold
    if op == '<=':
        return count <= threshold
    return True


def _tally_extreme(model: dict, rows) -> int | None:
    """The count Min or Max is asking for: how many rows the least or most
    common value on show has. None when the count box is comparing against a
    number instead, or when there is nothing left to be extreme.

    The filter box narrows first, so Min and Max answer about the list in front
    of the user rather than one it is hiding -- and so the two boxes together
    can't argue their way to an empty list. Every row counts towards it,
    including one the search has no literal to compare against: it is a row of
    the list the user is reading.
    """
    op = _tally_count_op(model)
    if op not in TALLY_COUNT_EXTREME_OPS:
        return None
    text = model.get('tally_filter') or ''
    counts = [count for shown, count, _literal in rows
              if _tally_shows(text, shown)]
    if not counts:
        return None
    return min(counts) if op == 'min' else max(counts)


def _tally_lists(model: dict, shown: str, count: int,
                 extreme: int | None = None, eval_in_scope=None) -> bool:
    """Whether the tally's two display filters both leave a row on show.

    The one place they meet, so the rows the menu lists and the ones All and
    None act on can't come apart.
    """
    return (_tally_shows(model.get('tally_filter') or '', shown)
            and _tally_count_shows(_tally_count_op(model),
                                   model.get('tally_count_filter') or '', count,
                                   extreme, eval_in_scope))


def _tally_shown(model: dict, rows, eval_in_scope=None) -> List[str]:
    """The literals the display filters are leaving on show, which is what All
    and None act on: what the user can't see, they didn't mean to change."""
    extreme = _tally_extreme(model, rows)
    return [literal for shown, count, literal in rows
            if literal is not None
            and _tally_lists(model, shown, count, extreme, eval_in_scope)]


def _in_tally_order(literals, order) -> List[str]:
    """Sort a selection into the order the tally displays, so the search reads
    the same however the user clicked their way to it."""
    rank = {literal: i for i, literal in enumerate(order)}
    return sorted(literals, key=lambda literal: rank.get(literal, len(rank)))


# The tally is a Counter, and the headers hand out code that says so.
TALLY_IMPORTS = ('from collections import Counter',)


def _tally_counter_expr(col: str, source_expr: str,
                        binds: 'dict | None' = None, columns=None) -> str:
    """The whole tally, before the menu has narrowed or reordered anything.

    Counter takes any iterable, so a computed column goes in as a generator --
    there is no list to build on the way to counting it. A leaf under a splat
    or under a plain parent is keyed by a composed identity that is no
    expression at all, so it goes through the same whole-column read every
    other summary of that column uses.
    """
    if _is_leaf_identity(col):
        return f'Counter({_column_whole_expr(columns, col, source_expr, binds)})'
    clause = _column_values_clause(col, source_expr, binds)
    return f'Counter({clause if clause is not None else source_expr})'


def _tally_row_count_expr(col: str, source_expr: str, literal: str,
                          values, binds: 'dict | None' = None,
                          columns=None) -> str:
    """How many rows have one value -- the number that row is showing.

    A question about a single value, so it asks about that one rather than
    counting the whole column to look one answer up.

    When the column is the item, the values are the source itself, and a
    sequence can count one of its own. Only a sequence: a set has no `.count`
    at all, and a string's counts substrings rather than elements, which is a
    different question with the same name. Anything else -- and every computed
    column, which has no list to ask -- counts the rows that match as it goes.
    """
    if _is_leaf_identity(col):
        # A splat column's rows ARE its elements, so the number beside the
        # value counts those rather than the root rows they were spread from --
        # and the code for it counts the same things the tally did.
        flat = _column_whole_expr(columns, col, source_expr, binds)
        return f'sum(1 for v in {flat} if v == {literal})'
    # A dict never takes the .count path: it has no .count at all, and its
    # item_expr is a real expression rather than the None that would ask for one.
    item_expr = _column_item_expr(col, source_expr, binds=binds)
    if item_expr is None:
        if isinstance(values, (list, tuple)):
            return f'{source_expr}.count({literal})'
        item_expr = 'item'
    return (f'sum(1 for {_column_binding(col, source_expr, binds)} '
            f'if {item_expr} == {literal})')


def _tally_order_expr(counter_expr: str, sort: str, comparable: bool) -> str:
    """The tally's values and counts as the Sort by chip has them.

    Each order is the one a Python programmer would reach for, so the code reads
    as the sort rather than as a re-implementation of it.
    """
    if sort == 'common':
        return f'{counter_expr}.most_common()'
    if sort == 'rare':
        # The one order where the code and the list on screen can part company:
        # the display sorts by count, so equally rare values stay in first-seen
        # order, while reversing hands those back last-seen first. Same values
        # and same counts either way, and this is how one asks for it in Python.
        return f'reversed({counter_expr}.most_common())'
    if sort in ('item asc', 'item desc'):
        # A column of mixed types has no order of its own; the display falls
        # back to sorting on how the rows read, so the code says that too.
        key = '' if comparable else ', key=lambda vc: repr(vc[0])'
        reverse = ', reverse=True' if sort == 'item desc' else ''
        return f'sorted({counter_expr}.items(){key}{reverse})'
    return f'{counter_expr}.items()'


def _tally_text_condition(model: dict, var: str = 'v') -> str | None:
    """The filter box as a condition on *var*, or None when it isn't narrowing.

    The same case-insensitive substring of how a row reads that `_tally_shows`
    applies, said in Python.
    """
    text = (model.get('tally_filter') or '').strip().lower()
    return f'{text!r} in repr({var}).lower()' if text else None


def _tally_extreme_expr(model: dict, counts_var: str) -> str:
    """The count Min or Max is asking for.

    Over the list the filter box left rather than the whole tally, the way
    `_tally_extreme` reads it -- so the two boxes together can't argue their way
    to an empty list.
    """
    op = _tally_count_op(model)
    shown = _tally_text_condition(model, 'v2')
    if shown:
        return f'{op}(c2 for v2, c2 in {counts_var}.items() if {shown})'
    return f'{op}({counts_var}.values())'


def _tally_filter_exprs(model: dict, eval_in_scope=None) -> List[str]:
    """The display filters as conditions on a value `v` and its count `c`.

    One condition per box that is actually narrowing -- a box filtering nothing
    has nothing to say in code either. Min and Max compare against the name the
    comprehension binds for them rather than asking the tally a second time.
    """
    conditions = []
    text_condition = _tally_text_condition(model)
    if text_condition:
        conditions.append(text_condition)

    op = _tally_count_op(model)
    if op in TALLY_COUNT_EXTREME_OPS:
        conditions.append(f'c == _{op}')
    else:
        count_text = (model.get('tally_count_filter') or '').strip()
        if _tally_count_threshold(count_text, eval_in_scope) is not None:
            # The box may name the program's own value rather than a number, so
            # it goes in as written -- parenthesized where an operator of its
            # own would otherwise be pulled apart by the comparison.
            conditions.append(f'c {op} {_atomize(count_text)}')
    return conditions


def _tally_exprs(col, model: dict, tally, source_expr,
                 eval_in_scope=None) -> Tuple[str, str, str] | None:
    """The Python behind the Tally, Items and Counts headers: the mapping the
    section is showing, its values, and its counts.

    Built from the same sort and display filters the rendering reads, so what
    the user drags out is the list they were looking at.

    Anything the code would otherwise ask for twice is named once and used
    after, through a comprehension clause over a one-tuple: counting a list to
    find its rarest value, then counting it again to compare against, is a
    strange way to write down a question the menu only asked once.

    None when there is no expression to hand over: a list with no source to name
    it by, values that can't be counted, or filters that have left nothing on
    show -- there is no code that means an empty menu.
    """
    if source_expr is None or not isinstance(tally, dict):
        return None

    rows = _tally_rows(tally, model)
    extreme = _tally_extreme(model, rows)
    if not any(_tally_lists(model, shown, count, extreme, eval_in_scope)
               for shown, count, _literal in rows):
        return None

    counter_expr = _tally_counter_expr(col, source_expr, _model_binds(model),
                                       model.get('columns') or {})
    sort = _tally_sort(model)
    conditions = _tally_filter_exprs(model, eval_in_scope)
    if sort == TALLY_SORT_DEFAULT and not conditions:
        # Nothing sorted and nothing narrowed: the count is the whole answer.
        return (counter_expr, f'list({counter_expr})',
                f'list({counter_expr}.values())')

    # Only Min and Max read the tally more than once -- for the extreme, and
    # then for the values to compare against it -- so only they are worth a
    # name. Everything else says `Counter(...)` where it means it. The names
    # lead with an underscore: they are the comprehension's own scaffolding,
    # not something the user asked to have around.
    op = _tally_count_op(model)
    clauses = []
    if op in TALLY_COUNT_EXTREME_OPS:
        base = '_cnts'
        clauses.append(f'for {base} in [{counter_expr}]')
        clauses.append(f'for _{op} in [{_tally_extreme_expr(model, base)}]')
    else:
        base = counter_expr

    clauses.append(
        f'for v, c in {_tally_order_expr(base, sort, _tally_comparable(tally))}')
    body = ' '.join(clauses)
    if conditions:
        body += f' if {" and ".join(conditions)}'
    return (f'{{v: c {body}}}', f'[v {body}]', f'[c {body}]')


# =============================================================================
# Column sort
# =============================================================================
#
# The Sort submenu of a column's ▾ menu writes the sort into the line the table
# is already showing -- `data = json.load(f)` becomes `data = sorted(json.load(f),
# key=lambda item: item['b'])` -- so the next run re-renders the table sorted
# and everything downstream sees the sorted list. Nothing here reorders rows on
# screen: the table draws the list in the order it receives it, and the order it
# receives is the one the code now says.
#
# So the sort is not model state. Which box is ticked is read back out of the
# line, the way a tally's checkmarks are read back out of the column search:
# the code is the only record of it, and there is nowhere for the two to
# disagree. A sort the user wrote by hand ticks the box that describes it.
#
# The line's own expression arrives as `_source_span` -- see visualize() -- and
# is absent wherever there is nothing to rewrite (a loop variable is bound by
# its statement, not written on it), which is what dims the two rows.

# The directions the submenu offers, in the order it offers them, and what each
# one writes. Ascending is the bare `sorted`, which is how anyone types it.
SORT_DIRECTIONS = ('asc', 'desc')

_SORT_LABELS = {'asc': 'Asc', 'desc': 'Desc'}


def _sort_label(direction: str) -> str:
    return _SORT_LABELS.get(direction, direction)


def _parse_sorted(text: str | None):
    """A `sorted(...)` call read apart, or None when the text isn't one.

    Answers (what is being sorted, what it is keyed on, whether it is reversed)
    -- the three things the menu needs to know and the three it writes. The
    inner expression comes back as the user's own text rather than an unparse
    of it, because taking a sort off writes it back verbatim.

    The key is the body of `lambda item: ...`, which is the shape this menu
    writes and the shape a column can be recognized in. One written any other
    way -- `key=len` -- comes back as written instead, so it can't be mistaken
    for the no-key sort that orders on the row itself. Either way the call is
    still a sort, so clicking a direction replaces it rather than nesting
    inside it.
    """
    if not text:
        return None
    try:
        node = ast.parse(text, mode='eval').body
    except (SyntaxError, ValueError):
        return None
    # A sorted dict is `dict(sorted(d.items(), ...))`, and the wrapper is
    # unwrapped TRANSPARENTLY: the same triple comes back, so no caller grows a
    # fourth element and canonical_source_expr goes on recognising a sorted
    # dict as the same source -- without which every sort of a dict would read
    # as a new expression and discard the searches and aggregations set up on
    # the very table being sorted.
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'dict' and len(node.args) == 1
            and not node.keywords):
        node = node.args[0]
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'sorted' and len(node.args) == 1):
        return None

    key_node = None
    reverse = False
    for kw in node.keywords:
        if kw.arg == 'key':
            key_node = kw.value
        elif kw.arg == 'reverse':
            reverse = (isinstance(kw.value, ast.Constant)
                       and kw.value.value is True)
        else:
            # A `**kwargs` (arg is None) or anything else lands here: not a
            # shape this menu can speak about, so not one it should rewrite.
            return None

    inner = ast.get_source_segment(text, node.args[0])
    if inner is None:
        return None
    # `inner` is the container the line names, so a dict sort's trailing
    # .items() comes off with the wrapper. _sort_expr re-emits both from its own
    # binds rather than from what was parsed.
    arg_node = node.args[0]
    if (isinstance(arg_node, ast.Call) and isinstance(arg_node.func, ast.Attribute)
            and arg_node.func.attr == 'items' and not arg_node.args
            and not arg_node.keywords):
        inner = ast.get_source_segment(text, arg_node.func.value) or inner
    if key_node is None:
        key_expr = None
    elif (isinstance(key_node, ast.Lambda) and len(key_node.args.args) == 1
            and key_node.args.args[0].arg == 'item'):
        key_expr = ast.get_source_segment(text, key_node.body)
    else:
        key_expr = ast.get_source_segment(text, key_node)
    return (inner, key_expr, reverse)


# A sort's key lambda binds one parameter, and tuple-unpacking parameters are
# illegal in Python 3 -- so a dict's pair is reached through it by position.
# The name stays `item` because that is the name _parse_sorted recognises.
_SORT_PAIR_BINDS = {'k': 'item[0]', 'v': 'item[1]', 'i': 'i'}


def _sort_key_expr(col: str, inner: str, binds: 'dict | None') -> 'str | None':
    """What a sort orders on, written against the lambda's one parameter."""
    if not _is_dict_binds(binds):
        return _column_item_expr(col, inner)
    # For a dict the key is never None: `sorted(d.items())` would order on the
    # pair, and the menu means the column.
    return _column_item_expr(col, inner, item_expr='item',
                             binds=_SORT_PAIR_BINDS)


def _sort_expr(text: str, col: str, direction: 'str | None',
               binds: 'dict | None' = None) -> str:
    """*text* sorted by *col* -- or, with no direction, with its sort taken off.

    Always unwraps first, so re-sorting by another column, or flipping the
    direction, replaces the sort rather than nesting inside it.

    A dict sorts its items and is rebuilt as a dict: `sorted(d, key=...)`
    returns a list of KEYS whatever the key function is, so this is a shape
    change rather than a key= to get right.
    """
    parsed = _parse_sorted(text)
    inner = parsed[0] if parsed else text
    if direction is None:
        return inner
    is_dict = _is_dict_binds(binds)
    # A column naming the list means the list as the line has it, which is what
    # is being sorted rather than the sort of it.
    key = _sort_key_expr(col, inner, binds)
    parts = [f'{_atomize(inner)}.items()' if is_dict else inner]
    if key is not None:
        parts.append(f'key=lambda item: {key}')
    if direction == 'desc':
        parts.append('reverse=True')
    call = f'sorted({", ".join(parts)})'
    return f'dict({call})' if is_dict else call


def _sort_checked(text: 'str | None', col: str, direction: str,
                  binds: 'dict | None' = None) -> bool:
    """Whether the line already sorts by this column in this direction."""
    parsed = _parse_sorted(text)
    if parsed is None:
        return False
    inner, key_expr, reverse = parsed
    return (key_expr == _sort_key_expr(col, inner, binds)
            and reverse == (direction == 'desc'))


def canonical_source_expr(expr: 'str | None') -> 'str | None':
    """What counts as the same source expression for reusing a cached model.

    The runner keys a model on the expression it was built for, so that
    renaming x -> y rebuilds one whose cells would otherwise eval the old name.
    A sort wrapper is precisely the part of an expression that is NOT that kind
    of change -- the same rows, in another order -- and a line rewritten by the
    Sort menu would otherwise throw away the searches and aggregations the user
    set up on the very table they were sorting.

    Asked of the same _parse_sorted the checkboxes are read with, so the menu
    and the cache can't come to different views of what a sort is.
    """
    parsed = _parse_sorted(expr)
    return parsed[0] if parsed else expr


# =============================================================================
# Group by
# =============================================================================
#
# One row of a column's ▾ menu, which writes the list cut up by that column: a
# dict whose keys are the column's values and whose values are the rows that
# had them. The answer is a dict of lists, so the dict and table visualizers
# already know how to draw it -- the groups show up under the new line without
# a line of drawing code here.

# The name the dict is built up under, which stays bound in the user's scope
# after the line runs. Short, because it appears twice in every line this
# writes.
_GROUP_VAR = '_d'


def _group_by_expr(col: str, source_expr: str,
                   binds: 'dict | None' = None) -> str:
    """*source_expr* cut up by *col*: a dict of the rows that share a value.

    A dict of lists rather than `itertools.groupby`, which only groups runs and
    so answers wrongly for any list the user hasn't already sorted -- and
    `setdefault` rather than a `defaultdict`, which would need an import. The
    walrus is what keeps the whole thing an expression, so the row can hand it
    to a drag and the line it writes reads like every other line this menu
    writes.

    A group holds whole rows rather than the column's own values -- what the
    user asks for by grouping is the table cut up -- so the binding is the
    whole-row one even where the key alone would have needed less of it.

    A column naming `$i` is welcome here, unlike in Sort: `sorted` takes a key
    over rows and a row handed to one doesn't know its number, but a
    comprehension can count, so the row number is a key like any other.
    """
    return (f'({_GROUP_VAR} := {{}}, '
            f'[{_GROUP_VAR}.setdefault('
            f'{_column_key_expr(col, source_expr, binds=binds)}, [])'
            f'.append({_default_item_expr(binds)}) '
            f'for {_column_binding(col, source_expr, binds, whole_row=True)}'
            f'])[0]')


# The grouped dict lands on a line of its own, and what detection would say
# about one is not what it wants: it asks a dict's VALUES for their fields, and
# a group answers with a position per element it happens to hold. So the click
# sends the columns along with the line, as the `#%click` comment it opens with.
_GROUPED_COLUMNS = ['$k', 'len($v)']


def _reads_the_row(col: str) -> bool:
    """Whether a column of the table being grouped still means what it meant
    when read off an element of a group.

    A group holds whole ROWS, so inside `*$v` the element is a row and an
    ordinary column reads it unchanged. A sigil is what doesn't survive: `$i`
    is the row's number in the list it came from, and an element of a group has
    none; `$k` and `$v` name the halves of a dict's row, and grouping a dict
    answers with lists of pairs. `$$` named the list the row was read from, and
    under a splat it names the root row instead.
    """
    if dollar_expr_sigils(col):
        return False
    return max((len(m[1]) for m in DOLLARS_RE.finditer(col)), default=0) <= 1


def _grouped_slots(col: str, columns) -> list:
    """The columns the grouped dict opens with: the key, how big the group is,
    and the group's rows spread across the columns the table already had.

    The column grouped ON is left out of the spread -- it has one value per
    group by construction, and `$k` is already showing it.
    """
    subs = {c: config for c, config in _as_columns(columns).items()
            if c != col and _reads_the_row(c)}
    splat = f'{SPLAT}$v'
    return _GROUPED_COLUMNS + [{'expr': splat, 'cols': _slots_from_columns(subs)}
                               if subs else splat]


# =============================================================================
# Row actions
# =============================================================================
#
# The columns have a drag handle and a ▾ menu on their headers; the rows have
# the same two on their numbers. What a column's menu asks is a question about
# a column of values -- sort by it, tally it, add it up -- and what a row's asks
# is the handful of things one row of a list is good for: dropping it, taking
# it out, or reading it as the names of the rows under it.
#
# Every one of them writes a line rather than changing the table, so there is no
# row state to keep: which menu is open is the same `openDropdown` slot the
# column menus use, keyed by the row number instead of a column expression.
#
# They are one catalog, `_row_actions`, which the menu draws itself from and the
# click reads back -- so a row cannot offer one line and write another, and the
# handle on the number is built out of the same answers.
#
# Pop is the one that does both at once, and the one exception to writing rather
# than changing: `data.pop(2)` hands back the row AND takes it out of the very
# list the rest of the file goes on using, where Delete writes a copy without it
# and Extract writes a copy of it. That is what `.pop` means to anyone reading
# the line, and it is the reason the row sits between the two groups.
#
# A row is two things at once and the menu says both: the ITEM, whatever `$` is
# for this container, and the ROW OF CELLS, the columns that happen to be on
# screen. They coincide often enough (a one-column table showing `$`) that the
# menu drops the second when they read the same, and differ often enough that
# offering only one of them would be picking for the user.
#
# The last row of a list can be named a third way -- `[-1]`, which is what a
# person writes for "the last one" and the only naming here that survives the
# list growing. So it gets its own rows, at the top, and the cells of that row
# are handed the same naming (see _names_from_end).
#
# A row can also be named by what it CONTAINS rather than by where it sits, and
# `delete_matching` is the one row of the menu written that way: the list
# without every row equal to this one. Beside Delete, because the two answer the
# same question ("not this") about different things -- a position and a value --
# and a list where the difference doesn't show (no two rows alike) is one where
# either will do.

ROW_ACTIONS = ('last_delete', 'last_pop', 'last_item', 'last_cells',
               'delete', 'delete_matching', 'pop', 'item', 'cells', 'headers')

# The ones that name the row from the end. First in the menu, because a row
# that HAS an end-relative name is one the user reached for as "the last one".
LAST_ROW_ACTIONS = ('last_delete', 'last_pop', 'last_item', 'last_cells')

# How much of a value the Delete-matching row spells out. Long enough to tell
# two rows of a table apart, short enough that the panel is still a menu; the
# whole value is one drag away, off the row's own handle.
ROW_MATCH_LABEL_LEN = 30

# What each one calls the line it writes. `{word}` is item or entry (see
# _item_word), which is what the `$i` heading this very column already calls it.
_ROW_ACTION_NAMES = {
    'last_delete': '{base}_without_last',
    # Named for what the line IS -- the row that came out -- rather than for
    # what the list became, which is the one thing about a pop that has no
    # name to be bound to.
    'last_pop': '{base}_popped_last_{word}',
    'last_item': '{base}_last_{word}',
    'last_cells': '{base}_last_row',
    'delete': '{base}_without_{word}_{i}',
    'pop': '{base}_popped_{word}_{i}',
    # Not `{i}` either: what it leaves out is a value, and any of the rows
    # holding that value would have written this same line.
    'delete_matching': '{base}_without_matching_{word}s',
    'item': '{base}_{word}_{i}',
    'cells': '{base}_row_{i}',
    # Not `{i}`: what it makes is the same list of dicts whichever row named
    # the keys, and row 0 -- the only one anyone reaches for twice -- would read
    # as a row number in the name of a list that no longer has one.
    'headers': '{base}_dicts',
}


def _item_word(model: dict) -> str:
    """What this container calls one of its rows' values.

    The `$i` header over the row numbers says "the entry number" for a dict, so
    a menu hanging off that very column cannot go on calling the same thing an
    item. The row of CELLS is a row either way -- that is a fact about the
    table, which draws rows whatever it is drawing them from.
    """
    return 'entry' if _is_dict_binds(_model_binds(model)) else 'item'


def _names_from_end(model: dict, lst, i: int) -> bool:
    """Whether row *i* is worth naming `[-1]` as well as by its number.

    The last row of a list of more than one. A list of one has a last row that
    is also its first, and `data[-1]` would be `data[0]` said twice. A dict is
    left out entirely: its rows are addressed by key, which is already a name
    that doesn't move when the dict grows, so an end-relative one buys nothing
    and `list(d.items())[-1]` is not what anyone would have written.
    """
    if _is_dict_binds(_model_binds(model)):
        return False
    try:
        n = len(lst)
    except Exception:
        return False
    return n > 1 and i == n - 1


def _row_item_expr(model: dict, lst, i: int,
                   from_end: bool = False) -> 'str | None':
    """Row *i* itself, named through the source: `data[2]`, `data[-1]`, or a
    dict's own `('b', d['b'])`.

    Whatever bare `$` is for this container, which for a dict is the pair its
    `.items()` gives -- the same naming every cell of that row is written
    through (see _cell_binds), so the row and its cells cannot disagree about
    which row is meant.
    """
    source_expr = model.get('_source_expr')
    if source_expr is None:
        return None
    return _cell_binds(source_expr, i, lst, from_end)[1]


def _row_column_exprs(model: dict, lst, i: int,
                      from_end: bool = False) -> 'list | None':
    """Every drawn column of row *i*, named through the source -- in the order
    the table draws them.

    The columns as DRAWN, so a column the user took away is not among them and
    one they computed is. The index column is not either: it heads nothing the
    user added, and the row number is already written into every one of these.

    A splat column reads as the whole list it spread rather than the one element
    a rendered row shows: this is asked of the ROOT row, which is one row
    however many rendered rows it takes across. That is `_leaf_row_expr`, the
    same reading a row aggregation's row shows in a splat column -- and, for a
    leaf nothing splatted, the very expression that leaf's cell is dragged out
    by, which is why the body reads its cells' code back out of this list rather
    than substituting the same column twice per row.
    """
    source_expr = model.get('_source_expr')
    leaves = _leaf_columns(model.get('columns') or {})
    if source_expr is None or not leaves:
        return None
    return [_column_cell_expr(_leaf_row_expr(leaf), source_expr, i, lst,
                              from_end)
            for leaf in leaves]


def _row_tuple_expr(model: dict, lst, i: int, parts=None,
                    from_end: bool = False) -> 'str | None':
    """Row *i* as the columns on screen read it -- one of the two things the
    drag handle on the number hands over, and what Extract Row Cells writes.

    One column is handed over bare rather than as `(x,)`. A one-tuple is what
    the label says and not what anyone dragging one column out of one row
    means.

    *parts* is `_row_column_exprs` already in hand, for the render, which has
    them for the cells anyway. It is the caller's job that they were asked for
    with the same *from_end*.
    """
    if parts is None:
        parts = _row_column_exprs(model, lst, i, from_end)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else f'({", ".join(parts)})'


def _row_without_expr(model: dict, lst, i: int,
                      from_end: bool = False) -> 'str | None':
    """The container with row *i* left out.

    Slices for a list, and the two ends written out only where there are two:
    the first row is `data[1:]` and the last `data[:2]`, which is what anyone
    would write and shorter than the general form that would also be correct.
    Reached as the LAST row it is `data[:-1]` instead -- the same rows, said
    the way the row was asked for, and the only one of the two that goes on
    meaning "all but the last" once the list grows.

    A dict is not sliceable and has a name for its rows, so it drops the entry
    by key -- `{k: v for k, v in d.items() if k != 'b'}` -- through the same key
    expression its cells are addressed by, with the positional fallback for a
    key that has no source form.
    """
    source_expr = model.get('_source_expr')
    if source_expr is None:
        return None
    if _is_dict_binds(_model_binds(model)):
        key = _cell_binds(source_expr, i, lst)[0]['k']
        return (f'{{k: v for k, v in {_atomize(source_expr)}.items() '
                f'if k != {key}}}')
    src = _atomize(source_expr)
    if from_end:
        return f'{src}[:-1]'
    if i == 0:
        return f'{src}[1:]'
    if i == len(lst) - 1:
        return f'{src}[:{i}]'
    return f'{src}[:{i}] + {src}[{i + 1}:]'


def _row_pop_expr(model: dict, lst, i: int,
                  from_end: bool = False) -> 'str | None':
    """Row *i* taken out of the container and handed back: `data.pop(2)`.

    The one line this menu writes that changes what everything downstream
    sees. Delete writes the list without a row and Extract writes the row;
    `.pop` does both to the list already there, which is what anyone reading
    the line expects of it and the reason it is worth a row of its own beside
    two that nearly say it.

    `data.pop(-1)` off the last row -- the same row, said the way the row was
    asked for, and the only naming that goes on meaning the last one once the
    list grows. There is no shorter form for any other row: bare `.pop()` IS
    the last one, so a numbered row has its number written out.

    A dict pops by key, through the same key expression its cells are
    addressed by, with the positional fallback for a key that has no source
    form -- as `_row_without_expr` does, so the row a pop takes and the row a
    delete leaves out cannot come to be different rows. It answers the VALUE
    it took out where the rest of this menu answers the entry: `d.pop('b')` is
    the one form anyone writes for taking an entry out, and nobody reading it
    expects a pair back.
    """
    source_expr = model.get('_source_expr')
    if source_expr is None:
        return None
    src = _atomize(source_expr)
    if _is_dict_binds(_model_binds(model)):
        return f'{src}.pop({_cell_binds(source_expr, i, lst)[0]["k"]})'
    return f'{src}.pop({-1 if from_end else i})'


def _row_match_literal(model: dict, lst, i: int) -> 'str | None':
    """Row *i*'s value as Python source to compare against, or None where there
    is none to write.

    The tally's test, asked of a whole row rather than of one column's value:
    most objects have no literal, since their repr describes them rather than
    spelling them out, and a value that isn't equal to itself would match
    nothing anyway.

    A dict answers None whatever it holds. Its entries are unique by key, so
    every entry equal to this one IS this one -- Delete Entry under a second
    name, and a menu offering the same line twice is offering a choice that
    isn't one.
    """
    if _is_dict_binds(_model_binds(model)):
        return None
    try:
        value = lst[i]
    except Exception:
        return None
    try:
        return _tally_literal(value)
    except Exception:
        return None


def _row_delete_matching_expr(model: dict, lst, i: int) -> 'str | None':
    """The container with every row equal to row *i* left out.

    A comprehension rather than a slice: what it takes out is a VALUE, and
    where that value sits (or how many times) is exactly what the line is not
    written in terms of. So the same line comes out of whichever of the equal
    rows the user reached for.

    `!=` against the row's own literal -- the one `_row_match_literal` reads, so
    the label naming the value and the line comparing against it are the same
    text.
    """
    source_expr = model.get('_source_expr')
    literal = _row_match_literal(model, lst, i)
    if source_expr is None or literal is None:
        return None
    return f'[item for item in {_atomize(source_expr)} if item != {literal}]'


def _row_headers_expr(model: dict, lst, i: int) -> 'str | None':
    """The rows under row *i*, keyed by row *i*'s own values: what a list of
    lists straight out of a CSV reader wants to be.

    The rows it names are every OTHER row, which is the list Delete Row already
    knows how to write -- so the two cannot come to disagree about what is left
    once a row is spoken for.

    `dict(zip(...))` rather than a comprehension over the pairs: it is the
    spelling anyone would reach for, and it is shorter. Inert where the row
    would not zip -- a dict has no row of headers to find, and zipping a number
    or a string is a line that cannot run or one that runs character by
    character.
    """
    if _is_dict_binds(_model_binds(model)):
        return None
    header = _row_item_expr(model, lst, i)
    rest = _row_without_expr(model, lst, i)
    if header is None or rest is None:
        return None
    try:
        if not isinstance(lst[i], (list, tuple)):
            return None
    except Exception:
        return None
    return f'[dict(zip({header}, item)) for item in {rest}]'


def _row_action_label(action: str, model: dict, lst, i: int) -> str:
    """What a row of the menu reads as, naming the row it is about.

    Every row says which row, rather than the menu saying it once: the panel is
    hoisted out of the table and can end up anywhere on screen, so a row read on
    its own has to say what it means.

    An item is an item (or a dict's entry); a row of cells is a row, which is a
    fact about the table rather than about what it is drawing.
    """
    word = _item_word(model).capitalize()
    # One column is handed over bare (see _row_tuple_expr), so the label
    # doesn't promise a tuple that isn't written.
    as_tuple = (' as Tuple'
                if len(_leaf_columns(model.get('columns') or {})) > 1 else '')
    # The one row named by a value instead of a number, so it has to show the
    # value -- shortened, because a row of a table is a whole record often
    # enough that its repr would run off the side of the menu. Read off the same
    # literal the line compares against, so the two can't name different values;
    # empty for every other row, which asks after a position and never reads it.
    # Only ever plural where `word` is "item": a dict is offered no such row.
    match = truncate_str(_row_match_literal(model, lst, i) or '',
                         ROW_MATCH_LABEL_LEN)
    return {
        'last_delete': f'Delete Last {word}',
        'last_pop': f'Pop Last {word}',
        'last_item': f'Extract Last {word}',
        'last_cells': f'Extract Last Row Cells{as_tuple}',
        'delete': f'Delete {word} {i}',
        'delete_matching': f'Delete {match} {word}s',
        'pop': f'Pop {word} {i}',
        'item': f'Extract {word} {i}',
        'cells': f'Extract Row {i} Cells{as_tuple}',
        'headers': f'Use {word} {i} as Headers',
    }.get(action, '')


def _row_action_code(action: str, model: dict, lst, i: int,
                     parts=None) -> 'str | None':
    """The line one row of the menu writes, or None where there is none.

    The end-relative rows answer None off the last row, which is the same
    answer the menu draws when it leaves them out -- so a click that arrives
    for one anyway (a stale panel, a list that has since grown) writes nothing
    rather than a line about a row it was never offered for.

    *parts* is a `_row_column_exprs` cache for the NUMBERED cells row only; the
    end-relative one names its cells differently and asks for its own.
    """
    from_end = action in LAST_ROW_ACTIONS
    if from_end and not _names_from_end(model, lst, i):
        return None
    if action in ('delete', 'last_delete'):
        return _row_without_expr(model, lst, i, from_end)
    if action == 'delete_matching':
        return _row_delete_matching_expr(model, lst, i)
    if action in ('pop', 'last_pop'):
        return _row_pop_expr(model, lst, i, from_end)
    if action in ('item', 'last_item'):
        return _row_item_expr(model, lst, i, from_end)
    if action == 'cells':
        return _row_tuple_expr(model, lst, i, parts)
    if action == 'last_cells':
        return _row_tuple_expr(model, lst, i, from_end=True)
    if action == 'headers':
        return _row_headers_expr(model, lst, i)
    return None


def _drop_repeats(rows: list) -> list:
    """Whatever of *rows* says something the rows before it haven't.

    A row's item and its cells are the same expression whenever the table draws
    one column and that column is `$` -- and for a dict, whenever it draws `$k`
    and `$v` side by side, which IS the entry. Offering the same code twice
    under two names is offering the user a choice that isn't one.

    Rows carrying no code are left where they are: they say what CAN'T be
    written here, which two of them can do without repeating each other.
    """
    seen, out = set(), []
    for row in rows:
        code = row[-1]
        if code is not None:
            if code in seen:
                continue
            seen.add(code)
        out.append(row)
    return out


def _row_asks(action: str, model: dict, lst, i: int) -> bool:
    """Whether the menu puts this question to row *i* at all.

    Two rows are left out entirely rather than drawn inert where they don't
    apply, because neither is a question this row was asked and answered
    nothing to: an ordinary row is not a last row, and a row with no literal
    has no value for the menu to name in the label -- the row would read
    `Delete  Items` and say nothing at all.

    Every other row stands whatever it can write, so one with no line still
    says what can't be written here (see _render_row_menu's unselectable).
    """
    if action in LAST_ROW_ACTIONS:
        return _names_from_end(model, lst, i)
    if action == 'delete_matching':
        return _row_match_literal(model, lst, i) is not None
    return True


def _row_actions(model: dict, lst, i: int,
                 parts=None) -> List[Tuple[str, str, Optional[str]]]:
    """`(action, label, code)` per row of the row ▾ menu, in menu order.

    The one description of what a row can be written into: the menu draws
    itself from this, the handle on the number is built out of the same
    answers, and the click reads it back rather than working the line out a
    second time.
    """
    return _drop_repeats([
        (action, _row_action_label(action, model, lst, i),
         _row_action_code(action, model, lst, i, parts))
        for action in ROW_ACTIONS if _row_asks(action, model, lst, i)])


def _row_handle_exprs(model: dict, lst, i: int, parts=None) -> List[PyExp]:
    """What the drag handle on a row's number offers, in the order the tooltip
    stacks them. The first is what a drag hands over.

    Two readings of the row -- the cells on screen, and the item behind them --
    because a table showing three of a record's ten fields can be asked for
    either and the handle has no way of knowing which was meant. The cells come
    first: the handle sits on a row of the table, and the table is the columns.

    For the last row of a list, the two end-relative readings come ahead of
    both, so the drag hands over `[-1]` there. That is the naming the cells of
    that row are handed as well, and the only one that goes on meaning the same
    row once the list grows.
    """
    word = _item_word(model)
    rows = []
    if _names_from_end(model, lst, i):
        rows += [("Last row's cells",
                  _row_tuple_expr(model, lst, i, from_end=True)),
                 (f'Last {word}', _row_item_expr(model, lst, i, from_end=True))]
    rows += [("Row's cells", _row_tuple_expr(model, lst, i, parts)),
             (word.capitalize(), _row_item_expr(model, lst, i))]
    return [PyExp(code, label=label)
            for label, code in _drop_repeats(rows) if code is not None]


def _row_action_name(action: str, model: dict, source_expr: str, i: int) -> str:
    """What to call the line a row of the menu writes."""
    _has_var, base = _name_context_for_source(source_expr)
    return _ROW_ACTION_NAMES[action].format(base=base, word=_item_word(model),
                                            i=i)


# =============================================================================
# Convert type
# =============================================================================
#
# The Convert Type submenu of a column's ▾ menu wraps the column's own
# expression -- `$['n']` becomes `int($['n'])` -- so the cells, the search, the
# tally and every aggregation read the converted values without one of them
# being told about it. Nothing here touches the line the table is showing: a
# conversion says how one COLUMN reads, where a sort says what order the rows
# arrive in and so has to be written where the rows come from.
#
# So, as in Sort, the checkboxes are not model state. Which one is ticked is read
# back out of the column expression, and there is nowhere for the two to
# disagree; a conversion the user typed by hand ticks the box that describes it.
#
# The rows under the separator write the converted column BESIDE the original,
# which is the one thing the checkbox cannot do: keep both readings on screen at
# once, and keep the original's searches and aggregations while doing it.

# The types the submenu offers, in the order it offers them. Python's own
# one-argument constructors, so the code a row writes is the code anyone would
# type -- and the row's name is the function's.
CONVERT_TYPES = ('int', 'float', 'str', 'bool')


def _dollar_probe(expr: str) -> tuple:
    """*expr* with every dollar run replaced by a name Python can parse, and the
    map back.

    A column expression is not Python -- `$['n']` is a SyntaxError -- so it is
    read through placeholders, and any source segment taken off the parse is
    handed back through the same map. Distinct names rather than one shared
    probe, so `$$` and `$` come back as themselves.

    A dollar that is string content is replaced too, and comes back verbatim for
    the same reason: only the STRUCTURE is read off the parse, and the text is
    always the user's own.
    """
    names = {}

    def probe(m):
        name = f'_snc_dlr{len(names)}_'
        names[name] = m[0]
        return name

    return DOLLARS_RE.sub(probe, expr), names


def _unprobe(text: 'str | None', names: dict) -> 'str | None':
    for name, token in names.items():
        text = text.replace(name, token) if text is not None else None
    return text


def _is_convert_call(node) -> bool:
    """Whether a parsed node is one of the conversions this menu speaks about.

    One argument and no keywords: `int(x, 16)` reads a base, so taking that
    wrapper off would change what the column SAYS rather than what type it reads
    as -- and this menu only ever offers to change the latter.
    """
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in CONVERT_TYPES and len(node.args) == 1
            and not node.keywords)


def _parse_convert(expr: str, is_splat: bool = False) -> 'tuple | None':
    """A conversion read apart as (what it converts, which type), or None when
    the expression isn't one.

    Two shapes, because a splat spread a LIST into rows: `int($['n'])` for the
    one value an ordinary column has per row, and `[int(item2) for item2 in
    $['ns']]` for the elements a splat spreads. Whatever the element is called,
    since _promote_expr names it away from whatever it wraps -- what is checked
    is that the comprehension converts its own element and nothing else, which
    is the only shape the star can be taken back off again.
    """
    probed, names = _dollar_probe(expr)
    try:
        node = ast.parse(probed, mode='eval').body
    except (SyntaxError, ValueError):
        return None
    if is_splat:
        if not (isinstance(node, ast.ListComp) and len(node.generators) == 1):
            return None
        gen = node.generators[0]
        if gen.ifs or gen.is_async or not isinstance(gen.target, ast.Name):
            return None
        if not (_is_convert_call(node.elt)
                and isinstance(node.elt.args[0], ast.Name)
                and node.elt.args[0].id == gen.target.id):
            return None
        inner = _unprobe(ast.get_source_segment(probed, gen.iter), names)
        return None if inner is None else (inner, node.elt.func.id)
    if not _is_convert_call(node):
        return None
    inner = _unprobe(ast.get_source_segment(probed, node.args[0]), names)
    return None if inner is None else (inner, node.func.id)


def _convert_expr(col_expr: str, to: 'str | None') -> str:
    """*col_expr* -- one column's own expression -- reading as *to*, or, with no
    type, with whatever conversion it has taken off.

    Always unwraps first, so picking another type replaces the conversion rather
    than nesting inside it -- the same answer _sort_expr gives a second sort.

    A splat spread a list into rows, so what converts is every ELEMENT of it:
    the star stays where it is and the conversion goes inside, which is the same
    line _promote_expr writes when a sub-column comes out of a splat.
    """
    is_splat, inner = _split_splat(col_expr)
    star = SPLAT if is_splat else ''
    parsed = _parse_convert(inner, is_splat)
    if parsed is not None:
        inner = parsed[0]
    if to is None:
        return f'{star}{inner}'
    if is_splat:
        return f'{star}{_promote_expr(f"{to}($)", f"{SPLAT}{inner}")}'
    return f'{to}({inner})'


def _converted_type(col_expr: str) -> 'str | None':
    """Which type a column already reads as, or None -- the checkbox, read off
    the expression rather than out of the model."""
    is_splat, inner = _split_splat(col_expr)
    parsed = _parse_convert(inner, is_splat)
    return parsed[1] if parsed else None


def _convert_target(col: str, to: 'str | None') -> tuple:
    """(the column's own expression converted, the identity it would then have).

    A column is written in the scope its parent hands out, so what converts is
    the LAST segment of the key: the whole expression for a column of the table,
    the sub-column's own expression for one drawn under another.
    """
    path = col.split(SUBCOL_SEP)
    seg = _convert_expr(path[-1], to)
    return seg, SUBCOL_SEP.join(path[:-1] + [seg])


def _convert_writable(columns, col: str, seg: str) -> bool:
    """Whether *col* can be written as *seg* where it lives.

    False when a sibling already reads that way: two columns would share one
    identity, and the second would be a cell nothing could tell from the first.
    What dims a row rather than letting the click land on nothing.
    """
    siblings = _siblings_of(columns, col)
    return (siblings is not None and col.split(SUBCOL_SEP)[-1] in siblings
            and seg not in siblings)


def _convert_values_expr(columns, col: str, to: str, source_expr: 'str | None',
                         binds: 'dict | None' = None) -> 'str | None':
    """Every value the column would have once converted, as one expression --
    what a Convert Type row hands to a drag.

    Asked of the columns as they WOULD read rather than assembled here: a column
    under a splat is keyed by an identity that means nothing on its own, and the
    ordinary whole-column question already knows how to flatten one. So the
    conversion is written into a copy of the config and the same question asked
    of that.
    """
    if source_expr is None:
        return None
    path = col.split(SUBCOL_SEP)
    seg, converted = _convert_target(col, to)
    # A column that already reads that way is its own answer -- and renaming it
    # to the name it has would be refused as a duplicate.
    if seg == path[-1]:
        return _column_whole_expr(columns, col, source_expr, binds)
    cols = copy.deepcopy(columns)
    siblings = _siblings_of(cols, col)
    if siblings is None or path[-1] not in siblings:
        return None
    if not _col_rename_at(siblings, list(siblings).index(path[-1]), seg):
        return None
    return _column_whole_expr(cols, converted, source_expr, binds)


def _convert_column(model, col: str, to: 'str | None', eval_in_scope=None) -> bool:
    """Rewrite a column's own expression, keeping its place and what it carries.

    The clean-up a rename anywhere needs: the cells are keyed by the column, and
    so are the search and the aggregations. The search was written against the
    old expression and goes with it; the aggregations describe the column rather
    than filtering it, so they follow it over.
    """
    columns = model['columns']
    seg, converted = _convert_target(col, to)
    if not _convert_writable(columns, col, seg):
        return False
    # Both questions _col_rename_at can refuse on -- is the column there, is the
    # new name taken -- are the two _convert_writable just asked.
    siblings = _siblings_of(columns, col)
    _col_rename_at(siblings, list(siblings).index(col.split(SUBCOL_SEP)[-1]), seg)
    # The composed identity rather than the bare segment: a sub-column's cells,
    # search and aggregations are all keyed by the identity it is DRAWN under.
    _rename_column_children(model, col, converted)
    _remove_column_search(model, col)
    _rename_column_compute(model, col, converted)
    _recompose_search(model, eval_in_scope)
    return True


def _repoint_column_menus(model, old: str, new: str) -> None:
    """Keep the open menu on a column whose identity has just changed.

    A menu id names its column (see _menu_id), so a conversion would otherwise
    leave the menu open on a column no longer there -- and the checkbox that
    made it invites the next click straight after.

    The KIND is whatever the id said it was, so the column menu and whichever
    submenu is open both survive without either being named here.
    """
    def repointed(at):
        return (at[:-len(old)] + new
                if isinstance(at, str) and at.endswith(f'-{old}') else at)

    model['col_search_dropdown'] = repointed(model.get('col_search_dropdown'))
    open_dropdown = model.get('openDropdown')
    if isinstance(open_dropdown, dict):
        model['openDropdown'] = {**open_dropdown,
                                 'id': repointed(open_dropdown.get('id'))}


# =============================================================================
# Column compute
# =============================================================================
#
# The Compute submenu of a column's ▾ menu asks questions about the column as a
# whole: how many distinct values, the mean, the largest and which row holds it.
# Every row previews its answer, so reading one costs nothing; checking it keeps
# the answer on screen as a cell under the column.
#
# An aggregation IS its expression, written with `$` for the column -- the same
# `$` an arbitrary user-written aggregation will use. That one string is what is
# stored, what the preview evaluates, and what a drag hands to the file, so
# there is no way for the number on screen and the code in the file to drift.

# The aggregations the submenu lists, in the order it lists them. A `{{...}}` is
# a text box, and what's typed in it is part of the expression.
#
# `$` is the column, as everywhere else; `$$` is the list the column was read
# out of. Min Item and Max Item answer with a row of that list rather than a
# value of their own, and are drawn as a whole row of the table -- see
# _agg_is_row. They ask their question row by row, so the `$` in them is the
# column read off the row their key is handed rather than every value at once.
#
# An aggregation may carry the whole line it writes rather than the question
# alone, when the line is what everyone types by hand. np.histogram answers with
# a pair, and a pair is read by giving its halves names; so the names come along,
# and what the row computes is the question on the right of the `=` (_agg_expr).
#
# min and max stay builtins: shorter than numpy's, and they answer for strings
# and dates too. The rest borrow numpy, which is the shorter and more familiar
# way to write them down.
HISTOGRAM_AGG = 'counts, edges = np.histogram($, bins={{10}})'

# The two that answer with a row of the list. `min`/`max` with a key, which is
# how anyone picks a row out of a list by hand: no numpy to import, no coercing
# a column of mixed types into an order it doesn't have, and the row itself
# rather than a number to look it up by. `$` is the key's own row -- these are
# the only aggregations that read the column one row at a time.
ROW_AGGS = ('min($$, key=lambda item: $)', 'max($$, key=lambda item: $)')

# The same two for a column that names the row's number: there is none inside
# `lambda item:`, so the key runs over the row numbers instead. What such a key
# finds IS the number, so that is written down first and the row read back out
# of it -- an aggregation still answers with a row of the list, whichever way it
# found one, and the number beside it is the one it found rather than a lookup
# after the fact. _agg_row_template is where the choice is made.
# Iterating a dict yields KEYS, so a row aggregation over one has to name the
# items explicitly -- otherwise min() answers confidently with the wrong row.
ROW_AGGS_DICT = ('min($$.items(), key=lambda item: $)',
                 'max($$.items(), key=lambda item: $)')
ROW_AGGS_BY_INDEX_DICT = tuple(f'list($$.items())[{expr}]'
                               for expr in ('min(range(len($$)), key=lambda i: $)',
                                            'max(range(len($$)), key=lambda i: $)'))

# The list template a dict's row aggregation is written as instead.
_ROW_AGG_DICT_FORM = dict(zip(ROW_AGGS, ROW_AGGS_DICT))

ROW_AGG_INDEXES = ('min(range(len($$)), key=lambda i: $)',
                   'max(range(len($$)), key=lambda i: $)')
ROW_AGGS_BY_INDEX = tuple(f'$$[{expr}]' for expr in ROW_AGG_INDEXES)

COMPUTE_AGGS = (
    ('# Unique',         'len(set($))'),
    ('# Present',        'sum(x is not None for x in $)'),
    ('# Missing',        'sum(x is None for x in $)'),
    ('# NaN',            'sum(math.isnan(x) for x in $)'),
    ('Sum',             'sum($)'),
    ('Min',             'min($)'),
    ('Min Idx',         'np.argmin($)'),
    ('Min Item',        ROW_AGGS[0]),
    ('Mean',            'np.mean($)'),
    ('Stddev (Pop)',    'np.std($)'),
    ('Stddev (Sample)', 'np.std($, ddof=1)'),
    ('Median',          'np.median($)'),
    ('Percentile',      'np.percentile($, {{10}})'),
    ('Percentile',      'np.percentile($, {{90}})'),
    ('Max',             'max($)'),
    ('Max Idx',         'np.argmax($)'),
    ('Max Item',        ROW_AGGS[1]),
    ('Histogram',       HISTOGRAM_AGG),
)

# The rest of the submenu: questions whose answer is a whole list rather than a
# value, so there is no cell small enough to keep one in. Clicking writes the
# line, the way an action button does; each is a name, the expression it is, and
# what to call the line it writes.
COMPUTE_CODES = (
    ('Unique', 'set($)',     'unique'),
    ('Tally',  'Counter($)', 'tally'),
)

# The second box on a splatted column's Compute rows. The first asks the whole
# column and keeps one answer under the table; this one asks each group of it,
# and one answer per group is a column.
COMPUTE_PER_GROUP_TOOLTIP = 'A column of this, one answer per group'

# What the histogram's box says of itself. The other boxes in the submenu read
# off the name beside them -- the number in Percentile's box is the percentile
# -- but "Histogram 10" doesn't say what the 10 counts.
HISTOGRAM_BINS_TOOLTIP = 'Bin Count'


def _compute_scope(binds: 'dict | None' = None,
                   column_expr: 'str | None' = None,
                   source_expr: 'str | None' = None) -> DollarScope:
    """The scope an AGGREGATION is written in: the Compute box, and the box that
    labels the cell one of them makes.

    No sigils, and `$$$` nowhere: an aggregation is handed the column's values
    and the container they came out of (see _agg_eval, which binds exactly those
    two), and nothing about one row, there being no one row to ask about.
    """
    return DollarScope(
        Dollar('$', 'this whole column', column_expr),
        Dollar('$$', 'the whole original dict' if _is_dict_binds(binds)
               else 'the whole original list', source_expr),
    )

# A question this column can't answer -- an empty column, a mean of strings, a
# box holding something that isn't a number. Its own object rather than None,
# which an aggregation is free to return, or a string, which `min` of a column
# of strings is free to return.
NO_ANSWER = object()

_HOLE_RE = re.compile(r'\{\{(.*?)\}\}')


def _agg_holes(template: str) -> List[str]:
    """What's in an expression's boxes, in the order they read."""
    return _HOLE_RE.findall(template)


def _agg_fill(template: str) -> str:
    """The expression itself, with the braces around each box dropped."""
    return _HOLE_RE.sub(lambda m: m.group(1), template)


def _agg_shape(template: str) -> str:
    """An expression with its boxes emptied: what tells a percentile from a
    median without saying which percentile."""
    return _HOLE_RE.sub('{{}}', template)


# A name, or a list of them, answered into at the head of a line. The negative
# lookahead keeps `==` out of it, and requiring the `=` to follow the names
# directly keeps `<=`, `!=` and `+=` out too: those are questions, not answers.
_AGG_TARGETS_RE = re.compile(r'^[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*=(?!=)')


def _agg_expr(template: str) -> str:
    """The question an aggregation asks, without the names it answers into.

    An aggregation that carries the whole line it writes -- `counts, edges =
    np.histogram($, bins=10)`, which is how a pair is read -- is asking what is
    on the right of the `=`. The names are where the line puts the answer, and
    that is the only place the code and the question differ: everything else
    reads the template as it stands.
    """
    return _AGG_TARGETS_RE.sub('', template).lstrip()


def _agg_set_hole(template: str, hole: int, value: str) -> str:
    """The expression with one box rewritten.

    Braces typed into a box are dropped: they would close the box early and
    leave the template holding two of them.
    """
    value = value.replace('{', '').replace('}', '')
    index = [-1]

    def replace(match):
        index[0] += 1
        return f'{{{{{value}}}}}' if index[0] == hole else match.group(0)

    return _HOLE_RE.sub(replace, template)


def _agg_is_row(template: str) -> bool:
    """Whether an aggregation answers with a row of the list rather than a
    value of its own, and so is drawn as a whole row of the table.

    By shape against ROW_AGGS, the way _agg_is_histogram knows a histogram --
    not by anything structural about the expression. The free-form box promises
    that `$` is the whole column and `$$` the list, so an aggregation the user
    wrote that happens to name the list is still asked of the column at once;
    only these two ask row by row, and only because the catalog says so.
    """
    shape = _agg_shape(template)
    return any(_agg_shape(known) == shape for known in ROW_AGGS)


def _agg_by_index(template: str, col: str, shapes) -> str | None:
    """The *shapes* entry matching *template*, when the column is one that has
    to be keyed over the row numbers -- or None when it isn't.

    By shape against ROW_AGGS, the way _agg_is_row knows a row aggregation at
    all. Only a column naming `$i` needs the other shapes, so every column that
    doesn't is left with the ones everyone writes by hand.
    """
    if not dollar_expr_names_index(col):
        return None
    shape = _agg_shape(template)
    for known, by_index in zip(ROW_AGGS, shapes):
        if _agg_shape(known) == shape:
            return by_index
    return None


def _agg_row_template(template: str, col: str, binds: 'dict | None' = None) -> str:
    """A row aggregation's shape for the column it is asked of."""
    if _is_dict_binds(binds):
        return (_agg_by_index(template, col, ROW_AGGS_BY_INDEX_DICT)
                or _ROW_AGG_DICT_FORM.get(template, template))
    return _agg_by_index(template, col, ROW_AGGS_BY_INDEX) or template


def _agg_row_key_expr(col: str, source_expr: str,
                      binds: 'dict | None' = None) -> str:
    """What `$` stands for in a row aggregation: the column read off the row its
    key is handed.

    Reached through the row number when the column names one, since that is what
    such a key is handed instead -- see ROW_AGGS_BY_INDEX.
    """
    if _is_dict_binds(binds):
        # The lambda binds one pair, so the column reads through it -- and a
        # column naming $i is handed the row NUMBER instead, which reaches its
        # pair through list(d.items())[i] rather than d[i] (a key lookup, and
        # silently wrong or a KeyError).
        if not dollar_expr_names_index(col):
            return _column_key_expr(col, source_expr, item_expr='item',
                                    binds=_SORT_PAIR_BINDS)
        src = _atomize(source_expr)
        return _column_key_expr(
            col, source_expr, item_expr=f'list({src}.items())[i]',
            binds={'i': 'i', 'k': f'list({src})[i]',
                   'v': f'list({src}.values())[i]'})
    if not dollar_expr_names_index(col):
        return _column_key_expr(col, source_expr)
    return _column_key_expr(col, source_expr,
                            item_expr=f'{_atomize(source_expr)}[i]',
                            binds=_LIST_BINDS)


def _agg_row_index_code(item_code: str, source_expr: str,
                        template: str = None, col: str = None,
                        binds: 'dict | None' = None) -> str:
    """The index of the row a row aggregation picked: the list's own index of
    it, written around the code that picked it.

    `data.index(min(data, key=lambda item: item['b']))`. Around rather than
    beside, so the row the cells read and the number the index cell hands over
    cannot name different rows. `.index` finds the first row equal to it, which
    is the row `min` returned -- an earlier equal row has an equal key, so
    `min` would have stopped there.

    That last argument is only good while the key depends on the row alone. A
    column naming `$i` is compared partly BY its number, so an earlier equal row
    has a different key and `min` would not have stopped there -- and the answer
    that key found is the number itself. So it is written down directly and
    nothing is looked up (ROW_AGG_INDEXES).
    """
    by_index = _agg_by_index(template, col, ROW_AGG_INDEXES) if col else None
    if by_index is not None:
        return _agg_code(by_index, _agg_row_key_expr(col, source_expr, binds),
                         source_expr)
    if _is_dict_binds(binds):
        # dicts have no .index at all.
        return f'list({_atomize(source_expr)}.items()).index({item_code})'
    return f'{source_expr}.index({item_code})'


def _agg_row_index(lst, item, template: str = None, col: str = None,
                   eval_in_scope=None):
    """Where a row aggregation's row sits in the list, or NO_ANSWER -- the same
    question _agg_row_index_code writes down, asked here."""
    by_index = _agg_by_index(template, col, ROW_AGG_INDEXES) if col else None
    if by_index is not None:
        return _agg_eval(by_index, _agg_row_key_expr(col, '_lst', _binds_for(lst)),
                         None, lst,
                         eval_in_scope)
    try:
        # A dict has no .index at all, and its rows are its items -- the same
        # pair a row aggregation over one answers with, and the same lookup
        # _agg_row_index_code writes down for it.
        if isinstance(lst, dict):
            return list(lst.items()).index(item)
        return lst.index(item)
    except Exception:
        return NO_ANSWER





def _agg_imports(template: str) -> Tuple[str, ...]:
    """The imports an aggregation needs, off the template rather than the code
    a column fills it out into: `np.mean($)` says numpy whatever the `$` turns
    out to be, which is what a row of the menu has to answer with. Whatever the
    column itself needs comes from reading that code, wherever it is written."""
    return imports_for_code(_agg_fill(template))


def _agg_name(template: str) -> Optional[str]:
    """What a row and its cell read an expression as: the catalog's word for it
    -- `Percentile` -- or None when the catalog has no word for it, an
    expression the user wrote having no name but itself.

    By shape, so a percentile of any level is named Percentile. The number is
    what the box beside the name reads, not part of the name: it is the user's,
    and everything of theirs is a box wherever it is drawn.
    """
    shape = _agg_shape(template)
    for label, known in COMPUTE_AGGS:
        if _agg_shape(known) == shape:
            return label
    return None


def _agg_is_free(template: str) -> bool:
    """Whether an expression is one the user wrote themselves.

    Nothing marks it as theirs: a free-form aggregation is simply an expression
    no row of the catalog already reads, which is why one that happens to be
    written the same way as Min *is* Min and ticks that row. An empty box has
    written nothing yet, and counts as theirs until it does.
    """
    return _agg_name(template) is None


def _agg_order(template: str) -> int:
    """Where an expression sits in the menu, so a column's cells read down in
    the order its rows read.

    By shape, so a percentile of any level sorts where percentiles do -- and so
    the two of them, which no shape can tell apart, are left in the order they
    were asked for. An expression the catalog doesn't know goes last.
    """
    shape = _agg_shape(template)
    for i, (_, known) in enumerate(COMPUTE_AGGS):
        if _agg_shape(known) == shape:
            return i
    return len(COMPUTE_AGGS)


def _compute_rows(model: dict, col: str) -> List[Tuple[str, str, bool]]:
    """The Compute submenu's rows: a name, the expression the row is showing,
    and whether it's checked.

    All of it read back out of the column's list of aggregations, which is the
    only record of what is checked -- the way the tally reads its checkboxes
    back out of the search.

    A row pairs with a stored expression it matches exactly, and failing that
    with the first one of its shape nothing else has claimed. So `{{90}}` ticks
    the row that reads 90 rather than the one that reads 10, and a percentile
    edited to 25 ticks the first percentile row instead of adding a twelfth one
    -- and unchecking it leaves that row reading 10 again rather than taking it
    away while the user is looking at it.
    """
    stored = _column_computes(model, col)
    claimed = [False] * len(stored)
    paired: List[Optional[str]] = [None] * len(COMPUTE_AGGS)

    def claim(matches):
        for ri, (_, template) in enumerate(COMPUTE_AGGS):
            if paired[ri] is not None:
                continue
            for si, expr in enumerate(stored):
                if not claimed[si] and matches(template, expr):
                    claimed[si], paired[ri] = True, expr
                    break

    claim(lambda template, expr: template == expr)
    claim(lambda template, expr: _agg_shape(template) == _agg_shape(expr))

    rows = []
    for ri, (label, template) in enumerate(COMPUTE_AGGS):
        expr = paired[ri]
        rows.append((label, template if expr is None else expr,
                     expr is not None))
    return rows


def _compute_free_rows(model: dict, col: str) -> List[str]:
    """The submenu's last rows: the aggregations the user wrote themselves, and
    an empty box after them to write another in.

    In the order their cells read, since the box is the aggregation and the cell
    it made carries the same box.
    """
    return [expr for expr in _column_computes(model, col)
            if _agg_is_free(expr)] + ['']


def _compute_code_name(template: str, source_expr: str) -> str:
    """What to call the line a code row writes -- `data_tally` for a Tally of
    `data`, the way the action buttons name what they write."""
    _has_var, base = _name_context_for_source(source_expr)
    for _label, known, suffix in COMPUTE_CODES:
        if known == template:
            return f'{base}_{suffix}'
    return base


_numpy_module = None


def _numpy():
    """numpy, imported the first time something actually needs it.

    Never at module import: every run pays for that one, and most of them never
    open a Compute menu. numpy_visualizer.py avoids it for the same reason.
    """
    global _numpy_module
    if _numpy_module is None:
        import numpy
        _numpy_module = numpy
    return _numpy_module


def _agg_eval(body: str, column_expr: str, values, lst, eval_in_scope=None):
    """One aggregation body asked of a column and the list it came out of, or
    NO_ANSWER. *column_expr* is what `$` stands for and `_lst` what `$$` does.

    Evaluated in the user's scope, so a column expression that named the
    program's own values has already been read by the time we get here -- but
    `np` and `math` are handed in rather than looked up, so the answer doesn't
    depend on the file having imported them (or on what it called numpy if it
    did) -- the same two names _agg_imports writes an import for.

    Anything at all can go wrong here -- an expression that doesn't parse, a
    mean of strings, a numpy that isn't installed -- and none of it is worth
    more than a row with nothing to show.

    A warning counts as going wrong, for two reasons: numpy warns rather than
    raises where it has no answer (the mean of an empty column is a warning and
    a nan), and a warning would otherwise be printed into the output of the
    user's own program by a menu they only opened to look at.
    """
    try:
        levels = _compute_scope(column_expr=column_expr,
                                source_expr='_lst').replace_exps
        code = (f'lambda np, math, _v, _lst: '
                f'{replace_dollars_in_py_exp(body, levels)}')
        agg = eval_in_scope(code) if eval_in_scope is not None else eval(code)
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            return agg(_numpy(), math, values, lst)
    except Exception:
        return NO_ANSWER


def _agg_value(template: str, values: list, eval_in_scope=None, lst=None,
               col: str = '$'):
    """An aggregation's answer for a column's values, or NO_ANSWER.

    *lst* is the list the column was read out of, which is what a row
    aggregation orders; one that isn't handed a list has nothing to answer
    with, which is NO_ANSWER like any other question it can't answer.

    *col* is what a row aggregation reads off each row -- it asks its question
    row by row rather than of every value at once -- so it is read here against
    the names this lambda binds rather than against the source expression a
    drag would name. Defaulted to the column that is the row.
    """
    binds = _binds_for(lst) if lst is not None else None
    return _agg_eval(_agg_expr(_agg_fill(_agg_row_template(template, col, binds))),
                     (_agg_row_key_expr(col, '_lst', binds)
                      if _agg_is_row(template) else '_v'),
                     values, lst, eval_in_scope)


def _agg_code(template: str, column_expr: str, source_expr: str = None) -> str:
    """The expression itself, with `$` bound to the column and `$$` to the list
    the column was read out of.

    *column_expr* is what `$` stands for, which the caller knows because it
    knows the column: every value the column has -- the same list expression
    the column header hands to a drag -- or, for a row aggregation, the column
    read off one row. _agg_column_expr is where that choice is made.
    """
    # _compute_scope's levels, taken off the same declaration the Compute box
    # reads its tooltip off -- and it truncates at a source it can't name, which
    # is what "$$ is not bound here" has to look like on both sides.
    levels = _compute_scope(column_expr=column_expr,
                            source_expr=source_expr).replace_exps
    return replace_dollars_in_py_exp(_agg_fill(template), levels)


def _agg_column_expr(template: str, col: str, source_expr: str,
                     binds: 'dict | None' = None, columns=None) -> 'str | None':
    """What `$` stands for in an aggregation over *col*: every value the column
    has, or -- for a row aggregation, which asks row by row -- the column read
    off the row its key is handed.

    None when a row aggregation is asked of a column that spreads its value into
    rows: the question is which ROW of the list is the extreme one, and a splat
    column's rows are its own elements rather than the list's.
    """
    if not _agg_is_row(template):
        return _column_whole_expr(columns, col, source_expr, binds)
    reads = _agg_row_reads(col, columns)
    return None if reads is None else _agg_row_key_expr(reads, source_expr, binds)


def _agg_row_reads(col: str, columns=None) -> 'str | None':
    """The expression a row aggregation reads a column by -- row-scoped,
    because that is what its key is handed one of."""
    return col if columns is None else _column_row_expr(columns, col)


def _agg_col_code(template: str, col: str, source_expr: str,
                  binds: 'dict | None' = None, columns=None) -> 'str | None':
    """An aggregation's expression for one column of one list, or None when the
    column cannot be asked that question.

    The one place a column and an aggregation are put together, so what a cell
    hands over, what a menu row hands over, and what an event coming back is
    rebound onto cannot say different things.
    """
    column_expr = _agg_column_expr(template, col, source_expr, binds, columns)
    if column_expr is None:
        return None
    reads = _agg_row_reads(col, columns) if _agg_is_row(template) else col
    return _agg_code(_agg_row_template(template, reads or col, binds),
                     column_expr, source_expr)


# === Per-group aggregations ===================================================
#
# A column that splatted can be asked the same question two ways: of the whole
# column, whose answer is one value and lives in a cell under the table, and of
# each group, whose answer is one value PER GROUP -- and a group is a row of this
# table, so that is a column.
#
# Written as one it lands at the level its group is a row of: a leaf one splat
# deep answers per root row, which is a column of the table; a leaf two deep
# answers per element of the outer splat, which is a sub-column of it. So it
# rowspans its group because that is what a column at that depth already does,
# and there is no drawing code here at all.
#
# And being a column it can be sorted on, searched, tallied, converted,
# aggregated again, dragged elsewhere, and taken away by its own ▾ menu -- which
# is the whole reason for writing it as one. Nothing stores it: the column is the
# only record, the way a free-form aggregation is nothing but the expression it
# is, so the box is checked by finding one and unticking is taking it away.


def _leaf_splat_target(leaf: LeafColumn) -> 'str | None':
    """The menu target of the splat a leaf's group is spread by -- the innermost
    splat in its header path, ancestors and all.

    Where a per-group answer goes: among that splat's own siblings, which is the
    scope the answer is written in and the only one it reads correctly in.
    """
    path = leaf.header
    for i in range(len(path) - 1, -1, -1):
        if _split_splat(path[i])[0]:
            return SUBCOL_SEP.join(path[:i + 1])
    return None


def _group_agg_column(leaf: LeafColumn, template: str) -> 'str | None':
    """A per-group aggregation as the COLUMN it is, or None when there is no
    honest one to write.

    The whole-column aggregation asked of the group as if the group were the
    list:

        sum([item2['n'] for item2 in $v])
        min($v, key=lambda item: item2['n'])

    `_agg_expr` first, because an aggregation may carry the whole line it writes
    -- `counts, edges = np.histogram(...)` -- and a column is the question on the
    right of the `=`.

    The element is named by its LEVEL rather than `item`, the way a sub-column
    promoted out of a splat is (see _promote_expr). This column is read once per
    row, so anything wrapping it binds the row -- and `sorted(d.items(),
    key=lambda item: sum([item['n'] for item in item[1]]))`, which is what Sort
    writes over one, is correct Python that reads like a bug. A splat showing
    its own elements needs no comprehension at all: the group IS the column, so
    it is asked after directly rather than spread into a name.

    None for a column that names where its row sits: `$i` is the ROOT row's
    number and `$j` the position within the group, and neither is a number the
    group counts in -- so there is nothing to write and the box isn't offered.
    """
    if leaf.splat is None or not leaf.chain:
        return None
    sub = leaf.sub or '$'
    if dollar_expr_sigils(sub) & {'i', 'j'}:
        return None
    # The group's own list, in the scope the answer will be read in: the splat's
    # inner expression, which is written against exactly that scope.
    group = _split_splat(leaf.chain[-1])[1]
    # A row aggregation reads the column one row at a time, so `$` is the column
    # off the key's own row rather than every value at once -- which is what
    # _agg_col_code already knows how to write, and what the catalog's own
    # `lambda item:` binds.
    if _agg_is_row(template):
        return _agg_col_code(_agg_expr(template), sub, group)
    values = (group if sub.strip() == '$'
              else _promote_expr(sub, leaf.chain[-1],
                                 _fresh_elem_name(leaf.depth - 1, sub, group)))
    return _agg_code(_agg_expr(template), values, group)


# A name no program has, standing in a box while the question "what would this
# row have written?" is asked -- so the answer can be found again in the column
# and read back out. The two-pass idiom `_promote_expr` uses, for a substitution
# that has to produce a regex rather than code.
_GROUP_AGG_PROBE = '_snc_hole{}_'


def _group_agg_template(expr: str, leaf: LeafColumn,
                        template: str) -> 'str | None':
    """The template *expr* is this leaf's per-group aggregation of, with its
    boxes filled the way the column has them -- or None when the column is not
    that row's answer at all.

    What makes the second box a checkbox without anything being stored: the
    column is the only record, so which box is ticked is read back out of it,
    the way the tally's checkmarks are read out of the column search. A reading
    is accepted only when it composes back character for character, which is
    also what keeps a column the user wrote by hand from being claimed by a row
    that would then take it away.

    The level comes back too, so a column computing the 25th percentile ticks
    the percentile row reading 25 rather than the one the catalog opens with.
    """
    holes = len(_agg_holes(template))
    probed = template
    for i in range(holes):
        probed = _agg_set_hole(probed, i, _GROUP_AGG_PROBE.format(i))
    written = _group_agg_column(leaf, probed)
    if written is None:
        return None
    pattern = re.escape(written)
    for i in range(holes):
        pattern = pattern.replace(re.escape(_GROUP_AGG_PROBE.format(i)), '(.*?)')
    match = re.fullmatch(pattern, expr)
    if match is None:
        return None
    out = template
    for i, text in enumerate(match.groups()):
        out = _agg_set_hole(out, i, text)
    return out


def _group_agg_columns(columns, leaf: LeafColumn) -> dict:
    """The columns beside a leaf's splat that are per-group answers about it, as
    `{column expression: the template it reads as}`, in the order they are drawn.

    The one place the columns are asked what they are, so the box that reads
    checked and the click that unchecks it cannot come to disagree about which
    column is which row's answer.
    """
    target = _leaf_splat_target(leaf)
    siblings = _siblings_of(columns or {}, target) if target else None
    if not siblings:
        return {}
    out = {}
    for expr in siblings:
        for _label, template in COMPUTE_AGGS:
            read = _group_agg_template(expr, leaf, template)
            if read is not None:
                out[expr] = read
                break
    return out


def _group_agg_target(leaf: LeafColumn, expr: str) -> 'str | None':
    """A per-group answer's menu target -- how it is reached, which is its
    splat's own path with the splat itself swapped for the answer, since the two
    are siblings."""
    target = _leaf_splat_target(leaf)
    if target is None:
        return None
    return SUBCOL_SEP.join(target.split(SUBCOL_SEP)[:-1] + [expr])


def _add_group_agg_column(model: dict, leaf: LeafColumn,
                          template: str) -> 'str | None':
    """Put a per-group answer in beside the splat it is about, and say what was
    written -- the caller is the one that has to ask for its imports, and what
    the column needs is read off the column.

    Among that splat's own siblings, and within the block of answers already
    there in the order the submenu lists them -- so a column's answers read down
    the table the way its rows read down the menu. Only at the moment it is
    added: once it is a column it can be dragged like any other, and where the
    user puts it is where it stays.
    """
    expr = _group_agg_column(leaf, template)
    target = _leaf_splat_target(leaf)
    if expr is None or target is None:
        return None
    columns = model['columns']
    siblings = _siblings_of(columns, target)
    if siblings is None or expr in siblings:
        return None
    keys = list(siblings)
    splat_name = target.split(SUBCOL_SEP)[-1]
    at = keys.index(splat_name) + 1 if splat_name in keys else len(keys)
    order = _agg_order(template)
    for sibling, read in _group_agg_columns(columns, leaf).items():
        if sibling not in keys:
            continue
        if _agg_order(read) > order:
            at = min(at, keys.index(sibling))
            break
        at = max(at, keys.index(sibling) + 1)
    return expr if _col_insert(siblings, expr, at) else None


def _regroup_agg_column(model: dict, col: str, template: str, edited: str,
                        eval_in_scope=None) -> bool:
    """Rewrite a per-group answer for a level typed into the row that wrote it.

    The boxes inside a Compute row belong to the row rather than to either of
    its checkboxes, so a percentile edited to 25 has to reach whichever box is
    ticked. Without this the column would go on computing the level it was
    written with, and the row -- now reading 25 -- would show its box unticked
    beside it and add a second column on the next click.

    In place, keeping the column where it sits, since the user is editing the
    answer they can see rather than asking for another one.
    """
    leaf = _leaf_for(model.get('columns') or {}, col)
    if leaf is None:
        return False
    written = _group_agg_column(leaf, edited)
    if written is None:
        return False
    for expr, read in _group_agg_columns(model['columns'], leaf).items():
        if read == template:
            return _rename_column(model, _group_agg_target(leaf, expr),
                                  written, eval_in_scope)
    return False


def _format_agg_value(value) -> str:
    """An answer as cell text.

    Floats are rounded: a cell is read rather than computed against, and
    2.8000000000000003 says nothing 2.8 doesn't. What the cell hands over stays
    exact. A numpy scalar is unwrapped first -- `np.int64(2)` is how numpy
    writes itself down, not how a number reads.
    """
    if hasattr(value, 'item') and getattr(value, 'shape', None) == ():
        value = value.item()
    if isinstance(value, float):
        text = f'{value:.6g}'
    else:
        text = repr(value)
    return html.escape(truncate_str(text, 40))


def _agg_is_histogram(template: str) -> bool:
    """Whether an aggregation is the catalog's Histogram, at any bin count.

    By shape, the way _agg_name knows a percentile from a median, so nothing
    has to be stored beside the expression to say what it draws.
    """
    return _agg_shape(template) == _agg_shape(HISTOGRAM_AGG)


# How the bars are laid out. The height is what a count is measured against; the
# width is per bar, of which the bar itself takes most and the gap the rest.
_HIST_HEIGHT = 10
_HIST_STEP = 2
_HIST_BAR = 1


def _hist_counts(answer) -> Optional[list]:
    """The counts out of a `(counts, edges)` pair, or None for anything else.

    A bins box the user is still typing in can leave the aggregation answering
    with something else entirely, and a cell that can't draw its answer reads it
    instead -- so this asks rather than assumes, and never raises out of a
    render.
    """
    try:
        if isinstance(answer, str) or len(answer) != 2:
            return None
        counts, edges = answer
        if isinstance(counts, str) or len(counts) + 1 != len(edges):
            return None
        return [float(count) for count in counts]
    except Exception:
        return None


def _agg_hist_svg(answer) -> str:
    """A histogram's answer as bars, or '' for an answer that isn't one.

    `(counts, edges)` is nothing a cell can read as text, so the cell draws it.
    Bars and no more -- no axis, no labels: at one line high there is room for
    the shape of a column and nothing else, and the numbers are one drag away.

    Scaled to the fullest bin, with a floor under any bin that has something in
    it: one beside a hundred rounds to nothing, and a bar that isn't drawn reads
    as an empty bin rather than a rare one.

    preserveAspectRatio="none" so the drawing fills whatever box CSS gives it.
    The bars stay in proportion to each other, which is all a histogram says.
    """
    counts = _hist_counts(answer)
    if not counts:
        return ''
    peak = max(counts)
    if peak <= 0:
        return ''
    bars = []
    for i, count in enumerate(counts):
        if count <= 0:
            height = 0.0
        else:
            height = max(1.0, _HIST_HEIGHT * count / peak)
        bars.append(f'<rect x="{i * _HIST_STEP:g}" y="{_HIST_HEIGHT - height:g}" rx="1" ry="1" '
                    f'width="{_HIST_BAR:g}" height="{height:g}" />')
    # Wide enough for the bars and the gaps between them, and no wider: the gap
    # after the last one would be a margin the drawing didn't ask for.
    width = len(counts) * _HIST_STEP - (_HIST_STEP - _HIST_BAR)
    return (f'<svg class="col-agg-hist" '
            f'viewBox="0 0 {width:g} {_HIST_HEIGHT:g}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'{"".join(bars)}</svg>')


def _agg_answer_html(template: str, answer) -> str:
    """An answer as a cell reads it -- which for a histogram is its bars.

    One place for both the cell under the column and the preview in the menu,
    so the two cannot come to draw the same answer differently.
    """
    if _agg_is_histogram(template):
        drawn = _agg_hist_svg(answer)
        if drawn:
            return drawn
    return _format_agg_value(answer)


def _is_list_of_ints(val) -> bool:
    return isinstance(val, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in val)


def _is_list_of_int_pairs(val) -> bool:
    return (isinstance(val, list)
            and len(val) > 0
            and all(isinstance(x, (tuple, list)) and len(x) == 2
                    and isinstance(x[0], int) and not isinstance(x[0], bool)
                    and isinstance(x[1], int) and not isinstance(x[1], bool)
                    for x in val))


def _name_context_for_source(source_expr: str) -> tuple[bool, str]:
    """Return (has_var, suggestion base) for a source expression.

    has_var is True only when the source is a legal identifier, so it can serve
    as an assignment-name base; otherwise callers fall back to "result".
    """
    if source_expr.isidentifier() and not keyword.iskeyword(source_expr):
        return True, source_expr
    return False, "result"


def _get_search_context(model: dict, var_and_exp=None,
                        *, source_expr: str = None, eval_in_scope=None) -> dict | None:
    """The search context, plus whether the container is a dict.

    `is_dict` cannot be derived at the edge the way `binds` is: on the relink
    path the shared helper in visualizer_utils rebuilds ctx by parsing a source
    line, through a LinkConfig signature string_visualizer shares, and never
    holds the container at all. So it rides on the model.
    """
    ctx = _search_context_for(model, var_and_exp, source_expr=source_expr,
                              eval_in_scope=eval_in_scope)
    if ctx is not None:
        ctx['is_dict'] = bool(model.get('_is_dict'))
    return ctx


def _search_context_for(model: dict, var_and_exp=None,
                        *, source_expr: str = None, eval_in_scope=None) -> dict | None:
    """Build search context dict from model + source info.

    Returns None if no valid search or source info.
    """
    search = model.get('search')
    if not search and model.get('tool') != 'pick':
        return None

    if source_expr:
        has_var, suggest_base = _name_context_for_source(source_expr)
    else:
        if var_and_exp is None:
            return None
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else f"({expr})"
        suggest_base = var_name if var_name else "result"
        has_var = bool(var_name)

    if not search:
        return _pick_only_context(model, source_expr, has_var, suggest_base)

    first = bool(model.get('first_match', False))
    parsed = parse_search_term(search)
    if not parsed:
        return None

    kind, term = parsed

    if kind == 'slice':
        slice_start_raw, slice_stop_raw = term
        _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
        try:
            start_val = _eval(slice_start_raw) if slice_start_raw else None
        except Exception:
            start_val = None
        try:
            stop_val = _eval(slice_stop_raw) if slice_stop_raw else None
        except Exception:
            stop_val = None
        start_is_list = _is_list_of_ints(start_val)
        stop_is_list = _is_list_of_ints(stop_val)
        if start_is_list or stop_is_list:
            ctx = {
                'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
                'is_broadcast_slice': True,
                'has_start_list': start_is_list, 'has_stop_list': stop_is_list,
                'is_predicate': False, 'is_index': False, 'is_slice': False,
                'is_multi_index': False, 'is_first': first,
            }
            if start_is_list:
                ctx['start_list_expr'] = slice_start_raw
            else:
                ctx['slice_start'] = slice_start_raw
            if stop_is_list:
                ctx['stop_list_expr'] = slice_stop_raw
            else:
                ctx['slice_stop'] = slice_stop_raw
            return ctx
        return {
            'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
            'is_slice': True, 'slice_start': slice_start_raw, 'slice_stop': slice_stop_raw,
            'is_index': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': True,
        }

    expr_text = term
    if needs_implicit_dollar(expr_text):
        expr_text = '$ ' + expr_text.lstrip() if not expr_text.lstrip().startswith('.') else '$' + expr_text.lstrip()

    _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
    try:
        val = _eval(expr_text)
    except Exception:
        val = None

    if isinstance(val, int) and not isinstance(val, bool):
        return {
            'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
            'is_index': True, 'index_expr': expr_text,
            'is_slice': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': True,
        }

    if _is_list_of_ints(val):
        return {
            'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
            'is_multi_index': True, 'indices_expr': expr_text,
            'is_index': False, 'is_slice': False, 'is_predicate': False,
            'is_first': first,
        }

    if _is_list_of_int_pairs(val):
        return {
            'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
            'is_multi_pair': True, 'pairs_expr': expr_text,
            'is_index': False, 'is_slice': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': first,
        }

    predicate_with_dollar = expr_text
    if needs_implicit_dollar(search):
        if search.lstrip().startswith('.'):
            predicate_with_dollar = '$' + search.lstrip()
        else:
            predicate_with_dollar = '$ ' + search.lstrip()
    else:
        predicate_with_dollar = search

    # $ is the item and $$ the array, which is the level a column search's $$$
    # lands on once it is lifted into this scope. $i is the row's number, which
    # is what the comprehensions below bind `i` to.
    # For a dict the row is a pair, so bare $ is `(k, v)` and the halves bind
    # beside it -- matching the `k, v in d.items()` header generate_action
    # writes. $i stays the ROOT ROW's number for both.
    is_dict = bool(model.get('_is_dict'))
    predicate_expr = replace_dollars_in_py_exp(
        predicate_with_dollar,
        [_default_item_expr(_DICT_BINDS if is_dict else None),
         _atomize(source_expr)],
        bindings=_DICT_BINDS if is_dict else _LIST_BINDS)

    ctx = {
        'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
        'is_predicate': True, 'predicate_expr': predicate_expr,
        'names_index': dollar_expr_names_index(predicate_with_dollar),
        'is_index': False, 'is_slice': False, 'is_multi_index': False,
        'is_first': first,
    }

    # A pick composes an expression over the FIRST match only, so it forces
    # first-match mode and rides along for generate_action to wrap.
    pick_expr = model.get('pick_expr')
    if pick_expr:
        binds = _model_binds(model)
        ctx['pick_expr'] = replace_dollars_in_py_exp(
            pick_expr, _column_dollars(source_expr, _default_item_expr(binds)),
            index_exp='i', bindings=binds)
        # Either side of the next(...) may want the row's number, and one
        # binding serves both.
        ctx['needs_index'] = _pick_needs_index(pick_expr) or ctx['names_index']
        ctx['pick_is_array'] = _pick_is_array(model)
        ctx['is_first'] = True

    return ctx


def _pick_only_context(model: dict, source_expr: str, has_var: bool,
                       suggest_base: str) -> dict:
    """The context for a pick made with an empty search box.

    With no predicate there is no first match to bind, so the regions the table
    offers span every row and what they assemble is already self-contained --
    there is nothing for a next(...) to wrap, and no other action to write.
    """
    binds = _model_binds(model)
    pick_expr = model.get('pick_expr')
    return {
        'source_expr': source_expr, 'has_var': has_var,
        'suggest_base': suggest_base,
        'is_pick_only': True,
        'is_predicate': False, 'is_index': False, 'is_slice': False,
        'is_multi_index': False, 'is_first': False,
        'pick_expr': (replace_dollars_in_py_exp(
            pick_expr, _column_dollars(source_expr, _default_item_expr(binds)),
            index_exp='i', bindings=binds) if pick_expr else None),
        'pick_is_array': _pick_is_array(model),
    }


def _get_whole_list_context(model: dict, var_and_exp=None,
                            *, source_expr: str = None) -> dict | None:
    """The whole list as a context, plus whether it is a dict."""
    ctx = _whole_list_context_for(model, var_and_exp, source_expr=source_expr)
    if ctx is not None:
        ctx['is_dict'] = bool(model.get('_is_dict'))
    return ctx


def _whole_list_context_for(model: dict, var_and_exp=None,
                            *, source_expr: str = None) -> dict | None:
    """Build a context dict representing the whole list (no search filter)."""
    if source_expr:
        has_var, suggest_base = _name_context_for_source(source_expr)
    else:
        if var_and_exp is None:
            return None
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else f"({expr})"
        suggest_base = var_name if var_name else "result"
        has_var = bool(var_name)

    return {
        'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
        'is_whole_list': True,
        'is_predicate': False, 'is_index': False, 'is_slice': False,
        'is_multi_index': False, 'is_first': False,
    }


# Actions whose predicate form counts the rows off whatever the search asked,
# because the row's number is what they are for. They have no plain twin, so
# nothing distinguishes them by flag -- being one of these IS the distinction.
_INDEX_BOUND_ACTIONS = frozenset({'find_indices', 'loop_orig_idx'})


def _predicate_binds_index(ctx: dict) -> bool:
    """Whether the line a predicate came out of bound the row's number to `i`.

    Three ways it can have: a form with an indexed twin says which of the two
    was written (names_index), a pick says whether its next(...) counts the rows
    (needs_index), and the forms above always do. Anything else leaves `i` a
    name from the user's own program.
    """
    if ctx.get('names_index') or ctx.get('needs_index'):
        return True
    action = ctx.get('action')
    return (action in _INDEX_BOUND_ACTIONS
            # Delete's first-match form needs the number to cut the list at.
            or (action == 'delete' and bool(ctx.get('is_first'))))


def _dollarize_row_names(expr: str, names_index=False, is_dict=False) -> str:
    """Generated code read back as the dollars the boxes speak.

    The names a comprehension over the rows binds are what `$` and `$i` were
    written as on the way out, so they say the same thing on the way back. Which
    names those are is the container's: a list binds `item`, a dict `k` and `v`.

    Only the ones it actually binds, though. `i` is the row's number in a line
    that counts the rows off, and a name from the user's own program in one that
    doesn't -- reading the second as the first would quietly change what the
    search asks. Which line it is, the grammar says: every predicate form has an
    indexed twin, and they differ by `names_index`.

    Names are found by parsing rather than by matching text, so a `v` inside a
    string literal stays a `v`. A dict makes that matter -- single letters turn
    up in strings constantly -- but it was always the right reading, and a list
    gets it too now.
    """
    names = {'k': '$k', 'v': '$v'} if is_dict else {'item': '$'}
    if names_index:
        names['i'] = '$i'
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return expr

    lines = expr.split('\n')
    spots = [(n.lineno, n.col_offset, n.end_col_offset, names[n.id])
             for n in ast.walk(tree)
             if isinstance(n, ast.Name) and n.id in names]
    # From the end, so the offsets ahead of each splice stay where they were.
    for lineno, start, end, dollar in sorted(spots, reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:start] + dollar + line[end:]
    return '\n'.join(lines)


def _ctx_to_model(ctx: dict, model: dict) -> None:
    """Apply parsed DSL context to model state (reverse of _get_search_context)."""
    if ctx.get('is_index'):
        model['search'] = ctx.get('index_expr', '')
    elif ctx.get('is_slice'):
        start = ctx.get('slice_start', '')
        stop = ctx.get('slice_stop', '')
        model['search'] = f'{start}:{stop}'
    elif ctx.get('is_multi_index'):
        model['search'] = ctx.get('indices_expr', '')
    elif ctx.get('is_predicate'):
        pred = ctx.get('predicate_expr', '')
        model['search'] = _dollarize_row_names(pred, _predicate_binds_index(ctx),
                                               bool(ctx.get('is_dict')))
    # A restored search is a search like any other, so the column menus and the
    # tally light up for a filter that came back from a line of code.
    _apply_search_to_columns(model)
    model['first_match'] = bool(ctx.get('is_first'))

    # A picked expression survives the round-trip through the line of code, but
    # the region ids that produced it do not -- they aren't recoverable from the
    # expression. So the table re-enters pick mode showing the restored
    # expression, with nothing highlighted until the user picks again.
    pick_expr = ctx.get('pick_expr')
    if pick_expr:
        model['pick_expr'] = _dollarize_row_names(pick_expr,
                                                  _predicate_binds_index(ctx),
                                                  bool(ctx.get('is_dict')))
        model['first_match'] = True
        model['tool'] = 'pick'
    else:
        model['pick_expr'] = None
        model['tool'] = 'normal'
    model['picked'] = None


# === Code generation ===

_SUGGEST_SUFFIXES = {
    'any': 'any', 'all': 'all', 'count': 'count',
    'filter': 'filtered', 'find_indices': 'indices',
    'join': 'joined',
}


def _suggest_name_for_action(action: str, ctx: dict) -> str | None:
    if action in _STATEMENT_ACTIONS:
        return None
    base = ctx.get('suggest_base') or 'result'
    has_var = bool(ctx.get('has_var'))
    if action == 'filter':
        if ctx.get('is_pick_only'):
            # Nothing was filtered: the whole table is there, one column of it.
            suffix = 'picked'
        elif ctx.get('is_first'):
            suffix = 'match'
        else:
            suffix = 'filtered'
        return f"{base}_{suffix}" if has_var else f"result_{suffix}"
    if action == 'delete':
        return base if has_var else 'result'
    suffix = _SUGGEST_SUFFIXES.get(action)
    if suffix:
        return f"{base}_{suffix}" if has_var else f"result_{suffix}"
    return base if has_var else 'result'


def pick_filter_expr(ctx: dict) -> str:
    """Self-contained expression for the picked value.

    Pick is first-match-only, so one next(...) binds the matched row -- and its
    index, when the picked regions need one -- for the assembled expression to
    evaluate against. This is what Filter emits; Loop and Join run over it
    directly when the pick is an array.

    The binding is the container's: a dict's row is the pair its .items() gives.
    Everything inside is already written against those names, so this is the
    only place the two containers differ.
    """
    src = ctx['source_expr']
    if ctx.get('is_dict'):
        rows = f'{_atomize(src)}.items()'
        binding = (f'i, (k, v) in enumerate({rows})'
                   if ctx.get('needs_index') else f'k, v in {rows}')
    else:
        binding = (f'i, item in enumerate({src})'
                   if ctx.get('needs_index') else f'item in {src}')
    return (f'next(({ctx["pick_expr"]} for {binding} '
            f'if {ctx["predicate_expr"]}), None)')


def code_imports(code: str) -> tuple:
    """What code generated by this visualizer can't run without.

    Nothing of its own: every action here is builtins, comprehensions and
    slicing over the user's own list. But a column can hold code a child
    visualizer wrote -- a string cell's `re.sub` becomes a column of this table
    -- and every line written over that column carries that code inside it. So
    the answer is read off the code rather than being nothing at all.
    """
    return imports_for_code(code)


def generate_action(action: str, ctx: dict) -> tuple[str | None, str] | None:
    """Generate code for a list action.

    Returns (suggest_name, code_str) or None.
    """
    # No dict positional search writes a loop. A list's multi-index and
    # broadcast slice do, but their "original index" is a position where a
    # dict's is a key, so `for i in [0, 2]:` has no honest dict reading -- and
    # building some of the three would leave the family lopsided. None are
    # built, which is what index and slice already do.
    if ctx.get('is_dict') and action in ('loop_no_idx', 'loop_orig_idx',
                                         'loop_new_idx') and (
            ctx.get('is_multi_index') or ctx.get('is_broadcast_slice')):
        return None

    src = ctx['source_expr']
    first = ctx.get('is_first', False)

    # No search, so no match to bind: the picked expression already stands on
    # its own, and every action that would have needed the predicate is
    # unwritten. Loop and Join still run over a pick that is one array.
    if ctx.get('is_pick_only'):
        pick = ctx.get('pick_expr')
        if not pick:
            return None
        pick_array = bool(ctx.get('pick_is_array'))
        match action:
            case 'filter':
                code = pick
            case 'loop_no_idx' if pick_array:
                code = f'for item in {pick}:'
            case 'loop_new_idx' if pick_array:
                code = f'for i, item in enumerate({pick}):'
            case 'join' if pick_array:
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {pick})'
            case _:
                # Including loop_orig_idx: a column is a projection of the rows,
                # so its elements have no original index of their own.
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_dict') and ctx.get('is_index'):
        idx = ctx['index_expr']
        pairs = f'list({_atomize(src)}.items())'
        match action:
            case 'filter':
                # A row IS the pair, so that is what one position picks.
                code = f'{pairs}[{idx}]'
            case 'delete':
                # By POSITION, not by key: the position is what was searched
                # for, and d.pop(k) would need a key nobody named.
                code = (f'{{k: v for j, (k, v) in enumerate({_atomize(src)}.items()) '
                        f'if j != {idx}}}')
            case 'find_indices':
                # A dict's index is its key.
                code = f'list({_atomize(src)})[{idx}]'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_dict') and ctx.get('is_slice'):
        start = ctx.get('slice_start', '')
        stop = ctx.get('slice_stop', '')
        atom = _atomize(src)
        pairs = f'list({atom}.items())'
        match action:
            case 'filter':
                code = f'dict({pairs}[{start}:{stop}])'
            case 'delete':
                left = f'{pairs}[:{start}]' if start else '[]'
                right = f'{pairs}[{stop}:]' if stop else '[]'
                code = f'dict({left} + {right})'
            case 'find_indices':
                code = f'list({atom})[{start}:{stop}]'
            case 'join':
                # Values, matching the predicate form -- Join means one thing on
                # a dict however the rows were chosen. The tuple target is also
                # what keeps the line out of the list reader, whose slice shape
                # binds a bare `item`.
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(v) for k, v in {pairs}[{start}:{stop}])'
            case _:
                # Count over a slice is not a dict gap: no list writes one
                # either, so there is nothing here to reach parity with.
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_dict') and ctx.get('is_multi_index'):
        indices = ctx['indices_expr']
        atom = _atomize(src)
        pairs = f'list({atom}.items())'
        match action:
            case 'filter':
                # Several rows, so a dict -- where one position gave the pair.
                code = f'dict({pairs}[i] for i in {indices})'
            case 'delete':
                code = (f'{{k: v for j, (k, v) in enumerate({atom}.items()) '
                        f'if j not in set({indices})}}')
            case 'find_indices':
                code = f'[list({atom})[i] for i in {indices}]'
            case 'count':
                # These three never touch the container: they ask how many
                # positions were named, so the list forms are already right.
                code = f'len({indices})'
            case 'any':
                code = f'len({indices}) > 0'
            case 'all':
                code = f'len({indices}) == len({atom})'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(v) for k, v in [{pairs}[i] for i in {indices}])'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_dict') and ctx.get('is_broadcast_slice'):
        atom = _atomize(src)
        pairs = f'list({atom}.items())'
        has_start = ctx.get('has_start_list')
        has_stop = ctx.get('has_stop_list')
        # A band is a run of rows, so each one is its own dict.
        if has_start and has_stop:
            starts, stops = ctx['start_list_expr'], ctx['stop_list_expr']
            iter_expr = f'dict({pairs}[i:j]) for i, j in zip({starts}, {stops})'
            count_expr = starts
            ranges = f'range(s, e) for s, e in zip({starts}, {stops})'
            first_key = f'[list({atom})[i] for i in {starts}]'
        elif has_start:
            starts = ctx['start_list_expr']
            stop = ctx.get('slice_stop', '') or ''
            iter_expr = f'dict({pairs}[i:{stop}]) for i in {starts}'
            count_expr = starts
            stop_expr = stop if stop else f'len({atom})'
            ranges = f'range(s, {stop_expr}) for s in {starts}'
            first_key = f'[list({atom})[i] for i in {starts}]'
        else:
            stops = ctx['stop_list_expr']
            start = ctx.get('slice_start', '') or ''
            iter_expr = f'dict({pairs}[{start}:i]) for i in {stops}'
            count_expr = stops
            ranges = f'range({start or "0"}, e) for e in {stops}'
            # Every band starts in the same place, so every band reports the
            # same key. A list hardcodes 0 here even when it was given a start;
            # that is a list bug rather than a shape to copy.
            first_key = f'[list({atom})[{start or "0"}]] * len({stops})'
        match action:
            case 'filter':
                code = f'[{iter_expr}]'
            case 'delete':
                code = (f'{{k: v for j, (k, v) in enumerate({atom}.items()) '
                        f'if j not in set().union(*[{ranges}])}}')
            case 'find_indices':
                code = first_key
            case 'count':
                code = f'len({count_expr})'
            case 'any':
                code = f'len({count_expr}) > 0'
            case 'all':
                code = f'len({count_expr}) == len({atom})'
            case _:
                # Join over a band is unwritten for every container.
                return None
        return (_suggest_name_for_action(action, ctx), code)


    if ctx.get('is_index'):
        idx = ctx['index_expr']
        match action:
            case 'filter':
                code = f'{src}[{idx}]'
            case 'delete':
                code = f'{src}[:{idx}] + {src}[{idx}+1:]'
            case 'find_indices':
                code = idx
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_slice'):
        start = ctx.get('slice_start', '')
        stop = ctx.get('slice_stop', '')
        match action:
            case 'filter':
                code = f'{src}[{start}:{stop}]'
            case 'delete':
                left = f'{src}[:{start}]' if start else "''"
                right = f'{src}[{stop}:]' if stop else "''"
                if left == "''":
                    left = '[]'
                if right == "''":
                    right = '[]'
                code = f'{left} + {right}'
            case 'find_indices':
                stop_expr = stop if stop else f'len({src})'
                code = f'list(range({start or "0"}, {stop_expr}))'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {src}[{start}:{stop}])'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_multi_index'):
        indices = ctx['indices_expr']
        match action:
            case 'filter':
                code = f'[{src}[i] for i in {indices}]'
            case 'loop_no_idx':
                code = f'for item in [{src}[i] for i in {indices}]:'
            case 'loop_orig_idx':
                code = f'for i in {indices}:'
            case 'loop_new_idx':
                code = f'for i, item in enumerate({src}[i] for i in {indices}):'
            case 'delete':
                code = f'[item for i, item in enumerate({src}) if i not in set({indices})]'
            case 'find_indices':
                code = indices
            case 'count':
                code = f'len({indices})'
            case 'any':
                code = f'len({indices}) > 0'
            case 'all':
                code = f'len({indices}) == len({src})'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str({src}[i]) for i in {indices})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_broadcast_slice'):
        has_start = ctx.get('has_start_list')
        has_stop = ctx.get('has_stop_list')
        if has_start and has_stop:
            iter_expr = f'{src}[i:j] for i, j in zip({ctx["start_list_expr"]}, {ctx["stop_list_expr"]})'
            count_expr = ctx['start_list_expr']
        elif has_start:
            stop = ctx.get('slice_stop', '')
            iter_expr = f'{src}[i:{stop}] for i in {ctx["start_list_expr"]}' if stop else f'{src}[i:] for i in {ctx["start_list_expr"]}'
            count_expr = ctx['start_list_expr']
        else:
            start = ctx.get('slice_start', '')
            iter_expr = f'{src}[{start}:i] for i in {ctx["stop_list_expr"]}' if start else f'{src}[:i] for i in {ctx["stop_list_expr"]}'
            count_expr = ctx['stop_list_expr']
        match action:
            case 'filter':
                code = f'[{iter_expr}]'
            case 'loop_no_idx':
                code = f'for item in [{iter_expr}]:'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate([{iter_expr}]):'
            case 'loop_new_idx':
                code = f'for i, item in enumerate([{iter_expr}]):'
            case 'delete':
                if has_start and has_stop:
                    code = f'[item for i, item in enumerate({src}) if i not in set().union(*[range(s, e) for s, e in zip({ctx["start_list_expr"]}, {ctx["stop_list_expr"]})])]'
                elif has_start:
                    stop = ctx.get('slice_stop', '')
                    stop_expr = stop if stop else f'len({src})'
                    code = f'[item for i, item in enumerate({src}) if i not in set().union(*[range(s, {stop_expr}) for s in {ctx["start_list_expr"]}])]'
                else:
                    start = ctx.get('slice_start', '')
                    start_expr = start if start else '0'
                    code = f'[item for i, item in enumerate({src}) if i not in set().union(*[range({start_expr}, e) for e in {ctx["stop_list_expr"]}])]'
            case 'count':
                code = f'len({count_expr})'
            case 'any':
                code = f'len({count_expr}) > 0'
            case 'all':
                code = f'len({count_expr}) == len({src})'
            case 'find_indices':
                if has_start:
                    code = ctx['start_list_expr']
                else:
                    # Every band starts in the same place, so every band reports
                    # the same index -- but that place is the slice's own start,
                    # not necessarily 0. `1:[3,5]` bands data[1:3] and data[1:5].
                    start = ctx.get('slice_start', '') or '0'
                    code = f'[{start}] * len({ctx["stop_list_expr"]})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_multi_pair'):
        pairs = ctx['pairs_expr']
        iter_expr = f'{src}[i:j] for i, j in {pairs}'
        match action:
            case 'filter':
                code = f'[{iter_expr}]'
            case 'loop_no_idx':
                code = f'for item in [{iter_expr}]:'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate([{iter_expr}]):'
            case 'loop_new_idx':
                code = f'for i, item in enumerate([{iter_expr}]):'
            case 'delete':
                code = f'[item for i, item in enumerate({src}) if i not in set().union(*[range(s, e) for s, e in {pairs}])]'
            case 'count':
                code = f'len({pairs})'
            case 'any':
                code = f'len({pairs}) > 0'
            case 'all':
                code = f'len({pairs}) == len({src})'
            case 'find_indices':
                code = f'[i for i, j in {pairs}]'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_predicate') and ctx.get('is_dict'):
        pred = ctx['predicate_expr']
        pick = ctx.get('pick_expr')
        pick_array = bool(pick) and bool(ctx.get('pick_is_array'))
        if first and not pick and action not in ('filter', 'find_indices',
                                                 'delete'):
            return None
        # $i is the ROOT ROW index, so enumerate(d.items()) binds exactly what
        # $i means. The header is the general one either way: narrowing it to
        # d.values() would leave a `$k` in the predicate unbound.
        rows = (f'i, (k, v) in enumerate({src}.items())' if ctx.get('names_index')
                else f'k, v in {src}.items()')
        match action:
            case 'filter' if pick:
                code = pick_filter_expr(ctx)
            case 'loop_no_idx' if pick_array:
                code = f'for item in {pick_filter_expr(ctx)}:'
            case 'loop_new_idx' if pick_array:
                code = f'for i, item in enumerate({pick_filter_expr(ctx)}):'
            case 'loop_orig_idx' if pick_array:
                # Same as a list's: an array pick is a projection of a row
                # range, so there is no original index to hand back.
                return None
            case 'join' if pick_array:
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {pick_filter_expr(ctx)})'
            case _ if pick:
                # Every other action over a pick is unwritten for a list too.
                return None
            case 'filter' if first:
                # The pair is what a row IS, so that is what one match is.
                code = f'next(((k, v) for {rows} if {pred}), None)'
            case 'find_indices' if first:
                code = f'next((k for {rows} if {pred}), None)'
            case 'delete' if first:
                # The dict reading of the list's
                # `next((src[:i] + src[i+1:] for i, item in ...), src)`:
                # the generator yields the dict without this entry, next takes
                # the first and stops -- so the predicate runs only as far as
                # the match -- and the default hands the dict back untouched
                # when nothing matched.
                #
                # Excluded by KEY rather than against a next(..., None)
                # sentinel, because None is a perfectly good dict key; `k` is
                # bound by the outer generator, so it is always a real one.
                code = (f'next(({{k2: v2 for k2, v2 in {_atomize(src)}.items() '
                        f'if k2 != k}} for {rows} if {pred}), {src})')
            case 'filter':
                code = f'{{k: v for {rows} if {pred}}}'
            case 'delete':
                code = f'{{k: v for {rows} if not ({pred})}}'
            case 'find_indices':
                # A dict's "indices" are its keys.
                code = f'[k for {rows} if {pred}]'
            case 'count':
                code = f'sum(1 for {rows} if {pred})'
            case 'any':
                code = f'any({pred} for {rows})'
            case 'all':
                code = f'all({pred} for {rows})'
            case 'if_any':
                code = f'if any({pred} for {rows}):'
            case 'if_all':
                code = f'if all({pred} for {rows}):'
            case 'loop_no_idx':
                code = f'for k, v in {{k: v for {rows} if {pred}}}.items():'
            case 'loop_orig_idx':
                code = f'for {rows}:\n    if {pred}:'
            case 'loop_new_idx':
                code = (f'for i, (k, v) in enumerate('
                        f'{{k: v for {rows} if {pred}}}.items()):')
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(v) for {rows} if {pred})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_whole_list') and ctx.get('is_dict'):
        match action:
            case 'loop_no_idx':
                code = f'for k, v in {src}.items():'
            case 'loop_orig_idx' | 'loop_new_idx':
                code = f'for i, (k, v) in enumerate({src}.items()):'
            case 'any':
                code = f'any({src}.values())'
            case 'all':
                code = f'all({src}.values())'
            case 'if_any':
                code = f'if any({src}.values()):'
            case 'if_all':
                code = f'if all({src}.values()):'
            case 'count':
                code = f'sum(1 for v in {src}.values() if v)'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(v) for v in {src}.values())'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_predicate'):
        pred = ctx['predicate_expr']
        pick = ctx.get('pick_expr')
        # What a comprehension over the rows binds. The enumerate is only ever
        # there because the search asked for the row's number, so a search that
        # didn't hands over exactly the code it always did.
        rows = (f'i, item in enumerate({src})' if ctx.get('names_index')
                else f'item in {src}')
        # A pick spanning a contiguous run of rows in one column is a list, so
        # the list-consuming actions run over it. Anything else a pick produces
        # is a scalar or a tuple, and those actions stay unavailable.
        pick_array = bool(pick) and bool(ctx.get('pick_is_array'))
        match action:
            case 'filter':
                if pick:
                    code = pick_filter_expr(ctx)
                elif first:
                    code = f'next((item for {rows} if {pred}), None)'
                else:
                    code = f'[item for {rows} if {pred}]'
            case 'loop_no_idx' if pick_array:
                code = f'for item in {pick_filter_expr(ctx)}:'
            case 'loop_new_idx' if pick_array:
                code = f'for i, item in enumerate({pick_filter_expr(ctx)}):'
            case 'loop_orig_idx' if pick_array:
                # An array pick is a projection of a row range, so there is no
                # original index to hand back: for a pre-anchored range it would
                # just be the new index, and for a post-anchored one the offset
                # is trapped inside the next(...). The UI dims this row.
                return None
            case 'join' if pick_array:
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {pick_filter_expr(ctx)})'
            case 'loop_no_idx':
                code = f'for item in (item for {rows} if {pred}):'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate({src}):\n    if {pred}:'
            case 'loop_new_idx':
                code = f'for i, item in enumerate(item for {rows} if {pred}):'
            case 'any':
                code = f'any({pred} for {rows})'
            case 'all':
                code = f'all({pred} for {rows})'
            case 'if_any':
                code = f'if any({pred} for {rows}):'
            case 'if_all':
                code = f'if all({pred} for {rows}):'
            case 'delete':
                if first:
                    code = f'next(({src}[:i] + {src}[i+1:] for i, item in enumerate({src}) if {pred}), {src})'
                else:
                    code = f'[item for {rows} if not ({pred})]'
            case 'find_indices':
                if first:
                    code = f'next((i for i, item in enumerate({src}) if {pred}), None)'
                else:
                    code = f'[i for i, item in enumerate({src}) if {pred}]'
            case 'count':
                code = f'sum(1 for {rows} if {pred})'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for {rows} if {pred})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    if ctx.get('is_whole_list'):
        match action:
            case 'loop_no_idx':
                code = f'for item in {src}:'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate({src}):'
            case 'loop_new_idx':
                code = f'for i, item in enumerate({src}):'
            case 'any':
                code = f'any({src})'
            case 'all':
                code = f'all({src})'
            case 'if_any':
                code = f'if any({src}):'
            case 'if_all':
                code = f'if all({src}):'
            case 'count':
                code = f'sum(1 for item in {src} if item)'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {src})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    return None


def _emit_linked_update(expr: str, model: dict, commands: list,
                        suggest_name: 'str | None' = None,
                        rename: bool = False) -> None:
    """Send expression intent while leaving the concrete target to the editor.

    No-op when *expr* matches the last expression written for this link, so
    events that do not change the search context do not rewrite the linked LOC.

    Whether the code being written can be assigned to a name is read off the
    code itself rather than remembered from the action that linked the line: an
    action change can turn an expression into a block header (Join to Loop) or
    back, and a remembered answer would describe the shape that just stopped
    being true -- probing `name = for item in ...:` raises, and the update
    disappears in the except below.
    """
    if expr == model.get('last_linked_expr'):
        return
    text = expr if opens_block(expr) else '_linked_result = ' + expr
    try:
        ast.parse(with_pass_body(text))
    except SyntaxError:
        return
    model['last_linked_expr'] = expr
    commands.append(ChangeSelectedText(
        expression=expr,
        suggested_var_name=suggest_name if rename else None,
    ))


# === Matching indices for highlighting ===

def _compile_predicate(predicate_expr: str, eval_in_scope=None):
    """A dollar-substituted predicate as a callable of (item, lst, index, k, v).

    The key and value are bound for every container, not just a dict: a list
    row has no halves, so they arrive as None and a predicate naming them
    simply never matches -- which is the right answer, and cheaper than
    compiling two shapes of lambda.

    Built in the user's scope so the predicate's free names resolve to their
    program's, which is the only place they were ever written. Without a scope
    to build it in -- an unfocused preview, a test -- this module's globals are
    all there is, which is enough for a predicate that names nothing.
    """
    code = f'(lambda _item, _lst, _i, _bk=None, _bv=None: {predicate_expr})'
    return eval(code) if eval_in_scope is None else eval_in_scope(code)


def _get_matching_indices(search: str | None, lst: list, eval_in_scope=None) -> list:
    """Return list of row indices matching the search."""
    if not search or not lst:
        return []

    parsed = parse_search_term(search)
    if not parsed:
        return []

    kind, term = parsed

    if kind == 'slice':
        start_s, stop_s = term
        _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
        try:
            start_val = _eval(start_s) if start_s else None
        except Exception:
            start_val = None
        try:
            stop_val = _eval(stop_s) if stop_s else None
        except Exception:
            stop_val = None
        start_is_list = _is_list_of_ints(start_val)
        stop_is_list = _is_list_of_ints(stop_val)
        if start_is_list or stop_is_list:
            matched = set()
            if start_is_list and stop_is_list:
                for s, e in zip(start_val, stop_val):
                    matched.update(range(max(0, s), min(e, len(lst))))
            elif start_is_list:
                e = int(stop_s) if stop_s else len(lst)
                for s in start_val:
                    matched.update(range(max(0, s), min(e, len(lst))))
            else:
                s = int(start_s) if start_s else 0
                for e in stop_val:
                    matched.update(range(max(0, s), min(e, len(lst))))
            return sorted(matched)
        try:
            start = int(start_s) if start_s else 0
        except (ValueError, TypeError):
            start = 0
        try:
            stop = int(stop_s) if stop_s else len(lst)
        except (ValueError, TypeError):
            stop = len(lst)
        return list(range(max(0, start), min(stop, len(lst))))

    expr_text = term
    if needs_implicit_dollar(expr_text):
        if expr_text.lstrip().startswith('.'):
            expr_text = '$' + expr_text.lstrip()
        else:
            expr_text = '$ ' + expr_text.lstrip()

    _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
    try:
        val = _eval(expr_text)
    except Exception:
        val = None

    if isinstance(val, int) and not isinstance(val, bool):
        if 0 <= val < len(lst):
            return [val]
        return []

    if _is_list_of_ints(val):
        return [i for i in val if 0 <= i < len(lst)]

    if _is_list_of_int_pairs(val):
        matched = set()
        for s, e in val:
            matched.update(range(max(0, s), min(e, len(lst))))
        return sorted(matched)

    predicate_with_dollar = search
    if needs_implicit_dollar(search):
        if search.lstrip().startswith('.'):
            predicate_with_dollar = '$' + search.lstrip()
        else:
            predicate_with_dollar = '$ ' + search.lstrip()

    predicate_expr = replace_dollars_in_py_exp(
        predicate_with_dollar, ['_item', '_lst'],
        bindings={'i': '_i', 'k': '_bk', 'v': '_bv'})

    # The predicate is the user's own text, so the names in it are their
    # program's names: `== s` has to mean the same `s` the line above defines.
    # Compiling it as a lambda through eval_in_scope is what puts those names in
    # reach -- evaluating it here would only ever see this module's globals, and
    # the NameError would land in the per-row except below as "no matches".
    # The row item, the array and the row's number come in as arguments, so a
    # dollar keeps naming them whatever the surrounding scope calls its own
    # variables.
    try:
        predicate = _compile_predicate(predicate_expr, eval_in_scope)
    except Exception:
        return []

    matched = []
    for row in _rows(lst):
        try:
            if predicate(row.item, lst, row.index,
                         row.bindings.get('k'), row.bindings.get('v')):
                matched.append(row.index)
        except Exception:
            pass
    return matched


# =============================================================================
# Pick tool: pickable regions
# =============================================================================
#
# Pick mode is first-match-only. The table splits into three row bands -- the
# rows before the first match, the match row itself, and the rows after -- and
# each band crosses the row-index column plus every configured column. Every
# cell of that grid is one pickable region, so a table with N columns offers
# 3 * (1 + N) regions, minus any band that has no rows.
#
# With an empty search box there is no match, so there are no bands relative to
# one: the table is a single 'all' band per column, spanning every row. That is
# the whole difference -- a region is still one column over a run of rows, and
# `first_idx is None` is what says which reading applies.
#
# Region ids are '{band}_{column}': band is 'pre' / 'match' / 'post' / 'all' and
# column is 'idx' (the row-index column) or 'col_<n>' (an index into
# model['columns']).
#
# Region expressions are written in the table's own scope, where $ is the row
# item and `i` is the matched row's index. generate_action binds $ to `item` and
# wraps the whole assembled expression in a single next(...) over the first
# match, which is what makes `i` available. An 'all' band names no match and so
# needs no wrapper: what it picks out already stands on its own.

PICK_BANDS = ('pre', 'match', 'post', 'all')
PICK_IDX_COLUMN = 'idx'

# The pre/post bands map a column over a sublist, so their comprehensions need a
# loop variable. Deliberately not `item`: the generated wrapper already binds
# that to the matched row, and shadowing it inside the inner comprehension would
# read as a bug even though Python scopes it correctly.
_PICK_INNER_VAR = 'x'

# Row range [start, stop) each band covers, as Python source (None = list end).
_PICK_BAND_RANGES = {
    'pre': (None, 'i'),
    'post': ('i + 1', None),
    'all': (None, None),
}

# Bands of one column that sit next to each other collapse into a single range.
_PICK_COLLAPSE_RANGES = {
    frozenset(('pre', 'match', 'post')): (None, None),
    frozenset(('pre', 'match')): (None, 'i + 1'),
    frozenset(('match', 'post')): ('i', None),
}


def _pick_column_ids(columns) -> list:
    """Every pickable column id, in display order (row index first).

    Numbered by DRAWN column, which is what the overlays are laid over: a table
    with sub-columns draws more columns than it has top-level ones, and ids
    counted off those would name a different column than the one the region
    sits on -- or none at all, past the second.

    A splat column has no id: a band is a run of ROWS, and a splat column's
    rows are its own elements rather than the list's, so there is no expression
    for a run of them.
    """
    columns = _as_columns(columns)
    return [PICK_IDX_COLUMN] + [
        f'col_{n}' for n, leaf in enumerate(_leaf_columns(columns))
        if _column_row_expr(columns, leaf.expr) is not None]


def _pick_column_expr(col_id: str, columns) -> str | None:
    """The column expression a 'col_<n>' id refers to, or None if it doesn't."""
    if not col_id.startswith('col_'):
        return None
    try:
        n = int(col_id[len('col_'):])
    except ValueError:
        return None
    columns = _as_columns(columns)
    leaves = _leaf_columns(columns)
    if n >= len(leaves):
        return None
    return _column_row_expr(columns, leaves[n].expr)


def _parse_pick_region_id(region_id: str) -> tuple | None:
    """Split a region id into (band, column_id), or None if malformed."""
    for band in PICK_BANDS:
        prefix = f'{band}_'
        if region_id.startswith(prefix):
            return (band, region_id[len(prefix):])
    return None


def _pick_bands_present(first_idx: 'int | None', n_rows: int) -> tuple:
    """Which bands actually hold rows, for a first match at first_idx.

    No first match (first_idx None) means no band is relative to one, so the
    table offers the single whole-height band instead.
    """
    if first_idx is None:
        return ('all',)
    bands = []
    if first_idx > 0:
        bands.append('pre')
    bands.append('match')
    if first_idx < n_rows - 1:
        bands.append('post')
    return tuple(bands)


def _pick_region_ids(columns, first_idx: int, n_rows: int) -> list:
    """Every region id this table offers, in canonical order."""
    bands = _pick_bands_present(first_idx, n_rows)
    return [f'{band}_{col_id}'
            for col_id in _pick_column_ids(columns)
            for band in bands]


# What a band's comprehension binds over a dict, and why it is not `k, v`: the
# band sits inside the next(...) that binds the matched row, and that one has
# taken those names already. The list's `x` is the same idea for the same
# reason.
_PICK_INNER_DICT_BINDS = {'i': 'i', 'k': 'k2', 'v': 'v2'}
_PICK_INNER_DICT_TARGET = 'k2, v2'
_PICK_INNER_DICT_ITEM = '(k2, v2)'


def _pick_band_rows(source_expr: str, start: str | None, stop: str | None,
                    is_dict: bool) -> str:
    """The run of rows a band covers.

    A dict's rows are its pairs, so a band of them is a run of list(d.items())
    -- the same route every positional dict action takes.
    """
    if is_dict:
        rows = f'list({_atomize(source_expr)}.items())'
        return (rows if start is None and stop is None
                else f'{rows}[{start or ""}:{stop or ""}]')
    if start is None and stop is None:
        return source_expr
    return f'{source_expr}[{start or ""}:{stop or ""}]'


def _pick_element_expr(col_id: str, columns, source_expr: str, item_expr: str,
                       binds: 'dict | None') -> tuple | None:
    """(what one row of this column contributes, whether it names the row's
    number), written against the loop target a band's comprehension binds.

    One row rather than the whole band, which is what lets several columns
    share a single pass over the rows.
    """
    if col_id == PICK_IDX_COLUMN:
        return ('i', True)
    col = _pick_column_expr(col_id, columns)
    if col is None:
        return None
    # `$$` is the whole list, not the sublist this region is a band of.
    inner = replace_dollars_in_py_exp(
        col, _column_dollars(source_expr, item_expr), index_exp='i',
        bindings=_PICK_INNER_DICT_BINDS if _is_dict_binds(binds) else None)
    return (inner, dollar_expr_names_index(col))


def _pick_comprehension(elt: str, rows: str, start: str | None,
                        names_index: bool, is_dict: bool) -> str:
    """`elt` read off every row of `rows`."""
    target = _PICK_INNER_DICT_TARGET if is_dict else _PICK_INNER_VAR
    if not names_index:
        return f'[{elt} for {target} in {rows}]'
    # `$i` is the row's number in the whole list, not its place in this band, so
    # the count starts where the band does.
    from_row = '' if not start or start == '0' else f', {start}'
    # A tuple target needs its own parens inside the enumerate pair.
    unpacked = f'({target})' if ',' in target else target
    return f'[{elt} for i, {unpacked} in enumerate({rows}{from_row})]'


def _pick_range_expr(col_id: str, columns, source_expr: str,
                     start: str | None, stop: str | None,
                     binds: 'dict | None' = None) -> str | None:
    """Expression for one column over the row range [start, stop).

    start/stop are Python source snippets, or None for the ends of the list.
    The row NUMBERS the index column reports are positions for either container.
    """
    if col_id == PICK_IDX_COLUMN:
        lo = start or '0'
        hi = stop if stop is not None else f'len({source_expr})'
        return f'list(range({hi}))' if lo == '0' else f'list(range({lo}, {hi}))'
    col = _pick_column_expr(col_id, columns)
    if col is None:
        return None
    is_dict = _is_dict_binds(binds)
    if is_dict and start is None and stop is None:
        # A whole column has a short spelling, and it is the one the header
        # hands over -- so a full-height pick and a header drag agree.
        return _column_values_expr(col, source_expr, binds)
    item_expr = _PICK_INNER_DICT_ITEM if is_dict else _PICK_INNER_VAR
    rows = _pick_band_rows(source_expr, start, stop, is_dict)
    inner, names_index = _pick_element_expr(col_id, columns, source_expr,
                                            item_expr, binds)
    if inner == item_expr:
        # The identity column (a bare $, which is the default) maps each row to
        # itself, so the sublist is already the answer -- no comprehension.
        return rows
    return _pick_comprehension(inner, rows, start, names_index, is_dict)


def _pick_zip_expr(col_ids, columns, source_expr: str,
                   start: str | None, stop: str | None,
                   binds: 'dict | None' = None) -> str | None:
    """Several columns over the SAME run of rows, as one list of tuples.

    Picking two columns asks what their cells say about each other, and that is
    a question about the rows they share: one pass over those rows, one tuple
    per row. Written as a comprehension rather than a zip(...) so it is the same
    shape the one-column form already has, and so a `$i` anywhere in it counts
    the rows off the one enumerate.
    """
    is_dict = _is_dict_binds(binds)
    item_expr = _PICK_INNER_DICT_ITEM if is_dict else _PICK_INNER_VAR
    parts = [_pick_element_expr(col_id, columns, source_expr, item_expr, binds)
             for col_id in col_ids]
    if any(part is None for part in parts):
        return None
    elt = '(' + ', '.join(inner for inner, _ in parts) + ')'
    names_index = any(names for _, names in parts)
    rows = _pick_band_rows(source_expr, start, stop, is_dict)
    return _pick_comprehension(elt, rows, start, names_index, is_dict)


def _pick_match_expr(col_id: str, columns) -> str | None:
    """Expression for one column of the matched row itself (a scalar).

    Stays in dollar form: the next(...) around it binds the row, so the same
    substitution the search box's own expressions get is the right one, and it
    happens once, later.
    """
    if col_id == PICK_IDX_COLUMN:
        return 'i'
    return _pick_column_expr(col_id, columns)


def _pick_region_expr(region_id: str, columns, source_expr: str,
                      binds: 'dict | None' = None) -> str | None:
    """Dollar-form expression for a single region, or None if it doesn't exist."""
    parsed = _parse_pick_region_id(region_id)
    if parsed is None:
        return None
    band, col_id = parsed
    if band == 'match':
        return _pick_match_expr(col_id, columns)
    band_range = _PICK_BAND_RANGES.get(band)
    if band_range is None:
        return None
    return _pick_range_expr(col_id, columns, source_expr, *band_range, binds)


# Band sets that cover a single contiguous run of rows. A run of rows within ONE
# column evaluates to a list, which is what makes the list-consuming actions
# (Loop, Join) meaningful. {'match'} on its own is a single row -- a scalar --
# and {'pre', 'post'} has a hole in it, so neither qualifies.
_PICK_ARRAY_BAND_SETS = frozenset({
    frozenset(('all',)),
    frozenset(('pre',)),
    frozenset(('post',)),
    frozenset(('pre', 'match')),
    frozenset(('match', 'post')),
    frozenset(('pre', 'match', 'post')),
})


def _pick_bands_by_column(model: dict) -> dict:
    """col_id -> set of picked bands, dropping ids whose column is gone."""
    valid = set(_pick_column_ids(model.get('columns', [])))
    out: dict = {}
    for region_id in (model.get('picked') or []):
        parsed = _parse_pick_region_id(region_id)
        if parsed is None:
            continue
        band, col_id = parsed
        if col_id in valid:
            out.setdefault(col_id, set()).add(band)
    return out


def _pick_shared_range(bands_by_column: dict) -> tuple | None:
    """The one row range every picked column covers, or None if they differ.

    A range, so the lone match band does not qualify: that is a single row, and
    several columns of it are that row's cells rather than a run to read down.
    """
    band_sets = {frozenset(bands) for bands in bands_by_column.values()}
    if len(band_sets) != 1:
        return None
    bands = next(iter(band_sets))
    if bands in _PICK_COLLAPSE_RANGES:
        return _PICK_COLLAPSE_RANGES[bands]
    if bands in _PICK_ARRAY_BAND_SETS:
        return _PICK_BAND_RANGES[next(iter(bands))]
    return None


def _pick_is_array(model: dict) -> bool:
    """True when the pick is one contiguous run of rows -- of one column, or of
    several read down together.

    That is exactly when the picked expression evaluates to a list, so Loop and
    Join apply to it. A lone match row is a scalar, {'pre', 'post'} has a hole
    in it, and columns over different runs are lists side by side -- none of
    those are a single array.
    """
    if model.get('tool') != 'pick':
        return False
    return _pick_shared_range(_pick_bands_by_column(model)) is not None


def _build_pick_expr(model: dict, source_expr: str) -> str | None:
    """Assemble model['picked'] into one dollar-form expression.

    Bands of the same column collapse when they are contiguous: pre+match+post
    is that column over the whole list, pre+match is everything up to and
    including the match, match+post is the match onwards. pre+post has a hole in
    it, so it does not collapse.

    Columns covering the SAME run of rows are read down together, as one list of
    tuples rather than a tuple of lists -- a row of the answer is then a row of
    the table. Columns over different runs have no rows in common to pair up, so
    they stay side by side.

    Whatever survives is emitted in canonical order -- bare when there is one
    item, a tuple when there is more than one. The match band of a column is a
    scalar while pre/post are lists, so they are never concatenated.

    Region ids naming a column that no longer exists are dropped.
    """
    picked = model.get('picked') or []
    if not picked:
        return None
    columns = model.get('columns', [])
    bands_by_column = _pick_bands_by_column(model)
    binds = _model_binds(model)

    if len(bands_by_column) > 1:
        shared = _pick_shared_range(bands_by_column)
        if shared is not None:
            zipped = _pick_zip_expr(
                [col_id for col_id in _pick_column_ids(columns)
                 if col_id in bands_by_column],
                columns, source_expr, *shared, binds)
            if zipped:
                return zipped

    parts = []
    for col_id in _pick_column_ids(columns):
        bands = bands_by_column.get(col_id)
        if not bands:
            continue
        collapsed = _PICK_COLLAPSE_RANGES.get(frozenset(bands))
        if collapsed is not None:
            expr = _pick_range_expr(col_id, columns, source_expr, *collapsed,
                                    binds)
            if expr:
                parts.append(expr)
            continue
        for band in PICK_BANDS:
            if band in bands:
                expr = _pick_region_expr(f'{band}_{col_id}', columns,
                                         source_expr, binds)
                if expr:
                    parts.append(expr)

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return '(' + ', '.join(parts) + ')'


def _pick_source_expr(model: dict, var_and_exp=None) -> str | None:
    """How this table names its own list, for building region expressions."""
    src = model.get('_source_expr') or model.get('linked_source_expr')
    if src:
        return src
    if var_and_exp:
        var_name, expr = var_and_exp
        return var_name if var_name else f"({expr})"
    return None


def _table_rows_exps(model: dict, source_expr: 'str | None') -> list:
    """Every row read across the columns -- the table on screen, as code.

    The column twin of _row_tuple_expr: that one is one row across the columns,
    this is all of them, one tuple per row. Assembled out of the pick builders
    because Pick already writes exactly this expression when every column's
    full-height band is selected -- there is one right answer here and it is
    already written.

    Whatever the columns say is what comes out, so a column the user computed
    reads the same here as it does down the table. A search is not part of it:
    this is the table, not the matches.

    Nothing to offer in three cases, each because something else already says
    it better. A DICT's is `list(d.items())`, which its column header hands
    over. ONE column is that column, which its own header hands over -- the
    same reason _drop_repeats stops a row handle naming one expression twice.
    And a SPLAT column contributes no single value per row, so it is not among
    the ids _pick_column_ids offers; a table of nothing else falls under the
    one-column case and offers nothing.
    """
    columns = model.get('columns', [])
    if source_expr is None or model.get('_is_dict'):
        return []
    col_ids = [col_id for col_id in _pick_column_ids(columns)
               if col_id != PICK_IDX_COLUMN]
    if len(col_ids) < 2:
        return []
    binds = _model_binds(model)
    # The index column contributes `i`, which is what tips _pick_comprehension
    # into the enumerate form -- so the numbered reading is the same call.
    readings = [
        ("Every row's cells", col_ids),
        ('With row numbers', [PICK_IDX_COLUMN] + col_ids),
    ]
    exps = []
    for label, ids in readings:
        expr = _pick_zip_expr(ids, columns, source_expr, None, None, binds)
        if expr:
            exps.append(PyExp(expr, label=label))
    return exps


def _pick_needs_index(pick_expr: str) -> bool:
    """Whether an assembled expression refers to the matched row's index.

    A question about the shape of the expression rather than about any scope in
    it, so the dollars are collapsed rather than bound."""
    tree = _parse_dollar_expr(pick_expr)
    if tree is None:
        # Can't tell, so assume it does: the enumerate form binds `i` whether or
        # not the expression uses it, while the plain form would NameError.
        return True
    return any(isinstance(node, ast.Name) and node.id == 'i'
               for node in ast.walk(tree))


# === Child key management helpers ===

def _remove_column_children(model, column_name):
    """Remove all cell children for a given column."""
    children = model.get('children', {})
    keys_to_remove = [k for k in children if CELL_KEY_SEP in k and k.split(CELL_KEY_SEP, 1)[1] == column_name]
    for k in keys_to_remove:
        del children[k]


def _rename_column_children(model, old_name, new_name):
    """Rename cell children from old column name to new column name."""
    children = model.get('children', {})
    keys_to_rename = [(k, k.split(CELL_KEY_SEP, 1)[0]) for k in children
                      if CELL_KEY_SEP in k and k.split(CELL_KEY_SEP, 1)[1] == old_name]
    for old_key, row_idx in keys_to_rename:
        new_key = f"{row_idx}{CELL_KEY_SEP}{new_name}"
        children[new_key] = children.pop(old_key)


def can_visualize(value):
    return isinstance(value, (list, dict))


def get_fields(value):
    """How this container is addressed from *outside* -- the expressions an
    enclosing table uses to pull cells out of it. A dict addresses by key,
    a list by position. Unrelated to the $k/$v column sigils, which address
    a container from inside."""
    if isinstance(value, dict):
        return [f'$[{k!r}]' for k in value]
    return [f'$[{i}]' for i in range(len(value))]


# What a dict shows when its values have no fields of their own to detect: the
# key beside the value, which is the two-column layout a simple dict wants.
_DICT_DEFAULT_COLUMNS = ['$k', '$v']


def _dict_value_fields(d, get_visualizer) -> list:
    """A dict's VALUES' fields, rebound to read off `$v`.

    The values rather than the rows, because a dict's row is a pair this table
    made up to draw with -- there is no such object to hand a visualizer and
    ask. Each field comes back written against the value as `$`, so the leading
    dollar is rebound to `$v`
    -- through the substitution rather than str.replace, since a field may have
    a `$` inside a string literal.

    Empty when the values have none, which includes the empty dict and the
    simple {'a': 1} case.
    """
    fields = _collect_fields_from_samples(list(d.values()), get_visualizer,
                                          require_all=True)
    if not fields:
        return []
    # Rebound in two passes via a dollar-free placeholder, for the same reason
    # lift_column_predicate does: a replacement that itself contains a dollar
    # never re-parses, which would make every run after the first look like
    # code -- turning the `$` in `$['a$b']` into a binding too.
    holder = '_snc_val_'
    return [replace_dollars_in_py_exp(f, [holder]).replace(holder, '$v')
            for f in fields]


def _dict_value_columns(d, get_visualizer):
    """A dict's columns as the (+) menu offers them: `$k`, then whatever its
    values have to show, and the plain two columns when they have nothing."""
    fields = _dict_value_fields(d, get_visualizer)
    return (['$k'] + fields) if fields else list(_DICT_DEFAULT_COLUMNS)


# How many fields a table will spread across on its own. Past it the row stands
# alone: a table wider than this is harder to read than the values it came from,
# and every field is still one click away in the (+) menu, which offers all of
# them however many were drawn here.
MAX_DEFAULT_FIELDS = 5


def _rows_are_lists(values) -> bool:
    """Whether the rows are LISTS -- by the type rather than by having a
    length, since a string and a dict have one too and neither is a thing whose
    size is what a reader came for.

    One sampled row is enough, by the rule a field only some rows have goes by:
    the column means something wherever it is defined and reads as a hole where
    it isn't.
    """
    if not values:
        return False
    return any(isinstance(values[i], list) for i in _sample_indices(values))


def _default_columns(value, get_visualizer):
    """The columns a table opens with, having nothing saved to open with.

    The row itself, then how big it is where the rows are lists, then the
    fields it spreads into where there are few enough of them to read across.

    The row keeps a column of its own even where its fields are shown beside
    it: it is the thing the table is drawing, and a table made entirely of
    reads OFF the row leaves nowhere to see the row whole, drag it, or ask a
    question of it. A dict has always shown `$v` beside its key for that
    reason; `$` is the same column for a list.

    A dict's length is asked of its VALUES -- its own row is a pair and is two
    long whatever is in it -- and so are its fields, for the reason
    `_dict_value_fields` gives.

    Never empty, so there is no fallback for a caller to remember: the row is a
    column every table has, whatever its rows turn out to be made of.
    """
    is_dict = isinstance(value, dict)
    row = '$v' if is_dict else '$'
    values = list(value.values()) if is_dict else value
    columns = ['$k', '$v'] if is_dict else ['$']
    if _rows_are_lists(values):
        columns.append(f'len({row})')
    fields = (_dict_value_fields(value, get_visualizer) if is_dict else
              _collect_fields_from_samples(value, get_visualizer,
                                           require_all=True) or [])
    if 0 < len(fields) <= MAX_DEFAULT_FIELDS:
        columns += fields
    return columns


_COLUMN_MGMT_DEFAULTS = {
    # The column whose header is a box right now, by name -- see _menu_id:
    # what is being edited does not change when the columns move.
    'editing_column': None,
    # Where the box that writes a new column is, rather than whether there is
    # one: True for the far-right box the (+) opens, and which side of which
    # column for one the ▾ menu asked for (see _add_anchor). One slot, because
    # the box and where it sits are the same fact -- a second key could come to
    # say the box is open somewhere it isn't drawn.
    'adding_column': False,
    'column_input_value': '',
    'selected_suggestion_index': None,
    'column_drag_from': None,
    'column_drag_over': None,
    # Per-column searches, keyed by column expression. Stored as None rather
    # than {} so this shared defaults dict never hands the same dict to two
    # models; always read it as `model.get('column_searches') or {}`.
    'column_searches': None,
    # The terms of a hand-written main search that no column claimed, kept so a
    # column edit recomposes them instead of dropping them. Stored as None when
    # there are none, like the searches above.
    'search_leftovers': None,
    # Per-column aggregations, keyed by column expression like the searches
    # above, and each stored as the expression it is. Nothing records which of
    # the menu's rows are checked: that is read back out of these.
    'column_computes': None,
    # Which chip menu is open on the visible column search row ('op-3' /
    # 'compose-3'). Deliberately not `openDropdown`: those panels are nested
    # inside the column menu, which that single slot is already holding open.
    'col_search_dropdown': None,
    # What the open tally's two filter boxes say, and the order it lists values
    # in. One slot each rather than one per column, like the chip menus above:
    # only the open menu has a tally, and narrowing or reordering its list is a
    # way of reaching a value, not a setting to keep.
    'tally_filter': '',
    'tally_sort': TALLY_SORT_DEFAULT,
    'tally_count_filter': '',
    'tally_count_op': TALLY_COUNT_OP_DEFAULT,
}

_SEARCH_DEFAULTS = {
    'search': None,
    'first_match': False,
    'openDropdown': None,
    'linked_action': None,
    'linked_source_expr': None,
    'last_linked_expr': None,
    'auto_linked_once': False,
    'unlinked_action': None,
    # Pick tool. 'picked' holds region ids and is stored as None rather than []
    # so this shared defaults dict never hands the same list to two models;
    # always read it as `model.get('picked') or []`.
    'tool': 'normal',
    'picked': None,
    'pick_expr': None,
}

_OWN_KEYS = ["Enter", "Escape", "ArrowUp", "ArrowDown", "Tab"]


def _resolve_columns(lst, get_visualizer, slots_config):
    """Return (columns, slot_children) for a list.

    `slots_config` is what was saved for it: the line's comment at the root,
    the parent's slot `children` when nested. A missing config falls back to
    the columns a table opens with.
    """
    if slots_config is not None:
        exprs, slot_children = parse_slots(slots_config)
        return _columns_from_slots(exprs, parse_slot_cols(slots_config)), slot_children

    # The defaults never propose a splat, so they never propose sub-columns.
    return _columns_from_slots(_default_columns(lst, get_visualizer), {}), {}


def init_model(lst, get_visualizer=None, eval_in_scope=None, var_and_exp=None,
               slots_config=None, config_path=None, persist=True):
    """`slots_config`, `config_path` and `persist` are the nesting parameters
    -- see child_nesting_kwargs. At the root the runner passes the line's
    saved slots and an empty path."""
    config_fields = {
        '_config_path': list(config_path or []),
        '_config_persist': persist,
    }

    if get_visualizer is None:
        return {'children': {}, 'handledKeys': [], 'display_mode': 'table', 'columns': {'$': {}},
                '_slot_children': {}, '_is_dict': isinstance(lst, dict),
                **config_fields,
                **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS}

    source_expr = None
    if var_and_exp:
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else expr

    columns, slot_children = _resolve_columns(lst, get_visualizer, slots_config)
    config_fields['_slot_children'] = slot_children
    # A fact about the value, not display state -- see _model_binds.
    config_fields['_is_dict'] = isinstance(lst, dict)

    # Depth backstop: beyond the cap, stop building nested children entirely
    # (renders as a truncated repr) so cyclic values can't RecursionError.
    if too_deep(config_fields['_config_path']):
        return {
            'children': {}, 'handledKeys': list(_OWN_KEYS), 'display_mode': 'table',
            'columns': columns, '_source_expr': source_expr, '_too_deep': True,
            **config_fields, **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS,
        }

    children = {}
    # False when the source can't be re-evaluated for free, and then the rows in
    # hand are what the cells are read from -- see _is_pure_ref.
    read_through = eval_in_scope is not None and _is_pure_ref(source_expr)
    # Only the rows a fresh model can draw. A row loaded later has no child
    # waiting for it and builds one where it is drawn, which is what a cell does
    # for any child it doesn't find -- so this is a cost skipped, not a cell
    # lost. Worth skipping: this is one nested visualizer per cell, and a long
    # list is exactly where the count runs away.
    hidden = _hidden_rows(len(lst), ROWS_PER_PAGE)
    for row in _rows(lst, columns):
        if hidden is not None and hidden[0] <= row.index < hidden[1]:
            continue
        for leaf in _leaf_columns(columns):
            col = leaf.expr
            is_splat = leaf.splat is not None
            # An unsplatted column belongs to the root row, so it builds one
            # child per group rather than one per rendered row -- matching the
            # cells _visualize_table actually draws.
            if not is_splat and not row.span_start:
                continue
            try:
                cell_value = _leaf_cell_value(leaf, row, lst, source_expr,
                                              eval_in_scope, read_through)
            except Exception:
                cell_value = None
            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                # A cell visualizer that doesn't name the nesting params in its
                # init_model gets {} back and isn't handed them.
                extra = child_nesting_kwargs(config_fields, col,
                                             cell_vis.init_model)
                children[f"{row.key}{CELL_KEY_SEP}{col}"] = cell_vis.init_model(
                    cell_value, get_visualizer, eval_in_scope=eval_in_scope, **extra)

    handled_keys = aggregate_handled_keys(children, _OWN_KEYS)
    return {
        'children': children,
        'handledKeys': handled_keys,
        'display_mode': 'table',
        'columns': columns,
        'column_widths': {},
        '_source_expr': source_expr,
        **config_fields,
        **_COLUMN_MGMT_DEFAULTS,
        **_SEARCH_DEFAULTS,
    }


def _column_search_value_label(value: str) -> str:
    """A chip's or option's current value, as menu text.

    The values are Python (`and`, `>=`, `in`), so they render in the code font;
    the empty operator has no code to show and reads as a word instead.
    """
    if value == '':
        return '<span class="col-search-blank" data-charlen="6">(code)</span>'
    return f'<span class="snc-code" data-charlen="{len(value)}">{html.escape(value)}</span>'


def _render_column_search_chip(dropdown_id, current, options, make_event,
                               open_dropdown, chip_class, tooltip='',
                               label=_column_search_value_label) -> str:
    """One of the small dropdowns inside a column's ▾ menu: the two prefixing
    its search box, and the tally's Sort by.

    State-driven like the column menu it sits inside, and for the same reason:
    a hover menu is opened by a listener bound to the widget root, which this
    panel's trigger has already been hoisted out of.

    They share the one `col_search_dropdown` slot, so opening any of them puts
    the others away -- two panels overlapping inside an already-hoisted menu
    would be nowhere to read either of them.
    """
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    is_open = (open_dropdown == dropdown_id)

    panel_html = ''
    if is_open:
        rows = ''.join(
            f'<div class="snc-dropdown-option'
            f'{" selected" if option == current else ""}" '
            f'snc-mouse-down="{html.escape(make_event(option))}">'
            f'{label(option)}</div>'
            for option in options
        )
        panel_html = (
            f'<div class="snc-dropdown-panel flyout col-search-chip-panel" '
            f'snc-dropdown-align="flyout">{rows}</div>'
        )

    chip_classes = f'col-search-chip {chip_class}' + (' open' if is_open else '')
    tooltip_attr = f'data-tooltip="{html.escape(tooltip)}" ' if tooltip else ''
    return (
        f'<span class="snc-dropdown-trigger">'
        f'<span class="{chip_classes}" {tooltip_attr}'
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'{label(current)}'
        f'<span class="col-search-chip-arrow">▾</span></span>'
        f'{panel_html}'
        f'</span>'
    )


def _column_search_scope(binds: 'dict | None' = None) -> DollarScope:
    """The scope a COLUMN SEARCH is written in: one level in from the row, so
    every run is one longer than the main search box's.

    No expressions, because nothing substitutes here: `lift_column_predicate`
    rewrites the text into the main box's scope rather than binding it, carrying
    every sigil across untouched -- none of them names a scope, so the column
    value and the row it was read off share one row number, one key and one
    position. So the sigils are `_row_scope`'s, read at this depth.
    """
    is_dict = _is_dict_binds(binds)
    return DollarScope(
        Dollar('$', "this column's value"),
        *(Dollar(d.token, d.label) for d in _sigil_dollars(binds)),
        Dollar('$$', 'the (key, value) pair' if is_dict else 'the row'),
        Dollar('$$$', 'the whole dict' if is_dict else 'the whole list'),
    )


def _render_column_search_row(col, model) -> str:
    """Render one column's search: [and|or] [comparison] (text).

    The text is written in column scope, where $ is the column value, $$ the row
    item and $$$ the array. Whatever the user types here is lifted and folded
    into the main search box, which does the actual filtering.
    """
    row = _column_search_row(model, col)
    open_dropdown = model.get('col_search_dropdown')

    compose_html = _render_column_search_chip(
        _menu_id('compose', col), row['compose'], COLUMN_SEARCH_COMPOSE,
        lambda v: repr(ColumnSearchComposeSelect(col=col, compose=v)),
        open_dropdown, 'col-search-compose',
        "How this composes with other columns' filters")
    # No tooltip on the operator: it shows the operator, and the box beside it
    # shows what it compares against.
    op_html = _render_column_search_chip(
        _menu_id('op', col), row['op'], COLUMN_SEARCH_OPS,
        lambda v: repr(ColumnSearchOpSelect(col=col, op=v)),
        open_dropdown, 'col-search-op',
        'Search Operation')

    input_event = (f"lambda e: ColumnSearchInput(col={col!r}, "
                   f"value=e.get('value', ''))")
    # Focus is only ever taken right after the brackets were handed over, and
    # then the cursor belongs between them - never on merely opening the menu.
    focus_attrs = ''
    if model.get('_col_search_focus'):
        focus_attrs = f'autofocus snc-cursor-pos="{len("[")}" '
    # The chips sit on top of the search box, the way the string visualizer's
    # toggles sit on top of its Find box - mirrored to the left, since these read
    # before the value rather than after it. They come after the input so they
    # paint over it, and the input reserves room for them with its left padding.
    return (
        f'<div class="col-search-area"'
        f'{_column_dwell_attr(model, owns=(_menu_id("op", col), _menu_id("compose", col)))}>'
        # f'<div class="col-search-label-row"><span>Filter</span> <span>({compose_html} with other columns)</span></div>'
        f'<div class="search-box-wrapper">'
        f'<input type="text" snc-input="{html.escape(input_event)}" '
        f'value="{html.escape(row["text"])}" '
        f'{focus_attrs}'
        f'placeholder="Search" '
        f'data-tooltip="{html.escape(_column_search_scope(_model_binds(model)).legend)}" '
        f'spellcheck="false" '
        f'class="col-search-input search-box" />'
        f'<span class="col-search-chips-right">{op_html}{compose_html}</span>'
        f'</div>'
        f'</div>'
    )


_TALLY_NOTES = {
    TALLY_TOO_MANY: f'More than {TALLY_MAX_CARDINALITY} distinct values',
    TALLY_UNHASHABLE: "These values are not \"hashable\" and are therefore not counted.",
}

def _render_tally_check(checked: bool, disabled: bool = False) -> str:
    """A tally checkbox, which reports the search rather than holding a state of
    its own: CSS has it ignore the pointer, so the click that ticks it is the
    surrounding row's, and `checked` only ever comes from the model.
    """
    return (f'<input type="checkbox" class="col-tally-check"'
            f'{" checked" if checked else ""}'
            f'{" disabled" if disabled else ""} />')


def _tally_sort_label(value: str) -> str:
    """A sort order as menu text: capitalized words, unlike the operator chips
    this shares its shape with, which show the Python they write.

    Capitalized here rather than stored that way, so the model keeps the plain
    vocabulary the code compares against.
    """
    return (f'<span class="col-tally-sort-value">'
            f'{html.escape(value.title())}</span>')


def _tally_count_op_label(value: str) -> str:
    """A count comparison as chip text. The operators show the Python they
    compare with, like the column search's; Min and Max compare with none, so
    they read as words the way Sort by's orders do.
    """
    if value in TALLY_COUNT_EXTREME_OPS:
        return (f'<span class="col-tally-count-op-value">'
                f'{html.escape(value.title())}</span>')
    return _column_search_value_label(value)


def _render_column_tally(col, model, lst, eval_in_scope=None) -> str:
    """Render one column's tally: each distinct value and how many rows have it.

    Only computed while the menu is open, which is the one time the whole column
    is worth evaluating.
    """
    def title_html(expr):
        # The three headers are the section's grab handles: each hands over the
        # code for what it names, so what the user reads is what they can drag
        # into the file.
        return ''
        # return (f'<div class="col-tally-title"><span class="col-tally-title-text"'
                # f'{py_exp_attrs(PyExp(expr, TALLY_IMPORTS))}>Tally</span></div>')

    source_expr = model.get('_source_expr')
    # The two chips the tally opens itself: resting on the tally is not a way
    # of leaving a menu the tally put there.
    dwell = _column_dwell_attr(
        model, owns=(_menu_id('tally-sort', col),
                     _menu_id('tally-count-op', col)))
    tally = _tally(_column_values(col, lst, model, eval_in_scope))
    if tally is None:
        return ''
    if not isinstance(tally, dict):
        # A tally too long to list is still a tally worth handing over; values
        # that can't be counted have no expression to give.
        note_expr = (_tally_counter_expr(col, source_expr, _model_binds(model),
                                         model.get('columns') or {})
                     if tally == TALLY_TOO_MANY and source_expr else None)
        return (f'<div class="col-tally"{dwell}>{title_html(note_expr)}'
                f'<div class="col-tally-note">{_TALLY_NOTES[tally]}</div>'
                f'</div>')
    tally_expr, items_expr, counts_expr = (
        _tally_exprs(col, model, tally, source_expr, eval_in_scope)
        or (None, None, None))

    selected, exclude = _tally_selection(_column_search_row(model, col))
    selected = set(selected)
    filter_text = model.get('tally_filter') or ''
    count_op = _tally_count_op(model)
    # Min and Max leave the box with nothing to hold, so it shows nothing --
    # the number the model still remembers comes back with the next comparison.
    extreme_op = count_op in TALLY_COUNT_EXTREME_OPS
    count_text = '' if extreme_op else (model.get('tally_count_filter') or '')
    sort = _tally_sort(model)

    tally_rows = _tally_rows(tally, model)
    extreme = _tally_extreme(model, tally_rows)
    # A column that spreads its value into rows has no row-scoped predicate to
    # filter by: `*$['pets'] == 'cat'` matches no rows and would quietly empty
    # the table. So the tally stays as a summary -- every count, and the code
    # behind each of them -- and only the checking goes away.
    filterable = _column_row_expr(model.get('columns') or {}, col) is not None
    rows = []
    for text, count, literal in tally_rows:
        if not _tally_lists(model, text, count, extreme, eval_in_scope):
            continue
        label = html.escape(truncate_str(text, 60))
        count_expr = (_tally_row_count_expr(col, source_expr, literal, lst,
                                            _model_binds(model),
                                            model.get('columns') or {})
                      if source_expr and literal is not None else None)
        count_html = (f'<span class="col-tally-count"'
                      f'{py_exp_attrs(count_expr, align="right")}>{count}</span>')
        if literal is None or not filterable:
            # Nothing to compare against, or nowhere to compare it -- so the
            # count is all this row has to offer, and a disabled box says so
            # rather than looking clickable.
            rows.append(
                f'<div class="col-tally-row unselectable">'
                f'{_render_tally_check(False, disabled=True)}'
                f'<span class="col-tally-item snc-code">{label}</span>'
                f'{count_html}</div>')
            continue
        checked = literal in selected
        toggle_event = repr(TallyItemToggle(col=col, literal=literal))
        rows.append(
            f'<div class="col-tally-row{" checked" if checked else ""}" '
            f'snc-mouse-down="{html.escape(toggle_event)}">'
            f'{_render_tally_check(checked)}'
            f'<span class="col-tally-item snc-code">{label}</span>'
            f'{count_html}</div>')

    # A way of reaching a value in a long list, so it reads before them -- and
    # before All and None, which it decides the reach of.
    filter_event = (f"lambda e: TallyFilterInput(col={col!r}, "
                    f"value=e.get('value', ''))")
    filter_html = (
        f'<div class="col-tally-filter-wrapper">'
        f'<input type="text" class="col-tally-filter search-box" '
        f'snc-input="{html.escape(filter_event)}" '
        f'value="{html.escape(filter_text)}" '
        f'placeholder="Search tally" '
        f'data-tooltip="Show only values containing this text" '
        f'spellcheck="false" />'
        f'</div>'
    )
    # A second way of reaching a value: how often it occurs rather than how it
    # reads. The chip sits on top of the box the way the column search's
    # operator does, since it reads before the number the same way.
    count_event = (f"lambda e: TallyCountFilterInput(col={col!r}, "
                   f"value=e.get('value', ''))")
    count_html = (
        f'<div class="search-box-wrapper col-tally-count-box">'
        f'<input type="text" class="col-tally-count-filter search-box" '
        f'snc-input="{html.escape(count_event)}" '
        f'value="{html.escape(count_text)}" '
        f'placeholder="{"" if extreme_op else "N"}" '
        + ('' if extreme_op
           else 'data-tooltip="Show only values with this many rows" ')
        + f'spellcheck="false"{" disabled" if extreme_op else ""} />'
        f'<span class="col-search-chips">'
        + _render_column_search_chip(
            _menu_id('tally-count-op', col), count_op, TALLY_COUNT_OPS,
            lambda v: repr(TallyCountOpSelect(col=col, op=v)),
            model.get('col_search_dropdown'), 'col-tally-count-op',
            label=_tally_count_op_label)
        + '</span></div>'
    )
    # Beside the filter box rather than among All / None / Exclude below it:
    # those say what the search filters on, while these only say which values
    # the menu puts in front of the user, and in what order.
    sort_html = _render_column_search_chip(
            _menu_id('tally-sort', col), sort, TALLY_SORTS,
            lambda v: repr(TallySortSelect(col=col, sort=v)),
            model.get('col_search_dropdown'), 'col-tally-sort',
            'Order the values are listed in', _tally_sort_label)
    # All, None and Exclude say what the search filters on, so they go with the
    # checkboxes on a column there is no filtering by. Sort and the two find
    # boxes stay: they only say which values the menu puts in front of the user.
    select_html = ('' if not filterable else
        f'<span class="col-search-chip" '
        f'data-tooltip="Select every value shown" '
        f'snc-mouse-down="{html.escape(repr(TallySelectAll(col=col)))}">'
        f'All</span>'
        f'<span class="col-search-chip" '
        f'data-tooltip="Select none of the values shown" '
        f'snc-mouse-down="{html.escape(repr(TallySelectNone(col=col)))}">'
        f'None</span>'
        f'<span class="col-tally-exclude{" checked" if exclude else ""}" '
        f'data-tooltip="Filter to everything but the selected values" '
        f'snc-mouse-down="{html.escape(repr(TallyExcludeToggle(col=col)))}">'
        f'Exclude</span>')
    controls_html = (
        f'<div class="col-tally-controls">'
        f'{select_html}'
        f'<div class="col-tally-sort-box"><div class="col-tally-sort-icon">{ICONS["sort"]}</div>'
        f'{sort_html}'
        f'</div>'
        f'</div>'
    )
    # The filter box stays even when it has hidden everything: it's the way
    # back to the values.
    # if rows:
    body = (
        f'<div class="col-tally-list-header">'
        f'<span class="col-tally-item-header"'
        f'{py_exp_attrs(PyExp(items_expr, TALLY_IMPORTS))}>Tally</span>'
        # Counts sits at the panel's right edge, so its tooltip reads
        # leftwards rather than off the side of the menu.
        f'<span class="col-tally-count-header"'
        f'{py_exp_attrs(PyExp(counts_expr, TALLY_IMPORTS), align="right")}'
        f'>Counts {count_html}</span>'
        f'</div>'
        f'<div class="col-tally-list">'
        f'{"".join(rows)}'
        f'</div>'
    )
    # else:
    #     body = '<div class="col-tally-note">No values match</div>'
    return (f'<div class="col-tally"{dwell}>{title_html(tally_expr)}'
            f'{body}{filter_html}{controls_html}'
            f'</div>')


def _render_column_sort(col, model) -> str:
    """Render the Sort row of a column's ▾ menu, and its submenu when open.

    A flyout out of the already-hoisted column menu, like Compute, and sharing
    its one open slot -- so opening this puts Compute away, and Escape and every
    way of leaving the column menu already close it.

    It carries Compute's classes as well as its own: the two submenus are the
    same list of rows and are styled once, and `col-sort-*` is only a hook for
    what differs.
    """
    dropdown_id = _menu_id('sort', col)
    is_open = model.get('col_search_dropdown') == dropdown_id
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    panel_html = _render_sort_panel(col, model) if is_open else ''
    return (
        f'<div class="snc-dropdown-trigger col-compute col-sort"'
        f'{_column_dwell_attr(model, opens=dropdown_id)}>'
        f'<div class="snc-dropdown-option col-compute-trigger col-sort-trigger'
        f'{" open" if is_open else ""}" '
        f'data-tooltip="Order the rows by this column" '
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'<span class="snc-dropdown-option-label col-compute-title">Sort</span>'
        f'<span class="submenu-right-arrow">▸</span>'
        f'</div>{panel_html}</div>'
    )


def _render_sort_panel(col, model) -> str:
    """Two rows that sort the line the table is showing, and two that write the
    sorted list as a line of its own.

    The first two are checkboxes because a line is either sorted this way or it
    isn't, and the box is read off the line rather than off the model. They are
    inert where there is no expression to rewrite -- a loop variable is bound by
    its statement, not written on it -- and the rows below still work there,
    since writing a new line asks nothing of the old one.

    A column naming `$i` has neither: `sorted` takes a key over rows, and a row
    handed to one on its own doesn't know its number. Rather than hand over code
    that won't run, every row here goes inert -- the same answer as a line with
    nothing to rewrite, reached the same way.

    A splat column reaches it too, and for the same kind of reason: sorting
    orders ROWS, and a column that spreads its value into rows has no one value
    per row to order by.
    """
    # The event still names the TARGET, which is a leaf's identity; the code is
    # written against the expression that identity reads by.
    reads = _column_row_expr(model.get('columns') or {}, col)
    if reads is None or dollar_expr_names_index(reads):
        span, source_expr = None, None
    else:
        span = model.get('_source_span')
        source_expr = model.get('_source_expr')
    text = span[0] if span else None

    rows = []
    for direction in SORT_DIRECTIONS:
        checked = _sort_checked(text, reads, direction, _model_binds(model))
        inert = text is None
        classes = ('col-compute-row col-sort-row'
                   + (' checked' if checked else '')
                   + (' unselectable' if inert else ''))
        toggle_attr = '' if inert else (
            f' snc-mouse-down="'
            f'{html.escape(repr(SortClick(col=col, direction=direction)))}"')
        # What the row would make the line read, which is the code it names --
        # so a row already checked hands over the line as it stands rather than
        # the unsort a click there would write. Rightwards, like every handle in
        # these menus: a tooltip above one would cover the rows around it.
        row_html = (
            f'<div class="{classes}"'
            f'{py_exp_attrs(None if inert else _sort_expr(text, reads, direction, _model_binds(model)), align="right")}>'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(checked, disabled=inert)}'
            f'<span class="col-compute-name">{_sort_label(direction)}</span>'
            f'</span></div>')

        # The row itself is the handle, like Unique and Tally. Without a source
        # there is no list to name and so no line to write or drag.
        code = (None if source_expr is None
                else _sort_expr(source_expr, reads, direction,
                                _model_binds(model)))
        click_attr = '' if code is None else (
            f' snc-mouse-down="'
            f'{html.escape(repr(SortCodeClick(col=col, direction=direction)))}"')


        row_alt_html = (
            f'<div class="col-compute-row col-sort-code col-compute-row-aside"'
            f'{py_exp_attrs(code, align="right")}>'
            f'<span class="col-compute-toggle" {click_attr} data-tooltip="Insert as new code">{ICONS['plus']}</span>'
            f'</span>'
            f'</div>'
        )

        rows.append(
            f'<div class="col-convert-wrapper">'
            f'{row_html}'
            f'{row_alt_html}'
            f'</div>')

    return (f'<div class="snc-dropdown-panel flyout col-compute-panel '
            f'col-sort-panel" snc-dropdown-align="flyout">{"".join(rows)}</div>')


def _render_column_group_by(col, model) -> str:
    """Render the Group By row of a column's ▾ menu.

    A plain row rather than a flyout: there is one thing to write, and it writes
    a line of its own the way Sort's `(new code)` rows and Compute's Unique and
    Tally do. So it takes the dwell that puts an open submenu away, like every
    other row of the menu that opens none of its own.

    The row itself is the handle. Without a source there is no list to name, and
    so no line to write or drag. A splat column has nothing to write either:
    grouping cuts up ROWS by a value each of them has, and a column that spreads
    its value into rows hasn't got one. A column naming `$i` needs no such care:
    the comprehension enumerates, where a sort's key could not.
    """
    source_expr = model.get('_source_expr')
    # The event still names the TARGET; the code is written against the
    # expression that target reads by.
    reads = _column_row_expr(model.get('columns') or {}, col)
    code = (None if source_expr is None or reads is None
            else _group_by_expr(reads, source_expr, _model_binds(model)))
    click_attr = '' if code is None else (
        f' snc-mouse-down="{html.escape(repr(GroupByClick(col=col)))}"')
    # Rightwards, like every handle in these menus: a tooltip above one would
    # cover the rows around it.
    return (
        f'<div class="snc-dropdown-option col-group-by'
        f'{"" if code else " unselectable"}"'
        f'{_column_dwell_attr(model)}{py_exp_attrs(code, align="right")}>'
        f'<span class="snc-dropdown-option-label"{click_attr}>Group By</span>'
        f'</div>'
    )


# What the box at the foot of the Subcolumns submenu says its dollars mean.
#
# Assembled rather than written out, because a sub-column's scope is a fact
# about where its box sits and the box sits in four places. Two questions settle
# it: whether the column the sub is being added TO spreads its value into rows,
# and whether anything above it does.
#
# `$` is what the sub is written against -- one element under a splat, the
# column's own value otherwise. `$$` is the scope THAT was written in: the row
# for a top-level column (`_compose_sub` maps the parent's `$$` back to `$`),
# and the value it was read off for a nested one. Under a splat neither holds --
# `_column_dollars` puts the source expression beside the element, so `$$` is
# the whole list and the row has no name here at all.
#
# `$j`, the element's place in its group, exists wherever a splat does, which
# includes a plain sub-column read off a splatted element. `$$$` is left out
# everywhere because nothing binds it: two scopes are threaded in, and a longer
# run is left as written.
#
# A sub-column sees the row's whole binding map (see _leaf_cell_value), so a
# dict's halves reach it the way they reach the main box, and its `$i` counts
# entries for the same reason it does there.


def _subcol_binds(col: str, binds: 'dict | None' = None) -> dict:
    """The sigils a sub-column of *col* binds.

    `Row.bindings` with a `j` added by `_expand_row` for every splat level, and
    that is what `_leaf_cell_value` threads -- so a sub-column sees the
    container's own sigils wherever it sits, plus the element's place in its
    group wherever a splat is above it.
    """
    out = dict(binds or {})
    if any(_split_splat(part)[0] for part in col.split(SUBCOL_SEP)):
        out['j'] = 'j'
    return out


def _subcol_scope(col: str, binds: 'dict | None' = None) -> DollarScope:
    """The scope a SUB-COLUMN of *col* is written in.

    Read off the key's segments rather than off the config, so a splat nested
    under a plain column -- whose composed key leads with the plain parent and
    so has no star at the front to recognise it by -- is read as the splat it
    is.

    Also the scope the Column code box speaks while a sub-column is being
    EDITED: that box holds the sub-column's own expression, written in the scope
    its parent hands out, so the box it is edited in and the box it was written
    in promise the same thing by construction.

    Three shapes for `$$`, because a sub-column sits in four places. It is the
    scope `$` itself was written in: the row for a top-level column, the value
    it was read off for a nested one. Under a splat neither holds --
    `_column_dollars` puts the source expression beside the element, so the row
    has no name here at all.
    """
    path = col.split(SUBCOL_SEP)
    is_splat = _split_splat(path[-1])[0]
    is_dict = _is_dict_binds(binds)
    if is_splat:
        outer = 'the whole dict' if is_dict else 'the whole list'
    elif len(path) == 1:
        outer = 'the (key, value) pair' if is_dict else 'the row'
    else:
        outer = 'the value it was read off'
    return DollarScope(
        Dollar('$', 'one item of the column' if is_splat else "this column's value"),
        *(Dollar(d.token, d.label)
          for d in _sigil_dollars(_subcol_binds(col, binds))),
        Dollar('$$', outer),
    )


def _render_column_restar(col, model, lst, eval_in_scope=None) -> str:
    """Render the row that moves a column across the star: Expand list items
    into rows over a column of lists, Collapse lists to single cells over the
    splat that made.

    One row rather than two, because a column is only ever on one side of the
    star -- a menu offering both would have one of them do nothing, and the
    reader would have to work out which.

    A row that comes and goes with the data, unlike Subcolumns, which is always
    there because an expression can be written against any column. There is
    nothing to write here: the row IS the whole action, and over a column of
    numbers it would name something that cannot happen.

    It takes the dwell that puts an open submenu away, like every other row of
    the menu that opens none of its own.
    """
    if _can_collapse_column(col, model):
        label, event = 'Collapse lists to single cells', UnsplatColumnClick(col=col)
    elif _can_expand_column(col, lst, model, eval_in_scope):
        label, event = 'Expand list items into rows', SplatColumnClick(col=col)
    else:
        return ''
    return (
        f'<div class="snc-dropdown-option col-expand-rows"'
        f'{_column_dwell_attr(model)}>'
        f'<span snc-mouse-down="{html.escape(repr(event))}" '
        f'class="snc-dropdown-option-label">{label}</span>'
        f'</div>'
    )


def _render_column_subcols(col, model, lst, get_visualizer=None,
                           eval_in_scope=None) -> str:
    """Render the Subcolumns row of a column's ▾ menu, and its submenu when
    open.

    A flyout like Compute's, and sharing its one open slot. Offered on every
    column: there is nothing to detect on a column of numbers, but an
    expression can still be written against one, and a row that comes and goes
    with the data would be a worse thing to look for than a row that is always
    there.
    """
    dropdown_id = _menu_id('subcols', col)
    is_open = model.get('col_search_dropdown') == dropdown_id
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    panel_html = (_render_subcol_panel(col, model, lst, get_visualizer,
                                       eval_in_scope) if is_open else '')
    return (
        f'<div class="snc-dropdown-trigger col-compute col-subcol"'
        f'{_column_dwell_attr(model, opens=dropdown_id)}>'
        f'<div class="snc-dropdown-option col-compute-trigger col-subcol-trigger'
        f'{" open" if is_open else ""}" '
        f'data-tooltip="Spread this column across several" '
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'<span class="snc-dropdown-option-label col-compute-title">'
        f'Subcolumns</span>'
        f'<span class="submenu-right-arrow">▸</span>'
        f'</div>{panel_html}</div>'
    )


def _render_subcol_panel(col, model, lst, get_visualizer=None,
                         eval_in_scope=None) -> str:
    """Show all and Hide all, then a checkbox per field the column's values
    have, then whatever the user has written and an empty box to write another.

    What is checked is read back out of the column's own sub-columns rather
    than stored: the config is the only record of a sub-column, so the box and
    the table cannot come to disagree.
    """
    subs = list(_subs_at(model.get('columns') or {}, col) or {})
    candidates = _subcol_candidates(col, lst, model, get_visualizer,
                                    eval_in_scope)

    rows = [
        f'<div class="col-compute-row col-subcol-row col-subcol-all">'
        f'<span class="col-compute-toggle" '
        f'snc-mouse-down="{html.escape(repr(event))}">'
        f'<span class="col-compute-nocheck"></span>'
        f'<span class="col-compute-name">{label}</span>'
        f'</span></div>'
        for label, event in (('Show all', SubcolShowAll(col=col)),
                             ('Hide all', SubcolHideAll(col=col)))
    ]

    if candidates:
        rows.append('<div class="col-compute-sep"></div>')
    for expr in candidates:
        checked = expr in subs
        rows.append(
            f'<div class="col-compute-row col-subcol-row'
            f'{" checked" if checked else ""}">'
            f'<span class="col-compute-toggle" snc-mouse-down="'
            f'{html.escape(repr(SubcolToggle(col=col, expr=expr)))}">'
            f'{_render_tally_check(checked)}'
            f'<span class="col-compute-name">{html.escape(expr)}</span>'
            f'</span></div>')

    rows.append('<div class="col-compute-sep"></div>')
    # A box names itself by where it sits rather than by what it says, for the
    # reason the aggregation boxes do: the first character typed adds a column
    # to the table, and a box found again by its place in the list of
    # everything focusable would lose the rest of the word to it.
    for i, expr in enumerate([s for s in subs if s not in candidates] + ['']):
        written = bool(expr.strip())
        toggle_attr = '' if not written else (
            f' snc-mouse-down="'
            f'{html.escape(repr(SubcolToggle(col=col, expr=expr)))}"')
        rows.append(
            f'<div class="col-compute-row col-subcol-row col-subcol-free'
            f'{" checked" if written else ""}">'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(written, disabled=not written)}</span>'
            f'<input type="text" class="col-compute-expr search-box" '
            f'snc-input="{html.escape(_subcol_expr_event(col, expr))}" '
            f'snc-focus-key="subcol-free-{col}-{i}" '
            f'snc-key-down="{html.escape(repr(SubcolExprKeyDown()))}" '
            f'data-tooltip="{html.escape(_subcol_scope(col, _model_binds(model)).legend)}" '
            f'value="{html.escape(expr)}" placeholder="Subcolumn" '
            f'spellcheck="false" />'
            f'</div>')

    return (f'<div class="snc-dropdown-panel flyout col-compute-panel '
            f'col-subcol-panel" snc-dropdown-align="flyout">'
            f'{"".join(rows)}</div>')


def _subcol_expr_event(col: str, expr: str) -> str:
    """The box that holds a whole sub-column expression, at the foot of the
    submenu."""
    return (f"lambda e: SubcolExprInput(col={col!r}, expr={expr!r}, "
            f"value=e.get('value', ''))")


def _render_column_convert(col, model) -> str:
    """Render the Convert Type row of a column's ▾ menu, and its submenu when
    open.

    A flyout out of the already-hoisted column menu, like Sort, and sharing its
    one open slot -- so opening this puts Sort away, and Escape and every way of
    leaving the column menu already close it.

    It carries Compute's classes as well as its own, for Sort's reason: the
    three submenus are the same list of rows and are styled once.
    """
    dropdown_id = _menu_id('convert', col)
    is_open = model.get('col_search_dropdown') == dropdown_id
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    panel_html = _render_convert_panel(col, model) if is_open else ''
    return (
        f'<div class="snc-dropdown-trigger col-compute col-convert"'
        f'{_column_dwell_attr(model, opens=dropdown_id)}>'
        f'<div class="snc-dropdown-option col-compute-trigger'
        f' col-convert-trigger{" open" if is_open else ""}" '
        f'data-tooltip="Read this column\'s values as another type" '
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'<span class="snc-dropdown-option-label col-compute-title">'
        f'Change Type</span>'
        f'<span class="submenu-right-arrow">▸</span>'
        f'</div>{panel_html}</div>'
    )


def _render_convert_panel(col, model) -> str:
    """One row per type that rewrites the column, and one per type that writes
    another column beside it.

    The first four are checkboxes because a column either reads as a type or it
    doesn't, and the box is read off the column expression rather than off the
    model. Neither half needs the line the table is showing -- a conversion is
    about the column -- so, unlike Sort, a list with nothing to rewrite is no
    reason for a row to go inert. What does dim one is a sibling that already
    reads that way: two columns would share one identity.
    """
    columns = model.get('columns') or {}
    source_expr = model.get('_source_expr')
    binds = _model_binds(model)
    current = _converted_type(col.split(SUBCOL_SEP)[-1])

    rows = []
    for to in CONVERT_TYPES:
        checked = current == to
        # Clicking the type the column already reads as takes the conversion
        # off, so one row is both the way in and the way out.
        seg, _ident = _convert_target(col, None if checked else to)
        inert = not _convert_writable(columns, col, seg)
        toggle_attr = '' if inert else (
            f' snc-mouse-down="'
            f'{html.escape(repr(ConvertTypeToggle(col=col, to=to)))}"')
        # The row names a TYPE, not the click, so a row already checked hands
        # over the column as it stands rather than the unconversion a click
        # there would write. Rightwards, like every handle in these menus: a
        # tooltip above one would cover the rows around it.
        code = (None if inert else
                _convert_values_expr(columns, col, to, source_expr, binds))

        row_html = (
            f'<div class="col-compute-row col-convert-row'
            f'{" checked" if checked else ""}'
            f'{" unselectable" if inert else ""}"'
            f'{py_exp_attrs(code, align="right")}>'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(checked, disabled=inert)}'
            f'<span class="col-compute-name">{to}</span>'
            f'</span>'
            f'</div>'
        )


        # The row itself is the handle, like Sort's `(new code)` rows. What it
        # writes replaces any conversion the column already has rather than
        # nesting inside it, the way the checkboxes do.
        seg, _ident = _convert_target(col, to)
        click_attr = (
            f' snc-mouse-down="'
            f'{html.escape(repr(ConvertTypeColumnClick(col=col, to=to)))}"')
        code = _convert_values_expr(columns, col, to, source_expr, binds)

        row_alt_html = (
            f'<div class="col-compute-row col-convert-row col-compute-row-aside"'
            f'{py_exp_attrs(code, align="right")}>'
            f'<span class="col-compute-toggle" {click_attr} data-tooltip="Insert as a new column">{ICONS['column-right']}</span>'
            f'</span>'
            f'</div>'
        )

        rows.append(
            f'<div class="col-convert-wrapper">'
            f'{row_html}'
            f'{row_alt_html}'
            f'</div>')

    # rows.append('<div class="col-compute-sep"></div>')
    # for to in CONVERT_TYPES:
    #     # The row itself is the handle, like Sort's `(new code)` rows. What it
    #     # writes replaces any conversion the column already has rather than
    #     # nesting inside it, the way the checkboxes do.
    #     seg, _ident = _convert_target(col, to)
    #     inert = not _convert_writable(columns, col, seg)
    #     click_attr = '' if inert else (
    #         f' snc-mouse-down="'
    #         f'{html.escape(repr(ConvertTypeColumnClick(col=col, to=to)))}"')
    #     code = (None if inert else
    #             _convert_values_expr(columns, col, to, source_expr, binds))
    #     rows.append(
    #         f'<div class="col-compute-row col-compute-code col-convert-code'
    #         f'{" unselectable" if inert else ""}"'
    #         f'{py_exp_attrs(code, align="right")}>'
    #         f'<span class="col-compute-toggle"{click_attr}>'
    #         f'<span class="col-compute-nocheck"></span>'
    #         f'<span class="col-compute-name">{to} (new column)</span>'
    #         f'</span></div>')

    return (f'<div class="snc-dropdown-panel flyout col-compute-panel '
            f'col-convert-panel" snc-dropdown-align="flyout">'
            f'{"".join(rows)}</div>')


def _render_column_compute(col, model, lst, eval_in_scope=None) -> str:
    """Render the Compute row of a column's ▾ menu, and its submenu when open.

    A flyout out of an already-hoisted panel, like the chip menus on the search
    row, and sharing their one open slot -- so opening this puts those away, and
    Escape and every way of leaving the column menu already close it.

    Only computed while the submenu is open, which is the one time the whole
    column is worth evaluating for an answer nobody has asked to keep.
    """
    dropdown_id = _menu_id('compute', col)
    is_open = model.get('col_search_dropdown') == dropdown_id
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    panel_html = (_render_compute_panel(col, model, lst, eval_in_scope)
                  if is_open else '')
    return (
        f'<div class="snc-dropdown-trigger col-compute"'
        f'{_column_dwell_attr(model, opens=dropdown_id)}>'
        f'<div class="snc-dropdown-option col-compute-trigger'
        f'{" open" if is_open else ""}" '
        f'data-tooltip="Summarize this column" '
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'<span class="snc-dropdown-option-label col-compute-title">Compute</span>'
        f'<span class="submenu-right-arrow">▸</span>'
        f'</div>{panel_html}</div>'
    )


def _render_compute_panel(col, model, lst, eval_in_scope=None) -> str:
    """One row per aggregation: a checkbox, its name, a box for each hole in
    its expression, and the answer.

    The answer is there whether or not the row is checked -- glancing at the
    mean is the common case, and checking the box is only for keeping it.

    Under those, the rows that answer with a whole list (Unique, Tally), which
    write a line rather than keep a cell; and under those, the user's own
    aggregations, each a box holding the expression it is, with an empty one at
    the foot to write another in.
    """
    columns = model.get('columns') or {}
    values = _column_values(col, lst, model, eval_in_scope)
    source_expr = model.get('_source_expr')
    values_expr = (None if source_expr is None
                   else _column_whole_expr(columns, col, source_expr,
                                           _model_binds(model)))
    # A row aggregation reads the column off one row at a time, so it is asked
    # of the expression the column reads by rather than of a leaf's identity.
    reads = _column_row_expr(columns, col) or col

    # A column that splatted can be asked the same question two ways, so its
    # rows carry a second box: once per group, beside once for the column.
    # Nothing groups a column that did not splat, so it gets one box as before.
    # Through the leaf, because a splat nested under a plain column is keyed
    # `$['a']\x01*$['b']` and has no leading star to recognise it by.
    #
    # Which of them is ticked is read back out of the COLUMNS, a per-group
    # answer being a column and nothing else -- the way the tally's checkmarks
    # are read back out of the column search.
    leaf = _leaf_for(columns, col)
    group_checked = (set(_group_agg_columns(columns, leaf).values())
                     if leaf is not None else set())

    rows = []

    compute_template_rows = []
    grouped_compute_template_rows = []

    for is_group in [False, True]:
        for label, template, checked in _compute_rows(model, col):
            answer = _agg_value(template, values, eval_in_scope, lst, reads)
            # A question this column can't answer isn't worth checking -- but one
            # already checked stays clickable, or there'd be no way to uncheck it.
            unanswered = answer is NO_ANSWER
            inert = unanswered and not checked
            classes = ('col-compute-row' + (' checked' if checked else '')
                    + (' unselectable' if inert else ''))
            toggle_attr = '' if inert else (
                f' snc-mouse-down="'
                f'{html.escape(repr(ComputeToggle(col=col, expr=template)))}"')
            # The boxes and the answer sit outside the part that toggles: typing a
            # level, or dragging the answer out, is not a way of checking the row.
            holes = ''.join(
                f'<input type="text" class="col-compute-hole search-box" '
                f'snc-input="{html.escape(_compute_hole_event(col, template, i))}" '
                f'{_agg_hole_tooltip(template)}'
                f'value="{html.escape(text)}" spellcheck="false" />'
                for i, text in enumerate(_agg_holes(template)))
            # Nothing to hand over when there is no answer, and nothing to name the
            # column by when the list has no source.
            code = (None if unanswered or source_expr is None
                    else _agg_col_code(template, col, source_expr,
                                    _model_binds(model), columns))
            # The per-group box asks the same question of one group at a time, so
            # it is offered even when the whole column can't answer it: a column of
            # mixed types may still be summable a group at a time. Offered only
            # where there is an honest column to write, which is what a leaf under
            # a splat has and a column naming where its row sits hasn't.
            group_box = ''
            if leaf is not None and _group_agg_column(leaf, template) is not None:
                group_box = (
                    f'<span class="col-compute-toggle" '
                    f'data-tooltip="{html.escape(COMPUTE_PER_GROUP_TOOLTIP)}" '
                    f'snc-mouse-down="'
                    f'{html.escape(repr(ComputeToggle(col=col, expr=template, per_group=True)))}">'
                    f'{_render_tally_check(template in group_checked)}<span class="col-compute-name">{html.escape(label)}</span>{holes}</span>')

            if is_group:
                if group_box:
                    grouped_compute_template_rows.append(
                        f'<div class="{classes}"{py_exp_attrs(PyExp(code, _agg_imports(template)), align="right")}>'
                        f'{group_box}'
                        f'<span class="col-compute-preview"'
                        f'>{"" if unanswered else _agg_answer_html(template, answer)}</span>'
                        f'</div>'
                    )
            else:
                compute_template_rows.append(
                    f'<div class="{classes}"{py_exp_attrs(PyExp(code, _agg_imports(template)), align="right")}>'
                    f'<span class="col-compute-toggle"{toggle_attr}>'
                    f'{_render_tally_check(checked, disabled=inert)}'
                    f'<span class="col-compute-name">{html.escape(label)}</span>'
                    f'{holes}'
                    f'<span class="col-compute-preview"'
                    f'>{"" if unanswered else _agg_answer_html(template, answer)}</span></span>'
                    f'</div>'
                )



    # Show tabs if there was a grouped compute template
    if len(grouped_compute_template_rows) > 0:
        is_grouped_tab_selected = model.get('grouped_compute_tab_selected')

        rows.append('<div class="col-compute-tabs-wrapper">')
        rows.append('<div class="col-compute-tabs">')
        rows.append(f'<div class="col-compute-tab {"selected" if not is_grouped_tab_selected else ""}" snc-mouse-down="{html.escape(repr(SelectGroupedComputeTab(False)))}">Table</div>')
        rows.append(f'<div class="col-compute-tab {"selected" if is_grouped_tab_selected else ""}" snc-mouse-down="{html.escape(repr(SelectGroupedComputeTab(True)))}">Per Group</div>')
        rows.append('</div>')

        if is_grouped_tab_selected:
            rows = rows + grouped_compute_template_rows
        else:
            rows = rows + compute_template_rows

        rows.append('</div>')
    else:
        rows = rows + compute_template_rows

    rows.append('<div class="col-compute-sep"></div>')
    # A box names itself by where it sits rather than by what it says: the first
    # thing typed into the empty one adds a cell to the table, and a box found
    # again by its place in the list of everything focusable would lose the
    # typing to it.
    for i, template in enumerate(_compute_free_rows(model, col)):
        answer = _agg_value(template, values, eval_in_scope, lst, reads)
        unanswered = answer is NO_ANSWER
        # Through _agg_column_expr like the catalog's rows, so a box holding
        # something written the way Min Item is hands over what it computed.
        code = (None if unanswered or source_expr is None
                else _agg_col_code(template, col, source_expr,
                                   _model_binds(model), columns))
        # A row of theirs is checked by being there at all, and unchecking is
        # how it is taken away: the expression is the only record of it, so
        # there would be nothing left to keep. The empty one is checking
        # nothing yet, and has nothing to take away.
        written = bool(template.strip())
        toggle_attr = '' if not written else (
            f' snc-mouse-down="'
            f'{html.escape(repr(ComputeToggle(col=col, expr=template)))}"')
        rows.append(
            f'<div class="col-compute-row col-compute-free{" checked" if written else ""}"'
            f'{py_exp_attrs(PyExp(code, _agg_imports(template)), align="right") if written else ""}'
            f'>'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(written, disabled=not written)}</span>'
            f'<input type="text" class="col-compute-expr search-box" '
            f'snc-input="{html.escape(_compute_expr_event(col, template))}" '
            f'snc-focus-key="compute-free-{col}-{i}" '
            f'snc-key-down="{html.escape(repr(ComputeExprKeyDown()))}" '
            f'data-tooltip="{html.escape(_compute_scope(_model_binds(model)).legend)}" '
            f'value="{html.escape(template)}" placeholder="Expr" '
            f'spellcheck="false" />'
            f'<span class="col-compute-preview"'
            f'>{"" if unanswered else _agg_answer_html(template, answer)}</span>'
            f'</div>')

    rows.append('<div class="col-compute-sep"></div>')
    for label, template, _suffix in COMPUTE_CODES:
        # The row itself is the handle, there being no answer beside it to hang
        # one off. Without a source there is no line to write and none to drag.
        code = (None if values_expr is None
                else _agg_code(template, values_expr, source_expr))
        click_attr = '' if code is None else (
            f' snc-mouse-down='
            f'"{html.escape(repr(ComputeCodeClick(col=col, expr=template)))}"')
        rows.append(
            f'<div class="col-compute-row col-compute-code'
            f'{"" if code else " unselectable"}"'
            f'{py_exp_attrs(PyExp(code, _agg_imports(template)), align="right")}>'
            f'<span class="col-compute-toggle"{click_attr}>'
            f'<span class="col-compute-nocheck"></span>'
            f'<span class="col-compute-name">{html.escape(label)}</span>'
            f'</span></div>')

    return (f'<div class="snc-dropdown-panel flyout col-compute-panel" '
            f'snc-dropdown-align="flyout">{"".join(rows)}</div>')


def _compute_hole_event(col: str, template: str, hole: int) -> str:
    return (f"lambda e: ComputeHoleInput(col={col!r}, expr={template!r}, "
            f"hole={hole}, value=e.get('value', ''))")


def _agg_hole_tooltip(template: str) -> str:
    """What a box inside an expression says of itself, wherever it is drawn.

    Nothing, for most of them: the number in Percentile's box reads off the name
    beside it. Only the histogram's has anything to add, since "Histogram 10"
    doesn't say what the 10 counts.
    """
    if _agg_is_histogram(template):
        return f'data-tooltip="{html.escape(HISTOGRAM_BINS_TOOLTIP)}" '
    return ''


def _compute_expr_event(col: str, template: str) -> str:
    """The box that holds a whole aggregation, wherever it is drawn: at the foot
    of the submenu, or as the label of the cell it made."""
    return (f"lambda e: ComputeExprInput(col={col!r}, expr={template!r}, "
            f"value=e.get('value', ''))")


def _column_dwell_attr(model, *, opens: 'str | None' = None, owns=()) -> str:
    """What resting the pointer on a row of the column ▾ menu should do.

    A row that has a submenu offers to open it; the rest offer to put away
    whatever is open, so moving down the menu leaves one submenu showing at a
    time without anything having to be clicked.

    Rendered only where dwelling would change something -- every event costs a
    re-run, and a pointer left lying still on a menu that is already as the
    user wants it should cost nothing. *owns* are the dropdowns a row opened
    itself (the search row's two chips, the tally's): resting on the row a chip
    menu belongs to is not a way of leaving it.
    """
    open_id = model.get('col_search_dropdown')
    if opens is None and (open_id is None or open_id in owns):
        return ''
    if open_id == opens:
        return ''
    return (f' snc-dwell="'
            f'{html.escape(repr(ColumnSubmenuDwell(dropdown_id=opens)))}"')


def _render_column_menu(col, model, lst, eval_in_scope=None,
                        get_visualizer=None):
    """Render the rows of the per-column ▾ menu.

    State-driven (no data-hover-menu), so the TypeScript side hoists the panel out
    of the table's overflow container instead of cloning it on hover. Flyout-aligned:
    the panel's top-left corner sits at the ▾'s top-right, so the menu reads as
    belonging to the trigger rather than to the table row beneath it. The hoisting
    code mirrors it to the ▾'s left when there isn't room on the right.
    """
    remove_event = repr(RemoveColumnClick(col=col))
    rows = [
        _render_column_search_row(col, model),
        f'<div class="snc-dropdown-option"{_column_dwell_attr(model)}>'
        f'<span snc-mouse-down="{html.escape(remove_event)}" '
        f'class="snc-dropdown-option-label">Remove</span>'
        f'</div>',
        *(f'<div class="snc-dropdown-option col-add-beside"'
          f'{_column_dwell_attr(model)}>'
          f'<span snc-mouse-down="'
          f'{html.escape(repr(AddColumnAtClick(col=col, after=after)))}" '
          f'class="snc-dropdown-option-label">Insert {side}</span>'
          f'</div>'
          for side, after in (('Left', False), ('Right', True))),
        '<div class="col-compute-sep"></div>',
        # Beside Remove Column: the rows that decide which columns exist,
        # ahead of the three that ask questions about the rows. Expand comes
        # first of them, because it decides what a sub-column would even be
        # read against -- the whole list, or one element of it.        _render_column_restar(col, model, lst, eval_in_scope),
        _render_column_subcols(col, model, lst, get_visualizer,
                               eval_in_scope),
        _render_column_sort(col, model),
        _render_column_group_by(col, model),
        # Above Compute: it says how the column READS, which is a question
        # every row below it -- what the column adds up to, what it is
        # searched and tallied on -- then asks of the converted values.
        _render_column_convert(col, model),
        _render_column_compute(col, model, lst, eval_in_scope),
        '<div class="col-compute-sep"></div>',
        _render_column_tally(col, model, lst, eval_in_scope),
    ]
    # Says what a click outside the menu means, so the front end doesn't have to
    # know which of these panels is a menu or what closing one entails. The
    # submenus are hoisted panels of their own, so "outside" is outside all of
    # them -- clicking in Sort or Compute is not clicking away from this.
    dismiss = repr(ColumnMenuDismiss())
    return (
        f'<div class="snc-dropdown-panel flyout col-menu-panel" '
        f'snc-dropdown-align="flyout" snc-dismiss="{html.escape(dismiss)}">'
        + ''.join(rows)
        + '</div>'
    )


def _render_column_header(col, model, lst, eval_in_scope=None,
                          span_attrs='', extra_classes='', label=None,
                          get_visualizer=None, read_only=False):
    """Render a normal column header with drag handle, column name, and ▾ menu.

    *read_only* (clickacode.readOnlyVisualizers) draws the name alone: no handle to
    reorder by, no click to edit, no ▾ -- every one of those writes config or
    code. The filtered styling stays, since the filter still narrows the rows.

    The header shows the expression as written, dollar and all: it is the same
    text double-clicking it puts in the box, so there is nothing to translate
    between what a column reads as and what it is.

    *label* is what the cell shows when that differs from the column
    expression -- a sub-column is keyed by its composed identity but reads as
    the expression the user wrote.

    *get_visualizer* is here for the ▾ menu: the Subcolumns submenu asks the
    cells' visualizers what fields they have.
    """
    click_event = repr(ColumnClick(col=col))
    drag_start_event = repr(ColumnDragStart(col=col))
    drag_over_event = repr(ColumnDragOver(col=col))
    drag_end_event = repr(ColumnDragEnd(col=col))
    resize_event = repr(ColumnResize(col=col, width=0)) # The width is set by JS

    drag_from = model.get('column_drag_from')
    drag_over = model.get('column_drag_over')
    is_drag_source = (drag_from == col)
    is_drag_target = (drag_from is not None and drag_over == col and drag_from != col)

    th_classes = ['snc-hover-hidden-parent', 'col-header']
    if is_drag_source:
        th_classes.append('col-drag-source')
    if is_drag_target:
        # Which edge the drop line goes on is the one thing in a drag that is
        # genuinely about position rather than identity -- whether the column
        # is coming from the right or from the left. Read off where the columns
        # are DRAWN, in the model in hand, so neither a column that moved since
        # the drag began nor one whose header spans sub-columns can answer with
        # somewhere it isn't.
        at = _drawn_positions(model.get('columns') or {})
        from_right = at.get(drag_from, -1) > at.get(drag_over, -1)
        th_classes.append('col-drag-before' if from_right else 'col-drag-after')
    is_filtered = _column_search_active(model, col)
    if is_filtered:
        th_classes.append('col-filtered')

    if read_only:
        if extra_classes:
            th_classes.append(extra_classes)
        return (
            f'<th class="{" ".join(th_classes)}"{span_attrs} data-col="{repr(html.escape(col))}">'
            f'<span class="col-header-inner">'
            f'<span class="col-name">'
            f'{html.escape(truncate_str(col if label is None else label, 50))}</span>'
            f'</span>'
            f'</th>'
        )

    source_expr = model.get('_source_expr')
    py_exp_attr = ('' if source_expr is None
                   else py_exp_attrs(_column_header_exps(
                       model.get('columns') or {}, col, source_expr,
                       _model_binds(model))))

    # The ▾ trigger is pinned to the cell's right edge by .col-header-inner's flex
    # layout (which lives on an inner span, never on the <th>: display:flex on a
    # table cell drops it out of table layout and unsyncs header and body widths).
    menu_id = _menu_id('col-menu', col)
    open_dropdown = model.get('openDropdown') or {}
    menu_open = open_dropdown.get('id') == menu_id
    toggle_event = repr(DropdownToggle(dropdown_id=menu_id))
    menu_classes = ['col-menu', 'snc-hover-hidden', 'full-opacity-on-hover']
    if menu_open:
        # The open panel is hoisted out of the <th>, so the header stops being
        # hovered as soon as the pointer reaches it; pin the trigger visible.
        menu_classes.append('open')
    if is_filtered:
        # A search set here keeps filtering with the menu closed, so the way in
        # to it stays visible rather than waiting for a hover to reveal it.
        menu_classes.append('active')
    menu_html = (
        f'<span class="snc-dropdown-trigger col-menu-trigger">'
        f'<span snc-mouse-down="{html.escape(toggle_event)}" '
        f'data-tooltip="Column actions" '
        f'class="{" ".join(menu_classes)}">▾</span>'
        f'{_render_column_menu(col, model, lst, eval_in_scope, get_visualizer) if menu_open else ""}'
        f'</span>'
    )

    # Only while a column is actually being dragged. Every mouse move over a
    # header is a full re-run of the user's program -- one per 16ms of movement
    # -- and ColumnDragOver does nothing at all unless a drag is in progress, so
    # outside one they are asked for, paid for, and thrown away. mouseup stays:
    # it isn't continuous, and a release that lands here has to end the drag.
    track_move = ('' if drag_from is None else
                  f'snc-mouse-move="{html.escape(drag_over_event)}" ')



    if extra_classes:
        th_classes.append(extra_classes)
    return (
        f'<th class="{" ".join(th_classes)}"{span_attrs} data-col="{repr(html.escape(col))}" {get_col_width_style(col, model)}'
        f'{track_move}'
        f'snc-mouse-up="{html.escape(drag_end_event)}">'
        f'<span class="col-header-inner">'
        f'<span snc-mouse-down="{html.escape(drag_start_event)}" '
        f'data-tooltip="Drag to reorder" '
        f'class="col-handle col-drag-handle">⣿</span>'
        f'<span snc-mouse-down="{html.escape(click_event)}"'
        f'{py_exp_attr} '
        f'class="col-name">'
        f'{html.escape(truncate_str(col if label is None else label, 50))}</span>'
        f'{menu_html}'
        f'<span snc-resize-col="{html.escape(resize_event)}"'
        f'data-tooltip="Resize" '
        f'class="col-handle col-resize-handle"></span>'
        f'</span>'
        f'</th>'
    )


# The id of the menu the (+) opens. Not one of `_menu_id`'s, which name the
# column they hang off: this one belongs to the table rather than to any column,
# and asks which columns there are at all.
ADD_MENU_ID = 'col-add-menu'


def _render_add_column_header(lst, model, get_visualizer,
                              span_attrs: str = '') -> str:
    """The (+) at the right end of the header row, and the menu it opens.

    A menu rather than the box it used to open. Which columns a table shows is
    mostly a matter of ticking off fields the rows already have and only
    sometimes of writing one, so the box is one row of a list -- Add Column,
    over Show all / Hide all and a checkbox per field. That is exactly the shape
    a column's Subcolumns submenu has, for the same reason: both are asking
    which of a value's fields to spread into columns, one level apart.

    A drop-down rather than a flyout, unlike every menu inside a column's ▾:
    this one sits at the right end of the header with nothing beyond it, so it
    hangs off the (+)'s own right edge rather than reaching further right for
    room it hasn't got.

    It shares the one `openDropdown` slot with the column menus, so opening this
    puts one of those away and Escape closes it like any other.
    """
    menu_open = (model.get('openDropdown') or {}).get('id') == ADD_MENU_ID
    toggle_event = repr(DropdownToggle(dropdown_id=ADD_MENU_ID))
    # The open panel is hoisted out of the <th>, so the header stops being
    # hovered as soon as the pointer reaches it; pin the (+) lit, the way the
    # column menu's ▾ is.
    icon_classes = ['col-add-icon', 'full-opacity-on-hover']
    if menu_open:
        icon_classes.append('open')
    return (
        f'<div class="snc-dropdown-trigger col-add-trigger">'
        f'<span class="{" ".join(icon_classes)}" '
        f'snc-mouse-down="{html.escape(toggle_event)}" '
        f'data-tooltip="Add or remove columns">+</span>'
        f'{_render_add_column_panel(lst, model, get_visualizer) if menu_open else ""}'
        f'</div>'
    )


def _render_add_column_panel(lst, model, get_visualizer) -> str:
    """Add Column, then the row columns, then Show all and Hide all over the
    fields they reach -- two sections of checkboxes with the pair between them,
    acting on the one below (see the note above `_table_field_candidates`).

    What is checked is read back out of the table's own columns rather than
    stored, for the reason the Subcolumns submenu reads its boxes off the
    column's: the config is the only record of a column, so the menu and the
    table cannot come to disagree.

    A column neither list covers -- one the user wrote, like `sorted($)` -- is
    listed with the fields all the same, the way Subcolumns lists the
    expressions written into it: it is checked by being there at all, and Hide
    all reaches it, so a row is what puts it back. It gets no box to edit
    though, unlike a sub-column's: a column is renamed by double-clicking the
    header it is drawn under, and a sub-column has no header of its own to
    double-click.

    It carries the compute panel's classes as well as its own, for the reason
    the three submenus do: they are all the same list of rows, styled once. Its
    own is what CSS reads it back to menu size by -- those three are nested in a
    column's ▾ and shrink to suit, and this one is a top-level menu.
    """
    columns = model.get('columns') or {}
    fields = _table_field_candidates(lst, get_visualizer)
    row_cols = _table_row_candidates(lst)

    def check_row(expr):
        checked = expr in columns
        return (
            f'<div class="col-compute-row col-add-row'
            f'{" checked" if checked else ""}">'
            f'<span class="col-compute-toggle" snc-mouse-down="'
            f'{html.escape(repr(ColumnToggle(expr=expr)))}">'
            f'{_render_tally_check(checked)}'
            f'<span class="col-compute-name">{html.escape(expr)}</span>'
            f'</span></div>')

    rows = [
        f'<div class="col-compute-row col-add-row col-add-write">'
        f'<span class="col-compute-toggle" '
        f'snc-mouse-down="{html.escape(repr(AddColumnClick()))}">'
        f'<span class="col-compute-nocheck"></span>'
        f'<span class="col-compute-name">Add Column</span>'
        f'</span></div>',
        '<div class="col-compute-sep"></div>',
        # The row columns first, because Show all and Hide all reach past them
        # to the fields: anything between the pair and the list they act on
        # would read as theirs.
        *(check_row(expr) for expr in row_cols),
        '<div class="col-compute-sep"></div>',
    ]
    rows += [
        f'<div class="col-compute-row col-add-row col-add-all">'
        f'<span class="col-compute-toggle" '
        f'snc-mouse-down="{html.escape(repr(event))}">'
        f'<span class="col-compute-nocheck"></span>'
        f'<span class="col-compute-name">{label}</span>'
        f'</span></div>'
        for label, event in (('Show all', ColumnShowAll()),
                             ('Hide all', ColumnHideAll()))
    ]

    # A column the user wrote goes with the fields rather than up with the row
    # columns: it is read off the row the way they are, and it is the pair's to
    # hide.
    written = [c for c in columns if c not in fields and c not in row_cols]
    if fields or written:
        rows.append('<div class="col-compute-sep"></div>')
        rows += [check_row(expr) for expr in (*fields, *written)]

    # The same event a column ▾ menu's panel carries: a click outside every open
    # panel is a click away from whichever of them is open, and this is one of
    # them -- it is held open by the same slot and closed by the same call.
    dismiss = repr(ColumnMenuDismiss())
    return (f'<div class="snc-dropdown-panel left col-compute-panel '
            f'col-add-panel" snc-dropdown-align="left" '
            f'snc-dismiss="{html.escape(dismiss)}">{"".join(rows)}</div>')


def _render_row_index_header(model, n_header: int) -> str:
    """The cell over the row numbers.

    It says `$i`: the token a column expression writes to name the number
    underneath it, so the column of numbers is labelled with the way to ask
    about them rather than left blank. Dimmed, like the numbers themselves --
    it heads a column the user didn't add and can't remove.

    The tooltip is that sigil's phrase from `_SIGIL_LABELS`, the same one the
    code boxes' legends read, so hovering here and hovering there can't come
    back with two different accounts of what `$i` counts.

    It reaches down past the sub-column rows for the reason the columns beside
    it do: there is nothing under it to head, and stopping short would slide
    the first sub-column underneath it.
    """
    binds = _model_binds(model)
    tooltip = f'$i is {_SIGIL_LABELS["i"][_is_dict_binds(binds)]}'
    span_attrs = f' rowspan="{n_header}"' if n_header > 1 else ''
    return (f'<th class="row-index-header"{span_attrs} '
            f'data-tooltip="{html.escape(tooltip)}">$i</th>')


def _render_row_menu(model, lst, i: int, parts=None) -> str:
    """The rows of the ▾ menu on a row's number.

    A state-driven panel like the column menu's, so the front end hoists it out
    of the table's overflow container, and flyout-aligned so it reads as
    belonging to the ▾ rather than to the row it is drawn over. It opens no
    submenus of its own, so no row of it takes a dwell.

    Each row is a handle on the line it writes, like Group By: the code a click
    inserts is the code a drag hands over, from the one catalog both read.
    """
    rows = []
    for action, label, code in _row_actions(model, lst, i, parts):
        click_attr = '' if code is None else (
            f' snc-mouse-down='
            f'"{html.escape(repr(RowActionClick(row=i, action=action)))}"')
        rows.append(
            f'<div class="snc-dropdown-option row-action'
            f'{"" if code else " unselectable"}"'
            f'{py_exp_attrs(code, align="right")}>'
            f'<span class="snc-dropdown-option-label"{click_attr}>'
            f'{html.escape(label)}</span>'
            f'</div>')
    dismiss = repr(ColumnMenuDismiss())
    return (f'<div class="snc-dropdown-panel flyout row-menu-panel" '
            f'snc-dropdown-align="flyout" snc-dismiss="{html.escape(dismiss)}">'
            + ''.join(rows)
            + '</div>')


def _render_row_widgets(model, lst, i: int, parts=None) -> tuple:
    """The drag handle and the ▾ that hang off a row's number, as `(left,
    right)` -- the two sides of the number they sit on.

    The row numbers are the only cells a row has that aren't already showing
    something, and they are a character or two wide -- so neither widget is in
    the cell's flow. Both are positioned out of it, the handle over the table's
    left edge and the ▾ over the column beside it, and both are drawn only
    while the number is hovered. So the column stays as wide as its numbers
    and nothing the user came to read is covered up until they reach for it.

    Outside the table's left edge is outside the scrollport that clips it, so
    the handle is `snc-hover-hoist`: the front end lifts a copy of it out to
    the editor container while the number is hovered, the way it lifts a hover
    menu out, and lays that copy over the box the stylesheet gave the original.
    So the original is placed here like anything else and merely made invisible
    -- it is still what says where its copy belongs. The ▾ needs none of this:
    the column it hangs over is inside the table.

    Nothing at all where no row of the menu could write a line -- without a
    source expression there is no list to name, so there is nothing to drag and
    nothing to write, the same answer Group By gives. That is the whole test:
    with a source, Delete always has a line, so a menu with a source in hand
    always has something live in it.

    The menu's own rows are worked out only while it is open. This runs once
    per row of the table and the table draws every row it has, so a closed
    menu's expressions would be several per row of the list, built and thrown
    away on every keystroke. The handle's are not optional -- they are what it
    hands over -- so they are paid for on every row.

    *parts* is `_row_column_exprs` for this row, by its NUMBER, which the body
    has in hand -- the same reason it is threaded rather than asked for again.
    An end-relative reading names its cells differently and asks for its own.
    """
    if model.get('_source_expr') is None:
        return ('', '')
    handle_exprs = _row_handle_exprs(model, lst, i, parts)
    handle = ('' if not handle_exprs else
              f'<span class="row-handle" snc-hover-hoist '
              f'data-tooltip="Drag out this row" '
              f'data-tooltip-align="bottom"'
              f'{py_exp_attrs(handle_exprs)}>⣿</span>')

    menu_id = _menu_id('row-menu', str(i))
    menu_open = (model.get('openDropdown') or {}).get('id') == menu_id
    # The open panel is hoisted out of the cell, so the number stops being
    # hovered as soon as the pointer reaches it; pin the trigger visible.
    open_class = ' open' if menu_open else ''
    toggle_event = repr(DropdownToggle(dropdown_id=menu_id))
    menu = (
        f'<span class="snc-dropdown-trigger row-menu-trigger{open_class}">'
        f'<span snc-mouse-down="{html.escape(toggle_event)}" '
        f'data-tooltip="Row actions" class="row-menu{open_class}">▾</span>'
        f'{_render_row_menu(model, lst, i, parts) if menu_open else ""}'
        f'</span>'
    )
    return (handle, menu)


def _render_row_index_cell(model, lst, i: int, span_attrs: str = '',
                           overlay: str = '', parts=None,
                           widgets: bool = True) -> str:
    """One row's number, and the two controls that hang off it.

    The number and the controls sit in a wrapper INSIDE the cell rather than in
    the cell itself. That wrapper is what can be laid out -- the controls line
    up against the number rather than against a cell as tall as whatever is
    drawn beside it -- and `display: flex` on a <td> drops the cell out of
    table layout, which is the reason `.col-header-inner` exists too.

    So the wrapper is where the handle is placed even though the copy that gets
    drawn is lifted out of the table: the front end lays that copy over the box
    the wrapper gave the original, so the stylesheet here settles where it goes
    and nothing on the other side has to. Which is why `snc-hoist-host` is on
    the wrapper -- it marks what does the laying out.

    The pick overlay stays a child of the CELL: it covers the whole cell and is
    positioned against it, and it is only ever drawn when the controls are not.
    """
    handle, menu = (_render_row_widgets(model, lst, i, parts) if widgets
                    else ('', ''))
    host_attr = ' snc-hoist-host' if handle or menu else ''
    return (f'<td class="row-index"{span_attrs}>'
            f'<div class="row-index-inner"{host_attr}>'
            f'{handle}{i}{menu}'
            f'</div>{overlay}</td>')


def _column_input_tooltip(model) -> str:
    """What the Column code box says its dollars mean, for the column in it.

    A new column, or an existing top-level one, is written in row scope. A
    SUB-column is not: the box holds that sub-column's own expression (see
    ColumnClick, which strips the composed identity down to it), and that
    expression was written in the scope its parent hands out -- where `$` is the
    parent's value or one splatted element, and `$j` names a position the row
    scope has no word for.

    So an edit says exactly what the Subcolumns box that wrote the text says,
    asked of the PARENT: the two boxes hold the same expression and must not
    read as two different scopes.

    A box opened BESIDE a sub-column is writing another one, so it says the
    same thing: what it writes goes in beside its neighbour, in the scope that
    neighbour is read in.
    """
    binds = _model_binds(model)
    beside = _add_beside_target(model)
    written = (model.get('editing_column')
               or (beside[0] if beside is not None else None))
    if written and SUBCOL_SEP in written:
        return _subcol_scope(written.rsplit(SUBCOL_SEP, 1)[0], binds).legend
    return _row_scope(binds, model.get('_source_expr')).legend


def _column_input_html(lst, model, get_visualizer, is_editing):
    """The box a column is written in, with whatever it can suggest."""
    input_value = model.get('column_input_value', '')
    input_event = "lambda e: ColumnInput(value=e.get('value', ''))"

    current_columns = model.get('columns', [])
    if get_visualizer is not None:
        suggestions = _get_column_suggestions(lst, get_visualizer, current_columns, input_value)
    else:
        suggestions = []
    selected_idx = model.get('selected_suggestion_index')

    suggestion_html = ''
    if suggestions:
        items = []
        for i, suggestion in enumerate(suggestions[:10]):
            select_event = repr(ColumnSelect(name=suggestion))
            is_selected = (selected_idx == i)
            option_cls = 'snc-dropdown-option col-suggestion' + (' selected' if is_selected else '')
            scroll_attr = ' snc-scroll-into-view' if is_selected else ''
            items.append(
                f'<div snc-mouse-down="{html.escape(select_event)}" '
                f'class="{option_cls}"'
                f'{scroll_attr}'
                f'>{html.escape(suggestion)}</div>'
            )
        suggestion_html = (
            f'<div class="snc-dropdown-panel left col-suggest-panel" snc-dropdown-align="left">'
            + '\n'.join(items)
            + '</div>'
        )

    extra_attrs = ' autofocus'
    if is_editing:
        extra_attrs += ' snc-select-all'

    return (
        f'<span class="snc-dropdown-trigger">'
        f'<input type="text" snc-input="{html.escape(input_event)}" '
        f'value="{html.escape(input_value)}" '
        f'placeholder="Column code" '
        f'data-tooltip="{html.escape(_column_input_tooltip(model))}" '
        f'spellcheck="false"'
        f'{extra_attrs} '
        f'class="col-input" />'
        f'{suggestion_html}'
        f'</span>'
    )


def _render_column_input(lst, model, get_visualizer, is_editing, span_attrs=''):
    """A header cell holding the box, for a column being added or edited.

    An edited cell keeps the spans the header cell it replaced had: the box is
    a different thing to look at, not a differently-shaped hole in the header.
    Without them a splat being renamed stops covering its sub-columns, and a
    column beside sub-columns stops reaching down past their row -- either way
    everything to the right of it shifts while the user is typing.
    """
    return (f'<th{span_attrs}>'
            f'{_column_input_html(lst, model, get_visualizer, is_editing)}</th>')


def _resolve_first_and_index(model, eval_in_scope):
    """Compute the effective `first` flag and `is_index_search` for the given model.

    Plain slice and plain index searches force first=True (they target a single
    region). Broadcast slices (lists in start/stop) keep the user's first_match
    preference because there are multiple regions to iterate.
    """
    search = model.get('search')
    has_search = search is not None and search != ''
    first = bool(model.get('first_match', False))
    is_index_search = False

    if not has_search:
        return first, is_index_search

    parsed = parse_search_term(search)
    if parsed and parsed[0] == 'slice':
        start_s, stop_s = parsed[1]
        _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
        try:
            sv = _eval(start_s) if start_s else None
        except Exception:
            sv = None
        try:
            ev = _eval(stop_s) if stop_s else None
        except Exception:
            ev = None
        if not (_is_list_of_ints(sv) or _is_list_of_ints(ev)):
            first = True
    elif parsed and parsed[0] == 'expr':
        try:
            val = eval(parsed[1]) if eval_in_scope is None else eval_in_scope(parsed[1])
            if isinstance(val, int) and not isinstance(val, bool):
                first = True
                is_index_search = True
        except Exception:
            pass

    return first, is_index_search


def _is_plain_slice_search(model: dict, eval_in_scope) -> bool:
    """True if the search is a contiguous slice (not a broadcast slice with
    list bounds).

    Plain slices select a multi-item region, so list-wide actions like Join
    apply even though `first` is forced True for them.
    """
    search = model.get('search')
    if not search:
        return False
    parsed = parse_search_term(search)
    if not parsed or parsed[0] != 'slice':
        return False
    start_s, stop_s = parsed[1]
    _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
    try:
        start_val = _eval(start_s) if start_s else None
    except Exception:
        start_val = None
    try:
        stop_val = _eval(stop_s) if stop_s else None
    except Exception:
        stop_val = None
    return not (_is_list_of_ints(start_val) or _is_list_of_ints(stop_val))


def _preview_expr(model, action, eval_in_scope):
    """Pre-compute the Python expression an action would generate.

    Used to populate `data-action-expr` (action buttons) and `snc-py-exps`
    (dropdown rows) so the existing snc-action-tooltip / py-exp-tooltip systems
    can show + copy + drag the expression on hover.
    """
    source_expr = model.get('_source_expr')
    if not source_expr:
        return ''
    ctx = _get_search_context(model, source_expr=source_expr, eval_in_scope=eval_in_scope)
    if ctx is None:
        ctx = _get_whole_list_context(model, source_expr=source_expr)
    if not ctx:
        return ''
    if action.startswith('join:'):
        ctx = dict(ctx)
        ctx['join_separator'] = action[5:]
        action = 'join'
    try:
        result = generate_action(action, ctx)
    except Exception:
        return ''
    # The preview is copied and dragged into the file as-is, so a statement
    # needs the body that generation leaves off.
    return with_pass_body(result[1]) if result else ''


def _preview_py_exp_attrs(model, action, eval_in_scope, **kwargs) -> str:
    """The same preview, as the attributes that hand it to the editor.

    What the code needs imported is declared here, beside the code, exactly as
    it is when the same action is clicked rather than dragged.
    """
    expr = _preview_expr(model, action, eval_in_scope)
    return py_exp_attrs(PyExp(expr, code_imports(expr)), **kwargs)


def _compute_predicate_previews(model: dict, eval_in_scope) -> tuple:
    """Compute (any_val, all_val) boolean previews for the Any/All dropdown.

    Mirrors the string visualizer: evaluate the actual `any(...)` / `all(...)`
    expressions the buttons would generate so the dropdown can show the live
    True/False result. Returns (bool|None, bool|None); None means the value is
    not applicable (e.g. All in first-match mode) or couldn't be computed.
    """
    if eval_in_scope is None:
        return (None, None)
    search = model.get('search')
    if search is None or search == '':
        return (None, None)
    # Any/All are unavailable in pick mode, so don't compute suffixes that would
    # only decorate dimmed rows.
    if model.get('tool') == 'pick':
        return (None, None)

    def _eval_bool(action):
        expr = _preview_expr(model, action, eval_in_scope)
        if not expr:
            return None
        try:
            return bool(eval_in_scope(expr))
        except Exception:
            return None

    first, _ = _resolve_first_and_index(model, eval_in_scope)
    any_val = _eval_bool('any')
    # `all` is disabled in first-match mode (a single item), so no preview then.
    all_val = _eval_bool('all') if not first else None
    return (any_val, all_val)


def _predicate_suffix(val) -> str:
    """Render the ` (True)`/` (False)` suffix for an Any/All dropdown label.

    The boolean value is wrapped in a `snc-code` span so it renders in the code
    font while the surrounding label text stays in the UI font.
    """
    if val is None:
        return ''
    return f' (<span class="snc-code">{html.escape(str(val))}</span>)'


def _render_search_box_input(model, eval_in_scope=None):
    """Render the .search-box + .search-toggles-container row contents.

    Returned HTML is the inside of a single .search-div-row (the input
    wrapper). The outer .search-div wrapper is added by `_render_search_box`.
    """
    search_value = model.get('search') or ''
    search_input_event = "lambda e: SearchBoxInput(value=e.get('value', ''))"

    first_match, _ = _resolve_first_and_index(model, eval_in_scope)

    # With a search, pick composes an expression out of the first match's parts
    # and so pins first-match mode on; without one it spans every row and there
    # is no match to be first. Inert either way until the user leaves pick.
    if model.get('tool') == 'pick':
        pick_has_search = bool(model.get('search'))
        state = 'active' if pick_has_search else 'inactive'
        tooltip = ('Pick uses the first match only' if pick_has_search
                   else 'Pick covers every row')
        first_match_toggle_html = (
            f'<span class="search-button {state} dimmed"'
            f' data-tooltip="{tooltip}">'
            f'{ICONS["match-first"]}'
            f'</span>'
        )
    else:
        fm_event = repr(FirstMatchToggle())
        first_match_toggle_html = (
            f'<span class="search-button {"active" if first_match else "inactive"}"'
            f' data-tooltip="First match only"'
            f' snc-mouse-down="{html.escape(fm_event)}">'
            f'{ICONS["match-first"]}'
            f'</span>'
        )

    toggles_html = (
        f'<span class="search-toggles-container">'
        f'{first_match_toggle_html}'
        f'</span>'
    )

    return (
        f'<div class="search-box-wrapper">'
        f'<input type="text" tabindex="0"'
        f' snc-input="{html.escape(search_input_event)}"'
        f' value="{html.escape(search_value)}"'
        f' placeholder="Search"'
        f' data-tooltip="{html.escape(_row_scope(_model_binds(model), model.get("_source_expr")).legend)}"'
        f' spellcheck="false"'
        f' class="search-box" />'
        f'{toggles_html}'
        f'</div>'
    )


# What the Join menu's own box says of itself. The one box in the action bar,
# and it sits a few pixels from a search box that DOES speak dollars -- so it
# says that it doesn't, which is the only place in the visualizer worth saying
# that. Whatever is typed here goes into `sep.join(...)` as written.
JOIN_SEP_TOOLTIP = 'The separator, as a Python expression (no $ here)'


def _render_action_buttons(model, lst, eval_in_scope=None):
    """Render the .action-buttons bar (no outer wrapper).

    Uses .action-button + .snc-dropdown-trigger / .snc-dropdown-panel /
    .snc-dropdown-option classes shared with the string visualizer. Each
    .action-button carries data-action-expr so the snc-action-tooltip system
    handles copy + drag-to-extract on hover; each .snc-dropdown-option
    carries snc-py-exps for the same purpose.
    """
    search = model.get('search')
    has_search = search is not None and search != ''
    first, is_index_search = _resolve_first_and_index(model, eval_in_scope)
    # In pick mode the actions operate on the picked expression, not on the match
    # set: Any/All and Find Indices have nothing to say about it, while Loop and
    # Join apply exactly when the pick is an array (see _pick_is_array).
    pick_mode = model.get('tool') == 'pick'
    pick_array = _pick_is_array(model)

    match_count = 0
    if has_search and eval_in_scope is not None:
        try:
            match_count = len(_get_matching_indices(search, lst, eval_in_scope))
        except Exception:
            pass
    elif not has_search:
        match_count = len(lst)

    linked_action = model.get('linked_action')

    # Nothing generate_action declines to write should offer a button that
    # looks like it will. For a list that is every action; for a dict the
    # positional families are still cut, so the question is asked per action
    # rather than answered once for the whole container.
    is_dict = bool(model.get('_is_dict'))

    def writes_code(action):
        if not is_dict:
            return True
        return bool(_preview_expr(model, action, eval_in_scope))

    def action_btn(label, action, enabled=True, title='', extra_classes=''):
        enabled = enabled and writes_code(action)
        cls = 'action-button'
        if not enabled:
            cls += ' dimmed'
        if linked_action == action:
            cls += ' linked'
        if extra_classes:
            cls += ' ' + extra_classes
        event = repr(ActionButtonClick(action=action, copy=False))
        expr_attr = (_preview_py_exp_attrs(model, action, eval_in_scope,
                                           draggable=False,
                                           attr='data-action-expr')
                     if enabled else '')
        title_attr = f' title="{html.escape(title)}"' if title else ''
        return (
            f'<span class="{cls}" snc-mouse-down="{html.escape(event)}"'
            f'{expr_attr}{title_attr}>{label}</span>'
        )

    def dropdown_row(label, action, enabled):
        enabled = enabled and writes_code(action)
        cls = 'snc-dropdown-option'
        if not enabled:
            cls += ' dimmed'
        act_event = repr(ActionButtonClick(action=action, copy=False))
        py_exp_attr = (_preview_py_exp_attrs(model, action, eval_in_scope,
                                             draggable=False, align='right')
                       if enabled else '')
        return (
            f'<div class="{cls}"{py_exp_attr}>'
            f'<span snc-mouse-down="{html.escape(act_event)}" class="snc-dropdown-option-label">{label}</span>'
            f'</div>'
        )

    parts = []

    # 1. Count (matches the string visualizer's action-button order)
    # Pick is about what an expression extracts, not about how many rows there
    # are, so counting is off for as long as it is active.
    count_enabled = not (has_search and first) and not pick_mode
    count_label = f'<span class="text">Count: {match_count}</span>'
    parts.append(action_btn(count_label, 'count', count_enabled, 'Count of matches'))

    # 2. Filter / Find One
    filter_lbl = (
        f'{ICONS["filter"]}<span class="text">Find One<span class="shortcut">⏎</span></span>'
        if first
        else f'{ICONS["filter"]}<span class="text">Filter<span class="shortcut">⏎</span></span>'
    )
    # Filter is the action that consumes a picked expression, so it is live for
    # a pick made with no search too.
    parts.append(action_btn(filter_lbl, 'filter',
                            has_search or bool(model.get('pick_expr')),
                            'Filter matches (Enter)'))

    # 3. Loop dropdown (hover-menu, panel always rendered with data-hover-menu)
    loop_enabled = pick_array if pick_mode else not (has_search and first)
    loop_trigger_cls = 'snc-dropdown-trigger' + ('' if loop_enabled else ' dimmed')
    # An array pick is a projection of a row range, so its elements have no
    # meaningful "original index": for a column like len($) they aren't the rows
    # at all, and for a post-band pick the offset lives inside the next(...).
    orig_idx_enabled = loop_enabled and not pick_array
    loop_rows = ''.join([
        dropdown_row('No indices', 'loop_no_idx', loop_enabled),
        dropdown_row('Original indices', 'loop_orig_idx', orig_idx_enabled),
        dropdown_row('New indices', 'loop_new_idx', loop_enabled),
    ])
    parts.append(
        f'<span class="{loop_trigger_cls}">'
        f'<span class="action-button" title="For loop over matches">'
        f'{ICONS["loop"]}<span class="text">Loop</span>'
        f'</span>'
        f'<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
        f'{loop_rows}'
        f'</div>'
        f'</span>'
    )

    # 4. ? (Any/All) dropdown (hover-menu). Show a live True/False preview of
    # the boolean each option would evaluate to (like the string visualizer).
    pred_trigger_cls = 'snc-dropdown-trigger'
    any_val, all_val = _compute_predicate_previews(model, eval_in_scope)
    any_suffix = _predicate_suffix(any_val)
    all_suffix = _predicate_suffix(all_val)
    pred_enabled = has_search and not pick_mode
    pred_all_enabled = pred_enabled and not first
    pred_rows = ''.join([
        dropdown_row(f'Any{any_suffix}', 'any', pred_enabled),
        dropdown_row(f'If Any{any_suffix}', 'if_any', pred_enabled),
        dropdown_row(f'All{all_suffix}', 'all', pred_all_enabled),
        dropdown_row(f'If All{all_suffix}', 'if_all', pred_all_enabled),
    ])
    # Dimmed for pick mode only. Without a search the trigger has always stayed
    # undimmed (just its rows dim), so leave that alone.
    if pick_mode:
        pred_trigger_cls += ' dimmed'
    parts.append(
        f'<span class="{pred_trigger_cls}">'
        f'<span class="action-button" title="Boolean queries">'
        f'{ICONS["exists"]}<span class="text">Any/All</span>'
        f'</span>'
        f'<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
        f'{pred_rows}'
        f'</div>'
        f'</span>'
    )

    # 5. Delete
    delete_lbl = (
        f'{ICONS["bin"]}<span class="text">Delete First<span class="shortcut">⌘⌫</span></span>'
        if first
        else f'{ICONS["bin"]}<span class="text">Delete All<span class="shortcut">⌘⌫</span></span>'
    )
    # Delete is off while pick is active: the user is composing an extraction
    # expression, and firing Delete would throw that work away.
    parts.append(action_btn(delete_lbl, 'delete',
                            has_search and model.get('tool') != 'pick',
                            'Delete matches'))

    # 6. Join dropdown (hover-menu like Loop and Any/All). The custom
    # separator <input> lives inside the panel; hovering the panel keeps it
    # open while the user types.
    open_dropdown = model.get('openDropdown')
    # A plain slice targets a contiguous, multi-item region, so Join applies
    # even though `first` is forced True for slices.
    join_enabled = (pick_array if pick_mode else
                    (not (has_search and first)
                     or _is_plain_slice_search(model, eval_in_scope)))
    join_trigger_cls = 'snc-dropdown-trigger' + ('' if join_enabled else ' dimmed')
    join_btn_cls = 'action-button'
    if linked_action == 'join':
        join_btn_cls += ' linked'

    join_presets = ["''", "' '", "'\\n'", "','", "'\\t'"]
    rows = []
    for sep_expr in join_presets:
        act_action = f'join:{sep_expr}'
        act_event = repr(ActionButtonClick(action=act_action, copy=False))
        py_exp_attr = (_preview_py_exp_attrs(model, act_action, eval_in_scope,
                                             draggable=False, align='right')
                       if join_enabled else '')
        rows.append(
            f'<div class="snc-dropdown-option"{py_exp_attr}>'
            f'<span snc-mouse-down="{html.escape(act_event)}" class="snc-dropdown-option-label">'
            f'{html.escape(sep_expr)}</span>'
            f'</div>'
        )

    custom_sep = (open_dropdown.get('customSep', "''")
                  if open_dropdown and open_dropdown.get('id') == 'action-join'
                  else "''")
    custom_input_event = "lambda e: JoinSeparatorInput(value=e.get('value', ''))"
    custom_act_action = f'join:{custom_sep}'
    custom_py_exp_attr = (_preview_py_exp_attrs(model, custom_act_action,
                                                eval_in_scope, draggable=False,
                                                align='right')
                          if join_enabled else '')
    rows.append(
        f'<div class="snc-dropdown-option"{custom_py_exp_attr}>'
        f'<input type="text" snc-input="{html.escape(custom_input_event)}" '
        f'value="{html.escape(custom_sep)}" '
        f'placeholder="expr" '
        f'data-tooltip="{html.escape(JOIN_SEP_TOOLTIP)}" '
        f'spellcheck="false" '
        f'class="snc-dropdown-input join-sep-input" />'
        f'</div>'
    )

    parts.append(
        f'<span class="{join_trigger_cls}">'
        f'<span class="{join_btn_cls}" title="Join list items into a string">'
        f'<span class="text">Join</span>'
        f'</span>'
        f'<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
        f'{"".join(rows)}'
        f'</div>'
        f'</span>'
    )

    # 7. Find Indices (disabled for single-index searches — the index is already known)
    indices_lbl = (
        f'{ICONS["search-idx"]}<span class="text">First Index</span>'
        if first
        else f'{ICONS["search-idx"]}<span class="text">Find Indices</span>'
    )
    parts.append(action_btn(indices_lbl, 'find_indices',
                            has_search and not is_index_search and not pick_mode,
                            'Indices of matches'))

    return f'<div class="action-buttons">{"".join(parts)}</div>'


# (tool id, icon HTML, display name). Both glyphs live in the bundled
# Pragmasevka nerd font; the pick cursor is the same one the string visualizer
# uses for its own pick tool.
_TOOL_TOOLBAR_TOOLS = [
    ('normal', nerd_font_icon('\U000F01C0'), 'Normal'),
    ('pick', ICONS['pick-tool'], 'Pick'),
]


def _render_tool_toolbar(model: dict) -> str:
    """Render the Normal/Pick toolbar for the upper-right corner.

    Pick needs no search: without one it composes an expression out of whole
    columns rather than out of the first match's parts.
    """
    current = model.get('tool', 'normal')
    if current not in ('normal', 'pick'):
        current = 'normal'
    # Pick builds src[a:b] band slices, which a dict cannot take; bands over
    # list(d.items()) are the natural translation, and land with splat.
    disabled = ('pick',) if model.get('_is_dict') else ()
    return render_tool_toolbar(
        _TOOL_TOOLBAR_TOOLS, current,
        lambda tool: repr(ToolSelect(tool=tool)),
        disabled=disabled)


def _pick_band_for_row(row: int, first_idx: 'int | None') -> str:
    """Which band a row falls in, relative to the first match."""
    if first_idx is None:
        return 'all'
    if row < first_idx:
        return 'pre'
    if row == first_idx:
        return 'match'
    return 'post'


def _pick_edge_class(row: int, first_idx: 'int | None', n_rows: int) -> str:
    """Where a row sits within its band, for the rounded-rect CSS.

    A region spans every row of its band in one column, which is several <td>s
    in different <tr>s, so it cannot be one element. Instead each cell draws its
    own piece: the ends round off and cap the outline, the middles draw only
    side borders, and the stack reads as a single rounded rect.
    """
    band = _pick_band_for_row(row, first_idx)
    if band == 'all':
        lo, hi = 0, n_rows - 1
    elif band == 'pre':
        lo, hi = 0, first_idx - 1
    elif band == 'match':
        lo, hi = first_idx, first_idx
    else:
        lo, hi = first_idx + 1, n_rows - 1
    if lo == hi:
        return 'pick-region-only'
    if row == lo:
        return 'pick-region-first'
    if row == hi:
        return 'pick-region-last'
    return 'pick-region-mid'


def _pick_standalone_exprs(model: dict, source_expr: str, eval_in_scope,
                           region_ids) -> dict:
    """region_id -> a self-contained expression, for drag and hover tooltips.

    Region expressions are written against `i` and `item`, which only exist
    inside the generated next(...) wrapper, so a draggable version has to carry
    that wrapper with it. The search context is built once and re-pointed at
    each region rather than rebuilt per region.
    """
    base = _get_search_context(model, source_expr=source_expr,
                              eval_in_scope=eval_in_scope)
    if not base:
        return {}
    columns = model.get('columns', [])
    binds = _model_binds(model)
    out = {}
    for region_id in region_ids:
        expr = _pick_region_expr(region_id, columns, source_expr, binds)
        if not expr:
            continue
        ctx = dict(base)
        ctx['pick_expr'] = replace_dollars_in_py_exp(
            expr, _column_dollars(source_expr, _default_item_expr(binds)),
            index_exp='i', bindings=binds)
        # Either side of the next(...) may want the row's number -- the region
        # or the predicate it is picked out by -- and one binding serves both.
        ctx['needs_index'] = _pick_needs_index(expr) or bool(base.get('names_index'))
        ctx['is_first'] = True
        result = generate_action('filter', ctx)
        if result:
            out[region_id] = result[1]
    return out


def _render_pick_region(row: int, col_id: str, model: dict, first_idx: int,
                        n_rows: int, standalone_exprs: dict) -> str:
    """Render one cell's slice of a pickable region.

    An absolutely-positioned overlay rather than attributes on the <td>: cells
    hold nested child visualizers that carry their own mouse handlers and drag
    handles, and those would swallow the click.
    """
    band = _pick_band_for_row(row, first_idx)
    region_id = f'{band}_{col_id}'
    classes = ['pick-region', f'pick-band-{band}',
               _pick_edge_class(row, first_idx, n_rows)]
    if region_id in (model.get('picked') or []):
        classes.append('selected')
    event = repr(PickToggle(region_id=region_id))
    expr_attr = py_exp_attrs(standalone_exprs.get(region_id))
    return (
        f'<span class="{" ".join(classes)}" '
        f'snc-mouse-down="{html.escape(event)}"{expr_attr}></span>'
    )


def _render_load_more_row(n_hidden: int, colspan: int, small: bool) -> str:
    """The row that stands in for the rows a table isn't drawing.

    It says both what a click will do and how much is behind it, so how far the
    table reaches is readable without opening anything.

    In the unfocused preview it acts on the press instead of pinning focus to
    the line -- the same opt-out the expand bar takes (see render_expand_toggle)
    and for the same reason: a long value is worth reading further down without
    going to it.

    Under the pick tool it carries no band of its own. A band's outline is drawn
    a cell at a time and capped at the band's own ends (_pick_edge_class), so
    what a gap in the middle of one costs is a cap it never had: the outline
    runs into the gap and out the other side, which is what the band does.
    """
    next_n = min(ROWS_PER_PAGE, n_hidden)
    label = f'Load {next_n} more'
    if n_hidden > next_n:
        label += f' ({n_hidden} hidden)'
    preview_attrs = ' draggable="false" snc-unfocused-clickable' if small else ''
    return (
        f'<tr class="row-load-more">'
        f'<td class="load-more" colspan="{colspan}"{preview_attrs} '
        f'snc-mouse-down="{html.escape(repr(LoadMoreRows()))}">'
        f'{label}</td></tr>'
    )


def _render_pick_preview(model: dict, eval_in_scope) -> str:
    """Live preview line: what the picked expression produces.

    Its own in-flow row rather than the string visualizer's .transform-preview,
    which is absolutely positioned to overlay the right end of the replace input
    and would escape to the container edge here. Nothing renders until something
    is picked.
    """
    if model.get('tool') != 'pick' or not model.get('pick_expr'):
        return ''
    if eval_in_scope is None:
        return ''
    expr = _preview_expr(model, 'filter', eval_in_scope)
    if not expr:
        return ''
    try:
        result = truncate_str(repr(eval_in_scope(expr)), 200)
    except Exception as e:
        result = str(e)
    return (
        f'<div class="pick-preview">'
        f'<span class="pick-preview-arrow">⇒</span>'
        f'<span class="pick-preview-value">{html.escape(result)}</span>'
        f'</div>'
    )

def _render_auxiliary_attributes(model, lst):
    source_expr = model.get('_source_expr') if model else None
    len_exp = f'len({source_expr})' if source_expr else None
    len_n = len(lst)
    # A dict counts entries, a list counts items; either way one of them is
    # singular. Parenthesised because a bare chain of conditionals binds to the
    # right and would answer 'entries' for every plural, dict or not.
    noun = (('entries' if len_n != 1 else 'entry') if model['_is_dict']
            else ('items' if len_n != 1 else 'item'))
    return (
        f'<div class="auxiliary-attributes">'
        f'<div class="tiny-len" snc-unfocused-clickable{py_exp_attrs(len_exp)}>{len_n} {noun}</div>'
        f'</div>'
    )

def _render_search_box(model, lst, eval_in_scope=None, small=False, focused_child=None):
    """Render the full .search-div (search input row + action buttons row)."""
    input_html = _render_search_box_input(model, eval_in_scope)
    has_focused_child_class = ' has-focused-child-search-box' if focused_child else ''

    if small:
        action_buttons_html = ''
    else:
        action_buttons_html = _render_action_buttons(model, lst, eval_in_scope)
    preview_html = '' if small else _render_pick_preview(model, eval_in_scope)
    preview_row = (f'<div class="search-div-row">{preview_html}</div>'
                   if preview_html else '')

    auxiliary_html = _render_auxiliary_attributes(model, lst)

    return (
        f'<div class="search-div toolbar-anchor{has_focused_child_class}">'
        f'<div class="search-div-row">'
        f'<div class="search-replace-container">{input_html}</div>'
        f'</div>'
        f'{preview_row}'
        f'<div class="search-div-row">'
        f'{action_buttons_html}'
        f'</div>'
        f'{auxiliary_html}'
        f'</div>'
    )


def _agg_child_key(asking_col: str, template: str, shown_col: str) -> str:
    """The key an answer is a child under.

    Shaped like a cell's -- something\x00column -- so the column half really is
    the column half, and a column being renamed or removed walks these keys
    along with the rest of the children.

    The other half says which column asked and what it asked, which is all it
    takes to work the answer out again when an event comes back for it: an
    answer is computed rather than looked up, so unlike a cell there is no row
    index that would find it. A row aggregation shows one column while another
    column asked, which is why the two are named separately.
    """
    return (f'agg{AGG_KEY_SEP}{asking_col}{AGG_KEY_SEP}{template}'
            f'{CELL_KEY_SEP}{shown_col}')


def _parse_agg_child_key(key: str):
    """(asking column, aggregation, shown column), or None for a cell's key."""
    head, _, shown_col = key.partition(CELL_KEY_SEP)
    parts = head.split(AGG_KEY_SEP)
    if parts[:1] != ['agg'] or len(parts) != 3:
        return None
    return parts[1], parts[2], shown_col


def _agg_child_nesting(model, key: str, value, child_init_model) -> dict:
    """What an answer's visualizer is told about where it sits.

    Nested, like a cell's: it is drawn inside somebody else's table and so it
    draws small until it is focused, whatever it holds.

    But unsaved, which is the one place it parts from a cell. A cell holds a
    value the config can describe the way to -- this column -- and saves its
    own columns at that path. An answer holds something the table WORKED OUT,
    which is nowhere in the shape of the value and so has no path to be saved
    at. Left saving, an answer would write its columns over the column's own.
    """
    extra = child_nesting_kwargs(model, key, child_init_model)
    # Only if the child asked for it -- an older visualizer that names none of
    # these gets {} back and must keep getting it.
    if 'persist' in extra:
        extra['persist'] = False
    return extra


def _drop_agg_children(model: dict, col: str, keep) -> None:
    """Forget the models of the answers a column no longer shows.

    The counterpart to _remove_column_children, which reaches the answers under
    a column that is going away; this one is for the answers that go while the
    column stays. Only an answer's key parses, so a cell's is never read as one.
    """
    children = model.get('children') or {}
    for child_key in list(children):
        parsed = _parse_agg_child_key(child_key)
        if parsed is not None and parsed[0] == col and parsed[1] not in keep:
            del children[child_key]


def _agg_child_value(key: str, lst, model, eval_in_scope=None):
    """The answer a key points at, worked out from the list again.

    The one place an answer is computed for a child, so what a cell showed and
    what an event coming back from that cell is handed are the same value.
    """
    asking_col, template, shown_col = _parse_agg_child_key(key)
    columns = model.get('columns') or {}
    if not _agg_is_row(template):
        values = _column_values(asking_col, lst, model, eval_in_scope)
        return _agg_display_value(_agg_value(template, values, eval_in_scope))
    item = _agg_value(template, None, eval_in_scope, lst,
                      _agg_row_reads(asking_col, columns) or asking_col)
    if item is NO_ANSWER:
        return NO_ANSWER
    idx = _agg_row_index(lst, item, template,
                         _agg_row_reads(asking_col, columns), eval_in_scope)
    shown = _leaf_for(columns, shown_col)
    return _agg_display_value(_column_cell_value(
        _leaf_row_expr(shown) if shown is not None else shown_col,
        item, lst, eval_in_scope,
        index=None if idx is NO_ANSWER else idx,
        bindings=_row_agg_bindings(lst, item, idx)))


def _agg_child_expr(key: str, source_expr, binds: 'dict | None' = None,
                    columns=None, container=None) -> str | None:
    """The expression that names the value a key points at, or None when the
    list has no source to name it from.

    The one place that expression is written, so the code a cell hands over and
    the code that events coming back from that cell are rebound onto cannot
    drift apart.
    """
    if source_expr is None:
        return None
    asking_col, template, shown_col = _parse_agg_child_key(key)
    if not _agg_is_row(template):
        return _agg_code(template,
                         _column_whole_expr(columns, asking_col, source_expr,
                                            binds))
    item_code = _agg_col_code(template, asking_col, source_expr, binds, columns)
    if item_code is None:
        return None
    shown = _leaf_for(columns or {}, shown_col)
    reads = _leaf_row_expr(shown) if shown is not None else shown_col
    # A dict's row is a PAIR, and every column of one is written as `$k` or
    # `$v` -- so the halves are named off the row the aggregation picked, the
    # same way a sort's key reaches them through its one parameter.
    atom = _atomize(item_code)
    return replace_dollars_in_py_exp(
        reads, _column_dollars(source_expr, item_code),
        index_exp=_agg_row_index_code(item_code, source_expr, template,
                                      _agg_row_reads(asking_col, columns),
                                      binds),
        bindings=({'k': f'{atom}[0]', 'v': f'{atom}[1]'}
                  if _is_dict_binds(binds) else None))


def _agg_display_value(answer):
    """The answer as a cell shows it, which for a number is not quite the object
    that came back.

    `np.float64(2.8000000000000003)` is how numpy writes a number down rather
    than how one reads, and the trailing digits belong to the arithmetic rather
    than to the answer. A cell is read rather than computed against -- what it
    hands over is the expression, which stays exact -- so it is handed the
    number, rounded the way _format_agg_value has always shown it.
    """
    if hasattr(answer, 'item') and getattr(answer, 'shape', None) == ():
        answer = answer.item()
    if isinstance(answer, float):
        return float(f'{answer:.6g}')
    return answer


def _render_agg_answer(template, answer, key, code, model, get_visualizer,
                       eval_in_scope=None, max_width=None) -> str:
    """The answer half of a cell: nothing, bars, or the answer handed to
    whichever visualizer reads its type -- the same as any other cell of the
    table, and for the same reason. An aggregation can answer with anything the
    column holds, and a line of text is only the shape of some of those.

    A histogram stays drawn here: it answers with a pair of arrays whose whole
    meaning is the shape of the bars, which a visualizer of the arrays would
    show as two lists of numbers instead.

    Handed its own expression rather than wrapped in one, so a child with
    handles of its own keeps them, and drawn small until the user pins it --
    both the way a cell does it.

    A child that answers the expression with a handle around its whole self
    stops carrying it: the cell already is that handle, and the inner one's
    tooltip would be drawn above the answer, over the cell's label. The wrapper
    stays, so the value still reads as a handle and still drags -- the cell's
    is what a hover or a drag on it finds.
    """
    if answer is NO_ANSWER:
        return ''
    if _agg_is_histogram(template):
        drawn = _agg_hist_svg(answer)
        if drawn:
            return drawn
    value = _agg_display_value(answer)
    vis = get_visualizer(value)
    child_model = model.get('children', {}).get(key)
    if child_model is None:
        child_model = vis.init_model(
            value, get_visualizer, eval_in_scope=eval_in_scope,
            **_agg_child_nesting(model, key, value, vis.init_model))
        # Kept, so that the model an event runs against is this one rather than
        # the bare fallback route_child_event builds for a child its parent has
        # none for -- which asks for no nesting, and so hands the answer the
        # root's config to read and to overwrite. Keeping it is also what lets
        # an answer the user has opened stay open across a render.
        if child_model is not None:
            model.setdefault('children', {})[key] = child_model
    small = key != model.get('focused_child')
    var_and_exp = (None, code) if code else None
    if hasattr(vis, 'visualize_els'):
        htmls = vis.visualize_els(value, child_model, get_visualizer,
                                  eval_in_scope, max_width=max_width,
                                  max_height=80, small=small,
                                  var_and_exp=var_and_exp)
    else:
        htmls = [vis.visualize(value, child_model, get_visualizer,
                               eval_in_scope, max_width=max_width,
                               max_height=80, small=small,
                               var_and_exp=var_and_exp)]
    drawn = ''.join(defer_drag_grab(child_html, code) for child_html in htmls)
    return f'{wrap_child_prefix(key)}{drawn}{wrap_child_suffix}'


def _agg_label_html(expr: str, col: str, level: int,
                    binds: 'dict | None' = None) -> str:
    """What names a cell: the catalog's word for the aggregation, or a box
    holding the expression when the aggregation is the user's own.

    Either way, what the user wrote is a box wherever it is read. There is no
    name for one of theirs but the expression itself, and the number in a
    percentile's name is theirs too -- so the label carries the same boxes the
    submenu offers, with the same events behind them, and a level can be
    changed where it is read rather than by finding the row that set it.

    They name themselves by where they sit rather than by what they say, so that
    typing in one -- which rewrites what it says -- doesn't cost it the focus it
    is being typed into.

    *binds* is what the submenu's box is asked for too: this box is that box
    under another name, so the scope it says it speaks has to be the same one.
    """
    # The cell around them is a drag handle, and a drag beginning inside a box
    # would take the selection the user was making with it.
    name = _agg_name(expr)
    if name is None:
        return (f'<input type="text" class="col-agg-label col-agg-expr" '
                f'snc-input="{html.escape(_compute_expr_event(col, expr))}" '
                f'snc-focus-key="agg-expr-{col}-{level}" '
                f'snc-key-down="{html.escape(repr(ComputeExprKeyDown()))}" '
                f'data-tooltip="{html.escape(_compute_scope(binds).legend)}" '
                f'value="{html.escape(expr)}" size="{max(len(expr), 4)}" '
                f'draggable="false" spellcheck="false" />')
    holes = ''.join(
        f' <input type="text" class="col-agg-hole" '
        f'snc-input="{html.escape(_compute_hole_event(col, expr, i))}" '
        f'snc-focus-key="agg-hole-{col}-{level}-{i}" '
        f'{_agg_hole_tooltip(expr)}'
        f'value="{html.escape(text)}" size="{max(len(text), 1)}" '
        f'draggable="false" spellcheck="false" />'
        for i, text in enumerate(_agg_holes(expr)))
    return f'<div class="col-agg-label">{html.escape(name)}{holes}</div>'


def _agg_remove_x_html(expr: str, col: str) -> str:
    """The ✕ that takes a cell's aggregation away.

    The submenu's own checkbox event, because an aggregation is checked by being
    in the column's list: unchecking it in the menu and taking it off the table
    are one act, so the ✕ needs no event of its own -- and one the user wrote
    themselves is taken away the same way as any other.

    Only the whole-column answers have one. A per-group answer is a column, and
    a column is taken away by the row its own ▾ menu already offers.

    Not a drag handle, though it sits inside one: what the cell hands over is
    the answer's expression, and a drag begun on the ✕ is a click the user
    slipped on rather than an ask for the code.
    """
    event = ComputeToggle(col=col, expr=expr)
    return ('<span class="col-agg-x snc-hover-hidden" '
            f'snc-mouse-down="{html.escape(repr(event))}" '
            'draggable="false" data-tooltip="Remove aggregation">✕</span>')


def _render_agg_cell(expr, col, level, values, model, get_visualizer,
                     eval_in_scope=None, source_expr=None,
                     max_width=None) -> str:
    """One answer, in a cell of its own."""
    answer = _agg_value(expr, values, eval_in_scope)
    key = _agg_child_key(col, expr, col)
    # A column whose values have changed out from under an aggregation says
    # nothing rather than dropping the cell the user put there.
    code = (None if answer is NO_ANSWER
            else _agg_child_expr(key, source_expr, _model_binds(model),
                                 model.get('columns') or {}))
    return (
        f'<td class="col-agg-cell snc-hover-hidden-parent">'
        f'<div class="col-agg"{py_exp_attrs(PyExp(code, _agg_imports(expr)))}>'
        f'{_agg_label_html(expr, col, level, _model_binds(model))}'
        f'{_agg_remove_x_html(expr, col)}'
        f'<div class="col-agg-value">'
        f'{_render_agg_answer(expr, answer, key, code, model, get_visualizer, eval_in_scope, max_width)}'
        f'</div>'
        f'</div></td>')


def _column_cell_value(col: str, item, lst, eval_in_scope=None, index=None,
                       bindings=None):
    """One row's value for a column, or NO_ANSWER when the column can't be read
    off that row.

    *lst* is what the column's `$$` names and *index* what its `$i` does -- the
    row it is read off is not the whole of its scope. *bindings* is the rest of
    it: a dict's row is a PAIR, and every column of one is written as `$k` or
    `$v`, so without them every cell of a dict's row reads as no value at all.
    """
    try:
        return eval_dollar_expr(col, item, eval_in_scope, outer=(lst,),
                                index=index, bindings=bindings)
    except Exception:
        return NO_ANSWER


def _row_agg_bindings(lst, item, index=None) -> dict:
    """What the suffixed dollars stand for in the row a row aggregation picked.

    The same map _root_rows builds for a drawn row, for a row that is not drawn
    from the container's own order: the pair a dict's row is, and the number the
    aggregation found it at.
    """
    binds = {} if index is None or index is NO_ANSWER else {'i': index}
    if isinstance(lst, dict) and isinstance(item, tuple) and len(item) == 2:
        binds.update({'k': item[0], 'v': item[1]})
    return binds


def _render_agg_item_row(expr, ci, level, columns, lst, model, get_visualizer,
                         eval_in_scope=None, source_expr=None,
                         max_width=None) -> str:
    """A row aggregation's row: the row of the list a column's Min Item or Max
    Item picked out, drawn across every column with its index beside it.

    The row comes out of the aggregation's own expression and its index out of
    the list's own `.index` of that row, so the values on screen and the code
    each cell hands over name the same row of the list. The column's values are
    never gathered at all: `min` with a key reads them one row at a time.

    Only the column that asked is labelled. The other cells are that row's
    values, and a "Min Item" over each of them would read as a claim that each
    was least in its own column.

    The row's own name -- the label spilling across the row -- is what hands
    over the row itself. Nothing else in the row does: each cell hands over a
    column of it and the index cell the number beside it, so without the name
    there is no handle on the row unless a `$` column happens to be drawn.
    """
    leaves = _leaf_columns(columns)
    asking = leaves[ci].expr
    reads = _column_row_expr(columns, asking)
    item = _agg_value(expr, None, eval_in_scope, lst, reads or asking)
    idx = _agg_row_index(lst, item, expr, reads, eval_in_scope)
    # Nothing to hand over when the aggregation has no row to point at, and
    # nothing to name the list by when it has no source.
    binds = _binds_for(lst)
    item_code = (None if item is NO_ANSWER or source_expr is None
                 else _agg_col_code(expr, asking, source_expr, binds, columns))
    idx_code = (None if idx is NO_ANSWER or item_code is None
                else _agg_row_index_code(item_code, source_expr, expr,
                                         reads, binds))

    cells = [f'<td class="row-index col-agg-cell">'
             f'<div class="col-agg"{py_exp_attrs(PyExp(idx_code, _agg_imports(expr)))}>'
             f'<div class="col-agg-label col-agg-item-label"'
             f'{py_exp_attrs(PyExp(item_code, _agg_imports(expr)))}>'
             f'{_agg_name(expr)} by {reads or asking}</div>'
             f'<div class="col-agg-label"></div>' # needed for spacing, the above is position: absolute to overflow
             f'{"" if idx is NO_ANSWER else _format_agg_value(idx)}'
             f'</div></td>']
    add_box = _add_box_leaf(model, columns)
    for cj, leaf in enumerate(leaves):
        col = leaf.expr
        # The column being written has no value for this row either, and the
        # row still has to line up with the columns above it.
        if add_box is not None and add_box[0] == cj:
            cells.append('<td class="col-add-blank"></td>')
        value = (NO_ANSWER if item is NO_ANSWER
                 else _column_cell_value(_leaf_row_expr(leaf), item, lst,
                                         eval_in_scope,
                                         index=None if idx is NO_ANSWER else idx,
                                         bindings=_row_agg_bindings(lst, item, idx)))
        key = _agg_child_key(asking, expr, col)
        code = (None if value is NO_ANSWER or item_code is None
                else _agg_child_expr(key, source_expr, binds, columns))
        label = ('<div class="col-agg-label"></div>' if cj != ci else
                 f'{_agg_label_html(expr, asking, level, binds)}'
                 f'{_agg_remove_x_html(expr, asking)}')
        side_value_class = ' not-agg-col' if cj != ci else ''
        cells.append(
            f'<td class="col-agg-cell snc-hover-hidden-parent">'
            f'<div class="col-agg{side_value_class}"{py_exp_attrs(PyExp(code, _agg_imports(expr)))}>'
            f'{label}<div class="col-agg-value">'
            f'{_render_agg_answer(expr, value, key, code, model, get_visualizer, eval_in_scope, max_width)}'
            f'</div>'
            f'</div></td>')
    return f'<tr class="col-agg-row col-agg-item-row">{"".join(cells)}</tr>'


def _agg_layout(columns, model) -> List[tuple]:
    """The rows of answers under the table, top to bottom.

    A row of cells is `('cells', [expr or None per LEAF])`; a row aggregation
    takes a row to itself and is `('item', leaf index, expr)`.

    Per leaf rather than per top-level column, because that is what the body
    draws: a table with sub-columns has more cells in a row than it has columns,
    and a row of answers as wide as the columns would leave every cell after the
    first sitting under the wrong one -- and an answer asked of a sub-column
    with nowhere to go at all.

    The cells come first and the rows of the list under them, because an answer
    about a column reads as part of that column while a row of the list reads
    as part of the list -- and because a column asked for its aggregations in
    menu order, where Min Item and Max Item are last anyway.

    The stacks hang from the bottom rather than sitting from the top: a column
    with fewer answers than the deepest one is blank in the rows *above* its
    first. The floor is the edge every stack shares -- the table is right over
    it -- so hanging from it is what keeps the cells reading as one block
    rather than as a ragged bottom edge.
    """
    stacks = [_column_computes(model, leaf.expr)
              for leaf in _leaf_columns(columns)]
    cell_stacks = [[expr for expr in stack if not _agg_is_row(expr)]
                   for stack in stacks]
    depth = max((len(stack) for stack in cell_stacks), default=0)
    hung = [[None] * (depth - len(stack)) + stack for stack in cell_stacks]
    levels: List[tuple] = [
        ('cells', [stack[level] for stack in hung])
        for level in range(depth)]
    levels += [('item', ci, expr)
               for ci, stack in enumerate(stacks) for expr in stack
               if _agg_is_row(expr)]
    return levels


def _render_agg_rows(columns, model, lst, get_visualizer, eval_in_scope=None,
                     source_expr=None, max_width=None) -> str:
    """The rows of answers under the table, or nothing when no column has asked
    for one.

    Real rows of the table, because that is what keeps a cell the same width as
    the column it belongs to. A row of cells is not a row of the list, though:
    no index, and nothing in it to pick. A row aggregation's row reads like one
    -- it is one -- but there is still nothing in it to pick.

    They go in a <tfoot>, which pins to the bottom of the scrollport the way
    the header pins to the top. The whole foot pins as one block, so no row has
    to be told where to stop above the next -- and so no cell has to be the
    height every other cell is. A column with fewer answers than the deepest
    one blanks the rows above its first, since the stacks hang from the floor.
    """
    levels = _agg_layout(columns, model)
    if not levels:
        return ''

    leaves = _leaf_columns(columns)
    # Once per column, however many answers are asked of it -- and not at all
    # for a column that only picks rows, since a key reads them one at a time.
    asked = [any(level[0] == 'cells' and level[1][ci] is not None
                 for level in levels)
             for ci in range(len(leaves))]
    reads = [_column_values(leaf.expr, lst, model, eval_in_scope) if asked[ci]
             else None
             for ci, leaf in enumerate(leaves)]
    add_box = None if is_read_only() else _add_box_leaf(model, columns)

    rows = []
    for level, spec in enumerate(levels):
        if spec[0] == 'item':
            _, ci, expr = spec
            rows.append(_render_agg_item_row(expr, ci, level, columns, lst,
                                             model, get_visualizer,
                                             eval_in_scope, source_expr,
                                             max_width))
            continue
        cells = []
        for ci, expr in enumerate(spec[1]):
            # The column being written is asked nothing, but it is drawn: these
            # rows have to leave it the space its header takes, like every
            # other row of the table.
            if add_box is not None and add_box[0] == ci:
                cells.append('<td class="col-add-blank"></td>')
            if expr is None:
                cells.append('<td class="col-agg-blank"></td>')
            else:
                cells.append(_render_agg_cell(expr, leaves[ci].expr, level,
                                              reads[ci], model, get_visualizer,
                                              eval_in_scope, source_expr,
                                              max_width))
        rows.append(f'<tr class="col-agg-row">'
                    f'<td class="row-index col-agg-blank"></td>{"".join(cells)}</tr>')
    return f'<tfoot class="col-agg-rows">{"".join(rows)}</tfoot>'


def get_col_width_style(col, model):
    column_widths = model.get('column_widths')
    width = column_widths.get(col)

    if width is None:
        return ''

    return f' style="min-width: {width}px; max-width: {width}px; overflow: hidden;"'

def _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, every_row_exps=None):
    children = model.get('children', {})
    columns = model.get('columns', [])
    focused_child = model.get('focused_child')

    max_column_width = round(800 / math.sqrt(max(len(columns), 1)))

    search = model.get('search')
    has_search = search is not None and search != ''
    # Read-only visualizers (clickacode.readOnlyVisualizers): the rows are drawn and
    # nothing that writes code or config is -- no toolbar, no column menus or
    # (+), no row handles or menus, no search or action bar, no pick regions.
    # The drag handles go quiet on their own (see py_exp_attrs). A search left
    # in the model from before still narrows the rows: that is a view.
    read_only = is_read_only()
    # There is nothing to pick out of a small (unfocused) preview. With a search
    # pick is first-match-only; without one the whole table is one band.
    pick_mode = (model.get('tool') == 'pick') and not small and not read_only
    first = bool(model.get('first_match', False)) or pick_mode

    matched_indices = set()
    if has_search and not small:
        try:
            matched = _get_matching_indices(search, lst, eval_in_scope)
            if first and matched:
                matched = matched[:1]
            matched_indices = set(matched)
        except Exception:
            pass

    collapsed_max_height = (max_height or 144) - 32
    # The aggregation rows are part of what the table has to show, so a short
    # one doesn't get a scrollbar for the sake of the answers under it. 18px is
    # the height of a row of plain cells; one holding a nested visualizer is
    # taller, so this is a floor on how tall the table wants to be.
    agg_rows = len(_agg_layout(columns, model))
    wanted_height = 18 * (len(lst) + 1 + agg_rows)
    # Offered on every table, not just the ones wanted_height says are clipped:
    # that figure is 18px a row, which is a row of plain cells, and a row
    # holding a nested visualizer is taller. So a table counted as fitting can
    # still have rows out of sight, and withholding the bar would leave nothing
    # to bring them into view with. Only the browser knows the real heights;
    # rather than guess at them here, the bar is always there. It costs a short
    # table nothing to carry one -- opening it lifts a ceiling the table isn't
    # reaching anyway, so nothing moves until something is actually clipped.
    can_expand = True
    expanded = bool(model.get('expanded', False) or focused_child)
    actual_max_height = (max(EXPANDED_PANE_MAX_HEIGHT, collapsed_max_height)
                         if expanded else collapsed_max_height)
    actual_min_height = min(wanted_height, actual_max_height)
    if not small: # room for toolbar
        actual_min_height = max(actual_min_height, 41)

    actual_max_width = f' max-width:{max_width}px;' if max_width is not None else ''

    table_div_style = f'min-height: {actual_min_height}px; max-height: {actual_max_height}px;{actual_max_width}'

    # The keys commit and cancel the column box, which read-only never opens.
    key_handler = ('' if read_only else
                   f'snc-key-down="{html.escape(repr(ColumnKeyDown()))}" snc-mouse-down="{html.escape(repr(DeselectChildren()))}"')
    small_class = ' small' if small else ''
    expandable_class = ' is-expandable' if can_expand else ''
    has_focused_child_class = ' has-focused-child' if focused_child else ''
    # Driven by pick_mode, not the raw model value: the pick styling strips the
    # cell borders, so it must only apply when regions are actually drawn.
    tool_class = f' {"pick" if pick_mode else "normal"}-tool-selected' if not small else ''
    strs = [
        f'<div tabindex="0" {key_handler} '
        f'class="visualizer-container list-visualizer{small_class}{tool_class}{expandable_class}{has_focused_child_class}">'
    ]

    strs.append(f'<div class="snc-tool-and-visualizer">')

    # The tool toolbar only makes sense on the focused visualizer; in small mode
    # there is no room for it and it would compete with the real focus.
    if not small and not read_only:
        strs.append(_render_tool_toolbar(model))

    is_dragging_class = 'list-table-is-dragging' if model.get('column_drag_from') is not None or model.get('column_drag_over') is not None else ''

    strs.append(f'<div class="list-table-scroll snc-base-visualizer {is_dragging_class}" style="{table_div_style}">')
    leaves = _leaf_columns(columns)
    header_rows = _header_cells(columns)
    # A splat carrying sub-columns spans them, and they get a header row of
    # their own underneath -- one more for every level of nesting. With no
    # sub-columns anywhere this is one <tr> of width-1 cells, exactly the
    # markup it has always been.
    n_header = len(header_rows)


    # One <thead> around every header row, the way the aggregations share one
    # <tfoot>: a row group sticks as a block, so a sub-column row pins under
    # the row above it without anything having to measure that row's height.
    strs.append('<table><thead class="col-header-rows"><tr>')
    strs.append(_render_row_index_header(model, n_header))

    # Where Add Column Before / After put the box: beside the column it was
    # asked for, in that column's own header row, so the new column is written
    # where it is going to be drawn.
    beside = None if read_only else _add_beside_target(model)
    for level, cells in enumerate(header_rows):
        if level:
            strs.append('<tr>')
        for cell in cells:
            span_attrs = ''
            # A cell the box is drawn under has to span it too, or it stops
            # short and its sub-columns shift out from under it.
            over_box = (beside is not None
                        and beside[0].startswith(cell.expr + SUBCOL_SEP))
            colspan = cell.colspan + (1 if over_box else 0)
            if colspan > 1:
                span_attrs = f' colspan="{colspan}"'
            if cell.rowspan > 1:
                span_attrs += f' rowspan="{cell.rowspan}"'
            # The box is a column of the table like any other: it reaches down
            # past the sub-column rows the way its new neighbours do.
            box = ('' if beside is None or beside[0] != cell.expr else
                   _render_column_input(
                       lst, model, get_visualizer, is_editing=False,
                       span_attrs=(f' rowspan="{n_header - level}"'
                                   if n_header - level > 1 else '')))
            if box and not beside[1]:
                strs.append(box)
            if model.get('editing_column') == cell.expr and not read_only:
                strs.append(_render_column_input(
                    lst, model, get_visualizer, is_editing=True,
                    span_attrs=span_attrs))
            else:
                # A sub-column is a column: it gets the same header, so the
                # same menu -- search, tally, sort and Compute all key on the
                # column expression, and a leaf's is one _column_values
                # understands.
                strs.append(_render_column_header(
                    cell.expr, model, lst, eval_in_scope,
                    span_attrs=span_attrs,
                    extra_classes='col-subheader' if level else None,
                    label=cell.label if level else None,
                    get_visualizer=get_visualizer,
                    read_only=read_only))
            if box and beside[1]:
                strs.append(box)

        if level == 0:
            # Both sit at the right end of the top row, where there is nothing
            # below them to head -- so they reach to the bottom of the header
            # like the columns beside them, rather than leaving a hole under
            # themselves for every sub-column row.
            full_span = f' rowspan="{n_header}"' if n_header > 1 else ''
            # Unless it is already drawn beside the column it was asked for --
            # an anchor the table no longer has falls back to here, so the box
            # is drawn exactly once wherever it ends up.
            if model.get('adding_column') and beside is None and not read_only:
                strs.append(_render_column_input(lst, model, get_visualizer,
                                                 is_editing=False,
                                                 span_attrs=full_span))
        strs.append('</tr>')
    strs.append('</thead>')

    # Which drawn column the open box takes the place of, and how deep it hangs
    # -- the cells below have to leave it a column's worth of room, or every
    # column to its right slides off the values it names.
    add_box = None if read_only else _add_box_leaf(model, columns)

    if len(lst) == 0:

        strs.append(f'<tr><td class="empty-list" '
                    f'colspan="{len(leaves) + 1 + (add_box is not None)}">'
                    f'Empty {lst.__class__.__name__}.</td></tr>')

    source_expr = model.get('_source_expr')
    # Whether a cell may be read by evaluating `<source>[i]` again, or has to be
    # read off the row in hand -- see _is_pure_ref. The code the cells hand over
    # still names the source either way.
    read_through = eval_in_scope is not None and _is_pure_ref(source_expr)

    scroll_to = model.get('_scroll_to_match', False)

    first_match_row = min(matched_indices) if matched_indices else None
    # Pick mode replaces the row-match / row-dim striping with a grid of
    # pickable regions: three row bands (before the match, the match, after)
    # crossed with the row-index column and every configured column -- or, with
    # no search, one full-height band per column. A search that matches nothing
    # is neither: there is no match to band the rows around.
    pick_here = pick_mode and (first_match_row is not None or not has_search)
    pick_exprs = {}
    if pick_here and source_expr is not None:
        pick_exprs = _pick_standalone_exprs(
            model, source_expr, eval_in_scope,
            _pick_region_ids(columns, first_match_row, len(lst)))

    # Asked rather than assumed: a column the pick tool offers no expression
    # for draws no overlay, instead of one that would be discarded as invalid
    # the moment it was clicked.
    pick_ids = set(_pick_column_ids(columns))

    def pick_overlay(row, col_id):
        if not pick_here or col_id not in pick_ids:
            return ''
        return _render_pick_region(row, col_id, model, first_match_row,
                                   len(lst), pick_exprs)

    rendered = _rows(lst, columns)

    # The window over the root rows: the page in hand, then the tail. A search
    # that found a row below the page opens the window down to it -- that row is
    # what the search was for, and what `_scroll_to_match` is aimed at, so it has
    # to be there to scroll to. Opened contiguously rather than by punching a
    # hole for the match alone: the rows in between are the ones the user is
    # scrolling past to reach it, and one gap in a table reads as one gap.
    # Cleared again the moment the search is, since nothing here is remembered.
    shown = _shown_rows(model)
    if first_match_row is not None:
        shown = max(shown, first_match_row + 1)
    hidden = _hidden_rows(len(lst), shown)
    # The same reach the empty-list row takes: every drawn column and the row
    # numbers beside them.
    load_more_colspan = len(leaves) + 1 + (add_box is not None)

    # Set on every root row below, and read only by the leaves whose cells are
    # drawn on one -- but declared here so they can never be read before a root
    # row has said what they are.
    row_exprs = None
    cell_exprs = None
    for rn, row in enumerate(rendered):
        i = row.index
        if hidden is not None and hidden[0] <= i < hidden[1]:
            # Drawn once, on the first rendered row of the first root row left
            # out, so it lands exactly where the gap opens.
            if i == hidden[0] and row.span_start:
                strs.append(_render_load_more_row(
                    hidden[1] - hidden[0], load_more_colspan, small))
            continue
        # The last row of a list is handed `[-1]` rather than its number, all
        # the way down: the cells of that row, the code a child of one of them
        # makes, and the two readings the row's own handle leads with. It is
        # the one naming here that goes on meaning the same row once the list
        # grows, which is what a cell dragged into the file is for.
        from_end = (not small and not pick_here
                    and _names_from_end(model, lst, i))
        # A column draws once per group at the depth it was splatted to, and
        # spans that group. This is where the mockup's key cell comes from: `$k`
        # rowspans because it did not splat, not because it is a key -- and a
        # column splatted once but not twice spans its inner group the same way.
        # A per-group answer is one of these: a column at the depth its group is
        # a row of, spanning that group for the same reason `$k` does.
        def leaf_span(depth):
            width = row.span_at(depth)
            return f' rowspan="{width}"' if width > 1 else ''

        span_attr = leaf_span(0)
        is_match = i in matched_indices
        row_class_attr = ''
        scroll_attr = ''
        if has_search and matched_indices and not pick_here:
            if is_match:
                row_class_attr = ' class="row-match"'
                if scroll_to and i == first_match_row:
                    scroll_attr = ' snc-scroll-to-match'
            else:
                row_class_attr = ' class="row-dim"'
        elif pick_here:
            # The band classes let CSS dim the before/after rows; the regions
            # themselves carry the outlines and fills.
            band = _pick_band_for_row(i, first_match_row)
            row_class_attr = f' class="pick-row-{band}"'
            if scroll_to and i == first_match_row:
                scroll_attr = ' snc-scroll-to-match'

        strs.append(f'<tr{row_class_attr}{scroll_attr}>')
        # The row index is a root-row value like any other, so it rowspans for
        # the same reason the unsplatted columns do.
        if row.span_start:
            # Every drawn column of this root row, worked out once. It is what
            # the row's own handle hands over as a tuple, and -- for a leaf
            # nothing splatted, whose cell is drawn on this very row -- the
            # expression that cell is dragged out by, so the two are one
            # substitution rather than two per column per row.
            row_exprs = (None if small or pick_here
                         else _row_column_exprs(model, lst, i))
            # And the same again from the end, where the row has an end to be
            # named from: those are the cells' own, and the handle's
            # end-relative readings are built from them in turn.
            cell_exprs = (_row_column_exprs(model, lst, i, from_end=True)
                          if from_end else row_exprs)
            # The row's own handle and menu, once per ROOT row -- one row is
            # one row however many rendered rows a splat takes it across.
            # Neither in a small table, where there is no room and no line to
            # write, nor under the pick tool, whose region overlay sits on top
            # of this cell and takes every click that lands on it.
            strs.append(_render_row_index_cell(
                model, lst, i, span_attrs=span_attr,
                overlay=pick_overlay(i, PICK_IDX_COLUMN), parts=row_exprs,
                widgets=not small and not pick_here and not read_only))

        for ci, leaf in enumerate(leaves):
            col = leaf.expr
            # The column being written has no values yet, so it leaves the
            # space it will take -- and spans its group the way a column at
            # that depth does, since that is the shape of the space.
            if add_box is not None and add_box[0] == ci and row.starts_at(add_box[1]):
                strs.append(f'<td class="col-add-blank"'
                            f'{leaf_span(add_box[1])}></td>')
            # A column belongs to the group at the depth it was splatted to, so
            # it is drawn once per group at THAT depth rather than once per
            # rendered row. The innermost depth is a group of one, which is how
            # a leaf under the last splat comes to draw on every row.
            if not row.starts_at(leaf.depth):
                continue
            composite_key = f"{row.key}{CELL_KEY_SEP}{col}"
            try:
                cell_value = _leaf_cell_value(leaf, row, lst, source_expr,
                                              eval_in_scope, read_through)
            except Exception:
                cell_value = None

            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                cell_model = children.get(composite_key)
                if cell_model is None:
                    extra = child_nesting_kwargs(model, col,
                                                 cell_vis.init_model)
                    cell_model = cell_vis.init_model(cell_value, get_visualizer,
                                                     eval_in_scope=eval_in_scope, **extra)
                child_small = small or (composite_key != focused_child)

                # A leaf nothing splatted reads the same expression per cell as
                # per root row, and its cell is only ever drawn on the row that
                # worked that list out -- so it is read back rather than
                # substituted a second time. A splat's cell names the ELEMENT
                # it is showing, which is a different question, and asks it.
                cell_expr = (
                    None if source_expr is None
                    else (cell_exprs[ci]
                          if cell_exprs is not None and leaf.splat is None
                          else _leaf_cell_expr(leaf, source_expr, row, lst,
                                               from_end)))

                # The parent doesn't wrap children for drag: each is handed its
                # access-path expression and decides for itself, so a child with
                # its own handles keeps them instead of being covered by one.
                child_var_and_exp = (None, cell_expr) if cell_expr else None

                # And the other readings of whatever it draws inside: the same
                # reach down every row (see _cell_inner_exps). None under a
                # splat -- the cell shows one ELEMENT there, so there is no
                # once-per-row expression for anything in it, which is the same
                # question _column_row_expr answers with None.
                col_row_expr = (None if source_expr is None
                                else _column_row_expr(columns, col))
                # When this table is itself a cell, the reach goes on up: the
                # `name` of a CSV row inside a cell is `x[0][1]` here, one
                # column of the inner table, AND `[item[1] for item in x]`
                # read down the outer one. The cell's path within THIS list --
                # built against `$` rather than the source -- is what the table
                # above composes onto, exactly as a tuple hands up its slot.
                rel_cell_expr = (None if leaf.splat is not None else
                                 _leaf_cell_expr(leaf, '$', row, lst, from_end))
                outer_reads = (list(every_row_exps(rel_cell_expr))
                               if every_row_exps is not None and rel_cell_expr
                               else [])
                cell_every_row = _cell_every_row(
                    columns, col_row_expr, source_expr, _model_binds(model),
                    every_row_exps, leaf.splat is None)
                draw_cell = getattr(cell_vis, 'visualize_els', None) or cell_vis.visualize
                inner = ({'every_row_exps': cell_every_row}
                         if cell_every_row is not None
                         and wants_kwarg(draw_cell, 'every_row_exps')
                         else {})

                if hasattr(cell_vis, 'visualize_els'):
                    cell_htmls = cell_vis.visualize_els(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small, var_and_exp=child_var_and_exp, **inner)
                else:
                    cell_htmls = [cell_vis.visualize(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small, var_and_exp=child_var_and_exp, **inner)]
                if outer_reads and cell_expr:
                    cell_htmls = [add_drag_readings(h, cell_expr, outer_reads)
                                  for h in cell_htmls]

                # A column drawn once for a group has to span it -- otherwise
                # the cell occupies the first row only and every row under it
                # shifts left.
                cell_span = leaf_span(leaf.depth)
                strs.append(f'<td data-col="{repr(html.escape(col))}" {get_col_width_style(col, model)} {cell_span}>')
                strs.append(wrap_child_prefix(composite_key))
                strs.extend(cell_htmls)
                strs.append(wrap_child_suffix)
                strs.append(pick_overlay(i, f'col_{ci}'))
                strs.append('</td>')
            else:
                cell_span = leaf_span(leaf.depth)
                strs.append(f'<td data-col="{repr(html.escape(col))}" {get_col_width_style(col, model)} {cell_span}>{pick_overlay(i, f"col_{ci}")}</td>')

        strs.append('</tr>')

    strs.append(_render_agg_rows(columns, model, lst, get_visualizer,
                                 eval_in_scope, source_expr, max_column_width))

    strs.append('</table>')

    strs.append('</div>')

    # Under the pane and above the search area, where the string visualizer
    # puts its own. Nothing marks the container: the pane's ceiling is written
    # inline above, and a class here would reach the cells' panes too.
    if can_expand:
        strs.append(f'<div class="expand-and-len">')
        strs.append(render_expand_toggle(expanded, repr(ExpandToggle()), small=small))
        strs.append(f'</div>')


    if not small and not read_only:
        strs.append(_render_add_column_header(
            lst, model, get_visualizer))

    strs.append('</div>')

    if not small and not read_only:
        strs.append(_render_search_box(model, lst, eval_in_scope, small=False, focused_child=focused_child))

    strs.append('</div>')
    return ''.join(strs)



def _adopt_source(model: dict, var_and_exp=None, source_span=None) -> None:
    """Take in what this run says about the line the value came from.

    Both are refreshed rather than remembered, because the line can be rewritten
    under a model that outlives the rewrite -- which is exactly what the Sort
    submenu does. A model still holding the expression from before would go on
    evaluating its cells against it and show the old order against the new
    value.

    *source_span* is the expression the line is showing, and where it sits, for
    the sort rows to rewrite; it is absent at a site with nothing to rewrite (a
    loop variable is bound by its statement, not written on it) and for a nested
    table, which has no line of its own at all.

    Only visualize passes *var_and_exp*, and only it can: a child's update is
    dispatched with the PARENT's (see update_child), so reading it there would
    give every nested table its parent's expression to evaluate cells against.
    Rendering hands each child its own, and visualize runs after the events in
    every run, so it is both the safe place and a sufficient one.
    """
    if var_and_exp:
        var_name, expr = var_and_exp
        model['_source_expr'] = var_name if var_name else expr
    if source_span is not None or '_source_span' not in model:
        model['_source_span'] = source_span


def _visualize_collapsed(value, var_and_exp) -> str:
    """A nested table nobody is looking at: the value's repr, cut to the length
    of a label.

    A table inside a cell spends a cell's worth of room on what a dozen
    characters say as well, and spends it again on every row -- so it is drawn
    only once someone has asked for it, by clicking (see PinFocus).

    The click and the drag are what the table it replaced was carrying, so the
    repr carries them instead: a mousedown for the front-end to route, and the
    whole-value handle a small string preview takes for the same reason -- with
    no cells left inside to offer their own more specific expressions, an outer
    handle has nothing to claim the hover from, and without one this would be
    the one value on screen that can't be dragged out.
    """
    return wrap_drag_grab(
        f'<span class="small" snc-mouse-down="{html.escape(repr(PinFocus()))}">'
        f'{html.escape(truncate_repr(value))}</span>',
        var_and_exp)


def visualize(lst: list, model: dict, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, var_and_exp=None, source_span=None, every_row_exps=None):
    _adopt_source(model, var_and_exp, source_span)
    model['_is_dict'] = isinstance(lst, dict)
    model['columns'] = _as_columns(model.get('columns'))
    # Depth-capped leaf: render a plain truncated repr instead of a nested table.
    if model.get('_too_deep'):
        return f'<span class="small">{html.escape(truncate_str(repr(lst), 200))}</span>'

    # Nested and unfocused -- a cell of some other table, or a field of an
    # object. Decided here rather than by the parent drawing the repr itself:
    # the parent would have to know which of its cells hold containers, and
    # would have to except the focused one anyway. A non-empty config path is
    # what nesting is (see init_model), and `small` alone is not: a table on an
    # unfocused LINE is still the biggest thing on that line.
    if small and model.get('_config_path'):
        return _visualize_collapsed(lst, var_and_exp)

    # No whole-area drag handle in either size: the cells and column headers
    # carry their own snc-py-exps, and a handle wrapping all of them would claim
    # every hover in between. Only the generic visualizers self-wrap.
    return _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small, every_row_exps=every_row_exps)


def _table_child_value_getter(key, lst, model, eval_in_scope=None):
    # An answer under the table is computed rather than looked up, so its key
    # carries the question instead of a row to index.
    if _parse_agg_child_key(key) is not None:
        return _agg_child_value(key, lst, model, eval_in_scope)
    source_expr = _cell_source_expr(model, eval_in_scope)
    row_key, field_key = key.split(CELL_KEY_SEP, 1)
    columns = model.get('columns') or []
    row = _row_by_key(lst, columns, row_key)
    # Through the leaf, because the key is a leaf's identity: a splat's is the
    # whole splatted list rather than the element the cell is showing, and a
    # sub-column's is a composition that means nothing as an expression.
    leaf = _leaf_for(columns, field_key)
    if leaf is not None:
        return _leaf_cell_value(
            leaf, row, lst, source_expr, eval_in_scope,
            read_through=source_expr is not None and eval_in_scope is not None)
    if source_expr is not None and eval_in_scope is not None:
        return eval_in_scope(
            _column_cell_expr(field_key, source_expr, row.index, lst))
    return eval_dollar_expr(field_key, row.item, eval_in_scope, outer=(lst,),
                            bindings=row.bindings)


def update(event, var_and_exp, model: Any, value, get_visualizer=None, eval_in_scope=None, source_span=None) -> Tuple[Any, List[Any]]:
    if event is None or not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])

    if model is None:
        model = {'children': {}, 'handledKeys': [], 'display_mode': 'table',
                 'columns': {'$': {}},
                 '_slot_children': {}, '_config_path': [],
                 '_config_persist': True,
                 **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS}

    # The span only, and only when this run brought one: see _adopt_source.
    if source_span is not None:
        _adopt_source(model, source_span=source_span)

    if value is not None:
        model['_is_dict'] = isinstance(value, dict)
    model['columns'] = _as_columns(model.get('columns'))

    try:
        make_python_event = eval(event['pythonEventStr'])
    except Exception:
        return (model, [])

    event_json = event.get('eventJSON', {})
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event

    if msg is None:
        return (model, [])

    if isinstance(msg, ChildEvent):
        is_agg = _parse_agg_child_key(msg.child_key) is not None
        row_key, cell_col = msg.child_key.split(CELL_KEY_SEP, 1)
        new_model, commands = route_child_event(
            event, model, value,
            child_value_getter=lambda key: _table_child_value_getter(key, value, model, eval_in_scope),
            get_visualizer=get_visualizer,
            # The cell's value is bound to a name for the child, so the code it
            # generates is dollar-free; the column expression goes back in below.
            var_and_exp=(None, CHILD_SOURCE_BINDER),
            eval_in_scope=eval_in_scope,
        )
        src = model.get('_source_expr')
        if is_agg:
            # An answer is one value the aggregation worked out, not a value
            # each row has, so at the ROOT there is no row-generic form of it:
            # the same expression names it wherever it is headed.
            #
            # Nested, that stops being true. This table is a cell, drawn once
            # per row of the table above, and the answer is THAT row's -- so
            # code made in it becomes a column up there and has to stay generic.
            # The answer is asked of the source, so writing it against the
            # binder instead of the concrete cell is the whole of it, and the
            # parent resolves that two ways with the two expressions it has.
            # Resolved here, the parent's column read `''.join(x[0])` on every
            # row: one row's answer, repeated down the table.
            def agg_expr_from(source):
                return _agg_child_expr(msg.child_key, source, _model_binds(model),
                                       model.get('columns') or {},
                                       value) or cell_col
            agg_expr = agg_expr_from(src)
            agg_code = (agg_expr_from(CHILD_SOURCE_BINDER)
                        if is_nested(var_and_exp) else agg_expr)
            commands = [nest_child_command(cmd, agg_code, agg_expr)
                        for cmd in commands]
        else:
            # A column stays generic (a dollar expression); anything bound for
            # the clipboard names this row concretely, since the user pastes it
            # into the editor as-is.
            # Under splat the row is looked up by its key, since "3.1" and
            # "3.0" share a column but not a value -- and int("3.1") raises.
            columns = model.get('columns') or {}
            _row = (_row_by_key(value, columns, row_key)
                    if value is not None else None)
            leaf = _leaf_for(columns, cell_col)
            # The scope the child's code is written in. A cell under a splat
            # shows one ELEMENT, so what is generic about it is generic over
            # the elements -- `$['kind']`, not the composed identity the cell
            # is keyed by, which is no expression at all.
            generic_cell = (_column_row_expr(columns, cell_col)
                            or (leaf.sub if leaf else None) or cell_col)
            if src is None:
                concrete_cell = generic_cell
            else:
                # The last row's cells were handed `[-1]` on the way down (see
                # _names_from_end), so code made in one comes back bound to the
                # same expression -- otherwise the value on screen and the text
                # on the clipboard would name different rows.
                idx = _row.index if _row else 0
                from_end = _names_from_end(model, value, idx)
                if leaf is not None and _row is not None:
                    concrete_cell = _leaf_cell_expr(leaf, src, _row, value,
                                                    from_end)
                else:
                    concrete_cell = _column_cell_expr(cell_col, src, idx,
                                                      value, from_end)
            # A table that is itself a CELL does not take the column: each
            # row of the table above draws its own inner table, and a column
            # written into one of them is a fact about that row alone -- there
            # is nothing keeping the others in step with it. So the code is
            # mapped over this table's rows and travels on up, still carrying
            # the binder, and the OUTERMOST table is the one that takes it.
            # Its clipboard text is unaffected: that names this row and always
            # did, so it is resolved here as before.
            if is_nested(var_and_exp):
                commands = [
                    (cmd[0], _map_over_rows_code(cmd[1]), *cmd[2:])
                    if is_new_code(cmd) and not is_agg
                    else nest_child_command(cmd, generic_cell, concrete_cell)
                    for cmd in commands]
            else:
                commands = [nest_child_command(cmd, generic_cell, concrete_cell)
                            for cmd in commands]

        filtered_commands: List[Any] = []
        has_rows = bool(value)
        for cmd in commands:
            # Code out of a cell becomes a column of this table, since a cell's
            # expression is one every row answers. An answer's isn't, so its
            # code travels on up to whoever asked for it.
            #
            # A column is the expression and nothing else -- it outlives the
            # command, gets saved with the line and comes back -- so what the
            # child declared it needed imported is not kept here. It is read
            # back off the column instead, wherever the column is handed to the
            # editor (see code_imports and imports_for_code).
            #
            # The declaration is still asked for now, though: the column is
            # evaluated in the user's scope on every run, so until the file has
            # the import there is nothing for the column to show.
            if is_new_code(cmd) and not is_agg and is_nested(var_and_exp):
                # Mapped above and headed for the outermost table.
                filtered_commands.append(cmd)
            elif is_new_code(cmd) and not is_agg:
                _add_derived_column(new_model, cell_col, cmd[1])
                if len(cmd) > 2 and cmd[2]:
                    filtered_commands.append(AddImports(imports=tuple(cmd[2])))
                if has_rows:
                    _save_slots(new_model)
            else:
                filtered_commands.append(cmd)
        new_model['handledKeys'] = aggregate_handled_keys(new_model.get('children', {}), _OWN_KEYS)
        return (new_model, filtered_commands)

    commands: List[Any] = []
    has_rows = bool(value)
    model['_scroll_to_match'] = False
    # A one-shot request, cleared here so it can't pull focus into a column
    # search box on some later, unrelated render.
    model['_col_search_focus'] = False

    match msg:
        case AddColumnClick():
            _close_column_menus(model)
            model['adding_column'] = True
            model['column_input_value'] = ''
            model['editing_column'] = None

        # The rest of the (+) menu. These leave it open, like the sub-column
        # rows they are modelled on: ticking several in a row is what a list of
        # boxes is for. Nothing re-points it either -- the id names the table
        # rather than a column, so no column moving under it can take it
        # elsewhere.
        case ColumnToggle(expr=expr):
            expr = expr.strip()
            if expr:
                if expr in model['columns']:
                    _drop_column(model, expr, eval_in_scope)
                else:
                    _col_add(model['columns'], expr)
                _save_columns(model)

        # The fields only. The row columns are their own section for exactly
        # this reason: they are true of every table rather than detected off
        # this one, so asking to see the fields is not asking for them.
        case ColumnShowAll():
            for expr in _table_field_candidates(value, get_visualizer):
                _col_add(model['columns'], expr)
            _save_columns(model)

        # The fields only, like Show all: the pair acts on the section it is
        # drawn against, and the row columns above it are neither's to touch.
        # So a column the user wrote goes -- it is one of the fields as far as
        # the menu is concerned -- and `$` stays.
        case ColumnHideAll():
            spared = set(_table_row_candidates(value))
            for expr in list(model['columns']):
                if expr not in spared:
                    _drop_column(model, expr, eval_in_scope)
            _save_columns(model)

        case AddColumnAtClick(col=named, after=after):
            _close_column_menus(model)
            target = _named_column(model, named)
            model['adding_column'] = (True if target is None
                                      else _add_anchor_value(target, after))
            model['column_input_value'] = ''
            model['editing_column'] = None

        case ColumnInput(value=val):
            model['column_input_value'] = val
            if val and get_visualizer is not None:
                suggestions = _get_column_suggestions(value, get_visualizer, model.get('columns', []), val)
                model['selected_suggestion_index'] = 0 if suggestions else None
            else:
                model['selected_suggestion_index'] = None

        case ColumnSelect(name=name):
            if model.get('adding_column'):
                _add_beside(model, name)
                model['adding_column'] = False
                model['column_input_value'] = ''
                if has_rows:
                    _save_slots(model)
            elif model.get('editing_column') is not None:
                old_name = _named_column(model, model['editing_column'])
                if old_name is not None:
                    _rename_column(model, old_name, name, eval_in_scope)
                model['editing_column'] = None
                model['column_input_value'] = ''
                if has_rows:
                    _save_slots(model)

        case ColumnClick(col=named):
            _close_column_menus(model)
            detail = event_json.get('detail', 1)
            if detail >= 2:
                target = _named_column(model, named)
                if target is not None:
                    model['editing_column'] = target
                    # A sub-column is edited as the expression it is, not as
                    # the composed identity it is keyed by.
                    model['column_input_value'] = (
                        target.split(SUBCOL_SEP, 1)[1]
                        if SUBCOL_SEP in target else target)
                    model['adding_column'] = False

        case RemoveColumnClick(col=named):
            _close_column_menus(model)
            removed_col = _named_column(model, named)
            if removed_col is not None and _drop_column(model, removed_col,
                                                        eval_in_scope):
                # The box was open on the column that just went; the others
                # keep their names, so nothing else has to be adjusted.
                if model.get('editing_column') == removed_col:
                    model['editing_column'] = None
                    model['column_input_value'] = ''
                if has_rows:
                    _save_slots(model)

        case ColumnDragStart(col=named):
            _close_column_menus(model)
            target = _named_column(model, named)
            if target is not None:
                model['column_drag_from'] = target
                model['column_drag_over'] = target

        case ColumnDragOver(col=named):
            if model.get('column_drag_from') is not None:
                if event_json.get('buttons', 0) == 0:
                    model['column_drag_from'] = None
                    model['column_drag_over'] = None
                else:
                    model['column_drag_over'] = named

        case ColumnDragEnd(col=named):
            drag_from = model.get('column_drag_from')
            from_target = _named_column(model, drag_from)
            to_target = _named_column(model, named)
            if (from_target is not None and to_target is not None
                    and from_target != to_target):
                # Within one parent this reorders; across a splat boundary it
                # promotes or adopts, rewriting the expression as it moves.
                # A refusal (a sigil column being adopted) leaves everything
                # exactly as it was.
                if _move_target(model['columns'], from_target, to_target):
                    # Column order is term order in the composed search.
                    _recompose_search(model, eval_in_scope)
                    if has_rows:
                        _save_slots(model)
            model['column_drag_from'] = None
            model['column_drag_over'] = None

        case ColumnKeyDown():
            key = event_json.get('key', '')
            is_input_active = model.get('adding_column') or model.get('editing_column') is not None

            if key == 'ArrowDown' and is_input_active:
                suggestions = _get_column_suggestions(value, get_visualizer, model.get('columns', []), model.get('column_input_value', '')) if get_visualizer else []
                if suggestions:
                    cur = model.get('selected_suggestion_index')
                    if cur is None:
                        model['selected_suggestion_index'] = 0
                    else:
                        model['selected_suggestion_index'] = (cur + 1) % min(len(suggestions), 10)

            elif key == 'ArrowUp' and is_input_active:
                suggestions = _get_column_suggestions(value, get_visualizer, model.get('columns', []), model.get('column_input_value', '')) if get_visualizer else []
                if suggestions:
                    cur = model.get('selected_suggestion_index')
                    count = min(len(suggestions), 10)
                    if cur is None:
                        model['selected_suggestion_index'] = count - 1
                    else:
                        model['selected_suggestion_index'] = (cur - 1) % count

            elif key in ('Enter', 'Tab'):
                sel_idx = model.get('selected_suggestion_index')
                if sel_idx is not None and is_input_active:
                    suggestions = _get_column_suggestions(value, get_visualizer, model.get('columns', []), model.get('column_input_value', '')) if get_visualizer else []
                    capped = suggestions[:10]
                    if 0 <= sel_idx < len(capped):
                        commit_val = capped[sel_idx]
                    else:
                        commit_val = model.get('column_input_value', '').strip()
                else:
                    commit_val = model.get('column_input_value', '').strip()

                if model.get('adding_column'):
                    if commit_val:
                        _add_beside(model, commit_val)
                        if has_rows:
                            _save_slots(model)
                    model['adding_column'] = False
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None
                elif model.get('editing_column') is not None:
                    old_name = _named_column(model, model['editing_column'])
                    if commit_val and old_name is not None and _rename_column(
                            model, old_name, commit_val, eval_in_scope):
                        if has_rows:
                            _save_slots(model)
                    model['editing_column'] = None
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None
                elif key == 'Enter':
                    dd = model.get('openDropdown')
                    if dd and dd.get('id') == 'action-join':
                        custom_sep = dd.get('customSep', "''")
                        action = 'join'
                        ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                        if ctx is None:
                            ctx = _get_whole_list_context(model, var_and_exp)
                        if ctx:
                            ctx['join_separator'] = custom_sep
                            result = generate_action(action, ctx)
                            if result:
                                commands.append(new_code_command(result, code_imports))
                        model['openDropdown'] = None
                    elif model.get('search') or model.get('pick_expr'):
                        if model.get('linked_action'):
                            model['linked_action'] = 'filter'
                        else:
                            ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                            if ctx:
                                result = generate_action('filter', ctx)
                                if result:
                                    commands.append(new_code_command(result, code_imports))

            elif key == 'Backspace' and event_json.get('metaKey', False):
                if model.get('linked_action'):
                    model['linked_action'] = 'delete'
                else:
                    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                    if ctx:
                        result = generate_action('delete', ctx)
                        if result:
                            commands.append(new_code_command(result, code_imports))

            elif key == 'Escape':
                if model.get('col_search_dropdown'):
                    # Innermost first: a chip menu sits inside the column menu.
                    model['col_search_dropdown'] = None
                elif model.get('openDropdown'):
                    model['openDropdown'] = None
                    _reset_tally_view(model)
                elif model.get('tool') == 'pick':
                    model['tool'] = 'normal'
                    model['picked'] = None
                    model['pick_expr'] = None
                else:
                    model['adding_column'] = False
                    model['editing_column'] = None
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None

        case ColumnSearchInput(col=named, value=val):
            col = _named_column(model, named)
            if col is not None:
                _set_column_search(model, col, text=val)
                _recompose_search(model, eval_in_scope)

        case ColumnSearchOpSelect(col=named, op=op):
            col = _named_column(model, named)
            if col is not None and op in COLUMN_SEARCH_OPS:
                text = _column_search_row(model, col)['text'].strip()
                if op in COLUMN_SEARCH_MEMBERSHIP_OPS and not text:
                    # Hand over the brackets and put the cursor between them, so
                    # the user only types the contents. They're free to delete
                    # them and compare against a string or a range instead.
                    _set_column_search(model, col, op=op,
                                       text=COLUMN_SEARCH_COLLECTION_HINT)
                    model['_col_search_focus'] = True
                elif (op not in COLUMN_SEARCH_MEMBERSHIP_OPS
                        and text == COLUMN_SEARCH_COLLECTION_HINT):
                    # Brackets nothing ever went into: take them back rather than
                    # leave `$ == []` behind.
                    _set_column_search(model, col, op=op, text='')
                else:
                    _set_column_search(model, col, op=op)
                model['col_search_dropdown'] = None
                _recompose_search(model, eval_in_scope)

        case ColumnSearchComposeSelect(col=named, compose=compose):
            col = _named_column(model, named)
            if col is not None and compose in COLUMN_SEARCH_COMPOSE:
                _set_column_search(model, col, compose=compose)
                model['col_search_dropdown'] = None
                _recompose_search(model, eval_in_scope)

        # Sort leaves the menu open for the same reason Compute does: it is a
        # checkbox, and flipping the direction is the common next act.
        case SortClick(col=named, direction=direction):
            col = _named_row_column(model, named)
            span = model.get('_source_span')
            # A column naming `$i` has no sort to write, and neither has one
            # that splats -- see _render_sort_panel, which draws no handle for
            # either. Checked here too, since a click can arrive from a panel
            # drawn before the column was edited.
            if col is not None and dollar_expr_names_index(col):
                col = None
            if col is not None and span is not None and direction in SORT_DIRECTIONS:
                text, *coords = span
                # Clicking the direction the line already sorts in takes the
                # sort off, so one row is both the way in and the way out.
                binds = _model_binds(model)
                wanted = (None if _sort_checked(text, col, direction, binds)
                          else direction)
                expr = _sort_expr(text, col, wanted, binds)
                if expr != text:
                    commands.append(ChangeSourceExpr(expr, *coords))

        # One line written, unlike checking a box, which invites the next -- so
        # this closes the menu the way the Compute code rows do.
        case SortCodeClick(col=named, direction=direction):
            col = _named_row_column(model, named)
            source_expr = model.get('_source_expr')
            if col is not None and dollar_expr_names_index(col):
                col = None
            if (col is not None and source_expr is not None
                    and direction in SORT_DIRECTIONS):
                _close_column_menus(model)
                # The whole list, named -- not whatever the line happens to say
                # -- the way every Compute row asks after the whole column.
                _has_var, base = _name_context_for_source(source_expr)
                commands.append(new_code_command(
                    (f'{base}_sorted', _sort_expr(source_expr, col, direction,
                                                  _model_binds(model))),
                    code_imports))

        # One line written, like the Sort code rows, so this closes the menu.
        # The list, named -- the line the table is showing has no say in it,
        # the same way the Compute rows ask after the whole column.
        case GroupByClick(col=named):
            # A splat has no one value per row to cut the rows up by, so it
            # answers None here and the click writes nothing -- the same answer
            # _render_column_group_by draws, reached the same way.
            col = _named_row_column(model, named)
            source_expr = model.get('_source_expr')
            if col is not None and source_expr is not None:
                _close_column_menus(model)
                _has_var, base = _name_context_for_source(source_expr)
                # setdefault and the walrus are the language's own, so the line
                # asks for nothing the column it groups by hasn't already.
                # The dict the line makes has no columns of its own yet, and
                # the ones to want are the ones in hand.
                commands.append(new_code_command(
                    (f'{base}_grouped',
                     _group_by_expr(col, source_expr, _model_binds(model))),
                    code_imports,
                    config=_grouped_slots(col, model.get('columns'))))

        # One line written, like Group By, so the menu closes behind it. The
        # code comes back out of the catalog the menu drew itself from rather
        # than being worked out a second time here, so the row that was clicked
        # and the line that lands cannot describe different rows.
        case RowActionClick(row=i, action=action):
            source_expr = model.get('_source_expr')
            in_range = isinstance(i, int) and 0 <= i < len(value)
            code = (_row_action_code(action, model, value, i)
                    if in_range and action in ROW_ACTIONS else None)
            if code is not None and source_expr is not None:
                _close_column_menus(model)
                commands.append(new_code_command(
                    (_row_action_name(action, model, source_expr, i), code),
                    code_imports))

        # Convert Type leaves the menu open for the same reason Sort does: it is
        # a checkbox, and picking another type is the common next act. The
        # column is called something else now, though, so the menu is pointed at
        # what it has become.
        case ConvertTypeToggle(col=named, to=to):
            col = _named_column(model, named)
            if col is not None and to in CONVERT_TYPES:
                # Clicking the type the column already reads as takes the
                # conversion off, so one row is both the way in and the way out.
                wanted = (None if _converted_type(col.split(SUBCOL_SEP)[-1]) == to
                          else to)
                _seg, converted = _convert_target(col, wanted)
                if _convert_column(model, col, wanted, eval_in_scope):
                    _repoint_column_menus(model, col, converted)
                    if has_rows:
                        _save_slots(model)

        # One column written, unlike checking a box, which invites the next --
        # so this closes the menu the way the Sort code rows do.
        case ConvertTypeColumnClick(col=named, to=to):
            col = _named_column(model, named)
            if col is not None and to in CONVERT_TYPES:
                seg, _converted = _convert_target(col, to)
                if _convert_writable(model['columns'], col, seg):
                    _close_column_menus(model)
                    # Beside the column rather than at the far right, which is
                    # where the answer belongs and, for a sub-column, the only
                    # scope the new expression reads correctly in.
                    siblings = _siblings_of(model['columns'], col)
                    _col_insert(siblings, seg,
                                list(siblings).index(col.split(SUBCOL_SEP)[-1]) + 1)
                    if has_rows:
                        _save_slots(model)

        # Compute leaves the menu open for the same reason the tally does:
        # checking several aggregations in a row is the whole point.
        case ComputeToggle(col=named, expr=expr, per_group=per_group):
            col = _named_column(model, named)
            if col is None:
                pass
            elif not per_group:
                exprs = _column_computes(model, col)
                if expr in exprs:
                    exprs.remove(expr)
                else:
                    exprs.append(expr)
                _set_column_computes(model, col, exprs)
            else:
                # A per-group answer is a column, so ticking the box adds one
                # and unticking takes it away -- and taking a column away is
                # taking a column away, however it was asked for.
                leaf = _leaf_for(model['columns'], col)
                already = ({e for e, read in
                            _group_agg_columns(model['columns'], leaf).items()
                            if read == expr} if leaf is not None else set())
                changed = False
                for gone in already:
                    changed |= _drop_column(model,
                                            _group_agg_target(leaf, gone),
                                            eval_in_scope)
                if not already and leaf is not None:
                    written = _add_group_agg_column(model, leaf, expr)
                    changed = written is not None
                    # The whole-column box declares what it needs on the line it
                    # writes. This one writes no line -- the answer is a column,
                    # run in the user's own scope on every run -- so a file with
                    # no numpy in it has nothing to show for a percentile. Read
                    # off the column rather than off the row that asked, since
                    # the sub-column being summarised may be code another
                    # visualizer wrote.
                    needs = imports_for_code(written) if written else ()
                    if needs:
                        commands.append(AddImports(imports=needs))
                if changed and has_rows:
                    _save_slots(model)

        case ComputeHoleInput(col=named, expr=expr, hole=hole, value=text):
            col = _named_column(model, named)
            if col is not None:
                edited = _agg_set_hole(expr, hole, text)
                exprs = _column_computes(model, col)
                if expr in exprs:
                    # In place, so the cell the user is typing at stays where
                    # it was in the column's stack.
                    exprs[exprs.index(expr)] = edited
                elif not _regroup_agg_column(model, col, expr, edited,
                                             eval_in_scope):
                    # Typing a level into a row that isn't checked is a way of
                    # asking for that percentile -- unless the per-group box
                    # beside it is the one that is checked, in which case the
                    # level belongs to the column that box wrote.
                    exprs.append(edited)
                _set_column_computes(model, col, exprs)
                if has_rows:
                    _save_slots(model)

        case ComputeExprKeyDown():
            key = event_json.get('key', '')
            if key == 'Enter':
                # Written: the cell is already there, and the menu has nothing
                # more to say about it.
                _close_column_menus(model)
            elif key == 'Escape':
                # Innermost first, the way Escape reads everywhere else in the
                # menu -- and this box is only drawn while the submenu is open.
                model['col_search_dropdown'] = None

        case ComputeExprInput(col=named, expr=expr, value=text):
            col = _named_column(model, named)
            if col is not None:
                exprs = _column_computes(model, col)
                if expr in exprs:
                    # In place, so the cell the user is typing at stays where it
                    # was in the column's stack. Emptying the box drops it,
                    # since _set_column_computes keeps no blank aggregations.
                    exprs[exprs.index(expr)] = text
                else:
                    exprs.append(text)
                _set_column_computes(model, col, exprs)

        # One line written, unlike checking a box, which invites the next -- so
        # this closes the menu the way an action button's dropdown closes.
        case ComputeCodeClick(col=named, expr=expr):
            col = _named_column(model, named)
            source_expr = model.get('_source_expr')
            if col is not None and source_expr is not None:
                _close_column_menus(model)
                code = _agg_code(expr, _column_whole_expr(
                    model.get('columns') or {}, col, source_expr,
                    _model_binds(model)))
                # The whole line is read, rather than the aggregation alone: the
                # column it is asked of goes inside it, and a column a string
                # cell wrote needs what it needs wherever it is written.
                commands.append(new_code_command(
                    (_compute_code_name(expr, source_expr), code),
                    code_imports))

        # The menu goes away for both: the column it was opened on is called
        # something else now, and the row that was clicked has become the other
        # one -- there is nothing left to click a second time.
        case SplatColumnClick(col=named):
            col = _named_column(model, named)
            if col is not None and _can_expand_column(col, value, model,
                                                      eval_in_scope):
                _close_column_menus(model)
                _expand_column_into_rows(model, col, value, get_visualizer,
                                         eval_in_scope)

        case UnsplatColumnClick(col=named):
            col = _named_column(model, named)
            if col is not None and _can_collapse_column(col, model):
                _close_column_menus(model)
                _collapse_column_into_cells(model, col, eval_in_scope)

        # Sub-columns leave the menu open, like the tally and Compute: checking
        # several boxes in a row is what a list of them is for. Every one of
        # these re-points the menu afterwards, because a column that gains or
        # loses its sub-columns moves in the target space the ids are made of.
        case SubcolToggle(col=named, expr=expr):
            col = _named_column(model, named)
            if col is not None and expr.strip():
                subs = _subs_at(model['columns'], col, create=True)
                if subs is not None:
                    if expr in subs:
                        _drop_subcolumn(model, col, expr, eval_in_scope)
                    else:
                        _col_add(subs, expr)
                    _save_subcolumns(model, col)

        case SubcolShowAll(col=named):
            col = _named_column(model, named)
            if col is not None:
                subs = _subs_at(model['columns'], col, create=True)
                if subs is not None:
                    for expr in _subcol_candidates(col, value, model,
                                                   get_visualizer, eval_in_scope):
                        _col_add(subs, expr)
                    _save_subcolumns(model, col)

        case SubcolHideAll(col=named):
            col = _named_column(model, named)
            if col is not None:
                for expr in list(_subs_at(model['columns'], col) or {}):
                    _drop_subcolumn(model, col, expr, eval_in_scope)
                _save_subcolumns(model, col)

        case SubcolExprInput(col=named, expr=expr, value=text):
            col = _named_column(model, named)
            if col is not None:
                subs = _subs_at(model['columns'], col, create=True)
                if subs is not None:
                    written = text.strip()
                    if expr in subs:
                        # In place, so the column the user is typing at stays
                        # where it is among its siblings.
                        index_of = list(subs).index(expr)
                        _drop_subcolumn(model, col, expr, eval_in_scope)
                        if written:
                            _col_add(subs, written)
                            _col_move(subs, len(subs) - 1, index_of)
                    elif written:
                        _col_add(subs, written)
                    _save_subcolumns(model, col)

        case SubcolExprKeyDown():
            key = event_json.get('key', '')
            if key == 'Enter':
                _close_column_menus(model)
            elif key == 'Escape':
                # Innermost first: the submenu sits inside the column menu.
                model['col_search_dropdown'] = None

        # The tally leaves the column menu open: picking several values in a row
        # is the whole point of it.
        case TallyItemToggle(col=named, literal=literal):
            col = _named_column(model, named)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                if literal in selected:
                    selected = [lit for lit in selected if lit != literal]
                else:
                    selected = selected + [literal]
                _write_tally_selection(
                    model, col,
                    _in_tally_order(selected,
                                    _tally_literals(col, model, value, eval_in_scope)),
                    exclude)
                _recompose_search(model, eval_in_scope)

        # All and None reach only as far as the filter box has left on show, so
        # with an empty box they mean every value and none of them.
        case TallySelectAll(col=named):
            col = _named_column(model, named)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                rows = _column_tally_rows(col, model, value, eval_in_scope)
                order = [lit for _text, _count, lit in rows if lit is not None]
                shown = _tally_shown(model, rows, eval_in_scope)
                kept = [lit for lit in selected if lit not in set(shown)]
                _write_tally_selection(
                    model, col, _in_tally_order(kept + shown, order), exclude)
                _recompose_search(model, eval_in_scope)

        case TallySelectNone(col=named):
            col = _named_column(model, named)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                shown = set(_tally_shown(
                    model, _column_tally_rows(col, model, value, eval_in_scope),
                    eval_in_scope))
                _write_tally_selection(
                    model, col, [lit for lit in selected if lit not in shown],
                    exclude)
                _recompose_search(model, eval_in_scope)

        case TallyExcludeToggle(col=named):
            col = _named_column(model, named)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                # Rewriting the same selection the other way round flips the
                # operator and leaves the values alone.
                _write_tally_selection(model, col, selected, not exclude)
                _recompose_search(model, eval_in_scope)

        case TallyFilterInput(col=named, value=val):
            # Display only: it decides which rows the menu lists, and never
            # what the column search says.
            if _named_column(model, named) is not None:
                model['tally_filter'] = val

        case TallySortSelect(col=named, sort=sort):
            # Display only too, though the order does reach the search: a
            # selection is written in the order it was listed in, so it reads
            # the way the list the user clicked through read.
            if _named_column(model, named) is not None and sort in TALLY_SORTS:
                model['tally_sort'] = sort
                model['col_search_dropdown'] = None

        case TallyCountFilterInput(col=named, value=val):
            # Display only, like the box beside it: which rows the menu lists,
            # never what the column search says.
            if _named_column(model, named) is not None:
                model['tally_count_filter'] = val

        case TallyCountOpSelect(col=named, op=op):
            if _named_column(model, named) is not None and op in TALLY_COUNT_OPS:
                model['tally_count_op'] = op
                model['col_search_dropdown'] = None

        case ColumnSearchDropdownToggle(dropdown_id=did):
            current = model.get('col_search_dropdown')
            model['col_search_dropdown'] = None if current == did else did

        # Set rather than toggled: dwelling says which submenu the pointer is
        # asking for, and that can't depend on which one it was asking for
        # before. Only rendered where it would change something, so arriving
        # here always does.
        case ColumnSubmenuDwell(dropdown_id=did):
            model['col_search_dropdown'] = did

        case ColumnMenuDismiss():
            _close_column_menus(model)

        case SearchBoxInput(value=val):
            had_search = bool(model.get('search'))
            model['search'] = val if val else None
            model['_scroll_to_match'] = True
            # Every keystroke, so the column menus and the tally checkmarks are
            # never describing a search that has moved on. Text that is still
            # half typed simply reads back as one leftover.
            _apply_search_to_columns(model, eval_in_scope)
            if had_search != bool(model['search']):
                # The bands the region ids name are the ones a first match
                # divides the rows into, and whether there IS a first match just
                # changed -- so the ids in hand no longer name anything.
                model['picked'] = None
                model['pick_expr'] = None

        case FirstMatchToggle():
            # Pick works over the first match only, so the toggle is inert while
            # pick is active (and renders dimmed to say so).
            if model.get('tool') != 'pick':
                model['first_match'] = not model.get('first_match', False)

        case ToolSelect(tool=t):
            if t in ('normal', 'pick'):
                model['tool'] = t
                model['openDropdown'] = None
                # Picks are scoped to one pick session: drop them whenever the
                # tool changes, entering or leaving.
                model['picked'] = None
                model['pick_expr'] = None
                if t == 'pick':
                    model['first_match'] = True
                    # Filter is the only action that consumes a picked
                    # expression, so a linked line switches over to it.
                    if model.get('linked_action'):
                        model['linked_action'] = 'filter'

        case PickToggle(region_id=region_id):
            if model.get('tool') == 'pick':
                picked = list(model.get('picked') or [])
                if region_id in picked:
                    picked.remove(region_id)
                else:
                    picked.append(region_id)
                model['picked'] = picked or None
                # _build_pick_expr emits in canonical (column, band) order, so
                # the click order the user happened to use doesn't leak out.
                model['pick_expr'] = _build_pick_expr(
                    model, _pick_source_expr(model, var_and_exp) or 'result')

        case ExpandToggle():
            # The one bit the bar owns. Undeclared in the defaults above: it is
            # false until the bar is there to be clicked, and the render reads
            # it back the same way.
            model['expanded'] = not model.get('expanded', False)

        case LoadMoreRows():
            # Undeclared until clicked, for the reason `expanded` is -- and it
            # only ever grows, so a page loaded stays loaded until the model is
            # rebuilt.
            model['shown_rows'] = _shown_rows(model) + ROWS_PER_PAGE

        case DropdownToggle(dropdown_id=did):
            current = model.get('openDropdown')
            # A chip menu, and a tally narrowed down or reordered, belong to the
            # menu that was open rather than to the one being opened.
            model['col_search_dropdown'] = None
            _reset_tally_view(model)
            if current is not None and current.get('id') == did:
                model['openDropdown'] = None
            else:
                model['openDropdown'] = {'id': did}

        case JoinSeparatorInput(value=val):
            dd = model.get('openDropdown')
            if dd and dd.get('id') == 'action-join':
                dd['customSep'] = val

        case ActionButtonClick(action=action, copy=copy):
            model['openDropdown'] = None
            join_sep = None
            if action.startswith('join:'):
                join_sep = action[5:]
                action = 'join'
            if model.get('linked_action') and not copy:
                model['linked_action'] = action
                ctx = _get_search_context(model, var_and_exp,
                                          source_expr=model['linked_source_expr'],
                                          eval_in_scope=eval_in_scope)
                if ctx is None:
                    ctx = _get_whole_list_context(
                        model,
                        var_and_exp,
                        source_expr=model['linked_source_expr'],
                    )
                if ctx:
                    if join_sep is not None:
                        ctx['join_separator'] = join_sep
                    result = generate_action(action, ctx)
                    if result:
                        _emit_linked_update(result[1], model, commands,
                                            suggest_name=result[0], rename=True)
            else:
                ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                if ctx is None:
                    ctx = _get_whole_list_context(model, var_and_exp)
                if ctx:
                    if join_sep is not None:
                        ctx['join_separator'] = join_sep
                    result = generate_action(action, ctx)
                    if result:
                        if copy:
                            commands.append(CopyToClipboard(text=with_pass_body(result[1])))
                        else:
                            commands.append(new_code_command(result, code_imports))
                            # Link the freshly inserted LOC to this action so
                            # subsequent interactions edit it in place (via
                            # ChangeSelectedText) instead of stacking new lines.
                            # Nested, there is no line to own - see is_nested.
                            if not is_nested(var_and_exp):
                                model['linked_action'] = action
                                model['linked_source_expr'] = ctx.get('source_expr')
                                model['last_linked_expr'] = result[1]
                                model['auto_linked_once'] = True

        case Unlink():
            # Stash the action so the chain icon can resume it on relink.
            model['unlinked_action'] = model.get('linked_action')
            model['linked_action'] = None
            model['linked_source_expr'] = None
            model['last_linked_expr'] = None

        case Relink(mode=mode, text=text):
            handle_relink(_LINK_CONFIG, mode, text, var_and_exp, model, commands,
                          eval_in_scope=eval_in_scope)

        case DeselectChildren():
            model['focused_child'] = None

        case SelectGroupedComputeTab(grouped=grouped):
            model['grouped_compute_tab_selected'] = grouped

        case ColumnResize(col=col, width=width):
            model['column_widths'][col] = width


    if is_nested(var_and_exp):
        return (model, commands)

    if model.get('linked_action') and not isinstance(msg, (ActionButtonClick, Unlink, Relink)):
        ctx = _get_search_context(model, var_and_exp,
                                  source_expr=model['linked_source_expr'],
                                  eval_in_scope=eval_in_scope)
        if ctx:
            result = generate_action(model['linked_action'], ctx)
            if result:
                _emit_linked_update(result[1], model, commands,
                                    suggest_name=result[0])
    elif (not model.get('linked_action')
          and not model.get('auto_linked_once')
          and not commands
          and not isinstance(msg, (Unlink, Relink))):
        # First meaningful interaction: if it yields a parseable expression,
        # auto-insert a line of code and self-link so subsequent interactions
        # update it in place via ChangeSelectedText (the linked block above).
        _maybe_auto_link(var_and_exp, model, commands, eval_in_scope=eval_in_scope)

    return (model, commands)


# Default actions used when auto-linking on the first interaction, or when
# relinking to a line whose shape rules out the previously stashed action.
_AUTO_LINK_ACTION = 'filter'
_AUTO_LINK_STATEMENT_ACTION = 'loop_no_idx'

# This visualizer's wiring for the shared relink logic in visualizer_utils.
_LINK_CONFIG = LinkConfig(
    parse_line=parse_generated_code_or_assignment,
    get_context=_get_search_context,
    generate_action=generate_action,
    ctx_to_model=_ctx_to_model,
    change_selected_text=ChangeSelectedText,
    default_action=_AUTO_LINK_ACTION,
    default_statement_action=_AUTO_LINK_STATEMENT_ACTION,
    statement_actions=_STATEMENT_ACTIONS,
    whole_value_context=_get_whole_list_context,
    code_imports=code_imports,
)


def _maybe_auto_link(var_and_exp, model: dict, commands: list, *, eval_in_scope=None) -> None:
    """If the current search state yields a parseable filter expression, set up
    linked editing and append a NewCode tuple to insert the linked line.

    No-op if no search context is available or the generated code doesn't parse.
    """
    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
    if not ctx:
        return
    result = generate_action(_AUTO_LINK_ACTION, ctx)
    if not result:
        return
    suggest_name, expr = result
    prefix = f'{suggest_name} = ' if suggest_name else ''
    try:
        ast.parse(with_pass_body(prefix + expr))
    except SyntaxError:
        return
    model['linked_action'] = _AUTO_LINK_ACTION
    model['linked_source_expr'] = ctx.get('source_expr')
    model['last_linked_expr'] = expr
    model['auto_linked_once'] = True
    commands.append(new_code_command(result, code_imports))
