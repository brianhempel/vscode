"""List visualizer for Sculpt-n-Code.

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
   - Loads saved column configuration from dotfile

3. update(event, var_and_exp, model, value) -> (new_model, commands)
   - Processes UI events (click, input, keyboard, drag) and returns updated model
   - Routes child events to cell visualizers
   - Handles column management events

================================================================================
COLUMN CONFIGURATION
================================================================================

Columns shown in the table are configurable and persisted:

1. DOTFILE (.snc_list_columns.json in working directory):
   - JSON mapping {item_type_key: [column_name, ...]}
   - Highest priority: user-customized columns

2. Auto-detection via _detect_table_columns:
   - Samples items and returns union of fields if all support get_fields

3. Default: ['$'] (the item itself)
   - Used when items lack fields (strings, ints, mixed types, empty lists)
   - Users can add computed columns via the (+) button
================================================================================
"""

import ast
import html
import keyword
import random
import re
import warnings
from dataclasses import dataclass
from math import sqrt
from typing import Any, List, Tuple, Optional

from list_visualizer_grammar import parse_generated_code_or_assignment, _STATEMENT_ACTIONS
from visualizer_utils import (
    ChildEvent, Unlink, Relink,
    route_child_event, aggregate_handled_keys,
    with_pass_body,
    LinkConfig, handle_relink,
    wrap_child_prefix, wrap_child_suffix,
    DOLLARS_RE,
    strip_leading_dollar, eval_dollar_expr, replace_dollars_in_py_exp,
    py_exp_attrs,
    CHILD_SOURCE_BINDER, nest_generated_expr, nest_child_command,
    new_code_command,
    dollar_expr_parses, is_nested,
    get_full_class_name, truncate_str,
    config_key, parse_slots, load_root_slots, save_slots_at_path,
    child_nesting_kwargs, too_deep,
    nerd_font_icon, render_tool_toolbar,
    ICONS,
)

# This visualizer participates in the shared nested-slots config (parents thread
# per-slot config + path to it; see visualizer_utils). Used to decide whether to
# pass nesting kwargs to a child.
SUPPORTS_NESTED_CONFIG = True

CELL_KEY_SEP = '\x00'

# === Event types ===

@dataclass(frozen=True, slots=True)
class AddColumnClick:
    """User clicked the (+) button to add a new column."""
    pass

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
    index: int

@dataclass(frozen=True, slots=True)
class RemoveColumnClick:
    """User clicked the (x) button to remove a column."""
    index: int

@dataclass(frozen=True, slots=True)
class ColumnDragStart:
    """User pressed mouse down on a column drag handle to start reordering."""
    index: int

@dataclass(frozen=True, slots=True)
class ColumnDragOver:
    """Mouse moved over a column header while dragging (reorder target)."""
    index: int

@dataclass(frozen=True, slots=True)
class ColumnDragEnd:
    """User released mouse to drop a column at the target position."""
    index: int

@dataclass(frozen=True, slots=True)
class ColumnKeyDown:
    """Keyboard event in column management (Enter to commit, Escape to cancel)."""
    pass

@dataclass(frozen=True, slots=True)
class ColumnSearchInput:
    """User typed in a column's search box (inside that column's ▾ menu)."""
    index: int
    value: str

@dataclass(frozen=True, slots=True)
class ColumnSearchOpSelect:
    """User picked a comparison operator for a column's search."""
    index: int
    op: str

@dataclass(frozen=True, slots=True)
class ColumnSearchComposeSelect:
    """User picked how a column's search composes with the other columns'."""
    index: int
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
    index: int
    literal: str

@dataclass(frozen=True, slots=True)
class TallySelectAll:
    """User clicked Select All on a column's tally."""
    index: int

@dataclass(frozen=True, slots=True)
class TallySelectNone:
    """User clicked Select None on a column's tally."""
    index: int

@dataclass(frozen=True, slots=True)
class TallyExcludeToggle:
    """User toggled Exclude on a column's tally, turning the values it has
    selected into the ones to leave out."""
    index: int

@dataclass(frozen=True, slots=True)
class TallyFilterInput:
    """User typed in a column tally's filter box, narrowing which of the
    column's values the menu lists."""
    index: int
    value: str

@dataclass(frozen=True, slots=True)
class TallySortSelect:
    """User picked the order a column tally lists its values in."""
    index: int
    sort: str

@dataclass(frozen=True, slots=True)
class TallyCountFilterInput:
    """User typed in a column tally's count box, narrowing the menu to the
    values of that frequency."""
    index: int
    value: str

@dataclass(frozen=True, slots=True)
class TallyCountOpSelect:
    """User picked how a column tally's count box compares."""
    index: int
    op: str

@dataclass(frozen=True, slots=True)
class ComputeToggle:
    """User checked or unchecked one of a column's Compute rows.

    Identified by the expression it is showing rather than by a name for it, so
    an aggregation the user wrote themselves needs no event of its own.
    """
    index: int
    expr: str

@dataclass(frozen=True, slots=True)
class ComputeHoleInput:
    """User typed in one of the boxes inside a Compute row's expression, e.g.
    the level of a percentile."""
    index: int
    expr: str
    hole: int
    value: str

@dataclass(frozen=True, slots=True)
class ComputeCodeClick:
    """User clicked one of the Compute submenu's code rows -- Unique, Tally --
    which answer with a whole list, so they write a line rather than keep a cell
    on screen."""
    index: int
    expr: str

@dataclass(frozen=True, slots=True)
class ComputeExprInput:
    """User typed an aggregation of their own: into the empty box at the foot of
    the Compute submenu, or into the box that labels the cell it made.

    Both boxes hold the whole expression rather than part of one, which is what
    tells this from ComputeHoleInput.
    """
    index: int
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

# === Command types ===

@dataclass(frozen=True, slots=True)
class CopyToClipboard:
    text: str

@dataclass(frozen=True, slots=True)
class ChangeSelectedText:
    expression: str
    suggested_var_name: Optional[str] = None


# === Dotfile operations ===

COLUMN_DOTFILE_NAME = '.snc_list_columns.json'


def _get_item_type_key(lst):
    """Return a type key for the items in the list (based on first item's class)."""
    if not lst:
        return None
    return get_full_class_name(lst[0])


def load_columns_from_dotfile(type_key: str):
    """Load the saved slot list for an item type from the dotfile (or None).

    Kept as the single root-read entry point so tests can patch it for isolation.
    Returns the raw slot list (bare strings and/or {"expr", "children"} dicts).
    """
    return load_root_slots(COLUMN_DOTFILE_NAME, type_key)


def save_columns_to_dotfile(root_type, path, exprs, dotfile=COLUMN_DOTFILE_NAME):
    """Path-scoped writer: persist a (sub-)table's column exprs at its location.

    `path` is the list of (slot_expr, child_type) steps from the root type.
    """
    save_slots_at_path(dotfile, root_type, path, exprs)


def _save_slots(model: dict) -> None:
    """Persist a table model's columns at its config path (preserves nested
    children of surviving columns and other types on disk)."""
    save_columns_to_dotfile(
        model.get('_config_root_type'),
        model.get('_config_path') or [],
        list(model.get('columns', [])),
        model.get('_config_root_dotfile') or COLUMN_DOTFILE_NAME,
    )


# === Column autocomplete helpers ===

def _sample_indices(lst):
    """Return a sorted set of representative indices for sampling a list."""
    indices = {0}
    if len(lst) > 1:
        indices.add(len(lst) - 1)
    if len(lst) > 2:
        middle = list(range(1, len(lst) - 1))
        indices.update(random.sample(middle, min(10, len(middle))))
    return sorted(indices)


def _collect_fields_from_samples(lst, get_visualizer, require_all=False):
    """Collect the union of fields from sampled list items.

    If require_all is True, returns None when any sampled item lacks get_fields.
    Otherwise skips items without get_fields.
    """
    if not lst:
        return [] if not require_all else None

    columns = []
    seen = set()

    for idx in _sample_indices(lst):
        vis = get_visualizer(lst[idx])
        item_get_fields = getattr(vis, 'get_fields', None)
        if item_get_fields is None:
            if require_all:
                return None
            continue
        fields = item_get_fields(lst[idx])
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


def _is_valid_python_expression(s: str) -> bool:
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
    (the same trick dollar_expr_parses uses) before parsing.
    """
    try:
        return ast.parse(DOLLARS_RE.sub('_crt_', expr), mode='eval').body
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
    """
    depth = max((len(m[0]) for m in DOLLARS_RE.finditer(pred)), default=1)
    # Substituted in two passes via dollar-free placeholders:
    # replace_dollars_in_py_exp tells code dollars from string-literal dollars by
    # re-parsing with the run restored, and a replacement that itself contains
    # dollars never parses -- which would make every run after the first look
    # like code even inside a string.
    holders = [f'_snc_lift{n}_' for n in range(1, depth + 1)]
    out = replace_dollars_in_py_exp(pred, holders)
    for n, holder in enumerate(holders, start=1):
        out = out.replace(holder, _atomize(col_expr) if n == 1 else '$' * (n - 1))
    return out


def _paren_if_loose(term: str) -> str:
    """Parenthesize a term whose top level would swallow a surrounding `and`."""
    node = _parse_dollar_expr(term)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return f'({term})'
    if isinstance(node, (ast.IfExp, ast.Lambda, ast.NamedExpr)):
        return f'({term})'
    return term


def compose_column_searches(columns, column_searches, eval_in_scope=None) -> str | None:
    """Fold every active column search into one main-search string.

    The `and` columns form a group in column order; the `or` columns are then
    or'd against it. Parentheses appear only where Python's precedence would
    otherwise read the result differently, so a lone column search comes out as
    exactly what the user typed.
    """
    searches = column_searches or {}
    and_terms, or_terms = [], []
    for col in columns:
        row = searches.get(col)
        if not row:
            continue
        pred = column_search_predicate(row.get('op', ''), row.get('text', ''),
                                       eval_in_scope)
        if not pred:
            continue
        term = lift_column_predicate(pred, col)
        # A row that never said how it composes composes the way every other
        # default does. Only `or` is a choice; `and` is what not choosing means,
        # so a row built without the key reads as one rather than crashing here.
        compose = row.get('compose') or 'and'
        (or_terms if compose.lower() == 'or' else and_terms).append(term)

    if not and_terms and not or_terms:
        return None
    group = ' and '.join(_paren_if_loose(t) for t in and_terms)
    if not or_terms:
        return group
    # `and` binds tighter than `or`, so a single-term group needs no parens.
    if len(and_terms) > 1:
        group = f'({group})'
    return ' or '.join(([group] if and_terms else []) + or_terms)


# The rows are keyed by column EXPRESSION, like _slot_children and the cell
# children, so reordering columns can't scramble which search belongs to which.

def _column_at(model: dict, index: int) -> str | None:
    columns = model.get('columns', [])
    return columns[index] if 0 <= index < len(columns) else None


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


def _rename_column_search(model: dict, old_name: str, new_name: str) -> None:
    searches = dict(model.get('column_searches') or {})
    if old_name in searches:
        searches[new_name] = searches.pop(old_name)
        model['column_searches'] = searches or None


def _column_computes(model: dict, col: str) -> List[str]:
    """The aggregations a column is showing, as the expressions they are."""
    return list((model.get('column_computes') or {}).get(col) or [])


def _set_column_computes(model: dict, col: str, exprs) -> None:
    """Write a column's aggregations, keeping them in the order the menu lists
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


def _remove_column_compute(model: dict, col: str) -> None:
    computes = dict(model.get('column_computes') or {})
    computes.pop(col, None)
    model['column_computes'] = computes or None


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

    Menu ids are index-based, so adding, removing, reordering or renaming a
    column leaves an open menu pointing at the wrong one.
    """
    model['openDropdown'] = None
    model['col_search_dropdown'] = None
    _reset_tally_view(model)


def _recompose_search(model: dict, eval_in_scope=None) -> None:
    """Push the column searches into the main search box.

    One-directional for now: the main box is free to hold anything the user
    types, so when the columns have nothing to say we leave a hand-written
    search alone rather than clearing it. `search_from_columns` records what the
    columns last wrote, which is what tells the two apart.
    """
    composed = compose_column_searches(model.get('columns', []),
                                       model.get('column_searches') or {},
                                       eval_in_scope)
    if composed is None and model.get('search') != model.get('search_from_columns'):
        return
    previous = model.get('search')
    model['search'] = composed or None
    model['search_from_columns'] = composed
    if model['search'] != previous:
        model['_scroll_to_match'] = True


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


def _column_item_expr(col: str) -> str | None:
    """One row's value for a column, written against a row bound to `item` --
    or None when the column is the item itself and there is nothing to read."""
    return None if col.strip() == '$' else replace_dollars_in_py_exp(col, ['item'])


def _column_key_expr(col: str) -> str:
    """The same, as a key to order the list by: `item` itself when the column
    is the row, which is what `min(lst, key=lambda item: item)` reads."""
    return _column_item_expr(col) or 'item'


def _column_values_clause(col: str, source_expr: str) -> str | None:
    """A column's values as a comprehension body, `<value> for item in <source>`,
    for a caller that brackets it itself -- or None when the column is the item
    and the source already is the values.

    The one description of where a column's values come from: what the header
    hands to a drag, what the tally counts, and what the tally hands over in
    turn.
    """
    item_expr = _column_item_expr(col)
    return None if item_expr is None else f'{item_expr} for item in {source_expr}'


def _column_values_expr(col: str, source_expr: str) -> str:
    """The same as a list: the source itself when the column is the item, and a
    comprehension over it otherwise."""
    clause = _column_values_clause(col, source_expr)
    return source_expr if clause is None else f'[{clause}]'


def _column_values(col, lst, model, eval_in_scope=None) -> list:
    """Every row's value for one column, in row order.

    The table evaluates a cell at a time, but a tally wants the whole column, so
    ask for it in one comprehension -- the same expression the header hands to a
    drag. Rows the column can't be read from are dropped: a summary shouldn't
    cost the other n-1 rows.
    """
    if col.strip() == '$':
        return list(lst)

    source_expr = model.get('_source_expr')
    if source_expr is not None and eval_in_scope is not None:
        try:
            return list(eval_in_scope(_column_values_expr(col, source_expr)))
        except Exception:
            # A comprehension is all or nothing, so one unreadable row lands
            # here too; the loop below gets the rest.
            pass

    values = []
    for item in lst:
        try:
            values.append(eval_dollar_expr(col, item, eval_in_scope))
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


def _tally_counter_expr(col: str, source_expr: str) -> str:
    """The whole tally, before the menu has narrowed or reordered anything.

    Counter takes any iterable, so a computed column goes in as a generator --
    there is no list to build on the way to counting it.
    """
    clause = _column_values_clause(col, source_expr)
    return f'Counter({clause if clause is not None else source_expr})'


def _tally_row_count_expr(col: str, source_expr: str, literal: str,
                          values) -> str:
    """How many rows have one value -- the number that row is showing.

    A question about a single value, so it asks about that one rather than
    counting the whole column to look one answer up.

    When the column is the item, the values are the source itself, and a
    sequence can count one of its own. Only a sequence: a set has no `.count`
    at all, and a string's counts substrings rather than elements, which is a
    different question with the same name. Anything else -- and every computed
    column, which has no list to ask -- counts the rows that match as it goes.
    """
    item_expr = _column_item_expr(col)
    if item_expr is None:
        if isinstance(values, (list, tuple)):
            return f'{source_expr}.count({literal})'
        item_expr = 'item'
    return f'sum(1 for item in {source_expr} if {item_expr} == {literal})'


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

    counter_expr = _tally_counter_expr(col, source_expr)
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

COMPUTE_AGGS = (
    ('#Unique',    'len(set($))'),
    ('#Present',   'sum(x is not None for x in $)'),
    ('#Missing',   'sum(x is None for x in $)'),
    ('Min',        'min($)'),
    ('Min Idx',    'np.argmin($)'),
    ('Mean',       'np.mean($)'),
    ('Median',     'np.median($)'),
    ('Percentile', 'np.percentile($, {{10}})'),
    ('Percentile', 'np.percentile($, {{90}})'),
    ('Max',        'max($)'),
    ('Max Idx',    'np.argmax($)'),
    ('Min Item',   ROW_AGGS[0]),
    ('Max Item',   ROW_AGGS[1]),
    ('Histogram',  HISTOGRAM_AGG),
)

# The rest of the submenu: questions whose answer is a whole list rather than a
# value, so there is no cell small enough to keep one in. Clicking writes the
# line, the way an action button does; each is a name, the expression it is, and
# what to call the line it writes.
COMPUTE_CODES = (
    ('Unique', 'set($)',     'unique'),
    ('Tally',  'Counter($)', 'tally'),
)

COMPUTE_IMPORTS = ('import numpy as np',)

# What a box the user writes an aggregation in says of itself, wherever it is
# drawn. The same thing the column search box says of its own, less `$$$`: an
# aggregation is asked of the whole column, so there is no one item to name.
COMPUTE_EXPR_TOOLTIP = '$ is this column, $$ the list'

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


def _agg_row_index_code(item_code: str, source_expr: str) -> str:
    """The index of the row a row aggregation picked: the list's own index of
    it, written around the code that picked it.

    `data.index(min(data, key=lambda item: item['b']))`. Around rather than
    beside, so the row the cells read and the number the index cell hands over
    cannot name different rows. `.index` finds the first row equal to it, which
    is the row `min` returned -- an earlier equal row has an equal key, so
    `min` would have stopped there.
    """
    return f'{source_expr}.index({item_code})'


def _agg_row_index(lst, item):
    """Where a row aggregation's row sits in the list, or NO_ANSWER -- the same
    question _agg_row_index_code writes down, asked here."""
    try:
        return lst.index(item)
    except Exception:
        return NO_ANSWER


def _agg_imports(template: str) -> Tuple[str, ...]:
    """The imports an expression needs, declared where it's written, the way
    TALLY_IMPORTS is."""
    code = _agg_fill(template)
    return ((COMPUTE_IMPORTS if 'np.' in code else ())
            + (TALLY_IMPORTS if 'Counter(' in code else ()))


def _agg_label(template: str) -> str:
    """What a row and its cell read: the catalog's name for the expression,
    with whatever is in its boxes after it (`Percentile 25`).

    An expression the catalog doesn't know -- one the user wrote -- has no name
    but itself.
    """
    shape = _agg_shape(template)
    for label, known in COMPUTE_AGGS:
        if _agg_shape(known) == shape:
            return ' '.join([label] + _agg_holes(template))
    return _agg_fill(template)


def _agg_is_free(template: str) -> bool:
    """Whether an expression is one the user wrote themselves.

    Nothing marks it as theirs: a free-form aggregation is simply an expression
    no row of the catalog already reads, which is why one that happens to be
    written the same way as Min *is* Min and ticks that row. An empty box has
    written nothing yet, and counts as theirs until it does.
    """
    shape = _agg_shape(template)
    return not any(_agg_shape(known) == shape for _, known in COMPUTE_AGGS)


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


def _agg_value(template: str, values: list, eval_in_scope=None, lst=None,
               item_expr: str = 'item'):
    """An aggregation's answer for a column's values, or NO_ANSWER.

    *lst* is the list the column was read out of, which is what a row
    aggregation orders; one that isn't handed a list has nothing to answer
    with, which is NO_ANSWER like any other question it can't answer.

    *item_expr* is the column read off one row, against a row bound to `item`,
    which is what `$` stands for in a row aggregation -- it asks its question
    row by row rather than of every value at once. Defaulted to `item` itself,
    the column that is the row.

    Evaluated in the user's scope, so a column expression that named the
    program's own values has already been read by the time we get here -- but
    `np` is handed in rather than looked up, so the answer doesn't depend on
    the file having imported numpy (or on what it called it if it did).

    Anything at all can go wrong here -- an expression that doesn't parse, a
    mean of strings, a numpy that isn't installed -- and none of it is worth
    more than a row with nothing to show.

    A warning counts as going wrong, for two reasons: numpy warns rather than
    raises where it has no answer (the mean of an empty column is a warning and
    a nan), and a warning would otherwise be printed into the output of the
    user's own program by a menu they only opened to look at.
    """
    try:
        column = item_expr if _agg_is_row(template) else '_v'
        body = replace_dollars_in_py_exp(_agg_expr(_agg_fill(template)),
                                         [column, '_lst'])
        code = f'lambda np, _v, _lst: {body}'
        agg = eval_in_scope(code) if eval_in_scope is not None else eval(code)
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            return agg(_numpy(), values, lst)
    except Exception:
        return NO_ANSWER


def _agg_code(template: str, column_expr: str, source_expr: str = None) -> str:
    """The expression itself, with `$` bound to the column and `$$` to the list
    the column was read out of.

    *column_expr* is what `$` stands for, which the caller knows because it
    knows the column: every value the column has -- the same list expression
    the column header hands to a drag -- or, for a row aggregation, the column
    read off one row. _agg_column_expr is where that choice is made.
    """
    replacements = ([column_expr] if source_expr is None
                    else [column_expr, source_expr])
    return replace_dollars_in_py_exp(_agg_fill(template), replacements)


def _agg_column_expr(template: str, col: str, source_expr: str) -> str:
    """What `$` stands for in an aggregation over *col*: every value the column
    has, or -- for a row aggregation, which asks row by row -- the column read
    off the row its key is handed."""
    return (_column_key_expr(col) if _agg_is_row(template)
            else _column_values_expr(col, source_expr))


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

    By shape, the way _agg_label knows a percentile from a median, so nothing
    has to be stored beside the expression to say what it draws.
    """
    return _agg_shape(template) == _agg_shape(HISTOGRAM_AGG)


# How the bars are laid out. The height is what a count is measured against; the
# width is per bar, of which the bar itself takes most and the gap the rest.
_HIST_HEIGHT = 10
_HIST_STEP = 2
_HIST_BAR = 1.6


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
        bars.append(f'<rect x="{i * _HIST_STEP:g}" y="{_HIST_HEIGHT - height:g}" '
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
    """Build search context dict from model + source info.

    Returns None if no valid search or source info.
    """
    search = model.get('search')
    if not search:
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
    # lands on once it is lifted into this scope.
    predicate_expr = replace_dollars_in_py_exp(predicate_with_dollar,
                                              ['item', _atomize(source_expr)])

    ctx = {
        'source_expr': source_expr, 'has_var': has_var, 'suggest_base': suggest_base,
        'is_predicate': True, 'predicate_expr': predicate_expr,
        'is_index': False, 'is_slice': False, 'is_multi_index': False,
        'is_first': first,
    }

    # A pick composes an expression over the FIRST match only, so it forces
    # first-match mode and rides along for generate_action to wrap.
    pick_expr = model.get('pick_expr')
    if pick_expr:
        ctx['pick_expr'] = replace_dollars_in_py_exp(pick_expr, ['item'])
        ctx['needs_index'] = _pick_needs_index(pick_expr)
        ctx['pick_is_array'] = _pick_is_array(model)
        ctx['is_first'] = True

    return ctx


def _get_whole_list_context(model: dict, var_and_exp=None,
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
        model['search'] = re.sub(r'\bitem\b', '$', pred)
    model['first_match'] = bool(ctx.get('is_first'))

    # A picked expression survives the round-trip through the line of code, but
    # the region ids that produced it do not -- they aren't recoverable from the
    # expression. So the table re-enters pick mode showing the restored
    # expression, with nothing highlighted until the user picks again.
    pick_expr = ctx.get('pick_expr')
    if pick_expr:
        model['pick_expr'] = re.sub(r'\bitem\b', '$', pick_expr)
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
        if ctx.get('is_first'):
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
    """
    binding = (f'i, item in enumerate({ctx["source_expr"]})'
               if ctx.get('needs_index') else f'item in {ctx["source_expr"]}')
    return (f'next(({ctx["pick_expr"]} for {binding} '
            f'if {ctx["predicate_expr"]}), None)')


def code_imports(code: str) -> tuple:
    """What code generated by this visualizer can't run without.

    Nothing, so far: every action here is builtins, comprehensions and slicing
    over the user's own list. The tally headers do need Counter, but they hand
    their expression straight to the editor rather than through an action, and
    declare TALLY_IMPORTS where they do it.
    """
    return ()


def generate_action(action: str, ctx: dict) -> tuple[str | None, str] | None:
    """Generate code for a list action.

    Returns (suggest_name, code_str) or None.
    """
    src = ctx['source_expr']
    first = ctx.get('is_first', False)

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
                    code = f'[0] * len({ctx["stop_list_expr"]})'
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

    if ctx.get('is_predicate'):
        pred = ctx['predicate_expr']
        pick = ctx.get('pick_expr')
        # A pick spanning a contiguous run of rows in one column is a list, so
        # the list-consuming actions run over it. Anything else a pick produces
        # is a scalar or a tuple, and those actions stay unavailable.
        pick_array = bool(pick) and bool(ctx.get('pick_is_array'))
        match action:
            case 'filter':
                if pick:
                    code = pick_filter_expr(ctx)
                elif first:
                    code = f'next((item for item in {src} if {pred}), None)'
                else:
                    code = f'[item for item in {src} if {pred}]'
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
                code = f'for item in (item for item in {src} if {pred}):'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate({src}):\n    if {pred}:'
            case 'loop_new_idx':
                code = f'for i, item in enumerate(item for item in {src} if {pred}):'
            case 'any':
                code = f'any({pred} for item in {src})'
            case 'all':
                code = f'all({pred} for item in {src})'
            case 'if_any':
                code = f'if any({pred} for item in {src}):'
            case 'if_all':
                code = f'if all({pred} for item in {src}):'
            case 'delete':
                if first:
                    code = f'next(({src}[:i] + {src}[i+1:] for i, item in enumerate({src}) if {pred}), {src})'
                else:
                    code = f'[item for item in {src} if not ({pred})]'
            case 'find_indices':
                if first:
                    code = f'next((i for i, item in enumerate({src}) if {pred}), None)'
                else:
                    code = f'[i for i, item in enumerate({src}) if {pred}]'
            case 'count':
                code = f'sum(1 for item in {src} if {pred})'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {src} if {pred})'
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
    """
    if expr == model.get('last_linked_expr'):
        return
    text = ('_linked_result = ' if model.get('linked_has_assignment') else '') + expr
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
    """A dollar-substituted predicate as a callable of (item, lst).

    Built in the user's scope so the predicate's free names resolve to their
    program's, which is the only place they were ever written. Without a scope
    to build it in -- an unfocused preview, a test -- this module's globals are
    all there is, which is enough for a predicate that names nothing.
    """
    code = f'(lambda _item, _lst: {predicate_expr})'
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

    predicate_expr = replace_dollars_in_py_exp(predicate_with_dollar, ['_item', '_lst'])

    # The predicate is the user's own text, so the names in it are their
    # program's names: `== s` has to mean the same `s` the line above defines.
    # Compiling it as a lambda through eval_in_scope is what puts those names in
    # reach -- evaluating it here would only ever see this module's globals, and
    # the NameError would land in the per-row except below as "no matches".
    # The row item and the array come in as arguments, so a dollar keeps naming
    # them whatever the surrounding scope calls its own variables.
    try:
        predicate = _compile_predicate(predicate_expr, eval_in_scope)
    except Exception:
        return []

    matched = []
    for i, item in enumerate(lst):
        try:
            if predicate(item, lst):
                matched.append(i)
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
# Region ids are '{band}_{column}': band is 'pre' / 'match' / 'post' and column
# is 'idx' (the row-index column) or 'col_<n>' (an index into model['columns']).
#
# Region expressions are written in the table's own scope, where $ is the row
# item and `i` is the matched row's index. generate_action binds $ to `item` and
# wraps the whole assembled expression in a single next(...) over the first
# match, which is what makes `i` available.

PICK_BANDS = ('pre', 'match', 'post')
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
}

# Bands of one column that sit next to each other collapse into a single range.
_PICK_COLLAPSE_RANGES = {
    frozenset(('pre', 'match', 'post')): (None, None),
    frozenset(('pre', 'match')): (None, 'i + 1'),
    frozenset(('match', 'post')): ('i', None),
}


def _pick_column_ids(columns) -> list:
    """Every pickable column id, in display order (row index first)."""
    return [PICK_IDX_COLUMN] + [f'col_{n}' for n in range(len(columns))]


def _pick_column_expr(col_id: str, columns) -> str | None:
    """The column expression a 'col_<n>' id refers to, or None if it doesn't."""
    if not col_id.startswith('col_'):
        return None
    try:
        n = int(col_id[len('col_'):])
    except ValueError:
        return None
    return columns[n] if 0 <= n < len(columns) else None


def _parse_pick_region_id(region_id: str) -> tuple | None:
    """Split a region id into (band, column_id), or None if malformed."""
    for band in PICK_BANDS:
        prefix = f'{band}_'
        if region_id.startswith(prefix):
            return (band, region_id[len(prefix):])
    return None


def _pick_bands_present(first_idx: int, n_rows: int) -> tuple:
    """Which bands actually hold rows, for a first match at first_idx."""
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


def _pick_range_expr(col_id: str, columns, source_expr: str,
                     start: str | None, stop: str | None) -> str | None:
    """Expression for one column over the row range [start, stop).

    start/stop are Python source snippets, or None for the ends of the list.
    """
    if col_id == PICK_IDX_COLUMN:
        lo = start or '0'
        hi = stop if stop is not None else f'len({source_expr})'
        return f'list(range({hi}))' if lo == '0' else f'list(range({lo}, {hi}))'
    col = _pick_column_expr(col_id, columns)
    if col is None:
        return None
    if start is None and stop is None:
        sub = source_expr
    else:
        sub = f'{source_expr}[{start or ""}:{stop or ""}]'
    inner = replace_dollars_in_py_exp(col, [_PICK_INNER_VAR])
    if inner == _PICK_INNER_VAR:
        # The identity column (a bare $, which is the default) maps each row to
        # itself, so the sublist is already the answer -- no comprehension.
        return sub
    return f'[{inner} for {_PICK_INNER_VAR} in {sub}]'


def _pick_match_expr(col_id: str, columns) -> str | None:
    """Expression for one column of the matched row itself (a scalar)."""
    if col_id == PICK_IDX_COLUMN:
        return 'i'
    return _pick_column_expr(col_id, columns)


def _pick_region_expr(region_id: str, columns, source_expr: str) -> str | None:
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
    return _pick_range_expr(col_id, columns, source_expr, *band_range)


# Band sets that cover a single contiguous run of rows. A run of rows within ONE
# column evaluates to a list, which is what makes the list-consuming actions
# (Loop, Join) meaningful. {'match'} on its own is a single row -- a scalar --
# and {'pre', 'post'} has a hole in it, so neither qualifies.
_PICK_ARRAY_BAND_SETS = frozenset({
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


def _pick_is_array(model: dict) -> bool:
    """True when the pick is one contiguous run of rows from a single column.

    That is exactly when the picked expression evaluates to a list, so Loop and
    Join apply to it. A lone match row is a scalar, pre+post is two lists, and
    two columns make a tuple -- none of those are a single array.
    """
    if model.get('tool') != 'pick':
        return False
    bands_by_column = _pick_bands_by_column(model)
    if len(bands_by_column) != 1:
        return False
    bands = next(iter(bands_by_column.values()))
    return frozenset(bands) in _PICK_ARRAY_BAND_SETS


def _build_pick_expr(model: dict, source_expr: str) -> str | None:
    """Assemble model['picked'] into one dollar-form expression.

    Bands of the same column collapse when they are contiguous: pre+match+post
    is that column over the whole list, pre+match is everything up to and
    including the match, match+post is the match onwards. pre+post has a hole in
    it, so it does not collapse.

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

    parts = []
    for col_id in _pick_column_ids(columns):
        bands = bands_by_column.get(col_id)
        if not bands:
            continue
        collapsed = _PICK_COLLAPSE_RANGES.get(frozenset(bands))
        if collapsed is not None:
            expr = _pick_range_expr(col_id, columns, source_expr, *collapsed)
            if expr:
                parts.append(expr)
            continue
        for band in PICK_BANDS:
            if band in bands:
                expr = _pick_region_expr(f'{band}_{col_id}', columns, source_expr)
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


def _pick_needs_index(pick_expr: str) -> bool:
    """Whether an assembled expression refers to the matched row's index."""
    code = replace_dollars_in_py_exp(pick_expr, ['item'])
    try:
        tree = ast.parse(code, mode='eval')
    except SyntaxError:
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
    return isinstance(value, list)


def get_fields(value):
    return [f'$[{i}]' for i in range(len(value))]


def _detect_table_columns(lst, get_visualizer):
    """Sample items and return union of fields if all sampled items are tabular, else None."""
    return _collect_fields_from_samples(lst, get_visualizer, require_all=True)


_COLUMN_MGMT_DEFAULTS = {
    'editing_column_index': None,
    'adding_column': False,
    'column_input_value': '',
    'selected_suggestion_index': None,
    'column_drag_from': None,
    'column_drag_over': None,
    # Per-column searches, keyed by column expression. Stored as None rather
    # than {} so this shared defaults dict never hands the same dict to two
    # models; always read it as `model.get('column_searches') or {}`.
    'column_searches': None,
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
    # What the column searches last composed, so a search the user typed by hand
    # can be told from one the columns wrote (see _recompose_search).
    'search_from_columns': None,
    'first_match': False,
    'openDropdown': None,
    'linked_action': None,
    'linked_source_expr': None,
    'linked_has_assignment': None,
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


def _resolve_columns(lst, get_visualizer, slots_config, config_path):
    """Return (columns, slot_children) for a list at this nesting position.

    At the root (config_path is None) the dotfile is read by item type. When
    nested, only the parent-supplied slots_config is used -- the type config is
    NOT re-read, which is what breaks the infinite recursion. A missing config
    falls back to auto-detected columns (or ['$']).
    """
    if config_path is None:
        type_key = config_key(lst)
        loaded = load_columns_from_dotfile(type_key) if type_key else None
    else:
        loaded = slots_config

    if loaded is not None:
        return parse_slots(loaded)

    columns = _detect_table_columns(lst, get_visualizer)
    if columns is None:
        columns = ['$']
    return columns, {}


def init_model(lst, get_visualizer=None, eval_in_scope=None, var_and_exp=None,
               slots_config=None, config_root_type=None, config_root_dotfile=None,
               config_path=None):
    is_root = config_path is None
    root_type = config_key(lst) if is_root else config_root_type
    root_dotfile = COLUMN_DOTFILE_NAME if is_root else config_root_dotfile
    path = [] if is_root else config_path
    config_fields = {
        '_config_root_type': root_type,
        '_config_root_dotfile': root_dotfile,
        '_config_path': path,
    }

    if get_visualizer is None:
        return {'children': {}, 'handledKeys': [], 'display_mode': 'table', 'columns': ['$'],
                '_slot_children': {}, **config_fields,
                **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS}

    source_expr = None
    if var_and_exp:
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else expr

    columns, slot_children = _resolve_columns(lst, get_visualizer, slots_config, config_path)
    config_fields['_slot_children'] = slot_children

    # Depth backstop: beyond the cap, stop building nested children entirely
    # (renders as a truncated repr) so cyclic values can't RecursionError.
    if too_deep(path):
        return {
            'children': {}, 'handledKeys': list(_OWN_KEYS), 'display_mode': 'table',
            'columns': columns, '_source_expr': source_expr, '_too_deep': True,
            **config_fields, **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS,
        }

    children = {}
    for i, item in enumerate(lst):
        for col in columns:
            try:
                if source_expr is not None and eval_in_scope is not None:
                    cell_value = eval_in_scope(replace_dollars_in_py_exp(col, [f'{source_expr}[{i}]']))
                else:
                    cell_value = eval_dollar_expr(col, item, eval_in_scope)
            except Exception:
                cell_value = None
            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                extra = (child_nesting_kwargs(config_fields, col, cell_value)
                         if getattr(cell_vis, 'SUPPORTS_NESTED_CONFIG', False) else {})
                children[f"{i}{CELL_KEY_SEP}{col}"] = cell_vis.init_model(
                    cell_value, get_visualizer, eval_in_scope=eval_in_scope, **extra)

    handled_keys = aggregate_handled_keys(children, _OWN_KEYS)
    return {
        'children': children,
        'handledKeys': handled_keys,
        'display_mode': 'table',
        'columns': columns,
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


def _render_column_search_row(col, index, model) -> str:
    """Render one column's search: [and|or] [comparison] (text).

    The text is written in column scope, where $ is the column value, $$ the row
    item and $$$ the array. Whatever the user types here is lifted and folded
    into the main search box, which does the actual filtering.
    """
    row = _column_search_row(model, col)
    open_dropdown = model.get('col_search_dropdown')

    compose_html = _render_column_search_chip(
        f'compose-{index}', row['compose'], COLUMN_SEARCH_COMPOSE,
        lambda v: repr(ColumnSearchComposeSelect(index=index, compose=v)),
        open_dropdown, 'col-search-compose',
        "How this composes with other columns' filters")
    # No tooltip on the operator: it shows the operator, and the box beside it
    # shows what it compares against.
    op_html = _render_column_search_chip(
        f'op-{index}', row['op'], COLUMN_SEARCH_OPS,
        lambda v: repr(ColumnSearchOpSelect(index=index, op=v)),
        open_dropdown, 'col-search-op',
        'Search Operation')

    input_event = (f"lambda e: ColumnSearchInput(index={index}, "
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
        f'<div class="col-search-area">'
        # f'<div class="col-search-label-row"><span>Filter</span> <span>({compose_html} with other columns)</span></div>'
        f'<div class="search-box-wrapper">'
        f'<input type="text" snc-input="{html.escape(input_event)}" '
        f'value="{html.escape(row["text"])}" '
        f'{focus_attrs}'
        f'placeholder="Column Search" '
        f'data-tooltip="$ is this column, $$ the item, $$$ the list" '
        f'spellcheck="false" '
        f'class="col-search-input search-box" />'
        f'<span class="col-search-chips">{op_html}</span>'
        f'<span class="col-search-chips-right">{compose_html}</span>'
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


def _render_column_tally(col, index, model, lst, eval_in_scope=None) -> str:
    """Render one column's tally: each distinct value and how many rows have it.

    Only computed while the menu is open, which is the one time the whole column
    is worth evaluating.
    """
    def title_html(expr):
        # The three headers are the section's grab handles: each hands over the
        # code for what it names, so what the user reads is what they can drag
        # into the file.
        return (f'<div class="col-tally-title"><span class="col-tally-title-text"'
                f'{py_exp_attrs(expr, imports=TALLY_IMPORTS)}>Tally</span></div>')

    source_expr = model.get('_source_expr')
    tally = _tally(_column_values(col, lst, model, eval_in_scope))
    if tally is None:
        return ''
    if not isinstance(tally, dict):
        # A tally too long to list is still a tally worth handing over; values
        # that can't be counted have no expression to give.
        note_expr = (_tally_counter_expr(col, source_expr)
                     if tally == TALLY_TOO_MANY and source_expr else None)
        return (f'<div class="col-tally">{title_html(note_expr)}'
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
    rows = []
    for text, count, literal in tally_rows:
        if not _tally_lists(model, text, count, extreme, eval_in_scope):
            continue
        label = html.escape(truncate_str(text, 60))
        if literal is None:
            # Nothing to compare against, so the count is all this row has to
            # offer, and a disabled box says so rather than looking clickable.
            rows.append(
                f'<div class="col-tally-row unselectable">'
                f'{_render_tally_check(False, disabled=True)}'
                f'<span class="col-tally-item snc-code">{label}</span>'
                f'<span class="col-tally-count">{count}</span>'
                f'</div>')
            continue
        checked = literal in selected
        toggle_event = repr(TallyItemToggle(index=index, literal=literal))
        count_expr = (_tally_row_count_expr(col, source_expr, literal, lst)
                      if source_expr else None)
        rows.append(
            f'<div class="col-tally-row{" checked" if checked else ""}" '
            f'snc-mouse-down="{html.escape(toggle_event)}">'
            f'{_render_tally_check(checked)}'
            f'<span class="col-tally-item snc-code">{label}</span>'
            f'<span class="col-tally-count"'
            f'{py_exp_attrs(count_expr, align="right")}>{count}</span>'
            f'</div>')

    # A way of reaching a value in a long list, so it reads before them -- and
    # before All and None, which it decides the reach of.
    filter_event = (f"lambda e: TallyFilterInput(index={index}, "
                    f"value=e.get('value', ''))")
    filter_html = (
        f'<input type="text" class="col-tally-filter search-box" '
        f'snc-input="{html.escape(filter_event)}" '
        f'value="{html.escape(filter_text)}" '
        f'placeholder="Find a value below" '
        f'data-tooltip="Show only values containing this text" '
        f'spellcheck="false" />'
    )
    # A second way of reaching a value: how often it occurs rather than how it
    # reads. The chip sits on top of the box the way the column search's
    # operator does, since it reads before the number the same way.
    count_event = (f"lambda e: TallyCountFilterInput(index={index}, "
                   f"value=e.get('value', ''))")
    count_html = (
        f'<div class="search-box-wrapper col-tally-count-box">'
        f'<input type="text" class="col-tally-count-filter search-box" '
        f'snc-input="{html.escape(count_event)}" '
        f'value="{html.escape(count_text)}" '
        f'placeholder="{"" if extreme_op else "Count"}" '
        + ('' if extreme_op
           else 'data-tooltip="Show only values with this many rows" ')
        + f'spellcheck="false"{" disabled" if extreme_op else ""} />'
        f'<span class="col-search-chips">'
        + _render_column_search_chip(
            f'tally-count-op-{index}', count_op, TALLY_COUNT_OPS,
            lambda v: repr(TallyCountOpSelect(index=index, op=v)),
            model.get('col_search_dropdown'), 'col-tally-count-op',
            label=_tally_count_op_label)
        + '</span></div>'
    )
    # Beside the filter box rather than among All / None / Exclude below it:
    # those say what the search filters on, while these only say which values
    # the menu puts in front of the user, and in what order.
    sort_html = _render_column_search_chip(
            f'tally-sort-{index}', sort, TALLY_SORTS,
            lambda v: repr(TallySortSelect(index=index, sort=v)),
            model.get('col_search_dropdown'), 'col-tally-sort',
            'Order the values are listed in', _tally_sort_label)
    controls_html = (
        f'<div class="col-tally-controls">'
        f'<span class="col-search-chip" '
        f'data-tooltip="Select every value shown" '
        f'snc-mouse-down="{html.escape(repr(TallySelectAll(index=index)))}">'
        f'All</span>'
        f'<span class="col-search-chip" '
        f'data-tooltip="Select none of the values shown" '
        f'snc-mouse-down="{html.escape(repr(TallySelectNone(index=index)))}">'
        f'None</span>'
        f'<span class="col-tally-exclude{" checked" if exclude else ""}" '
        f'data-tooltip="Filter to everything but the selected values" '
        f'snc-mouse-down="{html.escape(repr(TallyExcludeToggle(index=index)))}">'
        f'{_render_tally_check(exclude)} Exclude</span>'
        f'<div class="col-tally-sort-box">Sort:'
        f'{sort_html}'
        f'</div>{count_html}'
        f'</div>'
    )
    # The filter box stays even when it has hidden everything: it's the way
    # back to the values.
    if rows:
        body = (
            f'<div class="col-tally-list-header">'
            f'<span class="col-tally-item-header"'
            f'{py_exp_attrs(items_expr, imports=TALLY_IMPORTS)}>Items</span>'
            # Counts sits at the panel's right edge, so its tooltip reads
            # leftwards rather than off the side of the menu.
            f'<span class="col-tally-count-header"'
            f'{py_exp_attrs(counts_expr, imports=TALLY_IMPORTS, align="right")}'
            f'>Counts</span>'
            f'</div>'
            f'<div class="col-tally-list">{"".join(rows)}</div>'
        )
    else:
        body = '<div class="col-tally-note">No values match</div>'
    return (f'<div class="col-tally">{title_html(tally_expr)}'
            f'{filter_html}{controls_html}{body}'
            f'</div>')


def _render_column_compute(col, index, model, lst, eval_in_scope=None) -> str:
    """Render the Compute row of a column's ▾ menu, and its submenu when open.

    A flyout out of an already-hoisted panel, like the chip menus on the search
    row, and sharing their one open slot -- so opening this puts those away, and
    Escape and every way of leaving the column menu already close it.

    Only computed while the submenu is open, which is the one time the whole
    column is worth evaluating for an answer nobody has asked to keep.
    """
    dropdown_id = f'compute-{index}'
    is_open = model.get('col_search_dropdown') == dropdown_id
    toggle_event = repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id))
    panel_html = (_render_compute_panel(col, index, model, lst, eval_in_scope)
                  if is_open else '')
    return (
        f'<div class="snc-dropdown-trigger col-compute">'
        f'<div class="snc-dropdown-option col-compute-trigger'
        f'{" open" if is_open else ""}" '
        f'data-tooltip="Summarize this column" '
        f'snc-mouse-down="{html.escape(toggle_event)}">'
        f'<span class="snc-dropdown-option-label col-compute-title">Compute</span>'
        f'<span class="col-compute-arrow">▸</span>'
        f'</div>{panel_html}</div>'
    )


def _render_compute_panel(col, index, model, lst, eval_in_scope=None) -> str:
    """One row per aggregation: a checkbox, its name, a box for each hole in
    its expression, and the answer.

    The answer is there whether or not the row is checked -- glancing at the
    mean is the common case, and checking the box is only for keeping it.

    Under those, the rows that answer with a whole list (Unique, Tally), which
    write a line rather than keep a cell; and under those, the user's own
    aggregations, each a box holding the expression it is, with an empty one at
    the foot to write another in.
    """
    values = _column_values(col, lst, model, eval_in_scope)
    source_expr = model.get('_source_expr')
    values_expr = (None if source_expr is None
                   else _column_values_expr(col, source_expr))

    item_expr = _column_key_expr(col)

    rows = []
    for label, template, checked in _compute_rows(model, col):
        answer = _agg_value(template, values, eval_in_scope, lst, item_expr)
        # A question this column can't answer isn't worth checking -- but one
        # already checked stays clickable, or there'd be no way to uncheck it.
        unanswered = answer is NO_ANSWER
        inert = unanswered and not checked
        classes = ('col-compute-row' + (' checked' if checked else '')
                   + (' unselectable' if inert else ''))
        toggle_attr = '' if inert else (
            f' snc-mouse-down="'
            f'{html.escape(repr(ComputeToggle(index=index, expr=template)))}"')
        # The boxes and the answer sit outside the part that toggles: typing a
        # level, or dragging the answer out, is not a way of checking the row.
        holes = ''.join(
            f'<input type="text" class="col-compute-hole search-box" '
            f'snc-input="{html.escape(_compute_hole_event(index, template, i))}" '
            f'value="{html.escape(text)}" spellcheck="false" />'
            for i, text in enumerate(_agg_holes(template)))
        # Nothing to hand over when there is no answer, and nothing to name the
        # column by when the list has no source.
        code = (None if unanswered or source_expr is None
                else _agg_code(template,
                               _agg_column_expr(template, col, source_expr),
                               source_expr))
        rows.append(
            f'<div class="{classes}">'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(checked, disabled=inert)}'
            f'<span class="col-compute-name">{html.escape(label)}</span>'
            f'</span>{holes}'
            f'<span class="col-compute-preview"'
            f'{py_exp_attrs(code, imports=_agg_imports(template), align="right")}'
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
            f'"{html.escape(repr(ComputeCodeClick(index=index, expr=template)))}"')
        rows.append(
            f'<div class="col-compute-row col-compute-code'
            f'{"" if code else " unselectable"}"'
            f'{py_exp_attrs(code, imports=_agg_imports(template), align="right")}>'
            f'<span class="col-compute-toggle"{click_attr}>'
            f'<span class="col-compute-nocheck"></span>'
            f'<span class="col-compute-name">{html.escape(label)}</span>'
            f'</span></div>')

    rows.append('<div class="col-compute-sep"></div>')
    # A box names itself by where it sits rather than by what it says: the first
    # thing typed into the empty one adds a cell to the table, and a box found
    # again by its place in the list of everything focusable would lose the
    # typing to it.
    for i, template in enumerate(_compute_free_rows(model, col)):
        answer = _agg_value(template, values, eval_in_scope, lst, item_expr)
        unanswered = answer is NO_ANSWER
        # Through _agg_column_expr like the catalog's rows, so a box holding
        # something written the way Min Item is hands over what it computed.
        code = (None if unanswered or source_expr is None
                else _agg_code(template,
                               _agg_column_expr(template, col, source_expr),
                               source_expr))
        # A row of theirs is checked by being there at all, and unchecking is
        # how it is taken away: the expression is the only record of it, so
        # there would be nothing left to keep. The empty one is checking
        # nothing yet, and has nothing to take away.
        written = bool(template.strip())
        toggle_attr = '' if not written else (
            f' snc-mouse-down="'
            f'{html.escape(repr(ComputeToggle(index=index, expr=template)))}"')
        rows.append(
            f'<div class="col-compute-row col-compute-free'
            f'{" checked" if written else ""}">'
            f'<span class="col-compute-toggle"{toggle_attr}>'
            f'{_render_tally_check(written, disabled=not written)}</span>'
            f'<input type="text" class="col-compute-expr search-box" '
            f'snc-input="{html.escape(_compute_expr_event(index, template))}" '
            f'snc-focus-key="compute-free-{index}-{i}" '
            f'snc-key-down="{html.escape(repr(ComputeExprKeyDown()))}" '
            f'data-tooltip="{html.escape(COMPUTE_EXPR_TOOLTIP)}" '
            f'value="{html.escape(template)}" placeholder="Add aggregation" '
            f'spellcheck="false" />'
            f'<span class="col-compute-preview"'
            f'{py_exp_attrs(code, imports=_agg_imports(template), align="right")}'
            f'>{"" if unanswered else _agg_answer_html(template, answer)}</span>'
            f'</div>')

    return (f'<div class="snc-dropdown-panel flyout col-compute-panel" '
            f'snc-dropdown-align="flyout">{"".join(rows)}</div>')


def _compute_hole_event(index: int, template: str, hole: int) -> str:
    return (f"lambda e: ComputeHoleInput(index={index}, expr={template!r}, "
            f"hole={hole}, value=e.get('value', ''))")


def _compute_expr_event(index: int, template: str) -> str:
    """The box that holds a whole aggregation, wherever it is drawn: at the foot
    of the submenu, or as the label of the cell it made."""
    return (f"lambda e: ComputeExprInput(index={index}, expr={template!r}, "
            f"value=e.get('value', ''))")


def _render_column_menu(col, index, model, lst, eval_in_scope=None):
    """Render the rows of the per-column ▾ menu.

    State-driven (no data-hover-menu), so the TypeScript side hoists the panel out
    of the table's overflow container instead of cloning it on hover. Flyout-aligned:
    the panel's top-left corner sits at the ▾'s top-right, so the menu reads as
    belonging to the trigger rather than to the table row beneath it. The hoisting
    code mirrors it to the ▾'s left when there isn't room on the right.
    """
    remove_event = repr(RemoveColumnClick(index=index))
    rows = [
        f'<div class="snc-dropdown-option">'
        f'<span snc-mouse-down="{html.escape(remove_event)}" '
        f'class="snc-dropdown-option-label">Remove Column</span>'
        f'</div>',
        _render_column_compute(col, index, model, lst, eval_in_scope),
        _render_column_search_row(col, index, model),
        _render_column_tally(col, index, model, lst, eval_in_scope),
    ]
    return (
        f'<div class="snc-dropdown-panel flyout col-menu-panel" snc-dropdown-align="flyout">'
        + ''.join(rows)
        + '</div>'
    )


def _render_column_header(col, index, model, lst, eval_in_scope=None):
    """Render a normal column header with drag handle, column name, and ▾ menu."""
    click_event = repr(ColumnClick(index=index))
    drag_start_event = repr(ColumnDragStart(index=index))
    drag_over_event = repr(ColumnDragOver(index=index))
    drag_end_event = repr(ColumnDragEnd(index=index))

    drag_from = model.get('column_drag_from')
    drag_over = model.get('column_drag_over')
    is_drag_source = (drag_from == index)
    is_drag_target = (drag_from is not None and drag_over == index and drag_from != index)

    th_classes = ['snc-hover-hidden-parent', 'col-header']
    if is_drag_source:
        th_classes.append('col-drag-source')
    if is_drag_target:
        th_classes.append('col-drag-before' if drag_from > drag_over else 'col-drag-after')
    is_filtered = _column_search_active(model, col)
    if is_filtered:
        th_classes.append('col-filtered')

    source_expr = model.get('_source_expr')
    py_exp_attr = ('' if source_expr is None
                   else py_exp_attrs(_column_values_expr(col, source_expr)))

    # The ▾ trigger is pinned to the cell's right edge by .col-header-inner's flex
    # layout (which lives on an inner span, never on the <th>: display:flex on a
    # table cell drops it out of table layout and unsyncs header and body widths).
    menu_id = f'col-menu-{index}'
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
        f'{_render_column_menu(col, index, model, lst, eval_in_scope) if menu_open else ""}'
        f'</span>'
    )

    return (
        f'<th class="{" ".join(th_classes)}" '
        f'snc-mouse-move="{html.escape(drag_over_event)}" '
        f'snc-mouse-up="{html.escape(drag_end_event)}">'
        f'<span class="col-header-inner">'
        f'<span snc-mouse-down="{html.escape(drag_start_event)}" '
        f'data-tooltip="Drag to reorder" '
        f'class="col-handle snc-hover-hidden full-opacity-on-hover">⣿</span>'
        f'<span snc-mouse-down="{html.escape(click_event)}"'
        f'{py_exp_attr} '
        f'class="col-name">'
        f'{html.escape(strip_leading_dollar(col) or col)}</span>'
        f'{menu_html}'
        f'</span>'
        f'</th>'
    )


def _render_column_input(lst, model, get_visualizer, is_editing, editing_index=-1):
    """Render a column header with input for adding or editing a column name."""
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

    input_html = (
        f'<span class="snc-dropdown-trigger">'
        f'<input type="text" snc-input="{html.escape(input_event)}" '
        f'value="{html.escape(input_value)}" '
        f'placeholder="column name" '
        f'spellcheck="false"'
        f'{extra_attrs} '
        f'class="col-input" />'
        f'{suggestion_html}'
        f'</span>'
    )

    return f'<th>{input_html}</th>'


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

    Used to populate `data-action-expr` (action buttons) and `snc-py-exp`
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
    return py_exp_attrs(expr, imports=code_imports(expr), **kwargs)


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

    # Pick composes an expression out of the first match's parts, so it pins
    # first-match mode on: the toggle shows active but is inert until the user
    # leaves pick.
    if model.get('tool') == 'pick':
        first_match_toggle_html = (
            f'<span class="search-button active dimmed"'
            f' data-tooltip="Pick uses the first match only">'
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
        f' spellcheck="false"'
        f' class="search-box" />'
        f'{toggles_html}'
        f'</div>'
    )


def _render_action_buttons(model, lst, eval_in_scope=None):
    """Render the .action-buttons bar (no outer wrapper).

    Uses .action-button + .snc-dropdown-trigger / .snc-dropdown-panel /
    .snc-dropdown-option classes shared with the string visualizer. Each
    .action-button carries data-action-expr so the snc-action-tooltip system
    handles copy + drag-to-extract on hover; each .snc-dropdown-option
    carries snc-py-exp for the same purpose.
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

    def action_btn(label, action, enabled=True, title='', extra_classes=''):
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
    count_enabled = not (has_search and first)
    count_label = f'<span class="text">Count: {match_count}</span>'
    parts.append(action_btn(count_label, 'count', count_enabled, 'Count of matches'))

    # 2. Filter / Find One
    filter_lbl = (
        f'{ICONS["filter"]}<span class="text">Find One<span class="shortcut">⏎</span></span>'
        if first
        else f'{ICONS["filter"]}<span class="text">Filter<span class="shortcut">⏎</span></span>'
    )
    parts.append(action_btn(filter_lbl, 'filter', has_search, 'Filter matches (Enter)'))

    # 3. Loop dropdown (hover-menu, panel always rendered with data-hover-menu)
    loop_enabled = not (has_search and first) or pick_array
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
    join_enabled = (not (has_search and first)
                    or _is_plain_slice_search(model, eval_in_scope)
                    or pick_array)
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
    ('pick', nerd_font_icon('\U000F01BD'), 'Pick'),
]


def _render_tool_toolbar(model: dict) -> str:
    """Render the Normal/Pick toolbar for the upper-right corner.

    Pick is DIMMED (click-inert) without a search: it composes an expression out
    of the first match's parts, so there is nothing for it to work on.
    """
    current = model.get('tool', 'normal')
    if current not in ('normal', 'pick'):
        current = 'normal'
    search = model.get('search')
    has_search = search is not None and search != ''
    return render_tool_toolbar(
        _TOOL_TOOLBAR_TOOLS, current,
        lambda tool: repr(ToolSelect(tool=tool)),
        disabled=() if has_search else ('pick',))


def _pick_band_for_row(row: int, first_idx: int) -> str:
    """Which band a row falls in, relative to the first match."""
    if row < first_idx:
        return 'pre'
    if row == first_idx:
        return 'match'
    return 'post'


def _pick_edge_class(row: int, first_idx: int, n_rows: int) -> str:
    """Where a row sits within its band, for the rounded-rect CSS.

    A region spans every row of its band in one column, which is several <td>s
    in different <tr>s, so it cannot be one element. Instead each cell draws its
    own piece: the ends round off and cap the outline, the middles draw only
    side borders, and the stack reads as a single rounded rect.
    """
    band = _pick_band_for_row(row, first_idx)
    if band == 'pre':
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
    out = {}
    for region_id in region_ids:
        expr = _pick_region_expr(region_id, columns, source_expr)
        if not expr:
            continue
        ctx = dict(base)
        ctx['pick_expr'] = replace_dollars_in_py_exp(expr, ['item'])
        ctx['needs_index'] = _pick_needs_index(expr)
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


def _render_search_box(model, lst, eval_in_scope=None, small=False):
    """Render the full .search-div (search input row + action buttons row)."""
    input_html = _render_search_box_input(model, eval_in_scope)
    if small:
        action_buttons_html = ''
    else:
        action_buttons_html = _render_action_buttons(model, lst, eval_in_scope)
    preview_html = '' if small else _render_pick_preview(model, eval_in_scope)
    preview_row = (f'<div class="search-div-row">{preview_html}</div>'
                   if preview_html else '')
    return (
        f'<div class="search-div">'
        f'<div class="search-div-row">'
        f'<div class="search-replace-container">{input_html}</div>'
        f'</div>'
        f'{preview_row}'
        f'<div class="search-div-row">'
        f'{action_buttons_html}'
        f'</div>'
        f'</div>'
    )


def _agg_label_html(expr: str, index: int, level: int) -> str:
    """What names a cell: the catalog's word for the aggregation, or a box
    holding the expression when the aggregation is the user's own.

    There is no name for one of theirs but the expression itself, so the place
    it reads is the place to edit it -- the same box the submenu offers, and the
    same event behind it.

    It names itself by where it sits rather than by what it says, so that typing
    in it -- which rewrites what it says -- doesn't cost it the focus it is
    being typed into.
    """
    if not _agg_is_free(expr):
        return f'<span class="col-agg-label">{html.escape(_agg_label(expr))}</span>'
    # The cell around it is a drag handle, and a drag beginning inside the box
    # would take the selection the user was making with it.
    return (f'<input type="text" class="col-agg-label col-agg-expr" '
            f'snc-input="{html.escape(_compute_expr_event(index, expr))}" '
            f'snc-focus-key="agg-expr-{index}-{level}" '
            f'snc-key-down="{html.escape(repr(ComputeExprKeyDown()))}" '
            f'data-tooltip="{html.escape(COMPUTE_EXPR_TOOLTIP)}" '
            f'value="{html.escape(expr)}" size="{max(len(expr), 4)}" '
            f'draggable="false" spellcheck="false" />')


def _render_agg_cell(expr, index, level, values, values_expr, style_attr,
                     eval_in_scope=None) -> str:
    """One answer, in a cell of its own."""
    answer = _agg_value(expr, values, eval_in_scope)
    # A column whose values have changed out from under an aggregation says
    # nothing rather than dropping the cell the user put there.
    code = (None if answer is NO_ANSWER or values_expr is None
            else _agg_code(expr, values_expr))
    return (
        f'<td class="col-agg-cell"{style_attr}>'
        f'<div class="col-agg"{py_exp_attrs(code, imports=_agg_imports(expr))}>'
        f'{_agg_label_html(expr, index, level)}'
        f'<span class="col-agg-value">'
        f'{"" if answer is NO_ANSWER else _agg_answer_html(expr, answer)}</span>'
        f'</div></td>')


def _column_cell_value(col: str, item, eval_in_scope=None):
    """One row's value for a column, or NO_ANSWER when the column can't be read
    off that row."""
    try:
        return eval_dollar_expr(col, item, eval_in_scope)
    except Exception:
        return NO_ANSWER


def _render_agg_item_row(expr, ci, level, columns, lst, style_attr,
                         eval_in_scope=None, source_expr=None) -> str:
    """A row aggregation's row: the row of the list a column's Min Item or Max
    Item picked out, drawn across every column with its index beside it.

    The row comes out of the aggregation's own expression and its index out of
    the list's own `.index` of that row, so the values on screen and the code
    each cell hands over name the same row of the list. The column's values are
    never gathered at all: `min` with a key reads them one row at a time.

    Only the column that asked is labelled. The other cells are that row's
    values, and a "Min Item" over each of them would read as a claim that each
    was least in its own column.
    """
    item_expr = _column_key_expr(columns[ci])
    item = _agg_value(expr, None, eval_in_scope, lst, item_expr)
    idx = _agg_row_index(lst, item)
    # Nothing to hand over when the aggregation has no row to point at, and
    # nothing to name the list by when it has no source.
    item_code = (None if item is NO_ANSWER or source_expr is None
                 else _agg_code(expr, item_expr, source_expr))
    idx_code = (None if idx is NO_ANSWER or item_code is None
                else _agg_row_index_code(item_code, source_expr))

    cells = [f'<td class="row-index col-agg-cell"{style_attr}>'
             f'<span{py_exp_attrs(idx_code, imports=_agg_imports(expr))}>'
             f'{"" if idx is NO_ANSWER else _format_agg_value(idx)}'
             f'</span></td>']
    for cj, col in enumerate(columns):
        value = (NO_ANSWER if item is NO_ANSWER
                 else _column_cell_value(col, item, eval_in_scope))
        code = (None if item_code is None or value is NO_ANSWER
                else replace_dollars_in_py_exp(col, [item_code]))
        label = '' if cj != ci else _agg_label_html(expr, ci, level)
        cells.append(
            f'<td class="col-agg-cell"{style_attr}>'
            f'<div class="col-agg"{py_exp_attrs(code, imports=_agg_imports(expr))}>'
            f'{label}<span class="col-agg-value">'
            f'{"" if value is NO_ANSWER else _format_agg_value(value)}</span>'
            f'</div></td>')
    return f'<tr class="col-agg-row col-agg-item-row">{"".join(cells)}</tr>'


def _agg_layout(columns, model) -> List[tuple]:
    """The rows of answers under the table, top to bottom.

    A row of cells is `('cells', [expr or None per column])`; a row aggregation
    takes a row to itself and is `('item', column index, expr)`.

    The cells come first and the rows of the list under them, because an answer
    about a column reads as part of that column while a row of the list reads
    as part of the list -- and because a column asked for its aggregations in
    menu order, where Min Item and Max Item are last anyway.
    """
    stacks = [_column_computes(model, col) for col in columns]
    cell_stacks = [[expr for expr in stack if not _agg_is_row(expr)]
                   for stack in stacks]
    depth = max((len(stack) for stack in cell_stacks), default=0)
    levels: List[tuple] = [
        ('cells', [stack[level] if level < len(stack) else None
                   for stack in cell_stacks])
        for level in range(depth)]
    levels += [('item', ci, expr)
               for ci, stack in enumerate(stacks) for expr in stack
               if _agg_is_row(expr)]
    return levels


def _render_agg_rows(columns, model, lst, eval_in_scope=None,
                     source_expr=None) -> str:
    """The rows of answers under the table, or nothing when no column has asked
    for one.

    Real rows of the table, because that is what keeps a cell the same width as
    the column it belongs to. A row of cells is not a row of the list, though:
    no index, and nothing in it to pick. A row aggregation's row reads like one
    -- it is one -- but there is still nothing in it to pick.

    They pin to the bottom of the scrollport the way the header pins to the
    top, and sticky can't stack itself, so each row is told how far above the
    bottom to stop. A column with fewer answers than the deepest one blanks the
    rows below its last: an empty cell has nothing to pin over the rows it
    would otherwise cover.
    """
    levels = _agg_layout(columns, model)
    if not levels:
        return ''

    # Once per column, however many answers are asked of it -- and not at all
    # for a column that only picks rows, since a key reads them one at a time.
    asked = [any(level[0] == 'cells' and level[1][ci] is not None
                 for level in levels)
             for ci in range(len(columns))]
    reads = [(_column_values(col, lst, model, eval_in_scope),
              None if source_expr is None else _column_values_expr(col,
                                                                   source_expr))
             if asked[ci] else (None, None)
             for ci, col in enumerate(columns)]

    rows = []
    for level, spec in enumerate(levels):
        below = len(levels) - 1 - level
        style_attr = ('' if below == 0 else
                      f' style="bottom: calc({below} * '
                      f'var(--snc-agg-row-height))"')
        if spec[0] == 'item':
            _, ci, expr = spec
            rows.append(_render_agg_item_row(expr, ci, level, columns, lst,
                                             style_attr, eval_in_scope,
                                             source_expr))
            continue
        cells = []
        for ci, expr in enumerate(spec[1]):
            if expr is None:
                cells.append('<td class="col-agg-blank"></td>')
            else:
                values, values_expr = reads[ci]
                cells.append(_render_agg_cell(expr, ci, level, values,
                                              values_expr, style_attr,
                                              eval_in_scope))
        rows.append(f'<tr class="col-agg-row">'
                    f'<td class="row-index"></td>{"".join(cells)}</tr>')
    return ''.join(rows)


def _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False):
    children = model.get('children', {})
    columns = model.get('columns', [])
    focused_child = model.get('focused_child')

    max_column_width = round(800 / sqrt(max(len(columns), 1)))

    search = model.get('search')
    has_search = search is not None and search != ''
    # Pick mode is first-match-only, and there is nothing to pick out of a small
    # (unfocused) preview or a table with no search.
    pick_mode = (model.get('tool') == 'pick') and has_search and not small
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

    actual_max_height = (max_height or 400) - 32
    # The aggregation rows are part of what the table has to show, so a short
    # one doesn't get a scrollbar for the sake of the answers under it.
    agg_rows = len(_agg_layout(columns, model))
    actual_min_height = min(22 * (len(lst) + 1 + agg_rows), actual_max_height)

    actual_max_width = f' max-width:{max_width}px;' if max_width is not None else ''

    table_div_style = f'min-height: {actual_min_height}px; max-height: {actual_max_height}px;{actual_max_width}'

    key_handler = repr(ColumnKeyDown())
    small_class = ' small' if small else ''
    # Driven by pick_mode, not the raw model value: the pick styling strips the
    # cell borders, so it must only apply when regions are actually drawn.
    tool_class = f' {"pick" if pick_mode else "normal"}-tool-selected' if not small else ''
    strs = [
        f'<div tabindex="0" snc-key-down="{html.escape(key_handler)}" '
        f'class="visualizer-container list-visualizer{small_class}{tool_class}">'
    ]
    # The tool toolbar only makes sense on the focused visualizer; in small mode
    # there is no room for it and it would compete with the real focus.
    if not small:
        strs.append(_render_tool_toolbar(model))
    strs.append(f'<div class="list-table-scroll" style="{table_div_style}">')
    strs.append('<table><tr>')
    strs.append('<th></th>')

    for ci, col in enumerate(columns):
        if model.get('editing_column_index') == ci:
            strs.append(_render_column_input(lst, model, get_visualizer, is_editing=True, editing_index=ci))
        else:
            strs.append(_render_column_header(col, ci, model, lst, eval_in_scope))

    if model.get('adding_column'):
        strs.append(_render_column_input(lst, model, get_visualizer, is_editing=False))

    add_event = repr(AddColumnClick())
    strs.append(
        f'<th class="snc-hover-hidden-parent col-add" '
        f'snc-mouse-down="{html.escape(add_event)}" '
        f'data-tooltip="Add column">'
        f'<span class="col-add-icon snc-hover-hidden full-opacity-on-hover">+</span>'
        f'</th>'
    )

    strs.append('</tr>')

    source_expr = model.get('_source_expr')

    scroll_to = model.get('_scroll_to_match', False)
    first_match_row = min(matched_indices) if matched_indices else None

    # Pick mode replaces the row-match / row-dim striping with a grid of
    # pickable regions: three row bands (before the match, the match, after)
    # crossed with the row-index column and every configured column.
    pick_here = pick_mode and first_match_row is not None
    pick_exprs = {}
    if pick_here and source_expr is not None:
        pick_exprs = _pick_standalone_exprs(
            model, source_expr, eval_in_scope,
            _pick_region_ids(columns, first_match_row, len(lst)))

    def pick_overlay(row, col_id):
        if not pick_here:
            return ''
        return _render_pick_region(row, col_id, model, first_match_row,
                                   len(lst), pick_exprs)

    for i, item in enumerate(lst):
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

        strs.append(f'<tr{row_class_attr}{scroll_attr}><td class="row-index">')
        strs.append(str(i))
        strs.append(pick_overlay(i, PICK_IDX_COLUMN))
        strs.append('</td>')

        for ci, col in enumerate(columns):
            composite_key = f"{i}{CELL_KEY_SEP}{col}"
            try:
                if source_expr is not None and eval_in_scope is not None:
                    cell_value = eval_in_scope(replace_dollars_in_py_exp(col, [f'{source_expr}[{i}]']))
                else:
                    cell_value = eval_dollar_expr(col, item, eval_in_scope)
            except Exception:
                cell_value = None

            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                cell_model = children.get(composite_key)
                if cell_model is None:
                    extra = (child_nesting_kwargs(model, col, cell_value)
                             if getattr(cell_vis, 'SUPPORTS_NESTED_CONFIG', False) else {})
                    cell_model = cell_vis.init_model(cell_value, get_visualizer,
                                                     eval_in_scope=eval_in_scope, **extra)
                child_small = (composite_key != focused_child)

                cell_expr = None
                if source_expr is not None:
                    cell_expr = replace_dollars_in_py_exp(col, [f'{source_expr}[{i}]'])

                # The parent doesn't wrap children for drag: each is handed its
                # access-path expression and decides for itself, so a child with
                # its own handles keeps them instead of being covered by one.
                child_var_and_exp = (None, cell_expr) if cell_expr else None
                if hasattr(cell_vis, 'visualize_els'):
                    cell_htmls = cell_vis.visualize_els(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small, var_and_exp=child_var_and_exp)
                else:
                    cell_htmls = [cell_vis.visualize(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small, var_and_exp=child_var_and_exp)]

                strs.append('<td>')
                strs.append(wrap_child_prefix(composite_key))
                strs.extend(cell_htmls)
                strs.append(wrap_child_suffix)
                strs.append(pick_overlay(i, f'col_{ci}'))
                strs.append('</td>')
            else:
                strs.append(f'<td>{pick_overlay(i, f"col_{ci}")}</td>')

        strs.append('</tr>')

    strs.append(_render_agg_rows(columns, model, lst, eval_in_scope, source_expr))

    strs.append('</table>')
    strs.append('</div>')

    if not small:
        strs.append(_render_search_box(model, lst, eval_in_scope, small=False))

    strs.append('</div>')
    return ''.join(strs)


def visualize(lst: list, model: dict, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, var_and_exp=None):
    # Depth-capped leaf: render a plain truncated repr instead of a nested table.
    if model.get('_too_deep'):
        return f'<span class="small">{html.escape(truncate_str(repr(lst), 200))}</span>'

    # No whole-area drag handle in either size: the cells and column headers
    # carry their own snc-py-exp, and a handle wrapping all of them would claim
    # every hover in between. Only the generic visualizers self-wrap.
    return _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small)


def _table_child_value_getter(key, lst, eval_in_scope=None, source_expr=None):
    row_key, field_key = key.split(CELL_KEY_SEP, 1)
    idx = int(row_key)
    if source_expr is not None and eval_in_scope is not None:
        return eval_in_scope(replace_dollars_in_py_exp(field_key, [f'{source_expr}[{idx}]']))
    return eval_dollar_expr(field_key, lst[idx], eval_in_scope)


def update(event, var_and_exp, model: Any, value, get_visualizer=None, eval_in_scope=None) -> Tuple[Any, List[Any]]:
    if event is None or not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])

    if model is None:
        model = {'children': {}, 'handledKeys': [], 'display_mode': 'table', 'columns': ['$'],
                 '_slot_children': {}, '_config_root_type': None,
                 '_config_root_dotfile': None, '_config_path': [],
                 **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS}

    try:
        make_python_event = eval(event['pythonEventStr'])
    except Exception:
        return (model, [])

    event_json = event.get('eventJSON', {})
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event

    if msg is None:
        return (model, [])

    if isinstance(msg, ChildEvent):
        row_key, cell_col = msg.child_key.split(CELL_KEY_SEP, 1)
        new_model, commands = route_child_event(
            event, model, value,
            child_value_getter=lambda key: _table_child_value_getter(key, value, eval_in_scope, model.get('_source_expr')),
            get_visualizer=get_visualizer,
            # The cell's value is bound to a name for the child, so the code it
            # generates is dollar-free; the column expression goes back in below.
            var_and_exp=(None, CHILD_SOURCE_BINDER),
            eval_in_scope=eval_in_scope,
        )
        # A column stays row-generic (the cell_col dollar expression); anything
        # bound for the clipboard names this row concretely, since the user
        # pastes it into the editor as-is.
        src = model.get('_source_expr')
        concrete_cell = (replace_dollars_in_py_exp(cell_col, [f'{src}[{row_key}]'])
                         if src else cell_col)
        commands = [nest_child_command(cmd, cell_col, concrete_cell) for cmd in commands]

        filtered_commands: List[Any] = []
        type_key = _get_item_type_key(value) if value else None
        for cmd in commands:
            if isinstance(cmd, tuple) and len(cmd) in (2, 3):
                new_model['columns'].append(cmd[1])
                if type_key:
                    _save_slots(new_model)
            else:
                filtered_commands.append(cmd)
        new_model['handledKeys'] = aggregate_handled_keys(new_model.get('children', {}), _OWN_KEYS)
        return (new_model, filtered_commands)

    commands: List[Any] = []
    type_key = _get_item_type_key(value) if value else None
    model['_scroll_to_match'] = False
    # A one-shot request, cleared here so it can't pull focus into a column
    # search box on some later, unrelated render.
    model['_col_search_focus'] = False

    match msg:
        case AddColumnClick():
            _close_column_menus(model)
            model['adding_column'] = True
            model['column_input_value'] = ''
            model['editing_column_index'] = None

        case ColumnInput(value=val):
            model['column_input_value'] = val
            if val and get_visualizer is not None:
                suggestions = _get_column_suggestions(value, get_visualizer, model.get('columns', []), val)
                model['selected_suggestion_index'] = 0 if suggestions else None
            else:
                model['selected_suggestion_index'] = None

        case ColumnSelect(name=name):
            if model.get('adding_column'):
                model['columns'].append(name)
                model['adding_column'] = False
                model['column_input_value'] = ''
                if type_key:
                    _save_slots(model)
            elif model.get('editing_column_index') is not None:
                idx = model['editing_column_index']
                if 0 <= idx < len(model['columns']):
                    old_name = model['columns'][idx]
                    model['columns'][idx] = name
                    if old_name != name:
                        _rename_column_children(model, old_name, name)
                        _rename_column_search(model, old_name, name)
                        _rename_column_compute(model, old_name, name)
                        _recompose_search(model, eval_in_scope)
                model['editing_column_index'] = None
                model['column_input_value'] = ''
                if type_key:
                    _save_slots(model)

        case ColumnClick(index=idx):
            _close_column_menus(model)
            detail = event_json.get('detail', 1)
            if detail >= 2:
                if 0 <= idx < len(model['columns']):
                    model['editing_column_index'] = idx
                    model['column_input_value'] = model['columns'][idx]
                    model['adding_column'] = False

        case RemoveColumnClick(index=idx):
            _close_column_menus(model)
            if 0 <= idx < len(model['columns']):
                removed_col = model['columns'].pop(idx)
                _remove_column_children(model, removed_col)
                _remove_column_search(model, removed_col)
                _remove_column_compute(model, removed_col)
                _recompose_search(model, eval_in_scope)
                if model.get('editing_column_index') is not None:
                    if model['editing_column_index'] == idx:
                        model['editing_column_index'] = None
                        model['column_input_value'] = ''
                    elif model['editing_column_index'] > idx:
                        model['editing_column_index'] -= 1
                if type_key:
                    _save_slots(model)

        case ColumnDragStart(index=idx):
            _close_column_menus(model)
            if 0 <= idx < len(model['columns']):
                model['column_drag_from'] = idx
                model['column_drag_over'] = idx

        case ColumnDragOver(index=idx):
            if model.get('column_drag_from') is not None:
                if event_json.get('buttons', 0) == 0:
                    model['column_drag_from'] = None
                    model['column_drag_over'] = None
                else:
                    model['column_drag_over'] = idx

        case ColumnDragEnd(index=idx):
            drag_from = model.get('column_drag_from')
            if drag_from is not None and 0 <= drag_from < len(model['columns']):
                target = idx
                if drag_from != target:
                    col = model['columns'].pop(drag_from)
                    model['columns'].insert(target, col)
                    # Column order is term order in the composed search.
                    _recompose_search(model, eval_in_scope)
                    if type_key:
                        _save_slots(model)
            model['column_drag_from'] = None
            model['column_drag_over'] = None

        case ColumnKeyDown():
            key = event_json.get('key', '')
            is_input_active = model.get('adding_column') or model.get('editing_column_index') is not None

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
                        model['columns'].append(commit_val)
                        if type_key:
                            _save_slots(model)
                    model['adding_column'] = False
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None
                elif model.get('editing_column_index') is not None:
                    idx = model['editing_column_index']
                    if commit_val and 0 <= idx < len(model['columns']):
                        old_name = model['columns'][idx]
                        model['columns'][idx] = commit_val
                        if old_name != commit_val:
                            _rename_column_children(model, old_name, commit_val)
                            _rename_column_search(model, old_name, commit_val)
                            _rename_column_compute(model, old_name, commit_val)
                            _recompose_search(model, eval_in_scope)
                        if type_key:
                            _save_slots(model)
                    model['editing_column_index'] = None
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
                    elif model.get('search'):
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
                    model['editing_column_index'] = None
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None

        case ColumnSearchInput(index=idx, value=val):
            col = _column_at(model, idx)
            if col is not None:
                _set_column_search(model, col, text=val)
                _recompose_search(model, eval_in_scope)

        case ColumnSearchOpSelect(index=idx, op=op):
            col = _column_at(model, idx)
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

        case ColumnSearchComposeSelect(index=idx, compose=compose):
            col = _column_at(model, idx)
            if col is not None and compose in COLUMN_SEARCH_COMPOSE:
                _set_column_search(model, col, compose=compose)
                model['col_search_dropdown'] = None
                _recompose_search(model, eval_in_scope)

        # Compute leaves the menu open for the same reason the tally does:
        # checking several aggregations in a row is the whole point.
        case ComputeToggle(index=idx, expr=expr):
            col = _column_at(model, idx)
            if col is not None:
                exprs = _column_computes(model, col)
                if expr in exprs:
                    exprs.remove(expr)
                else:
                    exprs.append(expr)
                _set_column_computes(model, col, exprs)

        case ComputeHoleInput(index=idx, expr=expr, hole=hole, value=text):
            col = _column_at(model, idx)
            if col is not None:
                exprs = _column_computes(model, col)
                edited = _agg_set_hole(expr, hole, text)
                if expr in exprs:
                    # In place, so the cell the user is typing at stays where
                    # it was in the column's stack.
                    exprs[exprs.index(expr)] = edited
                else:
                    # Typing a level into a row that isn't checked is a way of
                    # asking for that percentile.
                    exprs.append(edited)
                _set_column_computes(model, col, exprs)

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

        case ComputeExprInput(index=idx, expr=expr, value=text):
            col = _column_at(model, idx)
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
        case ComputeCodeClick(index=idx, expr=expr):
            col = _column_at(model, idx)
            source_expr = model.get('_source_expr')
            if col is not None and source_expr is not None:
                _close_column_menus(model)
                code = _agg_code(expr, _column_values_expr(col, source_expr))
                # What the line needs imported is the expression's own, declared
                # where every other aggregation declares it rather than read back
                # out of the text.
                commands.append(new_code_command(
                    (_compute_code_name(expr, source_expr), code),
                    lambda _code: _agg_imports(expr)))

        # The tally leaves the column menu open: picking several values in a row
        # is the whole point of it.
        case TallyItemToggle(index=idx, literal=literal):
            col = _column_at(model, idx)
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
        case TallySelectAll(index=idx):
            col = _column_at(model, idx)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                rows = _column_tally_rows(col, model, value, eval_in_scope)
                order = [lit for _text, _count, lit in rows if lit is not None]
                shown = _tally_shown(model, rows, eval_in_scope)
                kept = [lit for lit in selected if lit not in set(shown)]
                _write_tally_selection(
                    model, col, _in_tally_order(kept + shown, order), exclude)
                _recompose_search(model, eval_in_scope)

        case TallySelectNone(index=idx):
            col = _column_at(model, idx)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                shown = set(_tally_shown(
                    model, _column_tally_rows(col, model, value, eval_in_scope),
                    eval_in_scope))
                _write_tally_selection(
                    model, col, [lit for lit in selected if lit not in shown],
                    exclude)
                _recompose_search(model, eval_in_scope)

        case TallyExcludeToggle(index=idx):
            col = _column_at(model, idx)
            if col is not None:
                selected, exclude = _tally_selection(_column_search_row(model, col))
                # Rewriting the same selection the other way round flips the
                # operator and leaves the values alone.
                _write_tally_selection(model, col, selected, not exclude)
                _recompose_search(model, eval_in_scope)

        case TallyFilterInput(index=idx, value=val):
            # Display only: it decides which rows the menu lists, and never
            # what the column search says.
            if _column_at(model, idx) is not None:
                model['tally_filter'] = val

        case TallySortSelect(index=idx, sort=sort):
            # Display only too, though the order does reach the search: a
            # selection is written in the order it was listed in, so it reads
            # the way the list the user clicked through read.
            if _column_at(model, idx) is not None and sort in TALLY_SORTS:
                model['tally_sort'] = sort
                model['col_search_dropdown'] = None

        case TallyCountFilterInput(index=idx, value=val):
            # Display only, like the box beside it: which rows the menu lists,
            # never what the column search says.
            if _column_at(model, idx) is not None:
                model['tally_count_filter'] = val

        case TallyCountOpSelect(index=idx, op=op):
            if _column_at(model, idx) is not None and op in TALLY_COUNT_OPS:
                model['tally_count_op'] = op
                model['col_search_dropdown'] = None

        case ColumnSearchDropdownToggle(dropdown_id=did):
            current = model.get('col_search_dropdown')
            model['col_search_dropdown'] = None if current == did else did

        case SearchBoxInput(value=val):
            model['search'] = val if val else None
            model['_scroll_to_match'] = True
            if not model['search'] and model.get('tool') == 'pick':
                # Pick builds an expression out of the first match's parts, so
                # clearing the search leaves it nothing to stand on.
                model['tool'] = 'normal'
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
                                model['linked_has_assignment'] = bool(result[0])
                                model['last_linked_expr'] = result[1]
                                model['auto_linked_once'] = True

        case Unlink():
            # Stash the action so the chain icon can resume it on relink.
            model['unlinked_action'] = model.get('linked_action')
            model['linked_action'] = None
            model['linked_source_expr'] = None
            model['linked_has_assignment'] = None
            model['last_linked_expr'] = None

        case Relink(mode=mode, text=text):
            handle_relink(_LINK_CONFIG, mode, text, var_and_exp, model, commands,
                          eval_in_scope=eval_in_scope)

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
    model['linked_has_assignment'] = bool(suggest_name)
    model['last_linked_expr'] = expr
    model['auto_linked_once'] = True
    commands.append(new_code_command(result, code_imports))
