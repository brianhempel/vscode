"""Shared utilities for visualizer composition in Sculpt-n-Code."""

import ast
import dataclasses
import functools
import html
import inspect
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple


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
    """Truncate a string, showing beginning + … + end if too long."""
    if len(s) <= max_len:
        return s
    half = max_len // 2
    if max_len >= 5:
        return s[:half] + '…' + s[-half + 1:]
    return s[:max(max_len - 1, 0)] + '…'


def safe_repr(value):
    """HTML-escape repr(value), returning an error span on failure."""
    try:
        return html.escape(repr(value))
    except Exception:
        return f'<span style="color: {ERROR_RED};">[Error]</span>'


def span(text, color):
    """Wrap text in a colored <span>."""
    return f'<span style="color: {color};">{text}</span>'


def nerd_font_icon(glyph: str, size: int = 12) -> str:
    """Wrap a Pragmasevka nerd-font glyph so it renders in the icon font."""
    return f'<span style="font-family:Pragmasevka;font-size:{size}px">{glyph}</span>'


def render_tool_toolbar(tools, current: str, make_event, *, disabled=()) -> str:
    """Render the upper-right tool toolbar shared by the visualizers.

    The string visualizer offers literal/fuzzy/index/pick; the list visualizer
    offers normal/pick. Only the tool list differs, so the markup lives here.

    Args:
      tools: sequence of (tool_id, icon_html, display_name). icon_html is
        emitted verbatim -- callers escape their own labels, because some are
        plain text ('ab') and some are pre-rendered icon spans.
      current: the active tool id, which gets the .active class.
      make_event: tool_id -> the repr'd event string for snc-mouse-down. Taken
        as a callback because each visualizer defines its own ToolSelect type,
        and the string is eval'd in that module's namespace.
      disabled: tool ids to render dimmed and click-inert (no handler at all).
    """
    btns = []
    for tool, icon_html, name in tools:
        cls = 'tool-button'
        if tool == current:
            cls += ' active'
        is_disabled = tool in disabled
        if is_disabled:
            cls += ' dimmed'
        # Right-aligned tooltip: the toolbar sits in the upper-right corner,
        # where there is empty editor space to the right.
        attrs = (f'class="{cls}" data-tool="{tool}" '
                 f'data-tooltip="{html.escape(name)}" data-tooltip-align="right"')
        if is_disabled:
            btns.append(f'<span {attrs}>{icon_html}</span>')
        else:
            event = html.escape(make_event(tool))
            btns.append(f'<span {attrs} snc-mouse-down="{event}">{icon_html}</span>')
    return f'<div class="tool-toolbar">{"".join(btns)}</div>'


# How tall a pane opened by the expand toggle is allowed to get. The string
# visualizer sizes its pane in CSS (.visualizer-container.expanded
# .string-visualizer, in string-visualizer.css) and repeats the number there;
# the table works its height out here, so it reads it from Python.
EXPANDED_PANE_MAX_HEIGHT = 600


def render_expand_toggle(expanded: bool, event: str, *, small: bool = False) -> str:
    """Render the full-width bar under a pane that is clipping its content.

    Offered by the string and list visualizers when the collapsed pane doesn't
    show everything. What opening one costs is each visualizer's own business
    (the string lifts a CSS max-height, the table recomputes its inline one);
    this draws the bar, points the chevron, and reports the click.

    The open/closed class sits on the bar rather than on the visualizer's
    container, so a container holding children -- a table's cells -- doesn't
    hand their panes a state that isn't theirs.

    Args:
      expanded: whether the pane is open, which picks the tooltip and turns
        the chevron over.
      event: the repr'd event string for snc-mouse-down. Taken as a string
        because each visualizer defines its own ExpandToggle type, and it is
        eval'd in that module's namespace.
      small: whether this is the non-focused preview, where the bar is the one
        control still offered. There it opts out of click-to-focus
        (snc-unfocused-clickable, see snc.ts) so a tall value can be peeked at
        without pinning focus to its line, and out of dragging, so a click the
        user slipped on isn't read as a drag of the cell around it.
    """
    preview_attrs = ' draggable="false" snc-unfocused-clickable' if small else ''
    return (
        f'<div class="expand-toggle{" expanded" if expanded else ""}"{preview_attrs}'
        f' snc-mouse-down="{html.escape(event)}"'
        f' data-tooltip="{"Collapse" if expanded else "Expand"}">'
        f'<span class="chevron">⌄</span></div>'
    )


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
# object, evaluated on the object); in both cases `$` denotes "a value of type
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
    config); for a dict it's the pair of types its entries hold, written
    `K->V`; for everything else the value's own class. An empty list or dict
    has no key.

    The dict branch is a deliberate exception to `config_key(x) ==
    config_key([x])`. A list of dicts keys on `builtins.dict` -- its ELEMENT
    class -- while a bare dict keys on `str->int`, because otherwise every dict
    in a program would share one saved column config no matter what it held.
    Different axes, deliberately not shared.
    """
    if isinstance(value, list):
        if not value:
            return None
        return get_full_class_name(value[0])
    if isinstance(value, dict):
        if not value:
            return None
        k, v = next(iter(value.items()))
        return f'{get_full_class_name(k)}->{get_full_class_name(v)}'
    return get_full_class_name(value)


def parse_slots(slots_config, expr_transform=None):
    """Split a slot list into (exprs, slot_children).

    slot_children maps a slot's expr -> its {T2: [slot, ...]} children map
    (only for slots that actually carry children). Bare-string entries are
    treated as childless slots. `expr_transform` is applied to each expr (used
    by the object visualizer to ensure a leading dollar).
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


def parse_slot_cols(slots_config) -> dict:
    """A slot's SUB-COLUMNS, keyed by slot expr -- {expr: [col, ...]}.

    Only splat slots carry these: `{'expr': '*$.members', 'cols': [...]}`, the
    columns written against ONE splatted element. Read apart from parse_slots
    because `children` and `cols` are different axes -- `children` is a nested
    visualizer's own config keyed by TYPE, `cols` is this table's sub-columns --
    and conflating them would let one overwrite the other.

    Slots without sub-columns are absent rather than present-and-empty, so a
    caller can ask `expr in cols` and mean it.
    """
    out = {}
    for entry in (slots_config or []):
        if not isinstance(entry, dict) or 'expr' not in entry:
            continue
        cols = entry.get('cols')
        if isinstance(cols, list) and cols:
            # A sub-column is a bare expression, or -- when it splats in turn --
            # an entry with `cols` of its own. Both are kept; the caller is what
            # knows how deep it is willing to go.
            out[entry['expr']] = [c for c in cols
                                  if isinstance(c, str)
                                  or (isinstance(c, dict) and 'expr' in c)]
    return out


def too_deep(config_path) -> bool:
    """True when nesting has reached the depth cap (a backstop against cyclic
    values that would otherwise RecursionError)."""
    return len(config_path or []) >= MAX_NEST_DEPTH


@functools.lru_cache(maxsize=None)
def keyword_params(fn: Callable, drop_first: bool = False) -> Optional[FrozenSet[str]]:
    """The names `fn` accepts as keyword arguments, or None for "anything".

    None means the signature is a blank check -- either it takes **kwargs, or
    it can't be introspected at all (some builtins), in which case the call
    itself is the better judge than a guess made here. `drop_first` discards
    the leading `self` of a method being inspected through its class.
    """
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None
    if drop_first:
        params = params[1:]
    if any(p.kind is p.VAR_KEYWORD for p in params):
        return None
    return frozenset(p.name for p in params
                     if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))


def _keyword_params_of(fn: Callable) -> Optional[FrozenSet[str]]:
    # Cache on the underlying function: attribute access on a visualizer object
    # makes a fresh bound method each time, but they all share one __func__
    # (and caching the method would pin its instance in the cache forever).
    unbound = getattr(fn, '__func__', None)
    if unbound is not None:
        return keyword_params(unbound, True)
    return keyword_params(fn)


def wants_kwarg(fn: Callable, name: str) -> bool:
    """True when `fn` would accept `name` as a keyword argument.

    Ask before computing an argument that most callees don't want -- in a table
    this is asked once per cell.
    """
    accepted = _keyword_params_of(fn)
    return accepted is None or name in accepted


def supported_kwargs(fn: Callable, **kwargs) -> dict:
    """Drop the kwargs `fn` doesn't ask for by name.

    Lets a caller offer every optional thing a visualizer function might want
    (nested config, eval_in_scope, ...) while a visualizer author opts in by
    simply naming the parameter -- no capability constant to also declare.
    """
    accepted = _keyword_params_of(fn)
    if accepted is None or kwargs.keys() <= accepted:
        return kwargs
    return {name: value for name, value in kwargs.items() if name in accepted}


def call_with_supported_kwargs(fn: Callable, *args, **kwargs):
    """Call `fn`, passing only the keyword arguments it asks for."""
    return fn(*args, **supported_kwargs(fn, **kwargs))


def child_nesting_kwargs(parent_model: dict, slot_expr: str, cell_value,
                         child_init_model: Optional[Callable] = None) -> dict:
    """Compute the nesting kwargs to hand a child (sub-)visualizer.

    The child receives the slot's nested config for the cell's type (or None ->
    default), the inherited root type/dotfile, and the path extended by this
    (slot_expr, cell_type) step (so it can persist edits at its own location).

    A visualizer opts into all this by naming the parameters in its init_model;
    pass that function as `child_init_model` and a child that doesn't ask for
    them gets {} (and pays nothing for it -- this runs once per cell).
    """
    if child_init_model is not None and not wants_kwarg(child_init_model, 'slots_config'):
        return {}
    children_map = (parent_model.get('_slot_children') or {}).get(slot_expr) or {}
    t2 = config_key(cell_value)
    slots_config = children_map.get(t2) if t2 is not None else None
    kwargs = {
        'slots_config': slots_config,
        'config_root_type': parent_model.get('_config_root_type'),
        'config_root_dotfile': parent_model.get('_config_root_dotfile'),
        'config_path': (parent_model.get('_config_path') or []) + [(slot_expr, t2)],
    }
    if child_init_model is None:
        return kwargs
    return supported_kwargs(child_init_model, **kwargs)


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
    for entry in exprs:
        # An entry is either a bare expr or a slot carrying this table's own
        # keys (`cols`). Either way the slot already on disk is reused when
        # there is one, so its `children` -- a nested visualizer's config,
        # which the caller knows nothing about -- survives untouched.
        expr = entry['expr'] if isinstance(entry, dict) else entry
        existing = _find_slot(old, expr)
        slot = existing if existing is not None else {'expr': expr}
        if isinstance(entry, dict):
            for key, value in entry.items():
                if key != 'expr':
                    slot[key] = value
        rebuilt.append(slot)
    target[:] = rebuilt

    _save_dotfile_dict(dotfile_name, data)


# =============================================================================
# Dollar ($) utilities
# =============================================================================

# $ is not a Python token at all, so it can only appear legally inside a string
# literal. replace only $ that are in variable position (not in strings, etc)
# does this by replace-and-check one by one to see if parse succeeds with the $ retained
#
# A trailing letter makes the token something ABOUT the value rather than the
# value: `$i` its index, `$k` a key, `$v` a value, `$j` a position within a
# splat. Each carries its own boundary, so `$item` is still a dollar beside a
# variable the program might have, `$i2` a dollar beside that name, and `$key`
# and `$ki` likewise -- only the bare letter is a sigil. A dollar RUN says how
# far out to look, and none of these is a scope of its own, so a sigil is never
# a run: see replace_dollars_in_py_exp.
#
# The two halves are captured so the token doesn't have to be taken apart by
# rstrip afterwards -- which read `$k` as a run of depth 2 and was the defect
# every consumer of this pattern shared. Group 1 is the run, group 2 the sigil
# or None. There is deliberately no `$ki`, so the character class needs no
# longest-first ordering.
DOLLARS_RE = re.compile(r'(?<!\$)(\$+)(?!\$)(?:([ijkv])(?![A-Za-z0-9_]))?')

# replace_exps should be array, where replace_exps[0] is the replacement for $, replace_exps[1] for $$, etc
# replace_exps should not have dollars in them. if necessary, run this on them first
# a run naming a scope beyond replace_exps is left as written - the caller only
# knows the scopes it was given, and must not invent a binding for the rest
# bindings maps a sigil to the expression it stands for -- {'i': ..., 'k': ...}
# -- and binds at depth 1 only: a container has one row number and one key to
# give, so a sigil means the same thing at every depth rather than one per
# scope. `$$i` and `$$k` name nothing, and are left as written like any other
# run with no binding for them.
# index_exp is the older spelling of bindings={'i': ...}, kept because
# string_visualizer and z_object_visualizer call it that way.
def replace_dollars_in_py_exp(py_exp: str, replace_exps, index_exp=None,
                              bindings=None) -> str:
    binds = dict(bindings or {})
    if index_exp is not None:
        binds.setdefault('i', index_exp)
    temp_names = {} # temp name to the dollar token it stands for
    def temp_replacer(m):
        temp_name = f'_{len(m[0])}dollars_{len(temp_names)}_'
        temp_names[temp_name] = m[0]
        return temp_name
    out = DOLLARS_RE.sub(temp_replacer, py_exp)

    for name, token in temp_names.items():
        try:
            temp_str = out.replace(name, token)
            ast.parse(temp_str)
            out = temp_str # parse succeeded, meaning the dollars were likely in a string and should not be replaced
        except SyntaxError:
            run, sigil = DOLLARS_RE.fullmatch(token).groups()
            n_dollars = len(run)
            if sigil is not None:
                # Sigils bind at depth 1 only, and an unbound one is left as
                # written -- which isn't Python, so the caller reads it as
                # "no value" rather than as something it can evaluate.
                bound = binds.get(sigil) if n_dollars == 1 else None
                out = out.replace(name, token if bound is None else bound)
            elif n_dollars <= len(replace_exps):
                out = out.replace(name, replace_exps[n_dollars-1])
            else:
                out = out.replace(name, token)

    return out


# A name no program has, standing in for the scopes while the question below is
# asked: a run left as written doesn't parse, and then every token after it would
# look like code too.
_NAMES_INDEX_PROBE = '_snc_names_i_'
_NAMES_INDEX_BINDER = '_snc_probe_'


# Bounded, unlike _is_pure_ref's: that one is keyed on a source expression,
# which changes when a line does, while this is keyed on text a box is being
# typed into -- a new key per keystroke, and only the last few ever asked again.
SIGILS = ('i', 'j', 'k', 'v')

# One probe per sigil, for the same reason as the pair above: a name no program
# has, so finding it in the result means the substitution bound it.
_SIGIL_PROBES = {s: f'_snc_sigil_{s}_' for s in SIGILS}


@functools.lru_cache(maxsize=1024)
def dollar_expr_sigils(expr: str) -> frozenset:
    """Which suffixed dollars *expr* actually binds.

    What every caller choosing a comprehension header has to know: `$v` alone
    wants `v in d.values()`, `$k` alone `k in d`, both `k, v in d.items()`.
    Asked through the substitution itself rather than by scanning for the
    characters, so a `$k` that is string content answers no for exactly the
    reason it isn't bound.

    Cached on the text: a column is one string asked after once per cell, and
    the answer is a parse of it.
    """
    depth = max((len(m[1]) for m in DOLLARS_RE.finditer(expr)), default=0)
    out = replace_dollars_in_py_exp(expr, [_NAMES_INDEX_BINDER] * depth,
                                    bindings=_SIGIL_PROBES)
    return frozenset(s for s, probe in _SIGIL_PROBES.items() if probe in out)


def dollar_expr_names_index(expr: str) -> bool:
    """Whether *expr* asks for the index of the value it is written against.

    What every caller choosing between `for item in lst` and
    `for i, item in enumerate(lst)` has to know. The one sigil most callers
    care about; the rest don't need the whole set.
    """
    return 'i' in dollar_expr_sigils(expr)


def dollar_expr_parses(s: str, mode: str = 'eval') -> bool:
    """Whether *s* is valid Python once every dollar run is read as a value.

    Used to validate text the user typed, which may name any number of scopes,
    so the levels are collapsed to one placeholder rather than bound.
    """
    try:
        ast.parse(s, mode=mode)
        return True
    except SyntaxError:
        pass
    if '$' not in s:
        return False
    try:
        ast.parse(DOLLARS_RE.sub('_dlr_', s), mode=mode)
        return True
    except SyntaxError:
        return False


# --- Nesting: how a child visualizer talks about its own value ----------------
#
# A dollar run names a scope: $ is the innermost value, $$ its parent, and so on.
# A list column or object field is written in ITS OWN scope, where $ is the row
# or the object. A child visualizer nested in one of those cells introduces a
# new innermost scope (the string visualizer binds $ to the current regex
# match), so the cell's own value is one scope out: $$.
#
# The child never emits dollars in generated code, though. The parent binds the
# cell value to CHILD_SOURCE_BINDER and hands that over as the child's source
# expression; the child generates ordinary dollar-free Python against it, and the
# parent swaps its own (dollar-bearing) expression back in via
# nest_generated_expr when it takes the code. That keeps replace_exps dollar-free
# everywhere and keeps generated code parseable at every intermediate step.
#
# In its own UI the child still SHOWS that value as $$, which is what the user
# reads in the replace box.

CHILD_SOURCE_BINDER = '_snc_cell_'
CHILD_SOURCE_DISPLAY = '$$'


def is_nested(var_and_exp) -> bool:
    """Whether a visualizer is running inside a parent's cell.

    A nested visualizer's code becomes a column or field in its parent rather
    than a line in the editor, so it never links: there is no line for it to
    own, and no chain icon on a cell to break the link with. Linking one would
    also rewrite editor text on every mouse event that crossed it.
    """
    return bool(var_and_exp) and var_and_exp[1] == CHILD_SOURCE_BINDER


def nest_generated_expr(expr: str, parent_expr: str) -> str:
    """Bring a child's generated code into the parent's scope.

    *parent_expr* is how the parent refers to the child's value in the parent's
    own scope (a list column, an object field accessor) and may contain dollars.
    """
    return expr.replace(CHILD_SOURCE_BINDER, f'({parent_expr})')


def new_code_command(result, code_imports=None) -> tuple:
    """A generated ``(suggest_name, code)`` pair as a NewCode command.

    An optional third slot says what the code can't run without: the visualizer
    that wrote it is the one that knows, so it declares it here rather than
    leaving the runner or the editor to read the text and guess. Whether the
    file already has those imports, and where a missing one would go, is the
    editor's to answer -- it is the only side that knows the file as it stands
    now.

    Code that needs nothing stays the pair it has always been, so "no third
    slot" reads as "nothing to add" everywhere the command travels.
    """
    imports = tuple(code_imports(result[1])) if code_imports else ()
    return (result[0], result[1], imports) if imports else (result[0], result[1])


def nest_child_command(cmd, code_expr: str, clipboard_expr: str):
    """Resolve the binder in one command coming back from a child visualizer.

    The two expressions differ by destination, not by scope depth. Generated
    code (a NewCode tuple) may be headed for the parent's own config, where a
    dollar expression is exactly right - a list column has to stay row-generic.
    Clipboard text is pasted into the editor verbatim, so it has to name the
    value concretely; a parent whose code_expr is already concrete passes the
    same expression twice.
    """
    if isinstance(cmd, tuple) and len(cmd) in (2, 3):
        # Rebinding the scope doesn't change what the code needs imported, so
        # any declaration travels up with it untouched.
        return (cmd[0], nest_generated_expr(cmd[1], code_expr), *cmd[2:])
    # Duck-typed: each visualizer declares its own CopyToClipboard.
    text = getattr(cmd, 'text', None)
    if isinstance(text, str) and CHILD_SOURCE_BINDER in text:
        return dataclasses.replace(cmd, text=nest_generated_expr(text, clipboard_expr))
    return cmd


def strip_leading_dollar(name: str) -> str:
    """Remove a single leading $ for display purposes."""
    if name.startswith('$'):
        return name[1:]
    return name


def eval_dollar_expr(field_expr: str, value, eval_in_scope=None, outer=(),
                     index=None, bindings=None):
    """Evaluate a $-prefixed field expression against a value.

    The value comes in as an argument and the expression is compiled in the
    user's scope, so a column like `$ * factor` can name their program's
    variables alongside the dollar. Without a scope to compile it in -- an
    unfocused preview, a test -- this module's globals are all there is, which
    is enough for an expression that only reaches through the dollar.

    *outer* is the enclosing scopes, innermost first: what `$$` stands for,
    then `$$$`, and so on. A caller with nothing outside the value passes none,
    and then a longer run is left as written -- which won't compile, the right
    answer for a dollar with nothing to bind.

    *index* is where the value sits in whatever it came out of, which is what
    `$i` names. It comes in as an argument like the value does, so a row number
    of 0 binds as readily as any other. A caller that has no index to give
    leaves `$i` unbound, which is the same answer as the run above.

    *bindings* is the same for the other sigils -- {'k': ..., 'v': ...} for a
    row of a dict -- as VALUES, so a column can be evaluated against a row that
    has a key as well as a value. `index=` is the older spelling of {'i': ...}.
    """
    names = ['_v'] + [f'_v{n}' for n in range(2, len(outer) + 2)]
    binds = dict(bindings or {})
    if index is not None:
        binds['i'] = index
    # `_b` prefixed so a $v binding can't land on top of _v, the value itself.
    binders = {sigil: f'_b{sigil}' for sigil in binds}
    body = replace_dollars_in_py_exp(field_expr, names, bindings=binders)
    ordered = list(binds)
    params = names + [binders[s] for s in ordered]
    code = f'(lambda {", ".join(params)}: {body})'
    args = (value, *outer) + tuple(binds[s] for s in ordered)
    return (eval(code) if eval_in_scope is None else eval_in_scope(code))(*args)


@dataclass(frozen=True, slots=True)
class ChildEvent:
    """Envelope wrapping a child visualizer's event for parent routing."""
    child_key: str
    py_ev_str: str

@dataclass(frozen=True, slots=True)
class Unlink:
    """Sent by the TypeScript front-end when an editor-visualizer link is broken."""
    pass

@dataclass(frozen=True, slots=True)
class Relink:
    """Sent by the TypeScript front-end when the user re-establishes a link via
    the chain icon.

    mode is either:
      - 'takeover': the front-end already linked an existing assignment line;
        the visualizer should replace its right-hand side (emit
        ChangeSelectedText).
      - 'insert':   there was no assignable line to take over; the visualizer
        should insert a fresh linked line (emit a NewCode tuple).

    text is the content of the taken-over line (only meaningful for takeover
    mode); a fresh model uses it to adopt the existing line instead of
    clobbering it with a default-generated expression.
    """
    mode: str = 'insert'
    text: str = ''


# Visualizers generate statements as bare headers (`for item in xs:`), because
# the header is what an editor link owns and rewrites; the body below it belongs
# to the user. These two helpers re-attach a placeholder body wherever the code
# has to stand on its own: insertion, clipboard, and syntax validation.

BLOCK_INDENT = '    '

def opens_block(code: str) -> bool:
    """Whether generated *code* ends with a `:` header and so needs a body."""
    return code.rstrip().endswith(':')


def with_pass_body(code: str) -> str:
    """Append a `pass` body to *code* when it opens a block, else return it as is.

    The body is indented one level past the last (deepest) header line, so a
    nested header like `for ...:\\n    if ...:` gets its `pass` at two levels.
    """
    if not opens_block(code):
        return code
    last_line = code.rstrip().split('\n')[-1]
    last_indent = last_line[:len(last_line) - len(last_line.lstrip())]
    return f'{code}\n{last_indent}{BLOCK_INDENT}pass'


def without_pass_body(code: str) -> str:
    """Drop a trailing placeholder `pass` body, leaving the bare header.

    Inverse of with_pass_body, for text coming back from the editor. A body the
    user has actually written is not scaffolding and is left alone.
    """
    lines = code.rstrip().split('\n')
    if len(lines) < 2 or lines[-1].strip() != 'pass':
        return code
    header = '\n'.join(lines[:-1])
    return header if opens_block(header) else code


# =============================================================================
# Relinking a visualizer to a line of code
# =============================================================================
#
# Re-establishing a link via the chain icon works the same way for every
# visualizer that generates code; only the grammar it parses/generates with and
# the actions it defaults to differ. Those differences travel in a LinkConfig
# built once per visualizer module, so the logic below exists once.

@dataclass(frozen=True, slots=True)
class LinkConfig:
    """One visualizer's wiring for the shared relink logic.

    parse_line, get_context, generate_action and ctx_to_model are the
    visualizer's own grammar/model plumbing; change_selected_text is its
    command dataclass. default_action / default_statement_action are what a
    relink falls back to when nothing is stashed (or when the stash generates
    the wrong shape), and statement_actions is the set of actions that generate
    a block header rather than an assignable expression.

    whole_value_context is an optional second context source, used when the
    model has no search: a list can still generate over the whole list, a
    string has nothing to generate without a search.

    code_imports is how the visualizer says what the code it just generated
    needs imported to run; a visualizer whose code never reaches outside the
    builtins leaves it off.
    """
    parse_line: Callable[[str], Tuple[Any, str]]
    get_context: Callable[..., 'dict | None']
    generate_action: Callable[[str, dict], 'Tuple[str | None, str] | None']
    ctx_to_model: Callable[[dict, dict], None]
    change_selected_text: Callable[..., Any]
    default_action: str
    default_statement_action: str
    statement_actions: 'frozenset[str]'
    whole_value_context: 'Callable[..., dict | None] | None' = None
    code_imports: 'Callable[[str], tuple] | None' = None


def link_source_expr(var_and_exp) -> 'str | None':
    """The expression a link generates from, even with no search yet."""
    if not var_and_exp:
        return None
    var_name, expr = var_and_exp
    return var_name if var_name else f"({expr})"


def parse_owned_line(cfg: LinkConfig, text: str, var_and_exp) -> 'tuple[dict, str] | None':
    """Parse *text* if it is code this visualizer could have written for this
    value, i.e. one of its actions over its own source expression.

    Returns ``(ctx, prefix)`` as the visualizer's parse_line does, or None when
    the line belongs to something else (or to nothing we recognize).
    """
    parsed, prefix = cfg.parse_line(text)
    if not (parsed and parsed.get('action') and parsed.get('source_expr')):
        return None
    if var_and_exp:
        line_var = var_and_exp[0]
        if line_var and parsed['source_expr'] != line_var:
            return None
    return (parsed, prefix)


def relink_action(cfg: LinkConfig, model: dict, mode: str, text: str) -> str:
    """The action a relink should resume.

    The action stashed by the matching Unlink wins, but only when it generates
    the same shape as the line being linked: writing an expression over a block
    header (or a header into an assignment) would break the code around it.
    """
    stashed = model.get('unlinked_action')
    if mode != 'takeover':
        return stashed or cfg.default_action
    wants_statement = opens_block(text)
    if stashed and (stashed in cfg.statement_actions) == wants_statement:
        return stashed
    return cfg.default_statement_action if wants_statement else cfg.default_action


def adopt_linked_line(cfg: LinkConfig, owned: 'tuple[dict, str]', var_and_exp,
                      model: dict, *, eval_in_scope=None) -> bool:
    """Adopt an already-parsed line (see parse_owned_line) into the model.

    Used when a fresh model is asked to take over a line that already contains
    a previously-generated linked expression (relink-takeover after a file
    reopen). Leaves the line's text untouched; only the model is updated.
    Returns True on success.
    """
    parsed, prefix = owned
    cfg.ctx_to_model(parsed, model)
    model['linked_action'] = parsed['action']
    model['linked_source_expr'] = parsed['source_expr']
    model['linked_has_assignment'] = bool(prefix)
    model['auto_linked_once'] = True
    # Snapshot the expression already in the editor so the next no-op event
    # (hover, etc.) does not rewrite it identically. Only the search context is
    # consulted: the line just parsed into the model is what defines it, so a
    # whole-value fallback would be describing a different line.
    ctx = cfg.get_context(model, var_and_exp,
                          source_expr=model['linked_source_expr'],
                          eval_in_scope=eval_in_scope)
    if ctx:
        result = cfg.generate_action(parsed['action'], ctx)
        if result:
            model['last_linked_expr'] = result[1]
    return True


def _relink_context(cfg: LinkConfig, model: dict, var_and_exp, *, eval_in_scope=None):
    """The context a relink generates from: the model's search, falling back to
    the whole value for visualizers that can generate without one."""
    ctx = cfg.get_context(model, var_and_exp, eval_in_scope=eval_in_scope)
    if ctx is None and cfg.whole_value_context is not None:
        ctx = cfg.whole_value_context(model, var_and_exp)
    return ctx


def handle_relink(cfg: LinkConfig, mode: str, text: str, var_and_exp,
                  model: dict, commands: list, *, eval_in_scope=None) -> None:
    """Handle a Relink event: record the link in *model* and, where the link
    implies code, append the command that writes it to *commands*."""
    owned = parse_owned_line(cfg, text, var_and_exp) if mode == 'takeover' else None
    if owned and not model.get('unlinked_action'):
        # Fresh model over an existing generated line: adopt the line as-is
        # (parse it into the model) instead of clobbering it.
        if adopt_linked_line(cfg, owned, var_and_exp, model, eval_in_scope=eval_in_scope):
            return

    action = relink_action(cfg, model, mode, text)
    ctx = _relink_context(cfg, model, var_and_exp, eval_in_scope=eval_in_scope)
    result = cfg.generate_action(action, ctx) if ctx else None
    source_expr = link_source_expr(var_and_exp)

    # Taking over a line we didn't write inserts and rewrites nothing: the link
    # alone is what the user asked for, and the next interaction is what edits
    # the line. So only an expression actually written below may be remembered
    # as last_linked_expr - remembering one we never wrote would make the next
    # interaction that regenerates it a no-op, stranding the user's text on a
    # line the chain icon claims is linked.
    written = None
    if result and owned:
        # Resuming a link on a line we wrote: bring it up to date with the
        # visualizer's current state, keeping the var name.
        written = result[1]
        commands.append(cfg.change_selected_text(expression=written,
                                                 suggested_var_name=None))
    elif result and mode == 'insert':
        written = result[1]
        commands.append(new_code_command(result, cfg.code_imports))

    if source_expr and (result or mode == 'takeover'):
        model['linked_action'] = action
        model['linked_source_expr'] = source_expr
        model['unlinked_action'] = None
        model['auto_linked_once'] = True
        # Statement actions have no name to assign to.
        model['linked_has_assignment'] = action not in cfg.statement_actions
        model['last_linked_expr'] = written


def py_exp_attrs(expr, *, imports=(), draggable: bool = True,
                 align: str = None, attr: str = 'snc-py-exp') -> str:
    """The attributes that hand a Python expression to the editor, ready to be
    dropped into a tag (they lead with a space).

    An expression that can't run on its own says so here: *imports* is what the
    visualizer producing the code knows it needs, and the front end decides
    whether the file already has them and where they would go. Nothing in
    between reads the expression to guess.

    *attr* is which tooltip system picks the expression up -- the py-exp one by
    default, or `data-action-expr` for an action button, whose tooltip offers
    the same copy, insert and drag. Either way the imports ride along under the
    one name, so the editor has a single place to look.

    Renders nothing without an expression, so a caller with no access path to
    offer can drop this in unconditionally.
    """
    if not expr:
        return ''
    attrs = f' {attr}="{html.escape(expr)}"'
    if imports:
        attrs += f' snc-py-exp-imports="{html.escape(json.dumps(list(imports)))}"'
    if draggable:
        attrs += ' draggable="true"'
    if align:
        attrs += f' snc-py-exp-align="{html.escape(align)}"'
    return attrs


def wrap_drag_grab(inner_html: str, var_and_exp) -> str:
    """Wrap a visualizer's whole output in a draggable snc-py-exp grab span.

    Only for visualizers with no content of their own to hover - the generic
    and static ones. A visualizer that renders its own handles (list cells,
    field chips, characters) must not do this: the outer handle would claim
    every hover inside it and show the whole value's expression instead of the
    more specific one under the cursor. Renders bare when the parent supplies
    no access-path expression via var_and_exp.
    """
    expr = var_and_exp[1] if var_and_exp else None
    if not expr:
        return inner_html
    return (f'<span{py_exp_attrs(expr)} '
            f'class="py-exp-grab">{inner_html}</span>')


def defer_drag_grab(child_html: str, expr: str) -> str:
    """Let a parent's handle answer for a child's whole-value one, when the two
    would say the same expression.

    A parent that is a handle itself -- an aggregation cell, whose label and
    answer are one thing to drag -- still passes the expression down, because a
    child with handles of its own builds the more specific ones out of it. The
    generic visualizers, having nothing of their own to hover, wrap the whole
    answer in the same handle instead, and two handles saying the same thing is
    one too many: the inner tooltip is drawn above the answer, over the label
    that says which aggregation is being read.

    So the expression comes off the wrapper and the wrapper stays: it is what
    draws the grab cursor and the border around the value, and hovering it or
    dragging it walks up to the parent's handle -- the same expression, from the
    one place that has room to show it.

    Only the exact wrapper `wrap_drag_grab` writes for *expr* is rewritten, and
    only when it is the whole of what the child drew -- handles the child drew
    inside its own content are its own and keep their expressions.
    """
    prefix = f'<span{py_exp_attrs(expr)} class="py-exp-grab">'
    if not expr or not child_html.startswith(prefix):
        return child_html
    # Where the wrapper closes, which has to be the end of what the child drew:
    # one that drew two wrapped things side by side opens and closes the same
    # way, and rewriting the first tag would speak for the last as well.
    depth = 0
    for tag in re.finditer(r'</?span\b', child_html):
        depth += 1 if tag.group() == '<span' else -1
        if depth == 0:
            if child_html[tag.start():] != '</span>':
                return child_html
            return f'<span class="py-exp-grab">{child_html[len(prefix):]}'
    return child_html


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
