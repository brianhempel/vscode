"""
String visualizer for Sculpt-n-Code.

This visualizer displays Python string values with interactive selection capabilities,
allowing users to build regex patterns by demonstration.

================================================================================
ARCHITECTURE OVERVIEW
================================================================================

This visualizer follows the Elm architecture with three core functions:

1. visualize(value, model, get_visualizer) -> HTML string
   - Renders the string value as interactive HTML
   - Each character is wrapped in a <span> with mouse event handlers
   - Selection highlighting is applied based on model state

2. init_model() -> dict
   - Returns the initial model state for a new visualization

3. update(event, var_and_exp, model) -> (new_model, commands)
   - Processes UI events (mouse, keyboard) and returns updated model
   - May return commands (like NewCode) for VS Code to execute

================================================================================
HOW IT WORKS
================================================================================

RENDERING:
- The string is displayed character-by-character inside a <div>
- Special characters (\n, \t) are shown as escape sequences
- Regex anchors ^ and $ are shown as visible boundary markers
- Each <span> has snc-mouse-* attributes containing Python code strings
  that get eval'd in the update() function to create typed event objects

INTERNAL INDEXING:
- Characters use "internal indices" that differ from string indices
- Index 0: ^ marker, Index 1+: actual characters
- Newlines expand to 3 indices: $ (end-of-line), \n, ^ (start-of-line)
- The build_internal_to_string_mapping() function converts between systems

SELECTION (Programming by Demonstration):
- Users can create regex patterns by selecting parts of the string
- Dragging the TOP half of characters creates "literal" selections (yellow)
- Dragging the BOTTOM half creates "fuzzy" selections (purple = .*)
- Multiple segments can be chained by starting a new drag at the end of
  the previous selection
- Pressing Enter generates regex code: list(re.finditer(r'pattern', var, flags=re.M))

TOOLS (the "tool toolbar" in the upper-right corner):
- 'literal' (default): drag selects literal chars (also: hold shift)
- 'fuzzy': drag selects a fuzzy pattern (also: hold alt/option)
- 'index': drag selects a slice/index expression like 5:10 (also: hold ctrl)
- 'pick': click chips covering the FIRST match's visible features
  (start/end indices, prefix/suffix substrings, capture groups) to build
  a Replace expression. See "PICK TOOL" below.

PICK TOOL:
- Works with every kind of search: regex (r'pat'), literal string ('sub' /
  "sub"), string-valued expression (`x`), and index / slice (5 or 2:7).
  Literal and expression searches match via re.finditer(re.escape(...)), so
  they hand back the same match object the regex path picks from - they just
  have no capture groups, leaving 'group_0' as the only group chip.
- Activated via the cursor-arrow tool button. While active:
    * Only the FIRST match is highlighted (so prefix/suffix are unambiguous).
    * The Replace box auto-opens; selections drive its content.
    * Capture groups are auto-turned-on for multi-segment regexes (the
      'c' flag), so each capture group can be selected individually.
- Each visible feature of the match is a clickable chip:
    'start'   -> match.start() index
    'end'     -> match.end() index
    'prefix'  -> str[:match.start()]
    'group_0' -> the whole match (when cap groups OFF or single segment)
    'group_N' -> the Nth capture group ($[N])
    'suffix'  -> str[match.end():]
- Each chip carries:
    * snc-mouse-down="SegmentToggle(segment_id=...)" so a click toggles
      the segment in/out of model['selectedSegments'].
    * snc-py-exps="[{"expr": ...}]" so the existing tooltip + drag plumbing
      pick it up as a draggable expression source.
- Selecting segments rebuilds model['replace_text']:
    * Single item   -> just the expression
    * Adjacent strs -> joined with " + " (concatenation)
    * Anything else -> tuple "(item1, item2, ...)"
- Simplifications applied during assembly:
    * All capture groups (group_1..N) -> collapse to group_0 ($[0])
    * {prefix, group_0, suffix}        -> just <src>
    * {group_0, suffix}                -> <src>[$.start():]
    * {prefix, group_0}                -> <src>[:$.end()]
- Multi-match mode (no '1' flag): each chip's expression becomes a list
  comprehension over re.finditer(...), e.g.
    group_1 -> [m[1] for m in re.finditer(r'pat', src, flags=re.M)]

FETCH MENU:
- The one button in the action bar that asks nothing of the search: a string
  that names a place -- a URL, a path -- is one read away from the value it
  stands for, and this writes that read as a line of its own.
    Fetch URL     > as string / as JSON
    Read Filepath > as string / as CSV / as JSON / as Excel
- The same reads pythonDropProvider.ts writes when a URL or a file is dragged
  into the editor, offered after the fact for a string the program already has.
  See FETCH_MENUS.
- Which rows are live is read off the value: a URL by how it starts, a path by
  the file being there (asked of the filesystem, in the user's own process).
- Unlike the action buttons it links nothing -- there is no gesture afterwards
  for a line to be kept in step with.

MODEL STATE:
- search: Regex pattern in Pythonic raw-string form, e.g. r'hello.*world'
  with optional postfix flags (1, i, c).
  All segments (literal and fuzzy) are ungrouped by default.
  Groups are only kept when two literal segments are adjacent,
  to disambiguate their boundary:
    e.g., "r'hello.*world'" or "r'(hello)(world).*'"
  Triple-quoted variants are also accepted on input for patterns containing
  both single and double quotes.
  Non-regex search types use familiar Python delimiters: 'sub'/"sub" for
  substring, 5:10 for slice, `expr` for expressions.
- anchorIdx/cursorIdx: Current drag start/end positions (internal indices)
- anchorType: 'literal' or 'fuzzy' based on where the drag started
- dragging: Whether a drag is in progress
- tool: Active tool ('literal' / 'fuzzy' / 'index' / 'pick')
- selectedSegments: In pick-tool mode, the ordered list of selected segment IDs
  driving the Replace box content.

Note: The string value is NOT stored in the model. Instead, it is passed as
a parameter to init_model(value), update(..., value), and visualize(value, model, ...).

COMMANDS:
- NewCode(code): Tells VS Code to replace the file contents with new code
  (used when Enter is pressed to insert the generated regex line)

================================================================================
"""

import ast
import html
import keyword
import os
import re
import re._parser as regex_parser  # type: ignore[import]
from re._constants import (  # type: ignore[import]
    AT_BEGINNING, AT_BEGINNING_STRING, AT_END, AT_END_STRING,
    MAXREPEAT,
)

from dataclasses import dataclass
from typing import List, Tuple, Any, Optional

from visualizer_utils import is_read_only
from visualizer_utils import (modifier_key_label, replace_dollars_in_py_exp, Unlink, Relink, truncate_repr, ICONS,
                              opens_block, with_pass_body,
                              Dollar, DollarScope,
                              LinkConfig, handle_relink, new_code_command, py_exp_attrs, PyExp,
                              CHILD_SOURCE_BINDER, CHILD_SOURCE_DISPLAY,
                              dollar_expr_parses, is_nested, label_readings,
                              nerd_font_icon, render_tool_toolbar,
                              render_expand_toggle, wrap_drag_grab)
import z_object_visualizer

# === Command types (Elm-style commands for VS Code to execute) ===

@dataclass(frozen=True, slots=True)
class CopyToClipboard:
    text: str

@dataclass(frozen=True, slots=True)
class ChangeSelectedText:
    # The backend owns expression generation; the editor owns the concrete
    # assignment target in its linked range.
    expression: str
    # Set only for an action change that semantically suggests a new target.
    suggested_var_name: Optional[str] = None

# === Event types ===

@dataclass(frozen=True, slots=True)
class MouseMove:
    index: int

@dataclass(frozen=True, slots=True)
class MouseDown:
    index: int

@dataclass(frozen=True, slots=True)
class MouseUp:
    index: int

@dataclass(frozen=True, slots=True)
class KeyDown:
    pass

@dataclass(frozen=True, slots=True)
class PinFocus:
    """A click on the non-focused preview, which exists only to be one.

    A nested preview is focused by clicking it: route_child_event pins focus on
    the first mousedown a non-focused child receives and drops the payload
    unread. So this event has no case in `update` on purpose - by the time a
    string visualizer would handle its own events it is focused, and a focused
    visualizer no longer renders the preview that sends this."""
    pass

@dataclass(frozen=True, slots=True)
class DropdownToggle:
    dropdown_id: str

@dataclass(frozen=True, slots=True)
class DropdownSelect:
    dropdown_id: str
    option_value: str

@dataclass(frozen=True, slots=True)
class MouseOut:
    pass

@dataclass(frozen=True, slots=True)
class HandleMouseDown:
    segment_index: int
    side: str  # 'left' or 'right'

@dataclass(frozen=True, slots=True)
class SearchBoxInput:
    value: str

@dataclass(frozen=True, slots=True)
class ReplaceBoxInput:
    value: str

@dataclass(frozen=True, slots=True)
class ReplaceToggle:
    pass

@dataclass(frozen=True, slots=True)
class ExpandToggle:
    """Expand/collapse the string-visualizer pane (only offered for tall strings)."""
    pass

@dataclass(frozen=True, slots=True)
class FirstMatchToggle:
    pass

@dataclass(frozen=True, slots=True)
class CaseSensitiveToggle:
    pass

@dataclass(frozen=True, slots=True)
class CaptureGroupsToggle:
    pass

@dataclass(frozen=True, slots=True)
class ActionButtonClick:
    action: str  # 'match_strings', 'find_or_map', 'replace', 'delete', 'loop', 'loop_match_strings', 'any', 'all', 'if_any', 'if_all', 'count', 'filter', 'find_indices', 'split'
    copy: bool   # True → CopyToClipboard, False → NewCode

@dataclass(frozen=True, slots=True)
class FetchClick:
    """A row of the Fetch menu: read the string as the place it names.

    *source* is where the bytes come from ('url' over the network, 'file' off
    the disk) and *fmt* how they are read ('text', 'json', 'csv', 'excel').
    See FETCH_MENUS for what each pair writes.
    """
    source: str
    fmt: str

@dataclass(frozen=True, slots=True)
class RepetitionInput:
    dropdown_id: str
    field: str  # 'exact', 'min', or 'max'
    value: str

@dataclass(frozen=True, slots=True)
class ToolSelect:
    tool: str  # 'literal' | 'fuzzy' | 'index' | 'pick'

@dataclass(frozen=True, slots=True)
class SegmentToggle:
    """Toggle a feature of the first match into model['selectedSegments'].

    segment_id is one of:
      - 'start'   - the match.start() index label
      - 'end'     - the match.end()   index label
      - 'prefix'  - substring from string start to match start
      - 'group_0' - the whole match (used when capture groups OFF)
      - 'group_N' - capture group N (used when capture groups ON)
      - 'suffix'  - substring from match end to string end
    """
    segment_id: str

@dataclass(frozen=True, slots=True)
class SliceLabelInput:
    """Fired when the user types into a slice/index-label edit popup.

    side: 'start' / 'end' for slice bounds, 'center' for a bare index pick.
    value: the new raw expression text (may be empty -> elide that side).
    """
    side: str
    value: str

# attached handlers can be Python code strings that evaluate to functions of type: RawEventJSON -> ModelEvent
# def mouse_move(i) -> Callable[[dict], MouseMove | MouseDown | MouseUp | KeyDown]:
#     return lambda _: MouseMove(i)


# eval(f"{MouseOver(10)}") works




# Icons (loaded from icons/*.svg) live in visualizer_utils.ICONS so other
# visualizers can reuse them.

# Available fuzzy character class options for dropdown selection
# Each tuple is (pattern_value, display_label)
# Note: These are character classes only - repetition is handled separately
FUZZY_PATTERN_OPTIONS = [
    (r"\s", r"\s"),
    (r"\d", r"\d"),
    (r"[0-9\.]", r"[0-9\.]"),
    (r"[a-z]", r"[a-z]"),
    (r"[A-Z]", r"[A-Z]"),
    (r"[A-Za-z]", r"[A-Za-z]"),
    (r"[A-Za-z0-9]", r"[A-Za-z0-9]"),
    (r"\w", r"\w"),
    (r"\S", r"\S"),
    (r".", r"."),
    (r"[\S\s]", r"[\S\s]"),
]

# Sentinel characters for visible regex anchors (ASCII Device Control chars)
# These are inserted into an "augmented string" to enable 1:1 mapping
# between string positions and visual display indices.
DC2 = chr(0x12)  # ^  - start of line/string anchor
DC3 = chr(0x13)  # $  - end of line/string anchor

_SENTINEL_CHARS = [DC2, DC3]

# Lambda parameter the previews bind the string itself to, so a replace
# expression that mentions $$ (see CHILD_SOURCE_DISPLAY) can be evaluated
# against the real value rather than a name only the generated code has.
_PREVIEW_SOURCE_BINDER = '_snc_v'


# What the two boxes say of themselves. Only one of them speaks dollars at all.
#
# The Find box takes a pattern, a piece of text, or a place in the string, and
# binds nothing -- so it has no scope, and what it says is what it accepts. It
# deliberately says nothing about `$`: this is the one box where a bare `$` is
# legal as written, being the regex end anchor, and a note saying the box has no
# dollars would read as a note saying not to type one.
FIND_TOOLTIP = "Text, r'regex', an index, or start:stop"


def replace_scope(idx_slice: bool, match_expr: str = None,
                  source_expr: str = None) -> DollarScope:
    """The scope the Replace box is written in.

    Exactly the two levels `_replace_expr_bound` binds, declared here so the box
    and the substitution can't come to disagree: `$` is whatever the grammar
    fills `mtch` with and `$$` is the string being searched, which stays true
    when nested (see CHILD_SOURCE_DISPLAY).

    What `mtch` holds turns on the search. A regex or a text search matches
    through `re.finditer`, so it is a match object and the text is one subscript
    away; an index or a slice reaches into the string directly, so it IS the
    text. Nothing else about the scope changes, which is why one declaration
    with one branch says it.
    """
    return DollarScope(
        Dollar('$', 'the selected text' if idx_slice else 'the match',
               match_expr),
        *(() if idx_slice else (Dollar('$[0]', 'its text'),)),
        Dollar('$$', 'the whole string', source_expr),
    )


def synthesize_fuzzy_pattern(actual_text: str, prev_char: str | None = '', next_char: str | None = '') -> str:
    """
    Synthesize a fuzzy regex pattern that matches exactly the given text.

    Enumerates patterns from FUZZY_PATTERN_OPTIONS and picks the most specific
    one that matches the dragged text, so the highlighted fuzzy segment
    corresponds precisely to the user's mouse drag distance.

    Step 1: Try each pattern with an open-ended quantifier:
            - For a fresh selection (both prev_char and next_char are strings),
              use + (one or more) so the regex won't match zero characters.
            - When adjacent to an existing literal segment (prev_char or
              next_char is None), use * (zero or more) since the literal
              already anchors the match.
            Skip if a non-None boundary character matches the pattern
            (the quantifier would overshoot that edge).
    Step 2: If none matched, try each with {n} repetition (e.g. \\d{3}).

    Args:
        actual_text: The actual string characters under the drag range
                     (sentinel chars should already be stripped).
        prev_char: The character immediately before the drag range, or ''
                   if at start of string. None if adjacent to an existing
                   literal segment on the left (suppresses + in favor of *).
        next_char: The character immediately after the drag range, or ''
                   if at end of string. None if adjacent to an existing
                   literal segment on the right (suppresses + in favor of *).

    Returns:
        A regex pattern string like "\\s+", "\\s*", "\\d{3}", or ".*".
    """
    if not actual_text:
        return ".*"

    n = len(actual_text)

    # Use + only for fresh selections (both boundaries are strings).
    # When adjacent to an existing literal (either is None), use *.
    is_fresh = prev_char is not None and next_char is not None
    quantifier = '+' if is_fresh else '*'

    # Step 1: Try open-ended quantifier (+ or *).
    # Prefer more specific character classes first.
    # Skip if a non-None boundary character matches (would overshoot).
    for pattern_str, _ in FUZZY_PATTERN_OPTIONS:
        try:
            if re.fullmatch(pattern_str + quantifier, actual_text):
                # Check right boundary (only when next_char is a string)
                if next_char and re.fullmatch(pattern_str, next_char):
                    continue
                # Check left boundary (only when prev_char is a string)
                if prev_char and re.fullmatch(pattern_str, prev_char):
                    continue
                return pattern_str + quantifier
        except Exception:
            continue

    # Step 2: Try {n} repetition
    for pattern_str, _ in FUZZY_PATTERN_OPTIONS:
        try:
            if re.fullmatch(pattern_str + '{' + str(n) + '}', actual_text):
                return pattern_str + '{' + str(n) + '}'
        except Exception:
            continue

    # Fallback (should be unreachable since [\S\s]{n} matches everything)
    return r"[\S\s]" + quantifier


def char_to_regex_literal(char: str) -> str:
    """Convert a character (possibly sentinel) to its regex representation."""
    if char == DC2:
        return '^'
    elif char == DC3:
        return '$'
    elif char == '\n':
        return r'\n'
    elif char == '\t':
        return r'\t'
    elif char == '\r':
        return r'\r'
    elif char == "'":
        return "\\'"
    else:
        return re.escape(char)


def span(text, color, style=''):
    return f'<span style="color: {color};{style}">{text}</span>'

def get_fields(value):
    return None


def can_visualize(value):
    return isinstance(value, str)


def render_dropdown(
    dropdown_id: str,
    options: list[tuple[str, str]],
    is_open: bool,
    trigger_content: str,
    trigger_style: str = '',
) -> str:
    """Render a reusable dropdown component.

    Args:
        dropdown_id: Unique identifier for this dropdown instance
        options: List of (value, display_label) tuples
        is_open: Whether the dropdown is currently open
        trigger_content: HTML content for the trigger element
        trigger_style: Additional CSS styles for the trigger

    Returns:
        HTML string for the dropdown (trigger + options list if open)
    """
    # Trigger element with click handler to toggle
    trigger_event = repr(DropdownToggle(dropdown_id))
    trigger_html = (
        f'<span snc-mouse-down="{html.escape(trigger_event)}" '
        f'style="cursor: pointer; {trigger_style}">{trigger_content}</span>'
    )

    if not is_open:
        return trigger_html

    # Build options list
    options_html = []
    for value, label in options:
        select_event = repr(DropdownSelect(dropdown_id, value))
        option_html = (
            f'<div snc-mouse-down="{html.escape(select_event)}" '
            'style="padding: 2px 6px; cursor: pointer; white-space: nowrap;"'
            f'class="snc-dropdown-option">{html.escape(label)}</div>'
        )
        options_html.append(option_html)

    # Dropdown container (absolutely positioned below trigger)
    dropdown_html = (
        f'<div class="snc-dropdown-panel" snc-dropdown-align="left">{"".join(options_html)}</div>'
    )

    # Wrap trigger and dropdown in a relative container
    return (
        f'<span class="snc-dropdown-trigger" style="position: relative; display: inline-block;">'
        f'{trigger_html}{dropdown_html}</span>'
    )


def _overlay_html(content: str, side: str, seg_type: str, color: str) -> str:
    """Generate an overlay span for pattern/repetition display.

    Args:
        content: The text to display in the overlay
        side: 'left' or 'right' positioning
        seg_type: 'literal' or 'fuzzy' - affects vertical positioning
        color: The color for the overlay text
    """
    if not content:
        return ''

    # return f'<span class="overlay-container {seg_type}"><span class="overlay-content {seg_type} side-{side}">{html.escape(content)}</span></span>'

    v_align = 'text-top' if seg_type == 'literal' else 'baseline'
    top = -7 if seg_type == 'literal' else 3
    h_pos = 'left: -1px;' if side == 'left' else 'right: 0px;'
    return (
        f'<span style="position: relative; display: inline-block; vertical-align: {v_align}"><span style="'
        'position: absolute;'
        f'{h_pos}'
        f'top: {top}px;'
        'font-size: 5px;'
        'font-style: normal;'
        'font-weight: bold;'
        'padding: 0;'
        f'color: {color};'
        'pointer-events: none;'
        'z-index: 10;'
        'line-height: 6px;'
        f'">{html.escape(content)}</span></span>'
    )


def _format_repetition(min_count, max_count) -> str:
    if min_count == max_count:
        return f'{min_count}'
    elif min_count == 0 and max_count == float('inf'):
        return '*'
    elif min_count == 1 and max_count == float('inf'):
        return '+'
    elif min_count == 0 and max_count == 1:
        return '?'
    elif min_count == 0:
        return f'≤{max_count}'
    elif max_count == float('inf'):
        return f'≥{min_count}'
    else:
        return f'{min_count}-{max_count}'

def _segment_pattern_label(pat_str: str, segment_index: int, model: dict, seg_len: int = 1) -> str:
    dropdown_id = f'fuzzy-pattern-{segment_index}'
    open_dropdown = model.get('openDropdown') if model else None
    is_open = open_dropdown is not None and open_dropdown.get('id') == dropdown_id

    trigger_event = repr(DropdownToggle(dropdown_id))
    label_text = html.escape(pat_str) if pat_str else '.*'
    trigger_html = (
        f'<span class="segment-label pattern seg-length-{seg_len}" '
        f'snc-mouse-down="{html.escape(trigger_event)}">{label_text}</span>'
    )

    dropdown_panel = ''
    if is_open:
        options_html = []
        for value, label in FUZZY_PATTERN_OPTIONS:
            select_event = repr(DropdownSelect(dropdown_id, value))
            options_html.append(
                f'<div class="snc-dropdown-option" snc-mouse-down="{html.escape(select_event)}">'
                f'{html.escape(label)}</div>'
            )
        dropdown_panel = (
            f'<div class="snc-dropdown-panel left code" snc-dropdown-align="left">{"".join(options_html)}</div>'
        )

    return (
        f'<span class="segment-label-anchor">'
        f'<span class="snc-dropdown-trigger">{trigger_html}{dropdown_panel}</span>'
        f'</span>'
    )

def _quantifier_to_simple_option(min_count, max_count) -> str | None:
    """Return the matching simple-option value ('1' / '?' / '*' / '+') or None.

    Used to highlight the current quantifier in the repetition dropdown.
    """
    inf = float('inf')
    if min_count == 1 and max_count == 1:
        return '1'
    if min_count == 0 and max_count == 1:
        return '?'
    if min_count == 0 and max_count == inf:
        return '*'
    if min_count == 1 and max_count == inf:
        return '+'
    return None


def _quantifier_to_prefill(min_count, max_count) -> tuple[str, str, str]:
    """Return (exactN, rangeMin, rangeMax) strings to seed the repetition dropdown.

    Only the matching field(s) are populated; the others stay ''. Simple
    quantifiers (1, ?, *, +) leave all fields empty (they're shown via
    .selected on the simple option instead).
    """
    inf = float('inf')
    if _quantifier_to_simple_option(min_count, max_count) is not None:
        return ('', '', '')
    if min_count == max_count:
        return (str(min_count), '', '')
    # Range form (incl. open-ended {n,} and {0,m})
    range_max = '' if max_count == inf else str(max_count)
    return ('', str(min_count), range_max)


def _segment_repetition_label(rep_str: str, segment_index: int, seg_type: str, model: dict,
                              seg_len: int = 1, min_count=None, max_count=None) -> str:
    dropdown_id = f'repetition-{segment_index}'
    open_dropdown = model.get('openDropdown') if model else None
    is_open = open_dropdown is not None and open_dropdown.get('id') == dropdown_id

    # The bounds say nothing about laziness; the label and the selected
    # option both need to.
    is_lazy = _segment_is_lazy(model, segment_index)
    if is_lazy:
        rep_str += '?'

    trigger_event = repr(DropdownToggle(dropdown_id))
    trigger_html = (
        f'<span class="segment-label repetition seg-length-{seg_len}" '
        f'snc-mouse-down="{html.escape(trigger_event)}">{html.escape(rep_str)}</span>'
    )

    dropdown_panel = ''
    if is_open:
        # Compute which option/row matches the segment's current quantifier so
        # we can mark it .selected in the rendered list.
        current_simple = (_quantifier_to_simple_option(min_count, max_count)
                          if min_count is not None else None)
        if is_lazy:
            # `*?` and `+?` are offered as options; other lazy forms select nothing.
            current_simple = current_simple + '?' if current_simple in ('*', '+') else None
        # Fall back to derived prefill values if the openDropdown state hasn't
        # been seeded yet (e.g. legacy openDropdowns set without a toggle event).
        if min_count is not None and max_count is not None:
            seeded_exact, seeded_min, seeded_max = _quantifier_to_prefill(min_count, max_count)
        else:
            seeded_exact, seeded_min, seeded_max = '', '', ''
        # Whether a range/exact quantifier is the current one (no simple match)
        current_is_exact = current_simple is None and bool(seeded_exact)
        current_is_range = current_simple is None and (bool(seeded_min) or bool(seeded_max))

        options_html = []
        for value, label in REPETITION_OPTIONS:
            select_event = repr(DropdownSelect(dropdown_id, value))
            cls = 'snc-dropdown-option'
            if value == current_simple:
                cls += ' selected'
            options_html.append(
                f'<div class="{cls}" data-tooltip="{html.escape(_REPETITION_TOOLTIP[value])}" '
                f'snc-mouse-down="{html.escape(select_event)}">'
                f'{html.escape(label)}</div>'
            )

        # Exact-n input value: openDropdown[exactN] is '' if user cleared,
        # '<value>' if user typed, or KEY MISSING if not yet seeded. Use seeded
        # only when the key is missing (i.e. before the toggle handler ran).
        if open_dropdown and 'exactN' in open_dropdown:
            exact_n = open_dropdown['exactN']
        else:
            exact_n = seeded_exact
        exact_input_event = f"lambda e: RepetitionInput(dropdown_id='{dropdown_id}', field='exact', value=e.get('value', ''))"
        exact_cls = 'snc-dropdown-option' + (' selected' if current_is_exact else '')
        options_html.append(
            f'<div class="{exact_cls}" data-tooltip="{html.escape(_REPETITION_TOOLTIP["exact"])}">'
            f'{{'
            f'<input class="snc-dropdown-input" type="text" snc-input="{html.escape(exact_input_event)}" '
            f'value="{html.escape(exact_n)}" placeholder="n" />'
            f'}}</div>'
        )

        if open_dropdown and 'rangeMin' in open_dropdown:
            range_min = open_dropdown['rangeMin']
        else:
            range_min = seeded_min
        if open_dropdown and 'rangeMax' in open_dropdown:
            range_max = open_dropdown['rangeMax']
        else:
            range_max = seeded_max
        min_input_event = f"lambda e: RepetitionInput(dropdown_id='{dropdown_id}', field='min', value=e.get('value', ''))"
        max_input_event = f"lambda e: RepetitionInput(dropdown_id='{dropdown_id}', field='max', value=e.get('value', ''))"
        range_cls = 'snc-dropdown-option' + (' selected' if current_is_range else '')
        options_html.append(
            f'<div class="{range_cls}" data-tooltip="{html.escape(_REPETITION_TOOLTIP["range"])}">'
            f'{{'
            f'<input class="snc-dropdown-input" type="text" snc-input="{html.escape(min_input_event)}" '
            f'value="{html.escape(range_min)}" placeholder="n" />'
            f','
            f'<input class="snc-dropdown-input" type="text" snc-input="{html.escape(max_input_event)}" '
            f'value="{html.escape(range_max)}" placeholder="n" />'
            f'}}</div>'
        )

        rep_category = (
            f'<div class="snc-dropdown-category">'
            f'<div class="snc-dropdown-category-name">Repetition</div>'
            f'{"".join(options_html)}'
            f'</div>'
        )

        dropdown_panel = (
            f'<div class="snc-dropdown-panel categorized right code" snc-dropdown-align="right">'
            f'{rep_category}'
            f'</div>'
        )

    return (
        f'<span class="segment-label-anchor">'
        f'<span class="snc-dropdown-trigger">{trigger_html}{dropdown_panel}</span>'
        f'</span>'
    )

def _segment_index_label(label_text: str, position: str, seg_len: int = 1,
                         model: dict | None = None) -> str:
    """Render an index label for a slice/index selection endpoint.

    Click-to-edit: each label is wired to DropdownToggle('slice-label-{position}').
    When that dropdown is open, render a small one-input panel prefilled with
    the side's current value so the user can replace e.g. '5' with a variable.
    Re-uses .segment-label.pattern / .repetition positioning so left/right end
    up in familiar spots; .index-label lets CSS swap the styling.

    position: 'start' (left), 'end' (right), or 'center' (single-char pick).
    """
    side_class = {
        'start': 'pattern',
        'end': 'repetition',
        'center': 'pattern center',
    }[position]
    dropdown_id = f'slice-label-{position}'
    open_dropdown = (model or {}).get('openDropdown')
    is_open = open_dropdown is not None and open_dropdown.get('id') == dropdown_id

    trigger_event = repr(DropdownToggle(dropdown_id))
    trigger_html = (
        f'<span class="segment-label index-label {side_class} seg-length-{seg_len}" '
        f'snc-mouse-down="{html.escape(trigger_event)}">{html.escape(label_text)}</span>'
    )

    dropdown_panel = ''
    if is_open:
        # Prefer the user-typed value if present; otherwise fall back to the
        # seeded value from the open handler.
        current_value = open_dropdown.get('value', '') if open_dropdown else ''
        # Align the panel near the relevant edge of the slice highlight.
        align = 'right' if position == 'end' else 'left'
        input_event = f"lambda e: SliceLabelInput(side='{position}', value=e.get('value', ''))"
        # autofocus + snc-select-all: when the framework re-renders this
        # widget after the dropdown opens, it focuses this input and selects
        # its text so the user can immediately type a replacement.
        dropdown_panel = (
            f'<div class="snc-dropdown-panel slice-label-panel" snc-dropdown-align="{align}">'
            f'<div class="snc-dropdown-option">'
            f'<input class="snc-dropdown-input slice-label-input" type="text" '
            f'snc-input="{html.escape(input_event)}" '
            f'value="{html.escape(current_value)}" placeholder="" '
            f'autofocus snc-select-all />'
            f'</div>'
            f'</div>'
        )

    return (
        f'<span class="segment-label-anchor">'
        f'<span class="snc-dropdown-trigger">{trigger_html}{dropdown_panel}</span>'
        f'</span>'
    )


HTML_ESCAPE_CHARS = '<>&\'"'

def text_group_span(chars: list, start_index: int) -> str:
    text = ''.join(html.escape(c) if c in HTML_ESCAPE_CHARS else c for c in chars)
    return f'<span class="string-visualizer-text-group" snc-text-start="{start_index}">{text}</span>'

def char_span(string, index, is_special, highlight=None, model=None, scroll_to=False, is_regex_anchor=False):
    return ''.join(char_span_els(string, index, is_special, highlight, model, scroll_to, is_regex_anchor))

def char_span_els(string, index, is_special, highlight=None, model=None, scroll_to=False, is_regex_anchor=False) -> List[str]:
    """Render a character span with optional selection highlighting.

    Args:
        string: The character(s) to display
        index: The internal index for this character
        is_special: Whether this is a special character (anchor, escape sequence)
        highlight: None or a highlight tuple (start, end, type, pattern_display, repetition, segment_index)
        model: The model state (needed for dropdown open state)
        is_regex_anchor: True for the synthetic regex anchors (^ at string start,
            $ at string end, and the $/^ flanking each \\n display). These are
            NOT real characters of the string - they're visual aids. Index mode
            hides only this class so escape-sequence displays (\\n, \\t), which
            represent real characters, stay visible and indices line up.
    """
    # styles = f'color:{GRAY};' if is_special else ''
    pat_html = ''
    repetition_html = ''
    classes = ['char-span']
    dropdown_id = None

    if (is_special):
        classes.append('is-special')
    if is_regex_anchor:
        classes.append('is-regex-anchor')
        # Differentiate start vs end anchors so CSS can collapse only the END
        # ($) anchors in index mode (so \n displays sit flush at line end),
        # while START (^) anchors stay invisible-but-space-occupying so the
        # rest of the string doesn't shift left.
        anchor_side = 'end' if string == '$' else 'start'
        classes.append(f'is-anchor-{anchor_side}')

    if highlight is not None:
        start, end, seg_type, pat_str, (min_count, max_count), segment_index = highlight
        color = '#00aeff' if seg_type in ('literal', 'slice') else '#868686'
        classes.append('highlight')
        classes.append(f'{seg_type}')

        # Segment-mode highlights: pat_str packs 'seg_id|expr|label'. We
        # short-circuit to a custom rendering path below that emits the
        # SegmentToggle handler on the wrapper, marks the chip selected when
        # appropriate, and renders the inline chip label at the start of the
        # segment.
        is_segment_mode_hl = seg_type in ('segment-region', 'segment-group')
        seg_mode_id = None
        seg_mode_expr = None
        seg_mode_label = None
        if is_segment_mode_hl and pat_str:
            parts = pat_str.split('|', 2)
            if len(parts) == 3:
                seg_mode_id, seg_mode_expr, seg_mode_label = parts
            if model is not None and seg_mode_id in (model.get('selectedSegments') or []):
                classes.append('segment-selected')

        # styles += f' border-{"top" if seg_type == "literal" else "bottom"}: 1px solid {color}; border-image: linear-gradient(to {"bottom" if seg_type == "literal" else "top"}, {color} 20%, transparent 20%) 1;'
        is_interactive = segment_index is not None and not is_segment_mode_hl
        # Slice/index highlights carry static labels in pat_str:
        #   'a|b' -> two labels (start='a', end='b') for multi-char slices
        #   'X'   -> one centered label for a single-char index pick
        slice_start_label = None
        slice_end_label = None
        slice_center_label = None
        if seg_type == 'slice' and pat_str:
            if '|' in pat_str:
                a_lbl, b_lbl = pat_str.split('|', 1)
                slice_start_label = a_lbl
                slice_end_label = b_lbl
            else:
                slice_center_label = pat_str

        # Segment-mode highlights: NO floating chip above. The snc-py-exps,
        # draggable, and SegmentToggle handler all live on the wrapper itself
        # (added below alongside mouse_listener) so the highlighted chars BECOME
        # the clickable/draggable element. Only the match-start / match-end
        # index labels (which aren't on a single char) stay as floating chips.
        # No-op here.

        segment_active = False
        if is_interactive:
            classes.append('is-interactive')
            if model is not None:
                h = model.get('hoverIdx')
                if model.get('dragging'):
                    segment_active = True
                elif h is not None and start <= h < end:
                    segment_active = True
                hd = model.get('handleDrag')
                if hd is not None and hd.get('segmentIndex') == segment_index:
                    segment_active = True
                od = model.get('openDropdown')
                if od is not None and od.get('id') in (
                    f'repetition-{segment_index}',
                    f'fuzzy-pattern-{segment_index}',
                    'slice-label-start',
                    'slice-label-end',
                    'slice-label-center',
                ):
                    segment_active = True

        # Fuzzy segments only get a resize handle on an OPEN end (one that does
        # not abut a neighbor segment). Primary segments have contiguous
        # left-to-right indices, so a segment has a left/right neighbor iff it
        # is not the first/last. Literal segments always get both handles.
        primary_count = (model or {}).get('_primarySegmentCount')
        has_left_neighbor = segment_index is not None and segment_index > 0
        has_right_neighbor = (segment_index is not None and primary_count is not None
                              and segment_index < primary_count - 1)
        fuzzy_open_left = seg_type == 'fuzzy' and not has_left_neighbor
        fuzzy_open_right = seg_type == 'fuzzy' and not has_right_neighbor

        if start == index:
            classes.append('start')
            if slice_center_label is not None:
                # Single-char index pick: render ONE centered label here only.
                # No resize handles - it's a point selection, not a range.
                pat_html = _segment_index_label(slice_center_label, position='center', seg_len=1, model=model)
            elif slice_start_label is not None:
                # Multi-char slice: render the left index label AND a left
                # resize handle (parallel to literal-segment handles).
                seg_len = end - start
                pat_html = _segment_index_label(slice_start_label, position='start', seg_len=seg_len, model=model)
                left_handle_event = repr(HandleMouseDown(segment_index=segment_index, side='left'))
                pat_html += (
                    '<span class="char-span-start-handle-container">'
                    f'<span class="char-span-resize-handle left" snc-mouse-down="{html.escape(left_handle_event)}"></span></span>'
                )
            elif is_interactive:
                seg_len = end - start
                if segment_active and seg_type == 'fuzzy':
                    pat_html = _segment_pattern_label(pat_str, segment_index, model, seg_len)
                if seg_type != 'fuzzy' or fuzzy_open_left:
                    left_handle_event = repr(HandleMouseDown(segment_index=segment_index, side='left'))
                    pat_html += (
                        '<span class="char-span-start-handle-container">'
                        f'<span class="char-span-resize-handle left" snc-mouse-down="{html.escape(left_handle_event)}"></span></span>'
                    )
        if end - 1 == index:
            classes.append('end')
            if slice_end_label is not None:
                seg_len = end - start
                repetition_html = _segment_index_label(slice_end_label, position='end', seg_len=seg_len, model=model)
                right_handle_event = repr(HandleMouseDown(segment_index=segment_index, side='right'))
                repetition_html += (
                    '<span class="char-span-start-handle-container">'
                    f'<span class="char-span-resize-handle right" snc-mouse-down="{html.escape(right_handle_event)}"></span></span>'
                )
            elif is_interactive:
                show_rep = segment_active and not (model.get('dragging') and seg_type == 'literal')
                if show_rep:
                    rep_str = _format_repetition(min_count, max_count)
                    seg_len = end - start
                    repetition_html = _segment_repetition_label(rep_str, segment_index, seg_type, model, seg_len, min_count, max_count)
                if seg_type == 'literal' or fuzzy_open_right:
                    right_handle_event = repr(HandleMouseDown(segment_index=segment_index, side='right'))
                    repetition_html += (
                        '<span class="char-span-start-handle-container">'
                        f'<span class="char-span-resize-handle right" snc-mouse-down="{html.escape(right_handle_event)}"></span></span>'
                    )
    elif model is not None and model.get('hoverIdx') == index and not model.get('dragging'):
        classes.append('hover')

    mouse_listener = f'snc-mouse="{str(index)}"'

    # In segment mode, override the wrapper's mouse-down to toggle the segment
    # selection instead of starting a literal/fuzzy drag. snc-mouse-down beats
    # snc-mouse in the dispatcher's attribute lookup, so we just append it.
    # We also attach snc-py-exps + draggable so the highlighted char itself is
    # the hover-tooltip / drag-source for the segment's expression.
    if (highlight is not None
            and highlight[2] in ('segment-region', 'segment-group')
            and isinstance(highlight[3], str)):
        parts = highlight[3].split('|', 2)
        seg_id_for_listener = parts[0]
        seg_expr = parts[1] if len(parts) >= 2 else ''
        seg_event = repr(SegmentToggle(segment_id=seg_id_for_listener))
        mouse_listener = (f'snc-mouse="{str(index)}" '
                          f'snc-mouse-down="{html.escape(seg_event)}"'
                          f'{py_exp_attrs(seg_expr)}')

    # snc-mouse="5" is shorthand for snc-mouse-move="MouseMove(5)" snc-mouse-down="MouseDown(5)" snc-mouse-up="MouseUp(5)"
    # (this abbreviation speeds up the string visualization quite a bit)
    scroll_attr = ' snc-scroll-to-match' if scroll_to else ''
    # Mirror anchor classes onto the container so CSS can collapse the entire
    # wrapper (display:none) in index mode - hiding only the inner char-span
    # would leave the container's padding/whitespace and the \n display would
    # not sit flush with the end of its line. Only END ($) anchors collapse;
    # START (^) anchors keep their slot so the string doesn't shift left.
    container_classes = 'char-span-container'
    if is_regex_anchor:
        anchor_side = 'end' if string == '$' else 'start'
        container_classes += f' is-regex-anchor is-anchor-{anchor_side}'
    if pat_html or repetition_html:
        return [pat_html, f'<span class="{container_classes}" {mouse_listener}{scroll_attr}><span class="{" ".join(classes)}">', html.escape(string) if string in HTML_ESCAPE_CHARS else string, '</span></span>', repetition_html]
    else:
        return [f'<span class="{container_classes}" {mouse_listener}{scroll_attr}><span class="{" ".join(classes)}">', html.escape(string) if string in HTML_ESCAPE_CHARS else string, '</span></span>']


    # return f'{pat_html}<span snc-mouse="{index}" style="padding-right:1px;{styles}">{html.escape(string) if string in HTML_ESCAPE_CHARS else string}</span>{repetition_html}'
    # index_str = str(index)
    # return f'{pat_html}<span snc-mouse-move="MouseMove({index_str})" snc-mouse-down="MouseDown({index_str})" snc-mouse-up="MouseUp({index_str})" style="color:{GRAY if is_special else STRING};padding-right:1px;{styles}">{html.escape(string) if string in HTML_ESCAPE_CHARS else string}</span>{repetition_html}'

# === Index mapping functions ===

def compute_internal_length(string_value: str) -> int:
    """
    Compute the total internal length for a string's visual representation.

    Internal indices include:
    - 1 prefix anchor (^ at 0)
    - Each character adds 1
    - Each \n adds 2 extra ($ before, ^ after)
    - 1 suffix anchor ($)

    Formula: 2 + len(string_value) + 2 * newline_count
    """
    return 2 + len(string_value) + 2 * string_value.count('\n')


def extract_by_internal_indices(string_value: str, start: int, end: int) -> str:
    """
    Extract text from string_value by internal visual indices.

    Returns a string where visible anchors are represented as DC sentinel
    characters (DC2=^, DC3=$) and regular characters are included as-is.
    This is suitable for passing to char_to_regex_literal or for display
    after converting sentinels to their text representations.

    Args:
        string_value: The original string
        start: Start internal index (inclusive)
        end: End internal index (exclusive)

    Returns:
        String for the range [start:end) with DC sentinel chars for anchors
    """
    if start >= end:
        return ''

    # Build a list of (internal_index, char) pairs
    elements = []
    idx = 0

    # Prefix anchor
    elements.append((idx, DC2))  # ^
    idx += 1

    # Characters
    for char in string_value:
        if char == '\n':
            elements.append((idx, DC3))  # $
            idx += 1
            elements.append((idx, '\n'))
            idx += 1
            elements.append((idx, DC2))  # ^
            idx += 1
        else:
            elements.append((idx, char))
            idx += 1

    # Suffix anchor
    elements.append((idx, DC3))  # $
    idx += 1

    # Extract the slice
    result = []
    for elem_idx, char in elements:
        if start <= elem_idx < end:
            result.append(char)

    return ''.join(result)


def build_internal_to_string_mapping(string_value: str) -> List[int]:
    """
    Build a mapping from internal visualizer indices to actual string character indices.

    Internal indices:
    - 0: ^ prefix marker (maps to string index 0, start of string)
    - 1+: actual characters, but \n expands to 3 indices, \t to 1

    Returns a list where mapping[internal_idx] = string_char_idx.
    """
    mapping = []

    # Prefix marker maps to start of string (index 0)
    mapping.append(0)  # ^ -> 0

    string_idx = 0
    for char in string_value:
        if char == '\n':
            # \n expands to: $ (char), \n (display), ^ (next line marker)
            mapping.append(string_idx)      # $ -> current char
            mapping.append(string_idx + 1)  # \n -> after this char
            mapping.append(string_idx + 1)  # ^ -> after this char (start of next logical char)
        elif char == '\t':
            # \t expands to single display
            mapping.append(string_idx)
        else:
            # Regular character
            mapping.append(string_idx)
        string_idx += 1

    # Add end marker (one past the last character)
    mapping.append(string_idx)

    return mapping


def build_string_to_internal_mapping(string_value: str) -> List[int]:
    """
    Build a mapping from string character indices to internal visualizer indices.

    This is the inverse of build_internal_to_string_mapping.

    For each character position in the original string, returns the internal index
    where that character is displayed. For newlines, returns the index of the \\n
    display element (not the $ or ^ anchors).

    Returns a list where mapping[string_idx] = internal_idx.
    Also appends one extra entry for the end position (len(string)).
    """
    mapping = []

    internal_idx = 1  # Start after ^ (0)

    for char in string_value:
        if char == '\n':
            # \n expands to: $ (internal_idx), \n (internal_idx+1), ^ (internal_idx+2)
            # Map the string's \n to the \n display element (middle one)
            mapping.append(internal_idx + 1)
            internal_idx += 3
        else:
            # Regular character (including \t which displays as single element)
            mapping.append(internal_idx)
            internal_idx += 1

    # End position maps to $ anchor at the end
    mapping.append(internal_idx)

    return mapping


def internal_range_to_string_slice(internal_start: int, internal_end: int, string_value: str) -> Tuple[int, int]:
    """
    Convert internal visualizer index range to actual string slice indices.

    Args:
        internal_start: Start of selection in internal indices (inclusive)
        internal_end: End of selection in internal indices (exclusive)
        string_value: The actual string being visualized

    Returns:
        (slice_start, slice_end) for string[slice_start:slice_end]
    """
    mapping = build_internal_to_string_mapping(string_value)

    # Clamp to valid range
    internal_start = max(0, min(internal_start, len(mapping) - 1))
    internal_end = max(0, min(internal_end, len(mapping)))

    if internal_end <= internal_start:
        return (0, 0)

    slice_start = mapping[internal_start] if internal_start < len(mapping) else len(string_value)
    # For end, we want the character AFTER the last selected internal index
    slice_end = mapping[internal_end - 1] if internal_end - 1 < len(mapping) else len(string_value)

    # If end points to same char as start of that internal index, advance by 1
    if slice_end <= slice_start:
        slice_end = slice_start + 1

    # For end index, we actually want to include the character at internal_end - 1
    # So we need to find what string index that maps to, then add 1
    last_internal = internal_end - 1
    if last_internal < len(mapping):
        last_string_idx = mapping[last_internal]
        # Find if this is a multi-index char (like \n) and get the actual char end
        slice_end = last_string_idx + 1

    return (slice_start, min(slice_end, len(string_value)))


# === Regex building and parsing functions ===

def append_segment_to_regex(current_regex: str | None, segment_type: str, text: str) -> str:
    """
    Append a new segment to the regex pattern.

    The result is canonicalized: literal segments are ungrouped unless
    adjacent to another literal segment.  Postfix flags (i, 1, c, etc.)
    are preserved and the 'c' flag keeps all groups.

    Args:
        current_regex: Current regex search (e.g., r"r'hello'") or None
        segment_type: 'literal' or 'fuzzy'
        text: The text to add (from augmented string, may contain sentinel chars)

    Returns:
        Canonicalized regex pattern with the segment appended, e.g., "r'hello(.*)'"
    """
    if current_regex is None:
        inner_pattern = ""
        flags = ""
    else:
        inner_pattern = get_regex_inner_pattern(current_regex) or ""
        flags = get_search_flags(current_regex)

    if segment_type == 'literal':
        regex_parts = [char_to_regex_literal(char) for char in text]
        new_segment = f"({''.join(regex_parts)})"
    else:  # fuzzy
        new_segment = f"({text})" if text else "(.*)"

    canonical_inner = _canonicalize_inner(f"{inner_pattern}{new_segment}")
    result = make_regex_search(canonical_inner, flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def prepend_segment_to_regex(current_regex: str | None, segment_type: str, text: str) -> str:
    """
    Prepend a new segment to the beginning of the regex pattern.

    Similar to append_segment_to_regex but inserts at the start.
    Used when extending selections from the left side.
    The result is canonicalized.  Postfix flags are preserved.

    Args:
        current_regex: Current regex search (e.g., r"r'hello'") or None
        segment_type: 'literal' or 'fuzzy'
        text: The text to add (from augmented string, may contain sentinel chars)

    Returns:
        Canonicalized regex pattern with the segment prepended.
    """
    if current_regex is None:
        inner_pattern = ""
        flags = ""
    else:
        inner_pattern = get_regex_inner_pattern(current_regex) or ""
        flags = get_search_flags(current_regex)

    if segment_type == 'literal':
        regex_parts = [char_to_regex_literal(char) for char in text]
        new_segment = f"({''.join(regex_parts)})"
    else:  # fuzzy
        new_segment = f"({text})" if text else "(.*)"

    canonical_inner = _canonicalize_inner(f"{new_segment}{inner_pattern}")
    result = make_regex_search(canonical_inner, flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def insert_segment_at_position(current_regex: str | None, position: int, segment_type: str, text: str) -> str:
    """
    Insert a new segment at a specific position in the regex pattern.

    Used when clicking inside a fuzzy segment to split/anchor it. The position
    determines where in the regex the new segment goes to maintain text order.
    Postfix flags are preserved.

    Args:
        current_regex: Current regex search (e.g., r"r'(.*)world'") or None
        position: The 0-based position to insert at (0 = prepend, len = append)
        segment_type: 'literal' or 'fuzzy'
        text: The text to add (from augmented string, may contain sentinel chars)

    Returns:
        New regex pattern with the segment inserted at the given position (canonicalized).
    """
    if current_regex is None:
        return append_segment_to_regex(None, segment_type, text)

    if segment_type == 'literal':
        regex_parts = [char_to_regex_literal(char) for char in text]
        new_segment_text = ''.join(regex_parts)
    else:  # fuzzy
        new_segment_text = text if text else '.*'

    inner_pattern = get_regex_inner_pattern(current_regex) or ""
    flags = get_search_flags(current_regex)
    segments = parse_all_segments(inner_pattern)

    new_seg = {'text': new_segment_text, 'is_grouped': True}

    if position <= 0:
        segments.insert(0, new_seg)
    elif position >= len(segments):
        segments.append(new_seg)
    else:
        segments.insert(position, new_seg)

    fully_grouped_inner = ''.join(f"({s['text']})" for s in segments)
    canonical_inner = _canonicalize_inner(fully_grouped_inner)
    result = make_regex_search(canonical_inner, flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def extract_quantifier(pattern: str) -> tuple[str, str]:
    """
    Extract the base pattern and quantifier from a regex pattern string.

    Args:
        pattern: A regex pattern like ".*", "\\s+", "[a-z]{2,5}", ".*?" (lazy)

    Returns:
        (base_pattern, quantifier) tuple, e.g., (".", "*") or ("[a-z]", "{2,5}")
        If no quantifier, returns (pattern, "")
    """
    # Match quantifiers at the end: *, +, ?, {n}, {n,}, {,m}, {n,m}
    # Also handles lazy quantifiers: *?, +?, ??, {n,m}?
    quantifier_match = re.search(r'([*+?]|\{[0-9,]+\})\??$', pattern)
    if quantifier_match:
        quantifier = quantifier_match.group(0)  # Use group(0) to include the optional ?
        base = pattern[:quantifier_match.start()]
        return (base, quantifier)
    return (pattern, "")


def replace_segment_pattern(selection_regex: str, segment_index: int, new_char_class: str) -> str:
    """
    Replace the character class of a specific segment, preserving its quantifier.

    Used when selecting a different fuzzy pattern from the dropdown.
    Postfix flags are preserved.

    Args:
        selection_regex: Current regex search (e.g., r"r'hello'", canonical form)
        segment_index: 0-based index of the segment to replace (matches highlight segment indices)
        new_char_class: The new character class (e.g., r"\\s", r"\\d", r"[a-z]")
                        Note: This should NOT include a quantifier.

    Returns:
        New regex pattern with the segment's character class replaced,
        but its quantifier preserved (canonicalized).
    """
    inner_pattern = get_regex_inner_pattern(selection_regex) or ""
    flags = get_search_flags(selection_regex)

    segments = parse_all_segments(inner_pattern)

    if 0 <= segment_index < len(segments):
        old_text = segments[segment_index]['text']
        _, quantifier = extract_quantifier(old_text)
        segments[segment_index] = {'text': f'{new_char_class}{quantifier}', 'is_grouped': True}

    fully_grouped_inner = ''.join(f"({s['text']})" for s in segments)
    canonical_inner = _canonicalize_inner(fully_grouped_inner)
    result = make_regex_search(canonical_inner, flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def _is_single_atom(pattern: str) -> bool:
    """Check if a regex pattern is a single atom that can have a quantifier applied directly.

    Single atoms include: ., \s, \d, \w, [a-z], h, \n, etc.
    Multi-atom patterns like 'hello' or '\nhello' need a (?:...) wrapper for group repetition.

    Args:
        pattern: A regex pattern string (without quantifier)

    Returns:
        True if the pattern is a single regex atom.
    """
    try:
        parsed = list(regex_parser.parse(pattern))
        return len(parsed) == 1
    except Exception:
        return False


# Available repetition options for dropdown selection
# Each tuple is (quantifier_value, display_label)
REPETITION_OPTIONS = [
    ('1', '1'),
    ('?', '?'),
    ('*', '*'),
    ('*?', '*?'),
    ('+', '+'),
    ('+?', '+?'),
]

# What each repetition option does, shown on hover. Keyed by the option value;
# 'exact' and 'range' are the two typed-in rows below the simple options.
REPETITION_TOOLTIPS = [
    ('1', 'Exactly one'),
    ('?', 'Zero or one'),
    ('*', 'Zero or more, as many as possible'),
    ('*?', 'Zero or more, the fewest possible'),
    ('+', 'One or more, as many as possible'),
    ('+?', 'One or more, the fewest possible'),
    ('exact', 'Exactly n'),
    ('range', 'Between n and m (leave m blank for no upper limit)'),
]
_REPETITION_TOOLTIP = dict(REPETITION_TOOLTIPS)


def _segment_is_lazy(model: dict | None, segment_index: int) -> bool:
    """Whether the segment's quantifier is lazy (`*?`, `+?`, `??`, `{n,m}?`).

    Laziness is not part of the (min, max) bounds the highlighter carries, so
    it is read back off the search itself.
    """
    search = model.get('search') if model else None
    inner = get_regex_inner_pattern(search) if search else None
    if not inner:
        return False
    try:
        segments = parse_all_segments(inner)
        _, quantifier = extract_quantifier(segments[segment_index]['text'])
    except Exception:
        return False
    return len(quantifier) > 1 and quantifier.endswith('?')


def replace_segment_repetition(selection_regex: str, segment_index: int, new_quantifier: str) -> str:
    """
    Replace the quantifier of a specific segment, preserving its base pattern.

    For single-atom patterns (., \\s, [a-z], single char), the quantifier is applied directly.
    For multi-atom patterns (hello, \\nhello), wraps in (?:...) when adding a quantifier,
    and unwraps when removing.  Postfix flags are preserved.

    Args:
        selection_regex: Current regex search (e.g., r"r'hello'", canonical form)
        segment_index: 0-based index of the segment to modify
        new_quantifier: New quantifier string ('', '?', '*', '+', '{n}', '{n,m}')
                        Use '' to remove the quantifier (exactly 1 match).

    Returns:
        New regex pattern with the segment's quantifier replaced,
        but its base pattern preserved (canonicalized).
    """
    inner_pattern = get_regex_inner_pattern(selection_regex) or ""
    flags = get_search_flags(selection_regex)

    segments = parse_all_segments(inner_pattern)

    if 0 <= segment_index < len(segments):
        old_text = segments[segment_index]['text']
        base, _ = extract_quantifier(old_text)

        raw_base = base
        if raw_base.startswith('(?:') and raw_base.endswith(')'):
            raw_base = raw_base[3:-1]

        if new_quantifier == '':
            new_text = raw_base
        else:
            if _is_single_atom(raw_base):
                new_text = f'{raw_base}{new_quantifier}'
            else:
                new_text = f'(?:{raw_base}){new_quantifier}'

        segments[segment_index] = {'text': new_text, 'is_grouped': True}

    fully_grouped_inner = ''.join(f"({s['text']})" for s in segments)
    canonical_inner = _canonicalize_inner(fully_grouped_inner)
    result = make_regex_search(canonical_inner, flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def resize_literal_segment(selection_regex: str, segment_index: int, string_value: str,
                           new_start: int, new_end: int) -> str:
    """
    Resize a literal segment to cover [new_start, new_end) in internal indices.

    Extracts text from string_value at the given internal indices, converts each
    character to its regex literal form, and replaces the specified segment's content.
    Postfix flags are preserved.

    Args:
        selection_regex: Regex search, e.g., "r'(hello)'" or "r'hello'"
        segment_index: 0-based index of the segment to resize
        string_value: The string being visualized
        new_start: New start internal index (inclusive)
        new_end: New end internal index (exclusive)

    Returns:
        New regex pattern with the segment resized, or original if range is empty.
    """
    if new_end <= new_start:
        return selection_regex

    text = extract_by_internal_indices(string_value, new_start, new_end)
    new_content = ''.join(char_to_regex_literal(char) for char in text)
    return _replace_segment_content(selection_regex, segment_index, new_content)


def _replace_segment_content(selection_regex: str, segment_index: int, new_content: str) -> str:
    """Replace the pattern text of one segment, preserving grouping and flags.

    Shared by resize_literal_segment / resize_fuzzy_segment: both differ only in
    how they derive the replacement content from the dragged range.
    """
    inner_pattern = get_regex_inner_pattern(selection_regex) or ""
    flags = get_search_flags(selection_regex)
    segments = parse_all_segments(inner_pattern)

    if not segments or segment_index >= len(segments):
        return selection_regex

    segments[segment_index]['text'] = new_content

    parts = []
    for seg in segments:
        if seg['is_grouped']:
            parts.append(f"({seg['text']})")
        else:
            parts.append(seg['text'])

    result = make_regex_search(''.join(parts), flags)
    if 'c' in flags:
        result = ensure_all_groups(result)
    return result


def resize_fuzzy_segment(selection_regex: str, segment_index: int, string_value: str,
                         new_start: int, new_end: int,
                         prev_char: str | None, next_char: str | None) -> str:
    """
    Resize a fuzzy segment to cover [new_start, new_end) in internal indices.

    Unlike resize_literal_segment, this re-runs the fuzzy pattern inference
    (synthesize_fuzzy_pattern) over the new range so the segment stays fuzzy
    rather than being baked into an escaped literal. The boundary context
    (prev_char / next_char) mirrors the new-fuzzy-selection logic:

        - Pass '' for an open edge at the string boundary.
        - Pass the adjacent character for an open edge in the middle of the
          string (so inference can avoid overshooting it and pick + / {n}).
        - Pass None for an edge that abuts an existing segment (so inference
          uses * since the neighbor already anchors the match).

    Args:
        selection_regex: Regex search, e.g., "r'(.*)'"
        segment_index: 0-based index of the segment to resize
        string_value: The string being visualized
        new_start: New start internal index (inclusive)
        new_end: New end internal index (exclusive)
        prev_char: Character context before the range (see above)
        next_char: Character context after the range (see above)

    Returns:
        New regex pattern with the segment resized, or original if range is empty.
    """
    if new_end <= new_start:
        return selection_regex

    selected_text = extract_by_internal_indices(string_value, new_start, new_end)
    actual_text = ''.join(c for c in selected_text if c not in _SENTINEL_CHARS)
    new_content = synthesize_fuzzy_pattern(actual_text, prev_char, next_char)
    return _replace_segment_content(selection_regex, segment_index, new_content)


# Valid string literal prefixes (lowercase); checked case-insensitively.
# Note: bare 'r' is in this set so _find_closing_delimiter handles raw-string
# style input, but parse_search_term reclassifies a bare 'r'/'R' prefix as a
# regex (not a string literal) so users can type r'pattern' the way they would
# in real Python.
_STRING_PREFIXES = {'', 'f', 'r', 'b', 'u', 'fr', 'rf', 'br', 'rb'}


def make_regex_search(inner: str, flags: str = '') -> str:
    """Build a canonical regex search string in r'pattern'flags form.

    Picks the smallest quoting that holds the pattern verbatim:
      - r'pattern'         (preferred)
      - r"pattern"         (when pattern contains a single quote)
      - r'''pattern'''     (when pattern contains both ' and ")
      - r\"\"\"pattern\"\"\"   (last resort; pattern contains all of the above)

    Falls back to a non-raw escaped string literal in the (extremely rare)
    case that the pattern contains every triple-quote variant.
    """
    if "'" not in inner:
        return f"r'{inner}'{flags}"
    if '"' not in inner:
        return f'r"{inner}"{flags}'
    if "'''" not in inner:
        return f"r'''{inner}'''{flags}"
    if '"""' not in inner:
        return f'r"""{inner}"""{flags}'
    escaped = inner.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'{flags}"


def _extract_raw_string_inner(literal: str) -> str | None:
    """If literal is a bare r-prefixed raw string (r'..', r\"..\", r'''..''',
    r\"\"\"..\"\"\"), return the inner pattern; else None.

    Other prefixes that contain 'r' (rb, br, fr, rf) are NOT treated as regex.
    """
    if not literal or len(literal) < 3:
        return None
    if literal[0] not in ('r', 'R'):
        return None
    if literal[1] not in ("'", '"'):
        # Has another prefix character (e.g. rb', rf') - not a pure r-string.
        return None
    rest = literal[1:]
    if rest.startswith("'''") and rest.endswith("'''") and len(rest) >= 6:
        return rest[3:-3]
    if rest.startswith('"""') and rest.endswith('"""') and len(rest) >= 6:
        return rest[3:-3]
    if rest[0] in ("'", '"') and rest[-1] == rest[0] and len(rest) >= 2:
        return rest[1:-1]
    return None


def _find_closing_delimiter(search: str | None) -> int | None:
    """Find the index just past the closing delimiter of a search string.

    Supports Python string literals ('str', "str", triple-quoted, with
    f/r/b/u prefixes - including the r'..' raw-string form used for regex)
    and backtick expressions (`expr`).

    Returns None if no valid closing delimiter is found.
    """
    if not search:
        return None

    # Backtick expression: `expr`
    if search[0] == '`':
        idx = search.find('`', 1)
        return idx + 1 if idx > 0 else None

    # String literal: optional prefix + quote
    prefix_end = 0
    lower = search.lower()
    for length in (2, 1):
        candidate = lower[:length]
        if candidate in _STRING_PREFIXES and candidate != '':
            prefix_end = length
            break

    if prefix_end >= len(search):
        return None

    rest = search[prefix_end:]
    is_raw = 'r' in lower[:prefix_end]

    # Detect quote style
    if rest.startswith("'''") or rest.startswith('"""'):
        quote = rest[:3]
        scan_start = 3
    elif rest[0] in ("'", '"'):
        quote = rest[0]
        scan_start = 1
    else:
        return None

    triple = len(quote) == 3
    i = scan_start
    while i < len(rest):
        if not is_raw and rest[i] == '\\' and i + 1 < len(rest):
            i += 2
            continue
        if triple:
            if rest[i:i + 3] == quote:
                return prefix_end + i + 3
        else:
            if rest[i] == quote:
                return prefix_end + i + 1
        i += 1

    return None


def _is_valid_python_expression(s: str) -> bool:
    """Check if s parses as a valid Python expression (supports $ dollar-scope syntax)."""
    return dollar_expr_parses(s)


def parse_slice_parts(search: str | None) -> tuple | None:
    """Try to parse search as a slice expression (e.g. '5:', ':5', '5:10', 'x:10').

    For each ':' in the search string, split into left/right. If both sides
    are blank or parse as valid Python expressions, return (left, right).
    Returns None if no valid slice split is found.

    Uses the same guess-and-check approach as replace_dollars_in_py_exp.
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
                return (left, right)
    return None


def is_regex_search(search: str | None) -> bool:
    """Check if the search string is a regex search."""
    p = parse_search_term(search)
    return p is not None and p[0] == 'regex'


def is_slice_search(search: str | None) -> bool:
    """Check if the search is a slice expression like '5:', ':10', '5:10'."""
    p = parse_search_term(search)
    return p is not None and p[0] == 'slice'


def is_literal_string_search(search: str | None, eval_in_scope=None) -> bool:
    """Check if the search matches a literal string: 'sub', "sub", or `x`/x.

    An expression search only counts when it evaluates to a string; the other
    things an expression can be (an int, a list of ints, a list of pairs) are
    index searches, not literal matches.

    These searches run as re.finditer(re.escape(...)), so they yield the same
    match objects the regex path does - they just have no capture groups.
    """
    p = parse_search_term(search)
    if not p:
        return False
    kind, term, _flags = p
    if kind == 'string':
        return eval_string_search(search) is not None
    if kind == 'expr' and term:
        try:
            return isinstance(eval_in_scope(term) if eval_in_scope else eval(term), str)
        except Exception:
            return False
    return False


def get_search_flags(search: str | None) -> str:
    """Extract postfix flags from a search string."""
    p = parse_search_term(search)
    return p[2] if p else ''


def is_first_match_mode(search: str | None) -> bool:
    """Check if the search is in first-match mode ('1' in postfix flags)."""
    return '1' in get_search_flags(search)


def is_case_insensitive(search: str | None) -> bool:
    """Check if the search is case-insensitive ('i' in postfix flags)."""
    return 'i' in get_search_flags(search)


def is_capture_groups_mode(search: str | None) -> bool:
    """Check if the search has capture groups preserved ('c' in postfix flags)."""
    return 'c' in get_search_flags(search)


def _is_flags_only(search: str | None) -> bool:
    """Check if search is a bare backtick form with only flags and no content (e.g. ``i1)."""
    p = parse_search_term(search)
    return p is not None and p[0] == 'expr' and p[1] == ''


def parse_search_term(search: str | None) -> tuple | None:
    """Parse any search string into (kind, term, flags).

    Returns None for empty or None inputs.
    kind is one of 'regex', 'string', 'slice', 'expr'.
    term is the extracted content:
      - regex: inner pattern (without the r'..' delimiters)
      - string: the literal including quotes (e.g. "'hello'")
      - slice: (start, stop) tuple
      - expr: expression text (backtick content or bare text)
    flags is the postfix flags string (e.g. '1i').

    Regex syntax mirrors Python's raw-string form so users can type
    r'pattern', r"pattern", r'''pattern''' or r\"\"\"pattern\"\"\" with
    optional flags appended. Other string prefixes (b'..', f'..', rb'..',
    fr'..', etc.) remain string literal searches.
    """
    if not search:
        return None
    if search[0] == '`':
        end = _find_closing_delimiter(search)
        if end is not None:
            return ('expr', search[1:end - 1], search[end:])
        return ('expr', search[1:], '')
    end = _find_closing_delimiter(search)
    if end is not None:
        literal = search[:end]
        flags = search[end:]
        inner = _extract_raw_string_inner(literal)
        if inner is not None:
            return ('regex', inner, flags)
        return ('string', literal, flags)
    parts = parse_slice_parts(search)
    if parts is not None:
        return ('slice', parts, '')
    return ('expr', search, '')


def get_regex_inner_pattern(search: str | None) -> str | None:
    """Extract the inner pattern from a regex search (strips r'..' delimiters and flags)."""
    p = parse_search_term(search)
    return p[1] if p and p[0] == 'regex' else None


def eval_string_search(search: str | None) -> str | None:
    """Evaluate the string literal in a search to get the actual Python string value.

    Returns None if not a string search or if evaluation fails.
    """
    p = parse_search_term(search)
    if not p or p[0] != 'string':
        return None
    try:
        result = eval(p[1])
        if isinstance(result, (str, bytes)):
            return result if isinstance(result, str) else result.decode('utf-8', errors='replace')
        return None
    except Exception:
        return None


def _toggle_search_flag(search: str, flag_char: str) -> str:
    """Toggle a single flag character in the postfix of a search string.

    Bare text (no delimiters) is wrapped in backticks before adding a flag.
    """
    end = _find_closing_delimiter(search)
    if end is None:
        # Bare text: wrap in backticks so we can append a flag
        search = f'`{search}`'
        end = len(search)
    prefix = search[:end]
    flags = search[end:]
    if flag_char in flags:
        flags = flags.replace(flag_char, '')
    else:
        flags += flag_char
    return prefix + flags


# Mapping from category constants to shorthand display strings
_CATEGORY_TO_SHORTHAND = {
    'CATEGORY_WORD': r'\w',
    'CATEGORY_NOT_WORD': r'\W',
    'CATEGORY_DIGIT': r'\d',
    'CATEGORY_NOT_DIGIT': r'\D',
    'CATEGORY_SPACE': r'\s',
    'CATEGORY_NOT_SPACE': r'\S',
}


def _char_class_to_string(items: list) -> str:
    """
    Reconstruct a character class from its parsed items.

    Handles shorthand classes (\w, \s, \d, etc.), ranges ([a-z]),
    and explicit character sets ([abc]).
    """
    # Check for single shorthand category like \w, \s, \d
    if len(items) == 1:
        item_op = str(items[0][0])
        item_av = items[0][1] if len(items[0]) > 1 else None
        if item_op == 'CATEGORY' and item_av is not None:
            cat_name = str(item_av)
            if cat_name in _CATEGORY_TO_SHORTHAND:
                return _CATEGORY_TO_SHORTHAND[cat_name]

    # Need to build full [...] representation
    negated = False
    parts = []

    for item in items:
        item_op = str(item[0])
        item_av = item[1] if len(item) > 1 else None

        if item_op == 'NEGATE':
            negated = True

        elif item_op == 'CATEGORY':
            cat_name = str(item_av)
            if cat_name in _CATEGORY_TO_SHORTHAND:
                parts.append(_CATEGORY_TO_SHORTHAND[cat_name])
            # else skip unknown categories

        elif item_op == 'RANGE':
            start, end = item_av
            start_char = chr(start)
            end_char = chr(end)
            # Escape special chars in ranges
            if start_char in r'\]-^':
                start_char = '\\' + start_char
            if end_char in r'\]-^':
                end_char = '\\' + end_char
            parts.append(f'{start_char}-{end_char}')

        elif item_op == 'LITERAL':
            char = chr(item_av)
            # Escape special chars inside character class
            if char in r'\]-^':
                parts.append('\\' + char)
            elif char == '\n':
                parts.append(r'\n')
            elif char == '\t':
                parts.append(r'\t')
            elif char == '\r':
                parts.append(r'\r')
            elif not char.isprintable():
                parts.append(f'\\x{item_av:02x}')
            else:
                parts.append(char)

    prefix = '[^' if negated else '['
    return prefix + ''.join(parts) + ']'


def _subpattern_to_string(subpattern: list, include_repetition: bool = True) -> str:
    """
    Reconstruct a regex pattern string from a parsed subpattern AST.

    This converts the internal regex parser representation back to a human-readable
    string for display purposes.
    """
    result = []

    for item in subpattern:
        op = item[0]
        av = item[1] if len(item) > 1 else None
        op_name = str(op)

        if op_name == 'LITERAL':
            # av is the character code
            char = chr(av)
            # Escape special regex chars and non-printable chars
            if char in r'\.^$*+?{}[]|()':
                result.append('\\' + char)
            elif char == '\n':
                result.append(r'\n')
            elif char == '\t':
                result.append(r'\t')
            elif char == '\r':
                result.append(r'\r')
            elif not char.isprintable():
                result.append(f'\\x{av:02x}')
            else:
                result.append(char)

        elif op_name == 'ANY':
            result.append('.')

        elif op_name == 'AT':
            if av == AT_BEGINNING_STRING:
                result.append(r'\A')
            elif av == AT_BEGINNING:
                result.append('^')
            elif av == AT_END:
                result.append('$')
            elif av == AT_END_STRING:
                result.append(r'\Z')
            # Other AT types (word boundary, etc.) - just skip for display

        elif op_name in ('MAX_REPEAT', 'MIN_REPEAT'):
            min_count, max_count, repeat_subpattern = av
            inner = _subpattern_to_string(list(repeat_subpattern))
            if include_repetition:
                if min_count == 0 and max_count == MAXREPEAT:
                    result.append(inner + '*')
                elif min_count == 1 and max_count == MAXREPEAT:
                    result.append(inner + '+')
                elif min_count == 0 and max_count == 1:
                    result.append(inner + '?')
                elif min_count == max_count:
                    result.append(inner + f'{{{min_count}}}')
                else:
                    max_str = '' if max_count == MAXREPEAT else str(max_count)
                    result.append(inner + f'{{{min_count},{max_str}}}')
                if op_name == 'MIN_REPEAT':
                    result.append('?')  # Non-greedy marker
            else:
                result.append(inner)

        elif op_name == 'SUBPATTERN':
            # Nested group
            group_id, add_flags, del_flags, nested = av
            result.append('(' + _subpattern_to_string(list(nested)) + ')')

        elif op_name == 'ASSERT':
            # Lookahead/lookbehind
            direction, nested = av
            inner = _subpattern_to_string(list(nested))
            if direction == 1:
                result.append(f'(?={inner})')
            elif direction == -1:
                result.append(f'(?<={inner})')

        elif op_name == 'ASSERT_NOT':
            direction, nested = av
            inner = _subpattern_to_string(list(nested))
            if direction == 1:
                result.append(f'(?!{inner})')
            elif direction == -1:
                result.append(f'(?<!{inner})')

        elif op_name == 'IN':
            # Character class [...] - reconstruct properly
            char_class_result = _char_class_to_string(av)
            result.append(char_class_result)

        elif op_name == 'BRANCH':
            # Alternation
            branches = [_subpattern_to_string(list(b)) for b in av[1]]
            result.append('|'.join(branches))

        elif op_name == 'GROUPREF':
            result.append(f'\\{av}')

        # Other operations can be added as needed

    return ''.join(result)


def _is_wildcard_pattern(pattern_item) -> bool:
    """Check if a pattern item matches variable characters (is a wildcard).

    Returns True for patterns like ., \s, \d, \w, [a-z], etc.
    Returns False for literal characters like \n, \., a, etc.
    """
    op_name = str(pattern_item[0])
    # ANY matches any character (.)
    if op_name == 'ANY':
        return True
    # IN is a character class like [a-z], \d, \s, \w, etc.
    if op_name == 'IN':
        return True
    return False


def _analyze_group(subpattern: list) -> Tuple[List[str], bool, Tuple[int, int | float], str]:
    """
    Analyze a regex subpattern to find leading/trailing anchors, check if it's fuzzy,
    extract repetition bounds, and reconstruct the pattern string for display.

    Returns:
        (anchor_types, is_fuzzy, repetition_bounds, pattern_display) where:
        - anchor_types is a list of anchor names found
          ('AT_BEGINNING_STRING', 'AT_BEGINNING', 'AT_END', 'AT_END_STRING')
        - is_fuzzy is True if the pattern matches variable text (wildcards)
        - repetition_bounds is (min, max) tuple where max can be float('inf')
        - pattern_display is the reconstructed pattern string for display
    """
    anchors = []
    is_fuzzy = False
    repetition: Tuple[int, int | float] = (1, 1)  # Default: exactly one match

    for item in subpattern:
        op = item[0]
        av = item[1] if len(item) > 1 else None
        op_name = str(op)

        if op_name == 'AT':
            if av == AT_BEGINNING_STRING:
                anchors.append('AT_BEGINNING_STRING')
            elif av == AT_BEGINNING:
                anchors.append('AT_BEGINNING')
            elif av == AT_END:
                anchors.append('AT_END')
            elif av == AT_END_STRING:
                anchors.append('AT_END_STRING')

        elif op_name == 'ANY':
            # Single . (any character) is fuzzy
            is_fuzzy = True

        elif op_name == 'IN':
            # Character class like [a-z], \d, \s, \w, etc. without repetition
            # These are fuzzy since they match variable characters
            is_fuzzy = True

        elif op_name in ('MAX_REPEAT', 'MIN_REPEAT'):
            min_count, max_count, repeat_pattern = av
            # Extract repetition bounds
            # max_count is MAXREPEAT for unbounded (*, +)
            if max_count == MAXREPEAT:
                repetition = (min_count, float('inf'))
            else:
                repetition = (min_count, max_count)

            # Check if the repeated pattern is a wildcard (., \s, \d, [a-z], etc.)
            # Only wildcard patterns with repetition are fuzzy
            # Literal patterns like \n{2,3} are NOT fuzzy
            if len(repeat_pattern) >= 1 and _is_wildcard_pattern(repeat_pattern[0]):
                is_fuzzy = True

    # Reconstruct the pattern string from the AST
    pattern_display = _subpattern_to_string(subpattern, include_repetition=False)

    return anchors, is_fuzzy, repetition, pattern_display


def parse_top_level_segments(inner_pattern: str) -> list:
    """Parse a regex inner pattern into top-level segments by parentheses.

    A segment is either:
    - Ungrouped content (literal text, anchors, fuzzy patterns not wrapped in parens)
    - A top-level parenthesized group

    Returns list of dicts with:
    - 'text': Content (without outer parens for grouped segments)
    - 'is_grouped': Whether the segment was wrapped in parentheses

    Note: ungrouped content may contain mixed literal/fuzzy patterns (e.g., 'hello.*world').
    Use parse_all_segments() if you need each literal/fuzzy region as a separate segment.

    Examples:
        'hello.*world'    -> [{'text':'hello.*world','is_grouped':False}]
        '(hello)(world)'  -> [{'text':'hello','is_grouped':True}, {'text':'world','is_grouped':True}]
        'hello(.*)'       -> [{'text':'hello','is_grouped':False}, {'text':'.*','is_grouped':True}]
    """
    if not inner_pattern:
        return []

    segments = []
    depth = 0
    group_start = None
    last_end = 0
    i = 0

    while i < len(inner_pattern):
        char = inner_pattern[i]

        if char == '\\':
            # Skip escaped character
            i += 2
            continue

        if char == '(':
            if depth == 0:
                # Capture ungrouped content before this group
                if i > last_end:
                    segments.append({'text': inner_pattern[last_end:i], 'is_grouped': False})
                group_start = i
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                segments.append({'text': inner_pattern[group_start + 1:i], 'is_grouped': True})
                last_end = i + 1

        i += 1

    # Capture trailing ungrouped content
    if last_end < len(inner_pattern):
        segments.append({'text': inner_pattern[last_end:], 'is_grouped': False})

    return segments


# --- String-level helpers for splitting ungrouped regex content ---

def _is_fuzzy_start(text: str, pos: int) -> int | None:
    """Check if position starts a fuzzy base pattern (wildcard).

    Returns end position of the base pattern, or None if not a fuzzy start.
    Recognizes: . (any), \\s \\S \\d \\D \\w \\W (shorthand classes), [...] (char classes).
    """
    if pos >= len(text):
        return None

    c = text[pos]

    # . (any character) - but not \\. (escaped dot)
    if c == '.':
        return pos + 1

    # Shorthand character classes: \s \S \d \D \w \W
    if c == '\\' and pos + 1 < len(text) and text[pos + 1] in 'sSwWdD':
        return pos + 2

    # Character class [...]
    if c == '[':
        j = pos + 1
        if j < len(text) and text[j] == '^':
            j += 1  # negation
        if j < len(text) and text[j] == ']':
            j += 1  # ] at start of class is literal
        while j < len(text):
            if text[j] == '\\' and j + 1 < len(text):
                j += 2
                continue
            if text[j] == ']':
                return j + 1
            j += 1
        return None  # Unclosed [

    return None


def _skip_quantifier(text: str, pos: int) -> int:
    """Skip a quantifier at the given position. Returns new position (unchanged if no quantifier)."""
    if pos >= len(text):
        return pos

    c = text[pos]
    if c in '*+?':
        pos += 1
        # Lazy modifier?
        if pos < len(text) and text[pos] == '?':
            pos += 1
        return pos

    if c == '{':
        j = pos + 1
        while j < len(text) and (text[j].isdigit() or text[j] == ','):
            j += 1
        if j < len(text) and text[j] == '}':
            j += 1
            # Lazy modifier?
            if j < len(text) and text[j] == '?':
                j += 1
            return j

    return pos


def _skip_literal_unit(text: str, pos: int) -> int:
    """Skip one literal unit (char or escape sequence) at the given position."""
    if pos >= len(text):
        return pos
    if text[pos] == '\\' and pos + 1 < len(text):
        return pos + 2
    return pos + 1


def _split_ungrouped_into_segments(text: str) -> list:
    """Split ungrouped pattern text into separate literal and fuzzy segments.

    Fuzzy patterns are wildcard bases (., \\s, \\d, \\w, [...]) with optional quantifiers.
    Everything else is literal.

    Returns list of segment text strings.
    E.g., 'hello.*world' -> ['hello', '.*', 'world']
          'hello'         -> ['hello']
          '.*'            -> ['.*']
          '.*\\s+'        -> ['.*', '\\s+']
    """
    if not text:
        return []

    segments = []
    i = 0
    literal_start = 0

    while i < len(text):
        fuzzy_base_end = _is_fuzzy_start(text, i)
        if fuzzy_base_end is not None:
            # Flush accumulated literal
            if i > literal_start:
                segments.append(text[literal_start:i])
            # Consume fuzzy base + optional quantifier
            fuzzy_end = _skip_quantifier(text, fuzzy_base_end)
            segments.append(text[i:fuzzy_end])
            i = fuzzy_end
            literal_start = i
        else:
            # Skip one literal unit
            i = _skip_literal_unit(text, i)

    # Flush remaining literal
    if literal_start < len(text):
        segments.append(text[literal_start:len(text)])

    return segments


def parse_all_segments(inner_pattern: str) -> list:
    """Parse a regex inner pattern into all segments, splitting ungrouped fuzzy/literal.

    Like parse_top_level_segments, but also splits ungrouped content at fuzzy/literal
    boundaries. The number of segments returned matches the number of capture groups
    produced by _to_fully_grouped_inner().

    Returns list of dicts with 'text' and 'is_grouped'.

    Examples:
        'hello.*world'    -> [{'text':'hello','is_grouped':False}, {'text':'.*','is_grouped':False}, {'text':'world','is_grouped':False}]
        '(hello)(world)'  -> [{'text':'hello','is_grouped':True}, {'text':'world','is_grouped':True}]
        '.*(hello)(world)' -> [{'text':'.*','is_grouped':False}, {'text':'hello','is_grouped':True}, {'text':'world','is_grouped':True}]
    """
    string_segments = parse_top_level_segments(inner_pattern)
    all_segments = []
    for seg in string_segments:
        if seg['is_grouped']:
            all_segments.append(seg)
        else:
            sub_texts = _split_ungrouped_into_segments(seg['text'])
            for st in sub_texts:
                all_segments.append({'text': st, 'is_grouped': False})
    return all_segments


def _canonicalize_inner(inner: str) -> str:
    """Canonicalize a regex inner pattern (no delimiters, no flags).

    Removes unnecessary top-level capturing groups. See canonicalize_regex
    for the canonicalization rules.
    """
    if not inner:
        return inner

    segments = parse_all_segments(inner)
    if not segments:
        return inner

    for seg in segments:
        try:
            parsed = regex_parser.parse(seg['text'])
            _, is_fuzzy, _, _ = _analyze_group(list(parsed))
            seg['is_fuzzy'] = is_fuzzy
        except Exception:
            seg['is_fuzzy'] = False

    # Only non-fuzzy (literal) segments adjacent to another non-fuzzy segment
    # need groups to disambiguate their boundary.
    needs_group = [False] * len(segments)
    for i in range(len(segments) - 1):
        if not segments[i]['is_fuzzy'] and not segments[i + 1]['is_fuzzy']:
            needs_group[i] = True
            needs_group[i + 1] = True

    parts = []
    for i, seg in enumerate(segments):
        # A segment must also keep its group if it contains non-capturing
        # groups like (?:hello)+, because ungrouping would cause
        # parse_top_level_segments to misinterpret those parens as top-level.
        needs_explicit = '(?' in seg['text']
        if needs_group[i] or needs_explicit:
            parts.append(f"({seg['text']})")
        else:
            parts.append(seg['text'])

    return ''.join(parts)


def canonicalize_regex(selection_regex: str | None) -> str | None:
    """Simplify a selection regex by removing unnecessary top-level groups.

    The canonical form removes groups from ALL segments (literal and fuzzy) unless
    two non-fuzzy (literal) segments are adjacent, in which case both keep groups
    to disambiguate their boundary.

    Examples:
        "r'(hello)(.*)(world)'" -> "r'hello.*world'"     (no adjacent literals)
        "r'(hello)(world)'"     -> "r'(hello)(world)'"   (adjacent literals need groups)
        "r'(hello)(world)(.*)'" -> "r'(hello)(world).*'" (hello/world adjacent, .* not)

    Postfix flags are preserved. This is idempotent: canonicalizing an already-
    canonical regex returns the same result.
    """
    if selection_regex is None:
        return None

    parsed = parse_search_term(selection_regex)
    if not parsed or parsed[0] != 'regex':
        return selection_regex

    _, inner, flags = parsed
    if not inner:
        return make_regex_search(inner, flags)

    canonical_inner = _canonicalize_inner(inner)
    return make_regex_search(canonical_inner, flags)


def ensure_all_groups(regex: str | None) -> str | None:
    """Convert a regex to fully-grouped form, preserving postfix flags.

    Every segment (literal and fuzzy) gets wrapped in a capturing group.
    Non-regex inputs pass through unchanged.
    """
    if regex is None or not is_regex_search(regex):
        return regex
    inner = get_regex_inner_pattern(regex)
    if not inner:
        return regex
    flags = get_search_flags(regex)
    grouped = _to_fully_grouped_inner(inner)
    return make_regex_search(grouped, flags)


def _to_fully_grouped_inner(inner_pattern: str) -> str:
    """Convert a (possibly canonical) inner pattern to fully-grouped form.

    Every segment (grouped or ungrouped) is wrapped in a capturing group.
    Ungrouped content is split at fuzzy/literal boundaries so each region
    becomes its own group. Used internally for regex matching.

    Examples:
        'hello.*world'     -> '(hello)(.*)(world)'
        '(hello)(world)'   -> '(hello)(world)'  (already fully grouped)
        'hello'            -> '(hello)'
        '.*(hello)(world)' -> '(.*)(hello)(world)'
    """
    string_segments = parse_top_level_segments(inner_pattern)
    if not string_segments:
        return inner_pattern

    result_parts = []
    for seg in string_segments:
        if seg['is_grouped']:
            result_parts.append(f"({seg['text']})")
        else:
            # Split ungrouped content into sub-segments at fuzzy/literal boundaries
            sub_texts = _split_ungrouped_into_segments(seg['text'])
            for st in sub_texts:
                result_parts.append(f"({st})")

    return ''.join(result_parts) if result_parts else inner_pattern


def _literal_match_highlights(search_text: str, string_value: str,
                              first_match_only: bool, re_flags: int) -> list:
    """Produce highlight tuples by matching a literal string against the value.

    All highlights are display-only (segment_index=None) since non-regex
    searches have no interactive segments.
    """
    escaped = re.escape(search_text)

    try:
        if first_match_only:
            m = re.search(escaped, string_value, flags=re_flags)
            matches = [m] if m else []
        else:
            matches = list(re.finditer(escaped, string_value, flags=re_flags))
    except Exception:
        return []

    if not matches:
        return []

    str_to_internal = build_string_to_internal_mapping(string_value)
    highlights = []

    for match in matches:
        str_start, str_end = match.span()
        if str_start == str_end:
            continue
        internal_start = str_to_internal[str_start] if str_start < len(str_to_internal) else 1
        if str_end > 0 and str_end <= len(str_to_internal):
            internal_end = str_to_internal[str_end - 1] + 1
            if str_end - 1 < len(string_value) and string_value[str_end - 1] == '\n':
                internal_end += 1
        else:
            internal_end = str_to_internal[-1] if str_to_internal else 1
        highlights.append((internal_start, internal_end, 'literal', search_text, (1, 1), None))

    return highlights


def _string_search_highlights(search: str, string_value: str) -> list:
    """Produce highlight tuples for a literal string search."""
    search_text = eval_string_search(search)
    if not search_text:
        return []
    return _literal_match_highlights(
        search_text, string_value,
        is_first_match_mode(search),
        re.I if is_case_insensitive(search) else 0)


# =============================================================================
# Canonical Index/Slice Expression Formatting
# =============================================================================
#
# These helpers produce the most compact / idiomatic Python expression for a
# selection in index mode (cmd-drag or persistent 'index' tool):
#
# - Single char    -> bare index, e.g. '5' or '-1' (negative shorthand)
# - Multi char     -> slice 'start:stop', with start=0 elision (':N'),
#                     stop=n elision ('N:' or ':' for whole string), and
#                     negative-end shorthand (':-1', ':-2', ':-3', or
#                     'start:-k') when k = n - stop is in {1, 2, 3} AND
#                     n > 2*k (so the forward stop is at least k+1, matching
#                     the user-spec "forward would be at least :2 :3 :4
#                     respectively").

def _neg_end_shorthand(stop: int, n: int) -> str | None:
    """Return '-k' shorthand for stop position when applicable, else None."""
    k = n - stop
    if k in (1, 2, 3) and n > 2 * k:
        return f'-{k}'
    return None


def _format_slice_expr(start: int, stop: int, n: int) -> str:
    """Format a slice expression with elision and negative-end shorthand.

    See module-level rules above. Caller is responsible for passing already
    clipped/non-empty bounds (start >= 0, stop > start, stop <= n).
    """
    start_part = '' if start == 0 else str(start)
    if stop == n:
        stop_part = ''
    else:
        stop_part = _neg_end_shorthand(stop, n) or str(stop)
    return f'{start_part}:{stop_part}'


def _format_index_expr(idx: int, n: int) -> str:
    """Format a bare-index expression with negative shorthand for last 1-3 chars."""
    neg = _neg_end_shorthand(idx, n)  # k = n - idx (1=last, 2=2nd-to-last, ...)
    return neg if neg is not None else str(idx)


def _index_highlight(index_val: int, string_value: str, label: str | None = None) -> list:
    """Produce a single highlight tuple for str[index_val].

    The static label rendered at the segment shows *label* if provided
    (matching the user's selection expression, e.g. '5' or '-1'); otherwise
    falls back to str(index_val) so callers passing a raw int still work.
    Returns [] if index is out of bounds.
    """
    n = len(string_value)
    if n == 0:
        return []
    if index_val < -n or index_val >= n:
        return []
    normalized = index_val % n
    str_to_internal = build_string_to_internal_mapping(string_value)
    internal_start = str_to_internal[normalized]
    internal_end = internal_start + 1
    if string_value[normalized] == '\n':
        internal_end += 1
    pat_str = label if label is not None else str(index_val)
    return [(internal_start, internal_end, 'slice', pat_str, (1, 1), None)]


def _slice_search_highlights(search: str, string_value: str, eval_in_scope) -> list:
    """Produce highlight tuples for a slice search expression.

    Evaluates slice bounds in the user's scope and highlights the resulting range.
    Supports broadcast slicing when left/right evaluates to a list of ints.
    """
    parts = parse_slice_parts(search)
    if parts is None:
        return []
    left, right = parts
    try:
        start = eval_in_scope(left) if left else None
        stop = eval_in_scope(right) if right else None
    except Exception:
        return []

    start_is_list = _is_list_of_ints(start)
    stop_is_list = _is_list_of_ints(stop)

    if start_is_list or stop_is_list:
        if not string_value:
            return []
        n = len(string_value)
        str_to_internal = build_string_to_internal_mapping(string_value)
        highlights = []
        if start_is_list and stop_is_list:
            for s, e in zip(start, stop):
                h = _slice_range_highlight(s, e, string_value, str_to_internal, str(s), str(e))
                if h:
                    highlights.append(h)
        elif start_is_list:
            for s in start:
                a_stop = stop if stop is not None else n
                h = _slice_range_highlight(s, a_stop, string_value, str_to_internal, str(s), right)
                if h:
                    highlights.append(h)
        else:
            for e in stop:
                a_start = start if start is not None else 0
                h = _slice_range_highlight(a_start, e, string_value, str_to_internal, left, str(e))
                if h:
                    highlights.append(h)
        return highlights

    if start is not None and not isinstance(start, int):
        return []
    if stop is not None and not isinstance(stop, int):
        return []

    n = len(string_value)
    sliced = string_value[start:stop]
    if not sliced:
        return []

    str_to_internal = build_string_to_internal_mapping(string_value)
    h = _slice_range_highlight(start if start is not None else 0,
                               stop if stop is not None else n,
                               string_value, str_to_internal,
                               left, right)
    return [h] if h is not None else []


def _is_list_of_ints(val) -> bool:
    return isinstance(val, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in val)


def _is_list_of_int_pairs(val) -> bool:
    return (isinstance(val, list)
            and len(val) > 0
            and all(isinstance(x, (tuple, list)) and len(x) == 2
                    and isinstance(x[0], int) and not isinstance(x[0], bool)
                    and isinstance(x[1], int) and not isinstance(x[1], bool)
                    for x in val))


def _slice_range_highlight(actual_start: int, actual_stop: int, string_value: str,
                           str_to_internal: list, left_label: str = '',
                           right_label: str = '') -> tuple | None:
    """Produce a highlight tuple for a string slice.

    *left_label* / *right_label* are the raw expression parts the slice was
    parsed from (e.g. '5', '-1', 'x', or '' for an omitted bound). They are
    rendered at the segment ends, with '-' substituted for empty strings so
    the user can see which side of the slice was elided.
    """
    n = len(string_value)
    if actual_start < 0:
        actual_start = max(actual_start + n, 0)
    if actual_stop < 0:
        actual_stop = max(actual_stop + n, 0)
    actual_stop = min(actual_stop, n)
    actual_start = min(actual_start, n)
    if actual_start >= actual_stop:
        return None
    internal_start = str_to_internal[actual_start]
    if actual_stop > 0 and actual_stop <= len(str_to_internal):
        internal_end = str_to_internal[actual_stop - 1] + 1
        if actual_stop - 1 < n and string_value[actual_stop - 1] == '\n':
            internal_end += 1
    else:
        internal_end = str_to_internal[-1] if str_to_internal else 1
    # seg_type='slice' triggers static index-label rendering. pat_str packs
    # the labels as 'left|right'; '·' (middle dot) marks an elided bound,
    # visually distinct from a negative-int label like '-1'.
    # segment_index=0 (rather than None) makes the slice interactive so the
    # visualizer renders left/right resize handles. There's only ever one
    # slice segment, so 0 is always correct.
    left = left_label or '·'
    right = right_label or '·'
    pat_str = f'{left}|{right}'
    return (internal_start, internal_end, 'slice', pat_str, (1, 1), 0)


def _expression_search_highlights(search: str, string_value: str, eval_in_scope) -> list:
    """Produce highlight tuples for a backtick or bare expression search.

    Uses eval_in_scope to evaluate in the user's code scope.
    If the expression evaluates to an int, treats it as an index search (str[N]).
    If it evaluates to a list of ints, highlights each indexed character.
    If it evaluates to a list of (int,int) pairs, highlights each slice range.
    Returns no highlights if eval fails.
    """
    p = parse_search_term(search)
    if not p or p[0] != 'expr':
        return []
    try:
        result = eval_in_scope(p[1])
    except Exception:
        return []
    if isinstance(result, int) and not isinstance(result, bool):
        # Single bare-index: label is the user's raw expression (e.g. '-1'),
        # not the resolved positive position.
        return _index_highlight(result, string_value, label=p[1])
    if _is_list_of_ints(result):
        highlights = []
        for idx in result:
            highlights.extend(_index_highlight(idx, string_value))
        return highlights
    if _is_list_of_int_pairs(result):
        if not string_value:
            return []
        str_to_internal = build_string_to_internal_mapping(string_value)
        highlights = []
        for s, e in result:
            n = len(string_value)
            a_start = s if s >= 0 else max(s + n, 0)
            a_stop = e if e >= 0 else max(e + n, 0)
            h = _slice_range_highlight(a_start, a_stop, string_value, str_to_internal, str(s), str(e))
            if h:
                highlights.append(h)
        return highlights
    if not isinstance(result, str):
        return []
    if not result:
        return []
    return _literal_match_highlights(
        result, string_value,
        is_first_match_mode(search),
        re.I if is_case_insensitive(search) else 0)


def parse_regex_for_highlighting(selection_regex: str | None, string_value: str, eval_in_scope=lambda _c: eval(_c)) -> List[Tuple[int, int, str, str, Tuple[int, int | float]]]:
    """
    Parse the search and run it against the ORIGINAL string to get highlight ranges.

    Supports regex (r'pattern'), string literals ('string'), backtick
    expressions (`expr`), and bare expressions.

    Returns:
        List of (internal_start, internal_end, type, pattern_display, repetition, segment_index) tuples.
    """
    parsed = parse_search_term(selection_regex)
    if not parsed:
        return []
    kind = parsed[0]

    if kind == 'string':
        return _string_search_highlights(selection_regex, string_value)

    if kind == 'slice':
        return _slice_search_highlights(selection_regex, string_value, eval_in_scope)

    if kind == 'expr':
        return _expression_search_highlights(selection_regex, string_value, eval_in_scope)

    inner_pattern = parsed[1]
    if not inner_pattern:
        return []

    # Convert to fully-grouped form so every segment is a capturing group.
    # This handles canonical regex where some segments may be ungrouped.
    grouped_pattern = _to_fully_grouped_inner(inner_pattern)

    # Parse the fully-grouped regex to understand its structure
    try:
        parsed = regex_parser.parse(grouped_pattern)
    except Exception:
        return []

    # Analyze each capturing group for anchors, fuzzy status, repetition, and pattern display
    group_info = []  # List of (anchors, is_fuzzy, repetition, pattern_display) per group
    for item in parsed:
        op = item[0]
        av = item[1] if len(item) > 1 else None
        op_name = str(op)
        if op_name == 'SUBPATTERN':
            group_id, add_flags, del_flags, subpattern = av
            anchors, is_fuzzy, repetition, pattern_display = _analyze_group(subpattern)
            group_info.append((anchors, is_fuzzy, repetition, pattern_display))

    first_match_only = is_first_match_mode(selection_regex)
    re_flags = re.M | (re.I if is_case_insensitive(selection_regex) else 0)

    # Run the fully-grouped regex against the ORIGINAL string (not augmented!)
    # re.M makes ^ and $ match at line boundaries
    try:
        if first_match_only:
            matches = []
            m = re.search(grouped_pattern, string_value, flags=re_flags)
            if m:
                matches = [m]
        else:
            matches = list(re.finditer(grouped_pattern, string_value, flags=re_flags))
    except Exception:
        return []

    if not matches:
        return []

    # Build the string-to-internal mapping for position translation
    str_to_internal = build_string_to_internal_mapping(string_value)

    highlights = []

    for match_idx, match in enumerate(matches):
        # First match gets real segment indices (for interactive widgets);
        # additional matches get None (highlight-only, no dropdowns/handles)
        is_primary = (match_idx == 0)

        num_groups = match.lastindex or 0

        for group_num in range(1, num_groups + 1):
            span = match.span(group_num)
            if span == (-1, -1):
                continue  # Group didn't participate in match

            str_start, str_end = span
            group_idx = group_num - 1
            anchors, is_fuzzy, repetition, pattern_display = group_info[group_idx] if group_idx < len(group_info) else ([], False, (1, 1), '')
            seg_type = 'fuzzy' if is_fuzzy else 'literal'

            if is_primary:
                segment_index = len(highlights)
            else:
                segment_index = None

            # Translate string positions to internal indices
            # Handle edge case: empty match (e.g., anchor-only groups or .* matching nothing)
            if str_start == str_end:
                # Zero-width match - we're at a gap/boundary position
                # For fuzzy (.*) matching empty, this is typically at an anchor position like $
                if str_start < len(str_to_internal):
                    internal_pos = str_to_internal[str_start]
                else:
                    internal_pos = str_to_internal[-1] if str_to_internal else 1

                # For zero-width matches, we're at the boundary BEFORE the character
                # This corresponds to anchor positions:
                # - Before a newline: the $ anchor (internal_pos - 1 for \n)
                # - At string start: the visible ^ anchor
                # - At string end: the $ anchor
                if str_start < len(string_value) and string_value[str_start] == '\n':
                    # We're at the boundary before a newline - that's the $ position
                    internal_start = internal_pos - 1  # $ is one before \n
                elif str_start == len(string_value):
                    # We're at the end of string - that's the $ position
                    internal_start = internal_pos
                elif str_start == 0:
                    # At the very start - the visible ^ is at position 0
                    internal_start = internal_pos
                else:
                    # General case: position right after previous char
                    internal_start = internal_pos

                internal_end = internal_start

                # Expand based on which anchors are present
                if 'AT_BEGINNING_STRING' in anchors:
                    internal_start = 0
                if 'AT_BEGINNING' in anchors:
                    if str_start == 0:
                        internal_start = 0
                if 'AT_END' in anchors:
                    internal_end = max(internal_end, internal_start + 1)
                if 'AT_END_STRING' in anchors:
                    internal_end = compute_internal_length(string_value)

                if internal_end <= internal_start:
                    internal_end = internal_start + 1
                highlights.append((internal_start, internal_end, seg_type, pattern_display, repetition, segment_index))
            else:
                # Normal match with content
                internal_start = str_to_internal[str_start] if str_start < len(str_to_internal) else 1
                # For end, we need the position AFTER the last matched character
                if str_end > 0 and str_end <= len(str_to_internal):
                    internal_end = str_to_internal[str_end - 1] + 1
                    # Adjust for newlines: if last char is \n, end should be after the ^ marker
                    if str_end > 0 and str_end - 1 < len(string_value) and string_value[str_end - 1] == '\n':
                        # \n maps to middle of 3 indices ($, \n, ^), so add 1 more to include ^
                        internal_end += 1
                else:
                    internal_end = str_to_internal[-1] if str_to_internal else 1

                # Extend for leading anchors
                if 'AT_BEGINNING_STRING' in anchors:
                    internal_start = 0
                if 'AT_BEGINNING' in anchors and str_start == 0:
                    internal_start = 0

                # Extend for trailing anchors
                if 'AT_END_STRING' in anchors:
                    internal_end = compute_internal_length(string_value)
                if 'AT_END' in anchors:
                    # $ anchor - extend to include the $ marker
                    # For end of string, $ is at augmented_len - 1
                    # For end of line, $ is right before the \n
                    pass  # The current end should already be correct

                highlights.append((internal_start, internal_end, seg_type, pattern_display, repetition, segment_index))

    return highlights


def get_last_segment_end_internal_idx(selection_regex: str | None, string_value: str) -> int | None:
    """
    Get the internal index where the last segment ends.

    Used to determine if a new selection is extending from the previous one.
    Only considers primary match segments (segment_index is not None).
    """
    highlights = parse_regex_for_highlighting(selection_regex, string_value)
    primary = [h for h in highlights if h[5] is not None]
    if not primary:
        return None
    last_start, last_end, _, _, _, _ = primary[-1]
    return last_end


def get_first_segment_start_internal_idx(selection_regex: str | None, string_value: str) -> int | None:
    """
    Get the internal index where the first segment starts.

    Used to determine if a new selection is extending from the left side.
    Only considers primary match segments (segment_index is not None).
    """
    highlights = parse_regex_for_highlighting(selection_regex, string_value)
    primary = [h for h in highlights if h[5] is not None]
    if not primary:
        return None
    first_start, first_end, _, _, _, _ = primary[0]
    return first_start


def find_fuzzy_segment_at_index(selection_regex: str | None, string_value: str, idx: int) -> dict | None:
    """
    Find a fuzzy segment that contains the given internal index.

    Returns dict with 'start', 'end', 'segment_index' if found, None otherwise.
    Used to detect clicks inside realized fuzzy regions.
    Only considers primary match segments (segment_index is not None).
    """
    highlights = parse_regex_for_highlighting(selection_regex, string_value)
    for i, (start, end, seg_type, _, _, seg_idx) in enumerate(highlights):
        if seg_idx is not None and seg_type == 'fuzzy' and start <= idx < end:
            return {'start': start, 'end': end, 'segment_index': seg_idx}
    return None


# === Adjacency helpers for selection extension ===

def is_adjacent_right(idx: int, last_end: int, string_value: str) -> bool:
    """
    Check if idx is adjacent to last_end for right-extension purposes.

    Returns True if idx >= last_end and all characters at internal indices
    in [last_end, idx) are anchor/sentinel characters (which can be skipped).

    This handles cases like:
    - Extending past $ to reach \\n (at end of line)
    - Extending past ^ to reach the first char of the next line

    Anchor characters (^ and $) are zero-width regex positions that
    appear as visual markers in the UI. They don't represent actual string
    content, so it's natural to allow clicking "through" them to reach the
    next real character.
    """
    if idx < last_end:
        return False
    if idx == last_end:
        return True
    # Don't consider out-of-bounds indices as adjacent
    if idx >= compute_internal_length(string_value):
        return False
    # Check if all characters between last_end and idx are anchors
    skipped = extract_by_internal_indices(string_value, last_end, idx)
    return len(skipped) > 0 and all(c in _SENTINEL_CHARS for c in skipped)


def is_adjacent_left(idx: int, first_start: int, string_value: str) -> bool:
    """
    Check if idx is adjacent to first_start for left-extension purposes.

    Returns True if idx < first_start and all characters at internal indices
    in (idx, first_start) are anchor/sentinel characters (which can be skipped).

    This handles cases like:
    - Extending past ^ to reach \\n (going left from start of next line)
    - Extending past ^ to reach the first char at the start of string
    - Extending past $ to reach the last char of the previous line
    """
    if idx >= first_start:
        return False
    if idx == first_start - 1:
        return True
    # Don't consider out-of-bounds indices as adjacent
    if idx < 0:
        return False
    # Check if all characters between idx+1 and first_start are anchors
    skipped = extract_by_internal_indices(string_value, idx + 1, first_start)
    return len(skipped) > 0 and all(c in _SENTINEL_CHARS for c in skipped)



def strip_capturing_groups(pattern: str) -> str:
    """
    Strip any remaining capturing groups from a pattern, leaving just the inner content.

    For example: "hello(.*)world" -> "hello.*world"
                 "(hello)(world)" -> "helloworld"

    Used when generating re.search() code, where groups are not needed.
    """
    result = []
    i = 0
    while i < len(pattern):
        if pattern[i] == '(':
            # Skip the opening paren
            i += 1
        elif pattern[i] == ')':
            # Skip the closing paren
            i += 1
        elif pattern[i] == '\\' and i + 1 < len(pattern):
            # Escaped character - keep both
            result.append(pattern[i:i+2])
            i += 2
        else:
            result.append(pattern[i])
            i += 1
    return ''.join(result)




def vis_char_with_index_els(char, i, highlight_by_index, model=None, scroll_to=False) -> Tuple[List[str], int]:
    if char == '\n':
        return ([
            *char_span_els('$', i, True, highlight_by_index.get(i), model, scroll_to, is_regex_anchor=True),
            *char_span_els('\\n', i+1, True, highlight_by_index.get(i+1), model),
            '\n',
            *char_span_els('^', i+2, True, highlight_by_index.get(i+2), model, is_regex_anchor=True)
        ], i + 3)
    elif char == '\t':
        return (char_span_els('\\t', i, True, highlight_by_index.get(i), model, scroll_to), i + 1)

    return (char_span_els(char, i, False, highlight_by_index.get(i), model, scroll_to), i + 1)

def vis_char_with_index(char, i, highlight_by_index, model=None):
    """Visualize a character with optional highlighting.

    Args:
        highlight_by_index: dict mapping index -> highlight tuple or None
            where highlight tuple is (start, end, type, pattern_display, repetition, segment_index)
        model: The model state (needed for dropdown open state)
    """
    if char == '\n':
        return (char_span('$', i, True, highlight_by_index.get(i), model, is_regex_anchor=True) + (char_span('\\n', i+1, True, highlight_by_index.get(i+1), model) + '\n  ' + char_span('^', i+2, True, highlight_by_index.get(i+2), model, is_regex_anchor=True)), i + 3)
    elif char == '\t':
        return (char_span('\\t', i, True, highlight_by_index.get(i), model), i + 1)

    return (char_span(char, i, False, highlight_by_index.get(i), model), i + 1)


def _compute_handle_drag_regex(model: dict, string_value: str) -> str | None:
    """
    Compute the regex during an active handle drag, resizing the target literal segment.

    Uses the handleDrag state (segmentIndex, side, cursorIdx) plus the current
    search and string_value to determine the new segment boundaries.

    Args:
        model: The model state (must have handleDrag set)
        string_value: The string being visualized

    Returns:
        The preview regex with the segment resized, or the current search on error.
    """
    handle_drag = model['handleDrag']
    segment_index = handle_drag['segmentIndex']
    side = handle_drag['side']
    cursor_idx = handle_drag['cursorIdx']
    selection_regex = model.get('search')

    if selection_regex is None:
        return None

    # Get current highlights to find segment boundaries. Use a callable for
    # eval_in_scope so slice/index expressions resolve correctly.
    highlights = parse_regex_for_highlighting(selection_regex, string_value, eval_in_scope=lambda c: eval(c))
    if segment_index >= len(highlights):
        return selection_regex

    current_start, current_end, seg_type, _, _, _ = highlights[segment_index]

    if side == 'right':
        new_start = current_start
        new_end = max(cursor_idx + 1, current_start + 1)  # At least 1 char
    else:  # left
        new_start = min(cursor_idx, current_end - 1)  # At least 1 char
        new_end = current_end

    if seg_type == 'slice':
        # Translate internal indices to string positions and reformat as a
        # canonical slice expression (re-applying elision and -k shorthand).
        mapping = build_internal_to_string_mapping(string_value)
        n = len(string_value)
        if not mapping:
            return selection_regex
        string_start = mapping[new_start] if new_start < len(mapping) else n
        string_end = mapping[new_end] if new_end < len(mapping) else n
        if string_start >= string_end:
            return selection_regex
        return _format_slice_expr(string_start, string_end, n)

    if seg_type == 'fuzzy':
        # Re-run fuzzy inference over the new range (keep the segment fuzzy).
        # Boundary context depends on whether each edge abuts a neighbor
        # segment: a neighbor anchors that side (None -> *), otherwise use the
        # adjacent string character (or '' at the string boundary).
        primary_count = sum(1 for h in highlights if h[5] is not None)
        has_left_neighbor = segment_index > 0
        has_right_neighbor = segment_index < primary_count - 1

        if has_left_neighbor:
            prev_char: str | None = None
        else:
            prev_text = extract_by_internal_indices(string_value, new_start - 1, new_start) if new_start > 0 else ''
            prev_char = ''.join(c for c in prev_text if c not in _SENTINEL_CHARS)

        if has_right_neighbor:
            next_char: str | None = None
        else:
            next_text = extract_by_internal_indices(string_value, new_end, new_end + 1)
            next_char = ''.join(c for c in next_text if c not in _SENTINEL_CHARS)

        return resize_fuzzy_segment(selection_regex, segment_index, string_value,
                                    new_start, new_end, prev_char, next_char)

    return resize_literal_segment(selection_regex, segment_index, string_value, new_start, new_end)


def build_preview_regex(model, string_value: str) -> str | None:
    """
    Build what the regex would look like if we finalized the in-progress selection.

    This mirrors the logic in finalize_segment() but doesn't modify the model.

    Args:
        model: The model state
        string_value: The string being visualized

    Returns:
        The preview regex string, or the current search if no in-progress selection
    """
    # Check for handle drag state first
    handle_drag = model.get('handleDrag')
    if handle_drag is not None:
        cursor_idx = handle_drag.get('cursorIdx')
        if cursor_idx is not None:
            return _compute_handle_drag_regex(model, string_value)

    a = model.get('anchorIdx')
    c = model.get('cursorIdx')

    if not (isinstance(a, int) and isinstance(c, int)):
        # No in-progress selection, return existing regex
        return model.get('search')

    anchor_type = model.get('anchorType', 'literal')
    extend_direction = model.get('extendDirection')
    insert_after_segment = model.get('insertAfterSegment')
    current_regex = model.get('search')

    start = min(a, c)
    # For left-extension, end should NOT include +1 to avoid overlapping
    if extend_direction == 'left':
        end = max(a, c)
    else:
        end = max(a, c) + 1

    if anchor_type == 'index':
        # Convert internal indices -> string positions, then emit either a bare
        # index expression (for a single-char selection) or a slice. The existing
        # index/slice machinery then takes over for highlighting and codegen.
        mapping = build_internal_to_string_mapping(string_value)
        n = len(string_value)
        if not mapping:
            return None
        string_start = mapping[start] if start < len(mapping) else n
        string_end = mapping[end] if end < len(mapping) else n
        if string_start >= string_end:
            return None
        # Single-char selection: anchor and cursor on the same character.
        if a == c:
            return _format_index_expr(string_start, n)
        return _format_slice_expr(string_start, string_end, n)

    if anchor_type == 'fuzzy':
        # Synthesize a fuzzy pattern from the dragged text
        selected_text = extract_by_internal_indices(string_value, start, end)
        actual_text = ''.join(c for c in selected_text if c not in _SENTINEL_CHARS)

        # Determine boundary context:
        # - Fresh selection (no existing regex): pass actual prev/next chars
        #   so synthesize_fuzzy_pattern uses + (one or more).
        # - Adjacent to existing literal: pass None for that side so it uses *
        #   (zero or more), since the literal already anchors the match.
        is_fresh = (current_regex is None or _is_flags_only(current_regex)) and extend_direction is None and insert_after_segment is None

        if is_fresh:
            # New selection: check both edges
            prev_text = extract_by_internal_indices(string_value, start - 1, start) if start > 0 else ''
            prev_char = ''.join(c for c in prev_text if c not in _SENTINEL_CHARS)
            next_text = extract_by_internal_indices(string_value, end, end + 1)
            next_char = ''.join(c for c in next_text if c not in _SENTINEL_CHARS)
        elif extend_direction == 'left':
            # Prepending to existing regex: literal on the right
            prev_text = extract_by_internal_indices(string_value, start - 1, start) if start > 0 else ''
            prev_char = ''.join(c for c in prev_text if c not in _SENTINEL_CHARS)
            next_char = None
        elif extend_direction == 'right':
            # Appending to existing regex: literal on the left
            prev_char = None
            next_text = extract_by_internal_indices(string_value, end, end + 1)
            next_char = ''.join(c for c in next_text if c not in _SENTINEL_CHARS)
        elif insert_after_segment is not None:
            # Inserting between existing segments: literals on both sides
            prev_char = None
            next_char = None
        else:
            # Fallback: treat as adjacent
            prev_char = None
            next_text = extract_by_internal_indices(string_value, end, end + 1)
            next_char = ''.join(c for c in next_text if c not in _SENTINEL_CHARS)

        fuzzy_pattern = synthesize_fuzzy_pattern(actual_text, prev_char, next_char)
        if extend_direction == 'left':
            return prepend_segment_to_regex(current_regex, 'fuzzy', fuzzy_pattern)
        elif insert_after_segment is not None:
            if insert_after_segment == 0:
                insert_position = 0
            else:
                insert_position = insert_after_segment + 1
            return insert_segment_at_position(current_regex, insert_position, 'fuzzy', fuzzy_pattern)
        else:
            return append_segment_to_regex(current_regex, 'fuzzy', fuzzy_pattern)
    else:
        # Literal: need actual text from the selection
        selected_text = extract_by_internal_indices(string_value, start, end)
        if extend_direction == 'left':
            return prepend_segment_to_regex(current_regex, 'literal', selected_text)
        elif insert_after_segment is not None:
            if insert_after_segment == 0:
                insert_position = 0
            else:
                insert_position = insert_after_segment + 1
            return insert_segment_at_position(current_regex, insert_position, 'literal', selected_text)
        else:
            return append_segment_to_regex(current_regex, 'literal', selected_text)

def _readings(expr: str, also=()):
    """What a control hands over: its own answer, and the other ways it reads.

    One expression on its own needs no name -- there is nothing to tell it
    apart from. Several are named (One / List), so a tooltip can say which of
    them is this string's answer and which is the whole column's. Each carries
    what its own text needs imported, whoever wrote it.
    """
    primary = PyExp(expr, code_imports(expr))
    if not also:
        return primary
    return label_readings(primary, [
        (e if isinstance(e, PyExp) else PyExp(e))._replace(
            imports=code_imports(e.expr if isinstance(e, PyExp) else e))
        for e in also])


def _action_btn(label: str, action: str, enabled: bool = True,
                expr: str = '', linked: bool = False, also=()) -> str:
    event = repr(ActionButtonClick(action=action, copy=False))
    cls = 'action-button'
    if not enabled:
        cls += ' dimmed'
    if linked:
        cls += ' linked'
    expr_attr = py_exp_attrs(_readings(expr, also), draggable=False,
                             attr='data-action-expr')
    return (f'<span snc-mouse-down="{html.escape(event)}" class="{cls}"'
            f'{expr_attr}>{label}</span>')

def _preview_expr(model: dict, action: str, eval_in_scope, source_expr=None) -> str:
    """Pre-compute the expression that an action button would generate.

    *source_expr* overrides what the value is called. Passing `$` yields the
    action as a COLUMN expression -- what it would say of any row rather than
    of this one -- which is what a table above lifts to a comprehension (see
    _every_row_action_exps).
    """
    source_expr = source_expr or model.get('_source_expr')
    if not source_expr:
        return ''
    ctx = _get_search_context(model, source_expr=source_expr, eval_in_scope=eval_in_scope)
    if not ctx:
        return ''
    try:
        from string_visualizer_grammar import generate_action as _gen
        result = _gen(action, ctx)
        # The preview is copied and dragged into the file as-is, so a statement
        # needs the body that generation leaves off.
        return with_pass_body(result[1]) if result else ''
    except Exception:
        return ''


def _menu_row(label: str, event: str, enabled: bool, expr: str = '',
              also=()) -> str:
    """One row of a menu: what it says, what it sends, and what it writes.

    The row is the handle for its own code, offered rightwards so a tooltip
    doesn't cover the rows around it. A row is a button like the ones beside it
    -- in a table's cell what it writes becomes a column -- so it offers the
    same readings a button does (see _readings).
    """
    disabled = '' if enabled else ' dimmed'
    exp_attrs = py_exp_attrs(_readings(expr, also), draggable=False,
                             align='right')
    return (
        f'<div class="snc-dropdown-option{disabled}"{exp_attrs}>'
        f'<span snc-mouse-down="{html.escape(event)}" class="snc-dropdown-option-label">{label}</span>'
        f'</div>'
    )


def _dropdown_row(label: str, action: str, enabled: bool, expr: str = '',
                  also=()) -> str:
    return _menu_row(label, repr(ActionButtonClick(action=action, copy=False)),
                     enabled, expr, also)


def _every_row_action_exps(model: dict, action: str, eval_in_scope,
                           every_row_exps) -> list:
    """What this action says of EVERY row, when the string is a table's cell.

    Clicking already generalizes -- the code goes up as a column, one
    expression each row answers. Only the preview named one row, so the button
    offered `re.split(r',', parts[0], ...)` while the column it was about to
    write said `re.split(r',', $, ...)`. The action generated against `$` IS
    that column, so the table lifts it the same way it lifts an access path.

    Nothing for an action that writes a STATEMENT: `if any(...)` is a line and
    only ever a line, and a column holds an expression. Read down a list it
    would say nothing -- so it says nothing.
    """
    if every_row_exps is None:
        return []
    column = _preview_expr(model, action, eval_in_scope, source_expr='$')
    if not column or not dollar_expr_parses(column):
        return []
    return list(every_row_exps(column))


# What the Fetch menu offers and the read each row writes. A string that names
# a place -- a URL, a path -- is one `urlopen` or one `open` away from the value
# it stands for, and these are the reads pythonDropProvider.ts already writes
# when a URL or a file is dragged into the editor. Same reads, offered after the
# fact for a string the program has already got hold of.
#
# Each menu is (source, its row's label, its formats); each format is (fmt, its
# row's label, what to call the answer, how the read reads).
FETCH_MENUS = (
    ('url', 'Fetch URL', (
        ('text', 'as string', 'text',
         lambda src: f'urllib.request.urlopen({src}).read().decode()'),
        # json.load takes the response itself: a decode the reader would only
        # have to undo is a step to leave out.
        ('json', 'as JSON', 'data',
         lambda src: f'json.load(urllib.request.urlopen({src}))'),
    )),
    ('file', 'Read Filepath', (
        ('text', 'as string', 'text', lambda src: f'open({src}).read()'),
        ('csv', 'as CSV', 'rows',
         lambda src: f"list(csv.reader(open({src}, newline='')))"),
        ('json', 'as JSON', 'data', lambda src: f'json.load(open({src}))'),
        # Every sheet, because which one holds the data isn't ours to guess.
        ('excel', 'as Excel', 'sheets',
         lambda src: (f'{{sheet_name: pd.read_excel({src}, sheet_name=sheet_name)'
                      f".to_dict('records') for sheet_name in "
                      f'pd.ExcelFile({src}).sheet_names}}')),
    )),
)

# The schemes worth offering to fetch. The runner caches what `urlopen` reads
# (see url_cache.py), and only these are cached -- a rerun on every keystroke
# refetching is what makes a URL worth writing as a URL at all.
_FETCH_URL_SCHEMES = ('http://', 'https://')


def _names_a_url(value: str) -> bool:
    """Whether the string names something to read over the network."""
    text = (value or '').strip()
    return (text.lower().startswith(_FETCH_URL_SCHEMES)
            and not any(char.isspace() for char in text))


def _names_a_file(value: str) -> bool:
    """Whether the string names a file that is there.

    Asked of the filesystem rather than of the text, and in the user's own
    process with their own working directory, so the answer is the one `open()`
    would give a moment later. A string too long or too strange to be a path is
    not one, and the OS says so by raising -- which is the same no.
    """
    text = value or ''
    if not text or '\n' in text or _names_a_url(text):
        return False
    try:
        return os.path.isfile(text)
    except (OSError, ValueError):
        return False


def _fetch_format(source: str, fmt: str):
    """The FETCH_MENUS row a FetchClick names, or None if it names none."""
    for menu_source, _, formats in FETCH_MENUS:
        if menu_source == source:
            for row in formats:
                if row[0] == fmt:
                    return row
    return None


def _fetch_code(source_expr: str, source: str, fmt: str):
    """The line a Fetch row writes: (what to call it, the read itself).

    The name follows the same rule the generated actions use -- the source's
    own name and what the read makes of it, or a `result` where the string has
    no name to lend. A cell's binder is a name the parent substitutes into
    rather than one the user wrote, so it lends none either.
    """
    row = _fetch_format(source, fmt)
    if not row or not source_expr:
        return None
    _, _, suffix, read = row
    has_var = (source_expr != CHILD_SOURCE_BINDER and source_expr.isidentifier()
               and not keyword.iskeyword(source_expr))
    return (f'{source_expr if has_var else "result"}_{suffix}', read(source_expr))


def _fetch_row_exps(source: str, fmt: str, every_row_exps) -> list:
    """What a Fetch row's read says of EVERY row, when the string is a cell.

    Clicked in a cell the read becomes a column -- `open($).read()`, one answer
    each row has -- so the row offers that reading beside this string's own,
    exactly as an action button does (see _every_row_action_exps). Written
    against `$` here rather than the binder the click uses: the two spellings
    are the same question asked of the two things that answer it, a table's
    column and a parent's substitution.
    """
    row = _fetch_format(source, fmt)
    if every_row_exps is None or not row:
        return []
    return list(every_row_exps(row[3]('$')))


def _fetch_source_expr(model: dict, var_and_exp=None) -> str | None:
    """How the code names the string being read."""
    if var_and_exp:
        var_name, expr = var_and_exp
        return var_name if var_name else expr
    return model.get('_source_expr')


def _render_fetch_button(model: dict, value: str, every_row_exps=None) -> str:
    """The Fetch button: read the string as the place it names.

    Two rows, each with a submenu of the ways its bytes read. Alone in this bar
    the button asks nothing of the search -- what it acts on is the string
    itself -- so it is live where every other button is dimmed, and dim where
    the string names nowhere to read from.

    Which rows are live is read off the value: a URL by how it starts, a path by
    the file being there. The submenus open on hover in CSS alone, since a hover
    menu is a static clone the front end positions (see showHoverMenu in snc.ts)
    and nothing walks into one looking for further triggers.
    """
    source_expr = _fetch_source_expr(model)
    live = {'url': _names_a_url(value), 'file': _names_a_file(value)}

    rows = []
    for source, label, formats in FETCH_MENUS:
        enabled = bool(source_expr) and live[source]
        format_rows = []
        for fmt, fmt_label, _, _ in formats:
            code = _fetch_code(source_expr, source, fmt) if enabled else None
            format_rows.append(_menu_row(
                html.escape(fmt_label), repr(FetchClick(source=source, fmt=fmt)),
                enabled, code[1] if code else '',
                also=_fetch_row_exps(source, fmt, every_row_exps) if code else ()))
        rows.append(
            f'<div class="snc-dropdown-trigger fetch-submenu'
            f'{"" if enabled else " dimmed"}">'
            f'<div class="snc-dropdown-option">'
            f'<span class="snc-dropdown-option-label">{html.escape(label)}</span>'
            f'<span class="submenu-right-arrow">▸</span>'
            f'</div>'
            f'<div class="snc-dropdown-panel flyout fetch-format-panel"'
            f' snc-dropdown-align="flyout" data-hover-menu>'
            f'{"".join(format_rows)}</div>'
            f'</div>')

    panel = (
        f'<div class="snc-dropdown-panel left fetch-menu-panel has-submenu"'
        f' snc-dropdown-align="left" data-hover-menu>{"".join(rows)}</div>'
    )
    enabled = bool(source_expr) and any(live.values())
    return (
        f'<span class="snc-dropdown-trigger{"" if enabled else " dimmed"}">'
        f'<span class="action-button"><span class="text">Fetch</span></span>'
        f'{panel}</span>'
    )


def _render_action_buttons(model: dict, value: str, eval_in_scope, max_width=None,
                           every_row_exps=None) -> str:
    """Render the action button bar below the search/replace boxes."""
    selection_regex = model.get('search')
    has_search = selection_regex is not None and selection_regex != ''
    replace_visible = bool(model.get('replace_visible', False))
    replace_text = bool(model.get('replace_text'))
    has_replace = replace_visible and replace_text
    linked_action = model.get('linked_action')
    match_count = _eval_count_via_grammar(selection_regex, value, model, eval_in_scope) if has_search else 0
    first = is_first_match_mode(selection_regex) if has_search else False

    def expr(action):
        return _preview_expr(model, action, eval_in_scope)

    def also(action):
        return _every_row_action_exps(model, action, eval_in_scope, every_row_exps)

    def btn(label, action, enabled=True):
        return _action_btn(label, action, enabled,
                           expr(action) if enabled else '',
                           linked=linked_action == action,
                           also=also(action) if enabled else ())

    # these are nerd font glyphs, embedded in the bundled Pragmasevka font
    #   ┆ ┊   

    parts = []

    parts.append(_action_btn(f'<span class="text">Count: {match_count}</span>', 'count', has_search,
                             expr('count') if has_search else '',
                             also=also('count') if has_search else ()))
    # parts.append('<div class="action-button-divider"></div>')

    find_or_map_label = 'Map Matches' if replace_visible else 'Match Objects'
    parts.append(btn(f'''<span class="text">{find_or_map_label}</span>''', 'find_or_map', has_search))

    parts.append(btn(f'<span class="text">Substrs</span>', 'match_strings', has_search and not has_replace))

    parts.append(btn(f'<span class="text">Indexes</span>', 'find_indices', has_search))

    # Loop dropdown (shown on hover via CSS)
    loop_enabled = has_search and not first
    # 'Over matched strings' generates `for s in re.findall(...)` which ignores
    # the replace_expr, so it doesn't make sense alongside a replace/map/filter
    # predicate (mirrors the same restriction on the top-level Substrs button).
    loop_match_strings_enabled = loop_enabled and not has_replace

    def loop_row(label, action, enabled):
        return _dropdown_row(label, action, enabled,
                             expr(action) if enabled else '',
                             also=also(action) if enabled else ())

    # The 'loop' action loops over `val` (transformed) when has_replace, else over
    # `mtch` (match objects). Mirror the find_or_map button's label switch
    # (Match Objects <-> Map Matches) on replace_visible so opening the replace box
    # gives immediate UI feedback.
    over_match_label = 'Over mapped' if replace_visible else 'Over match objects'
    loop_panel = (
        '<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
        f'{loop_row("Over matched strings", "loop_match_strings", loop_match_strings_enabled)}'
        f'{loop_row(over_match_label, "loop", loop_enabled)}'
        f'</div>'
    )
    loop_btn = (
        f'<span class="snc-dropdown-trigger {"" if loop_enabled else "dimmed"}">'
        f'<span class="action-button">{ICONS['loop']}<span class="text">Loop</span></span>'
        f'{loop_panel}</span>'
    )
    parts.append(loop_btn)

    # Predicate dropdown (Any/If Any/All/If All)
    any_val, all_val = _compute_predicate_previews(
        selection_regex, value, replace_visible, model.get('replace_text'), match_count, eval_in_scope
    ) if has_search else (None, None)
    # Wrap the True/False value in a snc-code span so the label text stays in
    # the surrounding UI font but the boolean value renders in code font.
    def _predicate_suffix(val):
        if val is None:
            return ''
        return f' (<span class="snc-code">{html.escape(str(val))}</span>)'
    any_suffix = _predicate_suffix(any_val)
    all_suffix = _predicate_suffix(all_val)

    all_enabled = has_search and has_replace and not first

    def predicate_row(label, action, enabled):
        return _dropdown_row(label, action, enabled,
                             expr(action) if enabled else '',
                             also=also(action) if enabled else ())

    predicate_panel = (
        '<div class="snc-dropdown-panel left" snc-dropdown-align="left" data-hover-menu>'
        f'{predicate_row(f"Any{any_suffix}", "any", has_search)}'
        f'{predicate_row(f"If Any{any_suffix}", "if_any", has_search)}'
        f'{predicate_row(f"All{all_suffix}", "all", all_enabled)}'
        f'{predicate_row(f"If All{all_suffix}", "if_all", all_enabled)}'
        f'</div>'
    )
    predicate_btn = (
        f'<span class="snc-dropdown-trigger {"" if has_search else "dimmed"}">'
        f'<span class="action-button">{ICONS["exists"]}<span class="text">Any/All</span></span>'
        f'{predicate_panel}</span>'
    )
    parts.append(predicate_btn)

    # Delete is disabled in Pick mode (user is composing an extraction
    # expression via segment chips) and when the Replace box is open
    # (user is composing a replacement). Firing Delete in either state
    # would discard the in-progress work.
    delete_enabled = has_search and model.get('tool') != 'pick' and not replace_visible
    parts.append(btn(f'{ICONS["bin"]}<span class="text">Delete<span class="shortcut">⌘⌫</span></span>', 'delete', delete_enabled))
    # parts.append(btn('a┆b', 'split', has_search, 'Split string at matches'))
    # parts.append(btn('>┆<', 'split', has_search, 'Split string at matches'))
    parts.append(btn('<span style="font-family:Pragmasevka;margin-right:-1px;padding:0 1px;font-size:8px;border: 1px solid #4e4e4e;border-radius:1px 0 0 1px;border-width:1px 0 1px 1px;">a</span><span style="font-family:Pragmasevka;">┆</span><span style="font-family:Pragmasevka;margin-left:-1px;padding:0 1px;font-size:8px;border: 1px solid #4e4e4e;border-radius:0 1px 1px 0;border-width:1px 1px 1px 0;margin-right:3px">b</span><span class="text">Split</span>', 'split', has_search))
    # parts.append(btn('<span style="margin:-1px;padding:0 1px;font-size:8px;border: 1px solid #4e4e4e;border-radius:1px 0 0 1px;border-width:1px 0 1px 1px;">a</span>┆<span style="margin:-1px;padding:0 1px;font-size:8px;border: 1px solid #4e4e4e;border-radius:0;border-width:1px 0px 1px 0;">bc</span>┆<span style="margin:-1px;padding:0 1px;font-size:8px;border: 1px solid #4e4e4e;border-radius:0 1px 1px 0;border-width:1px 1px 1px 0;">b</span>', 'split', has_search, 'Split string at matches'))

    parts.append(btn(f'{ICONS["replace"]}<span class="text">Replace<span class="shortcut">⌘R</span></span>', 'replace', has_search and has_replace))
    parts.append(btn(f'{ICONS["filter"]}<span class="text">Filter</span>', 'filter', has_search and has_replace))

    # Last, and about the string rather than about the search -- see
    # _render_fetch_button.
    parts.append(_render_fetch_button(model, value, every_row_exps))

    return (
        f'<div class="action-buttons">'
        f'{"".join(parts)}'
        f'</div>'
    )


_TOOL_TOOLBAR_TOOLS = [
    # (tool id, icon HTML/text, display name, modifier that overrides to it)
    # The modifiers mirror _resolve_selection_type.
    ('literal', 'ab', 'Literal', 'shift'),
    ('fuzzy', '.*', 'Fuzzy', 'alt'),
    ('index', '01', 'Index', 'ctrl'),
    ('pick', nerd_font_icon('\U000F01BD'), 'Pick', None),
]


def _tool_tooltip(name: str, modifier: str | None) -> str:
    """The tool's name, and the key that picks it for a single gesture."""
    if modifier is None:
        return name
    return f'{name} ({modifier_key_label(modifier)})'


def _render_tool_toolbar(model, value: str = '', compact: bool = False) -> str:
    """Render the tool toolbar (literal/fuzzy/index/pick) for the upper-right corner.

    Two layouts:
      - VERTICAL (default): 4 stacked icon buttons. Used when the string is
        4+ lines tall so there's vertical room for them. Each icon button
        carries a data-tooltip attribute so the snc-tooltip system shows the
        tool's name on hover.
      - COMPACT (dropdown): a single-row trigger showing the active tool's
        ICON and a chevron (\U0001F783). Used when the string is shorter than
        4 lines so the toolbar doesn't dwarf the content. The 4 tool options
        live in a hover-menu panel underneath (icon + name per row). All 4
        icons also live (hidden) inside the trigger so CSS can swap which
        icon is visible based on body.snc-shift-down / snc-alt-down /
        snc-ctrl-down without a Python roundtrip.

    Each button (and dropdown option) carries a data-tool attribute so CSS
    can highlight the transient modifier override.

    The pick tool is DIMMED (click-disabled) when there's no current search
    since picking has nothing to operate on without a match.
    """
    current = (model or {}).get('tool', 'literal')
    if current not in ('literal', 'fuzzy', 'index', 'pick'):
        current = 'literal'
    has_search = bool((model or {}).get('search'))

    # Compact when the string fits in fewer than 4 lines vertically.
    # An empty string counts as 1 line.
    # line_count = (value.count('\n') + 1) if value else 1
    # compact = line_count < 4

    if not compact:
        return _render_tool_toolbar_vertical(current, has_search)
    return _render_tool_toolbar_compact(current, has_search)


def _tool_icon_html(tool: str, label: str) -> str:
    """Pre-rendered icon for the pick tool is HTML; raw text labels need escaping."""
    return ICONS['pick-tool'] if tool == 'pick' else html.escape(label)


def _render_tool_toolbar_vertical(current: str, has_search: bool) -> str:
    # Shared with the list visualizer's Normal/Pick toolbar; only the tool list
    # differs. Labels are escaped here because most are plain text.
    tools = [(tool, _tool_icon_html(tool, label), name, _tool_tooltip(name, modifier))
             for tool, label, name, modifier in _TOOL_TOOLBAR_TOOLS]
    return render_tool_toolbar(
        tools, current,
        lambda tool: repr(ToolSelect(tool=tool)),
        disabled=() if has_search else ('pick',))

# def _render_tool_toolbar_compact(current: str, has_search: bool) -> str:
#     # Shared with the list visualizer's Normal/Pick toolbar; only the tool list
#     # differs. Labels are escaped here because most are plain text.
#     tools = [(tool, _tool_icon_html(tool, label), name)
#              for tool, label, name in _TOOL_TOOLBAR_TOOLS]
#     return render_tool_toolbar(
#         tools, current,
#         lambda tool: repr(ToolSelect(tool=tool)),
#         disabled=() if has_search else ('pick',),
#         is_compact=True)

def _render_tool_toolbar_compact(current: str, has_search: bool) -> str:
    # Trigger: shows the active tool's ICON + a chevron. All 4 icons are
    # rendered as siblings; CSS hides all but the matching .tool-icon based
    # on data-active-tool (and modifier-key body classes).
    icon_spans = []
    for tool, label, _, _ in _TOOL_TOOLBAR_TOOLS:
        label_html = _tool_icon_html(tool, label)
        icon_spans.append(
            f'<span class="tool-icon" data-tool="{tool}">{label_html}</span>'
        )
    chevron = '<span class="tool-dropdown-chevron">\U0001F783</span>'
    trigger_html = (
        f'<span class="tool-button active tool-dropdown-trigger-button">'
        f'{"".join(icon_spans)}{chevron}</span>'
    )

    # Hover-menu panel: one row per tool (icon + name).
    rows = []
    for tool, label, name, modifier in _TOOL_TOOLBAR_TOOLS:
        tooltip = html.escape(_tool_tooltip(name, modifier))
        opt_cls = 'snc-dropdown-option tool-dropdown-option'
        if tool == current:
            opt_cls += ' active'
        disabled = (tool == 'pick' and not has_search)
        label_html = _tool_icon_html(tool, label)
        if disabled:
            opt_cls += ' dimmed'
            rows.append(
                f'<div class="{opt_cls}" data-tool="{tool}" data-tooltip="{tooltip}">'
                f'<span class="tool-dropdown-icon">{label_html}</span>'
                f'<span class="tool-dropdown-name">{html.escape(name)}</span>'
                f'</div>'
            )
        else:
            event = repr(ToolSelect(tool=tool))
            rows.append(
                f'<div class="{opt_cls}" data-tool="{tool}" data-tooltip="{tooltip}" '
                f'snc-mouse-down="{html.escape(event)}">'
                f'<span class="tool-dropdown-icon">{label_html}</span>'
                f'<span class="tool-dropdown-name">{html.escape(name)}</span>'
                f'</div>'
            )
    panel_html = (
        f'<div class="snc-dropdown-panel right tool-dropdown-panel" '
        f'snc-dropdown-align="right" data-hover-menu>'
        f'{"".join(rows)}</div>'
    )

    return (
        f'<div class="tool-toolbar tool-toolbar-compact" data-active-tool="{current}">'
        f'<span class="snc-dropdown-trigger tool-dropdown-trigger">'
        f'{trigger_html}{panel_html}'
        f'</span>'
        f'</div>'
    )


def _render_expand_bar(expanded: bool, value: str, model, *,
                       small: bool = False) -> str:
    """The bar under a clipped string: just the expand toggle. How tall and how
    long the string is rides on the search box instead (see
    _render_auxiliary_attributes) -- it is a tab about the search, and shows
    only while the search box does."""
    return (
        f'<div class="expand-and-len">'
        f'{render_expand_toggle(expanded, repr(ExpandToggle()), small=small)}'
        f'</div>'
    )

def _render_auxiliary_attributes(value: str, model, *, small: bool = False):
    """The tab on top of the search box: how tall the string is and how long,
    coarse measure before fine.

    Each count is a handle of its own -- the number on screen and the code that
    reads it are the same reading, so hovering one offers the other. The lines
    are counted the way they are drawn (a trailing newline draws an empty last
    line), so the expression offered counts them that way too rather than
    reaching for splitlines(), which would disagree with the screen. They render
    bare where there is no access path, the numbers still being worth having.
    """
    source_expr = model.get('_source_expr') if model else None
    if source_expr:
        len_exp = f'len({source_expr})'
        lines_exps = [
            PyExp(f"{source_expr}.count('\\n') + 1", label="Count"),
            PyExp(f"{source_expr}.splitlines()", label="As list"),
        ]
    else:
        len_exp = None
        lines_exps = None
    len_n = len(value)
    lines_n = value.count('\n') + 1

    return (
        f'<div class="auxiliary-attributes">'
        f'<div class="tiny-len" snc-unfocused-clickable{py_exp_attrs(lines_exps)}>{lines_n} line{"s" if lines_n != 1 else ""}</div>'
        f'<div class="tiny-len" snc-unfocused-clickable{py_exp_attrs(len_exp)}>{len_n} char{"s" if len_n != 1 else ""}</div>'
        f'</div>'
    )


def visualize(value, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, var_and_exp=None, every_row_exps=None) -> str:
    return ''.join(visualize_els(value, model, get_visualizer, eval_in_scope, max_width, max_height, small, var_and_exp, every_row_exps))

def visualize_els(value, model, get_visualizer, eval_in_scope, max_width=None, max_height=None, small=False, var_and_exp=None, every_row_exps=None) -> List[str]:
    if eval_in_scope is None:
        eval_in_scope = lambda _c: eval(_c)

    # Where this value sits is a property of the render, not of the model: a
    # parent's columns can change under a child that was built once. Adopt the
    # access path we were just handed so the draggable chips and the length
    # readout name the value the way the editor could evaluate it.
    if model is not None and var_and_exp:
        var_name, expr = var_and_exp
        model['_source_expr'] = var_name if var_name else expr

    # Small mode: a non-interactive inline preview. Skip all the expensive
    # selection/highlight machinery (preview regex, segment overlays, per-char
    # anchors, hover) and just print the raw string. We don't generate the
    # regex special chars (^/$ anchors, escape displays) at all here - small
    # mode has no search/selection so they'd add nothing. white-space:pre on
    # .string-visualizer renders the literal \n / \t correctly.
    #
    # The preview does get a whole-area drag handle, which the focused render
    # does not: dropping the per-character anchors drops their snc-py-exps with
    # them, so there is nothing inside for an outer handle to claim the hover
    # from, and without one the string would be the one value on the screen that
    # can't be dragged out. Same wrapper the generic visualizers use, for the
    # same reason -- no content of its own to hover.
    #
    # Read-only visualizers (clickacode.readOnlyVisualizers) draw the same preview
    # even when focused: everything the focused render adds -- the selection
    # anchors, the search box, the action buttons -- exists to build code, and
    # under read-only none of it may be offered. What is left is the text, the
    # expand bar, and the counts (which py_exp_attrs leaves bare).
    read_only = is_read_only()
    if small or read_only:
        # Non-focused preview: wrap the string in leading/trailing ' quotes so
        # it reads as a string literal. Each newline after the first gets a
        # leading space so subsequent lines align vertically under the first
        # line's content (which the opening quote shifts one char to the right).
        raw = value or ""
        display = "'" + raw.replace("\n", "\n ") + "'"
        size_styling = f'style="max-width:{max_width}px"' if max_width is not None else ''

        # Plain text, no per-character addressing. snc-text-start would let the
        # front-end turn a caret offset into an internal index, but the preview
        # cannot honour it: a newline prints one character while spending three
        # internal indices ($, the \n display, ^), so everything past one would
        # name the wrong character. Splitting per line would fix the arithmetic
        # at the cost of an element per line, which is what the grouping exists
        # to avoid. Nothing wants those indices anyway -- see PinFocus.
        display_html = html.escape(display)

        # Expand/collapse toggle is offered even in the non-focused (small)
        # preview so a tall string can be peeked at without pinning focus to
        # its line. Mirrors the focused-mode behavior below: only tall strings
        # (>4 lines) get it, since shorter ones aren't clipped by the 80px pane.
        expanded = bool(model.get('expanded', False)) if model else False
        expanded_class = ' expanded' if expanded else ''
        line_count = (raw.count('\n') + 1) if raw else 1
        expand_toggle_html = ''
        if line_count > 4:
            expand_toggle_html = _render_expand_bar(
                expanded, value, model, small=True)

        expandable_class = ' is-expandable' if expand_toggle_html else ''



        # One mousedown for the whole preview, standing in for the per-character
        # ones the focused render has. A nested preview is focused by clicking
        # it, and that is all this has to carry. The expand toggle sits inside
        # the handle but opts out of it (see render_expand_toggle), so a slipped
        # click on the chevron isn't read as a drag of the string.
        # A read-only focused string is already focused: nothing to pin, and
        # no keys to handle.
        handlers = ('' if not small else
                    f'snc-key-down="{html.escape(repr(KeyDown()))}" snc-mouse-down="{html.escape(repr(PinFocus()))}" ')
        small_class = ' small' if small else ''
        small_html = (
            f'<div tabindex="0" {handlers}class="visualizer-container literal-tool-selected{small_class}{expanded_class}{expandable_class}"><div class="snc-tool-and-visualizer"><div class="string-visualizer snc-base-visualizer"{size_styling}><div>'  # .string-visualizer is flex to remove extra pixels. needs extra inner div to restore white-space:pre
            f'{display_html}'
            f'</div></div>{expand_toggle_html}</div></div>'
        )
        return [wrap_drag_grab(small_html, var_and_exp)]

    # Build highlight_by_index from highlights (uses preview regex to include in-progress selection)
    preview_regex = build_preview_regex(model, value)
    highlights = parse_regex_for_highlighting(preview_regex, value, eval_in_scope) if value else []

    # Pick mode replaces the highlights with a curated set covering only the
    # FIRST match's prefix / capture-groups (or whole match) / suffix. Each
    # highlight is tagged so char_span_els emits SegmentToggle handlers + a chip.
    active_tool = (model or {}).get('tool', 'literal')
    segment_overlays = None
    if active_tool == 'pick' and value and model is not None:
        segment_overlays = _compute_segment_overlays(value, model, eval_in_scope)
        if segment_overlays:
            highlights = segment_overlays['highlights']

    highlight_by_index = {}
    for highlight in highlights:
        start, end, _, _, _, _ = highlight
        for i in range(start, end):
            highlight_by_index[i] = highlight

    # Count of primary (interactive) segments, used by char_span_els to decide
    # whether a fuzzy segment has an open end (and thus a resize handle) on a
    # given side. Primary segments have contiguous left-to-right indices, so a
    # segment has a left/right neighbor iff its index isn't the first/last.
    if model is not None:
        model['_primarySegmentCount'] = sum(1 for h in highlights if h[5] is not None)

    # Inline chips (start/end index labels in segment mode) are rendered as
    # extra HTML inserted before / after the corresponding char's wrapper.
    extra_chips_by_index = (segment_overlays['chips_by_index']
                            if segment_overlays else {})
    extra_chips_after_by_index = (segment_overlays.get('chips_after_by_index', {})
                                   if segment_overlays else {})

    scroll_to_match = model.get('_scroll_to_match', False) if model else False
    first_match_index = highlights[0][0] if (scroll_to_match and highlights) else None

    # Build character sequence with highlighting
    char_els = []

    # Visible start anchor is selectable at internal index 0
    char_els.append(char_span('^', 0, True, highlight_by_index.get(0), model, scroll_to=(0 == first_match_index), is_regex_anchor=True))

    hover_idx = model.get('hoverIdx') if model and not model.get('dragging') else None
    group_chars = []
    group_start = None

    def flush_group():
        nonlocal group_chars, group_start
        if group_chars and group_start is not None:
            char_els.append(text_group_span(group_chars, group_start))
            group_chars = []
            group_start = None

    index = 1
    for char in value:
        # Segment-mode start/end chips are inserted around the char they
        # belong to. They're absolutely positioned so they just need to be a
        # sibling near the right index.
        chips_here = extra_chips_by_index.get(index)
        if chips_here:
            flush_group()
            for chip_html in chips_here:
                char_els.append(chip_html)
        is_plain = (
            char != '\n' and char != '\t'
            and highlight_by_index.get(index) is None
            and index != hover_idx
        )
        index_before_char = index
        if is_plain:
            if group_start is None:
                group_start = index
            group_chars.append(char)
            index += 1
        else:
            flush_group()
            char_htmls, index = vis_char_with_index_els(char, index, highlight_by_index, model, scroll_to=(index == first_match_index))
            char_els.extend(char_htmls)
        # After-chips render to the right of the char. For plain chars (which
        # get batched into text-group spans), flush the group first so the
        # chip stays at the correct index.
        chips_after = extra_chips_after_by_index.get(index_before_char)
        if chips_after:
            flush_group()
            for chip_html in chips_after:
                char_els.append(chip_html)

    flush_group()

    # (must match internal index scheme for 1:1 correspondence with extract_by_internal_indices)
    char_els.append(char_span('$', index, True, highlight_by_index.get(index), model, scroll_to=(index == first_match_index), is_regex_anchor=True))
    index += 1

    # The string's length used to be printed here, floating at the top-left of
    # the final character position. It lives on the expand bar now (see
    # _render_expand_bar), out of the text's way -- but only for a string tall
    # enough to have a bar.

    # chars_html = ''.join(char_els)

    # The tool toolbar (literal/fuzzy/index/pick) is only useful when this is
    # the focused visualizer; in small mode there's no room for it and it
    # would just compete with the user's actual focus elsewhere.
    line_count = ((value or '').count('\n') + 1) if value else 1
    compact = line_count < 4
    tool_toolbar_html = '' if small else _render_tool_toolbar(model, value or '', compact)
    active_tool = (model or {}).get('tool', 'literal')
    if active_tool not in ('literal', 'fuzzy', 'index', 'pick'):
        active_tool = 'literal'

    # Build the search box at the bottom (hidden when small)
    if small:
        search_box_html = ""
    else:
        selection_regex = model.get("search")
        search_box_value = selection_regex if selection_regex else ""
        search_input_event = "lambda e: SearchBoxInput(value=e.get('value', ''))"
        # Index/slice searches force 1st on and disable Aa / (Cap)(Grps)
        idx_slice = is_index_or_slice_search(selection_regex, eval_in_scope)

        # Icon-only toggles get a data-tooltip so the snc-tooltip system
        # shows the human-readable name on hover (same pattern as the tool
        # toolbar in the upper-right corner).

        # "(Cap)(Grps)" toggle: on = capture groups preserved, off = only adjacent literal groups
        cap_groups_on = is_capture_groups_mode(selection_regex)
        cg_event = repr(CaptureGroupsToggle())
        cg_tooltip = 'data-tooltip="Use capture groups"'
        if idx_slice:
            cap_groups_toggle_html = f'<span class="search-button inactive dimmed" {cg_tooltip}>{ICONS["regex-group"]}</span>'
        else:
            cap_groups_toggle_html = f'<span class="search-button {"active" if cap_groups_on else "inactive"}" {cg_tooltip} snc-mouse-down="{html.escape(cg_event)}">{ICONS["regex-group"]}</span>'

        # "Aa" toggle: on (highlighted) = case-sensitive (default), off = case-insensitive
        # Dimmed and non-interactive for index/slice
        case_sensitive = not is_case_insensitive(selection_regex)
        cs_event = repr(CaseSensitiveToggle())
        cs_tooltip = 'data-tooltip="Match case"'
        if idx_slice:
            case_toggle_html = f'<span class="search-button inactive dimmed" {cs_tooltip}>{ICONS["caps"]}</span>'
        else:
            case_toggle_html = f'<span class="search-button {"active" if case_sensitive else "inactive"}" {cs_tooltip} snc-mouse-down="{html.escape(cs_event)}">{ICONS["caps"]}</span>'

        # "1st" toggle: off by default, on = first-match
        # Forced on for index/slice
        first_match = is_first_match_mode(selection_regex) or idx_slice
        fm_event = repr(FirstMatchToggle())
        fm_tooltip = 'data-tooltip="First match only"'
        first_match_toggle_html = f'<span class="search-button {"active" if first_match else "inactive"}" {fm_tooltip} snc-mouse-down="{html.escape(fm_event)}">{ICONS["match-first"]}</span>'

        # compact_toolbar = tool_toolbar_html if compact else ''
        # if compact:
        #     tool_toolbar_html = ''

        toggles_html = (
            f'<span class="search-toggles-container">'
            f"{cap_groups_toggle_html}"
            f"{case_toggle_html}"
            f"{first_match_toggle_html}"
            f"</span>"
        )
        replace_visible = model.get("replace_visible", False)
        replace_toggle_event = repr(ReplaceToggle())
        disclosure_icon = (
            '<span style="transform: rotate(90deg)">></span>'
            if replace_visible
            else ">"
        )
        discolure_button = f'<span snc-mouse-down="{html.escape(replace_toggle_event)}" data-tooltip="Toggle replace/map/filter" class="search-button disclosure-button">{disclosure_icon}</span>'

        replace_box_html = ""
        match_preview_html = ""
        preview_html = ""
        if replace_visible:
            replace_text_value = model.get("replace_text") or ""
            replace_input_event = "lambda e: ReplaceBoxInput(value=e.get('value', ''))"
            preview_html = _render_transform_preview(model, value, eval_in_scope)
            match_preview_html = _render_match_object_preview(model, value, eval_in_scope)
            replace_tooltip = replace_scope(idx_slice).legend
            replace_box_html = (
                f'<div class="search-box-wrapper replace-box-wrapper">'
                f'<input type="text" tabindex="0"'
                f' snc-input="{html.escape(replace_input_event)}"'
                f' value="{html.escape(replace_text_value)}"'
                f' placeholder="Replace/Map/Filter"'
                f' data-tooltip="{html.escape(replace_tooltip)}"'
                f' spellcheck="false"'
                f' class="search-box search-box-replace"'
                f" />"
                f'{preview_html}'
                f'</div>'
            )

        search_input_html = (
            f'<div class="search-box-wrapper">'
            f'<input type="text" tabindex="0"'
            f' snc-input="{html.escape(search_input_event)}"'
            f' value="{html.escape(search_box_value)}"'
            f' placeholder="Find"'
            f' data-tooltip="{html.escape(FIND_TOOLTIP)}"'
            f' spellcheck="false"'
            f' class="search-box"'
            f" />"
            f"{toggles_html}"
            f" </div>"
        )



        # Action buttons bar (hidden when small)
        action_buttons_html = (
            "" if small else _render_action_buttons(model, value, eval_in_scope,
                                                    max_width, every_row_exps)
        )

        auxiliary_html = _render_auxiliary_attributes(value, model, small=small)

        search_box_html = (
            f'<div class="search-div toolbar-anchor {"expanded" if replace_visible else ""}">'
            f'<div class="search-div-row">'
            f"{discolure_button}"
            f'<div class="search-replace-container">'
            f"{search_input_html}"
            f"{replace_box_html}"
            f"{match_preview_html}"
            f"</div>"
            f"</div>"
            f'<div class="search-div-row">'
            f'<div class="disclosure-button-spacer"></div>'
            f'{action_buttons_html}'
            f"</div>"
            f'{auxiliary_html}'
            f"</div>"
            f"</div>"
        )

    # Compact (dropdown) toolbar is used when the string is < 4 lines tall.
    # The visualizer container gets a class so CSS can add a few extra
    # right-padding pixels to keep characters from overlapping the wider
    # dropdown trigger. No need for that padding when the toolbar isn't there.
    compact_class = ' tool-toolbar-compact-container' if compact else ''

    # Expand/collapse toggle: only offered for tall strings (>4 lines), where the
    # 80px-tall pane clips the content. Clicking it expands the pane to its
    # 600px max-height (see string-visualizer.css). The container carries an
    # `expanded` class when open so the CSS can bump the max-height and rotate
    # the chevron. Not shown in small mode (handled by the early return above).
    expanded = bool(model.get('expanded', False)) if model else False
    expanded_class = ' expanded' if expanded else ''
    expand_toggle_html = ''
    if line_count > 4:
        expand_toggle_html = _render_expand_bar(expanded, value, model)

    is_expandable_class = ' is-expandable' if expand_toggle_html else ''

    # Add tabindex to make div focusable for keyboard events, and snc-key-down handler
    # doing it like this to try to make less string garbage. Small mode returned
    # early above (self-wrapped for drag), so this is always the full/interactive
    # path - it keeps its mouse events and is not a drag handle.
    return [
        f'''<div tabindex="0" snc-key-down="{html.escape(repr(KeyDown()))}" class="visualizer-container {active_tool}-tool-selected{compact_class}{expanded_class}{is_expandable_class}"><div class="snc-tool-and-visualizer">{tool_toolbar_html}<div class="string-visualizer snc-base-visualizer"><div>''', # .string-visualizer is flex to remove extra pixels. needs extra inner div to restore white-space:pre
        *char_els,
        f"""</div></div>{expand_toggle_html}</div>{search_box_html}</div>""",
    ]


def _eval_index_or_slice_match(selection_regex: str, string_value: str, eval_in_scope) -> str | list | None:
    """Evaluate index or slice search and return the matched string(s), or None.

    Returns:
      - str for single index/slice
      - list[str] for multi-index, multi-pair-slice, or broadcast slice
      - None if not an index/slice search
    """
    parsed = parse_search_term(selection_regex)
    if not parsed:
        return None
    kind, term, _flags = parsed

    if kind == 'slice':
        left, right = term
        try:
            start = eval_in_scope(left) if left else None
            stop = eval_in_scope(right) if right else None
        except Exception:
            return None
        start_is_list = _is_list_of_ints(start)
        stop_is_list = _is_list_of_ints(stop)
        if start_is_list or stop_is_list:
            n = len(string_value)
            if start_is_list and stop_is_list:
                return [string_value[s:e] for s, e in zip(start, stop)]
            elif start_is_list:
                return [string_value[s:stop] for s in start]
            else:
                return [string_value[start:e] for e in stop]
        sliced = string_value[start:stop]
        return sliced if sliced else None

    if kind == 'expr':
        try:
            result = eval_in_scope(term)
        except Exception:
            return None
        if isinstance(result, int) and not isinstance(result, bool):
            n = len(string_value)
            if n == 0 or result < -n or result >= n:
                return None
            return string_value[result]
        if _is_list_of_ints(result):
            return [string_value[i] for i in result]
        if _is_list_of_int_pairs(result):
            return [string_value[s:e] for s, e in result]

    return None


def is_index_or_slice_search(selection_regex: str | None, eval_in_scope=None) -> bool:
    """Check if the search is an index (expression->int), slice, or multi-index search.

    For slice, no eval needed. For index/multi variants, eval_in_scope is
    required to check if the expression evaluates to int, list[int], or
    list[tuple[int,int]].
    """
    parsed = parse_search_term(selection_regex)
    if not parsed:
        return False
    kind, term, _flags = parsed
    if kind == 'slice':
        return True
    if kind == 'expr' and eval_in_scope is not None:
        try:
            result = eval_in_scope(term)
            if isinstance(result, int) and not isinstance(result, bool):
                return True
            if _is_list_of_ints(result) or _is_list_of_int_pairs(result):
                return True
        except Exception:
            pass
    return False


def _eval_count_via_grammar(selection_regex: str | None, value: str, model: dict, eval_in_scope) -> int:
    """Compute count preview by generating and evaluating the grammar's CountAction expression.

    Uses the same generate_action('count', ...) path as the Count button click,
    ensuring the preview always matches the code that would be produced.
    """
    from string_visualizer_grammar import generate_action as _gen_action

    if not selection_regex or not value:
        return 0

    ctx = _get_search_context(model, source_expr='_snc_v', eval_in_scope=eval_in_scope)
    if not ctx or ctx.get('is_index') or ctx.get('is_slice'):
        return 0

    result = _gen_action('count', ctx)
    if not result:
        return 0

    _, code = result
    try:
        count_fn = eval_in_scope(f"(lambda _snc_v: {code})")
        return count_fn(value)
    except Exception:
        return 0


def _find_matches(selection_regex: str, string_value: str, eval_in_scope) -> list:
    """Return match objects (or matched strings for index/slice) for the current search pattern."""
    if not selection_regex or not string_value:
        return []

    matched = _eval_index_or_slice_match(selection_regex, string_value, eval_in_scope)
    if matched is not None:
        if isinstance(matched, list):
            return matched
        return [matched]
    if is_slice_search(selection_regex) or is_index_or_slice_search(selection_regex, eval_in_scope):
        return []

    parsed = parse_search_term(selection_regex)
    if not parsed:
        return []
    kind, term, flags = parsed
    ci = 'i' in flags
    first = '1' in flags

    if kind in ('string', 'expr'):
        if kind == 'string':
            search_text = eval_string_search(selection_regex)
        else:
            try:
                search_text = eval_in_scope(term)
            except Exception:
                return []
            if not isinstance(search_text, str):
                return []
        if not search_text:
            return []
        compiled = re.compile(re.escape(search_text), re.IGNORECASE if ci else 0)
        if first:
            m = compiled.search(string_value)
            return [m] if m else []
        return list(compiled.finditer(string_value))

    if kind == 'regex':
        pattern = strip_capturing_groups(term) if term else ''
        if not pattern:
            return []
        re_flags = re.M | (re.I if ci else 0)
        try:
            if first:
                m = re.search(pattern, string_value, flags=re_flags)
                return [m] if m else []
            return list(re.finditer(pattern, string_value, flags=re_flags))
        except Exception:
            return []

    return []


def _compute_predicate_previews(selection_regex, value, replace_visible, replace_text, match_count, eval_in_scope):
    """Compute (any_val, all_val) boolean previews for the predicate dropdown.

    Returns (bool|None, bool|None). None means not applicable / not computable.
    """
    if not selection_regex:
        return (None, None)

    if not replace_visible or not replace_text:
        return (match_count > 0, None)

    # Replace mode: evaluate the replace expression against actual matches
    matches = _find_matches(selection_regex, value, eval_in_scope)
    if not matches:
        return (False, True)  # any([])=False, all([])=True per Python semantics

    replace_expr = _replace_expr_bound(replace_text, 'mtch', _PREVIEW_SOURCE_BINDER)

    try:
        transform_fn = eval_in_scope(f"(lambda mtch, {_PREVIEW_SOURCE_BINDER}: {replace_expr})")
        results = [transform_fn(m, value) for m in matches]
        return (any(results), all(results))
    except Exception:
        return (None, None)


def _preview_chip(expr: str, val_repr: str, target: str = '.snc-replace-input') -> str:
    """Render a single clickable preview chip: expr => value.

    The snc-add-at-cursor attribute tells the front-end to insert `expr`
    at the cursor position in the input matched by snc-add-target (a CSS selector).
    """
    return (
        f'<span class="preview-chip-container">'
        f'<span class="preview-chip" snc-add-at-cursor="{html.escape(expr)}" snc-add-target="{html.escape(target)}">{html.escape(expr)}</span>'
        f' U {val_repr}'
        f'</span>'
    )

def _render_match_object_preview(model: dict, value: str, eval_in_scope) -> str:
    """Render the first regex match as a compact z_object small view between find/replace.

    Returns HTML string with draggable match properties ($[0], $.start(), $.end(),
    and capture groups), or '' if no regex match exists.
    """
    selection_regex = model.get('search')
    if not selection_regex:
        return '<div class="match-object-preview"><span class="small">No matches</span></div>'
    if is_index_or_slice_search(selection_regex, eval_in_scope):
        matched = _eval_index_or_slice_match(selection_regex, value, eval_in_scope)
        if matched is None:
            return '<div class="match-object-preview"><span class="small">No matches</span></div>'
        val_repr = truncate_repr(matched)
        field_html = z_object_visualizer.render_small_field(
            '$', val_repr, '$', add_target='.search-box-replace')
        return f'<div class="match-object-preview"><span class="small">{field_html}</span></div>'

    matches = _find_matches(selection_regex, value, eval_in_scope)
    if not matches:
        return '<div class="match-object-preview"><span class="small">No matches</span></div>'
    m = matches[0]
    if not isinstance(m, re.Match):
        return '<div class="match-object-preview"><span class="small">Match not a match object, ut oh</span></div>'

    fields = ['$[0]', '$.start()', '$.end()']
    grouped_match = None
    if is_regex_search(selection_regex):
        inner = get_regex_inner_pattern(selection_regex)
        if inner:
            ci = is_case_insensitive(selection_regex)
            flags = re.M | (re.I if ci else 0)
            try:
                grouped_match = re.search(inner, value, flags=flags)
                if grouped_match and grouped_match.lastindex:
                    for i in range(1, grouped_match.lastindex + 1):
                        if grouped_match.group(i) is not None:
                            fields.append(f'$[{i}]')
            except Exception:
                grouped_match = None

    display_match = grouped_match if grouped_match is not None else m
    match_model = {
        'fields': fields,
        '_source_expr': '$',
        '_add_target': '.search-box-replace',
    }
    obj_html = z_object_visualizer.visualize(
        display_match, match_model, None, eval_in_scope, small=True)
    return f'<div class="match-object-preview">{obj_html}</div>'


def _render_transform_preview(model: dict, value: str, eval_in_scope) -> str:
    """Render a live preview of match metadata and transform result using the first match.

    Returns HTML string, or '' if preconditions are not met (replace not visible,
    no search, or no matches).

    For index/slice searches, $ is the matched string (not a match object),
    so the preview shows $ => 'str' instead of $[0], $.start(), $.end().

    When the regex has capture groups, shows $[1], $[2], etc. alongside $[0].
    All expression chips are clickable (snc-add-at-cursor) to insert into the replace box.
    """
    if not model.get('replace_visible', False):
        return ''
    selection_regex = model.get('search')
    if not selection_regex:
        return ''

    is_idx_slice = is_index_or_slice_search(selection_regex, eval_in_scope)

    if is_idx_slice:
        matched_str = _eval_index_or_slice_match(selection_regex, value, eval_in_scope)
        if matched_str is None:
            return ''

        m_repr = html.escape(truncate_repr(matched_str))
        # row1 = _preview_chip('$', m_repr)

        result_str = ''
        replace_text = model.get('replace_text')
        if replace_text:
            replace_expr = _replace_expr_bound(replace_text, 'mtch', _PREVIEW_SOURCE_BINDER)
            try:
                transform_fn = eval_in_scope(f"(lambda mtch, {_PREVIEW_SOURCE_BINDER}: {replace_expr})")
                result = transform_fn(matched_str, value)
                result_str = html.escape(truncate_repr(result))
            except Exception as e:
                result_str = html.escape(str(e))
        row2 = f'<div class="transform-preview-content">{result_str}</div>' if result_str else ''

        return (
            f'<div class="transform-preview">'
            # f'<div class="transform-preview-content" style="font-size: 7px; filter: saturate(0.75); opacity: 0.75;">Match: {row1}</div>'
            f'{row2}'
            f'</div>'
        )

    matches = _find_matches(selection_regex, value, eval_in_scope)
    if not matches:
        return ''

    m = matches[0]
    m0 = html.escape(truncate_repr(m[0]))
    mstart = html.escape(truncate_repr(m.start()))
    mend = html.escape(truncate_repr(m.end()))

    # row1 = (
    #     _preview_chip('$[0]', m0)
    #     + _preview_chip('$.start()', mstart)
    #     + _preview_chip('$.end()', mend)
    # )

    # produce grouped_match for the transform evaluation so that
    # expressions like $[2] resolve against the real capture groups.
    # group_chips = ''
    grouped_match = None
    if is_regex_search(selection_regex):
        inner = get_regex_inner_pattern(selection_regex)
        if inner:
            ci = is_case_insensitive(selection_regex)
            flags = re.M | (re.I if ci else 0)
            try:
                grouped_match = re.search(inner, value, flags=flags)
                # if grouped_match and grouped_match.lastindex:
                    # for i in range(1, grouped_match.lastindex + 1):
                        # g = grouped_match.group(i)
                        # if g is not None:
                            # g_repr = html.escape(truncate_repr(g))
                            # group_chips += _preview_chip(f'$[{i}]', g_repr)
            except Exception:
                grouped_match = None

    transform_match = grouped_match if grouped_match is not None else m

    result_str = ''
    replace_text = model.get('replace_text')
    if replace_text:
        replace_expr = _replace_expr_bound(replace_text, 'mtch', _PREVIEW_SOURCE_BINDER)

        try:
            transform_fn = eval_in_scope(f"(lambda mtch, {_PREVIEW_SOURCE_BINDER}: {replace_expr})")
            result = transform_fn(transform_match, value)
            result_str = html.escape(truncate_repr(result))
        except Exception as e:
            result_str = html.escape(str(e))
    row2 = f'<div class="transform-preview-content">{result_str}</div>' if result_str else ''

    return (
        f'<div class="transform-preview">'
        f'{row2}'
        f'</div>'
    )


def init_model(value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
    """
    Initialize the model state for a new visualization.

    Args:
        value: The string value being visualized (not stored in model)
        var_and_exp: (var_name | None, expression) tuple from the source line
    """
    source_expr = None
    if var_and_exp:
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else expr

    return {
        "_source_expr": source_expr,
        "search": None,   # Regex pattern in Pythonic raw-string form, e.g., "r'hello.*world'"
        "anchorIdx": None,
        "anchorType": None,       # "literal" or "fuzzy" - determined when drag starts
        "cursorIdx": None,
        "dragging": False,
        "extendDirection": None,  # "left", "right", or None - which side we're extending from
        "insertAfterSegment": None,  # Segment index to insert after (for clicking inside fuzzy)
        "openDropdown": None,     # {"id": "fuzzy-pattern-0", "segmentIndex": 0} when dropdown is open
        "handleDrag": None,       # {"segmentIndex": int, "side": "left"|"right", "cursorIdx": int} when dragging a handle
        "undoHistory": [],        # Stack of previous search states
        "redoHistory": [],        # Stack for redo
        "handledKeys": ["Escape", "Enter", "cmd Backspace", "cmd r", "cmd z", "cmd shift z"],  # Keys to intercept from VS Code
        "hoverIdx": None,         # Internal index of the character currently hovered
        "replace_visible": False, # Whether the replace input box is visible
        "expanded": False,        # Whether the (tall) string-visualizer pane is expanded
        "replace_text": None,     # The replacement text (a Python string literal, e.g., "'world'")
        "linked_action": None,         # When linked: the action name (e.g. 'replace')
        "linked_source_expr": None,  # When linked: variable from parsed code (e.g. 'str1')
        "last_linked_expr": None,      # Last expression written to the linked LOC; skip
                                       # ChangeSelectedText when unchanged (hover, etc.)
        "auto_linked_once": False,     # True once an interaction has auto-inserted+linked a LOC
                                       # (prevents inserting a second line on later interactions)
        "unlinked_action": None,       # Action stashed on Unlink so the chain icon can
                                       # resume it when the user re-links
        "tool": "literal",             # Active selection tool: 'literal', 'fuzzy', 'index', or 'pick'
        "selectedSegments": [],        # In pick-tool mode: list of selected segment IDs
                                       # ('start', 'end', 'prefix', 'group_0', 'group_N', 'suffix')
                                       # in canonical order, used to drive the Replace box.
    }


def is_top_half(event_json):
    """Determine if mouse click was in top half of the target element."""
    offset_y = event_json.get('offsetY', 0)
    height = event_json.get('elementHeight', 1)
    return offset_y <= height / 2


def _resolve_selection_type(model, event_json):
    """Resolve the selection type for a click/hover from the active tool and modifiers.

    Priority order (matches the CSS override order in string-visualizer.css):
      shift > alt > ctrl > model['tool']
    - Shift held    -> 'literal'
    - Option/Alt    -> 'fuzzy'
    - Control       -> 'index'  (ctrl, not cmd/meta: cmd is reserved for
                                 cmd-backspace / cmd-r / cmd-z actions)
    - Otherwise: the model's active tool ('literal', 'fuzzy', or 'index').
    """
    if event_json.get('shiftKey'):
        return 'literal'
    if event_json.get('altKey'):
        return 'fuzzy'
    if event_json.get('ctrlKey'):
        return 'index'
    tool = (model or {}).get('tool', 'literal')
    # 'pick' is a chip-only mode: plain mouse drags fall back to 'literal'
    # so the user can still click on regular characters meaningfully.
    if tool == 'pick':
        return 'literal'
    return tool


def finalize_segment(model: dict, string_value: str) -> dict:
    """
    Finalize the in-progress segment and add it to search.

    Commits the current anchor/cursor selection to the regex pattern,
    saves to undo history, and clears the in-progress state.

    Args:
        model: The model state
        string_value: The string being visualized
    """
    # Build the new regex using the same logic as preview
    new_regex = build_preview_regex(model, string_value)
    current_regex = model.get('search')

    # Only update regex and undo history if something changed
    if new_regex != current_regex:
        model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
        model['redoHistory'] = []  # Clear redo on new action
        model['search'] = new_regex

    # Always clear in-progress state
    model['anchorIdx'] = None
    model['cursorIdx'] = None
    model['extendDirection'] = None
    model['insertAfterSegment'] = None
    model['dragging'] = False
    return model


def finalize_handle_drag(model: dict, string_value: str) -> dict:
    """
    Finalize a handle drag and update search.

    Computes the resized regex from the handle drag state, saves to undo history
    if changed, and clears the handleDrag state.

    Args:
        model: The model state (must have handleDrag set)
        string_value: The string being visualized
    """
    new_regex = _compute_handle_drag_regex(model, string_value)
    current_regex = model.get('search')

    # Only update if something changed
    if new_regex != current_regex:
        model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
        model['redoHistory'] = []
        model['search'] = new_regex

    model['handleDrag'] = None
    return model


def _commit_open_dropdown_edit(model: dict) -> None:
    """Apply any buffered edit from the currently-open dropdown to model['search'].

    Repetition + slice-label dropdowns BUFFER user-typed values into
    openDropdown state without touching model['search'] (so a transient
    invalid expression doesn't make the segment - and the dropdown -
    disappear mid-edit). This helper performs the deferred commit just
    before openDropdown is cleared (MouseDown elsewhere, DropdownToggle
    close, Enter, etc.). Escape is intentionally NOT plumbed through here:
    it stays a "discard" key.

    Caller is responsible for clearing model['openDropdown'] afterwards.
    """
    od = model.get('openDropdown')
    if not od:
        return
    did = od.get('id', '')

    if did.startswith('slice-label-'):
        # Build a new search by replacing the requested side with the
        # buffered value (or the whole expression for 'center').
        side = od.get('side') or did[len('slice-label-'):]
        typed = od.get('value', '')
        current_search = model.get('search') or ''
        if side == 'center':
            new_search = typed
        else:
            parts = parse_slice_parts(current_search)
            if parts is None:
                return
            left, right = parts
            if side == 'start':
                left = typed
            else:
                right = typed
            new_search = f'{left}:{right}'
        if new_search != current_search:
            model['undoHistory'] = model.get('undoHistory', []) + [current_search]
            model['redoHistory'] = []
            model['search'] = new_search if new_search else None
        return

    if did.startswith('repetition-'):
        segment_index = od.get('segmentIndex', 0)
        exact = od.get('exactN', '')
        rmin = od.get('rangeMin', '')
        rmax = od.get('rangeMax', '')
        new_quantifier = None
        if exact.isdigit() and exact != '':
            new_quantifier = '{' + exact + '}'
        elif rmin.isdigit() and rmax.isdigit():
            new_quantifier = '{' + rmin + ',' + rmax + '}'
        elif rmin.isdigit():
            new_quantifier = '{' + rmin + ',}'
        if new_quantifier is None:
            return
        current_regex = model.get('search')
        if not current_regex:
            return
        new_regex = replace_segment_repetition(current_regex, segment_index, new_quantifier)
        if new_regex != current_regex:
            model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
            model['redoHistory'] = []
            model['search'] = new_regex


# =============================================================================
# Expression Builder Helpers for Action Buttons
# =============================================================================

def _ctx_to_model(ctx: dict, model: dict) -> None:
    """Apply parsed DSL context to model state (reverse of _get_search_context).

    Mutates *model* in-place to reflect the search, replace, and flag state
    encoded in *ctx* (as returned by parse_generated_code).
    """
    if ctx.get('is_index'):
        model['search'] = ctx.get('index_expr', '')
    elif ctx.get('is_slice'):
        start = ctx.get('slice_start', '')
        stop = ctx.get('slice_stop', '')
        model['search'] = f'{start}:{stop}'
    elif ctx.get('is_expr') and ctx.get('expr'):
        model['search'] = ctx['expr']
    elif ctx.get('regex_pattern') is not None:
        flags = ''
        if ctx.get('is_first'):
            flags += '1'
        if ctx.get('is_ci'):
            flags += 'i'
        model['search'] = make_regex_search(ctx['regex_pattern'], flags)
    else:
        model['search'] = None

    replace_expr = ctx.get('replace_expr')
    if replace_expr:
        model['replace_visible'] = True
        # Inverse of _replace_expr_bound: turn the bound names back into the
        # dollar levels the replace box shows.
        model['replace_text'] = re.sub(
            rf'\b{CHILD_SOURCE_BINDER}\b', CHILD_SOURCE_DISPLAY,
            re.sub(r'\bmtch\b', '$', replace_expr))
    else:
        has_replace = ctx.get('has_replace', False)
        if not has_replace:
            model['replace_visible'] = False
            model['replace_text'] = None

    model['anchorIdx'] = None
    model['cursorIdx'] = None
    model['dragging'] = False
    model['insertAfterSegment'] = None
    model['openDropdown'] = None
    model['handleDrag'] = None
    model['undoHistory'] = []
    model['redoHistory'] = []


def _unwrap_backtick_expr(text: str) -> str:
    """Strip the `...` delimiters an expression search is written with."""
    if text.startswith('`') and len(text) >= 2:
        end = text.find('`', 1)
        if end > 0:
            return text[1:end]
    return text


def _wrap_source_expr(expr: str) -> str:
    """Parenthesize a source expression so it composes into generated code.

    The parens are load-bearing beyond precedence: they also mark the source as
    an expression rather than a named variable, which is what keeps a generated
    assignment named `result_*` instead of borrowing the expression's text.
    The nesting binder is exempt - it is a plain name the parent substitutes
    into, and must stay a bare token for nest_generated_expr to find it.
    """
    return expr if expr == CHILD_SOURCE_BINDER else f"({expr})"


def _display_source_expr(source_expr: str) -> str:
    """How the source string is SHOWN (replace box, segment chips).

    Nested in a list cell or object field, the value is bound to a name for code
    generation - but the user reads it as $$, one scope out from the $ bound to
    the current match.
    """
    return CHILD_SOURCE_DISPLAY if source_expr == CHILD_SOURCE_BINDER else source_expr


def _replace_expr_bound(replace_text: str, *binders: str) -> str:
    """The replace box's text as Python, with each dollar level bound.

    binders[0] binds $ (the current match); binders[1] binds $$ (the string
    being searched) - a name when generating code, the value itself when
    evaluating a preview.
    """
    return replace_dollars_in_py_exp(_unwrap_backtick_expr(replace_text), list(binders))


def _get_search_context(model: dict, var_and_exp=None, *, source_expr: str = None, eval_in_scope=None) -> dict | None:
    """Extract common search context from model and source info.

    Returns None if no valid search pattern or source info is available.
    Otherwise returns a dict with all values needed to build code expressions.

    If source_expr is provided, var_and_exp is not needed
    (used by the count preview which doesn't have source context).
    """
    selection_regex = model.get('search')
    if not selection_regex:
        return None

    parsed = parse_search_term(selection_regex)
    if not parsed:
        return None
    kind, term, flags = parsed

    if source_expr:
        # A linked source may be any expression (for example ``(str3)`` or
        # ``items[0]``). Keep using it to generate the RHS, but only use it as
        # an assignment-name base when it is actually a legal identifier.
        has_var = source_expr.isidentifier() and not keyword.iskeyword(source_expr)
        suggest_base = source_expr if has_var else "result"
    else:
        if var_and_exp is None:
            return None
        var_name, expr = var_and_exp
        source_expr = var_name if var_name else _wrap_source_expr(expr)
        suggest_base = var_name if var_name else "result"
        has_var = bool(var_name)

    replace_visible = model.get('replace_visible', False)
    replace_text = model.get('replace_text')
    replace_expr = None
    if replace_visible and replace_text:
        replace_expr = _replace_expr_bound(replace_text, 'mtch', source_expr)

    # --- Multi-index: list[int] ---
    if kind == 'expr':
        _eval = eval_in_scope or ast.literal_eval
        try:
            val = _eval(term)
        except Exception:
            val = None
        if _is_list_of_ints(val):
            return {
                'selection_regex': selection_regex,
                'source_expr': source_expr,
                'has_var': has_var,
                'suggest_base': suggest_base,
                'is_index': False, 'is_slice': False,
                'is_multi_index': True,
                'indices_expr': term,
                'replace_visible': replace_visible,
                'replace_text': replace_text,
                'replace_expr': replace_expr,
            }
        if _is_list_of_int_pairs(val):
            return {
                'selection_regex': selection_regex,
                'source_expr': source_expr,
                'has_var': has_var,
                'suggest_base': suggest_base,
                'is_index': False, 'is_slice': False,
                'is_multi_pair_slice': True,
                'pairs_expr': term,
                'replace_visible': replace_visible,
                'replace_text': replace_text,
                'replace_expr': replace_expr,
            }
        if isinstance(val, int) and not isinstance(val, bool):
            is_slice = False
            return {
                'selection_regex': selection_regex,
                'source_expr': source_expr,
                'has_var': has_var,
                'suggest_base': suggest_base,
                'is_index': True,
                'is_slice': False,
                'index_expr': term,
                'slice_start': None, 'slice_stop': None,
                'has_slice_start': False, 'has_slice_stop': False,
                'replace_visible': replace_visible,
                'replace_text': replace_text,
                'replace_expr': replace_expr,
            }

    # --- Slice (including broadcast) ---
    if kind == 'slice':
        slice_start_raw, slice_stop_raw = term
        _eval = eval_in_scope or ast.literal_eval
        start_val = None
        stop_val = None
        try:
            start_val = _eval(slice_start_raw) if slice_start_raw else None
        except Exception:
            pass
        try:
            stop_val = _eval(slice_stop_raw) if slice_stop_raw else None
        except Exception:
            pass
        start_is_list = _is_list_of_ints(start_val)
        stop_is_list = _is_list_of_ints(stop_val)
        if start_is_list or stop_is_list:
            ctx = {
                'selection_regex': selection_regex,
                'source_expr': source_expr,
                'has_var': has_var,
                'suggest_base': suggest_base,
                'is_index': False, 'is_slice': False,
                'is_broadcast_slice': True,
                'has_start_list': start_is_list,
                'has_stop_list': stop_is_list,
                'replace_visible': replace_visible,
                'replace_text': replace_text,
                'replace_expr': replace_expr,
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
            'selection_regex': selection_regex,
            'source_expr': source_expr,
            'has_var': has_var,
            'suggest_base': suggest_base,
            'is_index': False,
            'is_slice': True,
            'index_expr': None,
            'slice_start': slice_start_raw,
            'slice_stop': slice_stop_raw,
            'has_slice_start': bool(slice_start_raw),
            'has_slice_stop': bool(slice_stop_raw),
            'replace_visible': replace_visible,
            'replace_text': replace_text,
            'replace_expr': replace_expr,
        }
    first = '1' in flags
    ci = 'i' in flags
    is_expr = kind in ('string', 'expr')

    regex_pattern = None
    if kind == 'regex':
        if 'c' in flags:
            regex_pattern = term or ""
        else:
            regex_pattern = strip_capturing_groups(term) if term else ""

    return {
        'selection_regex': selection_regex,
        'source_expr': source_expr,
        'has_var': has_var,
        'suggest_base': suggest_base,
        'is_first': first,
        'is_ci': ci,
        'is_expr': is_expr,
        'is_index': False,
        'is_slice': False,
        'expr': term if is_expr else None,
        'regex_pattern': regex_pattern,
        'replace_visible': replace_visible,
        'replace_text': replace_text,
        'replace_expr': replace_expr,
    }


from string_visualizer_grammar import (
    generate_action, generate_copy_expr_for_if, parse_generated_code_or_assignment,
    code_imports, _STATEMENT_ACTIONS,
)


# =============================================================================
# Segment Selection Tool Helpers
# =============================================================================
#
# In segment-selection mode the user clicks chips covering the visible features
# of the FIRST match - its boundary indices, the prefix substring before it,
# its capture groups (or the whole match), and the suffix substring after it.
# Each chip carries a Python expression and toggles into model['selectedSegments'].
# Selections are then assembled into model['replace_text'] with simplifications.
#
# Segment IDs (canonical order, same order used to assemble the Replace box):
#   start   - match start index ($.start())
#   prefix  - substring from string start to match start (str[:$.start()])
#   group_0 - whole match string ($[0]); used when cap groups OFF / single segment
#   group_N - Nth capture group ($[N]); used when cap groups ON
#   suffix  - substring from match end to string end (str[$.end():])
#   end     - match end index ($.end())
#
# Multi-match mode (no '1' flag) wraps each in a list comprehension over
# re.finditer(...). Adjacent string segments concatenate with '+'; otherwise
# selections become a tuple. Indices break adjacency.

# Canonical sort order. group_N entries are placed by index between group_0
# and suffix; this rank function returns a tuple suitable for `sorted(key=...)`.
def _segment_rank(seg_id: str) -> tuple:
    if seg_id == 'start':
        return (0, 0)
    if seg_id == 'prefix':
        return (1, 0)
    if seg_id == 'group_0':
        return (2, 0)
    if seg_id.startswith('group_'):
        try:
            n = int(seg_id[len('group_'):])
        except ValueError:
            return (2, 999)
        return (2, n)  # group_0 sorts first; group_1, group_2... follow
    if seg_id == 'suffix':
        return (3, 0)
    if seg_id == 'end':
        return (4, 0)
    return (5, 0)


def _is_string_segment(seg_id: str) -> bool:
    """True for substring segments (concat-able with '+'); False for indices."""
    return seg_id == 'prefix' or seg_id == 'suffix' or seg_id.startswith('group_')


def _are_segments_adjacent(a: str, b: str, group_ids_in_order: list) -> bool:
    """Are the two string segments visually adjacent inside the value?

    Adjacency forms an undirected graph:
      prefix <-> first_group <-> ... <-> last_group <-> suffix
    where 'first_group' and 'last_group' come from group_ids_in_order
    (which is just ['group_0'] when cap groups are off, otherwise
     ['group_1', 'group_2', ...]).
    """
    if not _is_string_segment(a) or not _is_string_segment(b):
        return False
    if not group_ids_in_order:
        # Without any group, the only adjacency is prefix<->suffix (degenerate).
        return {a, b} == {'prefix', 'suffix'}
    first_g = group_ids_in_order[0]
    last_g = group_ids_in_order[-1]
    if {a, b} == {'prefix', first_g}:
        return True
    if {a, b} == {last_g, 'suffix'}:
        return True
    if a.startswith('group_') and b.startswith('group_'):
        # Adjacent if they appear consecutively in group_ids_in_order.
        try:
            ia = group_ids_in_order.index(a)
            ib = group_ids_in_order.index(b)
        except ValueError:
            return False
        return abs(ia - ib) == 1
    return False


def _segment_expr(seg_id: str, *, source_expr: str, is_first: bool,
                  finditer_call: str | None) -> str:
    """Return the Python expression for a single segment.

    First-match mode (is_first True) treats '$' as the match-object alias.
    Multi-match mode wraps with `[ ... for m in {finditer_call}]` so the
    expression evaluates to a list across all matches.
    """
    if is_first:
        if seg_id == 'start':
            return '$.start()'
        if seg_id == 'end':
            return '$.end()'
        if seg_id == 'prefix':
            return f'{source_expr}[:$.start()]'
        if seg_id == 'suffix':
            return f'{source_expr}[$.end():]'
        if seg_id.startswith('group_'):
            n = seg_id[len('group_'):]
            return f'$[{n}]'
        return seg_id  # unknown -> defensive

    # Multi-match: wrap each per-match expression in a list comprehension.
    # finditer_call is None when we can't build one (no regex_pattern); fall
    # back to first-match expressions in that degenerate case.
    if finditer_call is None:
        return _segment_expr(seg_id, source_expr=source_expr, is_first=True, finditer_call=None)
    if seg_id == 'start':
        per = 'm.start()'
    elif seg_id == 'end':
        per = 'm.end()'
    elif seg_id == 'prefix':
        per = f'{source_expr}[:m.start()]'
    elif seg_id == 'suffix':
        per = f'{source_expr}[m.end():]'
    elif seg_id.startswith('group_'):
        n = seg_id[len('group_'):]
        per = f'm[{n}]'
    else:
        per = seg_id
    return f'[{per} for m in {finditer_call}]'


def _build_finditer_call(ctx: dict | None) -> str | None:
    """Build the re.finditer(...) call used by multi-match segment expressions.

    Returns None for index/slice searches or when no usable pattern exists.
    """
    if not ctx:
        return None
    if ctx.get('is_index') or ctx.get('is_slice') or ctx.get('is_multi_index'):
        return None
    src = ctx.get('source_expr', '')
    pat = ctx.get('regex_pattern')
    if pat is None:
        # String/expr search - use the re.escape() form so the call still
        # produces match objects with .start()/.end() (no capture groups, but
        # group_0 / start / end / prefix / suffix all still make sense).
        # Spelled exactly as the grammar's ExprFinditer spells it, so a chip
        # dragged out here reads the same as generated Map Matches code: no
        # re.M (an escaped literal has no anchors for it to mean anything to).
        if ctx.get('is_expr') and ctx.get('expr'):
            esc = f"re.escape({ctx['expr']})"
        else:
            return None
        flags = ', flags=re.I' if ctx.get('is_ci') else ''
        return f"re.finditer({esc}, {src}{flags})"
    flags = 're.M|re.I' if ctx.get('is_ci') else 're.M'
    return f"re.finditer(r'{pat}', {src}, flags={flags})"


def _segment_group_ids_in_order(model: dict, value: str, eval_in_scope) -> list:
    """Return the canonical list of group segment IDs available in the search.

    With capture groups OFF (or no regex), only ['group_0'] is available.
    With capture groups ON, returns ['group_1', 'group_2', ...] for each
    capture group in the regex.
    """
    selection_regex = model.get('search')
    if not selection_regex or not is_regex_search(selection_regex):
        return ['group_0']
    if not is_capture_groups_mode(selection_regex):
        return ['group_0']
    inner = get_regex_inner_pattern(selection_regex) or ''
    try:
        n = len(parse_all_segments(inner))
    except Exception:
        n = 0
    if n <= 0:
        return ['group_0']
    return [f'group_{i}' for i in range(1, n + 1)]


def _segment_chip_html(seg_id: str, expr: str, label: str, *,
                       position: str = 'start', selected: bool = False) -> str:
    """Render a clickable chip for one segment (start/end index label).

    The chip carries:
      - snc-mouse-down="SegmentToggle(segment_id=...)" so a click toggles
        the selection in the visualizer model.
      - snc-py-exps="[{"expr": ...}]" so the existing tooltip/drag plumbing
        can pick the chip up as a draggable expression source.
      - label text (typically the numeric index, e.g. '6' or '11').
      - .selected CSS class when the segment is in model['selectedSegments'].

    position='start' positions the chip at the left edge of its anchor (used
    for the match-start label, which is inserted BEFORE the first match char).
    position='end' positions it at the right edge (used for the match-end
    label, which is inserted AFTER the last match char so the anchor sits at
    the right edge of the segment).
    """
    event = repr(SegmentToggle(segment_id=seg_id))
    cls = f'segment-chip pos-{position}'
    if selected:
        cls += ' selected'
    return (
        f'<span class="segment-label-anchor segment-chip-anchor">'
        f'<span class="{cls}" '
        f'snc-mouse-down="{html.escape(event)}"'
        f'{py_exp_attrs(expr)}>{html.escape(label)}</span>'
        f'</span>'
    )


def _segment_context_for_index_slice(selection_regex: str, source_expr: str,
                                      value: str, eval_in_scope) -> dict | None:
    """Build a segment-expression context for an index or slice search.

    Index/slice searches don't have a match object, so the expressions use
    the literal slice / index parts the user typed (e.g. '2', '7') wrapped
    around the source variable. Returns None for unsupported variants
    (multi-index, broadcast slice, etc.).
    """
    parsed = parse_search_term(selection_regex)
    if not parsed:
        return None
    kind, term, _flags = parsed

    if kind == 'slice':
        left, right = term
        try:
            start_v = eval_in_scope(left) if left else 0
            stop_v = eval_in_scope(right) if right else len(value)
        except Exception:
            return None
        if (not isinstance(start_v, int) or isinstance(start_v, bool)
                or not isinstance(stop_v, int) or isinstance(stop_v, bool)):
            return None  # broadcast / non-int slice - not yet supported
        # Normalize negative bounds for the suffix/prefix expressions: they
        # render in absolute terms (str[N:]), so we keep the user's literal
        # text but resolve to a positive int for the boundary positions.
        start_expr = left if left else '0'
        end_expr = right if right else f'len({source_expr})'
        return {
            'is_index_slice': True,
            'start_expr': start_expr,
            'end_expr': end_expr,
            'group_0': (f'{source_expr}[{start_expr}:{end_expr}]'
                        if right else f'{source_expr}[{start_expr}:]'),
        }

    if kind == 'expr':
        try:
            idx_v = eval_in_scope(term)
        except Exception:
            return None
        if not isinstance(idx_v, int) or isinstance(idx_v, bool):
            return None  # multi-index, list-of-pairs, etc - not yet supported
        # For single index, the "end" is just-past the picked char.
        start_expr = term
        end_expr = f'{term}+1'
        return {
            'is_index_slice': True,
            'start_expr': start_expr,
            'end_expr': end_expr,
            'group_0': f'{source_expr}[{start_expr}]',
        }

    return None


def _get_segment_expressions(model: dict, value: str, eval_in_scope,
                              var_and_exp=None) -> dict | None:
    """Return the segment-id -> Python expression mappings used everywhere.

    Returns TWO sets of expressions because they intentionally differ:
      - 'replace_exprs' (drives model['replace_text']):
        ALWAYS the first-match flavor ($.start(), $[1], ...). Action buttons
        like Loop / Map Matches wrap this into the all-matches form, so
        building list comprehensions here would just double-wrap.
      - 'chip_exprs' (drives snc-py-exps on chips and segment chars):
        Multi-match list-comprehension form when the search has no '1' flag,
        so DRAGGING a chip out of the visualizer (or hovering its tooltip)
        gives a self-contained, fully-evaluable expression. With '1' on, it
        matches the replace_exprs.

    Index/slice searches always have a single match, so chip_exprs == replace_exprs.

    The two sets also differ in how they name the SOURCE string. chip_exprs use
    the concrete access path (`rows[0].name`) so a dragged-out expression stands
    on its own; replace_exprs use the display form, which for a nested cell is
    `$$` - one scope out from the `$` bound to the match (see
    _display_source_expr). At the top level the two coincide.

    Returns dict:
      {
        'source_expr': str,
        'is_index_slice': bool,
        'replace_exprs': {seg_id: str},
        'chip_exprs':    {seg_id: str},
        'simplifications': {  # for _build_segment_replace_text
          'full': str,        # entire string (always == source)
          'tail': str,        # group_0 + suffix coverage
          'head': str,        # prefix + group_0 coverage
        },
      }
    Returns None when no search or no usable info.
    """
    selection_regex = model.get('search')
    if not selection_regex:
        return None

    if var_and_exp is None and model.get('_source_expr'):
        s = model.get('_source_expr')
        var_and_exp = (s, s)
    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope) if var_and_exp else None
    source_expr = (ctx['source_expr'] if ctx
                   else (var_and_exp[0] if var_and_exp and var_and_exp[0] else 'str'))
    display_expr = _display_source_expr(source_expr)

    # Index / slice path: single match, so chip and replace expressions differ
    # only in how they name the source.
    if is_index_or_slice_search(selection_regex, eval_in_scope):
        def _idx_exprs(src):
            idx_ctx = _segment_context_for_index_slice(
                selection_regex, src, value, eval_in_scope)
            if not idx_ctx:
                return None
            start_expr = idx_ctx['start_expr']
            end_expr = idx_ctx['end_expr']
            return idx_ctx, {
                'start': start_expr,
                'end': end_expr,
                'prefix': f'{src}[:{start_expr}]',
                'group_0': idx_ctx['group_0'],
                'suffix': f'{src}[{end_expr}:]',
            }

        chip = _idx_exprs(source_expr)
        replace = _idx_exprs(display_expr)
        if not chip or not replace:
            return None
        _, chip_exprs = chip
        # The simplifications land in replace_text, so they use the display
        # source throughout - including an open-ended slice's len(<source>).
        display_idx_ctx, replace_exprs = replace
        start_expr = display_idx_ctx['start_expr']
        end_expr = display_idx_ctx['end_expr']
        return {
            'source_expr': source_expr,
            'is_index_slice': True,
            'replace_exprs': replace_exprs,
            'chip_exprs': chip_exprs,
            'simplifications': {
                'full': display_expr,
                'tail': f'{display_expr}[{start_expr}:]',
                'head': f'{display_expr}[:{end_expr}]',
            },
        }

    # Regex / string path. Replace exprs always use first-match flavor.
    replace_exprs = {
        'start': '$.start()',
        'end': '$.end()',
        'prefix': f'{display_expr}[:$.start()]',
        'group_0': '$[0]',
        'suffix': f'{display_expr}[$.end():]',
    }

    # Chip exprs match Replace exprs when the user is in 1st-mode. Otherwise
    # wrap each per-match expression in [... for m in re.finditer(...)] so a
    # dragged-out expression evaluates to the list across all matches.
    is_first = is_first_match_mode(selection_regex)
    first_match_chip_exprs = {**replace_exprs,
                              'prefix': f'{source_expr}[:$.start()]',
                              'suffix': f'{source_expr}[$.end():]'}
    if is_first:
        chip_exprs = first_match_chip_exprs
    else:
        finditer_call = _build_finditer_call(ctx) if ctx else None
        if finditer_call is None:
            # No usable finditer call (e.g. no source_expr context); fall back
            # to first-match form so chips still produce something draggable.
            chip_exprs = first_match_chip_exprs
        else:
            chip_exprs = {
                'start':   f'[m.start() for m in {finditer_call}]',
                'end':     f'[m.end() for m in {finditer_call}]',
                'prefix':  f'[{source_expr}[:m.start()] for m in {finditer_call}]',
                'group_0': f'[m[0] for m in {finditer_call}]',
                'suffix':  f'[{source_expr}[m.end():] for m in {finditer_call}]',
            }

    return {
        'source_expr': source_expr,
        'is_index_slice': False,
        'replace_exprs': replace_exprs,
        'chip_exprs': chip_exprs,
        'simplifications': {
            'full': display_expr,
            'tail': f'{display_expr}[$.start():]',
            'head': f'{display_expr}[:$.end()]',
        },
    }


def _segment_id_to_replace_expression(seg_id: str, seg_ctx: dict) -> str:
    """Resolve segment ID -> Python expression for the Replace box (first-match).

    Handles the dynamic group_N case (capture groups beyond group_0).
    """
    exprs = seg_ctx.get('replace_exprs', {})
    if seg_id in exprs:
        return exprs[seg_id]
    if seg_id.startswith('group_') and not seg_ctx.get('is_index_slice'):
        n = seg_id[len('group_'):]
        return f'$[{n}]'
    return seg_id


def _segment_id_to_chip_expression(seg_id: str, seg_ctx: dict, value: str,
                                    eval_in_scope) -> str:
    """Resolve segment ID -> Python expression for snc-py-exps (multi-match
    list-comp form when applicable; first-match form otherwise).

    Handles the dynamic group_N case.
    """
    exprs = seg_ctx.get('chip_exprs', {})
    if seg_id in exprs:
        return exprs[seg_id]
    if seg_id.startswith('group_') and not seg_ctx.get('is_index_slice'):
        n = seg_id[len('group_'):]
        # Need to wrap in list-comp for multi-match mode if applicable.
        # Look at any other chip_expr to determine which mode we're in.
        any_chip_expr = next(iter(exprs.values()), '')
        if 'for m in re.finditer' in any_chip_expr:
            # Recover the finditer call from another chip expression.
            i = any_chip_expr.find('for m in ')
            if i >= 0:
                rest = any_chip_expr[i + len('for m in '):]
                # Strip trailing ']'.
                if rest.endswith(']'):
                    finditer_call = rest[:-1]
                    return f'[m[{n}] for m in {finditer_call}]'
        return f'$[{n}]'
    return seg_id


def _compute_segment_overlays(value: str, model: dict, eval_in_scope) -> dict | None:
    """Compute the segment-mode rendering plan for the FIRST match.

    Returns a dict with:
      - 'highlights': list of (start, end, seg_type, pat_str, rep, seg_idx)
                      tuples replacing the normal highlights. seg_type is one
                      of 'segment-region' (prefix/suffix) or 'segment-group'
                      (capture group / whole match). pat_str carries the
                      segment_id so char_span_els can attach the right
                      SegmentToggle handler.
      - 'chips_by_index': {internal_idx: [chip_html, ...]} for inline chips
                          (used for the start/end index labels which aren't
                          part of any region highlight).
      - 'selected_segment_ids': set of selected segment IDs (drives the
                                .segment-selected class via char_span_els).

    Returns None when there's no usable search or no match.
    """
    selection_regex = model.get('search')
    if not selection_regex or not value:
        return None

    seg_ctx = _get_segment_expressions(model, value, eval_in_scope)
    if not seg_ctx:
        return None
    source_expr = seg_ctx['source_expr']
    is_index_slice = seg_ctx['is_index_slice']

    # Get all highlights for the search, then filter to the first match.
    highlights = parse_regex_for_highlighting(selection_regex, value, eval_in_scope) if value else []
    if is_index_slice or is_literal_string_search(selection_regex, eval_in_scope):
        # Index/slice produces 'slice' seg_type highlights and a literal string
        # search produces 'literal' ones, both display-only (segment_index is
        # None) and one per match. Take the first one as the "match" - other
        # matches (multi-index, broadcast) are intentionally hidden by segment
        # mode (see fix Q1 in plan).
        primary = highlights[:1] if highlights else []
    else:
        primary = [h for h in highlights if h[5] is not None]
    if not primary:
        return None

    # Compute the first match's overall span from its primary segments.
    match_start_internal = min(h[0] for h in primary)
    match_end_internal = max(h[1] for h in primary)
    end_of_string_internal = compute_internal_length(value)
    # Internal index 0 is the visible '^' anchor; the actual content starts at 1.
    string_start_internal = 1
    # Suffix region ends just before the trailing '$' anchor (which is at
    # end_of_string_internal - 1). Allow it to be empty when match is at end.
    suffix_end_internal = end_of_string_internal - 1

    # Compute the match's start/end as STRING indices (not internal) so the
    # chip labels can show the actual numeric position (e.g. "6" / "11" for
    # /world/ matching "hello world"). Reuse the internal->string mapping.
    internal_to_string = build_internal_to_string_mapping(value)
    def _string_idx_at(internal_idx: int) -> int:
        if 0 <= internal_idx < len(internal_to_string):
            return internal_to_string[internal_idx]
        return len(value)
    match_start_string_idx = _string_idx_at(match_start_internal)
    if match_end_internal - 1 >= 0 and match_end_internal - 1 < len(internal_to_string):
        match_end_string_idx = internal_to_string[match_end_internal - 1] + 1
    else:
        match_end_string_idx = len(value)

    selected_set = set(model.get('selectedSegments') or [])

    # Decide which group IDs are interactive: for regex with cap groups on,
    # each capture group (including a lone group_1) gets its own chip.
    # Otherwise the whole match is one 'group_0' chip. Index/slice searches
    # never have capture groups.
    cap_groups_on = (not is_index_slice
                     and is_capture_groups_mode(selection_regex)
                     and is_regex_search(selection_regex))
    per_group_mode = cap_groups_on and len(primary) >= 1

    def _chip_expr_for(seg_id: str) -> str:
        return _segment_id_to_chip_expression(seg_id, seg_ctx, value, eval_in_scope)

    new_highlights: list = []

    # Prefix region (string start to match start). Empty if match starts at 0.
    if match_start_internal > string_start_internal:
        prefix_seg_id = 'prefix'
        new_highlights.append((
            string_start_internal, match_start_internal,
            'segment-region', f"{prefix_seg_id}|{_chip_expr_for(prefix_seg_id)}|pre",
            (1, 1), -1))

    # Match: either each capture group (per_group_mode) or the whole match.
    if per_group_mode:
        for h in primary:
            start, end, seg_type, _pat, _rep, seg_idx = h
            seg_id = f'group_{seg_idx + 1}'  # segment_index is 0-based, group_N is 1-based
            new_highlights.append((
                start, end, 'segment-group',
                f"{seg_id}|{_chip_expr_for(seg_id)}|$[{seg_idx + 1}]",
                (1, 1), seg_idx))
    else:
        seg_id = 'group_0'
        new_highlights.append((
            match_start_internal, match_end_internal,
            'segment-group',
            f"{seg_id}|{_chip_expr_for(seg_id)}|$[0]",
            (1, 1), 0))

    # Suffix region (match end to string end). Empty if match ends at string end.
    if suffix_end_internal > match_end_internal:
        seg_id = 'suffix'
        new_highlights.append((
            match_end_internal, suffix_end_internal,
            'segment-region', f"{seg_id}|{_chip_expr_for(seg_id)}|post",
            (1, 1), -1))

    # start/end index chips: rendered as standalone inline chips at the match
    # boundaries. Chip LABELS show the numeric position of the first match
    # (e.g. "6" / "11"); snc-py-exps carries the actual expression ($.start()
    # in 1st mode, list-comp otherwise). The start chip is inserted BEFORE
    # the match's first char so it floats over the left edge; the end chip
    # is inserted AFTER the match's last char so it floats over the right edge.
    chips_before_index: dict = {}
    chips_after_index: dict = {}
    start_chip = _segment_chip_html(
        'start', _chip_expr_for('start'),
        str(match_start_string_idx),
        position='start', selected=('start' in selected_set))
    end_chip = _segment_chip_html(
        'end', _chip_expr_for('end'),
        str(match_end_string_idx),
        position='end', selected=('end' in selected_set))
    chips_before_index.setdefault(match_start_internal, []).append(start_chip)
    chips_after_index.setdefault(match_end_internal - 1, []).append(end_chip)

    return {
        'highlights': new_highlights,
        'chips_by_index': chips_before_index,
        'chips_after_by_index': chips_after_index,
        'selected_segment_ids': selected_set,
    }


def _chip_label(seg_id: str, source_expr: str, is_first: bool) -> str:
    """Short, human-readable label for a segment chip.

    Kept minimal so chips don't visually dominate the visualization. The full
    expression is still available via snc-py-exps / drag.
    """
    if seg_id == 'start':
        return 'start'
    if seg_id == 'end':
        return 'end'
    if seg_id == 'prefix':
        return 'pre'
    if seg_id == 'suffix':
        return 'post'
    if seg_id.startswith('group_'):
        n = seg_id[len('group_'):]
        return f'$[{n}]'
    return seg_id


def _build_segment_replace_text(model: dict, var_and_exp, value: str,
                                eval_in_scope) -> str | None:
    """Assemble model['replace_text'] from model['selectedSegments'].

    Applies these simplifications (in order):
      1. All capture groups (group_1..N) selected   -> collapse to group_0.
      2. {prefix, group_0, suffix} selected         -> emit '<src>'.
      3. {group_0, suffix} selected                 -> emit tail-slice.
      4. {prefix, group_0} selected                 -> emit head-slice.

    The exact tail/head slice expressions vary based on search type:
      - regex first-match : '<src>[$.start():]' / '<src>[:$.end()]'
      - index/slice       : '<src>[<start_expr>:]' / '<src>[:<end_expr>]'

    After simplification, the remaining string segments become a single concat
    expression (joined with ' + ') if they're all mutually adjacent, otherwise
    the entire result is a tuple. Indices ('start' / 'end') always break
    adjacency, so any selection containing them produces a tuple.

    Returns None when no segments are selected.
    """
    selected = list(model.get('selectedSegments') or [])
    if not selected:
        return None

    seg_ctx = _get_segment_expressions(model, value, eval_in_scope, var_and_exp)
    if not seg_ctx:
        # Fall back to a minimal context so we can at least produce something.
        source_expr = (var_and_exp[0] if var_and_exp and var_and_exp[0] else 'str')
        seg_ctx = {
            'source_expr': source_expr,
            'is_index_slice': False,
            'replace_exprs': {},
            'chip_exprs': {},
            'simplifications': {
                'full': source_expr,
                'tail': f'{source_expr}[$.start():]',
                'head': f'{source_expr}[:$.end()]',
            },
        }

    source_expr = seg_ctx['source_expr']
    simpl = seg_ctx['simplifications']
    group_ids_in_order = _segment_group_ids_in_order(model, value, eval_in_scope)

    sel_set = set(selected)

    # Simplification 1: all groups -> group_0 (only meaningful when cap groups
    # are on AND the regex has at least 2 groups - selecting the only group
    # in a single-group regex should remain $[1]).
    if (len(group_ids_in_order) >= 2
            and group_ids_in_order != ['group_0']
            and all(g in sel_set for g in group_ids_in_order)):
        sel_set -= set(group_ids_in_order)
        sel_set.add('group_0')

    has_g0_or_all_groups = 'group_0' in sel_set

    # Simplifications 2-4 collapse adjacent string segments into a single
    # slice expression (regex: $.start()/$.end(); index/slice: literal bounds).
    if has_g0_or_all_groups:
        if {'prefix', 'group_0', 'suffix'} <= sel_set:
            sel_set -= {'prefix', 'group_0', 'suffix'}
            sel_set.add('__full__')
        elif {'group_0', 'suffix'} <= sel_set:
            sel_set -= {'group_0', 'suffix'}
            sel_set.add('__tail__')
        elif {'prefix', 'group_0'} <= sel_set:
            sel_set -= {'prefix', 'group_0'}
            sel_set.add('__head__')

    SPECIAL_EXPRS = {
        '__full__': simpl['full'],
        '__head__': simpl['head'],
        '__tail__': simpl['tail'],
    }

    # Order remaining items: real segments by canonical rank, specials stay
    # where group_0 would have been (rank 2).
    def _rank(s):
        if s in SPECIAL_EXPRS:
            return (2, 0)
        return _segment_rank(s)

    ordered = sorted(sel_set, key=_rank)

    # Build (id, expr, is_string) tuples in order.
    items = []
    for s in ordered:
        if s in SPECIAL_EXPRS:
            items.append((s, SPECIAL_EXPRS[s], True))
        else:
            expr = _segment_id_to_replace_expression(s, seg_ctx)
            items.append((s, expr, _is_string_segment(s)))

    # Single item: emit bare expression.
    if len(items) == 1:
        return items[0][1]

    # Build adjacency for "concat with +".
    all_strings = all(is_str for _, _, is_str in items)
    if all_strings:
        # Are all consecutive pairs adjacent?
        all_adjacent = True
        for (a, _, _), (b, _, _) in zip(items, items[1:]):
            # Treat specials as adjacent to their neighbors.
            ax = a if a not in SPECIAL_EXPRS else 'group_0'
            bx = b if b not in SPECIAL_EXPRS else 'group_0'
            if not _are_segments_adjacent(ax, bx, group_ids_in_order):
                all_adjacent = False
                break
        if all_adjacent:
            return ' + '.join(expr for _, expr, _ in items)

    # Fallback: tuple.
    return '(' + ', '.join(expr for _, expr, _ in items) + ')'


def update(event, var_and_exp, model: dict, value: str, get_visualizer=None, eval_in_scope=None) -> Tuple[dict, List[Any]]:
    """
    Update model based on event. Returns (new_model, commands) tuple.

    Args:
        event: The UI event to process
        var_and_exp: (var_name | None, expression) tuple from the source line
        model: The current model state
        value: The string value being visualized

    Commands are actions for VS Code to execute, like NewCode to update the file.
    """
    commands: List[Any] = []

    # Event should have pythonEventStr and eventJSON
    if event is None or event.get('pythonEventStr', '') == '' or event.get('eventJSON', '') == '':
        return (model, commands)
    if model is None:
        model = init_model(value, get_visualizer=get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp)

    make_python_event = eval(event['pythonEventStr'])
    event_json = event['eventJSON']
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event
    model['_scroll_to_match'] = False

    match msg:
        case HandleMouseDown(segment_index=seg_idx, side=side):
            # Start a handle drag on a literal segment edge
            model['handleDrag'] = {
                'segmentIndex': seg_idx,
                'side': side,
                'cursorIdx': None,  # Will be set on first MouseMove
            }
            # Clear any normal drag state
            model['dragging'] = False
            model['anchorIdx'] = None
            model['cursorIdx'] = None
            _commit_open_dropdown_edit(model)
            model['openDropdown'] = None

        case MouseDown(index=idx):
            # If a dropdown was open, treat this click like a "click outside
            # the modal": commit any buffered edit, dismiss the dropdown, and
            # do NOT also start a new selection (which would just wipe the
            # change the user was editing).
            if model.get('openDropdown') is not None:
                _commit_open_dropdown_edit(model)
                model['openDropdown'] = None
                return (model, commands)
            # Cancel any handle drag
            model['handleDrag'] = None
            # Clear hover preview (actual selection takes over)
            model['hoverIdx'] = None

            # Determine selection type from active tool + modifier overrides
            anchor_type = _resolve_selection_type(model, event_json)

            # Index mode is always a fresh slice selection - never extends an
            # existing regex selection (slices and regexes don't compose).
            if anchor_type == 'index':
                if not isinstance(idx, int):
                    return (model, commands)
                saved_linked = (model.get('linked_action'), model.get('linked_source_expr'))
                saved_tool = model.get('tool', 'literal')
                saved_expanded = model.get('expanded', False)
                model = init_model(value, get_visualizer=get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp)
                model['linked_action'], model['linked_source_expr'] = saved_linked
                model['tool'] = saved_tool
                model['expanded'] = saved_expanded
                model['anchorIdx'] = idx
                model['anchorType'] = 'index'
                model['cursorIdx'] = idx
                model['extendDirection'] = None
                model['dragging'] = True
                return (model, commands)

            selection_regex = model.get('search')

            # Check extension points if we have an existing selection
            last_end: int | None = None
            first_start: int | None = None
            fuzzy_info: dict | None = None
            if selection_regex and isinstance(idx, int):
                last_end = get_last_segment_end_internal_idx(selection_regex, value)
                first_start = get_first_segment_start_internal_idx(selection_regex, value)
                fuzzy_info = find_fuzzy_segment_at_index(selection_regex, value, idx)

            # Check if extending from the right (end of last segment)
            # Uses broader adjacency: allows skipping over visible anchor chars ($, ^)
            if last_end is not None and isinstance(idx, int) and is_adjacent_right(idx, last_end, value):
                # Keep existing regex, start new segment from where user clicked
                # (not from last_end, to avoid including skipped anchors in the segment)
                model['anchorIdx'] = idx
                model['anchorType'] = anchor_type
                model['cursorIdx'] = idx
                model['extendDirection'] = 'right'
                model['insertAfterSegment'] = None  # Not inserting at specific position
            # Check if extending from the left (near the start of first segment)
            # Uses broader adjacency: allows skipping over anchor chars
            elif first_start is not None and isinstance(idx, int) and is_adjacent_left(idx, first_start, value):
                # Keep existing regex, start new segment extending left from first
                # Anchor at first_start so the selection can span from cursor (first_start-1) to anchor
                model['anchorIdx'] = first_start
                model['anchorType'] = anchor_type
                model['cursorIdx'] = idx
                model['extendDirection'] = 'left'
                model['insertAfterSegment'] = None  # Not inserting at specific position
            # Check if clicking inside a fuzzy segment (to split it)
            elif fuzzy_info is not None and isinstance(idx, int):
                # Allow starting a new segment inside the fuzzy region
                # This will constrain/split the fuzzy match
                # Track which segment we clicked inside so we can insert after it
                model['anchorIdx'] = idx
                model['anchorType'] = anchor_type
                model['cursorIdx'] = idx
                model['extendDirection'] = None  # Not a simple left/right extend
                model['insertAfterSegment'] = fuzzy_info['segment_index']  # Insert after this segment
            else:
                # Fresh start: reset selection, preserving linked-editing state,
                # search flags, active tool, and expand/collapse chrome.
                saved_linked = (model.get('linked_action'), model.get('linked_source_expr'))
                saved_flags = get_search_flags(model.get('search'))
                saved_tool = model.get('tool', 'literal')
                saved_expanded = model.get('expanded', False)
                model = init_model(value, get_visualizer=get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp)
                model['linked_action'], model['linked_source_expr'] = saved_linked
                model['tool'] = saved_tool
                model['expanded'] = saved_expanded
                if saved_flags:
                    model['search'] = '``' + saved_flags
                if isinstance(idx, int):
                    model['anchorIdx'] = idx
                    model['anchorType'] = anchor_type
                    model['cursorIdx'] = idx
                model['extendDirection'] = None

            model['dragging'] = True

        case MouseMove(index=idx):
            if model.get('handleDrag') is not None:
                # Handle drag mode: update cursor position on the drag handle
                if event_json.get('buttons') == 0:
                    # Mouse released outside widget - finalize handle drag
                    model = finalize_handle_drag(model, value)
                else:
                    model['handleDrag']['cursorIdx'] = idx
            elif event_json.get('buttons') == 0:  # No mouse button held
                model = finalize_segment(model, value)
                # Update hover preview state from active tool + modifier overrides.
                # Index tool: no hover preview since clicking does nothing.
                if _resolve_selection_type(model, event_json) == 'index':
                    model['hoverIdx'] = None
                else:
                    model['hoverIdx'] = idx
            elif model.get('dragging'):
                model['cursorIdx'] = idx

        case MouseUp(index=idx):
            if model.get('handleDrag') is not None:
                # Finalize handle drag
                model['handleDrag']['cursorIdx'] = idx
                model = finalize_handle_drag(model, value)
            elif model.get('dragging'):
                model['cursorIdx'] = idx
                model = finalize_segment(model, value)

        case KeyDown():
            key = event_json.get('key')
            meta_key = event_json.get('metaKey', False)
            shift_key = event_json.get('shiftKey', False)

            if key == 'Enter':
                if model.get('openDropdown'):
                    # Enter on an open dropdown: commit buffered edits, close.
                    _commit_open_dropdown_edit(model)
                    model['openDropdown'] = None
                elif model.get('linked_action'):
                    model['linked_action'] = 'find_or_map'
                else:
                    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                    if ctx:
                        result = generate_action('find_or_map', ctx)
                        if result:
                            commands.append(new_code_command(result, code_imports))

            elif key == 'Backspace' and meta_key:
                if model.get('openDropdown'):
                    _commit_open_dropdown_edit(model)
                    model['openDropdown'] = None
                # Same gating as the Delete action button: Pick mode and an
                # open Replace box both indicate the user is composing
                # something else; firing Delete would discard that work.
                elif model.get('tool') == 'pick' or model.get('replace_visible'):
                    pass
                elif model.get('linked_action'):
                    model['linked_action'] = 'delete'
                else:
                    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                    if ctx:
                        result = generate_action('delete', ctx)
                        if result:
                            commands.append(new_code_command(result, code_imports))

            elif key == 'r' and meta_key:
                if model.get('linked_action'):
                    model['linked_action'] = 'replace'
                else:
                    ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                    if ctx:
                        result = generate_action('replace', ctx)
                        if result:
                            commands.append(new_code_command(result, code_imports))

            elif key == 'Escape':
                # Close dropdown if open, otherwise clear selections
                if model.get('openDropdown'):
                    model['openDropdown'] = None
                else:
                    # Clear all selections (save to undo first so it's recoverable)
                    current_regex = model.get('search')
                    if current_regex or model.get('anchorIdx') is not None:
                        model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
                        model['redoHistory'] = []
                    model['search'] = None
                    model['anchorIdx'] = None
                    model['cursorIdx'] = None
                    model['dragging'] = False
                    model['insertAfterSegment'] = None

            elif key == 'z' and meta_key and not shift_key:
                # Cmd-Z: Undo
                undo_history = model.get('undoHistory', [])
                if undo_history:
                    # Push current to redo
                    model['redoHistory'] = model.get('redoHistory', []) + [model.get('search')]
                    # Pop from undo
                    model['search'] = undo_history[-1]
                    model['undoHistory'] = undo_history[:-1]
                    # Clear any in-progress selection
                    model['anchorIdx'] = None
                    model['cursorIdx'] = None
                    model['dragging'] = False
                    model['insertAfterSegment'] = None

            elif key == 'z' and meta_key and shift_key:
                # Cmd-Shift-Z: Redo
                redo_history = model.get('redoHistory', [])
                if redo_history:
                    # Push current to undo
                    model['undoHistory'] = model.get('undoHistory', []) + [model.get('search')]
                    # Pop from redo
                    model['search'] = redo_history[-1]
                    model['redoHistory'] = redo_history[:-1]
                    # Clear any in-progress selection
                    model['anchorIdx'] = None
                    model['cursorIdx'] = None
                    model['dragging'] = False
                    model['insertAfterSegment'] = None

        case DropdownToggle(dropdown_id=did):
            # Toggle dropdown open/closed - committing buffered edits in either
            # case (re-clicking the same trigger commits + closes; switching to
            # a different dropdown commits the old one before opening the new).
            open_dropdown = model.get('openDropdown')
            if open_dropdown and open_dropdown.get('id') == did:
                _commit_open_dropdown_edit(model)
                model['openDropdown'] = None
            else:
                if open_dropdown:
                    _commit_open_dropdown_edit(model)
                # Open this dropdown, extract segment index from ID
                # ID format: "fuzzy-pattern-{segment_index}", "repetition-{segment_index}"
                # or "slice-label-{start|end|center}".
                parts = did.split('-')
                segment_index = int(parts[-1]) if parts[-1].isdigit() else 0
                dropdown_state = {'id': did, 'segmentIndex': segment_index}

                # For repetition dropdowns, seed text field values from the
                # segment's current quantifier so the dropdown opens prefilled
                # ({3} -> exactN='3', {2,5} -> rangeMin/Max='2'/'5', etc.).
                # Simple quantifiers (1/?/*/+) leave fields empty - the
                # matching simple option is shown via .selected instead.
                if did.startswith('repetition-'):
                    exact_n, range_min, range_max = '', '', ''
                    try:
                        highlights = parse_regex_for_highlighting(model.get('search'), value)
                        if 0 <= segment_index < len(highlights):
                            _, _, _, _, (mn, mx), _ = highlights[segment_index]
                            exact_n, range_min, range_max = _quantifier_to_prefill(mn, mx)
                    except Exception:
                        pass
                    dropdown_state['exactN'] = exact_n
                    dropdown_state['rangeMin'] = range_min
                    dropdown_state['rangeMax'] = range_max

                # For slice-label edit popups, seed the input value with the
                # current side's raw expression text.
                #   slice-label-start  -> left of slice (or '' if elided)
                #   slice-label-end    -> right of slice (or '' if elided)
                #   slice-label-center -> the bare-index expression as-is
                if did.startswith('slice-label-'):
                    side = did[len('slice-label-'):]
                    dropdown_state['side'] = side
                    seeded = ''
                    search = model.get('search') or ''
                    if side == 'center':
                        seeded = search
                    else:
                        parts = parse_slice_parts(search)
                        if parts is not None:
                            left, right = parts
                            seeded = left if side == 'start' else right
                    dropdown_state['value'] = seeded

                model['openDropdown'] = dropdown_state

        case DropdownSelect(dropdown_id=did, option_value=option):
            # Select an option from a dropdown
            open_dropdown = model.get('openDropdown')
            if open_dropdown and open_dropdown.get('id') == did:
                segment_index = open_dropdown.get('segmentIndex', 0)
                current_regex = model.get('search')
                if current_regex:
                    # Save to undo history
                    model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
                    model['redoHistory'] = []

                    if did.startswith('fuzzy-pattern-'):
                        # Fuzzy pattern dropdown: option is a character class
                        model['search'] = replace_segment_pattern(
                            current_regex, segment_index, option)
                    else:
                        # Repetition dropdown: option is a quantifier ('1', '?', '*', '+')
                        new_quantifier = '' if option == '1' else option
                        model['search'] = replace_segment_repetition(
                            current_regex, segment_index, new_quantifier)
            # Close the dropdown
            model['openDropdown'] = None

        case RepetitionInput(dropdown_id=did, field=field, value=val):
            # Buffer the typed value into openDropdown state. The actual regex
            # update happens on commit (when the dropdown closes), so a
            # transient invalid value never makes the segment disappear.
            open_dropdown = model.get('openDropdown')
            if open_dropdown and open_dropdown.get('id') == did:
                if field == 'exact':
                    open_dropdown['exactN'] = val
                elif field == 'min':
                    open_dropdown['rangeMin'] = val
                elif field == 'max':
                    open_dropdown['rangeMax'] = val

        case SliceLabelInput(side=side, value=val):
            # Buffer the typed expression into openDropdown state. The slice
            # is rewritten on commit (close), not on each keystroke.
            open_dropdown = model.get('openDropdown')
            expected_id = f'slice-label-{side}'
            if open_dropdown and open_dropdown.get('id') == expected_id:
                open_dropdown['value'] = val

        case FirstMatchToggle():
            current_regex = model.get('search')
            new_regex = _toggle_search_flag(current_regex or '``', '1')
            if _is_flags_only(new_regex) and not get_search_flags(new_regex):
                new_regex = None
            model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
            model['redoHistory'] = []
            model['search'] = new_regex

        case CaseSensitiveToggle():
            current_regex = model.get('search')
            new_regex = _toggle_search_flag(current_regex or '``', 'i')
            if _is_flags_only(new_regex) and not get_search_flags(new_regex):
                new_regex = None
            model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
            model['redoHistory'] = []
            model['search'] = new_regex

        case CaptureGroupsToggle():
            current_regex = model.get('search')
            if current_regex:
                new_regex = _toggle_search_flag(current_regex, 'c')
                turning_on = 'c' in get_search_flags(new_regex)
                if turning_on:
                    new_regex = ensure_all_groups(new_regex)
                else:
                    inner = get_regex_inner_pattern(new_regex)
                    flags = get_search_flags(new_regex)
                    if inner and is_regex_search(new_regex):
                        new_regex = canonicalize_regex(make_regex_search(inner, flags))
                model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
                model['redoHistory'] = []
                model['search'] = new_regex

        case SearchBoxInput(value=val):
            # Update search directly from search box input.
            # The value includes delimiters - regex uses Python raw-string form
            # (r'pattern', r"pattern", r'''pattern''', r"""pattern"""), strings
            # use quoted literals ('hello', "hello"), and slice expressions use
            # colon syntax (5:10).
            current_regex = model.get('search')
            new_regex = val if val else None
            if new_regex != current_regex:
                model['_scroll_to_match'] = True
                model['undoHistory'] = model.get('undoHistory', []) + [current_regex]
                model['redoHistory'] = []
                model['search'] = new_regex
            # Clear any in-progress drag state since user is editing directly
            model['anchorIdx'] = None
            model['cursorIdx'] = None
            model['dragging'] = False
            model['insertAfterSegment'] = None

        case ReplaceToggle():
            model['replace_visible'] = not model.get('replace_visible', False)

        case ExpandToggle():
            model['expanded'] = not model.get('expanded', False)

        case ReplaceBoxInput(value=val):
            model['replace_text'] = val if val else None

        case Unlink():
            # Stash the action so the chain icon can resume it on relink.
            model['unlinked_action'] = model.get('linked_action')
            model['linked_action'] = None
            model['linked_source_expr'] = None
            model['last_linked_expr'] = None

        case Relink(mode=mode, text=text):
            handle_relink(_LINK_CONFIG, mode, text, var_and_exp, model, commands,
                          eval_in_scope=eval_in_scope)

        case SegmentToggle(segment_id=seg_id):
            # Toggle the segment in the selection list (preserving canonical
            # order via _segment_rank), then rebuild the Replace text.
            current = list(model.get('selectedSegments') or [])
            if seg_id in current:
                current.remove(seg_id)
            else:
                current.append(seg_id)
            current.sort(key=_segment_rank)
            model['selectedSegments'] = current
            # Default eval_in_scope to plain eval so index/slice expression
            # resolution still works even when the caller didn't pass one in
            # (e.g. the test harness).
            ev = eval_in_scope if eval_in_scope is not None else (lambda c: eval(c))
            model['replace_text'] = _build_segment_replace_text(
                model, var_and_exp, value, ev)
            # Selecting any segment opens the Replace box so the user sees
            # the expression they're building.
            model['replace_visible'] = True

        case ToolSelect(tool=t):
            if t in ('literal', 'fuzzy', 'index', 'pick'):
                old_tool = model.get('tool', 'literal')
                model['tool'] = t
                _commit_open_dropdown_edit(model)
                model['openDropdown'] = None
                model['hoverIdx'] = None
                # Selections are scoped to a single pick-mode session; clear
                # them whenever the tool changes (entering or leaving pick).
                if t == 'pick' or old_tool == 'pick':
                    model['selectedSegments'] = []
                if t == 'pick':
                    # Auto-open the Replace box so the user sees the expression
                    # they're building as they click chips.
                    model['replace_visible'] = True
                    # Pick composes a map expression via segment chips; Map
                    # Matches (find_or_map with replace open) is the only
                    # action that consumes that expression. Mirror Enter.
                    if model.get('linked_action'):
                        model['linked_action'] = 'find_or_map'
                    # Auto-turn-on capture groups when the regex has more than
                    # one segment so each group gets its own clickable chip.
                    selection_regex = model.get('search')
                    if (selection_regex and is_regex_search(selection_regex)
                            and not is_capture_groups_mode(selection_regex)):
                        inner = get_regex_inner_pattern(selection_regex) or ''
                        try:
                            seg_count = len(parse_all_segments(inner))
                        except Exception:
                            seg_count = 0
                        if seg_count > 1:
                            new_regex = _toggle_search_flag(selection_regex, 'c')
                            new_regex = ensure_all_groups(new_regex)
                            model['undoHistory'] = model.get('undoHistory', []) + [selection_regex]
                            model['redoHistory'] = []
                            model['search'] = new_regex

        case FetchClick(source=source, fmt=fmt):
            # Reading what the string names is about the string rather than
            # about the search, so it writes a line of its own and links
            # nothing: there is no gesture afterwards to keep a line in step
            # with, the way a selection keeps its `re.finditer` in step.
            _commit_open_dropdown_edit(model)
            model['openDropdown'] = None
            result = _fetch_code(_fetch_source_expr(model, var_and_exp),
                                 source, fmt)
            if result:
                commands.append(new_code_command(result, code_imports))

        case ActionButtonClick(action=action, copy=copy):
            _commit_open_dropdown_edit(model)
            model['openDropdown'] = None
            if model.get('linked_action') and not copy:
                model['linked_action'] = action
                ctx = _get_search_context(model, var_and_exp,
                                          source_expr=model['linked_source_expr'],
                                          eval_in_scope=eval_in_scope)
                if ctx:
                    result = generate_action(action, ctx)
                    if result:
                        _emit_linked_update(result[1], model, commands,
                                            suggest_name=result[0], rename=True)
            else:
                ctx = _get_search_context(model, var_and_exp, eval_in_scope=eval_in_scope)
                if ctx:
                    if copy and action in ('if_any', 'if_all'):
                        bool_expr = generate_copy_expr_for_if(action, ctx)
                        if bool_expr:
                            commands.append(CopyToClipboard(text=bool_expr))
                        return (model, commands)
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

    if is_nested(var_and_exp):
        return (model, commands)

    if model.get('linked_action') and not isinstance(msg, (ActionButtonClick, FetchClick, Unlink, Relink)):
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
          and not isinstance(msg, (FetchClick, Unlink, Relink))):
        # First meaningful interaction: if it yields a parseable expression,
        # auto-insert a line of code and self-link so subsequent interactions
        # update it in place via ChangeSelectedText (the linked block above).
        _maybe_auto_link(msg, var_and_exp, model, commands, eval_in_scope=eval_in_scope)

    return (model, commands)


# Default actions used when auto-linking on the first interaction (mirroring
# the Enter-key behavior, find or map), or when relinking to a line whose shape
# rules out the previously stashed action.
_AUTO_LINK_ACTION = 'find_or_map'
_AUTO_LINK_STATEMENT_ACTION = 'loop'

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
    code_imports=code_imports,
)


def _maybe_auto_link(msg, var_and_exp, model: dict, commands: list, *, eval_in_scope=None) -> None:
    """If the current model state yields a parseable default expression, set up
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
    # Mirror how _get_search_context derives source_expr so the linked-update
    # block (which re-resolves via source_expr) rebuilds the same context.
    model['linked_action'] = _AUTO_LINK_ACTION
    model['linked_source_expr'] = ctx.get('source_expr')
    model['last_linked_expr'] = expr
    model['auto_linked_once'] = True
    commands.append(new_code_command(result, code_imports))


def _emit_linked_update(expr: str, model: dict, commands: list,
                        suggest_name: 'str | None' = None,
                        rename: bool = False) -> None:
    """Send expression intent while leaving the concrete target to the editor.

    No-op when *expr* matches the last expression written for this link, so
    events that do not change the search context (e.g. hover) do not rewrite
    the linked line of code.

    Whether the code being written can be assigned to a name is read off the
    code itself rather than remembered from the action that linked the line: an
    action change can turn an expression into a block header (Find into Loop)
    or back, and a remembered answer would describe the shape that just stopped
    being true -- probing `name = for i, mtch in ...:` raises, and the update
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
