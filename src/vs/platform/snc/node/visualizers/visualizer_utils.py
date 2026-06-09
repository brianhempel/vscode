"""Shared utilities for visualizer composition in Sculpt-n-Code."""

import ast
import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple


# =============================================================================
# VS Code theme colors (shared across all visualizers)
# =============================================================================

BLUE = "#569cd6"
STRING = "#ce9178"
VALUE = "#b5cea8"
TYPE = "#4ec9b0"
GRAY = "#808080"
GRAY_HALF_ALPHA = "rgba(128,128,128,0.5)"
ERROR_RED = "#f44747"
ADD_GREEN = "#89d185"
INPUT_BG = "#1e1e1e"
INPUT_BORDER = "#3c3c3c"
SUGGESTION_BG = "#252526"
SUGGESTION_HOVER = "#2a2d2e"
SELECTED_BG = "#094771"


# =============================================================================
# Shared SVG icons
# =============================================================================
#
# Each icon is loaded once at module import. The <svg> root gets the
# .search-icon CSS class so styling lives in CSS, and any inline style="..."
# attributes (Amadine's export format) are expanded to discrete fill="..." /
# stroke="..." attributes so CSS can override them.

ICONS: Dict[str, str] = {}

_STYLE_RE = re.compile(r'\bstyle="([^"]+)"', flags=re.M)
_ICON_NAMES = [
    "bin", "caps", "boolean-any", "boolean-all", "exists", "filter",
    "match-first", "regex-group", "split", "loop", "replace", "search",
    "search-str", "search-idx", "search-match",
]
for _icon in _ICON_NAMES:
    with open(os.path.join(os.path.dirname(__file__), f'icons/{_icon}.svg'), 'r') as _f:
        _svg_content = (_f.read()
                        .replace('<?xml version="1.0" encoding="utf-8"?>\n', '')
                        .replace('<svg ', '<svg class="search-icon"'))
        ICONS[_icon] = _STYLE_RE.sub(
            lambda m: ' '.join(f'{k}="{v}"'
                               for attr in m[1].rstrip(';').split(';')
                               for k, v in [attr.split(':', 2)]),
            _svg_content,
        )


# =============================================================================
# Shared HTML helpers
# =============================================================================

def truncate_str(s, max_len):
    """Truncate a string, showing beginning + \u2026 + end if too long."""
    if len(s) <= max_len:
        return s
    half = max_len // 2
    if max_len >= 5:
        return s[:half] + '\u2026' + s[-half + 1:]
    return s[:max(max_len - 1, 0)] + '\u2026'


def safe_repr(value):
    """HTML-escape repr(value), returning an error span on failure."""
    try:
        return html.escape(repr(value))
    except Exception:
        return f'<span style="color: {ERROR_RED};">[Error]</span>'


def span(text, color):
    """Wrap text in a colored <span>."""
    return f'<span style="color: {color};">{text}</span>'


# =============================================================================
# Dotfile persistence (generic JSON key→list storage)
# =============================================================================

def load_dotfile_list(dotfile_name: str, key: str, transform=None):
    """Load a list for a key from a JSON dotfile in the cwd.

    Returns the list (optionally transformed), or None if not found.
    """
    try:
        path = os.path.join(os.getcwd(), dotfile_name)
        with open(path, 'r') as f:
            data = json.load(f)
        items = data.get(key)
        if isinstance(items, list):
            return [transform(item) for item in items] if transform else items
        return None
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return None


def save_dotfile_list(dotfile_name: str, key: str, items: list):
    """Save a list for a key to a JSON dotfile in the cwd, preserving other keys."""
    path = os.path.join(os.getcwd(), dotfile_name)
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    data[key] = items
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# =============================================================================
# Class identification
# =============================================================================

def get_full_class_name(obj) -> str:
    """Return the full module.qualname for an object's class."""
    return obj.__class__.__module__ + '.' + obj.__class__.__qualname__


# =============================================================================
# Nested "slots" config (shared by the list + object visualizers)
# =============================================================================
#
# A "slot" is one column (for a list, evaluated per item) or one field (for an
# object, evaluated on the object); in both cases `^` denotes "a value of type
# T". The on-disk config maps a type key T -> [slot, ...]; a slot is a bare
# expr string or {"expr": ..., "children": {T2: [slot, ...]}}. When descending
# into a slot's cell, `children` is consulted by the cell's own type key, so a
# type T only applies where it appears in the tree. This is what stops the
# infinite recursion: a list/object whose cell is the same type does NOT re-read
# the global type config; it uses the explicitly-nested config or a default.

MAX_NEST_DEPTH = 5


def config_key(value) -> 'str | None':
    """The type key that selects a value's slots.

    For a list it's the element type (so a list-of-T and a single T share one
    config); for everything else it's the value's own class. Empty lists have
    no key.
    """
    if isinstance(value, list):
        if not value:
            return None
        return get_full_class_name(value[0])
    return get_full_class_name(value)


def parse_slots(slots_config, expr_transform=None):
    """Split a slot list into (exprs, slot_children).

    slot_children maps a slot's expr -> its {T2: [slot, ...]} children map
    (only for slots that actually carry children). Bare-string entries are
    treated as childless slots. `expr_transform` is applied to each expr (used
    by the object visualizer to ensure a leading caret).
    """
    exprs = []
    slot_children = {}
    for entry in (slots_config or []):
        if isinstance(entry, str):
            expr, children = entry, None
        elif isinstance(entry, dict) and 'expr' in entry:
            expr, children = entry['expr'], entry.get('children')
        else:
            continue
        if expr_transform is not None:
            expr = expr_transform(expr)
        exprs.append(expr)
        if isinstance(children, dict) and children:
            slot_children[expr] = children
    return exprs, slot_children


def too_deep(config_path) -> bool:
    """True when nesting has reached the depth cap (a backstop against cyclic
    values that would otherwise RecursionError)."""
    return len(config_path or []) >= MAX_NEST_DEPTH


def child_nesting_kwargs(parent_model: dict, slot_expr: str, cell_value) -> dict:
    """Compute the nesting kwargs to hand a child (sub-)visualizer.

    The child receives the slot's nested config for the cell's type (or None ->
    default), the inherited root type/dotfile, and the path extended by this
    (slot_expr, cell_type) step (so it can persist edits at its own location).
    """
    children_map = (parent_model.get('_slot_children') or {}).get(slot_expr) or {}
    t2 = config_key(cell_value)
    slots_config = children_map.get(t2) if t2 is not None else None
    return {
        'slots_config': slots_config,
        'config_root_type': parent_model.get('_config_root_type'),
        'config_root_dotfile': parent_model.get('_config_root_dotfile'),
        'config_path': (parent_model.get('_config_path') or []) + [(slot_expr, t2)],
    }


def load_root_slots(dotfile_name: str, root_type: 'str | None'):
    """Load the raw slot list for a type from a dotfile (or None)."""
    if not root_type:
        return None
    return load_dotfile_list(dotfile_name, root_type)


def _load_dotfile_dict(dotfile_name: str) -> dict:
    try:
        path = os.path.join(os.getcwd(), dotfile_name)
        with open(path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def _save_dotfile_dict(dotfile_name: str, data: dict) -> None:
    path = os.path.join(os.getcwd(), dotfile_name)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _normalize_slot_list(slot_list: list) -> None:
    """Convert any legacy bare-string entries to {'expr': ...} dicts in place."""
    for i, obj in enumerate(slot_list):
        if isinstance(obj, str):
            slot_list[i] = {'expr': obj}


def _find_slot(slot_list: list, expr: str):
    for obj in slot_list:
        if isinstance(obj, dict) and obj.get('expr') == expr:
            return obj
    return None


def save_slots_at_path(dotfile_name: str, root_type: 'str | None',
                       path, exprs: list) -> None:
    """Persist a (sub-)level's slot exprs at its path in the dotfile.

    `path` is a list of (slot_expr, child_type) steps from the root type. Only
    this level's expr list is rewritten; each surviving slot keeps its existing
    `children` (matched by expr), and other types/branches on disk are left
    untouched. So an ancestor never clobbers a descendant's nested config.
    """
    if not root_type:
        return
    data = _load_dotfile_dict(dotfile_name)

    target = data.get(root_type)
    if not isinstance(target, list):
        target = []
        data[root_type] = target

    for step in (path or []):
        step_expr, step_type = step[0], step[1]
        _normalize_slot_list(target)
        obj = _find_slot(target, step_expr)
        if obj is None:
            obj = {'expr': step_expr}
            target.append(obj)
        children = obj.get('children')
        if not isinstance(children, dict):
            children = {}
            obj['children'] = children
        child_list = children.get(step_type)
        if not isinstance(child_list, list):
            child_list = []
            children[step_type] = child_list
        target = child_list

    _normalize_slot_list(target)
    old = list(target)
    rebuilt = []
    for e in exprs:
        existing = _find_slot(old, e)
        rebuilt.append(existing if existing is not None else {'expr': e})
    target[:] = rebuilt

    _save_dotfile_dict(dotfile_name, data)


# =============================================================================
# Caret (^) utilities
# =============================================================================

# ^ is a rare python infix operator, generally invalid in variable position.
# replace only ^ that are in variable position (not in strings, etc)
# does this by replace-and-check one by one to see if parse succeeds with the ^ retained
ONE_CARET_RE = re.compile(r'(?<!\^)\^(?!\^)')

def replace_caret_in_py_exp(py_exp: str, replace_exp) -> str:
    temp_names = []
    def temp_replacer(m):
        temp_name = f'_caret_{len(temp_names)}_'
        temp_names.append(temp_name)
        return temp_name
    out = ONE_CARET_RE.sub(temp_replacer, py_exp)

    for name in temp_names:
        try:
            temp_str = out.replace(name, '^')
            ast.parse(temp_str)
            out = temp_str
        except SyntaxError:
            out = out.replace(name, replace_exp)

    return out


def strip_leading_caret(name: str) -> str:
    """Remove a single leading ^ for display purposes."""
    if name.startswith('^'):
        return name[1:]
    return name


def eval_caret_expr(field_expr: str, value, eval_in_scope=None):
    """Evaluate a ^-prefixed field expression against a value.

    Uses local eval with the value bound directly.
    """
    _v = value
    return eval(replace_caret_in_py_exp(field_expr, '_v'))


@dataclass(frozen=True, slots=True)
class ChildEvent:
    """Envelope wrapping a child visualizer's event for parent routing."""
    child_key: str
    py_ev_str: str

@dataclass(frozen=True, slots=True)
class EditorTextSelect:
    """Sent by the TypeScript front-end when the user selects text in the editor.

    Every visualizer's update() evals event strings in module scope, so this
    must be importable everywhere an eval happens."""
    text: str

@dataclass(frozen=True, slots=True)
class Unlink:
    """Sent by the TypeScript front-end when an editor-visualizer link is broken."""
    pass

def wrap_drag_grab(inner_html: str, var_and_exp) -> str:
    """Wrap a non-interactive (small-mode) visualizer's output in a draggable
    snc-py-exp grab span.

    Small-mode visualizers have no interactions, so their whole area can be a
    drag-to-extract handle. When the parent supplies the access-path expression
    via var_and_exp, the visualizer self-wraps; otherwise (top-level, no source
    expression, or interactive/full mode) it renders bare so it keeps its mouse
    events.
    """
    expr = var_and_exp[1] if var_and_exp else None
    if not expr:
        return inner_html
    return (f'<span snc-py-exp="{html.escape(expr)}" draggable="true" '
            f'class="py-exp-grab">{inner_html}</span>')


def wrap_child_prefix(child_key: str) -> str:
    return f'<span snc-child-key="{html.escape(repr(child_key))}">'

wrap_child_suffix = '</span>'

def wrap_child_html(child_html: str, child_key: str) -> str:
    """Wrap child HTML in a span whose snc-child-key attribute holds repr(child_key).

    The TypeScript frontend reads this attribute at event-dispatch time and
    wraps the pythonEventStr in a envelope: ChildEvent(child_key, pythonEventStr).
    """
    return f"{wrap_child_prefix(child_key)}{child_html}{wrap_child_suffix}"


def route_child_event(
    event: dict,
    model: dict,
    value: Any,
    child_value_getter: Callable[[str], Any],
    get_visualizer: Callable[[Any], Any],
    var_and_exp=None,
    eval_in_scope=None,
) -> Tuple[dict, List[Any]]:
    """Unwrap a ChildEvent and dispatch to the appropriate child visualizer.

    Args:
        event: The raw event dict with pythonEventStr and eventJSON.
        model: Parent model (must have 'children' dict).
        value: The parent's value (e.g. the list or object).
        child_value_getter: Maps child_key -> child value.
        get_visualizer: The standard visualizer resolver.
        var_and_exp: (var_name | None, expression) tuple for source context.
        eval_in_scope: Evaluator for the user's code scope.

    Returns:
        (updated_model, commands) with the child's model stored back.
    """
    try:
        make_python_event = eval(event['pythonEventStr'])
    except Exception as e:
        return (model, [])

    event_json = event['eventJSON']
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event

    if not isinstance(msg, ChildEvent):
        return (model, [])

    child_key = msg.child_key
    is_mousedown = (event_json or {}).get('type') == 'mousedown'
    is_focused = model.get('focused_child') == child_key

    if not is_focused:
        # Non-focused children do not receive events. The FIRST mousedown on a
        # non-focused child pins focus (mirroring the top-level click-to-expand
        # pattern); every other event (mousemove, mouseup, keystrokes, hover)
        # is dropped so that hovering across cells, or finishing a drag begun
        # in a focused sibling, doesn't accidentally yank focus.
        if is_mousedown:
            model['focused_child'] = child_key
        return (model, [])

    # Focused child: dispatch the event normally. focused_child is already
    # set to child_key, so no need to re-assign at the end.
    child_value = child_value_getter(child_key)
    child_vis = get_visualizer(child_value)

    children = model.get('children', {})
    child_model = children.get(child_key)
    if child_model is None:
        child_model = child_vis.init_model(child_value, get_visualizer,
                                           eval_in_scope=eval_in_scope)

    inner_event = {'pythonEventStr': msg.py_ev_str, 'eventJSON': event_json}
    new_child_model, commands = child_vis.update(
        inner_event, var_and_exp, child_model, child_value, get_visualizer,
        eval_in_scope=eval_in_scope,
    )

    children[child_key] = new_child_model
    model['children'] = children
    return (model, commands)


def aggregate_handled_keys(
    children_models: Dict[str, Any],
    own_keys: List[str] | None = None,
) -> List[str]:
    """Compute the union of handledKeys from all child models plus parent's own keys.

    Only reads one level deep; nested keys propagate because each child already aggregates its own descendants.
    """
    seen = set()
    result: List[str] = []

    for key in (own_keys or []):
        if key not in seen:
            seen.add(key)
            result.append(key)

    for child_model in children_models.values():
        if not isinstance(child_model, dict):
            continue
        for key in child_model.get('handledKeys', []):
            if key not in seen:
                seen.add(key)
                result.append(key)

    return result
