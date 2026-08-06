"""Shared utilities for visualizer composition in Sculpt-n-Code."""

import ast
import dataclasses
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
CARETS_RE = re.compile(r'(?<!\^)\^+(?!\^)')

# replace_exps should be array, where replace_exps[0] is the replacement for ^, replace_exps[1] for ^^, etc
# replace_exps should not have carets in them. if necessary, run this on them first
# a run naming a scope beyond replace_exps is left as written - the caller only
# knows the scopes it was given, and must not invent a binding for the rest
def replace_carets_in_py_exp(py_exp: str, replace_exps) -> str:
    temp_names = {} # temp name to number of carets
    def temp_replacer(m):
        n_carets = len(m[0])
        temp_name = f'_{n_carets}carets_{len(temp_names)}_'
        temp_names[temp_name] = n_carets
        return temp_name
    out = CARETS_RE.sub(temp_replacer, py_exp)

    for name, n_carets in temp_names.items():
        try:
            temp_str = out.replace(name, '^'*n_carets)
            ast.parse(temp_str)
            out = temp_str # parse succeeded, meaning the carets were likely in a string and should not be replaced
        except SyntaxError:
            if n_carets <= len(replace_exps):
                out = out.replace(name, replace_exps[n_carets-1])
            else:
                out = out.replace(name, '^'*n_carets)

    return out


def caret_expr_parses(s: str, mode: str = 'eval') -> bool:
    """Whether *s* is valid Python once every caret run is read as a value.

    Used to validate text the user typed, which may name any number of scopes,
    so the levels are collapsed to one placeholder rather than bound.
    """
    try:
        ast.parse(s, mode=mode)
        return True
    except SyntaxError:
        pass
    if '^' not in s:
        return False
    try:
        ast.parse(CARETS_RE.sub('_crt_', s), mode=mode)
        return True
    except SyntaxError:
        return False


# --- Nesting: how a child visualizer talks about its own value ----------------
#
# A caret run names a scope: ^ is the innermost value, ^^ its parent, and so on.
# A list column or object field is written in ITS OWN scope, where ^ is the row
# or the object. A child visualizer nested in one of those cells introduces a
# new innermost scope (the string visualizer binds ^ to the current regex
# match), so the cell's own value is one scope out: ^^.
#
# The child never emits carets in generated code, though. The parent binds the
# cell value to CHILD_SOURCE_BINDER and hands that over as the child's source
# expression; the child generates ordinary caret-free Python against it, and the
# parent swaps its own (caret-bearing) expression back in via
# nest_generated_expr when it takes the code. That keeps replace_exps caret-free
# everywhere and keeps generated code parseable at every intermediate step.
#
# In its own UI the child still SHOWS that value as ^^, which is what the user
# reads in the replace box.

CHILD_SOURCE_BINDER = '_snc_cell_'
CHILD_SOURCE_DISPLAY = '^^'


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
    own scope (a list column, an object field accessor) and may contain carets.
    """
    return expr.replace(CHILD_SOURCE_BINDER, f'({parent_expr})')


def nest_child_command(cmd, code_expr: str, clipboard_expr: str):
    """Resolve the binder in one command coming back from a child visualizer.

    The two expressions differ by destination, not by scope depth. Generated
    code (a NewCode 2-tuple) may be headed for the parent's own config, where a
    caret expression is exactly right - a list column has to stay row-generic.
    Clipboard text is pasted into the editor verbatim, so it has to name the
    value concretely; a parent whose code_expr is already concrete passes the
    same expression twice.
    """
    if isinstance(cmd, tuple) and len(cmd) == 2:
        return (cmd[0], nest_generated_expr(cmd[1], code_expr))
    # Duck-typed: each visualizer declares its own CopyToClipboard.
    text = getattr(cmd, 'text', None)
    if isinstance(text, str) and CHILD_SOURCE_BINDER in text:
        return dataclasses.replace(cmd, text=nest_generated_expr(text, clipboard_expr))
    return cmd


def strip_leading_caret(name: str) -> str:
    """Remove a single leading ^ for display purposes."""
    if name.startswith('^'):
        return name[1:]
    return name


def eval_caret_expr(field_expr: str, value, eval_in_scope=None):
    """Evaluate a ^-prefixed field expression against a value.

    The value comes in as an argument and the expression is compiled in the
    user's scope, so a column like `^ * factor` can name their program's
    variables alongside the caret. Without a scope to compile it in -- an
    unfocused preview, a test -- this module's globals are all there is, which
    is enough for an expression that only reaches through the caret.
    """
    code = f'(lambda _v: {replace_carets_in_py_exp(field_expr, ["_v"])})'
    return (eval(code) if eval_in_scope is None else eval_in_scope(code))(value)


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
        commands.append(result)

    if source_expr and (result or mode == 'takeover'):
        model['linked_action'] = action
        model['linked_source_expr'] = source_expr
        model['unlinked_action'] = None
        model['auto_linked_once'] = True
        # Statement actions have no name to assign to.
        model['linked_has_assignment'] = action not in cfg.statement_actions
        model['last_linked_expr'] = written


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
