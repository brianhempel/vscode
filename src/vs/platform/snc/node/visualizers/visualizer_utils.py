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
    model['focused_child'] = child_key
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
