"""Object visualizer for Sculpt-n-Code. z because that makes it last in priority.

This visualizer displays Python objects with configurable field inspection.

================================================================================
ARCHITECTURE OVERVIEW
================================================================================

This visualizer follows the Elm architecture with three core functions:

1. visualize(value, model) -> HTML string
   - Renders the object as a table of accessor → value rows
   - Shows a (+) button to add new fields
   - Shows autocomplete suggestions when adding/editing fields

2. init_model(value) -> dict
   - Returns the initial model state, loading saved fields from dotfile
   - Falls back to DEFAULT_FIELDS_FOR_TYPE, then non-trivial dir() names

3. update(event, var_and_exp, model, value) -> (new_model, commands)
   - Processes UI events (click, input, keyboard) and returns updated model
   - Saves field configuration to dotfile on commit

================================================================================
FIELD CONFIGURATION
================================================================================

Fields shown for each type are configurable and persisted:

1. DOTFILE (.snc_object_fields.json in working directory):
   - JSON mapping {full_class_name: [accessor_code, ...]}
   - Highest priority: user-customized fields

2. DEFAULT_FIELDS_FOR_TYPE:
   - Hardcoded defaults for known types (e.g., re.Match)
   - Used when type not in dotfile

3. Non-trivial dir() names:
   - Fallback: all attributes not in dir(object())
   - Used when type not in dotfile or DEFAULT_FIELDS_FOR_TYPE

================================================================================
"""

import html

from dataclasses import dataclass
from typing import List, Tuple, Any

from visualizer_utils import (
    ChildEvent, Unlink,
    wrap_child_html, route_child_event, aggregate_handled_keys,
    strip_leading_dollar, eval_dollar_expr, replace_dollars_in_py_exp,
    CHILD_SOURCE_BINDER, nest_generated_expr, nest_child_command, link_source_expr,
    get_full_class_name, truncate_str,
    config_key, parse_slots, load_root_slots, save_slots_at_path,
    child_nesting_kwargs, too_deep,
)

# This visualizer participates in the shared nested-slots config (parents thread
# per-slot config + path to it; see visualizer_utils). Used to decide whether to
# pass nesting kwargs to a child.
SUPPORTS_NESTED_CONFIG = True

# === Event types ===

@dataclass(frozen=True, slots=True)
class AddFieldClick:
    """User clicked the (+) button to add a new field."""
    pass

@dataclass(frozen=True, slots=True)
class FieldInput:
    """User typed in the field name input (add or edit mode)."""
    value: str

@dataclass(frozen=True, slots=True)
class FieldSelect:
    """User clicked an autocomplete suggestion."""
    accessor: str

@dataclass(frozen=True, slots=True)
class FieldClick:
    """User clicked on an existing field name (double-click to edit)."""
    index: int

@dataclass(frozen=True, slots=True)
class RemoveFieldClick:
    """User clicked the (×) button to remove a field."""
    index: int

@dataclass(frozen=True, slots=True)
class DragStart:
    """User pressed mouse down on a drag handle to start reordering."""
    index: int

@dataclass(frozen=True, slots=True)
class DragOver:
    """Mouse moved over a row while dragging (reorder target)."""
    index: int

@dataclass(frozen=True, slots=True)
class DragEnd:
    """User released mouse to drop a field at the target position."""
    index: int

@dataclass(frozen=True, slots=True)
class KeyDown:
    """Keyboard event (Enter to commit, Escape to cancel)."""
    pass


# === Constants ===

TRIVIAL_NAMES = set(dir(object()))

DEFAULT_FIELDS_FOR_TYPE = {
    're.Match': ['$[0]', '$.start(0)', '$.end(0)'],
}

DOTFILE_NAME = '.snc_object_fields.json'

_OWN_KEYS = ["Enter", "Escape", "ArrowUp", "ArrowDown", "Tab"]


def can_visualize(value):
    return value is not None and not isinstance(value, int) and not isinstance(value, float)

def get_fields(value):
    if value is None or isinstance(value, (int, float)):
        return None
    return _resolve_fields(value)


# === Dotfile operations ===

def _ensure_dollar_prefix(f):
    # Field expressions only need a dollar if they don't already reference the
    # source value somewhere; a leading dollar is only one of many valid forms
    # (e.g. 'str3[$.start():]' references $ inside an index expression).
    return f if '$' in f else f'${f}'


def load_fields_from_dotfile(full_class_name: str):
    """Load the raw slot list for a type from the dotfile (or None).

    Kept as the single root-read entry point so tests can patch it for
    isolation. The dollar-prefix normalization is applied later by parse_slots
    so it works uniformly with the nested slot format.
    """
    return load_root_slots(DOTFILE_NAME, full_class_name)


def save_fields_to_dotfile(root_type, path, exprs, dotfile=DOTFILE_NAME):
    """Path-scoped writer: persist a (sub-)object's field exprs at its location.

    `path` is the list of (slot_expr, child_type) steps from the root type.
    """
    save_slots_at_path(dotfile, root_type, path, exprs)


def _save_slots(model: dict) -> None:
    """Persist an object model's fields at its config path (preserves nested
    children of surviving fields and other types on disk)."""
    save_fields_to_dotfile(
        model.get('_config_root_type'),
        model.get('_config_path') or [],
        list(model.get('fields', [])),
        model.get('_config_root_dotfile') or DOTFILE_NAME,
    )


def _get_non_trivial_names(obj) -> list:
    """Return sorted list of attribute accessors (e.g. '$.x') for non-trivial names."""
    return sorted([f"$.{name}" for name in dir(obj) if name not in TRIVIAL_NAMES])


def _resolve_fields(obj) -> list:
    """Resolve fields using dotfile, defaults, then non-trivial names."""
    fields, _ = _resolve_fields_and_children(obj, None, None)
    return list(fields)


def _resolve_fields_and_children(obj, slots_config, config_path):
    """Return (fields, slot_children) for an object at this nesting position.

    At the root (config_path is None) the dotfile is read by class. When nested,
    only the parent-supplied slots_config is used -- the type config is NOT
    re-read, which is what breaks config-driven recursion. A missing config
    falls back to DEFAULT_FIELDS_FOR_TYPE, then non-trivial dir() names (value-
    driven recursion there is bounded by the depth cap).
    """
    full_class_name = get_full_class_name(obj)

    if config_path is None:
        loaded = load_fields_from_dotfile(full_class_name)
    else:
        loaded = slots_config

    if loaded is not None:
        return parse_slots(loaded, expr_transform=_ensure_dollar_prefix)

    default = DEFAULT_FIELDS_FOR_TYPE.get(full_class_name)
    if default is not None:
        return parse_slots(default, expr_transform=_ensure_dollar_prefix)

    return list(_get_non_trivial_names(obj)), {}


def _get_autocomplete_suggestions(obj, current_fields: list, input_value: str) -> list:
    """
    Return autocomplete suggestions: non-trivial names not already shown,
    filtered by input_value prefix.
    """
    all_names = _get_non_trivial_names(obj)
    existing = set(current_fields)
    suggestions = [name for name in all_names if name not in existing]
    if input_value:
        suggestions = [name for name in suggestions if name.startswith(input_value)]
    return suggestions


def _eval_field(obj, accessor_code: str, eval_in_scope=None):
    """
    Evaluate an accessor code against an object.

    Returns (placeholder_args, value_str, raw_value, is_error) tuple.
    placeholder_args suggest what the arguments are for callables.
    raw_value is the actual Python value (None on error or callable).
    is_error is True if evaluation raised an exception.
    """
    try:
        val = eval_dollar_expr(accessor_code, obj, eval_in_scope)
        val_str = None
    except Exception as e:
        return ('', str(e), None, True)

    if callable(val):
        placeholder_args = getattr(val, '__text_signature__', None) or '(...)'
        val_str = val.__doc__.split('\n', 1)[0] if val.__doc__ else None
        if val_str is None:
            val_str = repr(val)[:200]
        return (placeholder_args, val_str, None, False)

    placeholder_args = ''
    if val_str is None:
        val_str = repr(val)[:200]

    return (placeholder_args, val_str, val, False)


# === Elm architecture functions ===

def init_model(value, get_visualizer=None, eval_in_scope=None, var_and_exp=None,
               slots_config=None, config_root_type=None, config_root_dotfile=None,
               config_path=None):
    """
    Initialize the model state for a new visualization.

    Priority for fields: (nested config | dotfile) > DEFAULT_FIELDS_FOR_TYPE >
    non-trivial dir() names. Nested calls use the parent-supplied slots_config
    and never re-read the type dotfile (breaks config-driven recursion).
    """
    source_expr = None
    if var_and_exp:
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else expr

    is_root = config_path is None
    root_type = config_key(value) if is_root else config_root_type
    root_dotfile = DOTFILE_NAME if is_root else config_root_dotfile
    path = [] if is_root else config_path
    config_fields = {
        "_config_root_type": root_type,
        "_config_root_dotfile": root_dotfile,
        "_config_path": path,
        "_slot_children": {},
    }

    if value is None or isinstance(value, (int, float)):
        return {
            "fields": [],
            "editing_index": None,
            "adding_field": False,
            "input_value": "",
            "selected_suggestion_index": None,
            "drag_from_index": None,
            "drag_over_index": None,
            "children": {},
            "handledKeys": list(_OWN_KEYS),
            "_source_expr": source_expr,
            **config_fields,
        }

    fields, slot_children = _resolve_fields_and_children(value, slots_config, config_path)
    config_fields["_slot_children"] = slot_children

    # Depth backstop: beyond the cap, stop building nested children entirely
    # (renders as a truncated repr) so cyclic objects can't RecursionError.
    if too_deep(path):
        return {
            "fields": fields,
            "editing_index": None,
            "adding_field": False,
            "input_value": "",
            "selected_suggestion_index": None,
            "drag_from_index": None,
            "drag_over_index": None,
            "children": {},
            "handledKeys": list(_OWN_KEYS),
            "_source_expr": source_expr,
            "_too_deep": True,
            **config_fields,
        }

    children = {}
    if get_visualizer is not None:
        for accessor_code in fields:
            placeholder_args, val_str, raw_value, is_error = _eval_field(value, accessor_code, eval_in_scope)
            if not is_error and not placeholder_args and raw_value is not None:
                child_vis = get_visualizer(raw_value)
                extra = (child_nesting_kwargs(config_fields, accessor_code, raw_value)
                         if getattr(child_vis, 'SUPPORTS_NESTED_CONFIG', False) else {})
                children[accessor_code] = child_vis.init_model(raw_value, get_visualizer,
                                                               eval_in_scope=eval_in_scope, **extra)

    handled_keys = aggregate_handled_keys(children, _OWN_KEYS)

    return {
        "fields": fields,
        "editing_index": None,
        "adding_field": False,
        "input_value": "",
        "selected_suggestion_index": None,
        "drag_from_index": None,
        "drag_over_index": None,
        "children": children,
        "handledKeys": handled_keys,
        "_source_expr": source_expr,
        **config_fields,
    }


def update(event, var_and_exp, model: dict, value, get_visualizer=None, eval_in_scope=None) -> Tuple[dict, List[Any]]:
    """
    Update model based on event. Returns (new_model, commands) tuple.

    Args:
        event: The UI event to process
        var_and_exp: (var_name | None, expression) tuple from the source line
        model: The current model state
        value: The object being visualized
    """
    commands: List[Any] = []

    if event is None or event.get('pythonEventStr', '') == '' or event.get('eventJSON', '') == '':
        return (model, commands)

    make_python_event = eval(event['pythonEventStr'])
    event_json = event['eventJSON']
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event

    if msg is None:
        return (model, commands)

    if isinstance(msg, ChildEvent) and get_visualizer is not None:
        _obj_ref = value
        def _child_value_getter(accessor_key, _obj=_obj_ref):
            return eval_dollar_expr(accessor_key, _obj, eval_in_scope)
        new_model, child_cmds = route_child_event(
            event, model, value, _child_value_getter, get_visualizer,
            # The field's value is bound to a name for the child, so the code it
            # generates is dollar-free and about the FIELD rather than the object.
            var_and_exp=(None, CHILD_SOURCE_BINDER),
            eval_in_scope=eval_in_scope,
        )
        # Resolve the binder back to this field. Unlike a list column - which is
        # stored row-generically - an object visualizer's generated code goes
        # straight to the editor, same as its clipboard text, so the accessor is
        # resolved all the way to a concrete path for both.
        field_expr = replace_dollars_in_py_exp(
            msg.child_key, [model.get('_source_expr') or link_source_expr(var_and_exp) or 'obj'])
        child_cmds = [nest_child_command(cmd, field_expr, field_expr)
                      for cmd in child_cmds]
        new_model['handledKeys'] = aggregate_handled_keys(new_model.get('children', {}), _OWN_KEYS)
        return (new_model, child_cmds)

    full_class_name = get_full_class_name(value) if value is not None and not isinstance(value, (int, float)) else None

    match msg:
        case AddFieldClick():
            model['adding_field'] = True
            model['input_value'] = ''
            model['editing_index'] = None

        case FieldInput(value=val):
            model['input_value'] = val
            # Auto-highlight first matching suggestion so user can Tab/Enter immediately
            if val and value is not None:
                suggestions = _get_autocomplete_suggestions(value, model.get('fields', []), val)
                model['selected_suggestion_index'] = 0 if suggestions else None
            else:
                model['selected_suggestion_index'] = None

        case FieldSelect(accessor=accessor):
            if model.get('adding_field'):
                model['fields'].append(accessor)
                model['adding_field'] = False
                model['input_value'] = ''
                if full_class_name:
                    _save_slots(model)
            elif model.get('editing_index') is not None:
                idx = model['editing_index']
                if 0 <= idx < len(model['fields']):
                    model['fields'][idx] = accessor
                model['editing_index'] = None
                model['input_value'] = ''
                if full_class_name:
                    _save_slots(model)

        case RemoveFieldClick(index=idx):
            if 0 <= idx < len(model['fields']):
                removed_accessor = model['fields'].pop(idx)
                # Clean up child model for the removed field
                children = model.get('children', {})
                children.pop(removed_accessor, None)
                # Cancel editing if the removed field was being edited
                if model.get('editing_index') is not None:
                    if model['editing_index'] == idx:
                        model['editing_index'] = None
                        model['input_value'] = ''
                    elif model['editing_index'] > idx:
                        model['editing_index'] -= 1
                if full_class_name:
                    _save_slots(model)

        case DragStart(index=idx):
            if 0 <= idx < len(model['fields']):
                model['drag_from_index'] = idx
                model['drag_over_index'] = idx

        case DragOver(index=idx):
            if model.get('drag_from_index') is not None:
                if event_json.get('buttons', 0) == 0:
                    # Mouse released outside a DragEnd target — cancel drag
                    model['drag_from_index'] = None
                    model['drag_over_index'] = None
                else:
                    model['drag_over_index'] = idx

        case DragEnd(index=idx):
            drag_from = model.get('drag_from_index')
            if drag_from is not None and 0 <= drag_from < len(model['fields']):
                target = idx
                if drag_from != target:
                    field = model['fields'].pop(drag_from)
                    model['fields'].insert(target, field)
                    if full_class_name:
                        _save_slots(model)
            model['drag_from_index'] = None
            model['drag_over_index'] = None

        case FieldClick(index=idx):
            detail = event_json.get('detail', 1)
            if detail >= 2:
                # Double-click: start editing this field
                if 0 <= idx < len(model['fields']):
                    model['editing_index'] = idx
                    model['input_value'] = model['fields'][idx]
                    model['adding_field'] = False

        case KeyDown():
            key = event_json.get('key', '')
            is_input_active = model.get('adding_field') or model.get('editing_index') is not None

            if key == 'ArrowDown' and is_input_active:
                # Compute suggestions to know the count
                suggestions = _get_autocomplete_suggestions(value, model.get('fields', []), model.get('input_value', '')) if value is not None else []
                if suggestions:
                    cur = model.get('selected_suggestion_index')
                    if cur is None:
                        model['selected_suggestion_index'] = 0
                    else:
                        model['selected_suggestion_index'] = (cur + 1) % min(len(suggestions), 10)

            elif key == 'ArrowUp' and is_input_active:
                suggestions = _get_autocomplete_suggestions(value, model.get('fields', []), model.get('input_value', '')) if value is not None else []
                if suggestions:
                    cur = model.get('selected_suggestion_index')
                    count = min(len(suggestions), 10)
                    if cur is None:
                        model['selected_suggestion_index'] = count - 1
                    else:
                        model['selected_suggestion_index'] = (cur - 1) % count

            elif key in ('Enter', 'Tab'):
                # If a suggestion is selected, commit it
                sel_idx = model.get('selected_suggestion_index')
                if sel_idx is not None and is_input_active:
                    suggestions = _get_autocomplete_suggestions(value, model.get('fields', []), model.get('input_value', '')) if value is not None else []
                    capped = suggestions[:10]
                    if 0 <= sel_idx < len(capped):
                        commit_val = capped[sel_idx]
                    else:
                        commit_val = model.get('input_value', '').strip()
                else:
                    commit_val = model.get('input_value', '').strip()

                if model.get('adding_field'):
                    if commit_val:
                        model['fields'].append(commit_val)
                        if full_class_name:
                            _save_slots(model)
                    model['adding_field'] = False
                    model['input_value'] = ''
                    model['selected_suggestion_index'] = None
                elif model.get('editing_index') is not None:
                    idx = model['editing_index']
                    if commit_val and 0 <= idx < len(model['fields']):
                        model['fields'][idx] = commit_val
                        if full_class_name:
                            _save_slots(model)
                    model['editing_index'] = None
                    model['input_value'] = ''
                    model['selected_suggestion_index'] = None

            elif key == 'Escape':
                model['adding_field'] = False
                model['editing_index'] = None
                model['input_value'] = ''
                model['selected_suggestion_index'] = None

    return (model, commands)


_CHAR_PX = 7.7
_LINE_PX = 18



def _is_dunder(key):
    """Check if a display key like '.foo' is a dunder attribute."""
    name = key.lstrip('.')
    return name.startswith('__') and name.endswith('__')


def render_small_field(display_key: str, val_repr: str, expr: str, add_target: str = None) -> str:
    """Render a single interactive field chip: key=value, draggable with snc-py-exp."""
    exp_attr = f' snc-py-exp="{html.escape(expr)}" draggable="true"'
    add_attr = ''
    if add_target:
        add_attr = (f' snc-add-at-cursor="{html.escape(expr)}"'
                    f' snc-add-target="{html.escape(add_target)}"')
    return (
        f'<span{exp_attr}{add_attr} class="py-exp-grab">'
        f'<span class="field">{html.escape(display_key)}</span>'
        f'<span class="punct">=</span>'
        f'{html.escape(val_repr)}'
        f'</span>'
    )


def _visualize_small(obj, model, eval_in_scope, max_width=None, max_height=None):
    short_class_name = type(obj).__name__
    fields = model.get('fields', [])
    source_expr = model.get('_source_expr')
    add_target = model.get('_add_target')

    chars_per_line = int(max_width / _CHAR_PX) if max_width else 120
    num_lines = max(1, int(max_height / _LINE_PX)) if max_height else 20
    total_budget = chars_per_line * num_lines
    single_line = (num_lines <= 1)

    prefix = short_class_name + '('
    suffix = ')'
    remaining_budget = total_budget - len(prefix) - len(suffix)

    pairs = []
    for accessor_code in fields:
        placeholder_args, val_str, raw_value, is_error = _eval_field(obj, accessor_code, eval_in_scope)
        if placeholder_args:
            continue
        key = accessor_code
        stripped = strip_leading_dollar(accessor_code)
        if _is_dunder(stripped):
            continue
        pairs.append((key, val_str, is_error, accessor_code))

    shown = []
    budget_used = 0
    for i, (key, val, is_error, acc) in enumerate(pairs):
        remaining_pairs = len(pairs) - i
        ellipsis_str = f', +{remaining_pairs}' if remaining_pairs > 1 else ''
        sep = ', ' if shown else ''

        val_max = min(30, max(remaining_budget - budget_used - len(sep) - len(key) - 1 - len(ellipsis_str), 8))
        truncated_val = truncate_str(val, val_max)
        pair_text = f'{sep}{key}={truncated_val}'

        if budget_used + len(pair_text) + len(ellipsis_str) > remaining_budget and shown:
            overflow = len(pairs) - len(shown)
            shown.append(('_overflow', str(overflow), False, ''))
            break
        shown.append((key, truncated_val, is_error, acc))
        budget_used += len(pair_text)

    parts = [f'<span class="name">{html.escape(short_class_name)}</span>'
             f'<span class="punct">(</span>']
    for idx, (key, val, is_error, acc) in enumerate(shown):
        if idx > 0:
            parts.append('<span class="punct">, </span>')
        if key == '_overflow':
            parts.append(f'<span class="punct">+{html.escape(val)}</span>')
        elif source_expr and not is_error:
            field_expr = replace_dollars_in_py_exp(acc, [source_expr])
            parts.append(render_small_field(key, val, field_expr, add_target))
        else:
            parts.append(f'<span class="field">{html.escape(key)}</span>')
            parts.append('<span class="punct">=</span>')
            if is_error:
                parts.append(f'<span class="error">{html.escape(val)}</span>')
            else:
                parts.append(html.escape(val))
    parts.append('<span class="punct">)</span>')

    content = ''.join(parts)

    dyn_style = ''
    if max_width:
        dyn_style += f'max-width:{max_width}px;'
    if max_height:
        dyn_style += f'max-height:{max_height}px;'
    if single_line:
        dyn_style += 'white-space:nowrap;text-overflow:ellipsis;'
    style_attr = f' style="{dyn_style}"' if dyn_style else ''

    return f'<span class="small"{style_attr}>{content}</span>'


def visualize(obj, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, var_and_exp=None):
    """
    Render the object as HTML with configurable field inspection.

    Objects render as a table of accessor → value with interactive controls.
    """

    if obj is None or isinstance(obj, (int, float)):
        return repr(obj)

    # Depth-capped leaf: render a plain truncated repr instead of a nested table.
    if model.get('_too_deep'):
        return f'<span class="small">{html.escape(truncate_str(repr(obj), 200))}</span>'

    if small:
        # No whole-area drag handle for the object expression: the field chips
        # carry their own snc-py-exp, and a handle around them would claim every
        # hover over them. Only the generic visualizers self-wrap.
        return _visualize_small(obj, model, eval_in_scope, max_width, max_height)

    full_class_name = get_full_class_name(obj)
    source_expr = model.get('_source_expr')

    field_trs = []

    for i, accessor_code in enumerate(model.get('fields', [])):
        if model.get('editing_index') == i:
            field_trs.append(_render_input_row(obj, model, is_editing=True, editing_index=i, eval_in_scope=eval_in_scope))
        else:
            placeholder_args, val_str, raw_value, is_error = _eval_field(obj, accessor_code, eval_in_scope)
            click_event = repr(FieldClick(index=i))
            remove_event = repr(RemoveFieldClick(index=i))
            drag_start_event = repr(DragStart(index=i))
            drag_over_event = repr(DragOver(index=i))
            drag_end_event = repr(DragEnd(index=i))

            can_extract = source_expr and not is_error and not placeholder_args
            if can_extract:
                field_expr = replace_dollars_in_py_exp(accessor_code, [source_expr])
                exp_attr = f' snc-py-exp="{html.escape(field_expr)}" draggable="true"'
            else:
                exp_attr = ''

            children = model.get('children', {})
            focused_child = model.get('focused_child')
            if not is_error and not placeholder_args and raw_value is not None and get_visualizer is not None:
                child_vis = get_visualizer(raw_value)
                child_model = children.get(accessor_code)
                if child_model is None:
                    extra = (child_nesting_kwargs(model, accessor_code, raw_value)
                             if getattr(child_vis, 'SUPPORTS_NESTED_CONFIG', False) else {})
                    child_model = child_vis.init_model(raw_value, get_visualizer,
                                                       eval_in_scope=eval_in_scope, **extra)
                child_small = (accessor_code != focused_child)

                # The parent doesn't wrap children for drag: each is handed its
                # access-path expression and decides for itself, so a child with
                # its own handles keeps them instead of being covered by one.
                child_expr = field_expr if can_extract else None
                child_var_and_exp = (None, child_expr) if child_expr else None
                child_html = child_vis.visualize(raw_value, child_model, get_visualizer, eval_in_scope, max_width=500, small=child_small, var_and_exp=child_var_and_exp)
                child_wrapped = wrap_child_html(child_html, accessor_code)
                value_td = f'<td>{child_wrapped}</td>'
            else:
                if exp_attr:
                    value_td = f'<td><span{exp_attr} class="py-exp-grab">{html.escape(val_str)}</span></td>'
                else:
                    value_td = f'<td>{html.escape(val_str)}</td>'

            drag_from = model.get('drag_from_index')
            drag_over = model.get('drag_over_index')
            is_drag_source = (drag_from == i)
            is_drag_target = (drag_from is not None
                              and drag_over == i
                              and drag_from != i)
            drag_cls = ' drag-source' if is_drag_source else ''
            if is_drag_target:
                drag_cls += ' drag-above' if drag_from > drag_over else ' drag-below'

            field_trs.append(
                f'<tr class="snc-hover-hidden-parent{drag_cls}" '
                f'snc-mouse-move="{html.escape(drag_over_event)}" '
                f'snc-mouse-up="{html.escape(drag_end_event)}">'
                f'<td snc-mouse-down="{html.escape(drag_start_event)}" '
                f'data-tooltip="Drag to reorder" '
                f'class="handle full-opacity-on-hover">'
                f'<span class="snc-hover-hidden">☰</span></td>'
                f'<td snc-mouse-down="{html.escape(remove_event)}" '
                f'data-tooltip="Remove attribute" '
                f'class="remove full-opacity-on-hover">'
                f'<span class="snc-hover-hidden">×</span></td>'
                f'<td snc-mouse-down="{html.escape(click_event)}" class="field-name">'
                f'{html.escape(strip_leading_dollar(accessor_code))}<span class="field-args">{html.escape(placeholder_args)}</span></td>'
                f'{value_td}'
                f'</tr>'
            )

    if model.get('adding_field'):
        field_trs.append(_render_input_row(obj, model, is_editing=False, eval_in_scope=eval_in_scope))

    field_trs_str = '\n'.join(field_trs)

    add_event = repr(AddFieldClick())
    add_button = (
        f'<tr snc-mouse-down="{html.escape(add_event)}" data-tooltip="Add attribute" class="snc-hover-hidden-parent">'
        f'<td style="min-width:0.8em"></td><td style="min-width:1em"></td>'
        f'<td class="snc-hover-hide-border full-opacity-on-hover add" colspan=2>'
            f'<span class="snc-hover-hidden add-icon">+</span>'
        f'</td>'
        f'</tr>'
    )

    key_handler = repr(KeyDown())
    return (
        f'<div tabindex="0" snc-key-down="{html.escape(key_handler)}" class="visualizer-container">'
        f'<div class="obj-visualizer">'
        f'<h4>{html.escape(full_class_name)} {html.escape(repr(obj))}</h4>'
        f'<table>'
        f'{field_trs_str}'
        f'{add_button}'
        f'</table>'
        f'</div></div>'
    )


def _render_input_row(obj, model, is_editing: bool, editing_index: int = -1, eval_in_scope=None):
    """
    Render a table row with a text input for adding or editing a field.

    Shows the input field, autocomplete suggestions below, and a live-evaluated
    value in the second column.
    """
    input_value = model.get('input_value', '')
    input_event = "lambda e: FieldInput(value=e.get('value', ''))"

    # Evaluate current input as accessor to show live value
    if input_value.strip():
        _, val_str, _, _ = _eval_field(obj, input_value, eval_in_scope)
    else:
        val_str = ''

    # Build autocomplete suggestions
    current_fields = model.get('fields', [])
    suggestions = _get_autocomplete_suggestions(obj, current_fields, input_value)
    selected_idx = model.get('selected_suggestion_index')

    suggestion_html = ''
    if suggestions:
        items = []
        for i, suggestion in enumerate(suggestions[:10]):
            select_event = repr(FieldSelect(accessor=suggestion))
            is_selected = (selected_idx == i)
            sel_cls = ' selected' if is_selected else ''
            scroll_attr = ' snc-scroll-into-view' if is_selected else ''
            items.append(
                f'<div snc-mouse-down="{html.escape(select_event)}" '
                f'class="snc-dropdown-option{sel_cls}"'
                f'{scroll_attr}'
                f'>{html.escape(suggestion)}</div>'
            )
        suggestion_html = (
            f'<div class="snc-dropdown-panel left" snc-dropdown-align="left">'
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
        f'placeholder="$.field_name" '
        f'spellcheck="false"'
        f'{extra_attrs} '
        f'class="obj-input" />'
        f'{suggestion_html}'
        f'</span>'
    )

    return (
        f'<tr>'
        f'<td></td><td></td>'
        f'<td style="padding-right:8px;">'
        f'{input_html}'
        f'</td>'
        f'<td>{html.escape(val_str)}</td>'
        f'</tr>'
    )
