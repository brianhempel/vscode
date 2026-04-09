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
   - Auto-detects columns from item fields, or defaults to ['^'] (the item)
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

3. Default: ['^'] (the item itself)
   - Used when items lack fields (strings, ints, mixed types, empty lists)
   - Users can add computed columns via the (+) button
================================================================================
"""

import ast
import html
import random
import re
from dataclasses import dataclass
from math import sqrt
from typing import Any, List, Tuple

from visualizer_utils import (
    ChildEvent, EditorTextSelect, Unlink,
    route_child_event, aggregate_handled_keys,
    wrap_child_prefix, wrap_child_suffix,
    strip_leading_caret, eval_caret_expr, replace_caret_in_py_exp,
    load_dotfile_list, save_dotfile_list,
    get_full_class_name,
    BLUE, GRAY, GRAY_HALF_ALPHA, INPUT_BG, INPUT_BORDER, SUGGESTION_BG, SELECTED_BG,
)

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

# === Command types ===

@dataclass(frozen=True, slots=True)
class CopyToClipboard:
    text: str

@dataclass(frozen=True, slots=True)
class ChangeSelectedText:
    text: str


# === Dotfile operations ===

COLUMN_DOTFILE_NAME = '.snc_list_columns.json'


def _get_item_type_key(lst):
    """Return a type key for the items in the list (based on first item's class)."""
    if not lst:
        return None
    return get_full_class_name(lst[0])


def load_columns_from_dotfile(type_key: str):
    """Load saved columns for an item type from the dotfile. Returns list or None."""
    return load_dotfile_list(COLUMN_DOTFILE_NAME, type_key)


def save_columns_to_dotfile(type_key: str, columns: list):
    """Save columns for an item type to the dotfile, preserving other types' entries."""
    save_dotfile_list(COLUMN_DOTFILE_NAME, type_key, columns)


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

_IMPLICIT_CARET_RE = re.compile(
    r'^\s*(?:'
    r'>=|<=|!=|==|>|<'
    r'|in\b'
    r'|not\s+in\b'
    r'|is\s+not\b'
    r'|is\b'
    r'|\.'
    r')'
)


def needs_implicit_caret(search: str) -> bool:
    """True if search text starts with a binary operator, meaning ^ should be prepended."""
    return bool(_IMPLICIT_CARET_RE.match(search))


def _is_valid_python_expression(s: str) -> bool:
    try:
        ast.parse(s, mode='eval')
        return True
    except SyntaxError:
        pass
    if '^' in s:
        try:
            ast.parse(replace_caret_in_py_exp(s, '_crt_'), mode='eval')
            return True
        except SyntaxError:
            pass
    return False


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


def _is_list_of_ints(val) -> bool:
    return isinstance(val, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in val)


def _is_list_of_int_pairs(val) -> bool:
    return (isinstance(val, list)
            and len(val) > 0
            and all(isinstance(x, (tuple, list)) and len(x) == 2
                    and isinstance(x[0], int) and not isinstance(x[0], bool)
                    and isinstance(x[1], int) and not isinstance(x[1], bool)
                    for x in val))


def _get_search_context(model: dict, var_and_exp=None,
                        *, source_expr: str = None, eval_in_scope=None) -> dict | None:
    """Build search context dict from model + source info.

    Returns None if no valid search or source info.
    """
    search = model.get('search')
    if not search:
        return None

    if source_expr:
        var_name = source_expr
        suggest_base = source_expr
    else:
        if var_and_exp is None:
            return None
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else f"({expr})"
        suggest_base = var_name if var_name else "result"

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
                'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
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
            'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
            'is_slice': True, 'slice_start': slice_start_raw, 'slice_stop': slice_stop_raw,
            'is_index': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': True,
        }

    expr_text = term
    if needs_implicit_caret(expr_text):
        expr_text = '^ ' + expr_text.lstrip() if not expr_text.lstrip().startswith('.') else '^' + expr_text.lstrip()

    _eval = eval_in_scope or (lambda c: ast.literal_eval(c))
    try:
        val = _eval(expr_text)
    except Exception:
        val = None

    if isinstance(val, int) and not isinstance(val, bool):
        return {
            'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
            'is_index': True, 'index_expr': expr_text,
            'is_slice': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': True,
        }

    if _is_list_of_ints(val):
        return {
            'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
            'is_multi_index': True, 'indices_expr': expr_text,
            'is_index': False, 'is_slice': False, 'is_predicate': False,
            'is_first': first,
        }

    if _is_list_of_int_pairs(val):
        return {
            'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
            'is_multi_pair': True, 'pairs_expr': expr_text,
            'is_index': False, 'is_slice': False, 'is_predicate': False, 'is_multi_index': False,
            'is_first': first,
        }

    predicate_with_caret = expr_text
    if needs_implicit_caret(search):
        if search.lstrip().startswith('.'):
            predicate_with_caret = '^' + search.lstrip()
        else:
            predicate_with_caret = '^ ' + search.lstrip()
    else:
        predicate_with_caret = search

    predicate_expr = replace_caret_in_py_exp(predicate_with_caret, 'item')

    return {
        'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
        'is_predicate': True, 'predicate_expr': predicate_expr,
        'is_index': False, 'is_slice': False, 'is_multi_index': False,
        'is_first': first,
    }


def _get_whole_list_context(model: dict, var_and_exp=None,
                            *, source_expr: str = None) -> dict | None:
    """Build a context dict representing the whole list (no search filter)."""
    if source_expr:
        var_name = source_expr
        suggest_base = source_expr
    else:
        if var_and_exp is None:
            return None
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else f"({expr})"
        suggest_base = var_name if var_name else "result"

    return {
        'source_expr': source_expr, 'var_name': var_name, 'suggest_base': suggest_base,
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
        model['search'] = re.sub(r'\bitem\b', '^', pred)
    model['first_match'] = bool(ctx.get('is_first'))


# === Code generation ===

_SUGGEST_SUFFIXES = {
    'any': 'any', 'all': 'all', 'count': 'count',
    'filter': 'filtered', 'find_indices': 'indices',
    'join': 'joined',
}
_STATEMENT_ACTIONS = frozenset({'loop', 'loop_no_idx', 'loop_orig_idx', 'loop_new_idx', 'if_any', 'if_all'})


def _suggest_name_for_action(action: str, ctx: dict) -> str | None:
    if action in _STATEMENT_ACTIONS:
        return None
    base = ctx.get('suggest_base') or 'result'
    has_var = bool(ctx.get('var_name'))
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
                code = f'for item in [{src}[i] for i in {indices}]:\n    pass'
            case 'loop_orig_idx':
                code = f'for i in {indices}:\n    pass'
            case 'loop_new_idx':
                code = f'for i, item in enumerate({src}[i] for i in {indices}):\n    pass'
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
                code = f'for item in [{iter_expr}]:\n    pass'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate([{iter_expr}]):\n    pass'
            case 'loop_new_idx':
                code = f'for i, item in enumerate([{iter_expr}]):\n    pass'
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
                code = f'for item in [{iter_expr}]:\n    pass'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate([{iter_expr}]):\n    pass'
            case 'loop_new_idx':
                code = f'for i, item in enumerate([{iter_expr}]):\n    pass'
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
        match action:
            case 'filter':
                if first:
                    code = f'next((item for item in {src} if {pred}), None)'
                else:
                    code = f'[item for item in {src} if {pred}]'
            case 'loop_no_idx':
                code = f'for item in (item for item in {src} if {pred}):\n    pass'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate({src}):\n    if {pred}:\n        pass'
            case 'loop_new_idx':
                code = f'for i, item in enumerate(item for item in {src} if {pred}):\n    pass'
            case 'any':
                code = f'any({pred} for item in {src})'
            case 'all':
                code = f'all({pred} for item in {src})'
            case 'if_any':
                code = f'if any({pred} for item in {src}):\n    pass'
            case 'if_all':
                code = f'if all({pred} for item in {src}):\n    pass'
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
                code = f'for item in {src}:\n    pass'
            case 'loop_orig_idx':
                code = f'for i, item in enumerate({src}):\n    pass'
            case 'loop_new_idx':
                code = f'for i, item in enumerate({src}):\n    pass'
            case 'any':
                code = f'any({src})'
            case 'all':
                code = f'all({src})'
            case 'if_any':
                code = f'if any({src}):\n    pass'
            case 'if_all':
                code = f'if all({src}):\n    pass'
            case 'count':
                code = f'sum(1 for item in {src} if item)'
            case 'join':
                sep = ctx.get('join_separator', "''")
                code = f'{sep}.join(str(item) for item in {src})'
            case _:
                return None
        return (_suggest_name_for_action(action, ctx), code)

    return None


def _emit_linked_update(expr: str, model: dict, commands: list) -> None:
    """Append a ChangeSelectedText command only if the full text is valid Python."""
    text = (model.get('linked_prefix') or '') + expr
    try:
        ast.parse(text)
    except SyntaxError:
        return
    commands.append(ChangeSelectedText(text=text))


# === Matching indices for highlighting ===

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
    if needs_implicit_caret(expr_text):
        if expr_text.lstrip().startswith('.'):
            expr_text = '^' + expr_text.lstrip()
        else:
            expr_text = '^ ' + expr_text.lstrip()

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

    predicate_with_caret = search
    if needs_implicit_caret(search):
        if search.lstrip().startswith('.'):
            predicate_with_caret = '^' + search.lstrip()
        else:
            predicate_with_caret = '^ ' + search.lstrip()

    predicate_expr = replace_caret_in_py_exp(predicate_with_caret, '_item')

    matched = []
    for i, _item in enumerate(lst):
        try:
            if eval(predicate_expr):
                matched.append(i)
        except Exception:
            pass
    return matched


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
    return [f'^[{i}]' for i in range(len(value))]


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
}

_SEARCH_DEFAULTS = {
    'search': None,
    'first_match': False,
    'openDropdown': None,
    'linked_action': None,
    'linked_source_expr': None,
    'linked_prefix': None,
}

_OWN_KEYS = ["Enter", "Escape", "ArrowUp", "ArrowDown", "Tab"]


def init_model(lst, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
    if get_visualizer is None:
        return {'children': {}, 'handledKeys': [], 'display_mode': 'table', 'columns': ['^'],
                **_COLUMN_MGMT_DEFAULTS, **_SEARCH_DEFAULTS}

    source_expr = None
    if var_and_exp:
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else expr

    type_key = _get_item_type_key(lst)
    saved_columns = load_columns_from_dotfile(type_key) if type_key else None

    if saved_columns is not None:
        columns = saved_columns
    else:
        columns = _detect_table_columns(lst, get_visualizer)
        if columns is None:
            columns = ['^']

    children = {}
    for i, item in enumerate(lst):
        for col in columns:
            try:
                if source_expr is not None and eval_in_scope is not None:
                    cell_value = eval_in_scope(replace_caret_in_py_exp(col, f'{source_expr}[{i}]'))
                else:
                    cell_value = eval_caret_expr(col, item, eval_in_scope)
            except Exception:
                cell_value = None
            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                children[f"{i}{CELL_KEY_SEP}{col}"] = cell_vis.init_model(cell_value, get_visualizer,
                                                                          eval_in_scope=eval_in_scope)

    handled_keys = aggregate_handled_keys(children, _OWN_KEYS)
    return {
        'children': children,
        'handledKeys': handled_keys,
        'display_mode': 'table',
        'columns': columns,
        '_source_expr': source_expr,
        **_COLUMN_MGMT_DEFAULTS,
        **_SEARCH_DEFAULTS,
    }


def _render_column_header(col, index, model):
    """Render a normal column header with drag handle, remove button, and column name."""
    click_event = repr(ColumnClick(index=index))
    remove_event = repr(RemoveColumnClick(index=index))
    drag_start_event = repr(ColumnDragStart(index=index))
    drag_over_event = repr(ColumnDragOver(index=index))
    drag_end_event = repr(ColumnDragEnd(index=index))

    drag_from = model.get('column_drag_from')
    drag_over = model.get('column_drag_over')
    is_drag_source = (drag_from == index)
    is_drag_target = (drag_from is not None and drag_over == index and drag_from != index)

    th_style = 'padding:0 8px;text-align:left;'
    if is_drag_source:
        th_style += 'opacity:0.3;'
    if is_drag_target:
        if drag_from > drag_over:
            th_style += f'border-left:2px solid {BLUE};'
        else:
            th_style += f'border-right:2px solid {BLUE};'

    source_expr = model.get('_source_expr')
    if source_expr is not None:
        item_expr = replace_caret_in_py_exp(col, 'item')
        full_expr = f'[{item_expr} for item in {source_expr}]'
        py_exp_attr = f' snc-py-exp="{html.escape(full_expr)}" draggable="true"'
    else:
        py_exp_attr = ''

    return (
        f'<th class="snc-hover-hidden-parent" '
        f'snc-mouse-move="{html.escape(drag_over_event)}" '
        f'snc-mouse-up="{html.escape(drag_end_event)}" '
        f'style="{th_style}">'
        f'<span snc-mouse-down="{html.escape(drag_start_event)}" '
        f'style="color:{GRAY};cursor:grab;opacity:0.5;user-select:none;'
        f'font-size:8px;font-style:normal;" '
        f'title="Drag to reorder" class="snc-hover-hidden full-opacity-on-hover">U</span>'
        f'<span snc-mouse-down="{html.escape(remove_event)}" '
        f'style="color:{GRAY};cursor:pointer;opacity:0.5;user-select:none;" '
        f'title="Remove column" class="snc-hover-hidden full-opacity-on-hover">\u00d7</span>'
        f'<span snc-mouse-down="{html.escape(click_event)}"'
        f'{py_exp_attr} '
        f'style="color:{BLUE};cursor:pointer;">'
        f'{html.escape(strip_leading_caret(col) or col)}</span>'
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
            bg = SELECTED_BG if is_selected else SUGGESTION_BG
            scroll_attr = ' snc-scroll-into-view' if is_selected else ''
            items.append(
                f'<div snc-mouse-down="{html.escape(select_event)}" '
                f'class="snc-dropdown-option"'
                f'{scroll_attr} '
                f'style="padding:2px 6px;cursor:pointer;color:{BLUE};white-space:nowrap;'
                f'background:{bg};"'
                f'>{html.escape(suggestion)}</div>'
            )
        suggestion_html = (
            f'<div class="snc-dropdown-panel" snc-dropdown-align="left" style="'
            f'position:absolute;left:0;top:100%;'
            f'border:1px solid {INPUT_BORDER};'
            f'max-height:200px;overflow-y:auto;background:{SUGGESTION_BG};'
            f'min-width:150px;font-size:12px;">'
            + '\n'.join(items)
            + '</div>'
        )

    extra_attrs = ' autofocus'
    if is_editing:
        extra_attrs += ' snc-select-all'

    input_html = (
        f'<span class="snc-dropdown-trigger" style="position:relative;display:inline-block;">'
        f'<input type="text" snc-input="{html.escape(input_event)}" '
        f'value="{html.escape(input_value)}" '
        f'placeholder="column name" '
        f'spellcheck="false"'
        f'{extra_attrs} '
        f'style="background:{INPUT_BG};color:{BLUE};border:1px solid {INPUT_BORDER};'
        f'padding:1px 4px;font-family:inherit;font-size:inherit;'
        f'outline:none;width:120px;" />'
        f'{suggestion_html}'
        f'</span>'
    )

    return f'<th style="padding:0 8px;">{input_html}</th>'


SEARCH_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="none" stroke="#000000" stroke-width="1.5" d="M11.5 11.5L14 14M6.5 11a4.5 4.5 0 100-9 4.5 4.5 0 000 9z"/></svg>'


def _render_search_box(model, max_width=None, eval_in_scope=None):
    """Render the search box below the table."""
    search_value = model.get('search') or ''
    search_input_event = "lambda e: SearchBoxInput(value=e.get('value', ''))"
    search_svg = SEARCH_SVG.replace("stroke:#000000;", "stroke:#8C8C8C;").replace(
        "<svg ", '<svg style="position: absolute; margin-left: 5px; margin-top: 4px; width: 12px; height: 12px;"', 1)

    toggle_btn_style = (
        'border-radius: 3px;'
        'padding: 1px 3px;'
        'font-family: inherit;'
        'font-size: 10px;'
        'cursor: pointer;'
        'line-height: 16px;'
        'user-select: none;'
    )

    first_match = bool(model.get('first_match', False))
    search = model.get('search')

    # Force 1st on for plain slice searches (not broadcast slices)
    if search:
        parsed = parse_search_term(search)
        if parsed and parsed[0] == 'slice':
            start_s, stop_s = parsed[1]
            _sb_eval = eval_in_scope or (lambda c: ast.literal_eval(c))
            try:
                sv = _sb_eval(start_s) if start_s else None
            except Exception:
                sv = None
            try:
                ev = _sb_eval(stop_s) if stop_s else None
            except Exception:
                ev = None
            if not (_is_list_of_ints(sv) or _is_list_of_ints(ev)):
                first_match = True

    fm_event = repr(FirstMatchToggle())
    first_match_toggle_html = (
        f'<span snc-mouse-down="{html.escape(fm_event)}"'
        f' class="snc-hoverable"'
        f' style="'
        f'background: {"#264f78" if first_match else "transparent"};'
        f'margin-left: 2px;'
        f'color: {"#ccc" if first_match else "#8C8C8C"};'
        f'border: 1px solid {"#aaa" if first_match else "#3c3c3c"};'
        f'{toggle_btn_style}'
        f'"'
        f'>1<span style="font-size: 8px; vertical-align: 3px; display: inline-block; margin-top: -1em;">st</span></span>'
    )

    toggles_html = (
        f'<span style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%);">'
        f'{first_match_toggle_html}'
        f'</span>'
    )

    return (
        f'<div style="margin-top: 4px; white-space: normal; display: flex; align-items: start; gap: 2px;'
        f' max-width: {str(max_width) + "px" if max_width is not None else "none"};'
        f'">'
        f'<div style="flex: 1; min-width: 0;">'
        f'<div style="position: relative;">'
        f'{search_svg}'
        f'<input type="text" tabindex="0"'
        f' snc-input="{html.escape(search_input_event)}"'
        f' value="{html.escape(search_value)}"'
        f' placeholder="Search"'
        f' spellcheck="false"'
        f' style="'
        f'background: #1e1e1e;'
        f'color: #dcdcaa;'
        f'border: 1px solid #3c3c3c;'
        f'border-radius: 10px;'
        f'padding: 2px 45px 2px 20px;'
        f'font-family: inherit;'
        f'font-size: 12px;'
        f'outline: none;'
        f'width: 100%;'
        f'box-sizing: border-box;'
        f'"'
        f' />'
        f'{toggles_html}'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def _render_action_buttons(model, lst, eval_in_scope=None, max_width=None):
    """Render the action button bar below the search box."""
    search = model.get('search')
    has_search = search is not None and search != ''
    first = bool(model.get('first_match', False))

    # Force 1st for plain index/slice (not broadcast)
    is_index_search = False
    if has_search:
        parsed = parse_search_term(search)
        if parsed and parsed[0] == 'slice':
            start_s, stop_s = parsed[1]
            _btn_eval = eval_in_scope or (lambda c: ast.literal_eval(c))
            try:
                sv = _btn_eval(start_s) if start_s else None
            except Exception:
                sv = None
            try:
                ev = _btn_eval(stop_s) if stop_s else None
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

    match_count = 0
    if has_search and eval_in_scope is not None:
        try:
            match_count = len(_get_matching_indices(search, lst, eval_in_scope))
        except Exception:
            pass
    elif not has_search:
        match_count = len(lst)

    btn_base = (
        'border: 1px solid #3c3c3c;'
        'border-radius: 3px;'
        'padding: 1px 5px;'
        'font-family: inherit;'
        'font-size: 10px;'
        'cursor: pointer;'
        'line-height: 16px;'
        'user-select: none;'
        'white-space: nowrap;'
        'background: transparent;'
        'color: #8C8C8C;'
    )
    copy_base = (
        'border: 1px solid #3c3c3c;'
        'border-left: none;'
        'border-radius: 0 3px 3px 0;'
        'padding: 1px 3px;'
        'font-family: inherit;'
        'font-size: 10px;'
        'cursor: pointer;'
        'line-height: 16px;'
        'user-select: none;'
        'white-space: nowrap;'
        'background: transparent;'
        'color: #8C8C8C;'
    )
    btn_with_copy = btn_base + 'border-radius: 3px 0 0 3px;'
    disabled_style = 'opacity: 0.35; pointer-events: none;'

    linked_action = model.get('linked_action')
    linked_highlight = 'background: #264f78; color: #ccc; border-color: #aaa;'

    def action_btn(label, action, enabled=True, title='', extra_style=''):
        active = linked_highlight if linked_action == action else ''
        style = btn_with_copy + ('' if enabled else disabled_style) + active + extra_style
        event = repr(ActionButtonClick(action=action, copy=False))
        title_attr = f' title="{html.escape(title)}"' if title else ''
        return f'<span class="snc-hoverable" snc-mouse-down="{html.escape(event)}" style="margin-left: 3px;{style}"{title_attr}>{label}</span>'

    def copy_btn(action, enabled=True):
        style = copy_base + ('' if enabled else disabled_style)
        event = repr(ActionButtonClick(action=action, copy=True))
        return f'<span class="snc-hoverable" snc-mouse-down="{html.escape(event)}" style="{style}" title="Copy to clipboard">\u29C9</span>'

    def btn_group(label, action, enabled=True, title='', extra_btn_style=''):
        return f'<span>{action_btn(label, action, enabled, title, extra_btn_style)}{copy_btn(action, enabled)}</span>'

    parts = []

    # 1. Filter / Find One
    filter_lbl = 'Find One \u23ce' if first else 'Filter \u23ce'
    parts.append(btn_group(filter_lbl, 'filter', has_search, 'Filter matches (Enter)'))

    # 2. Loop dropdown
    open_dropdown = model.get('openDropdown')
    loop_dropdown_open = open_dropdown is not None and open_dropdown.get('id') == 'action-loop'
    loop_enabled = not (has_search and first)

    loop_toggle_event = repr(DropdownToggle('action-loop'))
    loop_disabled = '' if loop_enabled else disabled_style
    loop_btn_style = btn_base + ('background: #264f78; color: #ccc; border-color: #aaa;' if loop_dropdown_open else '') + loop_disabled
    loop_btn = f'<span class="snc-hoverable" snc-mouse-down="{html.escape(loop_toggle_event)}" style="margin-left: 3px;{loop_btn_style}" title="For loop over matches">Loop \u25be</span>'

    if loop_dropdown_open and loop_enabled:
        loop_opts = []
        loop_opt_style = 'padding: 3px 6px; display: flex; align-items: center; gap: 2px;'

        def loop_row(label, action):
            act_event = repr(ActionButtonClick(action=action, copy=False))
            cp_event = repr(ActionButtonClick(action=action, copy=True))
            return (
                f'<div style="{loop_opt_style}" class="snc-dropdown-option">'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(act_event)}" style="flex:1;">{label}</span>'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(cp_event)}" style="font-size:10px;color:#8C8C8C;" title="Copy to clipboard">\u29C9</span>'
                f'</div>'
            )

        loop_opts.append(loop_row('No indices', 'loop_no_idx'))
        loop_opts.append(loop_row('Original indices', 'loop_orig_idx'))
        loop_opts.append(loop_row('New indices', 'loop_new_idx'))

        loop_panel = (
            '<div class="snc-dropdown-panel" snc-dropdown-align="left" style="'
            'position: absolute;left: 0;top: 100%;'
            'background: #252526;border: 1px solid #3c3c3c;border-radius: 3px;'
            'z-index: 100;min-width: 120px;'
            'box-shadow: 0 2px 8px rgba(0,0,0,0.4);font-size: 11px;line-height: 1.4;'
            f'">{"".join(loop_opts)}</div>'
        )
        loop_btn = (
            f'<span class="snc-dropdown-trigger" style="position: relative; display: inline-block;">'
            f'{loop_btn}{loop_panel}</span>'
        )

    parts.append(loop_btn)

    # 3. ? dropdown
    predicate_dropdown_open = open_dropdown is not None and open_dropdown.get('id') == 'action-predicate'

    toggle_event = repr(DropdownToggle('action-predicate'))
    q_disabled = ''
    q_style = btn_base + ('background: #264f78; color: #ccc; border-color: #aaa;' if predicate_dropdown_open else '') + q_disabled
    q_btn = f'<span class="snc-hoverable" snc-mouse-down="{html.escape(toggle_event)}" style="margin-left: 3px;{q_style}" title="Boolean queries">? \u25be</span>'

    if predicate_dropdown_open:
        dropdown_opts = []
        opt_style = 'padding: 3px 6px; display: flex; align-items: center; gap: 2px;'

        def dropdown_row(label, action, enabled):
            row_style = opt_style + ('' if enabled else disabled_style)
            act_event = repr(ActionButtonClick(action=action, copy=False))
            cp_event = repr(ActionButtonClick(action=action, copy=True))
            return (
                f'<div style="{row_style}" class="snc-dropdown-option">'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(act_event)}" style="flex:1;">{label}</span>'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(cp_event)}" style="font-size:10px;color:#8C8C8C;" title="Copy to clipboard">\u29C9</span>'
                f'</div>'
            )

        dropdown_opts.append(dropdown_row('Any', 'any', True))
        dropdown_opts.append(dropdown_row('All', 'all', not (has_search and first)))
        dropdown_opts.append(dropdown_row('If Any', 'if_any', True))
        dropdown_opts.append(dropdown_row('If All', 'if_all', not (has_search and first)))

        dropdown_panel = (
            '<div class="snc-dropdown-panel" snc-dropdown-align="left" style="'
            'position: absolute;left: 0;top: 100%;'
            'background: #252526;border: 1px solid #3c3c3c;border-radius: 3px;'
            'z-index: 100;min-width: 100px;'
            'box-shadow: 0 2px 8px rgba(0,0,0,0.4);font-size: 11px;line-height: 1.4;'
            f'">{"".join(dropdown_opts)}</div>'
        )
        q_btn = (
            f'<span class="snc-dropdown-trigger" style="position: relative; display: inline-block;">'
            f'{q_btn}{dropdown_panel}</span>'
        )

    parts.append(q_btn)

    # 4. Delete
    delete_lbl = 'Delete First' if first else 'Delete All'
    parts.append(btn_group(delete_lbl, 'delete', has_search, 'Delete matches'))

    # 5. Join dropdown
    join_dropdown_open = open_dropdown is not None and open_dropdown.get('id') == 'action-join'
    join_enabled = not (has_search and first)

    join_toggle_event = repr(DropdownToggle('action-join'))
    join_disabled = '' if join_enabled else disabled_style
    join_active = linked_highlight if linked_action == 'join' else ''
    join_btn_style = btn_base + ('background: #264f78; color: #ccc; border-color: #aaa;' if join_dropdown_open else '') + join_disabled + join_active
    join_btn = f'<span class="snc-hoverable" snc-mouse-down="{html.escape(join_toggle_event)}" style="margin-left: 3px;{join_btn_style}" title="Join list items into a string">Join \u25be</span>'

    if join_dropdown_open and join_enabled:
        join_opts = []
        join_opt_style = 'padding: 3px 6px; display: flex; align-items: center; gap: 2px;'

        join_presets = ["''", "' '", "'\\n'", "','", "'\\t'"]

        for sep_expr in join_presets:
            act_action = f'join:{sep_expr}'
            act_event = repr(ActionButtonClick(action=act_action, copy=False))
            cp_event = repr(ActionButtonClick(action=act_action, copy=True))
            join_opts.append(
                f'<div style="{join_opt_style}" class="snc-dropdown-option">'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(act_event)}" style="flex:1;">{html.escape(sep_expr)}</span>'
                f'<span class="snc-hoverable" snc-mouse-down="{html.escape(cp_event)}" style="font-size:10px;color:#8C8C8C;" title="Copy to clipboard">\u29C9</span>'
                f'</div>'
            )

        custom_sep = open_dropdown.get('customSep', "''") if open_dropdown else "''"
        custom_input_event = "lambda e: JoinSeparatorInput(value=e.get('value', ''))"
        custom_act_action = f'join:{custom_sep}'
        custom_cp_event = repr(ActionButtonClick(action=custom_act_action, copy=True))
        join_opts.append(
            f'<div style="{join_opt_style}" class="snc-dropdown-option">'
            f'<input type="text" snc-input="{html.escape(custom_input_event)}" '
            f'value="{html.escape(custom_sep)}" '
            f'placeholder="expr" '
            f'spellcheck="false" '
            f'style="width: 50px; background: #1e1e1e; color: #dcdcaa; border: 1px solid #3c3c3c; '
            f'border-radius: 2px; padding: 1px 3px; font-size: 10px; font-family: inherit; outline: none;" />'
            f'<span class="snc-hoverable" snc-mouse-down="{html.escape(custom_cp_event)}" '
            f'style="font-size:10px;color:#8C8C8C;" title="Copy to clipboard">\u29C9</span>'
            f'</div>'
        )

        join_panel = (
            '<div class="snc-dropdown-panel" snc-dropdown-align="left" style="'
            'position: absolute;left: 0;top: 100%;'
            'background: #252526;border: 1px solid #3c3c3c;border-radius: 3px;'
            'z-index: 100;min-width: 80px;'
            'box-shadow: 0 2px 8px rgba(0,0,0,0.4);font-size: 11px;line-height: 1.4;'
            f'">{"".join(join_opts)}</div>'
        )
        join_btn = (
            f'<span class="snc-dropdown-trigger" style="position: relative; display: inline-block;">'
            f'{join_btn}{join_panel}</span>'
        )

    parts.append(join_btn)

    # 6. Find Indices (disabled for single-index searches — the index is already known)
    indices_lbl = 'First Index' if first else 'Find Indices'
    parts.append(btn_group(indices_lbl, 'find_indices', has_search and not is_index_search, 'Indices of matches'))

    # 7. Count
    count_label = f'Count ({match_count})'
    parts.append(btn_group(count_label, 'count', not (has_search and first), 'Count of matches'))

    if linked_action:
        unlink_event = repr(Unlink())
        unlink_style = btn_base + 'color: #e0a060;'
        parts.append(
            f'<span class="snc-hoverable" snc-mouse-down="{html.escape(unlink_event)}"'
            f' style="margin-left: 6px;{unlink_style}" title="Unlink from selected code">'
            f'\u26d3\ufe0e Unlink</span>'
        )

    return (
        f'<div style="margin-top: 4px; white-space: normal;'
        f'max-width: {str(max_width) + "px" if max_width is not None else "none"};">'
        f'{"".join(parts)}'
        f'</div>'
    )


def _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False):
    children = model.get('children', {})
    columns = model.get('columns', [])
    focused_child = model.get('focused_child')

    max_column_width = round(800 / sqrt(max(len(columns), 1)))

    search = model.get('search')
    has_search = search is not None and search != ''
    first = bool(model.get('first_match', False))

    matched_indices = set()
    if has_search and not small:
        try:
            matched = _get_matching_indices(search, lst, eval_in_scope)
            if first and matched:
                matched = matched[:1]
            matched_indices = set(matched)
        except Exception:
            pass

    table_div_style = (
        f'max-height: {(max_height or 400) - 32}px;'
        'overflow: auto;'
        'scrollbar-width: thin;'
        'scrollbar-color: rgba(127, 127, 127, 0.1) transparent;'
    )

    key_handler = repr(ColumnKeyDown())
    strs = [
        f'<div tabindex="0" snc-key-down="{html.escape(key_handler)}" '
        f'style="font-family:monospace;outline:none;">'
    ]
    strs.append(f'<div style="{table_div_style}">')
    strs.append('<table style="border-collapse:collapse;font-family:monospace;"><tr>')
    strs.append('<th style="padding:0 8px;"></th>')

    for ci, col in enumerate(columns):
        if model.get('editing_column_index') == ci:
            strs.append(_render_column_input(lst, model, get_visualizer, is_editing=True, editing_index=ci))
        else:
            strs.append(_render_column_header(col, ci, model))

    if model.get('adding_column'):
        strs.append(_render_column_input(lst, model, get_visualizer, is_editing=False))

    add_event = repr(AddColumnClick())
    strs.append(
        f'<th class="snc-hover-hidden-parent" '
        f'snc-mouse-down="{html.escape(add_event)}" '
        f'style="padding:0 4px;cursor:pointer;vertical-align:middle;">'
        f'<span class="snc-hover-hidden full-opacity-on-hover" '
        f'style="color:{GRAY};opacity:0.5;font-size:8px;font-style:normal;">+</span>'
        f'</th>'
    )

    strs.append('</tr>')

    source_expr = model.get('_source_expr')

    scroll_to = model.get('_scroll_to_match', False)
    first_match_row = min(matched_indices) if matched_indices else None

    for i, item in enumerate(lst):
        is_match = i in matched_indices
        row_style = ''
        scroll_attr = ''
        if has_search and matched_indices:
            if is_match:
                row_style = f' style="border-left:2px solid {BLUE};"'
                if scroll_to and i == first_match_row:
                    scroll_attr = ' snc-scroll-to-match'
            else:
                row_style = ' style="opacity:0.4;"'

        strs.append(f'<tr{row_style}{scroll_attr}><td style="color:')
        strs.append(GRAY)
        strs.append(';padding:0 8px;text-align:right;">')
        strs.append(str(i))
        strs.append('</td>')

        for col in columns:
            composite_key = f"{i}{CELL_KEY_SEP}{col}"
            try:
                if source_expr is not None and eval_in_scope is not None:
                    cell_value = eval_in_scope(replace_caret_in_py_exp(col, f'{source_expr}[{i}]'))
                else:
                    cell_value = eval_caret_expr(col, item, eval_in_scope)
            except Exception:
                cell_value = None

            if cell_value is not None:
                cell_vis = get_visualizer(cell_value)
                cell_model = children.get(composite_key)
                if cell_model is None:
                    cell_model = cell_vis.init_model(cell_value, get_visualizer,
                                                     eval_in_scope=eval_in_scope)
                child_small = (composite_key != focused_child)
                if hasattr(cell_vis, 'visualize_els'):
                    cell_htmls = cell_vis.visualize_els(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small)
                else:
                    cell_htmls = [cell_vis.visualize(cell_value, cell_model, get_visualizer, eval_in_scope, max_width=max_column_width, max_height=80, small=child_small)]

                is_generic = cell_model is None
                cell_exp_attr = ''
                if source_expr is not None:
                    cell_expr = replace_caret_in_py_exp(col, f'{source_expr}[{i}]')
                    cell_exp_attr = f' snc-py-exp="{html.escape(cell_expr)}" draggable="true"'

                if is_generic or not cell_exp_attr:
                    strs.append('<td style="padding:0 8px;">')
                    strs.append(wrap_child_prefix(composite_key))
                    if cell_exp_attr:
                        strs.append(f'<span{cell_exp_attr} class="py-exp-grab">')
                    strs.extend(cell_htmls)
                    if cell_exp_attr:
                        strs.append('</span>')
                    strs.append(wrap_child_suffix)
                    strs.append('</td>')
                else:
                    strs.append('<td style="padding:0;">')
                    strs.append(f'<div{cell_exp_attr} class="py-exp-cell">')
                    strs.append('<div draggable="false" class="py-exp-inner">')
                    strs.append(wrap_child_prefix(composite_key))
                    strs.extend(cell_htmls)
                    strs.append(wrap_child_suffix)
                    strs.append('</div></div>')
                    strs.append('</td>')
            else:
                strs.append('<td style="padding:0 8px;"></td>')

        strs.append('</tr>')

    strs.append('</table>')
    strs.append('</div>')

    if small:
        search_box_html = ''
        action_buttons_html = ''
    else:
        search_box_html = _render_search_box(model, max_width, eval_in_scope)
        action_buttons_html = _render_action_buttons(model, lst, eval_in_scope, max_width)

    strs.append(search_box_html)
    strs.append(action_buttons_html)
    strs.append('</div>')
    return ''.join(strs)


def visualize(lst: list, model: dict, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False):
    return _visualize_table(lst, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small)


def _table_child_value_getter(key, lst, eval_in_scope=None, source_expr=None):
    row_key, field_key = key.split(CELL_KEY_SEP, 1)
    idx = int(row_key)
    if source_expr is not None and eval_in_scope is not None:
        return eval_in_scope(replace_caret_in_py_exp(field_key, f'{source_expr}[{idx}]'))
    return eval_caret_expr(field_key, lst[idx], eval_in_scope)


def update(event, var_and_exp, model: Any, value, get_visualizer=None, eval_in_scope=None) -> Tuple[Any, List[Any]]:
    if event is None or not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])

    if model is None:
        model = {'children': {}, 'handledKeys': [], 'display_mode': 'table', 'columns': ['^'],
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
        _row_key, cell_col = msg.child_key.split(CELL_KEY_SEP, 1)
        new_model, commands = route_child_event(
            event, model, value,
            child_value_getter=lambda key: _table_child_value_getter(key, value, eval_in_scope, model.get('_source_expr')),
            get_visualizer=get_visualizer,
            var_and_exp=(None, cell_col),
            eval_in_scope=eval_in_scope,
        )
        filtered_commands: List[Any] = []
        type_key = _get_item_type_key(value) if value else None
        for cmd in commands:
            if isinstance(cmd, tuple) and len(cmd) == 2:
                _suggest_var_name, expr = cmd
                new_model['columns'].append(expr)
                if type_key:
                    save_columns_to_dotfile(type_key, new_model['columns'])
            else:
                filtered_commands.append(cmd)
        new_model['handledKeys'] = aggregate_handled_keys(new_model.get('children', {}), _OWN_KEYS)
        return (new_model, filtered_commands)

    commands: List[Any] = []
    type_key = _get_item_type_key(value) if value else None
    model['_scroll_to_match'] = False

    match msg:
        case AddColumnClick():
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
                    save_columns_to_dotfile(type_key, model['columns'])
            elif model.get('editing_column_index') is not None:
                idx = model['editing_column_index']
                if 0 <= idx < len(model['columns']):
                    old_name = model['columns'][idx]
                    model['columns'][idx] = name
                    if old_name != name:
                        _rename_column_children(model, old_name, name)
                model['editing_column_index'] = None
                model['column_input_value'] = ''
                if type_key:
                    save_columns_to_dotfile(type_key, model['columns'])

        case ColumnClick(index=idx):
            detail = event_json.get('detail', 1)
            if detail >= 2:
                if 0 <= idx < len(model['columns']):
                    model['editing_column_index'] = idx
                    model['column_input_value'] = model['columns'][idx]
                    model['adding_column'] = False

        case RemoveColumnClick(index=idx):
            if 0 <= idx < len(model['columns']):
                removed_col = model['columns'].pop(idx)
                _remove_column_children(model, removed_col)
                if model.get('editing_column_index') is not None:
                    if model['editing_column_index'] == idx:
                        model['editing_column_index'] = None
                        model['column_input_value'] = ''
                    elif model['editing_column_index'] > idx:
                        model['editing_column_index'] -= 1
                if type_key:
                    save_columns_to_dotfile(type_key, model['columns'])

        case ColumnDragStart(index=idx):
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
                    if type_key:
                        save_columns_to_dotfile(type_key, model['columns'])
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
                            save_columns_to_dotfile(type_key, model['columns'])
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
                        if type_key:
                            save_columns_to_dotfile(type_key, model['columns'])
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
                                commands.append(result)
                        model['openDropdown'] = None
                    elif model.get('search'):
                        if model.get('linked_action'):
                            model['linked_action'] = 'filter'
                        else:
                            ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                            if ctx:
                                result = generate_action('filter', ctx)
                                if result:
                                    commands.append(result)

            elif key == 'Backspace' and event_json.get('metaKey', False):
                if model.get('linked_action'):
                    model['linked_action'] = 'delete'
                else:
                    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                    if ctx:
                        result = generate_action('delete', ctx)
                        if result:
                            commands.append(result)

            elif key == 'Escape':
                if model.get('openDropdown'):
                    model['openDropdown'] = None
                else:
                    model['adding_column'] = False
                    model['editing_column_index'] = None
                    model['column_input_value'] = ''
                    model['selected_suggestion_index'] = None

        case SearchBoxInput(value=val):
            model['search'] = val if val else None
            model['_scroll_to_match'] = True

        case FirstMatchToggle():
            model['first_match'] = not model.get('first_match', False)

        case DropdownToggle(dropdown_id=did):
            current = model.get('openDropdown')
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
                        _emit_linked_update(result[1], model, commands)
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
                            commands.append(CopyToClipboard(text=result[1]))
                        else:
                            commands.append(result)

        case EditorTextSelect(text=selected_text):
            from list_visualizer_grammar import parse_generated_code_or_assignment
            parsed, prefix = parse_generated_code_or_assignment(selected_text)
            if parsed and parsed.get('action') and parsed.get('source_expr'):
                valid = True
                if var_and_exp:
                    line_var = var_and_exp[0]
                    if line_var and parsed['source_expr'] != line_var:
                        valid = False
                if valid:
                    _ctx_to_model(parsed, model)
                    model['linked_action'] = parsed['action']
                    model['linked_source_expr'] = parsed['source_expr']
                    model['linked_prefix'] = prefix

        case Unlink():
            model['linked_action'] = None
            model['linked_source_expr'] = None
            model['linked_prefix'] = None

    if model.get('linked_action') and not isinstance(msg, (ActionButtonClick, EditorTextSelect, Unlink)):
        ctx = _get_search_context(model, var_and_exp,
                                  source_expr=model['linked_source_expr'],
                                  eval_in_scope=eval_in_scope)
        if ctx:
            result = generate_action(model['linked_action'], ctx)
            if result:
                _emit_linked_update(result[1], model, commands)

    return (model, commands)
