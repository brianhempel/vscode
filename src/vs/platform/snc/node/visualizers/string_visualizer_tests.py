"""
Tests for string_visualizer.py update function.

These tests simulate mouse and keyboard events to verify the selection behavior
for building regex patterns by demonstration.

Run this test file directly:
	python3 src/vs/platform/snc/node/visualizers/string_visualizer_tests.py

Or use pytest with verbose output:
	python3 -m pytest src/vs/platform/snc/node/visualizers/string_visualizer_tests.py -v

No arguments are required; all tests should pass.
"""

import time
import unittest
from unittest.mock import patch
import re
from string_visualizer import (
    update, init_model, visualize,
    MouseDown, MouseMove, MouseUp, KeyDown,
    NotifyMouseIsUp,
    HandleMouseDown,
    DropdownToggle, DropdownSelect,
    SearchBoxInput,
    ReplaceBoxInput, ReplaceToggle,
    ExpandToggle,
    RepetitionInput,
    FirstMatchToggle,
    CaseSensitiveToggle,
    CaptureGroupsToggle,
    ActionButtonClick,
    ToolSelect,
    SegmentToggle,
    CopyToClipboard,
    ChangeSelectedText,
    Unlink,
    Relink,
    _format_slice_expr, _format_index_expr,
    SliceLabelInput,
    compute_internal_length,
    extract_by_internal_indices,
    get_last_segment_end_internal_idx,
    get_first_segment_start_internal_idx,
    parse_regex_for_highlighting,
    find_fuzzy_segment_at_index,
    replace_segment_pattern,
    replace_segment_repetition,
    REPETITION_OPTIONS, REPETITION_TOOLTIPS,
    resize_literal_segment,
    resize_fuzzy_segment,
    remove_segment,
    split_literal_segment,
    extract_quantifier,
    _subpattern_to_string,
    strip_capturing_groups,
    get_regex_inner_pattern,
    get_search_flags,
    is_first_match_mode,
    is_case_insensitive,
    is_capture_groups_mode,
    ensure_all_groups,
    make_regex_search,
    append_segment_to_regex,
    prepend_segment_to_regex,
    insert_segment_at_position,
    parse_all_segments,
    FUZZY_PATTERN_OPTIONS,
    negated_class_option,
    fuzzy_pattern_options,
    canonicalize_regex,
    is_regex_search,
    is_slice_search,
    parse_slice_parts,
    parse_search_term,
    eval_string_search,
    _find_closing_delimiter,
    is_adjacent_right,
    is_adjacent_left,
    synthesize_fuzzy_pattern,
    _eval_count_via_grammar,
    char_to_regex_literal,
    DC2, DC3,  # Sentinel characters
    _render_transform_preview,
    _render_match_object_preview,
    _eval_index_or_slice_match,
    _find_matches,
    is_index_or_slice_search,
    _action_btn,
    _dropdown_row,
)
from visualizer_utils import py_exp_attrs, PyExp


# The list-comprehension form a multi-match regex hands over, `{}` being how
# each match is read.
FINDITER = "[m{} for m in re.finditer(r'(a)(b)', str1, flags=re.M)]"


def exp_attr(*exprs):
    """The `snc-py-exps` attribute a handle offering these expressions carries,
    as it reads inside the tag it was written into."""
    return py_exp_attrs(list(exprs), draggable=False).strip()


# =============================================================================
# Test Helpers
# =============================================================================

def _legacy_internal_index(index: int) -> int:
    """Map the old test-only \\A/^/.../$/\\Z index space to the current visible one."""
    return max(index - 1, 0)


def make_mouse_down_event(index: int, top_half: bool = True, legacy_index: bool = True, shift_key: bool = False, ctrl_key: bool = False) -> dict:
    """Create a MouseDown event dict.

    Args:
        index: The character index clicked
        top_half: If True, click is in top half (literal). If False, bottom half (fuzzy).
        shift_key: If True, simulates the shift key being held down.
        ctrl_key: If True, simulates the ctrl key being held down (index mode).
    """
    if legacy_index:
        index = _legacy_internal_index(index)
    return {
        'pythonEventStr': repr(MouseDown(index)),
        'eventJSON': {
            'altKey': not top_half,
            'shiftKey': shift_key,
            'ctrlKey': ctrl_key,
            'offsetY': 5 if top_half else 15,  # top half < 10, bottom half >= 10
            'elementHeight': 20,
            'buttons': 1,
        }
    }


def make_mouse_move_event(index: int, buttons: int = 1, top_half: bool | None = None, legacy_index: bool = True,
                          alt_key: bool = False, shift_key: bool = False, ctrl_key: bool = False) -> dict:
    """Create a MouseMove event dict.

    Args:
        index: The character index the mouse moved to
        buttons: 1 if button pressed, 0 if released
        top_half: If provided, include offsetY/elementHeight for hover detection.
                  True = top half (literal), False = bottom half (fuzzy).
        alt_key/shift_key/ctrl_key: Modifier keys held during the move. The
                  front-end sends these on every event; the selection type
                  follows them live during a drag.
    """
    if legacy_index:
        index = _legacy_internal_index(index)
    event_json: dict = {
        'buttons': buttons,
        'altKey': alt_key,
        'shiftKey': shift_key,
        'ctrlKey': ctrl_key,
    }
    if top_half is not None:
        event_json['offsetY'] = 5 if top_half else 15  # top half < 10, bottom half >= 10
        event_json['elementHeight'] = 20
    return {
        'pythonEventStr': repr(MouseMove(index)),
        'eventJSON': event_json,
    }


def make_mouse_up_event(index: int, legacy_index: bool = True,
                        alt_key: bool = False, shift_key: bool = False, ctrl_key: bool = False) -> dict:
    """Create a MouseUp event dict."""
    if legacy_index:
        index = _legacy_internal_index(index)
    return {
        'pythonEventStr': repr(MouseUp(index)),
        'eventJSON': {
            'buttons': 0,
            'altKey': alt_key,
            'shiftKey': shift_key,
            'ctrlKey': ctrl_key,
        }
    }


def _command_text(cmd) -> str:
    """Return the code/text carried by a command, for substring assertions.

    Handles NewCode tuples (suggest_name, expr[, imports]), ChangeSelectedText,
    and CopyToClipboard. Returns '' for anything else.
    """
    if isinstance(cmd, tuple) and len(cmd) in (2, 3):
        return cmd[1] or ''
    text = getattr(cmd, 'text', None)
    return text or ''


def make_key_down_event(key: str, meta_key: bool = False, shift_key: bool = False) -> dict:
    """Create a KeyDown event dict."""
    return {
        'pythonEventStr': repr(KeyDown()),
        'eventJSON': {
            'key': key,
            'metaKey': meta_key,
            'shiftKey': shift_key,
        }
    }


# =============================================================================
# Basic Tests
# =============================================================================

class TestBasics(unittest.TestCase):
    """Test basic functionality: null events, init_model defaults."""

    def test_init_model_returns_expected_defaults(self):
        """init_model(value) returns a dict with all expected keys and default values."""
        model = init_model("test")

        self.assertIsNone(model['search'])
        self.assertIsNone(model['anchorIdx'])
        self.assertIsNone(model['anchorType'])
        self.assertIsNone(model['cursorIdx'])
        self.assertFalse(model['dragging'])
        self.assertIsNone(model['extendDirection'])
        self.assertNotIn('insertAfterSegment', model)
        # Note: stringValue is no longer stored in model - it's passed as parameter
        self.assertEqual(model['undoHistory'], [])
        self.assertEqual(model['redoHistory'], [])
        self.assertEqual(model['handledKeys'], ["Escape", "Enter", "cmd Backspace", "cmd r", "cmd z", "cmd shift z"])

    def test_null_event_returns_unchanged_model(self):
        """Passing None event returns model unchanged with no commands."""
        value = "test"
        model = init_model(value)

        new_model, commands = update(None, ('x', 'x'), model, value)

        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_empty_event_returns_unchanged_model(self):
        """Passing empty event dict returns model unchanged."""
        value = "test"
        model = init_model(value)

        new_model, commands = update({}, ('x', 'x'), model, value)

        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_event_with_empty_pythonEventStr_returns_unchanged(self):
        """Event with empty pythonEventStr returns model unchanged."""
        value = "test"
        model = init_model(value)

        event = {'pythonEventStr': '', 'eventJSON': {}}
        new_model, commands = update(event, ('x', 'x'), model, value)

        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_none_model_gets_initialized(self):
        """Passing None model initializes a fresh model."""
        event = make_mouse_down_event(5, top_half=True)
        value = "hello world"

        new_model, commands = update(event, ('x', 'x'), None, value)

        self.assertIsNotNone(new_model)
        self.assertEqual(new_model['anchorIdx'], _legacy_internal_index(5))
        self.assertEqual(new_model['cursorIdx'], _legacy_internal_index(5))
        self.assertEqual(new_model['anchorType'], 'literal')
        self.assertTrue(new_model['dragging'])
        self.assertEqual(commands, [])


# =============================================================================
# Single Literal Selection Tests
# =============================================================================

class TestSingleLiteralSelection(unittest.TestCase):
    """Test single literal selection: MouseDown (top half) -> MouseMove -> MouseUp.

    For "hello world", the augmented string indices are:
        0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z
    """

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_mouse_down_top_half_starts_literal_selection(self):
        """MouseDown in top half sets up literal drag state."""
        event = make_mouse_down_event(5, top_half=True)

        model, commands = update(event, self.var_and_exp, self.model, self.value)

        self.assertEqual(model['anchorIdx'], _legacy_internal_index(5))
        self.assertEqual(model['cursorIdx'], _legacy_internal_index(5))
        self.assertEqual(model['anchorType'], 'literal')
        self.assertTrue(model['dragging'])
        self.assertIsNone(model['search'])  # Not finalized yet
        self.assertEqual(commands, [])

    def test_mouse_move_updates_cursor_for_literal(self):
        """MouseMove updates cursorIdx during literal drag."""
        model, _ = update(make_mouse_down_event(5, top_half=True),
                         self.var_and_exp, self.model, self.value)

        model, _ = update(make_mouse_move_event(8),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['anchorIdx'], _legacy_internal_index(5))
        self.assertEqual(model['cursorIdx'], _legacy_internal_index(8))
        self.assertTrue(model['dragging'])
        self.assertIsNone(model['search'])  # Still not finalized

    def test_mouse_up_finalizes_hello_selection(self):
        """MouseUp finalizes 'hello' selection (indices 2-6) into /(hello)/."""
        # Select indices 2-6: h(2), e(3), l(4), l(5), o(6)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, commands = update(make_mouse_up_event(6),
                                self.var_and_exp, model, self.value)

        self.assertFalse(model['dragging'])
        self.assertIsNone(model['anchorIdx'])
        self.assertIsNone(model['cursorIdx'])
        self.assertEqual(model['search'], r"r'hello'")
        self.assertEqual(model['undoHistory'], [None])
        # Finalizing a selection now auto-inserts a linked find LOC.
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], tuple)

    def test_single_char_selection(self):
        """Click and release on same index selects single char 'h' -> /(h)/."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(2),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'h'")

    def test_world_selection(self):
        """Select 'world' (indices 8-12) -> /(world)/."""
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'world'")

    def test_space_selection(self):
        """Select just the space at index 7 -> /(\\ )/."""
        model, _ = update(make_mouse_down_event(7, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(7),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'\ '")


# =============================================================================
# Single Fuzzy Selection Tests
# =============================================================================

class TestSingleFuzzySelection(unittest.TestCase):
    """Test single fuzzy selection: MouseDown (bottom half) -> MouseUp."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_mouse_down_bottom_half_starts_fuzzy_selection(self):
        """MouseDown in bottom half starts a fuzzy selection."""
        event = make_mouse_down_event(5, top_half=False)

        model, commands = update(event, self.var_and_exp, self.model, self.value)

        self.assertEqual(model['anchorIdx'], _legacy_internal_index(5))
        self.assertEqual(model['anchorType'], 'fuzzy')
        self.assertTrue(model['dragging'])

    def test_mouse_move_updates_cursor_for_fuzzy(self):
        """MouseMove updates cursorIdx for fuzzy selection (needed for pattern synthesis)."""
        model, _ = update(make_mouse_down_event(5, top_half=False),
                         self.var_and_exp, self.model, self.value)
        self.assertEqual(model['cursorIdx'], _legacy_internal_index(5))

        model, _ = update(make_mouse_move_event(10, alt_key=True),
                         self.var_and_exp, model, self.value)

        # Cursor tracks mouse for fuzzy (used to synthesize pattern from drag range)
        self.assertEqual(model['cursorIdx'], _legacy_internal_index(10))

    def test_mouse_up_finalizes_fuzzy_segment(self):
        """MouseUp finalizes fuzzy segment with synthesized pattern.

        Clicking at index 5 (letter 'l' in 'hello world') with no drag:
        - The single char 'l' is lowercase, next char 'o' is also lowercase
        - So [a-z]+ would overshoot; falls back to [a-z]{1}
        """
        model, _ = update(make_mouse_down_event(5, top_half=False),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(5, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertFalse(model['dragging'])
        self.assertEqual(model['search'], r"r'[a-z]{1}'")
        self.assertEqual(model['undoHistory'], [None])

    def test_fresh_fuzzy_on_space_uses_plus(self):
        r"""Fresh fuzzy selection on space char uses \s+ (not \s*).

        Clicking at index 7 (the space in 'hello world') with no drag:
        - actual_text = ' '
        - prev_char = 'o' (doesn't match \s) -> clean left boundary
        - next_char = 'w' (doesn't match \s) -> clean right boundary
        - Fresh selection (no existing regex) -> uses + quantifier
        """
        model, _ = update(make_mouse_down_event(7, top_half=False),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(7, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertFalse(model['dragging'])
        self.assertEqual(model['search'], r"r'\s+'")
        self.assertEqual(model['undoHistory'], [None])

    def test_fresh_fuzzy_drag_across_letters_with_clean_boundaries(self):
        r"""Fresh fuzzy drag with clean boundaries uses +.

        For 'abc 123 xyz':
        Augmented: 0=\A, 1=^, 2=a, 3=b, 4=c, 5=' ', 6=1, 7=2, 8=3, 9=' ', 10=x, 11=y, 12=z, ...
        Dragging across '123' (indices 6-8):
        - actual_text = '123'
        - prev_char = ' ' (doesn't match \d) -> clean left boundary
        - next_char = ' ' (doesn't match \d) -> clean right boundary
        - Fresh selection -> \d+
        """
        value = "abc 123 xyz"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model, _ = update(make_mouse_down_event(6, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(8, alt_key=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8, alt_key=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'\d+'")


# =============================================================================
# Mid-Drag Modifier Change Tests
# =============================================================================

class TestMidDragModifierChanges(unittest.TestCase):
    """Modifier changes DURING a drag re-type the in-progress selection.

    The toolbar highlight and the idle hover preview both follow the held
    modifiers live; a drag follows them live too, instead of freezing the
    type resolved at mousedown. Whatever type is in effect at release is
    what finalizes.

    For "hello world", the augmented string indices are:
        0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z
    """

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_alt_pressed_mid_drag_switches_to_fuzzy(self):
        """A literal drag becomes fuzzy the moment alt is held."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        self.assertEqual(model['anchorType'], 'literal')

        model, _ = update(make_mouse_move_event(6, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['anchorType'], 'fuzzy')
        self.assertEqual(model['cursorIdx'], _legacy_internal_index(6))

    def test_alt_released_mid_drag_reverts_to_tool_type(self):
        """Releasing alt mid-drag falls back to the active tool (literal)."""
        model, _ = update(make_mouse_down_event(2, top_half=False),
                         self.var_and_exp, self.model, self.value)
        self.assertEqual(model['anchorType'], 'fuzzy')

        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['anchorType'], 'literal')

        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

    def test_modifiers_at_mouseup_decide_final_type(self):
        """Alt held only at release still finalizes the drag as fuzzy."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, commands = update(make_mouse_up_event(6, alt_key=True),
                                self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'[a-z]+'")

    def test_shift_pressed_mid_drag_overrides_fuzzy_tool(self):
        """With the fuzzy tool active, holding shift mid-drag forces literal."""
        self.model['tool'] = 'fuzzy'
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        self.assertEqual(model['anchorType'], 'fuzzy')

        model, _ = update(make_mouse_move_event(6, shift_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['anchorType'], 'literal')

        model, _ = update(make_mouse_up_event(6, shift_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

    def test_ctrl_pressed_mid_drag_switches_to_index_slice(self):
        """Holding ctrl mid-drag re-types the selection as an index slice."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6, ctrl_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['anchorType'], 'index')

        model, _ = update(make_mouse_up_event(6, ctrl_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], ':5')
        self.assertTrue(is_slice_search(model['search']))

    def test_ctrl_released_mid_drag_reverts_to_literal(self):
        """A ctrl-started (index) drag becomes literal when ctrl is released."""
        model, _ = update(make_mouse_down_event(2, top_half=True, ctrl_key=True),
                         self.var_and_exp, self.model, self.value)
        self.assertEqual(model['anchorType'], 'index')

        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['anchorType'], 'literal')

        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

    def test_ctrl_mid_drag_replaces_existing_regex_and_keeps_undo(self):
        """Switching to index mid-drag replaces the regex on finalize, and the
        old pattern lands in undo history (unlike a ctrl-mousedown, which
        resets the model up front)."""
        # Finalize 'hello' as a literal first.
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

        # Extend rightward from the match (adjacent, so no model reset),
        # pressing ctrl mid-drag.
        model, _ = update(make_mouse_down_event(7, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(12, ctrl_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['anchorType'], 'index')
        model, _ = update(make_mouse_up_event(12, ctrl_key=True),
                         self.var_and_exp, model, self.value)

        self.assertTrue(is_slice_search(model['search']))
        self.assertEqual(model['undoHistory'][-1], r"r'hello'")


# =============================================================================
# Chained Selections (Extend Right) Tests
# =============================================================================

class TestChainedSelectionsExtendRight(unittest.TestCase):
    """Test chaining selections by extending from the right end."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_extend_hello_with_fuzzy(self):
        """Extend 'hello' selection with fuzzy -> /(hello)(\s*)/."""
        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")

        # Get end index for extending
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertEqual(end_idx, _legacy_internal_index(7))

        # Extend with fuzzy at end
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])

    def test_extend_hello_with_space_literal(self):
        """Extend 'hello' with space literal -> /(hello)(\\ )/."""
        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)

        # Extend with single space (click and release at same position)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)(\ )'")

    def test_chain_hello_fuzzy_world(self):
        """Chain: hello -> fuzzy -> world gives /(hello)(.*)(world)/."""
        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")

        # Extend with fuzzy at end of hello (index 7)
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertEqual(end_idx, _legacy_internal_index(7))
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")

        # The fuzzy (\s*) matches " world$\Z" (indices 7-15)
        # To add "world", click INSIDE the fuzzy region at index 8 (start of 'w')
        # and drag to index 12 (end of 'world')
        # Augmented indices: 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\Z
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*world'")


class TestChainThreeSegmentsWithConstrainedFuzzy(unittest.TestCase):
    """Test chaining with fuzzy that doesn't consume everything."""

    def setUp(self):
        # Use a multiline string where (.*) stops at newline
        self.value = "hello\nworld"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')
        # Augmented: 0=\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=$, 8=\n, 9=^, 10=w, 11=o, 12=r, 13=l, 14=d, 15=$, 16=\Z

    def test_chain_hello_fuzzy_world_with_newline(self):
        """Chain hello -> fuzzy (stops at $) -> $\\n^ -> world."""
        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")

        # Extend with fuzzy (will stop at $ because .* doesn't match newline by default)
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello.*'")

        # The (.*) after "hello" matches the $ anchor (index 7)
        # So fuzzy spans 7-8, end_idx is 8
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertEqual(end_idx, _legacy_internal_index(8))

        # Extend with \n at index 8
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello.*\n'")


class TestFuzzyDragEndingAtLineBoundary(unittest.TestCase):
    r"""A fuzzy drag whose edge abuts a ^/$ anchor marker must look through the
    marker to the real neighboring character. Treating the marker as
    end-of-string skipped the overshoot check, so [\S\s]* leaked past the
    dragged range instead of stopping at that neighbor ([^g], [^c]).

    Finding no neighbor still shows up plainly here: it would put an unbounded
    [\S\s]* back in each of these."""

    def setUp(self):
        self.value = "abcdef\nghijk"
        # Internal: ^=0, a=1, b=2, c=3, d=4, e=5, f=6, $=7, \n=8, ^=9, g=10 ... k=14, $=15
        self.var_and_exp = ('x', 'x')

    def _select_cd(self):
        model = init_model(self.value)
        model, _ = update(make_mouse_down_event(3, top_half=True, legacy_index=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(4, legacy_index=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(4, legacy_index=False),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'cd'")
        return model

    def _fuzzy_drag(self, model, start_idx, end_idx):
        model, _ = update(make_mouse_down_event(start_idx, top_half=False, legacy_index=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)
        return model

    def test_fuzzy_drag_ending_on_newline_stays_counted(self):
        r"""Dragging e f \n (ending ON the \n) selects 3 chars; 'g' follows, so
        [\S\s]* would overshoot and the pattern must stop at the 'g'."""
        model = self._select_cd()
        model = self._fuzzy_drag(model, 5, 8)
        self.assertEqual(model['search'], r"r'cd[^g]*'")

    def test_fuzzy_drag_ending_on_next_line_caret_stays_counted(self):
        r"""Same drag but ending on the next line's ^ marker: still 3 real chars."""
        model = self._select_cd()
        model = self._fuzzy_drag(model, 5, 9)
        self.assertEqual(model['search'], r"r'cd[^g]*'")

    def test_fuzzy_drag_ending_on_dollar_excludes_newline(self):
        r"""Ending on the $ marker before the \n does not pull in the \n."""
        model = self._select_cd()
        model = self._fuzzy_drag(model, 5, 7)
        self.assertEqual(model['search'], r"r'cd[a-z]*'")

    def test_fresh_fuzzy_drag_starting_at_line_start_stays_counted(self):
        r"""A fresh fuzzy drag starting just after a ^ marker must see the \n
        before it as the left neighbor (which [\S\s]+ would swallow)."""
        value = "a\nb\nc"
        # Internal: ^=0, a=1, $=2, \n=3, ^=4, b=5, $=6, \n=7, ^=8, c=9, $=10
        model = init_model(value)
        model, _ = update(make_mouse_down_event(5, top_half=False, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(9, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(9, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'[\S\s]{3}'")

    def test_fuzzy_handle_resize_ending_on_newline_stays_counted(self):
        r"""Resizing a fuzzy segment's right handle onto a \n hits the same
        boundary lookup: 'c' follows across the ^ marker, so stay counted."""
        value = "a\nb\nc"
        # Internal: ^=0, a=1, $=2, \n=3, ^=4, b=5, $=6, \n=7, ^=8, c=9, $=10
        model = init_model(value)
        model['search'] = r"r'([\S\s]{3})'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(7, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(7, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'([^c]+)'")


# =============================================================================
# Extend Left (Prepend) Tests
# =============================================================================

class TestExtendLeft(unittest.TestCase):
    """Test extending selection from the left (prepending segments)."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_click_immediately_left_of_literal_extends_with_fuzzy(self):
        """Click char immediately left of literal selection extends it with fuzzy.

        BUG: Previously clicking the char immediately to the left of a literal
        selection would reset the selection instead of extending it.

        For "hello world":
            Augmented: 0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z

        If we select "world" (indices 8-12), clicking on index 7 (the space immediately
        to the left) should extend the selection to the left, not reset it.
        """
        # Select "world" (indices 8-12)
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'world'")

        # Get start index - this is 8 (the 'w')
        start_idx = get_first_segment_start_internal_idx(model['search'], self.value)
        self.assertEqual(start_idx, _legacy_internal_index(8))

        # Click on index 7 (the space immediately to the left) with fuzzy (bottom half)
        # This should extend left, NOT reset the selection
        model, _ = update(make_mouse_down_event(7, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7, alt_key=True),
                         self.var_and_exp, model, self.value)

        # Should prepend fuzzy: /(\s*)(world)/
        self.assertEqual(model['search'], r"r'\s*world'")
        self.assertEqual(model['undoHistory'], [None, r"r'world'"])

    def test_prepend_fuzzy_to_world(self):
        """Select 'world', then prepend fuzzy -> /(\s*)(world)/."""
        # Select "world" (indices 8-12)
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'world'")

        # Get start index for prepending
        start_idx = get_first_segment_start_internal_idx(model['search'], self.value)
        self.assertEqual(start_idx, _legacy_internal_index(8))

        # Prepend with fuzzy by clicking the char immediately to the left (start_idx - 1 = 7)
        model, _ = update(make_mouse_down_event(start_idx - 1, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(start_idx - 1, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'\s*world'")
        self.assertEqual(model['undoHistory'], [None, r"r'world'"])

    def test_prepend_literal_to_world(self):
        """Select 'world', prepend by dragging left selects 'o ' -> /(o\\ )(world)/."""
        # Select "world"
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        start_idx = get_first_segment_start_internal_idx(model['search'], self.value)
        self.assertEqual(start_idx, _legacy_internal_index(8))

        # Prepend by clicking at the char immediately to the left (start_idx - 1 = 7)
        # and dragging left to index 6. This selects indices 6, 7 = 'o', ' '
        model, _ = update(make_mouse_down_event(start_idx - 1, legacy_index=False, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(o\ )(world)'")


# =============================================================================
# Click Inside Fuzzy Segment Tests
# =============================================================================

class TestClickInsideFuzzy(unittest.TestCase):
    """Test clicking inside a fuzzy segment to split/constrain it."""

    def setUp(self):
        self.value = "hello world goodbye"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_click_inside_fuzzy_starts_new_segment(self):
        """Clicking inside a realized fuzzy region starts a new drag."""
        # Create hello + (.*) pattern
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")

        # Find where the fuzzy segment spans
        highlights = parse_regex_for_highlighting(model['search'], self.value)
        fuzzy_segment = None
        for start, end, seg_type, _, _, _, _ in highlights:
            if seg_type == 'fuzzy':
                fuzzy_segment = (start, end)
                break

        self.assertIsNotNone(fuzzy_segment)
        fuzzy_start, fuzzy_end = fuzzy_segment

        # Click inside the fuzzy region
        click_idx = fuzzy_start + 3
        fuzzy_info = find_fuzzy_segment_at_index(model['search'], self.value, click_idx)
        self.assertIsNone(fuzzy_info)  # canonical format doesn't expose groups to this helper

        # Click inside fuzzy to start new segment
        model, _ = update(make_mouse_down_event(click_idx, legacy_index=False, top_half=True),
                         self.var_and_exp, model, self.value)

        # Should start a new drag, resetting the regex
        self.assertTrue(model['dragging'])
        self.assertEqual(model['anchorIdx'], click_idx)
        self.assertIsNone(model['search'])  # Reset for new selection

    def test_visualize_while_dragging_inside_fuzzy_does_not_crash(self):
        """
        BUG TEST: Calling visualize() while dragging inside a fuzzy segment
        should not crash with an assertion error about overlapping highlights.

        The bug was: when dragging inside a fuzzy segment, the in-progress
        selection (anchorIdx to cursorIdx) overlaps with the existing fuzzy
        highlight, causing an AssertionError in visualize().

        Error was: "AssertionError: Index 12 already has a highlight: (7, 19, 'fuzzy', '.*', (0, inf))"
        """
        # Create hello + (.*) pattern
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")

        # Find where the fuzzy segment spans
        highlights = parse_regex_for_highlighting(model['search'], self.value)
        fuzzy_segment = None
        for start, end, seg_type, _, _, _, _ in highlights:
            if seg_type == 'fuzzy':
                fuzzy_segment = (start, end)
                break

        self.assertIsNotNone(fuzzy_segment)
        fuzzy_start, fuzzy_end = fuzzy_segment

        # Click inside the fuzzy region and START dragging (don't release yet)
        click_idx = fuzzy_start + 3
        model, _ = update(make_mouse_down_event(click_idx, legacy_index=False, top_half=True),
                         self.var_and_exp, model, self.value)

        # Drag to another position still inside the fuzzy region
        drag_idx = click_idx + 2
        model, _ = update(make_mouse_move_event(drag_idx, legacy_index=False),
                         self.var_and_exp, model, self.value)

        # Model should still be dragging with the in-progress selection
        self.assertTrue(model['dragging'])
        self.assertEqual(model['anchorIdx'], click_idx)
        self.assertEqual(model['cursorIdx'], drag_idx)

        # THIS IS THE BUG: visualize() crashes because the in-progress selection
        # overlaps with the existing fuzzy highlight
        # After fix, this should NOT raise an assertion error
        html_output = visualize(self.value, model, None, None)

        # Should produce valid HTML without crashing
        self.assertIsInstance(html_output, str)
        self.assertIn('<span', html_output)

    def test_anchor_fuzzy_with_literal_inside_appends_to_right(self):
        """
        BUG TEST: Clicking inside a fuzzy segment to anchor it with a literal
        should produce the pattern in the correct order: (1)(.*)(2).

        Where:
        - (1) = first literal selection
        - (2) = second literal selection (clicked inside fuzzy)

        Scenario:
        1. Select "hello" = (1) -> /(hello)/
        2. Extend with fuzzy at end -> /(hello)(.*)/
        3. Click inside the fuzzy region on "world" = (2)

        Expected: /(hello)(.*)(world)/ = (1)(.*)(2)
        Bug would produce: /(.*)(world)(hello)/ = (.*)(2)(1) - WRONG ORDER!

        The bug was that the literal was being added to the wrong position.
        """
        # For "hello world goodbye":
        # Augmented: 0=\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=' ', 14=g, ...

        # Step 1: Select "hello" (indices 2-6) = (1)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")

        # Step 2: Extend with fuzzy at end of hello
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertEqual(end_idx, _legacy_internal_index(7))
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")

        # Step 3: Click inside the fuzzy on "world" (indices 8-12) = (2)
        # This is a click-drag to select "world"
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(12),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                         self.var_and_exp, model, self.value)

        # Expected: (1)(\s*)(2) = /hello\s*world/
        # Bug would produce: (\s*)(2)(1) = /(\s*)(world)(hello)/ - WRONG!
        self.assertEqual(model['search'], r"r'hello\s*world'")

        # Verify segment order explicitly
        highlights = parse_regex_for_highlighting(model['search'], self.value)
        # Should be: [(2, 7, 'literal'), (7, 8, 'fuzzy'), (8, 13, 'literal')]
        # i.e., hello first, then fuzzy, then world
        self.assertEqual(len(highlights), 3)
        self.assertEqual(highlights[0][2], 'literal')  # hello
        self.assertEqual(highlights[1][2], 'fuzzy')    # (.*)
        self.assertEqual(highlights[2][2], 'literal')  # world

    def test_anchor_leading_fuzzy_inserts_before_fuzzy_to_maintain_text_order(self):
        """
        BUG TEST: When clicking inside a LEADING fuzzy segment (segment index 0),
        the new literal should be inserted BEFORE the fuzzy to maintain text order.

        Scenario:
        1. Select "world" -> /(world)/
        2. Prepend with fuzzy (click left of "world") -> /(.*)(world)/
        3. Click inside the leading fuzzy on "ello" -> should get /(ello)(.*)(world)/

        The key insight: the new literal "ello" comes BEFORE "world" in the text,
        so it should come before the fuzzy (which matches what's between them).

        Bug was: /(.*)(ello)(world)/ - fuzzy wrongly before the literal
        """
        # For "hello world":
        # Augmented: 0=\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\Z

        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Step 1: Select "world" (indices 8-12)
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(12),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(12),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'world'")

        # Step 2: Prepend with fuzzy (click at first_start - 1 = 7)
        first_start = get_first_segment_start_internal_idx(model['search'], value)
        self.assertEqual(first_start, _legacy_internal_index(8))
        model, _ = update(make_mouse_down_event(first_start - 1, legacy_index=False, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(first_start - 1, legacy_index=False, alt_key=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'\s*world'")

        # Verify the fuzzy segment exists (in canonical format, \s* only covers whitespace)
        highlights = parse_regex_for_highlighting(model['search'], value)
        fuzzy_segment = None
        for start, end, seg_type, _, _, _, _ in highlights:
            if seg_type == 'fuzzy':
                fuzzy_segment = (start, end, seg_type)
                break
        self.assertIsNotNone(fuzzy_segment)
        fuzzy_start, fuzzy_end, _ = fuzzy_segment

        # Step 3: Click on "ello" (indices 3-6), which is before the fuzzy in canonical format
        self.assertTrue(3 < fuzzy_start)

        model, _ = update(make_mouse_down_event(3, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)

        # In canonical format, clicking before the fuzzy region starts a new selection
        # (index 3 is before the \s* fuzzy at the space character)
        self.assertEqual(model['search'], r"r'ello'")

    def test_anchor_leading_fuzzy_abc_scenario(self):
        """
        BUG TEST: Exact reproduction of user's bug report.

        String: 'ABC'
        Click (1): literal C -> /(C)/
        Click (2): fuzzy B (extend left) -> /(.*)(C)/
        Click (3): literal A (inside fuzzy) -> Expected: /(A)(.*)(C)/

        Bug was producing: /(.*)(A)(C)/ - wrong order!
        """
        value = 'ABC'
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Augmented: 0=\A, 1=^, 2=A, 3=B, 4=C, 5=$, 6=\Z

        # Click (1): literal C (index 4)
        model, _ = update(make_mouse_down_event(4, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(4),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'C'")

        # Click (2): fuzzy B (extend left from C)
        first_start = get_first_segment_start_internal_idx(model['search'], value)
        self.assertEqual(first_start, _legacy_internal_index(4))
        model, _ = update(make_mouse_down_event(first_start - 1, legacy_index=False, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(first_start - 1, legacy_index=False, alt_key=True),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'[A-Z]{1}C'")

        # Click (3): literal A (inside fuzzy at index 2)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(2),
                         var_and_exp, model, value)

        # Expected: A + fuzzy + C - A first, then fuzzy for B, then C
        # Bug was: (.*)(A)(C) - wrong order
        self.assertEqual(model['search'], r"r'A[A-Z]{1}C'")


# =============================================================================
# Segment Click Menu Tests
# =============================================================================

class TestSegmentClickMenu(unittest.TestCase):
    """Mousedown inside an existing segment opens an actions menu below it,
    instead of wiping the regex (literal) or starting a split-drag (fuzzy)."""

    var_and_exp = ('x', 'x')

    def test_literal_interior_click_opens_menu(self):
        # "hello world": internal 1..6 is "hello"; 3 is strictly inside.
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown'],
                         {'id': 'segment-menu-0-0', 'segmentIndex': 0,
                          'matchIndex': 0, 'clickIdx': 3})
        self.assertEqual(model['search'], r"r'(hello)'")
        self.assertFalse(model['dragging'])
        self.assertIsNone(model['anchorIdx'])

    def test_canonical_literal_interior_click_opens_menu(self):
        # Segment-index metadata is present even without capture groups.
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"

        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown'],
                         {'id': 'segment-menu-0-0', 'segmentIndex': 0,
                          'matchIndex': 0, 'clickIdx': 3})
        self.assertEqual(model['search'], r"r'hello'")

    def test_click_on_segment_first_char_opens_menu(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_mouse_down_event(1, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-0')
        self.assertEqual(model['openDropdown']['clickIdx'], 1)

    def test_fuzzy_interior_click_opens_menu_not_split_drag(self):
        # 'a1b\na2b': the second match's (.*) covers the '2' at internal 8.
        value = 'a1b\na2b'
        model = init_model(value)
        model['search'] = r"r'(a)(.*)(b)'"

        model, _ = update(make_mouse_down_event(8, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown'],
                         {'id': 'segment-menu-1-1', 'segmentIndex': 1,
                          'matchIndex': 1, 'clickIdx': 8})
        self.assertEqual(model['search'], r"r'(a)(.*)(b)'")
        self.assertFalse(model['dragging'])
        self.assertIsNone(model.get('insertAfterSegment'))

    def test_fuzzy_tool_click_inside_segment_also_opens_menu(self):
        # The menu opens regardless of the active selection tool.
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_mouse_down_event(3, legacy_index=False, top_half=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-0')
        self.assertFalse(model['dragging'])

    def test_mouse_up_keeps_menu_open(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-0')
        self.assertEqual(model['search'], r"r'(hello)'")

    def test_click_with_menu_open_dismisses_without_selecting(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"
        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        # Click somewhere else while the menu is open: just dismiss.
        model, _ = update(make_mouse_down_event(8, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertIsNone(model.get('openDropdown'))
        self.assertEqual(model['search'], r"r'(hello)'")
        self.assertFalse(model['dragging'])
        self.assertIsNone(model['anchorIdx'])

    def test_escape_closes_menu_without_clearing_search(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"
        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        model, _ = update(make_key_down_event('Escape'),
                          self.var_and_exp, model, value)

        self.assertIsNone(model.get('openDropdown'))
        self.assertEqual(model['search'], r"r'(hello)'")

    def test_adjacent_click_still_extends_not_menu(self):
        # Click at the match's end continues the pattern as before.
        value = 'foo1 foo2 foo3'
        model = init_model(value)
        model['search'] = r"r'(foo)'"

        model, _ = update(make_mouse_down_event(14, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertIsNone(model.get('openDropdown'))
        self.assertTrue(model['dragging'])

        model, _ = update(make_mouse_up_event(14, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'(foo)(3)'")

    def test_click_outside_matches_still_starts_over(self):
        value = 'foo1   foo2'
        model = init_model(value)
        model['search'] = r"r'(foo)'"

        model, _ = update(make_mouse_down_event(6, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertIsNone(model.get('openDropdown'))
        self.assertTrue(model['dragging'])

    def test_index_tool_click_inside_segment_is_unchanged(self):
        # The index tool never composes with regex segments: still a fresh
        # slice selection, no menu.
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"
        model['tool'] = 'index'

        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)

        self.assertIsNone(model.get('openDropdown'))
        self.assertEqual(model['anchorType'], 'index')
        self.assertTrue(model['dragging'])

    # --- Menu rendering ---

    def _open_menu(self, value, search, click_idx):
        model = init_model(value)
        model['search'] = search
        model, _ = update(make_mouse_down_event(click_idx, legacy_index=False),
                          self.var_and_exp, model, value)
        return model

    def test_menu_panel_renders_when_open(self):
        model = self._open_menu("hello world", r"r'(hello)'", 3)
        html_out = visualize("hello world", model, None, None)

        self.assertIn('segment-menu-panel', html_out)
        self.assertIn('Remove segment', html_out)
        self.assertIn('Convert to Fuzzy', html_out)
        self.assertIn('Split here', html_out)

    def test_menu_rows_fire_dropdown_select(self):
        import html as html_mod
        model = self._open_menu("hello world", r"r'(hello)'", 3)
        html_out = visualize("hello world", model, None, None)

        for option_value in ('remove', 'convert', 'split'):
            event = repr(DropdownSelect('segment-menu-0-0', option_value))
            self.assertIn(html_mod.escape(event), html_out)

    def test_no_menu_panel_when_closed(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)'"
        html_out = visualize(value, model, None, None)

        self.assertNotIn('segment-menu-panel', html_out)

    def test_fuzzy_menu_offers_convert_to_literal_and_no_split(self):
        value = 'a1b\na2b'
        model = self._open_menu(value, r"r'(a)(.*)(b)'", 8)
        html_out = visualize(value, model, None, None)

        self.assertIn('segment-menu-panel', html_out)
        self.assertIn('Convert to Literal', html_out)
        self.assertNotIn('Split here', html_out)

    def test_no_split_when_clicked_on_first_char(self):
        # Splitting before the first char would leave an empty left half.
        model = self._open_menu("hello world", r"r'(hello)'", 1)
        html_out = visualize("hello world", model, None, None)

        self.assertIn('Remove segment', html_out)
        self.assertNotIn('Split here', html_out)

    def test_menu_renders_only_on_its_match(self):
        # 'foo bar foo': the second 'foo' is internal 9-11.
        value = 'foo bar foo'
        model = self._open_menu(value, r"r'(foo)'", 10)
        self.assertEqual(model['openDropdown']['id'], 'segment-menu-1-0')

        html_out = visualize(value, model, None, None)
        self.assertEqual(html_out.count('segment-menu-panel'), 1)

    def test_open_menu_forces_segment_labels_active(self):
        # With the menu open, its segment shows its labels like a hovered one.
        model = self._open_menu("hello world", r"r'(hello)'", 3)
        html_out = visualize("hello world", model, None, None)

        self.assertIn('repetition-0-0', html_out)

    def test_menu_panel_is_anchored_at_the_clicked_char(self):
        # The panel hangs off the char that was clicked, not the segment's
        # first char, so it lands under that char's split-point caret.
        model = self._open_menu("hello world", r"r'(hello)'", 3)
        html_out = visualize("hello world", model, None, None)

        after_panel = html_out[html_out.index('segment-menu-panel'):]
        m = re.search(r'snc-idx="(\d+)"', after_panel)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), '3')

    def test_clicked_char_is_marked_as_split_point(self):
        # The char the split would put at the head of the second half gets its
        # own span with a split-point class, so CSS can show the cut.
        model = self._open_menu("hello world", r"r'(hello)'", 3)
        html_out = visualize("hello world", model, None, None)

        m = re.search(r'<span class="([^"]*)" snc-idx="3"', html_out)
        self.assertIsNotNone(m, "clicked char should render as its own span")
        self.assertEqual(m.group(1).split(),
                         ['chr', 'highlight', 'literal', 'is-interactive', 'split-point'])
        self.assertEqual(html_out.count('split-point'), 1)

    def test_no_split_point_when_split_not_offered(self):
        # First-char click: no split row, no split-point marker.
        model = self._open_menu("hello world", r"r'(hello)'", 1)
        html_out = visualize("hello world", model, None, None)
        self.assertNotIn('split-point', html_out)

        # Fuzzy menu: no split either.
        model = self._open_menu('a1b\na2b', r"r'(a)(.*)(b)'", 8)
        html_out = visualize('a1b\na2b', model, None, None)
        self.assertNotIn('split-point', html_out)


class TestRemoveSegment(unittest.TestCase):
    """Removing an internal segment extends its LEFT neighbor to consume the
    removed occurrence's span; the leftmost and rightmost segments just remove
    themselves."""

    def test_internal_removal_extends_left_neighbor(self):
        # (hello) absorbs the space \s+ realized, keeping (world).
        self.assertEqual(
            remove_segment(r"r'(hello)(\s+)(world)'", 1, "hello world"),
            r"r'(hello\ )(world)'")

    def test_internal_removal_with_fuzzy_left_neighbor_reinfers(self):
        # 'a12yc': \d* consumes (y)'s span and is re-inferred over '12y';
        # lazy because the wider class could swallow the (c) that follows.
        self.assertEqual(
            remove_segment(r"r'(a)(\d*)(y)(c)'", 2, 'a12yc'),
            r"r'a[A-Za-z0-9]*?c'")

    def test_last_segment_removal_drops_just_it(self):
        self.assertEqual(
            remove_segment(r"r'(hello)(\s+)(world)'", 2, "hello world"),
            r"r'hello\s+'")

    def test_leftmost_removes_only_itself(self):
        self.assertEqual(
            remove_segment(r"r'(hello)(\s+)(world)'", 0, "hello world"),
            r"r'\s+world'")

    def test_only_segment_removes_everything(self):
        self.assertIsNone(remove_segment(r"r'(hello)'", 0, "hello world"))

    def test_new_trailing_lazy_fuzzy_is_delazified(self):
        # The laziness only existed to keep .*? from overrunning (world),
        # which is gone now.
        self.assertEqual(
            remove_segment(r"r'(hello)(.*?)(world)'", 2, "hello world"),
            r"r'hello.*'")

    def test_internal_removal_on_later_match_uses_that_matchs_span(self):
        # 'a1b a22b': the second match's \d* realizes '22' at internal 6-8.
        self.assertEqual(
            remove_segment(r"r'(a)(\d*)(b)'", 1, 'a1b a22b', match_index=1),
            r"r'(a22)(b)'")

    def test_flags_preserved(self):
        self.assertEqual(
            remove_segment(r"r'(hello)(\s+)(world)'i", 1, "hello world"),
            r"r'(hello\ )(world)'i")

    def test_capture_groups_flag_keeps_groups(self):
        self.assertEqual(remove_segment(r"r'(hello)(\s+)'c", 1, "hello world"),
                         r"r'(hello)'c")


class TestSplitLiteralSegment(unittest.TestCase):
    """Splitting a literal makes two literal segments; the clicked character
    starts the second one."""

    def test_split_before_clicked_char(self):
        # "hello world": (hello) spans internal 1-6; split at 3 -> he + llo.
        self.assertEqual(
            split_literal_segment(r"r'(hello)'", 0, "hello world", 1, 3, 6),
            r"r'(he)(llo)'")

    def test_split_round_trips_as_two_segments(self):
        result = split_literal_segment(r"r'(hello)'", 0, "hello world", 1, 3, 6)
        inner = get_regex_inner_pattern(result)
        self.assertEqual(len(parse_all_segments(inner)), 2)

    def test_split_at_segment_start_returns_unchanged(self):
        self.assertEqual(
            split_literal_segment(r"r'(hello)'", 0, "hello world", 1, 1, 6),
            r"r'(hello)'")

    def test_split_middle_segment_keeps_neighbors(self):
        # "hello world": 'world' spans internal 7-12; split at 10 -> wor + ld.
        self.assertEqual(
            split_literal_segment(r"r'hello\s*world'", 2, "hello world", 7, 10, 12),
            r"r'hello\s*(wor)(ld)'")

    def test_split_escapes_special_chars(self):
        # "xa.by": (a\.b) spans internal 2-5; split at 3 -> a + \.b.
        self.assertEqual(
            split_literal_segment(r"r'(a\.b)'", 0, "xa.by", 2, 3, 5),
            r"r'(a)(\.b)'")


class TestSegmentMenuActions(unittest.TestCase):
    """The three menu rows, driven end-to-end through MouseDown + DropdownSelect."""

    var_and_exp = ('x', 'x')

    def _menu_select(self, value, search, click_idx, option):
        model = init_model(value)
        model['search'] = search
        model, _ = update(make_mouse_down_event(click_idx, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertIsNotNone(model.get('openDropdown'), 'menu did not open')
        model, _ = update(make_dropdown_select_event(model['openDropdown']['id'], option),
                          self.var_and_exp, model, value)
        return model

    def test_remove_middle_segment_extends_left_neighbor(self):
        # Click inside '\ ' (internal 6): (hello) absorbs the space.
        model = self._menu_select('hello world', r"r'(hello)(\ )(world)'", 6, 'remove')
        self.assertEqual(model['search'], r"r'(hello\ )(world)'")
        self.assertIsNone(model.get('openDropdown'))

    def test_remove_internal_on_later_match_consumes_that_matchs_text(self):
        # 'a1b a22b': click the second match's \d* (internal 6): (a) absorbs '22'.
        model = self._menu_select('a1b a22b', r"r'(a)(\d*)(b)'", 6, 'remove')
        self.assertEqual(model['search'], r"r'(a22)(b)'")

    def test_remove_leftmost_removes_only_itself(self):
        model = self._menu_select('hello world', r"r'(hello)(\ )(world)'", 3, 'remove')
        self.assertEqual(model['search'], r"r'(\ )(world)'")

    def test_remove_rightmost_removes_only_itself(self):
        model = self._menu_select('hello world', r"r'(hello)(\ )(world)'", 8, 'remove')
        self.assertEqual(model['search'], r"r'(hello)(\ )'")

    def test_remove_only_segment_clears_search(self):
        model = self._menu_select('hello world', r"r'(hello)'", 3, 'remove')
        self.assertIsNone(model['search'])

    def test_convert_literal_to_fuzzy_uses_inference(self):
        # The middle '1' abuts segments on both sides, so inference gets
        # None/None boundary context and picks a * quantifier.
        model = self._menu_select('a1b', r"r'(a)(1)(b)'", 2, 'convert')
        self.assertEqual(model['search'], r"r'(a)(\d*)(b)'")

    def test_convert_single_literal_to_fuzzy_uses_string_context(self):
        # 'hello' has no neighbors: string start on the left, ' ' on the right.
        model = self._menu_select('hello world', r"r'(hello)'", 3, 'convert')
        self.assertEqual(model['search'], r"r'([a-z]+)'")

    def test_convert_fuzzy_to_literal_uses_matched_text(self):
        model = self._menu_select('a1b', r"r'(a)(\d*)(b)'", 2, 'convert')
        self.assertEqual(model['search'], r"r'(a)(1)(b)'")

    def test_convert_on_later_match_uses_that_matchs_text(self):
        # 'a1b a2b': the second match's \d* realizes '2' at internal 6.
        model = self._menu_select('a1b a2b', r"r'(a)(\d*)(b)'", 6, 'convert')
        self.assertEqual(model['search'], r"r'(a)(2)(b)'")

    def test_split_action(self):
        model = self._menu_select('hello world', r"r'(hello)'", 3, 'split')
        self.assertEqual(model['search'], r"r'(he)(llo)'")
        self.assertIsNone(model.get('openDropdown'))

    def test_action_pushes_undo_and_undo_restores(self):
        model = self._menu_select('hello world', r"r'(hello)'", 3, 'split')
        self.assertEqual(model['undoHistory'][-1], r"r'(hello)'")

        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, 'hello world')
        self.assertEqual(model['search'], r"r'(hello)'")


# =============================================================================
# Keyboard Event Tests
# =============================================================================

class TestKeyboardEvents(unittest.TestCase):
    """Test keyboard events: Escape, Enter, Cmd-Z, Cmd-Shift-Z."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def _create_hello_selection(self, model):
        """Helper to create /(hello)/ selection."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                         self.var_and_exp, model, self.value)
        return model

    def test_escape_clears_selection(self):
        """Escape key clears the selection and saves to undo."""
        model = self._create_hello_selection(self.model)
        self.assertEqual(model['search'], r"r'hello'")

        model, commands = update(make_key_down_event('Escape'),
                                self.var_and_exp, model, self.value)

        self.assertIsNone(model['search'])
        self.assertIsNone(model['anchorIdx'])
        self.assertIsNone(model['cursorIdx'])
        self.assertFalse(model['dragging'])
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])
        self.assertEqual(commands, [])

    def test_selection_auto_inserts_find_code(self):
        """Finalizing a selection auto-inserts the find LOC and links it."""
        model = init_model(self.value)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, commands = update(make_mouse_up_event(6),
                                 self.var_and_exp, model, self.value)

        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertEqual(expr, "re.findall(r'hello', x, flags=re.M)")
        self.assertEqual(model['linked_action'], 'match_strings')

    def test_enter_skips_unchanged_linked_expression(self):
        """After auto-link, Enter with the same find expr emits no ChangeSelectedText."""
        model = self._create_hello_selection(self.model)

        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, model, self.value)

        self.assertEqual(commands, [])
        self.assertEqual(model['linked_action'], 'match_strings')

    def test_enter_without_selection_does_nothing(self):
        """Enter without selection produces no commands."""
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)

        self.assertEqual(commands, [])

    def test_backspace_switches_linked_action_to_delete(self):
        """After auto-link, Cmd-Backspace switches the linked action to delete."""
        model = self._create_hello_selection(self.model)

        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, model, self.value)

        self.assertEqual(model['linked_action'], 'delete')
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertIn("re.sub(r'hello', '', x, flags=re.M)", commands[0].expression)

    def test_backspace_without_selection_does_nothing(self):
        """Backspace without selection produces no commands."""
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)

        self.assertEqual(commands, [])

    def test_cmd_z_undoes_selection(self):
        """Cmd-Z undoes the last selection."""
        model = self._create_hello_selection(self.model)

        # Add fuzzy segment
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])

        # Undo
        model, commands = update(make_key_down_event('z', meta_key=True),
                                self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")
        self.assertEqual(model['undoHistory'], [None])
        self.assertEqual(model['redoHistory'], [r"r'hello\s*'"])
        # Undo while linked re-syncs the linked LOC to the restored pattern.
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)

    def test_cmd_shift_z_redoes_selection(self):
        """Cmd-Shift-Z redoes the undone selection."""
        model = self._create_hello_selection(self.model)

        # Add fuzzy segment
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         self.var_and_exp, model, self.value)

        # Undo
        model, _ = update(make_key_down_event('z', meta_key=True),
                         self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

        # Redo
        model, commands = update(make_key_down_event('z', meta_key=True, shift_key=True),
                                self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])
        self.assertEqual(model['redoHistory'], [])
        # Redo while linked re-syncs the linked LOC to the restored pattern.
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)

    def test_undo_with_empty_history_does_nothing(self):
        """Cmd-Z with empty undo history does nothing."""
        model, commands = update(make_key_down_event('z', meta_key=True),
                                self.var_and_exp, self.model, self.value)

        self.assertIsNone(model['search'])
        self.assertEqual(model['undoHistory'], [])
        self.assertEqual(commands, [])

    def test_redo_with_empty_history_does_nothing(self):
        """Cmd-Shift-Z with empty redo history does nothing."""
        model, commands = update(make_key_down_event('z', meta_key=True, shift_key=True),
                                self.var_and_exp, self.model, self.value)

        self.assertIsNone(model['search'])
        self.assertEqual(commands, [])


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases: anchors, newlines, mouse released outside."""

    def test_selection_starting_at_visible_start_anchor(self):
        """Selection from index 0 includes ^ anchor -> /(^he)/."""
        value = "hello"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select indices 0-2: ^(0), h(1), e(2)
        model, _ = update(make_mouse_down_event(0, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(2, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(2, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'^he'")

    def test_selection_starting_at_first_char(self):
        """Selection from first visible char excludes the ^ anchor."""
        value = "hello"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select indices 1-3: h(1), e(2), l(3)
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(3, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(3, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hel'")

    def test_selection_with_newlines_before_newline(self):
        """Selection of 'hello' in 'hello\\nworld' -> /(hello)/."""
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Augmented: 0=^, 1=h, 2=e, 3=l, 4=l, 5=o, 6=$, 7=\n, 8=^, 9=w...
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hello'")

    def test_selection_across_newline(self):
        """Selection spanning newline in 'hi\\nbye' -> /(hi$\\n^b)/."""
        value = "hi\nbye"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Augmented: 0=^, 1=h, 2=i, 3=$, 4=\n, 5=^, 6=b, 7=y, 8=e, 9=$
        # Select indices 1-6: h(1), i(2), $(3), \n(4), ^(5), b(6)
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hi$\n^b'")

    def test_mouse_released_outside_widget(self):
        """MouseMove with buttons=0 finalizes segment."""
        value = "hello"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Start drag
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(4, legacy_index=False),
                         var_and_exp, model, value)

        self.assertTrue(model['dragging'])

        # Mouse released outside (buttons=0)
        model, _ = update(make_mouse_move_event(4, legacy_index=False, buttons=0),
                         var_and_exp, model, value)

        self.assertFalse(model['dragging'])
        self.assertEqual(model['search'], r"r'hell'")

    def test_empty_string_anchor_selection(self):
        """Selection on empty string selects visible anchors -> /(^$)/."""
        value = ""
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Augmented for "": 0=^, 1=$
        model, _ = update(make_mouse_down_event(0, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(1, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(1, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'^$'")

    def test_fresh_click_resets_selection(self):
        """Clicking away from extension points resets selection."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Create initial selection
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hello'")

        # Click somewhere NOT an extension point (index 9 = 'r' in world)
        model, _ = update(make_mouse_down_event(9, legacy_index=False, top_half=True),
                         var_and_exp, model, value)

        # Selection should be reset, new drag started (no flags to preserve)
        self.assertIsNone(model['search'])
        self.assertEqual(model['anchorIdx'], 9)
        self.assertTrue(model['dragging'])

    def test_fresh_drag_preserves_case_insensitive_flag(self):
        """A fresh drag with /hello/i preserves the i flag as ``i."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Create selection with case-insensitive flag
        model['search'] = r"r'hello'i"

        # Click somewhere NOT an extension point to start fresh drag
        model, _ = update(make_mouse_down_event(9, legacy_index=False, top_half=True),
                         var_and_exp, model, value)

        # Flags should be preserved as bare backtick form
        self.assertEqual(model['search'], '``i')
        self.assertTrue(model['dragging'])

    def test_fresh_drag_preserves_multiple_flags(self):
        """A fresh drag with /hello/i1 preserves both flags as ``i1."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model['search'] = r"r'hello'i1"

        model, _ = update(make_mouse_down_event(9, legacy_index=False, top_half=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], '``i1')

    def test_fresh_drag_then_select_builds_regex_with_preserved_flags(self):
        """After fresh drag preserving flags, completing selection carries flags to new regex."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model['search'] = r"r'hello'i"

        # Fresh drag on "world" (indices 7-11)
        model, _ = update(make_mouse_down_event(7, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(11, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(11, legacy_index=False),
                         var_and_exp, model, value)

        # New regex should have the i flag preserved
        self.assertEqual(model['search'], r"r'world'i")

    def test_bare_flags_preserved_across_toggle_then_drag(self):
        """Toggle 1st with no search, then drag should carry flag to new regex."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Toggle 1st with no search
        model, _ = update(make_first_match_toggle_event(),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], '``1')

        # Drag to select "hello" (indices 1-5)
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5, legacy_index=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5, legacy_index=False),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hello'1")


# =============================================================================
# Two-Phase Matching Tests (verify the fix works correctly)
# =============================================================================

class TestTwoPhaseMatching(unittest.TestCase):
    """
    Tests verifying that the two-phase matching approach works correctly.

    The fix matches regex patterns against the ORIGINAL string (not augmented),
    then translates positions to internal visual indices. This ensures regex
    patterns behave correctly for patterns involving newlines, quantifiers, etc.
    """

    def test_newline_plus_matches_consecutive_newlines(self):
        """
        A pattern with \\n+ should correctly match consecutive newlines
        and return proper internal indices for highlighting.
        """
        string_value = "a\n\nb"
        # Pattern matches both newlines
        # In original: \n\n is at positions 1-3 (string indices)
        # Internal indices: ^=0, a=1, $=2, \n=3, ^=4, $=5, \n=6, ^=7, b=8, $=9
        # The two \n chars are at internal 3 and 6

        highlights = parse_regex_for_highlighting(r"r'(\n+)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]

        # Should span both newlines
        # First \n is at string index 1 -> internal 3
        # Second \n is at string index 2 -> internal 6
        # End should be after second \n (including ^ marker) -> 8
        self.assertEqual(seg_type, 'literal')
        self.assertEqual(start, 3)  # First \n
        self.assertEqual(end, 8)    # After second \n and its ^ marker

    def test_literal_two_newlines_matches(self):
        """
        A pattern with literal \\n\\n should match two consecutive newlines.
        """
        string_value = "a\n\nb"
        highlights = parse_regex_for_highlighting(r"r'(\n\n)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'literal')

    def test_newline_quantifier_matches(self):
        """
        A pattern with \\n{2,3} should match 2-3 consecutive newlines.
        """
        string_value = "a\n\n\nb"  # Three newlines
        highlights = parse_regex_for_highlighting(r"r'(\n{2,3})'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'literal')

    def test_dot_plus_correct_span(self):
        """
        A pattern with .+ should match characters without being corrupted by sentinels.
        The internal index span should correspond to 5 characters.
        """
        string_value = "hello"
        # Internal indices: ^=0, h=1, e=2, l=3, l=4, o=5, $=6
        highlights = parse_regex_for_highlighting(r"r'(.+)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(start, 1)  # 'h' at internal index 1
        self.assertEqual(end, 6)    # After 'o' at internal index 5, so end is 6

    def test_backreference_matches_correctly(self):
        """
        A pattern with backreference (.)\\1 should find repeated chars correctly.
        """
        string_value = "xaay"
        # Internal indices: ^=0, x=1, a=2, a=3, y=4, $=5
        highlights = parse_regex_for_highlighting(r"r'((.)\2)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # "aa" is at string positions 1-3, internal indices 2-4
        self.assertEqual(start, 2)  # First 'a'
        self.assertEqual(end, 4)    # After second 'a'

    def test_lookbehind_newline_works(self):
        """
        A pattern with (?<=\\n)x should match 'x' after a newline.
        """
        string_value = "a\nxb"
        # Internal indices: ^=0, a=1, $=2, \n=3, ^=4, x=5, b=6, $=7
        highlights = parse_regex_for_highlighting(r"r'((?<=\n)x)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # 'x' is at string index 2, internal index 5
        self.assertEqual(start, 5)
        self.assertEqual(end, 6)

    def test_lookahead_before_newline_works(self):
        """
        A pattern with x(?=\\n) should match 'x' before a newline.
        """
        string_value = "ax\nb"
        # Internal indices: ^=0, a=1, x=2, $=3, \n=4, ^=5, b=6, $=7
        highlights = parse_regex_for_highlighting(r"r'(x(?=\n))'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # 'x' is at string index 1, internal index 2
        self.assertEqual(start, 2)
        self.assertEqual(end, 3)

    def test_word_boundary_correct_positions(self):
        """
        A pattern with word boundaries should return correct internal positions.
        """
        string_value = "hello world"
        # Internal indices: ^=0, h=1, e=2, l=3, l=4, o=5, ' '=6, w=7, o=8, r=9, l=10, d=11, $=12
        highlights = parse_regex_for_highlighting(r"r'(\bworld\b)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # "world" is at string positions 6-11, internal indices 7-12
        self.assertEqual(start, 7)   # 'w'
        self.assertEqual(end, 12)    # After 'd'

    def test_newline_followed_by_text(self):
        """
        A pattern with \\n followed by text should match correctly.
        """
        string_value = "hello\nworld"
        # Internal: ^=0, h=1, e=2, l=3, l=4, o=5, $=6, \n=7, ^=8, w=9, o=10, r=11, l=12, d=13, $=14
        highlights = parse_regex_for_highlighting(r"r'(\nworld)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # \n is at string index 5 -> internal 7
        # "world" ends at string index 10 -> internal 13
        self.assertEqual(start, 7)   # \n
        self.assertEqual(end, 14)    # After 'd'

    def test_fuzzy_pattern_identified_correctly(self):
        """
        A pattern with (.*) should be identified as fuzzy.
        """
        string_value = "hello world"
        highlights = parse_regex_for_highlighting(r"r'(hello)(.*)(world)'", string_value)
        self.assertEqual(len(highlights), 3)
        self.assertEqual(highlights[0][2], 'literal')  # hello
        self.assertEqual(highlights[1][2], 'fuzzy')    # (.*)
        self.assertEqual(highlights[2][2], 'literal')  # world

    def test_anchor_at_start_of_string(self):
        """
        A pattern starting with \\A should map to the visible start anchor highlight.
        """
        string_value = "hello"
        # Use single backslash for the \A anchor in the regex pattern
        highlights = parse_regex_for_highlighting(r"r'(\Ahello)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        # Should start at internal index 0 (^ position)
        self.assertEqual(start, 0)

    def test_caret_at_string_start_includes_marker(self):
        """^ matching at the very start highlights the visible ^ marker."""
        string_value = "abcdef\nghijk"
        # Internal: ^=0, a=1 ... f=6, $=7, \n=8, ^=9, g=10 ... k=14, $=15
        highlights = parse_regex_for_highlighting(r"r'(^a)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 0)
        self.assertEqual(end, 2)

    def test_caret_at_line_start_includes_marker(self):
        """^ matching after a newline highlights that line's ^ marker too."""
        string_value = "abcdef\nghijk"
        # Internal: ^=0, a=1 ... f=6, $=7, \n=8, ^=9, g=10 ... k=14, $=15
        highlights = parse_regex_for_highlighting(r"r'(^g)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 9)   # the line-2 ^ marker
        self.assertEqual(end, 11)    # through 'g'

    def test_lone_caret_group_at_line_start_highlights_marker(self):
        """A zero-width (^) group at a line start highlights the ^ marker, not
        the character after it."""
        string_value = "abcdef\nghijk"
        highlights = parse_regex_for_highlighting(r"r'(^)(g)'", string_value)
        self.assertEqual(len(highlights), 2)
        caret_start, caret_end, _, _, _, _, _ = highlights[0]
        self.assertEqual(caret_start, 9)
        self.assertEqual(caret_end, 10)
        g_start, g_end, _, _, _, _, _ = highlights[1]
        self.assertEqual((g_start, g_end), (10, 11))

    def test_dollar_at_line_end_includes_marker(self):
        """A literal drag can produce r'def$'; the line's $ marker highlights."""
        string_value = "abcdef\nghijk"
        # Internal: ^=0, a=1 ... f=6, $=7, \n=8, ^=9, g=10 ... k=14, $=15
        highlights = parse_regex_for_highlighting(r"r'(def$)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 4)
        self.assertEqual(end, 8)     # through the $ marker at 7

    def test_dollar_at_string_end_includes_marker(self):
        """$ matching at the very end highlights the trailing $ marker."""
        string_value = "abcdef\nghijk"
        highlights = parse_regex_for_highlighting(r"r'(ijk$)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 12)
        self.assertEqual(end, 16)    # through the trailing $ marker at 15

    def test_lone_dollar_group_at_line_end_highlights_marker(self):
        """A zero-width ($) group highlights the $ marker itself."""
        string_value = "abcdef\nghijk"
        highlights = parse_regex_for_highlighting(r"r'(f)($)'", string_value)
        self.assertEqual(len(highlights), 2)
        self.assertEqual((highlights[0][0], highlights[0][1]), (6, 7))
        self.assertEqual((highlights[1][0], highlights[1][1]), (7, 8))

    def test_caret_and_dollar_spanning_whole_line(self):
        """^...$ around a full line highlights both anchor markers."""
        string_value = "abcdef\nghijk"
        highlights = parse_regex_for_highlighting(r"r'(^ghijk$)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 9)   # line-2 ^ marker
        self.assertEqual(end, 16)    # through the trailing $ marker

    def test_dollar_on_empty_line_includes_marker(self):
        r"""\n$ ending at an empty line's $ includes that line's $ marker."""
        string_value = "a\n\nb"
        # Internal: ^=0, a=1, $=2, \n=3, ^=4, $=5, \n=6, ^=7, b=8, $=9
        # \n$ matches the first \n (str 1..2), whose $ lands on the empty line.
        highlights = parse_regex_for_highlighting(r"r'(\n$)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 3)   # the \n
        self.assertEqual(end, 6)     # through the empty line's $ marker at 5

    def test_caret_on_empty_line_includes_marker(self):
        """^ matching an empty line's start highlights that line's ^ marker."""
        string_value = "a\n\nb"
        # Internal: ^=0, a=1, $=2, \n=3, ^=4, $=5, \n=6, ^=7, b=8, $=9
        # ^\n only matches at string pos 2 (the empty line's own \n).
        highlights = parse_regex_for_highlighting(r"r'(^\n)'", string_value)
        self.assertEqual(len(highlights), 1)
        start, end, _, _, _, _, _ = highlights[0]
        self.assertEqual(start, 4)   # the empty line's ^ marker
        self.assertEqual(end, 8)     # through the \n and its trailing ^ marker


# =============================================================================
# Internal Index Computation Tests
# =============================================================================

class TestComputeInternalLength(unittest.TestCase):
    """Tests for compute_internal_length function."""

    def test_empty_string(self):
        """Empty string has 2 internal positions: ^, $."""
        self.assertEqual(compute_internal_length(""), 2)

    def test_single_char(self):
        """Single char: ^, char, $ = 3."""
        self.assertEqual(compute_internal_length("a"), 3)

    def test_simple_string(self):
        """'hello' = 2 + 5 + 0 = 7."""
        self.assertEqual(compute_internal_length("hello"), 7)

    def test_string_with_newline(self):
        """'hi\\nbye' = 2 + 6 + 2*1 = 10."""
        # Internal: ^(0), h(1), i(2), $(3), \n(4), ^(5), b(6), y(7), e(8), $(9)
        self.assertEqual(compute_internal_length("hi\nbye"), 10)

    def test_string_with_multiple_newlines(self):
        """'a\\n\\nb' = 2 + 4 + 2*2 = 10."""
        self.assertEqual(compute_internal_length("a\n\nb"), 10)

    def test_only_newline(self):
        """'\\n' = 2 + 1 + 2 = 5."""
        self.assertEqual(compute_internal_length("\n"), 5)


class TestExtractByInternalIndices(unittest.TestCase):
    """Tests for extract_by_internal_indices function."""

    def test_extract_visible_start_anchor(self):
        """Extract ^ anchor at index 0."""
        result = extract_by_internal_indices("hello", 0, 1)
        self.assertEqual(result, DC2)  # ^ sentinel

    def test_extract_first_char(self):
        """Extract first character at index 1."""
        result = extract_by_internal_indices("hello", 1, 2)
        self.assertEqual(result, "h")

    def test_extract_substring(self):
        """Extract 'ell' from 'hello'."""
        # Internal: ^(0), h(1), e(2), l(3), l(4), o(5), $(6)
        result = extract_by_internal_indices("hello", 2, 5)
        self.assertEqual(result, "ell")

    def test_extract_with_trailing_anchor(self):
        """Extract including $ anchor."""
        result = extract_by_internal_indices("hi", 3, 4)
        self.assertEqual(result, DC3)  # $ sentinel

    def test_extract_across_newline(self):
        """Extract text spanning a newline."""
        # Internal: ^(0), h(1), i(2), $(3), \n(4), ^(5), b(6), y(7), e(8), $(9)
        result = extract_by_internal_indices("hi\nbye", 2, 7)
        # Should get: i, $, \n, ^, b
        self.assertEqual(result, "i" + DC3 + "\n" + DC2 + "b")

    def test_extract_empty_range(self):
        """Empty range returns empty string."""
        result = extract_by_internal_indices("hello", 3, 3)
        self.assertEqual(result, "")

    def test_extract_full_string_with_anchors(self):
        """Extract entire augmented representation."""
        # For "ab": ^(0), a(1), b(2), $(3) - length 4
        result = extract_by_internal_indices("ab", 0, 4)
        self.assertEqual(result, DC2 + "ab" + DC3)


# =============================================================================
# Dropdown Tests
# =============================================================================

def make_dropdown_toggle_event(dropdown_id: str) -> dict:
    """Create a DropdownToggle event dict."""
    return {
        'pythonEventStr': repr(DropdownToggle(dropdown_id)),
        'eventJSON': {}
    }


def make_dropdown_select_event(dropdown_id: str, option_value: str) -> dict:
    """Create a DropdownSelect event dict."""
    return {
        'pythonEventStr': repr(DropdownSelect(dropdown_id, option_value)),
        'eventJSON': {}
    }


class TestDropdownToggle(unittest.TestCase):
    """Tests for dropdown toggle functionality."""

    def test_dropdown_toggle_opens_dropdown(self):
        """DropdownToggle opens the dropdown when it's closed."""
        model = init_model("hello")
        self.assertIsNone(model.get('openDropdown'))

        event = make_dropdown_toggle_event('fuzzy-pattern-0')
        model, _ = update(event, None, model, "hello")

        self.assertIsNotNone(model.get('openDropdown'))
        self.assertEqual(model['openDropdown']['id'], 'fuzzy-pattern-0')
        self.assertEqual(model['openDropdown']['segmentIndex'], 0)

    def test_dropdown_toggle_closes_dropdown(self):
        """DropdownToggle closes the dropdown when it's already open."""
        model = init_model("hello")
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_dropdown_toggle_event('fuzzy-pattern-0')
        model, _ = update(event, None, model, "hello")

        self.assertIsNone(model.get('openDropdown'))

    def test_dropdown_toggle_switches_dropdown(self):
        """DropdownToggle on a different dropdown closes the old one and opens the new."""
        model = init_model("hello")
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_dropdown_toggle_event('fuzzy-pattern-1')
        model, _ = update(event, None, model, "hello")

        self.assertIsNotNone(model.get('openDropdown'))
        self.assertEqual(model['openDropdown']['id'], 'fuzzy-pattern-1')
        self.assertEqual(model['openDropdown']['segmentIndex'], 1)

    def test_dropdown_parses_segment_index_from_id(self):
        """Segment index is correctly parsed from dropdown ID."""
        model = init_model("hello")

        event = make_dropdown_toggle_event('fuzzy-pattern-5')
        model, _ = update(event, None, model, "hello")

        self.assertEqual(model['openDropdown']['segmentIndex'], 5)


class TestDropdownSelect(unittest.TestCase):
    """Tests for dropdown selection functionality."""

    def test_dropdown_select_updates_regex_pattern(self):
        """Selecting a character class from dropdown updates the regex, preserving quantifier."""
        model = init_model("hello world")
        # Set up a regex with a fuzzy segment (.* has * quantifier)
        model['search'] = r"r'(hello)(.*)(world)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-1', 'segmentIndex': 1}

        # Select \s (character class only, no quantifier)
        event = make_dropdown_select_event('fuzzy-pattern-1', r'\s')
        model, _ = update(event, None, model, "hello world")

        # Result should be \s* (preserves the * from .*)
        self.assertEqual(model['search'], r"r'hello\s*world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_dropdown_select_closes_dropdown(self):
        """Selecting a pattern closes the dropdown."""
        model = init_model("test")
        model['search'] = r"r'(.*)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_dropdown_select_event('fuzzy-pattern-0', r'\d*')
        model, _ = update(event, None, model, "test")

        self.assertIsNone(model.get('openDropdown'))

    def test_dropdown_select_adds_to_undo_history(self):
        """Selecting a pattern saves the previous regex to undo history."""
        model = init_model("test")
        model['search'] = r"r'(.*)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        # Select \w (character class only), quantifier * is preserved
        event = make_dropdown_select_event('fuzzy-pattern-0', r'\w')
        model, _ = update(event, None, model, "test")

        self.assertEqual(model['undoHistory'], [r"r'(.*)'"]),
        self.assertEqual(model['search'], r"r'\w*'")

    def test_dropdown_select_ignores_wrong_dropdown_id(self):
        """Selection is ignored if dropdown ID doesn't match open dropdown."""
        model = init_model("test")
        model['search'] = r"r'(.*)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_dropdown_select_event('fuzzy-pattern-1', r'\d*')
        model, _ = update(event, None, model, "test")

        # Regex should remain unchanged
        self.assertEqual(model['search'], r"r'(.*)'")
        # But dropdown should still close
        self.assertIsNone(model.get('openDropdown'))


class TestDropdownCloseBehavior(unittest.TestCase):
    """Tests for dropdown close behavior on other events."""

    def test_mouse_down_closes_dropdown(self):
        """MouseDown on a character closes any open dropdown."""
        model = init_model("hello")
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_mouse_down_event(3, top_half=True)
        model, _ = update(event, None, model, "hello")

        self.assertIsNone(model.get('openDropdown'))

    def test_escape_closes_dropdown_first(self):
        """Escape closes dropdown without clearing selection."""
        model = init_model("hello")
        model['search'] = r"r'(hello)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0', 'segmentIndex': 0}

        event = make_key_down_event('Escape')
        model, _ = update(event, None, model, "hello")

        # Dropdown should be closed
        self.assertIsNone(model.get('openDropdown'))
        # But selection should remain
        self.assertEqual(model['search'], r"r'(hello)'")

    def test_escape_clears_selection_when_no_dropdown(self):
        """Escape clears selection when no dropdown is open."""
        model = init_model("hello")
        model['search'] = r"r'(hello)'"
        model['openDropdown'] = None

        event = make_key_down_event('Escape')
        model, _ = update(event, None, model, "hello")

        # Selection should be cleared
        self.assertIsNone(model.get('search'))


class TestExtractQuantifier(unittest.TestCase):
    """Tests for extract_quantifier function."""

    def test_extract_star(self):
        """Extract * quantifier from .*"""
        base, quant = extract_quantifier('.*')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '*')

    def test_extract_plus(self):
        """Extract + quantifier from \\s+"""
        base, quant = extract_quantifier(r'\s+')
        self.assertEqual(base, r'\s')
        self.assertEqual(quant, '+')

    def test_extract_question(self):
        """Extract ? quantifier from \\d?"""
        base, quant = extract_quantifier(r'\d?')
        self.assertEqual(base, r'\d')
        self.assertEqual(quant, '?')

    def test_extract_braced_range(self):
        """Extract {n,m} quantifier from [a-z]{2,5}"""
        base, quant = extract_quantifier('[a-z]{2,5}')
        self.assertEqual(base, '[a-z]')
        self.assertEqual(quant, '{2,5}')

    def test_extract_exact_count(self):
        """Extract {n} quantifier from \\w{3}"""
        base, quant = extract_quantifier(r'\w{3}')
        self.assertEqual(base, r'\w')
        self.assertEqual(quant, '{3}')

    def test_extract_min_only(self):
        """Extract {n,} quantifier from .{2,}"""
        base, quant = extract_quantifier('.{2,}')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '{2,}')

    def test_no_quantifier(self):
        """Pattern without quantifier returns empty string."""
        base, quant = extract_quantifier('.')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '')

    def test_character_class_no_quantifier(self):
        """Character class without quantifier."""
        base, quant = extract_quantifier('[a-z]')
        self.assertEqual(base, '[a-z]')
        self.assertEqual(quant, '')

    def test_lazy_star(self):
        """Extract *? lazy quantifier from .*?"""
        base, quant = extract_quantifier('.*?')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '*?')

    def test_lazy_plus(self):
        """Extract +? lazy quantifier from .+?"""
        base, quant = extract_quantifier('.+?')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '+?')

    def test_lazy_question(self):
        """Extract ?? lazy quantifier from .??"""
        base, quant = extract_quantifier('.??')
        self.assertEqual(base, '.')
        self.assertEqual(quant, '??')

    def test_lazy_braced(self):
        """Extract {n,m}? lazy quantifier."""
        base, quant = extract_quantifier('[a-z]{2,5}?')
        self.assertEqual(base, '[a-z]')
        self.assertEqual(quant, '{2,5}?')

    def test_lazy_with_char_class(self):
        """Extract lazy quantifier from character class pattern."""
        base, quant = extract_quantifier(r'\s*?')
        self.assertEqual(base, r'\s')
        self.assertEqual(quant, '*?')


class TestReplaceSegmentPattern(unittest.TestCase):
    """Tests for replace_segment_pattern function.

    replace_segment_pattern should only replace the character class,
    preserving the existing repetition quantifier.
    """

    def test_replace_preserves_star_quantifier(self):
        """Replacing .* with \s should give \s* (preserve *)."""
        result = replace_segment_pattern(r"r'(.*)(world)'", 0, r'\s')
        self.assertEqual(result, r"r'\s*world'")

    def test_replace_preserves_plus_quantifier(self):
        """Replacing .+ with \d should give \d+ (preserve +)."""
        result = replace_segment_pattern(r"r'(.+)(world)'", 0, r'\d')
        self.assertEqual(result, r"r'\d+world'")

    def test_replace_preserves_question_quantifier(self):
        """Replacing .? with \w should give \w? (preserve ?)."""
        result = replace_segment_pattern(r"r'(.?)(world)'", 0, r'\w')
        self.assertEqual(result, r"r'\w?world'")

    def test_replace_preserves_braced_quantifier(self):
        """Replacing .{2,5} with [a-z] should give [a-z]{2,5}."""
        result = replace_segment_pattern(r"r'(hello)(.{2,5})'", 1, r'[a-z]')
        self.assertEqual(result, r"r'hello[a-z]{2,5}'")

    def test_replace_preserves_exact_count_quantifier(self):
        """Replacing .{3} with \d should give \d{3}."""
        result = replace_segment_pattern(r"r'(.{3})'", 0, r'\d')
        self.assertEqual(result, r"r'\d{3}'")

    def test_replace_no_quantifier_adds_none(self):
        """Replacing (.) with \s should give (\s) - no quantifier added."""
        result = replace_segment_pattern(r"r'(.)'", 0, r'\s')
        self.assertEqual(result, r"r'\s'")

    def test_replace_character_class_preserves_quantifier(self):
        """Replacing [a-z]* with \d should give \d*."""
        result = replace_segment_pattern(r"r'([a-z]*)'", 0, r'\d')
        self.assertEqual(result, r"r'\d*'")

    def test_replace_middle_segment_preserves_quantifier(self):
        """Replace pattern of middle segment preserves its quantifier."""
        result = replace_segment_pattern(r"r'(hello)(.*)(world)'", 1, r'\s')
        self.assertEqual(result, r"r'hello\s*world'")

    def test_replace_out_of_bounds_index(self):
        """Out of bounds index leaves regex unchanged."""
        result = replace_segment_pattern(r"r'(hello)'", 5, r'\d')
        self.assertEqual(result, r"r'hello'")


class TestDropdownInVisualize(unittest.TestCase):
    """Tests for dropdown rendering in visualize function."""

    def test_visualize_renders_dropdown_trigger_for_fuzzy(self):
        """Fuzzy segments render with a clickable dropdown trigger when hovered."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)(.*)(world)'"
        # Segment labels (incl. the fuzzy-pattern dropdown trigger) are only
        # rendered while the segment is "active" (e.g. hovered).
        model['hoverIdx'] = 6  # the space char inside the (.*) segment

        html = visualize("hello world", model, None, None)

        # Should contain a dropdown toggle event for segment 1 (the fuzzy one)
        self.assertIn('DropdownToggle', html)
        self.assertIn('fuzzy-pattern-0-1', html)

    def test_visualize_renders_dropdown_options_when_open(self):
        """When dropdown is open, options are rendered."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)(.*)(world)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0-1', 'segmentIndex': 1,
                                 'matchIndex': 0}

        html = visualize("hello world", model, None, None)

        # Should contain dropdown select events for options
        self.assertIn('DropdownSelect', html)
        # Should contain some of the character class options (no quantifiers)
        self.assertIn(r'\s', html)
        self.assertIn(r'\d', html)


class TestPatternDisplay(unittest.TestCase):
    """Tests that regex patterns display correctly in UI overlays."""

    def test_word_char_displays_as_backslash_w(self):
        r"""The \w pattern should display as \w, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\w*)(!)'", 'hello!')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\w')

    def test_whitespace_displays_as_backslash_s(self):
        r"""The \s pattern should display as \s, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\s*)(world)'", '   world')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\s')

    def test_digit_displays_as_backslash_d(self):
        r"""The \d pattern should display as \d, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\d*)(!)'", '123!')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\d')

    def test_non_whitespace_displays_as_backslash_S(self):
        r"""The \S pattern should display as \S, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\S*)( )'", 'hello ')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\S')

    def test_non_digit_displays_as_backslash_D(self):
        r"""The \D pattern should display as \D, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\D*)(1)'", 'hello1')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\D')

    def test_non_word_displays_as_backslash_W(self):
        r"""The \W pattern should display as \W, not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(\W*)(a)'", '...a')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, r'\W')

    def test_character_range_displays_as_brackets(self):
        """Character class [a-z] should display as [a-z]."""
        highlights = parse_regex_for_highlighting(r"r'([a-z]*)(!)'", 'hello!')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, '[a-z]')

    def test_character_set_displays_as_brackets(self):
        """Character set [abc] should display as [abc]."""
        highlights = parse_regex_for_highlighting(r"r'([abc]*)(d)'", 'abcd')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, '[abc]')

    def test_dot_displays_as_dot(self):
        """The . pattern should display as . not [...]."""
        highlights = parse_regex_for_highlighting(r"r'(.)(!)(!)'", 'a!!')
        self.assertEqual(len(highlights), 3)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, '.')

    def test_literal_displays_correctly(self):
        """Literal patterns display as-is."""
        highlights = parse_regex_for_highlighting(r"r'(hello)(world)'", 'helloworld')
        self.assertEqual(len(highlights), 2)
        _, _, _, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(pattern_display, 'hello')


class TestFuzzyPatternRecognition(unittest.TestCase):
    """Tests that various wildcard patterns are recognized as fuzzy."""

    def test_dot_star_is_fuzzy(self):
        """The classic .* pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(.*)(world)'", 'hello world')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_whitespace_star_is_fuzzy(self):
        r"""The \s* pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(\s*)(world)'", '   world')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_digit_star_is_fuzzy(self):
        r"""The \d* pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(\d*)(world)'", '123world')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_word_char_star_is_fuzzy(self):
        r"""The \w* pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(\w*)(!)'", 'hello!')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_non_whitespace_star_is_fuzzy(self):
        r"""The \S* pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(\S*)( )'", 'hello ')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_character_class_star_is_fuzzy(self):
        """Character class with * like [a-z]* is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'([a-z]*)(!)'", 'hello!')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_character_class_plus_is_fuzzy(self):
        """Character class with + like [A-Z]+ is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'([A-Z]+)(!)'", 'HELLO!')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_dot_plus_is_fuzzy(self):
        """The .+ pattern is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(hello)(.+)'", 'hello world')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type, 'fuzzy')

    def test_single_dot_is_fuzzy(self):
        """A single . (any char) is fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(.)(ello)'", 'hello')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')

    def test_literal_text_is_not_fuzzy(self):
        """Literal text patterns are not fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(hello)(world)'", 'helloworld')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type1, _, _, _, _ = highlights[0]
        _, _, seg_type2, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type1, 'literal')
        self.assertEqual(seg_type2, 'literal')

    def test_escaped_special_chars_is_not_fuzzy(self):
        r"""Escaped special chars like \. are literal, not fuzzy."""
        highlights = parse_regex_for_highlighting(r"r'(hello)(\.)'", 'hello.')
        self.assertEqual(len(highlights), 2)
        _, _, seg_type, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type, 'literal')


# =============================================================================
# Synthesize Fuzzy Pattern Tests
# =============================================================================

class TestSynthesizeFuzzyPattern(unittest.TestCase):
    """Tests for synthesize_fuzzy_pattern() which picks the best regex pattern
    to match exactly the characters the user dragged over."""

    # ---- Step 1: + repetition with natural boundary ----

    def test_whitespace_at_boundary(self):
        r"""Whitespace followed by non-whitespace -> \s+."""
        result = synthesize_fuzzy_pattern("   ", next_char="w")
        self.assertEqual(result, r"\s+")

    def test_digits_at_boundary(self):
        r"""Digits followed by non-digit -> \d+."""
        result = synthesize_fuzzy_pattern("123", next_char="a")
        self.assertEqual(result, r"\d+")

    def test_lowercase_at_boundary(self):
        r"""Lowercase letters followed by space -> [a-z]+."""
        result = synthesize_fuzzy_pattern("abc", next_char=" ")
        self.assertEqual(result, r"[a-z]+")

    def test_uppercase_at_boundary(self):
        r"""Uppercase letters followed by space -> [A-Z]+."""
        result = synthesize_fuzzy_pattern("ABC", next_char=" ")
        self.assertEqual(result, r"[A-Z]+")

    def test_word_chars_at_boundary(self):
        r"""Mixed word chars followed by space -> \w+."""
        result = synthesize_fuzzy_pattern("heLLo_1", next_char=" ")
        self.assertEqual(result, r"\w+")

    def test_dot_plus_at_end_of_string(self):
        """Any text at end of string (no next char) -> first matching +."""
        # "abc" with no next char: \s fails, \d fails, [0-9\.] fails,
        # [a-z]+ matches with no overshoot since no next char
        result = synthesize_fuzzy_pattern("abc", next_char="")
        self.assertEqual(result, r"[a-z]+")

    def test_alphanumeric_at_boundary(self):
        r"""Alphanumeric chars followed by whitespace -> [A-Za-z0-9]+ (more specific than \S+)."""
        result = synthesize_fuzzy_pattern("abc123", next_char=" ")
        self.assertEqual(result, r"[A-Za-z0-9]+")

    def test_non_whitespace_at_boundary(self):
        r"""Non-whitespace with special chars followed by whitespace -> \S+."""
        result = synthesize_fuzzy_pattern("abc!@#", next_char=" ")
        self.assertEqual(result, r"\S+")

    def test_empty_text_returns_dot_star(self):
        """Empty drag text returns .*."""
        result = synthesize_fuzzy_pattern("", next_char="a")
        self.assertEqual(result, ".*")

    # ---- Step 1: + skipped when next_char also matches pattern ----

    def test_whitespace_not_at_boundary_skips_plus(self):
        r"""Whitespace followed by more whitespace -> can't use \s+, uses {n}."""
        result = synthesize_fuzzy_pattern("   ", next_char=" ")
        self.assertEqual(result, r"\s{3}")

    def test_digits_not_at_boundary_skips_plus(self):
        r"""Digits followed by more digits -> can't use \d+, uses {n}."""
        result = synthesize_fuzzy_pattern("12", next_char="3")
        self.assertEqual(result, r"\d{2}")

    def test_lowercase_not_at_boundary_skips_plus(self):
        r"""Lowercase followed by more lowercase -> can't use [a-z]+, uses {n}."""
        result = synthesize_fuzzy_pattern("hel", next_char="l")
        self.assertEqual(result, r"[a-z]{3}")

    # ---- Step 1: + skipped when prev_char also matches pattern ----

    def test_whitespace_prev_char_matches_skips_plus(self):
        r"""Whitespace preceded by more whitespace -> can't use \s+, uses {n}."""
        result = synthesize_fuzzy_pattern("   ", prev_char=" ", next_char="w")
        self.assertEqual(result, r"\s{3}")

    def test_digits_prev_char_matches_skips_plus(self):
        r"""Digits preceded by another digit -> can't use \d+, uses {n}."""
        result = synthesize_fuzzy_pattern("123", prev_char="0", next_char="a")
        self.assertEqual(result, r"\d{3}")

    def test_lowercase_prev_char_matches_skips_plus(self):
        r"""Lowercase preceded by more lowercase -> can't use [a-z]+, uses {n}."""
        result = synthesize_fuzzy_pattern("abc", prev_char="z", next_char=" ")
        self.assertEqual(result, r"[a-z]{3}")

    def test_prev_char_no_match_allows_plus(self):
        r"""Digits preceded by a letter (non-digit) -> \d+ is fine."""
        result = synthesize_fuzzy_pattern("123", prev_char="a", next_char="b")
        self.assertEqual(result, r"\d+")

    def test_both_edges_match_skips_plus(self):
        r"""Both prev and next match the pattern -> uses {n}."""
        result = synthesize_fuzzy_pattern("abc", prev_char="z", next_char="d")
        self.assertEqual(result, r"[a-z]{3}")

    # ---- Adjacent to existing literal (None) -> uses * ----

    def test_prev_char_none_uses_star(self):
        r"""prev_char=None means adjacent to literal on left -> \s*."""
        result = synthesize_fuzzy_pattern("   ", prev_char=None, next_char="w")
        self.assertEqual(result, r"\s*")

    def test_next_char_none_uses_star(self):
        r"""next_char=None means adjacent to literal on right -> \s*."""
        result = synthesize_fuzzy_pattern("   ", prev_char="a", next_char=None)
        self.assertEqual(result, r"\s*")

    def test_both_none_uses_star(self):
        r"""Both None (inserting between literals) -> \s*."""
        result = synthesize_fuzzy_pattern("   ", prev_char=None, next_char=None)
        self.assertEqual(result, r"\s*")

    def test_none_prev_still_checks_next_boundary(self):
        r"""prev_char=None but next_char matches pattern -> skips *, uses {n}."""
        result = synthesize_fuzzy_pattern("   ", prev_char=None, next_char=" ")
        self.assertEqual(result, r"\s{3}")

    def test_none_next_still_checks_prev_boundary(self):
        r"""next_char=None but prev_char matches pattern -> skips *, uses {n}."""
        result = synthesize_fuzzy_pattern("   ", prev_char=" ", next_char=None)
        self.assertEqual(result, r"\s{3}")

    # ---- Step 2: {n} repetition ----

    def test_mixed_text_uses_dot_n(self):
        """Mixed characters (letters+digits+space) with no anchored edge -> .{n}.

        With prev_char='' the left edge IS anchored, and the drag gets [^b]+
        instead -- see TestNegatedClassSynthesis.
        """
        result = synthesize_fuzzy_pattern("a1 ", prev_char="x", next_char="b")
        self.assertEqual(result, r".{3}")

    def test_single_char_with_same_next(self):
        r"""Single char 'l' followed by another 'l' -> [a-z]{1}."""
        result = synthesize_fuzzy_pattern("l", next_char="l")
        self.assertEqual(result, r"[a-z]{1}")

    def test_digits_and_dots(self):
        r"""'3.14' is all [0-9\.] followed by non-matching char -> [0-9\.]+."""
        result = synthesize_fuzzy_pattern("3.14", next_char=" ")
        self.assertEqual(result, r"[0-9\.]+")

    def test_digits_and_dots_not_at_boundary(self):
        r"""'3.14' followed by another digit -> [0-9\.]{4}."""
        result = synthesize_fuzzy_pattern("3.14", next_char="1")
        self.assertEqual(result, r"[0-9\.]{4}")

    # ---- Text with newlines ----

    def test_newline_text_uses_whitespace_plus(self):
        r"""Newline is whitespace, so '\n  ' with non-ws next -> \s+."""
        result = synthesize_fuzzy_pattern("\n  ", next_char="a")
        self.assertEqual(result, r"\s+")

    def test_mixed_with_newline_uses_bracket_n(self):
        r"""'a\nb' can't use .* (dot doesn't match \n), uses [\S\s]{3}.

        Again only once the left edge is unanchored; an anchored one gets
        [^ ]+ instead.
        """
        result = synthesize_fuzzy_pattern("a\nb", prev_char="x", next_char=" ")
        # . doesn't match \n, but [\S\s] does
        self.assertEqual(result, r"[\S\s]{3}")

    # ---- Integration: synthesized patterns are recognized as fuzzy ----

    def test_synthesized_plus_pattern_is_fuzzy_in_highlights(self):
        r"""\s+ pattern is recognized as fuzzy in highlighting."""
        highlights = parse_regex_for_highlighting(r"r'hello\s+world'", 'hello   world')
        self.assertEqual(len(highlights), 3)
        _, _, seg_type, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type, 'fuzzy')

    def test_synthesized_exact_n_pattern_is_fuzzy_in_highlights(self):
        r"""\d{3} pattern is recognized as fuzzy in highlighting."""
        highlights = parse_regex_for_highlighting(r"r'prefix\d{3}suffix'", 'prefix123suffix')
        self.assertEqual(len(highlights), 3)
        _, _, seg_type, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type, 'fuzzy')

    def test_synthesized_pattern_matches_exact_range(self):
        r"""Synthesized \s{3} matches exactly 3 spaces in context."""
        highlights = parse_regex_for_highlighting(r"r'hello\s{3}world'", 'hello   world')
        self.assertEqual(len(highlights), 3)
        # The fuzzy segment should cover exactly 3 characters
        fuzzy_start, fuzzy_end, seg_type, _, _, _, _ = highlights[1]
        self.assertEqual(seg_type, 'fuzzy')
        self.assertEqual(fuzzy_end - fuzzy_start, 3)


# =============================================================================
# Negated character class [^N]
# =============================================================================

class TestNegatedClassDisplay(unittest.TestCase):
    r"""A ONE-character negated class parses to NOT_LITERAL, not IN.

    Multi-character classes like [^,;] come back as IN [NEGATE, ...] and have
    always read back correctly, which is why this never surfaced -- but every
    class the fuzzy inference generates is exactly one character wide.
    """

    def test_single_char_negated_class_is_fuzzy(self):
        highlights = parse_regex_for_highlighting(r"r'[^,]+'", 'abc,def')
        self.assertTrue(highlights)
        _, _, seg_type, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')
        self.assertEqual(pattern_display, '[^,]')

    def test_single_char_negated_class_without_quantifier_is_fuzzy(self):
        highlights = parse_regex_for_highlighting(r"r'([^,])'", 'abc,def')
        self.assertTrue(highlights)
        _, _, seg_type, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')
        self.assertEqual(pattern_display, '[^,]')

    def test_negated_class_reads_back_on_every_match(self):
        highlights = parse_regex_for_highlighting(r"r'([^,]+)(, )'", 'ab, cd, ef')
        fuzzies = [h for h in highlights if h[2] == 'fuzzy']
        self.assertEqual(len(fuzzies), 2)
        for h in fuzzies:
            self.assertEqual(h[3], '[^,]')

    def test_multi_char_negated_class_still_works(self):
        highlights = parse_regex_for_highlighting(r"r'[^,;]+'", 'abc,def')
        self.assertTrue(highlights)
        _, _, seg_type, pattern_display, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'fuzzy')
        self.assertEqual(pattern_display, '[^,;]')


class TestNegatedClassOption(unittest.TestCase):
    """The [^N] option itself: when it exists, and how N is spelled."""

    def test_offered_for_a_real_following_char(self):
        self.assertEqual(negated_class_option(','), ('[^,]', '[^,]'))

    def test_not_offered_without_a_following_char(self):
        # '' = end of string, None = abuts an existing segment, sentinels are
        # the ^/$ anchor markers -- none of them is something to stop at.
        self.assertIsNone(negated_class_option(''))
        self.assertIsNone(negated_class_option(None))
        self.assertIsNone(negated_class_option(DC2))
        self.assertIsNone(negated_class_option(DC3))

    def test_sits_just_after_dot_in_the_option_list(self):
        values = [v for v, _ in fuzzy_pattern_options(',')]
        self.assertEqual(values[values.index('.') + 1], '[^,]')
        # ... and the static list is otherwise untouched.
        self.assertEqual([v for v in values if v != '[^,]'],
                         [v for v, _ in FUZZY_PATTERN_OPTIONS])

    def test_no_following_char_leaves_the_list_alone(self):
        self.assertEqual(fuzzy_pattern_options(None), list(FUZZY_PATTERN_OPTIONS))

    def test_generated_class_round_trips_for_tricky_delimiters(self):
        r"""What we generate has to read back as itself.

        `(` and `)` are escaped past what the regex engine needs, because
        parse_top_level_segments counts parens without skipping character
        classes and a bare one would split the segment in the wrong place.
        """
        for delim in [',', ')', '(', ']', '[', '-', '^', '$', '.', '*', '|',
                      '"', "'", '\\', '\n', '\t']:
            pattern, label = negated_class_option(delim)
            self.assertEqual(pattern, label, delim)
            self.assertEqual(len(parse_all_segments(pattern + '+')), 1,
                             (delim, pattern))
            highlights = parse_regex_for_highlighting(
                make_regex_search(pattern + '+'), 'abc')
            self.assertTrue(highlights, delim)
            self.assertEqual(highlights[0][2], 'fuzzy', delim)
            self.assertEqual(highlights[0][3], pattern, delim)


class TestNegatedClassSynthesis(unittest.TestCase):
    """A drag that stops at a delimiter should say so, rather than freezing the
    length of whatever happened to be there.

    The ordering rule: a class describing the CONTENT beats one describing only
    where the drag STOPS, which beats one giving only its LENGTH.
    """

    def test_mixed_content_stopping_at_delimiter(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('John Smith', prev_char='', next_char=','),
            '[^,]+')

    def test_adjacent_to_a_segment_on_the_left_uses_star(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('John Smith', prev_char=None, next_char=','),
            '[^,]*')

    def test_a_content_class_still_wins(self):
        # [a-z] says what the text IS; [^,] only says where it stops.
        self.assertEqual(
            synthesize_fuzzy_pattern('cd', prev_char=',', next_char=','),
            '[a-z]+')

    def test_a_fixed_length_content_class_beats_the_negated_class(self):
        # '12' out of '123' is two digits, not "everything up to a 3".
        self.assertEqual(
            synthesize_fuzzy_pattern('12', prev_char='', next_char='3'), r'\d{2}')
        self.assertEqual(
            synthesize_fuzzy_pattern('3.14', prev_char='', next_char='1'),
            r'[0-9\.]{4}')

    def test_unanchored_left_edge_falls_back_to_a_length(self):
        # [^,] matches 'x' too, so an unanchored [^,]+ would run left past the
        # drag -- the very jump this change exists to remove.
        self.assertEqual(
            synthesize_fuzzy_pattern('John Smith', prev_char='x', next_char=','),
            '.{10}')

    def test_text_containing_the_stop_char_falls_back(self):
        # [^,]+ cannot cover a drag that has a ',' inside it.
        self.assertEqual(
            synthesize_fuzzy_pattern('a, b', prev_char='', next_char=','), '.{4}')

    def test_end_of_string_has_nothing_to_stop_at(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('a1 ', prev_char='x', next_char=''), '.{3}')

    def test_abutting_segment_has_nothing_to_stop_at(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('a1 ', prev_char='x', next_char=None), '.{3}')

    def test_anchor_sentinel_is_not_a_stop_char(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('a1 ', prev_char='x', next_char=DC3), '.{3}')

    def test_mixed_text_stops_at_the_next_char(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('a1 ', prev_char='', next_char='b'), '[^b]+')

    def test_text_with_a_newline_stops_at_the_next_char(self):
        self.assertEqual(
            synthesize_fuzzy_pattern('a\nb', prev_char='', next_char=' '), '[^ ]+')


class TestNegatedClassDropdown(unittest.TestCase):
    """[^N] is dynamic: N is whatever follows that segment in that match."""

    def test_option_is_offered_for_the_following_char(self):
        import html as html_mod
        value = 'ab, cd, ef'
        model = init_model(value)
        model['search'] = r"r'(.*?)(, )'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-1-0', 'segmentIndex': 0,
                                 'matchIndex': 1}
        out = visualize(value, model, None, None)
        self.assertIn(
            html_mod.escape(repr(DropdownSelect('fuzzy-pattern-1-0', '[^,]'))), out)

    def test_no_option_when_the_segment_runs_to_the_end_of_the_string(self):
        value = 'hello world'
        model = init_model(value)
        model['search'] = r"r'(hello)(.*)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0-1', 'segmentIndex': 1,
                                 'matchIndex': 0}
        out = visualize(value, model, None, None)
        self.assertNotIn('[^', out)

    def test_selecting_the_option_rewrites_the_segment(self):
        value = 'ab, cd, ef'
        model = init_model(value)
        model['search'] = r"r'(.*)(,\ )'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0-0', 'segmentIndex': 0,
                                 'matchIndex': 0}
        model, _ = update(make_dropdown_select_event('fuzzy-pattern-0-0', '[^,]'),
                          None, model, value)
        self.assertEqual(model['search'], r"r'[^,]*,\ '")


# =============================================================================
# Lazy quantifiers keep a fuzzy segment's neighbour in place
# =============================================================================

class TestLazifyOvershootingFuzzy(unittest.TestCase):
    r"""A greedy `.*` in front of a literal binds that literal to its LAST
    occurrence, so the segment the user just dragged appears to jump down the
    string. Assembling the pattern makes such a fuzzy lazy -- but only where
    the overshoot is real.
    """

    def test_appending_a_literal_lazifies_the_fuzzy_before_it(self):
        self.assertEqual(append_segment_to_regex(r"r'(.*)'", 'literal', ', '),
                         r"r'.*?,\ '")

    def test_prepending_a_fuzzy_lazifies_it(self):
        self.assertEqual(prepend_segment_to_regex(r"r'(hello)'", 'fuzzy', '.*'),
                         r"r'.*?hello'")

    def test_appending_a_literal_after_an_ungrouped_fuzzy(self):
        self.assertEqual(append_segment_to_regex(r"r'hello.*'", 'literal', 'world'),
                         r"r'hello.*?world'")

    def test_inserting_a_fuzzy_before_a_literal_lazifies_it(self):
        self.assertEqual(
            insert_segment_at_position(r"r'(world)'", 0, 'fuzzy', '.*'),
            r"r'.*?world'")

    def test_a_class_that_cannot_cross_the_literal_stays_greedy(self):
        # \s can't match the 'w' of world, so \s+ never overshoots it.
        self.assertEqual(append_segment_to_regex(r"r'hello\s+'", 'literal', 'world'),
                         r"r'hello\s+world'")

    def test_a_negated_class_stays_greedy(self):
        # [^,] can't match ',' -- it already stops itself.
        self.assertEqual(append_segment_to_regex(r"r'[^,]+'", 'literal', ', '),
                         r"r'[^,]+,\ '")

    def test_a_closed_quantifier_stays_as_written(self):
        self.assertEqual(append_segment_to_regex(r"r'([A-Z]{1})'", 'literal', 'C'),
                         r"r'[A-Z]{1}C'")

    def test_a_trailing_fuzzy_stays_greedy(self):
        # Lazy at the tail has nothing to stop at: (hello)(.*?) on 'hello world'
        # would collapse to a single character.
        self.assertEqual(append_segment_to_regex(r"r'hello'", 'fuzzy', '.*'),
                         r"r'hello.*'")

    def test_typed_input_is_left_exactly_as_typed(self):
        model = init_model('hello world')
        model, _ = update(make_search_box_input_event(r"r'(hello)(.*)(world)'"),
                          ('x', 'x'), model, 'hello world')
        self.assertEqual(model['search'], r"r'(hello)(.*)(world)'")

    def test_resizing_the_fuzzy_keeps_it_lazy(self):
        # resize_fuzzy_segment re-infers with next_char=None, which yields a
        # greedy '*'; the segment must not silently lose its laziness.
        value = 'John Smith, Jane Doe'
        result = resize_fuzzy_segment(r"r'.*?,\ '", 0, value, 1, 11,
                                      prev_char='', next_char=None)
        self.assertEqual(result, r"r'.*?,\ '")

    def test_resizing_a_literal_leaves_its_neighbour_alone(self):
        result = resize_literal_segment(r"r'(hello)(.*)(world)'", 0, 'hello world',
                                        _legacy_internal_index(2),
                                        _legacy_internal_index(6))
        self.assertIn('(.*)', result)


class TestFuzzyDragDoesNotMoveItsNeighbour(unittest.TestCase):
    """The complaint all of this is for, at the level the user meets it: after
    a fuzzy drag, the literal already placed must still sit where it was put."""

    def setUp(self):
        self.var_and_exp = ('x', 'x')

    def test_literal_first_then_fuzzy_drag_left(self):
        # 'John Smith, Jane Doe, Ann Lee' -- internal idx = string idx + 1,
        # so the first ', ' is internal 11-12 and 'John Smith' is 1-10.
        value = 'John Smith, Jane Doe, Ann Lee'
        model = init_model(value)

        model, _ = update(make_mouse_down_event(11, legacy_index=False, top_half=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(12, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(12, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r',\ '")

        model, _ = update(make_mouse_down_event(10, legacy_index=False, top_half=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(1, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(1, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'.*?,\ '")

        # The ', ' is still on the FIRST comma, not the second.
        highlights = parse_regex_for_highlighting(model['search'], value)
        literal = next(h for h in highlights if h[2] == 'literal' and h[6] == 0)
        self.assertEqual((literal[0], literal[1]), (11, 13))

    def test_fuzzy_first_then_click_inside_opens_menu(self):
        # 'hello world and world again' -- 'hello' is internal 1-5, the first
        # 'world' is 7-11. A drag inside a realized fuzzy region no longer
        # carves a literal out of it: the mousedown opens the segment menu
        # instead, so the pattern (and its neighbour) stays untouched.
        value = 'hello world and world again'
        model = init_model(value)

        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        # Fuzzy-extend right, all the way to the end of the string.
        model, _ = update(make_mouse_down_event(6, legacy_index=False, top_half=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(27, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(27, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello.*'")

        # A drag starting on the first 'world' opens the fuzzy's menu.
        model, _ = update(make_mouse_down_event(7, legacy_index=False, top_half=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(11, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(11, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello.*'")
        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-1')


# =============================================================================
# Selection Adjacency Tests (skip over anchors)
# =============================================================================

class TestIsAdjacentRight(unittest.TestCase):
    """Unit tests for is_adjacent_right helper function.

    is_adjacent_right(idx, last_end, string_value) returns True if idx is
    at or just past last_end, with only anchor/sentinel chars in between.
    """

    def test_exact_adjacent(self):
        """idx == last_end is always adjacent."""
        self.assertTrue(is_adjacent_right(_legacy_internal_index(7), _legacy_internal_index(7), "hello\nworld"))

    def test_skip_dollar_to_newline(self):
        """Skip $ to reach \\n at end of line.

        String "hello\\nworld":
        Internal: ..., o=6, $=7, \\n=8, ...
        last_end=7 (at $), idx=8 (\\n). Skipped: $ (anchor).
        """
        self.assertTrue(is_adjacent_right(_legacy_internal_index(8), _legacy_internal_index(7), "hello\nworld"))

    def test_skip_dollar_past_end_is_not_adjacent(self):
        """There is no visible cell after the final $.

        String "hello":
        Internal: ..., o=6, $=7, \\Z=8
        last_end=7 (at $), idx=8 (\\Z). Skipped: $ (anchor).
        """
        self.assertFalse(is_adjacent_right(_legacy_internal_index(8), _legacy_internal_index(7), "hello"))

    def test_skip_caret_after_newline_to_first_char(self):
        """Skip ^ to reach first char of next line.

        String "hello\\nworld":
        Internal: ..., \\n=8, ^=9, w=10, ...
        last_end=9 (at ^), idx=10 (w). Skipped: ^ (anchor).
        """
        self.assertTrue(is_adjacent_right(_legacy_internal_index(10), _legacy_internal_index(9), "hello\nworld"))

    def test_skip_multiple_anchors_between_consecutive_newlines(self):
        """Skip ^$ between consecutive newlines.

        String "a\\n\\nb":
        Internal: ..., \\n=4, ^=5, $=6, \\n=7, ...
        last_end=5, idx=7. Skipped: ^$ (both anchors).
        """
        self.assertTrue(is_adjacent_right(_legacy_internal_index(7), _legacy_internal_index(5), "a\n\nb"))

    def test_not_adjacent_over_real_char(self):
        """Cannot skip \\n (a real character, not an anchor).

        String "hello\\nworld":
        Internal: ..., $=7, \\n=8, ^=9, ...
        last_end=7, idx=9. Skipped: $\\n — \\n is real.
        """
        self.assertFalse(is_adjacent_right(_legacy_internal_index(9), _legacy_internal_index(7), "hello\nworld"))

    def test_far_away_not_adjacent(self):
        """Far-away index is not adjacent."""
        self.assertFalse(is_adjacent_right(_legacy_internal_index(12), _legacy_internal_index(7), "hello\nworld"))

    def test_before_last_end_not_adjacent(self):
        """idx < last_end is not adjacent."""
        self.assertFalse(is_adjacent_right(_legacy_internal_index(5), _legacy_internal_index(7), "hello\nworld"))

    def test_out_of_bounds_not_adjacent(self):
        """Out-of-bounds idx is not adjacent."""
        self.assertFalse(is_adjacent_right(_legacy_internal_index(100), _legacy_internal_index(7), "hello"))


class TestIsAdjacentLeft(unittest.TestCase):
    """Unit tests for is_adjacent_left helper function.

    is_adjacent_left(idx, first_start, string_value) returns True if idx is
    just before first_start, with only anchor/sentinel chars in between.
    """

    def test_exact_adjacent(self):
        """idx == first_start - 1 is always adjacent."""
        self.assertTrue(is_adjacent_left(_legacy_internal_index(9), _legacy_internal_index(10), "hello\nworld"))

    def test_skip_caret_to_newline(self):
        """Skip ^ to reach \\n going left.

        String "hello\\nworld":
        Internal: ..., \\n=8, ^=9, w=10, ...
        first_start=10 (w), idx=8 (\\n). Skipped: ^ (anchor).
        """
        self.assertTrue(is_adjacent_left(_legacy_internal_index(8), _legacy_internal_index(10), "hello\nworld"))

    def test_skip_caret_to_backslash_A(self):
        """Skip ^ to reach \\A at start of string.

        String "hello":
        Internal: \\A=0, ^=1, h=2, ...
        first_start=2 (h), idx=0 (\\A). Skipped: ^ (anchor).
        """
        self.assertTrue(is_adjacent_left(_legacy_internal_index(0), _legacy_internal_index(2), "hello"))

    def test_skip_dollar_to_last_char_of_prev_line(self):
        """Skip $ to reach last char of previous line going left.

        String "hello\\nworld":
        Internal: ..., o=6, $=7, \\n=8, ...
        first_start=8 (\\n), idx=6 (o). Skipped: $ (anchor).
        """
        self.assertTrue(is_adjacent_left(_legacy_internal_index(6), _legacy_internal_index(8), "hello\nworld"))

    def test_skip_multiple_anchors_between_consecutive_newlines(self):
        """Skip $^ between consecutive newlines going left.

        String "a\\n\\nb":
        Internal: ..., \\n=4, ^=5, $=6, \\n=7, ...
        first_start=7, idx=4. Skipped: ^$ (both anchors going left).

        Wait, skipped chars are at indices 5 and 6, which are ^ and $.
        """
        self.assertTrue(is_adjacent_left(_legacy_internal_index(4), _legacy_internal_index(7), "a\n\nb"))

    def test_not_adjacent_over_real_char(self):
        """Cannot skip \\n (a real character) going left.

        String "hello\\nworld":
        Internal: ..., o=6, $=7, \\n=8, ^=9, w=10, ...
        first_start=10, idx=7. Between: \\n=8, ^=9. \\n is real.
        """
        self.assertFalse(is_adjacent_left(_legacy_internal_index(7), _legacy_internal_index(10), "hello\nworld"))

    def test_far_away_not_adjacent(self):
        """Far-away index is not adjacent."""
        self.assertFalse(is_adjacent_left(_legacy_internal_index(2), _legacy_internal_index(10), "hello\nworld"))

    def test_at_first_start_not_adjacent(self):
        """idx == first_start is not adjacent (must be to the left)."""
        self.assertFalse(is_adjacent_left(_legacy_internal_index(10), _legacy_internal_index(10), "hello\nworld"))

    def test_past_first_start_not_adjacent(self):
        """idx > first_start is not adjacent."""
        self.assertFalse(is_adjacent_left(_legacy_internal_index(11), _legacy_internal_index(10), "hello\nworld"))


class TestManyMatchesMouseDownPerformance(unittest.TestCase):
    """A click checks adjacency against every match, and a dense search in a
    long string has thousands. Each check must be cheap: paying a full pass
    over the string per match froze a 65k-char string with 10k matches for
    ~a minute on one MouseDown."""

    def test_mouse_down_with_thousands_of_matches_is_fast(self):
        line = "this is a sample string with several s chars spread across it ok\n"
        value = line * 1000  # 65,000 chars, 10,000 's' matches
        var_and_exp = ('x', 'x')

        # Both clicks abut no match, so every match's adjacency gets checked:
        # near the start the left-scan walks all 10k matches, near the end
        # the right-scan does.
        for click_at in (2,                              # the 'h' of "this"
                         len(value) - 3):                # near the end
            model = init_model(value)
            model['search'] = r"r's'"
            event = make_mouse_down_event(click_at, legacy_index=False)

            t0 = time.perf_counter()
            update(event, var_and_exp, model, value)
            elapsed = time.perf_counter() - t0

            self.assertLess(elapsed, 1.0,
                            f"MouseDown at {click_at} took {elapsed:.1f}s")

    def test_render_of_dense_click_preview_is_fast(self):
        """Clicking a single lone char previews a one-char pattern with
        thousands of matches; the render after it (and every drag-move render
        that follows) must not pay a full string walk per match (as
        _segmentNextChars once did)."""
        line = "this is a sample string with several s chars spread across it ok\n"
        value = line * 1000
        model = init_model(value)
        event = make_mouse_down_event(value.index(' s ') + 2, legacy_index=False)
        model, _ = update(event, ('x', 'x'), model, value)
        self.assertTrue(model['dragging'])

        t0 = time.perf_counter()
        visualize(value, model, None, None)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 1.0, f"dense preview render took {elapsed:.1f}s")


class TestSelectionAdjacencyIntegration(unittest.TestCase):
    """Integration tests for extending selections across anchor boundaries.

    These test the full flow through update() to verify that the adjacency
    fix works end-to-end for various scenarios.
    """

    def test_right_extend_over_dollar_to_newline(self):
        """BUG: After /(^)(.*)/, clicking \\n (past $) should extend, not reset.

        This is the user's primary reported bug: can't generate /^.*\\n/
        because \\n is drawn after $ and not considered adjacent.

        String "hello\\nworld":
        Internal: \\A=0, ^=1, h=2, e=3, l=4, l=5, o=6, $=7, \\n=8, ^=9, w=10, ...

        /(^)(.*)/ matches ^hello, last_end=7 (at $).
        Clicking \\n at index 8 should extend the selection.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select ^ literal at index 1
        model, _ = update(make_mouse_down_event(1, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(1),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'^'")

        # Extend with .* fuzzy
        last_end = get_last_segment_end_internal_idx(model['search'], value)
        model, _ = update(make_mouse_down_event(last_end, legacy_index=False, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(last_end, legacy_index=False, alt_key=True),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'^[a-z]{1}'")

        # Verify last_end (one past the last segment's last char)
        last_end = get_last_segment_end_internal_idx(model['search'], value)
        self.assertEqual(last_end, _legacy_internal_index(3))  # one past 'h' match from [a-z]{1}

        # Click \n at index 8 (past $ at 7) — THIS WAS THE BUG
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8),
                         var_and_exp, model, value)

        # /^[a-z]{1}/ matches on both lines (re.M). The click is nowhere near
        # the first match's end, but it sits right before the SECOND match, so
        # it extends that one leftward rather than starting over.
        self.assertEqual(model['search'], r"r'(\n)(^)[a-z]{1}'")

    def test_right_extend_over_dollar_to_newline_hello_first(self):
        """Extend /(hello)/ by clicking \\n (past $) should extend.

        String "hello\\nworld":
        /(hello)/ matches "hello", last_end=7 (at $).
        Clicking \\n at 8 should extend.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello" (indices 2-6)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        last_end = get_last_segment_end_internal_idx(model['search'], value)
        self.assertEqual(last_end, _legacy_internal_index(7))

        # Click \n at 8 (skips $ at 7)
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'(hello)(\n)'")

    def test_right_extend_to_visible_final_dollar(self):
        """After selecting "hello", clicking the final $ should extend.

        String "hello":
        Internal: \\A=0, ^=1, h=2, e=3, l=4, l=5, o=6, $=7, \\Z=8

        /(hello)/ ends at 7 (at $).
        Clicking \\Z at 8 should extend.
        """
        value = "hello"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        last_end = get_last_segment_end_internal_idx(model['search'], value)
        self.assertEqual(last_end, _legacy_internal_index(7))  # at $

        # Click the final $ at the end of the string
        model, _ = update(make_mouse_down_event(7, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(7),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'(hello)($)'")

    def test_right_extend_fuzzy_over_dollar_to_newline(self):
        """Fuzzy extension over $ to \\n should work too.

        Same as literal but using bottom-half click for fuzzy.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        last_end = get_last_segment_end_internal_idx(model['search'], value)

        # Click \n at 8 with fuzzy (bottom half) — skips $ at 7
        model, _ = update(make_mouse_down_event(8, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8, alt_key=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hello\s*'")

    def test_left_extend_over_caret_to_newline(self):
        """Select "world", clicking \\n (past ^ going left) should extend left.

        String "hello\\nworld":
        Internal: ..., $=7, \\n=8, ^=9, w=10, o=11, r=12, l=13, d=14, ...

        /(world)/ starts at 10 (w), first_start=10.
        Clicking \\n at 8: ^ at 9 is between (anchor). Should extend left.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "world" at indices 10-14
        model, _ = update(make_mouse_down_event(10, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(14),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(14),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'world'")

        first_start = get_first_segment_start_internal_idx(model['search'], value)
        self.assertEqual(first_start, _legacy_internal_index(10))

        # Click \n at 8 (past ^ at 9)
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8),
                         var_and_exp, model, value)

        # Should extend left over the ^ the click reached across. The ^ is a
        # position the user clicked through, not a character they picked, so
        # the new segment is the \n alone.
        self.assertEqual(model['search'], r"r'(\n)(world)'")

    def test_left_extend_over_caret_to_backslash_A(self):
        """Select "hello" from h, clicking \\A (past ^) should extend left.

        String "hello":
        Internal: \\A=0, ^=1, h=2, e=3, l=4, l=5, o=6, $=7, \\Z=8

        /(hello)/ starts at 2 (h), first_start=2.
        Clicking \\A at 0: ^ at 1 is between (anchor). Should extend left.
        """
        value = "hello"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        first_start = get_first_segment_start_internal_idx(model['search'], value)
        self.assertEqual(first_start, _legacy_internal_index(2))

        # Click \A at 0 (past ^ at 1)
        model, _ = update(make_mouse_down_event(0, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(0),
                         var_and_exp, model, value)

        # Should extend left with the visible ^ anchor
        self.assertEqual(model['search'], r"r'(^)(hello)'")

    def test_no_extend_over_real_characters(self):
        """Should NOT extend when real characters are between click and selection.

        String "hello\\nworld":
        Select "world" at w=10, first_start=10.
        Click $ at 7: between are \\n (real) and ^ (anchor). Can't skip \\n.
        Should reset, not extend.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "world"
        model, _ = update(make_mouse_down_event(10, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(14),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(14),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'world'")

        # Click $ at 7 — there's \n (real char) between $ and the selection
        model, _ = update(make_mouse_down_event(7, top_half=True),
                         var_and_exp, model, value)

        # Should reset, not extend
        self.assertIsNone(model['search'])

    def test_drag_after_skipped_adjacency_works(self):
        """After extending via skipped adjacency, drag should still work.

        Click \\n (skipping $), then drag to ^ to select \\n^.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        # Click \n at 8 (skips $ at 7) and drag to ^ at 9
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(9),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(9),
                         var_and_exp, model, value)

        # Should extend with \n^ (both selected by the drag)
        self.assertEqual(model['search'], r"r'(hello)(\n^)'")

    def test_right_extend_skipped_adjacency_does_not_include_anchor(self):
        """When extending right by skipping an anchor, the skipped anchor
        should NOT be included in the new segment.

        After /(hello)/ with last_end=7 ($), clicking \\n at 8 should
        produce a segment containing just \\n, not $\\n.
        """
        value = "hello\nworld"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)

        # Click \n at 8
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(8),
                         var_and_exp, model, value)

        # Should be just \n, NOT $\n
        self.assertEqual(model['search'], r"r'(hello)(\n)'")

    def test_existing_right_extend_still_works(self):
        """The standard right extension (idx == last_end) should still work.

        Regression test to make sure the fix doesn't break existing behavior.
        """
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello" (indices 2-6)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'hello'")

        # Extend with fuzzy at exact end
        end_idx = get_last_segment_end_internal_idx(model['search'], value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'hello\s*'")

    def test_existing_left_extend_still_works(self):
        """The standard left extension (idx == first_start - 1) should still work.

        Regression test.
        """
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "world"
        model, _ = update(make_mouse_down_event(8, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(12),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(12),
                         var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'world'")

        # Extend left at first_start - 1 (standard adjacency)
        start_idx = get_first_segment_start_internal_idx(model['search'], value)
        model, _ = update(make_mouse_down_event(start_idx - 1, legacy_index=False, top_half=False),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(start_idx - 1, legacy_index=False, alt_key=True),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'\s*world'")


# =============================================================================
# Search Box Tests
# =============================================================================

def make_search_box_input_event(value: str) -> dict:
    """Create a SearchBoxInput event dict (simulates typing in the search box).

    Args:
        value: The full current value of the search box input field.
    """
    return {
        'pythonEventStr': "lambda e: SearchBoxInput(value=e.get('value', ''))",
        'eventJSON': {
            'type': 'input',
            'value': value,
        }
    }


class TestSearchBoxBasics(unittest.TestCase):
    """Test basic search box input behavior."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_typing_regex_sets_selection_regex(self):
        """Typing a regex in the search box sets search directly."""
        model, commands = update(make_search_box_input_event(r"r'hello'"),
                                self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'hello'")
        # Typing a valid pattern now auto-inserts a linked find LOC.
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], tuple)

    def test_typing_regex_with_groups_sets_selection_regex(self):
        """Typing a regex with capturing groups works."""
        model, commands = update(make_search_box_input_event(r"r'(hello)(.*)(world)'"),
                                self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'(hello)(.*)(world)'")

    def test_clearing_search_box_clears_regex(self):
        """Clearing the search box (empty value) sets search to None."""
        self.model['search'] = r"r'(hello)'"
        self.model['undoHistory'] = [None]

        model, _ = update(make_search_box_input_event(''),
                          self.var_and_exp, self.model, self.value)

        self.assertIsNone(model['search'])

    def test_typing_saves_undo_history(self):
        """Each search box change saves the previous value to undo history."""
        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['undoHistory'], [None])  # Previous was None

        model, _ = update(make_search_box_input_event(r"r'hello world'"),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])

    def test_same_value_does_not_add_to_undo(self):
        """Typing the same value again doesn't add duplicate undo entries."""
        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['undoHistory'], [None])

        # Same value again
        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['undoHistory'], [None])  # No duplicate

    def test_typing_clears_drag_state(self):
        """Typing in the search box clears any in-progress drag state."""
        self.model['anchorIdx'] = 5
        self.model['cursorIdx'] = 8
        self.model['dragging'] = True

        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          self.var_and_exp, self.model, self.value)

        self.assertIsNone(model['anchorIdx'])
        self.assertIsNone(model['cursorIdx'])
        self.assertFalse(model['dragging'])

    def test_invalid_regex_still_stored(self):
        """An invalid regex is still stored so the user can keep editing."""
        model, _ = update(make_search_box_input_event(r"r'[unclosed'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'[unclosed'")

    def test_search_box_value_without_delimiters(self):
        """Value without / delimiters is stored as-is (future search types)."""
        model, _ = update(make_search_box_input_event('hello'),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], 'hello')


class TestSearchBoxVisualize(unittest.TestCase):
    """Test that the search box renders correctly in visualize output."""

    def test_search_box_present_in_output(self):
        """The search box input element is present in visualize output."""
        html = visualize("hello world", init_model("hello world"), None, None)
        self.assertIn('<input', html)
        self.assertIn('snc-input', html)
        self.assertIn('SearchBoxInput', html)

    def test_search_box_shows_empty_when_no_regex(self):
        """Search box value is empty when there's no selection regex."""
        model = init_model("hello world")
        html = visualize("hello world", model, None, None)
        # The value attribute should be empty
        self.assertIn('value=""', html)

    def test_search_box_shows_current_regex(self):
        """Search box shows the full search in r'..' form."""
        import html as html_mod
        model = init_model("hello world")
        model['search'] = r"r'(hello)(.*)(world)'"

        html_out = visualize("hello world", model, None, None)
        self.assertIn(html_mod.escape(r"r'(hello)(.*)(world)'"), html_out)

    def test_search_box_shows_regex_after_mouse_selection(self):
        """After a mouse selection, the search box reflects the built regex."""
        import html as html_mod
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        # Select "hello" by mouse
        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(6),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(6),
                         var_and_exp, model, value)

        html_out = visualize(value, model, None, None)
        self.assertIn(html_mod.escape(r"r'hello'"), html_out)

    def test_search_box_has_placeholder(self):
        """Search box has a placeholder for when it's empty."""
        html = visualize("hello world", init_model("hello world"), None, None)
        self.assertIn('placeholder=', html)


class TestSearchBoxToMouseInteraction(unittest.TestCase):
    """Test transitioning from search box editing to mouse-based selection."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_type_regex_then_extend_with_mouse(self):
        """Type a regex in the search box, then extend it with mouse selection.

        Type /(hello)/ -> extend right with fuzzy -> /(hello)(.*)/
        """
        # Type regex in search box
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'(hello)'")

        # Now extend with fuzzy from the right end
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertIsNotNone(end_idx)

        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello\s*'")

    def test_type_regex_then_click_inside_fuzzy(self):
        """Type a regex with fuzzy, then click inside the fuzzy.

        Type /(hello)(.*)/ -> click inside fuzzy opens its segment menu.
        """
        # Type regex with fuzzy segment in the search box
        model, _ = update(make_search_box_input_event(r"r'(hello)(.*)'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'(hello)(.*)'")

        # In "hello world", (.*) matches " world" (internal 6-12); the 'w'
        # sits at internal 7, inside the fuzzy.
        fuzzy_info = find_fuzzy_segment_at_index(model['search'], self.value, 7)
        self.assertIsNotNone(fuzzy_info)

        model, _ = update(make_mouse_down_event(8, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(12),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                          self.var_and_exp, model, self.value)

        # The click opens the fuzzy's menu; the pattern stays as typed.
        self.assertEqual(model['search'], r"r'(hello)(.*)'")
        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-1')

    def test_type_regex_then_new_mouse_selection_replaces(self):
        """Clicking far from the typed regex starts a fresh selection.

        Type /(hello)/ -> click in unrelated area -> replaces with new selection.
        """
        # Type regex
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'(hello)'")

        # Click on 'w' at index 8 (not adjacent to "hello" selection end at 7)
        # This is far enough away that it should start fresh
        # Actually, let's click somewhere definitely not adjacent
        # "hello" ends at index 7, and 'w' is at index 8.
        # is_adjacent_right(_legacy_internal_index(8), _legacy_internal_index(7), value) == True because 8 >= 7 and idx == last_end + 1
        # So let's click at 10 ('r') which is NOT adjacent to index 7
        model, _ = update(make_mouse_down_event(10, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(10),
                          self.var_and_exp, model, self.value)

        # Should reset and create a fresh single-char selection
        self.assertEqual(model['search'], r"r'r'")

    def test_type_regex_then_extend_left_with_mouse(self):
        """Type a regex in the search box, then extend it from the left.

        Type /(world)/ -> extend left with fuzzy -> /(.*)(world)/
        """
        # Type regex in search box
        model, _ = update(make_search_box_input_event(r"r'(world)'"),
                          self.var_and_exp, self.model, self.value)

        self.assertEqual(model['search'], r"r'(world)'")

        # Extend left with fuzzy
        start_idx = get_first_segment_start_internal_idx(model['search'], self.value)
        self.assertIsNotNone(start_idx)

        model, _ = update(make_mouse_down_event(start_idx - 1, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(start_idx - 1, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'\s*world'")


class TestMouseToSearchBoxInteraction(unittest.TestCase):
    """Test transitioning from mouse-based selection to search box editing."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def _select_hello(self, model):
        """Helper to create /(hello)/ via mouse selection."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)
        return model

    def _select_hello_fuzzy_world(self, model):
        """Helper to create /(hello)(.*)(world)/ via mouse selection."""
        model = self._select_hello(model)

        # Add fuzzy
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)

        # Add "world" inside fuzzy
        model, _ = update(make_mouse_down_event(8, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(12),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(12),
                          self.var_and_exp, model, self.value)
        return model

    def test_mouse_selection_then_edit_in_search_box(self):
        """Build a regex with mouse, then edit it via the search box."""
        model = self._select_hello(self.model)
        self.assertEqual(model['search'], r"r'hello'")

        # Now tweak the regex via search box
        model, _ = update(make_search_box_input_event(r"r'(hell)'"),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hell)'")
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])

    def test_mouse_selection_then_clear_via_search_box(self):
        """Build regex with mouse, then clear it by emptying the search box."""
        model = self._select_hello(self.model)
        self.assertEqual(model['search'], r"r'hello'")

        model, _ = update(make_search_box_input_event(''),
                          self.var_and_exp, model, self.value)

        self.assertIsNone(model['search'])
        self.assertEqual(model['undoHistory'], [None, r"r'hello'"])

    def test_mouse_selection_then_search_box_then_mouse_again(self):
        """Full round trip: mouse -> search box edit -> mouse extend.

        Build /(hello)/ with mouse -> edit to /(hel)/ in search box -> extend right.
        """
        model = self._select_hello(self.model)
        self.assertEqual(model['search'], r"r'hello'")

        # Edit in search box to shorten the pattern
        model, _ = update(make_search_box_input_event(r"r'(hel)'"),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hel)'")

        # Extend right with fuzzy from end of "hel" match
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        self.assertIsNotNone(end_idx)

        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hel[a-z]{1}'")

    def test_complex_mouse_then_edit_pattern_in_search_box(self):
        """Build /(hello)(.*)(world)/ with mouse, then change .* to \\s+ via search box."""
        model = self._select_hello_fuzzy_world(self.model)
        self.assertEqual(model['search'], r"r'hello\s*world'")

        # Edit the pattern in the search box to change \s* to \s+
        model, _ = update(make_search_box_input_event(r"r'(hello)(\s+)(world)'"),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)(\s+)(world)'")

    def test_mouse_then_search_box_then_extend_left(self):
        """Mouse selection -> edit in search box -> extend left with mouse.

        Build /(world)/ with mouse -> edit to /(world!)/ in search box (invalid for this string) ->
        fix back to /(world)/ -> extend left.
        """
        value = "hello world"
        model = init_model(value)

        # Select "world" with mouse
        model, _ = update(make_mouse_down_event(8, top_half=True),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(12),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(12),
                          self.var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'world'")

        # Edit in search box
        model, _ = update(make_search_box_input_event(r"r'(world!)'"),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'(world!)'")

        # Fix back
        model, _ = update(make_search_box_input_event(r"r'(world)'"),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'(world)'")

        # Extend left with fuzzy
        start_idx = get_first_segment_start_internal_idx(model['search'], value)
        model, _ = update(make_mouse_down_event(start_idx - 1, legacy_index=False, top_half=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(start_idx - 1, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, value)

        self.assertEqual(model['search'], r"r'\s*world'")


class TestSearchBoxUndoRedo(unittest.TestCase):
    """Test undo/redo interactions with search box edits."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_undo_search_box_edit(self):
        """Cmd-Z after a search box edit restores the previous regex."""
        # Type a regex
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'(hello)'")

        # Undo
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)

        self.assertIsNone(model['search'])
        self.assertEqual(model['undoHistory'], [])
        self.assertEqual(model['redoHistory'], [r"r'(hello)'"])

    def test_redo_search_box_edit(self):
        """Cmd-Shift-Z after undoing a search box edit restores the regex."""
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        # Undo
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertIsNone(model['search'])

        # Redo
        model, _ = update(make_key_down_event('z', meta_key=True, shift_key=True),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)'")

    def test_undo_across_mouse_and_search_box(self):
        """Undo traverses both mouse selections and search box edits.

        Mouse: None -> /(hello)/ -> /(hello)(.*)/
        Search box: /(hello)(.*)(world)/
        Undo 3 times should get back to None.
        """
        # Mouse: select hello
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

        # Mouse: extend with fuzzy
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello\s*'")

        # Search box: refine to /(hello)(.*)(world)/
        model, _ = update(make_search_box_input_event(r"r'(hello)(.*)(world)'"),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(.*)(world)'")
        self.assertEqual(model['undoHistory'], [None, r"r'hello'", r"r'hello\s*'"])

        # Undo 1: back to /hello\s*/
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello\s*'")

        # Undo 2: back to /hello/
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

        # Undo 3: back to None
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertIsNone(model['search'])

    def test_search_box_edit_clears_redo_history(self):
        """A search box edit after an undo clears the redo history."""
        # Create a regex
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        # Undo it
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['redoHistory'], [r"r'(hello)'"])

        # Type something new in search box - should clear redo
        model, _ = update(make_search_box_input_event(r"r'(world)'"),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(world)'")
        self.assertEqual(model['redoHistory'], [])


class TestSearchBoxEnterGeneratesCode(unittest.TestCase):
    """Test code generation from a search-box-entered regex.

    Typing a pattern auto-inserts a linked find LOC. Enter with an unchanged
    expression is a no-op (does not re-emit ChangeSelectedText).
    """

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_search_box_input_auto_inserts_find_code(self):
        """Typing a grouped regex auto-inserts the find LOC; Enter is a no-op."""
        model, insert_cmds = update(make_search_box_input_event(r"r'(hello)(.*)(world)'"),
                                    self.var_and_exp, self.model, self.value)
        self.assertEqual(len(insert_cmds), 1)
        suggest_name, expr = insert_cmds[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(r'hello.*world'", expr)

        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, model, self.value)
        self.assertEqual(commands, [])
        self.assertEqual(model['linked_action'], 'match_strings')

    def test_search_box_input_auto_inserts_simple_regex(self):
        """A simple regex without groups auto-inserts the find LOC."""
        model, insert_cmds = update(make_search_box_input_event(r"r'hello'"),
                                    self.var_and_exp, self.model, self.value)
        self.assertEqual(len(insert_cmds), 1)
        suggest_name, expr = insert_cmds[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(r'hello'", expr)

    def test_search_box_input_suggests_name_regardless_of_collision(self):
        """Search-box auto-insert suggests name without collision resolution."""
        model, insert_cmds = update(make_search_box_input_event(r"r'hello'"),
                                    self.var_and_exp, self.model, self.value)
        self.assertEqual(len(insert_cmds), 1)
        suggest_name, expr = insert_cmds[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(r'hello'", expr)


class TestAutoLinkOnInteraction(unittest.TestCase):
    """As soon as an interaction yields a parseable expression, auto-insert a
    line of code and self-link, so subsequent interactions update it in place."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_first_search_box_input_auto_inserts_linked_loc(self):
        """Typing a valid pattern in the search box auto-generates a linked LOC."""
        model, commands = update(make_search_box_input_event(r"r'hello'"),
                                 self.var_and_exp, self.model, self.value)

        # A NewCode tuple is emitted on the very first meaningful interaction.
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(r'hello'", expr)

        # The model is now linked so further edits update in place.
        self.assertEqual(model['linked_action'], 'match_strings')
        self.assertEqual(model['linked_source_expr'], 'x')
        self.assertTrue(model.get('auto_linked_once'))

    def test_second_interaction_updates_via_change_selected_text(self):
        """After auto-linking, the next interaction emits ChangeSelectedText, not a new insert."""
        model, first_commands = update(make_search_box_input_event(r"r'hello'"),
                                       self.var_and_exp, self.model, self.value)
        self.assertEqual(len(first_commands), 1)
        self.assertIsInstance(first_commands[0], tuple)

        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value)

        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertIn("re.findall(r'world'", commands[0].expression)
        # Still only auto-linked once; no second insert.
        self.assertTrue(model.get('auto_linked_once'))

    def test_no_insert_when_pattern_does_not_yield_expression(self):
        """An interaction that cannot build a context yields no command."""
        # Empty search: _get_search_context returns None -> nothing generated.
        model, commands = update(make_search_box_input_event(''),
                                 self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])
        self.assertIsNone(model.get('linked_action'))

    def test_no_double_insert_when_handler_already_generated(self):
        """If the event's own handler already emitted a NewCode (e.g. Enter),
        the auto-link block must not also emit a second insert."""
        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          self.var_and_exp, self.model, self.value)
        # First input already auto-linked. Pressing Enter while linked should
        # produce a single ChangeSelectedText, never a tuple + a change.
        model, commands = update(make_key_down_event('Enter'),
                                 self.var_and_exp, model, self.value)
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 0)

    def test_finalized_mouse_selection_auto_inserts_linked_loc(self):
        """Finishing a literal selection with the mouse auto-inserts a linked LOC."""
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, commands = update(make_mouse_up_event(6),
                                 self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], tuple)
        self.assertEqual(model['linked_action'], 'match_strings')


class TestActionButtonClickAutoLinks(unittest.TestCase):
    """Clicking an action button while unlinked must both insert the LOC and
    enter linked mode, so the next interaction edits that line in place."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"

    def test_action_button_click_inserts_and_links(self):
        model, commands = update(make_action_button_event('count'),
                                 self.var_and_exp, self.model, self.value)
        # Emits exactly one insert (NewCode tuple)...
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 1)
        # ...and enters linked mode for the clicked action.
        self.assertEqual(model['linked_action'], 'count')
        self.assertEqual(model['linked_source_expr'], 'x')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertEqual(model['last_linked_expr'], tuples[0][1])

    def test_next_interaction_updates_in_place(self):
        model, first = update(make_action_button_event('count'),
                              self.var_and_exp, self.model, self.value)
        self.assertTrue(any(isinstance(c, tuple) for c in first))
        # Changing the search now edits the linked line rather than inserting.
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))

    def test_copy_click_does_not_link(self):
        model, commands = update(make_action_button_event('count', copy=True),
                                 self.var_and_exp, self.model, self.value)
        self.assertIsNone(model.get('linked_action'))


def make_unlink_event() -> dict:
    """Create an Unlink event dict."""
    return {'pythonEventStr': repr(Unlink()), 'eventJSON': {'type': 'unlink'}}


def make_relink_event(mode: str = 'insert', text: str = '') -> dict:
    """Create a Relink event dict."""
    return {'pythonEventStr': repr(Relink(mode=mode, text=text)),
            'eventJSON': {'type': 'relink', 'mode': mode, 'text': text}}


class TestRelinkViaChainIcon(unittest.TestCase):
    """The chain icon re-establishes a link after Unlink, resuming the prior
    action. 'insert' emits a NewCode tuple; 'takeover' emits ChangeSelectedText."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        # Link via a button click, then unlink.
        self.model, _ = update(make_action_button_event('count'),
                               self.var_and_exp, self.model, self.value)
        self.model, _ = update(make_unlink_event(),
                               self.var_and_exp, self.model, self.value)
        self.assertIsNone(self.model.get('linked_action'))

    def test_relink_insert_emits_new_code_and_resumes_action(self):
        model, commands = update(make_relink_event('insert'),
                                 self.var_and_exp, self.model, self.value)
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 1)
        self.assertEqual(model['linked_action'], 'count')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertEqual(model['last_linked_expr'], tuples[0][1])

    def test_relink_takeover_emits_change_selected_text_and_resumes_action(self):
        # The line still holds what the count action wrote before the unlink.
        taken_over = "x_count = sum(1 for _ in re.finditer(r'hello', x, flags=re.M))"
        model, commands = update(make_relink_event('takeover', text=taken_over),
                                 self.var_and_exp, self.model, self.value)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertEqual(model['linked_action'], 'count')

    def test_relink_defaults_to_auto_link_action_when_none_stashed(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model, _ = update(make_relink_event('insert'),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'find_or_map')

    def test_relink_without_context_is_noop(self):
        model = init_model(self.value)  # no search -> no context
        model, commands = update(make_relink_event('insert'),
                                 self.var_and_exp, model, self.value)
        self.assertEqual(commands, [])
        self.assertIsNone(model.get('linked_action'))


class TestRelinkTakeoverAdoptsExistingLine(unittest.TestCase):
    """On relink-takeover with a fresh model, the taken-over line is parsed and
    adopted into the model (its text left untouched) instead of being clobbered
    by a default-generated expression."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        # A previously-generated linked line still present in the code after a
        # file reopen (fresh model). find_or_map with search r'hello' on x.
        self.line = "x_matches = list(re.finditer(r'hello', x, flags=re.M))"

    def test_fresh_takeover_adopts_line_without_commands(self):
        model = init_model(self.value)
        model, commands = update(make_relink_event('takeover', text=self.line),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'find_or_map')
        self.assertEqual(model.get('linked_source_expr'), 'x')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertIsNotNone(model.get('search'))
        # The line is already in the editor; adoption must not rewrite it.
        self.assertEqual(commands, [])

    def test_interaction_after_adoption_emits_change_selected_text(self):
        model = init_model(self.value)
        model, _ = update(make_relink_event('takeover', text=self.line),
                          self.var_and_exp, model, self.value, eval_in_scope=eval)
        # A subsequent meaningful interaction rewrites the linked line in place
        # (ChangeSelectedText), rather than inserting a duplicate NewCode line.
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))
        self.assertFalse(any(isinstance(c, tuple) for c in commands))

    def test_stashed_unlink_action_wins_over_adoption(self):
        # Link via a button click, then unlink -> unlinked_action is stashed.
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model, _ = update(make_action_button_event('count'),
                          self.var_and_exp, model, self.value, eval_in_scope=eval)
        model, _ = update(make_unlink_event(),
                          self.var_and_exp, model, self.value, eval_in_scope=eval)
        self.assertIsNone(model.get('linked_action'))
        # Relink-takeover with a stashed action resumes the stash (count) and
        # emits ChangeSelectedText, ignoring the taken-over line text.
        model, commands = update(make_relink_event('takeover', text=self.line),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(model.get('linked_action'), 'count')

    def test_unparseable_takeover_links_without_overwriting(self):
        """An unrecognized line is still a valid link target, but the relink
        must not write over it — only the user's next interaction may."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model, commands = update(
            make_relink_event('takeover', text='???  not parseable  ???'),
            self.var_and_exp, model, self.value, eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'find_or_map')
        self.assertEqual(commands, [])


class TestRelinkTakeoverKeepsCaptureGroups(unittest.TestCase):
    """Adopting a findall line whose pattern has capture groups must keep them:
    the search is restored in capture-groups mode ('c' flag), so the adopted
    state regenerates the exact line rather than one with the groups stripped
    (which would change findall's result shape from tuples to strings)."""

    def setUp(self):
        self.value = '1.2.3.4 - - "GET /index.html HTTP/1.1" 200'
        self.var_and_exp = ('str1', 'str1')
        self.line = (r'''str1_strings3 = re.findall'''
                     r'''(r'(")([A-Z]*)(\ )(.*)(\ HTTP/1\.)', str1, flags=re.M)''')

    def test_adopted_grouped_findall_round_trips_verbatim(self):
        model = init_model(self.value)
        model, commands = update(make_relink_event('takeover', text=self.line),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertEqual(
            model.get('last_linked_expr'),
            r'''re.findall(r'(")([A-Z]*)(\ )(.*)(\ HTTP/1\.)', str1, flags=re.M)''')


class TestRelinkTakeoverOfForeignLine(unittest.TestCase):
    """Taking over a line this visualizer did not write: the link is recorded,
    but the line is left alone until the user's next interaction. Recording
    nothing used to leave the front-end linked to a line Python knew nothing
    about, so the next interaction inserted a duplicate line."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        # Derived from `other`, not from this visualizer's `x`.
        self.foreign = "hits = list(re.finditer(r'z', other, flags=re.M))"

    def _took_over(self, text):
        model = init_model(self.value)
        return update(make_relink_event('takeover', text=text),
                      self.var_and_exp, model, self.value, eval_in_scope=eval)

    def test_links_without_touching_the_line(self):
        model, commands = self._took_over(self.foreign)
        self.assertEqual(commands, [])
        self.assertEqual(model.get('linked_action'), 'find_or_map')
        self.assertEqual(model.get('linked_source_expr'), 'x')
        self.assertTrue(model.get('auto_linked_once'))

    def test_next_interaction_edits_the_line_instead_of_inserting(self):
        model, _ = self._took_over(self.foreign)
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertEqual(len([c for c in commands
                              if isinstance(c, ChangeSelectedText)]), 1)

    def test_takeover_with_a_search_still_edits_the_line_next(self):
        """The takeover writes nothing, so the expression it would have written
        must not be remembered as already-written. Otherwise the next
        interaction that regenerates it is suppressed as a no-op and the
        foreign text sits there forever under a chain icon claiming a link."""
        model = init_model(self.value)
        model['search'] = r"r'world'"
        model, _ = update(make_relink_event('takeover', text=self.foreign),
                          self.var_and_exp, model, self.value, eval_in_scope=eval)
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertEqual([(type(c).__name__, c.expression) for c in commands],
                         [('ChangeSelectedText',
                           "list(re.finditer(r'world', x, flags=re.M))")])

    def test_header_takeover_links_a_statement_action(self):
        """Linking to a header must pick an action that generates a header, or
        the first interaction would replace the block and orphan its body."""
        from string_visualizer_grammar import _STATEMENT_ACTIONS
        model, commands = self._took_over('if flag:')
        self.assertEqual(commands, [])
        self.assertIn(model.get('linked_action'), _STATEMENT_ACTIONS)

    def test_next_interaction_after_header_takeover_stays_a_header(self):
        model, _ = self._took_over('if flag:')
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].expression.rstrip().endswith(':'))


class TestCtxToModelRestoresSearch(unittest.TestCase):
    """_ctx_to_model must restore the search text from any parsed line the
    grammar can produce -- including the multi-index / pair-slice / broadcast
    forms, which used to fall through to search=None and leave a relinked
    visualizer with an empty search box (dimming every action)."""

    def _adopt(self, code):
        from string_visualizer import _ctx_to_model, parse_generated_code_or_assignment
        parsed, _prefix = parse_generated_code_or_assignment(code)
        self.assertIsNotNone(parsed, f'expected to parse: {code!r}')
        model = init_model('hello world')
        _ctx_to_model(parsed, model)
        return model

    def test_index_get(self):
        self.assertEqual(self._adopt('x_result = x[5]')['search'], '5')

    def test_slice_get(self):
        self.assertEqual(self._adopt('x[2:7]')['search'], '2:7')

    def test_open_slice_delete(self):
        self.assertEqual(self._adopt("x[:2] + ''")['search'], '2:')

    def test_multi_index_get(self):
        self.assertEqual(self._adopt('[x[i] for i in [0, 2, 4]]')['search'],
                         '[0, 2, 4]')

    def test_multi_index_transform_restores_search_and_map(self):
        model = self._adopt('[(lambda mtch: mtch.upper())(x[i]) for i in idxs]')
        self.assertEqual(model['search'], 'idxs')
        self.assertEqual(model['replace_text'], '$.upper()')

    def test_multi_pair_get(self):
        self.assertEqual(self._adopt('[x[i:j] for i, j in pairs]')['search'],
                         'pairs')

    def test_broadcast_start_list(self):
        self.assertEqual(self._adopt('[x[i:7] for i in starts]')['search'],
                         'starts:7')

    def test_broadcast_stop_list(self):
        self.assertEqual(self._adopt('[x[2:i] for i in stops]')['search'],
                         '2:stops')

    def test_broadcast_both_lists(self):
        self.assertEqual(
            self._adopt('[x[i:j] for i, j in zip(starts, stops)]')['search'],
            'starts:stops')

    def test_bare_expression_is_not_mistaken_for_a_search(self):
        """Any bare expression parses via the greedy multi-index catch-all
        (see parse_generated_code_or_assignment); without a source_expr there
        is no evidence it was ever a search, so the search box stays empty."""
        self.assertIsNone(self._adopt('y = some_str.upper()')['search'])


class TestRelinkTakeoverAdoptsIndexLines(unittest.TestCase):
    """Relink-takeover of index-tool lines: the search box must come back
    holding the index/slice/indices the line reaches for, and the next
    interaction must edit the line in place."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    def _take_over(self, text):
        model = init_model(self.value)
        return update(make_relink_event('takeover', text=text),
                      self.var_and_exp, model, self.value, eval_in_scope=eval)

    def test_index_line_restores_search(self):
        model, commands = self._take_over('x_result = x[5]')
        self.assertEqual(commands, [])
        self.assertEqual(model.get('linked_action'), 'find_or_map')
        self.assertEqual(model.get('search'), '5')

    def test_interaction_after_index_takeover_edits_in_place(self):
        model, _ = self._take_over('x_result = x[5]')
        model, commands = update(make_search_box_input_event('7'),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertEqual([(type(c).__name__, c.expression) for c in commands],
                         [('ChangeSelectedText', 'x[7]')])

    def test_multi_index_line_restores_search(self):
        model, commands = self._take_over('chars = [x[i] for i in [0, 2]]')
        self.assertEqual(commands, [])
        self.assertEqual(model.get('linked_action'), 'find_or_map')
        self.assertEqual(model.get('search'), '[0, 2]')

    def test_interaction_after_multi_index_takeover_edits_in_place(self):
        model, _ = self._take_over('chars = [x[i] for i in [0, 2]]')
        model, commands = update(make_search_box_input_event('[1, 3]'),
                                 self.var_and_exp, model, self.value,
                                 eval_in_scope=eval)
        self.assertEqual([(type(c).__name__, c.expression) for c in commands],
                         [('ChangeSelectedText', '[x[i] for i in [1, 3]]')])


class TestNoUnlinkButtonInActionBar(unittest.TestCase):
    """The unlink affordance moved to the front-end chain icon, so the
    visualizer no longer renders an 'Unlink' action button when linked."""

    def test_linked_render_has_no_unlink_button(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        model['linked_action'] = 'find_or_map'
        html_out = visualize(value, model, None, None)
        self.assertNotIn('Unlink', html_out)


class TestSkipUnchangedLinkedExpression(unittest.TestCase):
    """Once linked, do not emit ChangeSelectedText when the presumptive
    expression is identical to what was last written (e.g. hover / Enter)."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)
        self.model, first = update(make_search_box_input_event(r"r'hello'"),
                                   self.var_and_exp, self.model, self.value)
        self.assertEqual(len(first), 1)
        self.assertIsInstance(first[0], tuple)
        self.assertEqual(self.model.get('last_linked_expr'), first[0][1])

    def test_hover_mouse_move_emits_nothing(self):
        """Hover updates hoverIdx but must not rewrite the linked LOC."""
        model, commands = update(
            make_mouse_move_event(4, buttons=0, legacy_index=False),
            self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])
        self.assertEqual(model['linked_action'], 'match_strings')

    def test_changed_search_emits_change_selected_text(self):
        """A search edit that changes the expression still updates the linked LOC."""
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertIn("re.findall(r'world'", commands[0].expression)
        self.assertEqual(model['last_linked_expr'], commands[0].expression)

    def test_repeat_identical_search_emits_nothing(self):
        """Re-sending the same search value must not emit another ChangeSelectedText."""
        model, commands = update(make_search_box_input_event(r"r'hello'"),
                                 self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])

    def test_unlink_clears_last_linked_expr(self):
        model, commands = update(
            {'pythonEventStr': repr(Unlink()), 'eventJSON': {'type': 'unlink'}},
            self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])
        self.assertIsNone(model.get('linked_action'))
        self.assertIsNone(model.get('last_linked_expr'))


class TestLinkedActionChangeRenamesVar(unittest.TestCase):
    """When the action changes on a linked line, the ChangeSelectedText command
    should carry the newly-suggested variable name so the editor can rename the
    assignment target (if the prior name is unused elsewhere in the code)."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)
        # Auto-link via a first search-div interaction (action: find_or_map -> x_matches).
        self.model, first = update(make_search_box_input_event(r"r'hello'"),
                                   self.var_and_exp, self.model, self.value)
        self.assertEqual(first[0][0], 'x_strings')
        self.assertNotIn('linked_prefix', self.model)

    def test_action_change_emits_expression_and_name_suggestion(self):
        """Switching to 'count' should suggest x_count as the new var name."""
        model, commands = update(make_action_button_event('count'),
                                 self.var_and_exp, self.model, self.value)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(change_cmds[0].suggested_var_name, 'x_count')
        self.assertNotIn('x_matches = ', change_cmds[0].expression)

    def test_ordinary_update_preserves_editor_owned_name(self):
        """Search edits update only the expression, preserving the editor's name."""
        # Re-emitting find_or_map (e.g. via search box change) keeps x_matches.
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, self.model, self.value)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertIsNone(change_cmds[0].suggested_var_name)

    def test_action_round_trip_resends_original_name_suggestion(self):
        """Name suggestions follow action changes, not a cached assignment name."""
        model, _ = update(make_action_button_event('delete'),
                          self.var_and_exp, self.model, self.value)
        model, commands = update(make_action_button_event('find_or_map'),
                                 self.var_and_exp, model, self.value)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(change_cmds[0].suggested_var_name, 'x_matches')

    def test_new_var_name_none_for_statement_action(self):
        """Statement actions (no assignment target) carry no new var name."""
        model, commands = update(make_action_button_event('if_any'),
                                 self.var_and_exp, self.model, self.value)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertIsNone(change_cmds[0].suggested_var_name)


class TestLinkedActionChangesShape(unittest.TestCase):
    """Switching a linked line between an expression action and a statement one.

    A header cannot be assigned to a name and an expression cannot open a block,
    so the shape has to be read off the code being written rather than
    remembered from the action that linked the line. A stale answer makes the
    update unparseable and it is dropped in silence — the user clicks Loop and
    nothing happens.
    """

    def setUp(self):
        self.value = "hello world hello"
        self.var_and_exp = ('x', 'x')

    def _linked(self):
        """Auto-linked via a search-box interaction (find_or_map -> x_strings)."""
        model = init_model(self.value)
        model, commands = update(make_search_box_input_event(r"r'hello'"),
                                 self.var_and_exp, model, self.value)
        self.assertEqual(commands[0][0], 'x_strings')
        return model

    def _switch_to(self, model, action):
        model, commands = update(make_action_button_event(action),
                                 self.var_and_exp, model, self.value)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1,
                         f'switching to {action!r} wrote nothing to the linked line')
        return model, changes[0]

    def test_switches_to_loop(self):
        model, change = self._switch_to(self._linked(), 'loop')
        self.assertEqual(change.expression,
                         "for i, mtch in enumerate(re.finditer(r'hello', x, flags=re.M)):")
        self.assertEqual(model.get('last_linked_expr'), change.expression)

    def test_switches_to_loop_match_strings(self):
        _, change = self._switch_to(self._linked(), 'loop_match_strings')
        self.assertEqual(change.expression,
                         "for i, s in enumerate(re.findall(r'hello', x, flags=re.M)):")

    def test_switches_to_if_any(self):
        _, change = self._switch_to(self._linked(), 'if_any')
        self.assertEqual(change.expression, "if re.search(r'hello', x, flags=re.M):")

    def test_switches_back_to_an_expression(self):
        model, _ = self._switch_to(self._linked(), 'loop')
        _, change = self._switch_to(model, 'count')
        self.assertEqual(change.expression,
                         "sum(1 for _ in re.finditer(r'hello', x, flags=re.M))")

    def test_search_change_after_a_shape_switch_still_updates(self):
        """The switch must leave last_linked_expr describing what is actually on
        the line, or the next interaction is suppressed as a no-op."""
        model, _ = self._switch_to(self._linked(), 'loop')
        model, commands = update(make_search_box_input_event(r"r'world'"),
                                 self.var_and_exp, model, self.value)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].expression,
                         "for i, mtch in enumerate(re.finditer(r'world', x, flags=re.M)):")


class TestSingleQuoteEscaping(unittest.TestCase):
    """Single quotes in regex literal segments must be escaped for r'' strings."""

    def test_char_to_regex_literal_escapes_single_quote(self):
        self.assertEqual(char_to_regex_literal("'"), "\\'")

    def test_literal_selection_with_single_quote_stores_escaped(self):
        value = "it's here"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5),
                         var_and_exp, model, value)

        self.assertEqual(model['search'], r'''r"it\'s"''')

    def test_enter_with_single_quote_generates_valid_raw_string(self):
        value = "it's here"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5),
                         var_and_exp, model, value)
        model, commands = update(make_mouse_up_event(5),
                         var_and_exp, model, value)
        # Auto-link inserts the find LOC; expression must use a valid raw string.
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn("r'it\\'s'", commands[0][1])

    def test_backspace_with_single_quote_generates_valid_raw_string(self):
        value = "it's here"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model, _ = update(make_mouse_down_event(2, top_half=True),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_move_event(5),
                         var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5),
                         var_and_exp, model, value)

        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                var_and_exp, model, value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertIn("r'it\\'s'", commands[0].expression)


class TestBareExpressionSuggestions(unittest.TestCase):
    """Tests for suggested variable names with bare expressions."""

    def test_bare_expression_suggests_result_matches(self):
        """For a bare expression (not an assignment), suggested name is result_matches."""
        model = init_model("hello world")
        model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Enter'),
                                (None, "print('hello world')"), model, "hello world")
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "result_strings")
        self.assertIn("re.findall(r'hello'", expr)

    def test_bare_expression_suggests_result_for_delete(self):
        """For a bare expression, Backspace suggests 'result' as var name."""
        model = init_model("hello world")
        model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                (None, "print('hello world')"), model, "hello world")
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "result")
        self.assertIn("re.sub(r'hello'", expr)

    def test_linked_bare_expression_keeps_result_name_for_slices(self):
        """Linked source expressions must not become assignment-name prefixes."""
        model = init_model("hello world")
        search = '[item.start() for item in str3_matches]:'
        eval_in_scope = lambda _expr: [0, 6]

        model, commands = update(
            make_search_box_input_event(search),
            (None, 'str3'),
            model,
            "hello world",
            eval_in_scope=eval_in_scope,
        )
        self.assertEqual(commands[0][0], 'result_slices')
        self.assertEqual(model['linked_source_expr'], '(str3)')

        # Switching action still suggests result_* (not str3_*) when renaming.
        model, commands = update(
            make_action_button_event('count'),
            (None, 'str3'),
            model,
            "hello world",
            eval_in_scope=eval_in_scope,
        )
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertEqual(commands[0].suggested_var_name, 'result_count')


class TestSearchBoxEscape(unittest.TestCase):
    """Test Escape key interactions with the search box."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_escape_clears_search_box_typed_regex(self):
        """Escape clears a regex that was typed in the search box."""
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        model, _ = update(make_key_down_event('Escape'),
                          self.var_and_exp, model, self.value)

        self.assertIsNone(model['search'])
        # The typed regex should be in undo history (recoverable)
        self.assertIn(r"r'(hello)'", model['undoHistory'])


class TestSearchBoxHighlighting(unittest.TestCase):
    """Test that regex typed in search box produces correct highlighting."""

    def test_typed_regex_with_groups_highlights_segments(self):
        """A typed regex with groups produces segment highlights."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(hello)(.*)(world)'"

        highlights = parse_regex_for_highlighting(model['search'], value)
        self.assertEqual(len(highlights), 3)

        # First segment: literal "hello"
        self.assertEqual(highlights[0][2], 'literal')

        # Second segment: fuzzy (.*)
        self.assertEqual(highlights[1][2], 'fuzzy')

        # Third segment: literal "world"
        self.assertEqual(highlights[2][2], 'literal')

    def test_typed_regex_without_groups_still_highlights_segments(self):
        """A typed regex without groups still produces segment highlights."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello.*world'"

        highlights = parse_regex_for_highlighting(model['search'], value)
        # Canonical parsing identifies segments even without explicit groups
        self.assertEqual(len(highlights), 3)

    def test_typed_invalid_regex_no_highlights(self):
        """An invalid regex produces no highlights (graceful handling)."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'[unclosed'"

        highlights = parse_regex_for_highlighting(model['search'], value)
        self.assertEqual(len(highlights), 0)

    def test_typed_regex_no_match_no_highlights(self):
        """A valid regex that doesn't match produces no highlights."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(xyz)'"

        highlights = parse_regex_for_highlighting(model['search'], value)
        self.assertEqual(len(highlights), 0)


class TestSearchBoxMultipleRoundTrips(unittest.TestCase):
    """Test multiple round trips between search box and mouse interactions."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_mouse_then_searchbox_then_mouse_then_searchbox(self):
        """Multiple alternations between mouse and search box.

        Mouse: /(hello)/
        Search box: /(hello)(.*)/
        Mouse: click inside fuzzy -> its segment menu opens, pattern kept
        Search box: tweak to /(hello)(\\s+)(world)/
        """
        # Mouse: select "hello"
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

        # Search box: add fuzzy
        model, _ = update(make_search_box_input_event(r"r'(hello)(.*)'"),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(.*)'")

        # Mouse: click inside fuzzy opens its menu, keeping the pattern
        model, _ = update(make_mouse_down_event(8, top_half=True),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(8),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(.*)'")
        self.assertEqual(model['openDropdown']['id'], 'segment-menu-0-1')

        # Escape dismisses the menu
        model, _ = update(make_key_down_event('Escape'),
                          self.var_and_exp, model, self.value)
        self.assertIsNone(model.get('openDropdown'))

        # Search box: tweak fuzzy to \s+ and pin "world"
        model, _ = update(make_search_box_input_event(r"r'(hello)(\s+)(world)'"),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(\s+)(world)'")

        # Verify the full undo history
        self.assertEqual(model['undoHistory'], [
            None,
            r"r'hello'",
            r"r'(hello)(.*)'",
        ])

    def test_searchbox_to_mouse_preserves_undo_chain(self):
        """Switching input methods doesn't break the undo chain."""
        # Search box
        model, _ = update(make_search_box_input_event(r"r'(hello)'"),
                          self.var_and_exp, self.model, self.value)

        # Mouse extend
        end_idx = get_last_segment_end_internal_idx(model['search'], self.value)
        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello\s*'")

        # Search box again
        model, _ = update(make_search_box_input_event(r"r'(hello)(\d+)'"),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(\d+)'")

        # Undo all the way back
        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello\s*'")

        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'(hello)'")

        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, self.value)
        self.assertIsNone(model['search'])

    def test_incremental_typing_in_search_box(self):
        """Simulates the user incrementally typing a regex character by character.

        Each keystroke fires an input event with the full current value.
        """
        model = self.model

        # Type "/" -> "/h" -> "/he" -> "/hel" -> "/hell" -> "/hello" -> "/hello/"
        steps = ['/', '/h', '/he', '/hel', '/hell', '/hello', r"r'hello'"]
        for step_value in steps:
            model, _ = update(make_search_box_input_event(step_value),
                              self.var_and_exp, model, self.value)
            self.assertEqual(model['search'], step_value)

        # Only the changing values should be in undo history
        self.assertEqual(model['undoHistory'], [None, '/', '/h', '/he', '/hel', '/hell', '/hello'])


# =============================================================================
# Test Helper: Handle Mouse Down Events
# =============================================================================

def make_handle_mouse_down_event(segment_index: int, side: str, match_index: int = 0) -> dict:
    """Create a HandleMouseDown event dict for drag handle interaction.

    Args:
        segment_index: Index of the segment whose handle is being dragged
        side: 'left', 'right', or 'seam' - which handle
        match_index: Which occurrence of the pattern the handle belongs to
    """
    return {
        'pythonEventStr': repr(HandleMouseDown(segment_index=segment_index, side=side,
                                               match_index=match_index)),
        'eventJSON': {
            'buttons': 1,
        }
    }


# =============================================================================
# Tests: resize_literal_segment (core function)
# =============================================================================

class TestResizeLiteralSegment(unittest.TestCase):
    """Test the resize_literal_segment function that modifies a literal segment's boundaries.

    For "hello world", internal indices are:
        0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z

    /(hello)/ matches "hello" at string indices 0-4, internal range [2, 7).
    """

    def setUp(self):
        self.value = "hello world"

    def test_expand_right(self):
        """Expand 'hello' right to include space -> 'hello '."""
        result = resize_literal_segment(r"r'(hello)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(8))
        self.assertEqual(result, r"r'(hello\ )'")

    def test_collapse_right(self):
        """Collapse 'hello' from right to 'hell'."""
        result = resize_literal_segment(r"r'(hello)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(6))
        self.assertEqual(result, r"r'(hell)'")

    def test_expand_left(self):
        """Expand 'ello' left to include 'h' -> 'hello'."""
        result = resize_literal_segment(r"r'(ello)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(7))
        self.assertEqual(result, r"r'(hello)'")

    def test_collapse_left(self):
        """Collapse 'hello' from left to 'ello'."""
        result = resize_literal_segment(r"r'(hello)'", 0, self.value, _legacy_internal_index(3), _legacy_internal_index(7))
        self.assertEqual(result, r"r'(ello)'")

    def test_single_char(self):
        """Resize to single char 'h'."""
        result = resize_literal_segment(r"r'(hello)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(3))
        self.assertEqual(result, r"r'(h)'")

    def test_no_change_if_empty_range(self):
        """Empty range (new_end <= new_start) returns original regex unchanged."""
        result = resize_literal_segment(r"r'(hello)'", 0, self.value, _legacy_internal_index(5), _legacy_internal_index(5))
        self.assertEqual(result, r"r'(hello)'")

    def test_multi_segment_resize_first(self):
        """Resize first segment in multi-segment regex."""
        result = resize_literal_segment(r"r'(hello)(.*)(world)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(8))
        self.assertEqual(result, r"r'(hello\ )(.*)(world)'")

    def test_multi_segment_resize_last(self):
        """Resize last segment in multi-segment regex."""
        result = resize_literal_segment(r"r'(hello)(.*)(world)'", 2, self.value, _legacy_internal_index(7), _legacy_internal_index(13))
        self.assertEqual(result, r"r'(hello)(.*)(\ world)'")

    def test_preserves_other_segments(self):
        """Other segments are unchanged when one is resized."""
        result = resize_literal_segment(r"r'(hello)(.*)(world)'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(3))
        self.assertEqual(result, r"r'(h)(.*)(world)'")

    # --- Canonical ungrouped form (the form actually stored in model) ---

    def test_ungrouped_single_expand_right(self):
        """Ungrouped /hello/ expanded right to include space."""
        result = resize_literal_segment(r"r'hello'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(8))
        self.assertEqual(result, r"r'hello\ '")

    def test_ungrouped_single_collapse_right(self):
        """Ungrouped /hello/ collapsed from right to 'hell'."""
        result = resize_literal_segment(r"r'hello'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(6))
        self.assertEqual(result, r"r'hell'")

    def test_ungrouped_single_collapse_left(self):
        """Ungrouped /hello/ collapsed from left to 'ello'."""
        result = resize_literal_segment(r"r'hello'", 0, self.value, _legacy_internal_index(3), _legacy_internal_index(7))
        self.assertEqual(result, r"r'ello'")

    def test_ungrouped_single_char_expand(self):
        """Ungrouped single char /h/ expanded right."""
        result = resize_literal_segment(r"r'h'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(4))
        self.assertEqual(result, r"r'he'")

    def test_ungrouped_multi_segment_resize_first(self):
        """Ungrouped /hello.*world/ resize first literal segment."""
        result = resize_literal_segment(r"r'hello.*world'", 0, self.value, _legacy_internal_index(2), _legacy_internal_index(8))
        self.assertEqual(result, r"r'hello\ .*world'")

    def test_ungrouped_multi_segment_resize_last(self):
        """Ungrouped /hello.*world/ resize last literal segment."""
        result = resize_literal_segment(r"r'hello.*world'", 2, self.value, _legacy_internal_index(7), _legacy_internal_index(13))
        self.assertEqual(result, r"r'hello.*\ world'")


# =============================================================================
# Tests: resize_fuzzy_segment (core function)
# =============================================================================

class TestResizeFuzzySegment(unittest.TestCase):
    """Test resize_fuzzy_segment, which re-runs fuzzy pattern inference on the
    new boundaries instead of converting the segment to a literal.

    For "hello world", internal indices are:
        0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z
    """

    def setUp(self):
        self.value = "hello world"

    def test_lone_fuzzy_over_letters_infers_char_class(self):
        r"""Resizing a lone /(.*)/ over "hello" infers [a-z]+ (both ends open -> +)."""
        result = resize_fuzzy_segment(r"r'(.*)'", 0, self.value,
                                      _legacy_internal_index(2), _legacy_internal_index(7),
                                      prev_char='', next_char=' ')
        self.assertEqual(result, r"r'([a-z]+)'")

    def test_lone_fuzzy_stays_fuzzy_not_literal(self):
        """Resizing a fuzzy segment must NOT produce escaped literal text."""
        result = resize_fuzzy_segment(r"r'(.*)'", 0, self.value,
                                      _legacy_internal_index(2), _legacy_internal_index(7),
                                      prev_char='', next_char=' ')
        self.assertNotIn('hello', result)

    def test_fuzzy_adjacent_left_literal_uses_star(self):
        r"""With a literal neighbor on the left (prev_char=None), inference uses *."""
        result = resize_fuzzy_segment(r"r'(hello)(.*)'", 1, self.value,
                                      _legacy_internal_index(7), _legacy_internal_index(8),
                                      prev_char=None, next_char='w')
        self.assertEqual(result, r"r'(hello)(\s*)'")

    def test_fuzzy_adjacent_right_literal_uses_star(self):
        r"""With a literal neighbor on the right (next_char=None), inference uses *.

        Lazy because [a-z]* can reach the 'w' of world and would otherwise bind
        it to its last occurrence.
        """
        result = resize_fuzzy_segment(r"r'(.*)(world)'", 0, self.value,
                                      _legacy_internal_index(2), _legacy_internal_index(7),
                                      prev_char='', next_char=None)
        self.assertEqual(result, r"r'([a-z]*?)(world)'")

    def test_no_change_if_empty_range(self):
        """Empty range (new_end <= new_start) returns the original regex unchanged."""
        result = resize_fuzzy_segment(r"r'(.*)'", 0, self.value,
                                      _legacy_internal_index(5), _legacy_internal_index(5),
                                      prev_char='', next_char='')
        self.assertEqual(result, r"r'(.*)'")

    def test_ungrouped_lone_fuzzy(self):
        r"""Ungrouped /.*/ over "hello" infers [a-z]+ without adding a group."""
        result = resize_fuzzy_segment(r"r'.*'", 0, self.value,
                                      _legacy_internal_index(2), _legacy_internal_index(7),
                                      prev_char='', next_char=' ')
        self.assertEqual(result, r"r'[a-z]+'")


# =============================================================================
# Tests: Literal Drag Handle Update Logic
# =============================================================================

class TestLiteralDragHandleUpdate(unittest.TestCase):
    """Test the handle drag interaction flow through update().

    For "hello world", internal indices are:
        0=\\A, 1=^, 2=h, 3=e, 4=l, 5=l, 6=o, 7=' ', 8=w, 9=o, 10=r, 11=l, 12=d, 13=$, 14=\\Z
    """

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    # --- Handle drag start ---

    def test_handle_mouse_down_right_starts_drag(self):
        """HandleMouseDown on right side starts handle drag mode."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, commands = update(make_handle_mouse_down_event(0, 'right'),
                                 self.var_and_exp, model, self.value)

        self.assertIsNotNone(model.get('handleDrag'))
        self.assertEqual(model['handleDrag']['segmentIndex'], 0)
        self.assertEqual(model['handleDrag']['side'], 'right')
        # Drag start with a pattern already present auto-inserts the find LOC.
        self.assertTrue(all('findall' in _command_text(c) for c in commands))

    def test_handle_mouse_down_left_starts_drag(self):
        """HandleMouseDown on left side starts handle drag mode."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, commands = update(make_handle_mouse_down_event(0, 'left'),
                                 self.var_and_exp, model, self.value)

        self.assertIsNotNone(model.get('handleDrag'))
        self.assertEqual(model['handleDrag']['segmentIndex'], 0)
        self.assertEqual(model['handleDrag']['side'], 'left')

    # --- Mouse move during handle drag ---

    def test_mouse_move_during_handle_drag_updates_cursor(self):
        """MouseMove during handle drag updates the drag cursor position."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(8),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['handleDrag']['cursorIdx'], _legacy_internal_index(8))

    def test_mouse_move_during_handle_drag_does_not_start_new_selection(self):
        """MouseMove during handle drag should NOT set anchorIdx/cursorIdx on model root."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(8),
                          self.var_and_exp, model, self.value)

        # The normal drag state should not be set
        self.assertIsNone(model.get('anchorIdx'))
        self.assertFalse(model.get('dragging', False))

    # --- Mouse up finalizes handle drag ---

    def test_mouse_up_finalizes_handle_drag(self):
        """MouseUp finalizes the handle drag and clears handleDrag state."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7),
                          self.var_and_exp, model, self.value)

        self.assertIsNone(model.get('handleDrag'))

    # --- Full drag right handle sequences ---

    def test_drag_right_handle_right_expands(self):
        """Drag right handle rightward: hello -> hello (space)."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello\ )'")

    def test_drag_right_handle_left_collapses(self):
        """Drag right handle leftward: hello -> hell."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        # hello is internal [2,7). Drag right handle to index 5 (second l).
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(5),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(5),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hell)'")

    # --- Full drag left handle sequences ---

    def test_drag_left_handle_left_expands(self):
        """Drag left handle leftward: ello -> hello."""
        model = init_model(self.value)
        model['search'] = r"r'(ello)'"

        # ello matches internal [3,7). Drag left handle to index 2 (h).
        model, _ = update(make_handle_mouse_down_event(0, 'left'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(2),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(2),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)'")

    def test_drag_left_handle_right_collapses(self):
        """Drag left handle rightward: hello -> ello."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        # hello is internal [2,7). Drag left handle to index 3 (e).
        model, _ = update(make_handle_mouse_down_event(0, 'left'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(3),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(3),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(ello)'")

    # --- Minimum size: cannot collapse to empty ---

    def test_right_handle_cannot_collapse_past_start(self):
        """Dragging right handle past start keeps at least 1 char."""
        model = init_model(self.value)
        model['search'] = r"r'(h)'"

        # h is internal [2,3). Drag right handle to index 1 (past start).
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(1),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(1),
                          self.var_and_exp, model, self.value)

        # Should stay as /(h)/ - at least 1 char
        self.assertEqual(model['search'], r"r'(h)'")

    def test_left_handle_cannot_collapse_past_end(self):
        """Dragging left handle past end keeps at least 1 char."""
        model = init_model(self.value)
        model['search'] = r"r'(h)'"

        # h is internal [2,3). Drag left handle to index 3 (past end).
        model, _ = update(make_handle_mouse_down_event(0, 'left'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(3),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(3),
                          self.var_and_exp, model, self.value)

        # Should stay as /(h)/ - at least 1 char
        self.assertEqual(model['search'], r"r'(h)'")

    # --- Multi-segment resize ---

    def test_resize_first_segment_in_multi(self):
        """Resize first segment in /(hello)(.*)(world)/."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)(.*)(world)'"

        # Drag right handle of hello to include space.
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello\ )(.*)(world)'")

    def test_resize_last_segment_in_multi(self):
        """Resize last segment in /(hello)(.*)(world)/."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)(.*)(world)'"

        # world is internal [8,13). Drag left handle to index 7 (space).
        model, _ = update(make_handle_mouse_down_event(2, 'left'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)(.*)(\ world)'")

    # --- Undo history ---

    def test_handle_drag_saves_to_undo_history(self):
        """Handle drag finalization saves old regex to undo history."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(7),
                          self.var_and_exp, model, self.value)

        self.assertIn(r"r'(hello)'", model['undoHistory'])

    def test_handle_drag_no_change_does_not_add_to_undo(self):
        """If handle is dragged back to original position, no undo entry."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        undo_before = list(model.get('undoHistory', []))

        # Drag right handle to 8 then back to 6 (original last char index).
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(8),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(hello)'")
        self.assertEqual(model.get('undoHistory', []), undo_before)

    # --- Preview during drag ---

    def test_preview_shows_resized_segment_during_drag(self):
        """During handle drag, the visualize output reflects the resized segment."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)

        # Still in handle-drag mode (no mouse-up yet).
        self.assertIsNotNone(model.get('handleDrag'))

        # The visualize function should use the preview regex which includes the space.
        html_output = visualize(self.value, model, None, None)
        # The literal highlight is now applied via the 'highlight literal' CSS classes
        # on individual char-spans (CSS supplies the border styling).
        self.assertIn('highlight literal', html_output)

    # --- Mouse released outside (buttons=0) during handle drag ---

    def test_mouse_move_buttons_0_finalizes_handle_drag(self):
        """MouseMove with buttons=0 during handle drag finalizes it."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"

        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)

        # Mouse released outside - buttons=0
        model, _ = update(make_mouse_move_event(8, buttons=0),
                          self.var_and_exp, model, self.value)

        self.assertIsNone(model.get('handleDrag'))
        self.assertEqual(model['search'], r"r'(hello\ )'")


# =============================================================================
# Tests: Fuzzy Drag Handle Update Logic
# =============================================================================

class TestFuzzyDragHandleUpdate(unittest.TestCase):
    """Dragging a fuzzy segment's handle re-runs fuzzy pattern inference on the
    new range (it must NOT convert the segment into a literal).

    For "abc 123", current internal indices are:
        0=^, 1=a, 2=b, 3=c, 4=' ', 5=1, 6=2, 7=3, 8=$
    """

    def setUp(self):
        self.value = "abc 123"
        self.var_and_exp = ('x', 'x')

    def test_drag_left_handle_infers_digit_class(self):
        r"""Lone /(.*)/ dragged from the left down to "123" infers \d+ (open right)."""
        model = init_model(self.value)
        model['search'] = r"r'(.*)'"

        model, _ = update(make_handle_mouse_down_event(0, 'left'),
                          self.var_and_exp, model, self.value)
        # Move left handle so the segment starts at the '1' (legacy index 6).
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(\d+)'")

    def test_drag_right_handle_infers_letter_class(self):
        r"""Lone /(.*)/ dragged from the right down to "abc" infers [a-z]+ (open left)."""
        model = init_model(self.value)
        model['search'] = r"r'(.*)'"

        # Move right handle so the segment ends after 'c' (cursor on 'c', legacy index 4).
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(4),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(4),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'([a-z]+)'")

    def test_drag_fuzzy_handle_does_not_create_literal(self):
        """Resizing a fuzzy segment never bakes the dragged text in as a literal."""
        model = init_model(self.value)
        model['search'] = r"r'(.*)'"

        model, _ = update(make_handle_mouse_down_event(0, 'left'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)

        self.assertNotIn('123', model['search'])

    def test_drag_trailing_fuzzy_after_literal_uses_star(self):
        r"""In /(abc)(.*)/, dragging the trailing fuzzy keeps a literal neighbor -> \s*."""
        model = init_model(self.value)
        model['search'] = r"r'(abc)(.*)'"

        # Fuzzy segment (index 1) matches " 123" starting at the space (index 4).
        # Drag its open right end back so it covers only the space (cursor on space,
        # legacy index 5 -> current 4).
        model, _ = update(make_handle_mouse_down_event(1, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(5),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(5),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'(abc)(\s*)'")


# =============================================================================
# Tests: Literal Drag Handle Rendering
# =============================================================================

class TestLiteralDragHandleRendering(unittest.TestCase):
    """Test that drag handles appear in HTML for literal segments, not fuzzy.

    Handles render only on the active (here: hovered) segment; see
    TestHandlesOnlyOnActiveSegment."""

    def setUp(self):
        self.value = "hello world"

    def test_literal_segment_has_resize_handle(self):
        """Literal selection bracket renders chr-resize-handle elements (CSS gives them ew-resize cursor)."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model['hoverIdx'] = 3
        html_output = visualize(self.value, model, None, None)
        self.assertIn('chr-resize-handle', html_output)

    def test_literal_segment_has_left_handle(self):
        """First char of literal segment renders a left drag handle."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model['hoverIdx'] = 3
        html_output = visualize(self.value, model, None, None)
        self.assertIn("side=&#x27;left&#x27;", html_output)

    def test_literal_segment_has_right_handle(self):
        """Last char of literal segment renders a right drag handle."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model['hoverIdx'] = 3
        html_output = visualize(self.value, model, None, None)
        self.assertIn("side=&#x27;right&#x27;", html_output)

    def test_literal_handle_has_HandleMouseDown_event(self):
        """Drag handle elements have HandleMouseDown event attribute."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model['hoverIdx'] = 3
        html_output = visualize(self.value, model, None, None)
        self.assertIn('HandleMouseDown', html_output)

    def test_lone_fuzzy_segment_has_both_drag_handles(self):
        """A standalone fuzzy selection has BOTH ends open, so it gets two handles."""
        model = init_model(self.value)
        model['search'] = r"r'(.*)'"
        model['hoverIdx'] = 5  # inside the first (whole-string) occurrence
        html_output = visualize(self.value, model, None, None)
        # One handle per open end, on the hovered occurrence only.
        self.assertEqual(html_output.count('HandleMouseDown'), 2)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", html_output)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", html_output)

    def test_fuzzy_open_right_has_right_handle_only(self):
        """In /(hello)(.*)/, the trailing fuzzy has an open RIGHT end only."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)(.*)'"
        model['hoverIdx'] = 8  # inside the fuzzy segment
        html_output = visualize(self.value, model, None, None)
        # Fuzzy is segment index 1: right handle present, left handle absent.
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;right&#x27;", html_output)
        self.assertNotIn("HandleMouseDown(segment_index=1, side=&#x27;left&#x27;", html_output)

    def test_fuzzy_open_left_has_left_handle_only(self):
        """In /(.*)(world)/, the leading fuzzy has an open LEFT end only."""
        model = init_model(self.value)
        model['search'] = r"r'(.*)(world)'"
        model['hoverIdx'] = 3  # inside the fuzzy segment
        html_output = visualize(self.value, model, None, None)
        # Fuzzy is segment index 0: left handle present, right handle absent.
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;", html_output)
        self.assertNotIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;", html_output)

    def test_mixed_segments_interior_boundaries_are_seams(self):
        """In /(hello)(.*)(world)/, a hovered literal gets a plain handle on
        its open outer edge and a shared seam handle at the boundary with the
        fuzzy; the flanked fuzzy has only seams on both sides."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)(.*)(world)'"
        model['hoverIdx'] = 3  # inside the 'hello' literal
        html_output = visualize(self.value, model, None, None)
        self.assertEqual(html_output.count('HandleMouseDown'), 2)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;", html_output)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;seam&#x27;", html_output)

        # Hovering the flanked fuzzy (segment index 1, the ' ' between the
        # literals) shows the seams on both of its sides, nothing else.
        model['hoverIdx'] = 6
        html_output = visualize(self.value, model, None, None)
        self.assertEqual(html_output.count('HandleMouseDown'), 2)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;seam&#x27;", html_output)
        self.assertIn("HandleMouseDown(segment_index=2, side=&#x27;seam&#x27;", html_output)


# =============================================================================
# Test Helper: Repetition Input Events
# =============================================================================

def make_repetition_input_event(dropdown_id: str, field: str, value: str) -> dict:
    """Create a RepetitionInput event dict for repetition text field interaction.

    Args:
        dropdown_id: The dropdown ID (e.g., 'repetition-0')
        field: Which field changed: 'exact', 'min', or 'max'
        value: The new value of the field
    """
    return {
        'pythonEventStr': repr(RepetitionInput(dropdown_id=dropdown_id, field=field, value=value)),
        'eventJSON': {}
    }


# =============================================================================
# Tests: replace_segment_repetition (core function)
# =============================================================================

class TestReplaceSegmentRepetition(unittest.TestCase):
    """Test the replace_segment_repetition function that modifies a segment's quantifier.

    replace_segment_repetition should replace the quantifier of a segment,
    preserving the base pattern (character class or literal content).

    Note: Results are canonicalized, so groups are only kept when:
    - Two adjacent non-fuzzy (literal) segments exist, OR
    - The segment text contains non-capturing groups (?:...)
    Single-segment regexes always have groups stripped.
    """

    # --- Fuzzy segment (single atom) repetition changes ---

    def test_replace_star_with_plus_on_fuzzy(self):
        """Replacing .* quantifier with + gives .+ (canonical: no group for single segment)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '+')
        self.assertEqual(result, r"r'.+'")

    def test_replace_star_with_question_on_fuzzy(self):
        """Replacing .* quantifier with ? gives .? (canonical)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '?')
        self.assertEqual(result, r"r'.?'")

    def test_replace_star_with_exact_on_fuzzy(self):
        """Replacing .* quantifier with {3} gives .{3} (canonical)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '{3}')
        self.assertEqual(result, r"r'.{3}'")

    def test_replace_star_with_range_on_fuzzy(self):
        """Replacing .* quantifier with {2,5} gives .{2,5} (canonical)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '{2,5}')
        self.assertEqual(result, r"r'.{2,5}'")

    def test_replace_star_with_no_quantifier_on_fuzzy(self):
        """Replacing .* with '' (exactly 1) gives . (canonical)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '')
        self.assertEqual(result, r"r'.'")

    def test_replace_plus_with_star_on_fuzzy(self):
        """Replacing .+ quantifier with * gives .* (canonical)."""
        result = replace_segment_repetition(r"r'(.+)'", 0, '*')
        self.assertEqual(result, r"r'.*'")

    def test_replace_on_char_class_fuzzy(self):
        r"""Replacing \s* quantifier with + gives \s+ (canonical)."""
        result = replace_segment_repetition(r"r'(\s*)'", 0, '+')
        self.assertEqual(result, r"r'\s+'")

    def test_replace_on_bracket_class_fuzzy(self):
        """Replacing [a-z]* quantifier with {2,5} gives [a-z]{2,5} (canonical)."""
        result = replace_segment_repetition(r"r'([a-z]*)'", 0, '{2,5}')
        self.assertEqual(result, r"r'[a-z]{2,5}'")

    # --- Literal segment (single char) repetition changes ---

    def test_replace_repetition_on_literal_single_char(self):
        """Adding + to single char literal 'h' gives h+ (canonical: no group)."""
        result = replace_segment_repetition(r"r'(h)'", 0, '+')
        self.assertEqual(result, r"r'h+'")

    def test_replace_single_char_with_exact(self):
        """Adding {3} to single char literal 'h' gives h{3} (canonical: no group)."""
        result = replace_segment_repetition(r"r'(h)'", 0, '{3}')
        self.assertEqual(result, r"r'h{3}'")

    # --- Literal segment (multi char) repetition changes ---

    def test_replace_repetition_on_literal_multi_char(self):
        """Adding + to multi-char literal 'hello' wraps in (?:hello)+ and keeps group."""
        result = replace_segment_repetition(r"r'(hello)'", 0, '+')
        # Group kept because text contains (?:
        self.assertEqual(result, r"r'((?:hello)+)'")

    def test_replace_repetition_on_literal_multi_char_exact(self):
        """Adding {3} to multi-char literal 'hello' wraps in (?:hello){3}."""
        result = replace_segment_repetition(r"r'(hello)'", 0, '{3}')
        self.assertEqual(result, r"r'((?:hello){3})'")

    def test_remove_repetition_from_literal_multi_char(self):
        """Removing quantifier from (?:hello)+ gives back hello (canonical: no group)."""
        result = replace_segment_repetition(r"r'((?:hello)+)'", 0, '')
        # Unwraps (?:...) and removes group since no (?:) in result
        self.assertEqual(result, r"r'hello'")

    def test_change_repetition_on_literal_multi_char(self):
        """Changing (?:hello)+ to (?:hello){2,5} keeps group."""
        result = replace_segment_repetition(r"r'((?:hello)+)'", 0, '{2,5}')
        self.assertEqual(result, r"r'((?:hello){2,5})'")

    # --- Multi-segment regex (canonical form strips groups for non-adjacent-literal segments) ---

    def test_replace_in_middle_segment(self):
        """Replace repetition of middle (fuzzy) segment in multi-segment regex.

        Canonical form: no adjacent literals -> no groups needed.
        """
        result = replace_segment_repetition(r"r'(hello)(.*)(world)'", 1, '+')
        self.assertEqual(result, r"r'hello.+world'")

    def test_replace_preserves_other_segments(self):
        """When adding (?:...) to one segment, it keeps its group."""
        result = replace_segment_repetition(r"r'(hello)(.*)(world)'", 0, '{3}')
        # (?:hello){3} segment keeps group, others get canonicalized
        self.assertEqual(result, r"r'((?:hello){3}).*world'")

    def test_replace_last_segment_repetition(self):
        """Replace repetition of last segment wraps in (?:...) and keeps group."""
        result = replace_segment_repetition(r"r'(hello)(.*)(world)'", 2, '+')
        self.assertEqual(result, r"r'hello.*((?:world)+)'")

    # --- Edge cases ---

    def test_out_of_bounds_index_unchanged(self):
        """Out of bounds segment index leaves regex unchanged (canonical form)."""
        result = replace_segment_repetition(r"r'(hello)'", 5, '+')
        self.assertEqual(result, r"r'hello'")

    def test_replace_with_min_only_range(self):
        """Replace with {2,} (2 or more) quantifier (canonical)."""
        result = replace_segment_repetition(r"r'(.*)'", 0, '{2,}')
        self.assertEqual(result, r"r'.{2,}'")

    def test_escaped_chars_in_literal(self):
        r"""Escaped chars like \n are single atoms, no wrapping needed (canonical)."""
        result = replace_segment_repetition(r"r'(\n)'", 0, '+')
        self.assertEqual(result, r"r'\n+'")


# =============================================================================
# Tests: Repetition Dropdown Toggle
# =============================================================================

class TestRepetitionDropdownToggle(unittest.TestCase):
    """Tests for toggling the repetition dropdown via DropdownToggle."""

    def test_repetition_dropdown_toggle_opens(self):
        """DropdownToggle with repetition-* ID opens the repetition dropdown."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)'"
        self.assertIsNone(model.get('openDropdown'))

        event = make_dropdown_toggle_event('repetition-0')
        model, _ = update(event, None, model, "hello world")

        self.assertIsNotNone(model.get('openDropdown'))
        self.assertEqual(model['openDropdown']['id'], 'repetition-0')
        self.assertEqual(model['openDropdown']['segmentIndex'], 0)

    def test_repetition_dropdown_toggle_closes(self):
        """DropdownToggle closes an already-open repetition dropdown."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0}

        event = make_dropdown_toggle_event('repetition-0')
        model, _ = update(event, None, model, "hello world")

        self.assertIsNone(model.get('openDropdown'))

    def test_repetition_dropdown_toggle_switches(self):
        """Opening a different repetition dropdown closes the old one."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)(.*)(world)'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0}

        event = make_dropdown_toggle_event('repetition-2')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['openDropdown']['id'], 'repetition-2')
        self.assertEqual(model['openDropdown']['segmentIndex'], 2)


# =============================================================================
# Tests: Repetition Dropdown Select (simple options: 1, ?, *, +)
# =============================================================================

class TestRepetitionDropdownSelect(unittest.TestCase):
    """Tests for selecting simple repetition options from the dropdown.

    Note: Results are canonicalized, so groups may be stripped for non-adjacent-literal
    segments. Multi-segment regexes without adjacent literals lose their groups.
    """

    def test_select_star_on_fuzzy(self):
        """Select * on a fuzzy segment changes .+ to .* (canonical: no groups)."""
        model = init_model("hello world")
        model['search'] = r"r'hello.+world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}

        event = make_dropdown_select_event('repetition-1', '*')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['search'], r"r'hello.*world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_select_plus_on_fuzzy(self):
        """Select + on a fuzzy segment changes .* to .+ (canonical: no groups)."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}

        event = make_dropdown_select_event('repetition-1', '+')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['search'], r"r'hello.+world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_select_question_on_fuzzy(self):
        """Select ? on a fuzzy segment changes .* to .? (canonical: no groups)."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}

        event = make_dropdown_select_event('repetition-1', '?')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['search'], r"r'hello.?world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_select_1_removes_quantifier(self):
        """Select 1 on a fuzzy segment removes the quantifier (e.g., .* -> .)."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}

        event = make_dropdown_select_event('repetition-1', '1')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['search'], r"r'hello.world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_select_plus_on_literal(self):
        """Select + on a literal segment adds + quantifier, wrapping multi-char in (?:...)."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0}

        event = make_dropdown_select_event('repetition-0', '+')
        model, _ = update(event, None, model, "hello world")

        # (?:hello)+ gets a group because it contains (?:)
        self.assertEqual(model['search'], r"r'((?:hello)+).*world'")
        self.assertIsNone(model.get('openDropdown'))

    def test_repetition_select_saves_undo(self):
        """Changing repetition saves previous regex to undo history."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}

        event = make_dropdown_select_event('repetition-1', '+')
        model, _ = update(event, None, model, "hello world")

        self.assertIn(r"r'hello.*world'", model['undoHistory'])

    def test_repetition_select_wrong_id_ignored(self):
        """Selection ignored if dropdown ID doesn't match."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0}

        event = make_dropdown_select_event('repetition-1', '+')
        model, _ = update(event, None, model, "hello world")

        # Regex unchanged
        self.assertEqual(model['search'], r"r'hello.*'")
        # Dropdown still closes
        self.assertIsNone(model.get('openDropdown'))


# =============================================================================
# Tests: RepetitionInput (text field changes for {n} and {n,m})
# =============================================================================

class TestRepetitionInput(unittest.TestCase):
    """Tests for RepetitionInput events from {n} and {n,m} text fields.

    Note: Results are canonicalized. Single-segment fuzzy patterns lose their groups.
    """

    # NOTE: Repetition + slice-label dropdowns BUFFER user-typed values into
    # openDropdown state without touching model['search']. The new quantifier /
    # slice expression is committed only when the dropdown closes (via
    # DropdownToggle, MouseDown elsewhere, Enter, etc.). This prevents
    # transient invalid expressions from making the segment - and the dropdown
    # itself - disappear mid-edit. Escape closes WITHOUT committing.

    def test_exact_field_buffers_value_without_changing_regex(self):
        """Typing into {n} only buffers the value; the regex stays put."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        event = make_repetition_input_event('repetition-0', 'exact', '3')
        model, _ = update(event, None, model, "hello world")

        self.assertEqual(model['search'], r"r'.*'")  # unchanged
        self.assertEqual(model['openDropdown']['exactN'], '3')

    def test_exact_field_commits_on_close(self):
        """Closing the dropdown commits the buffered exact quantifier."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        # Buffer
        model, _ = update(make_repetition_input_event('repetition-0', 'exact', '3'),
                          None, model, "hello world")
        # Close via DropdownToggle on the same id
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")

        self.assertEqual(model['search'], r"r'.{3}'")
        self.assertIsNone(model.get('openDropdown'))

    def test_exact_field_empty_does_not_change_regex(self):
        """Empty {n} field never produces a quantifier even on close."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '3', 'rangeMin': '', 'rangeMax': ''}

        # User clears the field, then closes.
        model, _ = update(make_repetition_input_event('repetition-0', 'exact', ''),
                          None, model, "hello world")
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")

        self.assertEqual(model['search'], r"r'.*'")  # still unchanged

    def test_range_min_and_max_buffer_then_commit(self):
        """Typing min then max buffers both, commits {min,max} on close."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'min', '2'),
                          None, model, "hello world")
        self.assertEqual(model['openDropdown']['rangeMin'], '2')
        self.assertEqual(model['search'], r"r'.*'")  # not yet

        model, _ = update(make_repetition_input_event('repetition-0', 'max', '5'),
                          None, model, "hello world")
        self.assertEqual(model['openDropdown']['rangeMax'], '5')
        self.assertEqual(model['search'], r"r'.*'")  # still not yet

        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")
        self.assertEqual(model['search'], r"r'.{2,5}'")

    def test_range_min_only_commits_open_ended(self):
        """Buffering only min yields {n,} on close."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'min', '2'),
                          None, model, "hello world")
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")

        self.assertEqual(model['search'], r"r'.{2,}'")

    def test_range_max_only_does_not_change_regex(self):
        """Setting only max (no min) doesn't produce a valid quantifier even
        on close - rangeMax alone has no canonical regex form."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'max', '5'),
                          None, model, "hello world")
        self.assertEqual(model['openDropdown']['rangeMax'], '5')
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")
        self.assertEqual(model['search'], r"r'.*'")

    def test_repetition_undo_saved_on_commit_only(self):
        """Undo history is appended only when the dropdown closes (commit), not on each keystroke."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'exact', '3'),
                          None, model, "hello world")
        # No undo entry yet - regex hasn't changed.
        self.assertNotIn(r"r'.*'", model.get('undoHistory', []))

        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")
        # Now the original regex is in undo.
        self.assertIn(r"r'.*'", model['undoHistory'])

    def test_repetition_input_non_numeric_ignored(self):
        """Non-numeric values are buffered but never produce a quantifier on close."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'exact', 'abc'),
                          None, model, "hello world")
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")
        self.assertEqual(model['search'], r"r'.*'")

    def test_repetition_input_on_literal_multi_char(self):
        """Closing after typing on a multi-char literal wraps in (?:...) and keeps group."""
        model = init_model("hello world")
        model['search'] = r"r'hello'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'exact', '3'),
                          None, model, "hello world")
        model, _ = update(make_dropdown_toggle_event('repetition-0'),
                          None, model, "hello world")

        self.assertEqual(model['search'], r"r'((?:hello){3})'")

    def test_mousedown_elsewhere_commits_repetition_buffer(self):
        """Clicking on the string (which clears openDropdown) commits buffered values."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'exact', '3'),
                          None, model, "hello world")
        # Simulate a mousedown on a char to close the dropdown.
        ev = {
            'pythonEventStr': repr(MouseDown(2)),
            'eventJSON': {'altKey': False, 'shiftKey': False, 'ctrlKey': False,
                          'offsetY': 5, 'elementHeight': 20, 'buttons': 1},
        }
        model, _ = update(ev, ('x', 'x'), model, "hello world")
        self.assertEqual(model['search'], r"r'.{3}'")
        self.assertIsNone(model.get('openDropdown'))

    def test_escape_discards_repetition_buffer(self):
        """Escape closes the dropdown WITHOUT committing the buffered value."""
        model = init_model("hello world")
        model['search'] = r"r'.*'"
        model['openDropdown'] = {'id': 'repetition-0', 'segmentIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        model, _ = update(make_repetition_input_event('repetition-0', 'exact', '3'),
                          None, model, "hello world")
        # Escape via KeyDown
        ev = make_key_down_event('Escape')
        model, _ = update(ev, ('x', 'x'), model, "hello world")
        self.assertEqual(model['search'], r"r'.*'")  # unchanged
        self.assertIsNone(model.get('openDropdown'))


# =============================================================================
# Tests: Repetition Dropdown Rendering
# =============================================================================

class TestRepetitionDropdownRendering(unittest.TestCase):
    """Tests that repetition dropdowns render correctly in visualize output.

    Note: We use canonical regexes that actually produce highlights for the test value.
    For "hello world": hello.*world matches and produces 3 segments.
    For single segments, use regexes that match the test value.
    """

    def test_literal_segment_has_clickable_repetition(self):
        """Literal segment renders repetition count as a clickable dropdown trigger
        when the segment is hovered (segments are only "active" while hovered)."""
        model = init_model("helloworld")
        model['search'] = r"r'(hello)(world)'"
        model['hoverIdx'] = 2  # somewhere inside 'hello' (segment 0)

        html_output = visualize("helloworld", model, None, None)

        self.assertIn('repetition-0', html_output)

    def test_fuzzy_segment_has_clickable_repetition(self):
        """Fuzzy segment renders repetition count as a clickable dropdown trigger
        when the segment is hovered."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        # The middle fuzzy segment (.*) covers just the space at internal index 6.
        model['hoverIdx'] = 6

        html_output = visualize("hello world", model, None, None)

        self.assertIn('repetition-0-1', html_output)

    def test_repetition_dropdown_open_shows_options(self):
        """When repetition dropdown is open, options are rendered."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-0-1', 'segmentIndex': 1,
                                  'matchIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        html_output = visualize("hello world", model, None, None)

        # Should contain dropdown select options
        self.assertIn('DropdownSelect', html_output)

    def test_repetition_dropdown_has_text_input_fields(self):
        """When repetition dropdown is open, text input fields for {n} and {n,m} are present."""
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-0-1', 'segmentIndex': 1,
                                  'matchIndex': 0,
                                  'exactN': '', 'rangeMin': '', 'rangeMax': ''}

        html_output = visualize("hello world", model, None, None)

        # Should contain RepetitionInput events for text fields
        self.assertIn('RepetitionInput', html_output)


class TestRepetitionDropdownPrefillAndSelected(unittest.TestCase):
    """The repetition dropdown should reflect the segment's CURRENT quantifier:
    - The matching simple option ('1' / '?' / '*' / '+') is highlighted with .selected.
    - For {n} (n>=2), the exact-n input row is .selected and value-prefilled.
    - For {n,m}, {n,}, {0,m} (range forms), the range input row is .selected
      and the min/max inputs are value-prefilled.
    Prefilling happens when the dropdown OPENS via DropdownToggle - subsequent
    user typing into the inputs replaces the seeded values.
    """

    # --- Renderer: .selected on the matching simple option --------------------

    def _open_dropdown_for(self, value, search, segment_index=0, match_index=0):
        """Helper: open the repetition dropdown for the given segment via the
        same code path the UI takes (DropdownToggle), so prefill happens."""
        model = init_model(value)
        model['search'] = search
        ev = make_dropdown_toggle_event(f'repetition-{match_index}-{segment_index}')
        model, _ = update(ev, None, model, value)
        return model

    def _selected_simple_options(self, html_output):
        """Return the labels of options that have the .selected class."""
        return re.findall(r'class="snc-dropdown-option selected[^"]*"[^>]*>([^<]+)<', html_output)

    def test_quantifier_one_marks_one_option_selected(self):
        value = "helloworld"
        # /(hello)(world)/ -> two literal segments, both with quantifier '1' (no quantifier)
        model = self._open_dropdown_for(value, r"r'(hello)(world)'", segment_index=0)
        html_output = visualize(value, model, None, None)
        self.assertEqual(self._selected_simple_options(html_output), ['1'])

    def test_quantifier_star_marks_star_option_selected(self):
        value = "hello world"
        model = self._open_dropdown_for(value, r"r'hello.*world'", segment_index=1)
        html_output = visualize(value, model, None, None)
        self.assertEqual(self._selected_simple_options(html_output), ['*'])

    def test_quantifier_plus_marks_plus_option_selected(self):
        value = "hello world"
        model = self._open_dropdown_for(value, r"r'hello.+world'", segment_index=1)
        html_output = visualize(value, model, None, None)
        self.assertEqual(self._selected_simple_options(html_output), ['+'])

    def test_quantifier_question_marks_question_option_selected(self):
        value = "hello world"
        model = self._open_dropdown_for(value, r"r'hello.?world'", segment_index=1)
        html_output = visualize(value, model, None, None)
        self.assertEqual(self._selected_simple_options(html_output), ['?'])

    # --- Prefill: openDropdown init from current quantifier -------------------

    def test_open_dropdown_prefills_exact_n_for_brace_quantifier(self):
        """For /.{3}/, opening the repetition dropdown seeds exactN='3'."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{3}'", segment_index=0)
        od = model.get('openDropdown')
        self.assertIsNotNone(od)
        self.assertEqual(od.get('exactN'), '3')
        self.assertEqual(od.get('rangeMin'), '')
        self.assertEqual(od.get('rangeMax'), '')

    def test_open_dropdown_prefills_range_for_brace_range_quantifier(self):
        """For /.{2,5}/, opening seeds rangeMin='2', rangeMax='5'."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{2,5}'", segment_index=0)
        od = model.get('openDropdown')
        self.assertEqual(od.get('exactN'), '')
        self.assertEqual(od.get('rangeMin'), '2')
        self.assertEqual(od.get('rangeMax'), '5')

    def test_open_dropdown_prefills_open_ended_range_quantifier(self):
        """For /.{3,}/, opening seeds rangeMin='3', rangeMax=''."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{3,}'", segment_index=0)
        od = model.get('openDropdown')
        self.assertEqual(od.get('exactN'), '')
        self.assertEqual(od.get('rangeMin'), '3')
        self.assertEqual(od.get('rangeMax'), '')

    def test_open_dropdown_no_prefill_for_simple_quantifier(self):
        """For /.+/, all input fields stay empty (the '+' simple option is selected instead)."""
        value = "abc"
        model = self._open_dropdown_for(value, r"r'.+'", segment_index=0)
        od = model.get('openDropdown')
        self.assertEqual(od.get('exactN'), '')
        self.assertEqual(od.get('rangeMin'), '')
        self.assertEqual(od.get('rangeMax'), '')

    # --- Render: input rows show prefilled values + .selected -----------------

    def test_render_exact_n_row_prefilled_and_selected(self):
        """Exact-n row's input has the seeded value and is marked .selected."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{3}'", segment_index=0)
        html_output = visualize(value, model, None, None)
        # Look for a value="3" attribute on the exact-n input
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;exact&#x27;[^"]*"[^/]*value="3"')
        # And the row is .selected (regex spans the <input> tag inside it)
        self.assertRegex(
            html_output,
            r'class="snc-dropdown-option selected"[^>]*>\{.*?field=&#x27;exact&#x27;',
        )

    def test_render_range_row_prefilled_and_selected(self):
        """Range row inputs have seeded values and the row is marked .selected."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{2,5}'", segment_index=0)
        html_output = visualize(value, model, None, None)
        # Both min and max prefilled
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;min&#x27;[^"]*"[^/]*value="2"')
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;max&#x27;[^"]*"[^/]*value="5"')
        # The range row is .selected (regex spans the <input> tag inside it)
        self.assertRegex(
            html_output,
            r'class="snc-dropdown-option selected"[^>]*>\{.*?field=&#x27;min&#x27;',
        )

    def test_render_open_ended_range_only_min_prefilled(self):
        """For {3,}, min is '3' and max is empty."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{3,}'", segment_index=0)
        html_output = visualize(value, model, None, None)
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;min&#x27;[^"]*"[^/]*value="3"')
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;max&#x27;[^"]*"[^/]*value=""')

    def test_user_typed_value_overrides_prefill(self):
        """If the user has already typed into a field, the rendered value
        is the user's typed value, not the original prefill."""
        value = "abcdef"
        model = self._open_dropdown_for(value, r"r'.{3}'", segment_index=0)
        # Simulate user clearing the exact-n field after the prefill.
        model['openDropdown']['exactN'] = ''
        html_output = visualize(value, model, None, None)
        # The input should now be empty (not '3' from the prefill).
        self.assertRegex(html_output, r'snc-input="[^"]*field=&#x27;exact&#x27;[^"]*"[^/]*value=""')


# =============================================================================
# Tests: Hover Preview
# =============================================================================

class TestHoverPreview(unittest.TestCase):
    """Test hover preview shows a border indicating literal/fuzzy on mouse hover."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)

    # --- Model state tests ---

    def test_mousemove_no_buttons_with_literal_tool_sets_hover(self):
        """MouseMove with buttons=0 and the 'literal' tool active sets hoverIdx."""
        # The default tool is 'literal'.
        event = make_mouse_move_event(5, buttons=0, top_half=True)
        model, _ = update(event, self.var_and_exp, self.model, self.value)

        self.assertEqual(model['hoverIdx'], _legacy_internal_index(5))

    def test_mousemove_no_buttons_with_fuzzy_tool_sets_hover(self):
        """MouseMove with buttons=0 and the 'fuzzy' tool active sets hoverIdx."""
        self.model['tool'] = 'fuzzy'
        event = make_mouse_move_event(5, buttons=0, top_half=False)
        model, _ = update(event, self.var_and_exp, self.model, self.value)

        self.assertEqual(model['hoverIdx'], _legacy_internal_index(5))

    def test_mousedown_clears_hover_state(self):
        """MouseDown clears hoverIdx."""
        # First set hover state
        event = make_mouse_move_event(5, buttons=0, top_half=True)
        model, _ = update(event, self.var_and_exp, self.model, self.value)
        self.assertEqual(model['hoverIdx'], _legacy_internal_index(5))

        # MouseDown should clear it
        event = make_mouse_down_event(5, top_half=True)
        model, _ = update(event, self.var_and_exp, model, self.value)

        self.assertIsNone(model['hoverIdx'])

    def test_hover_not_set_while_dragging(self):
        """MouseMove with buttons=1 (dragging) does not set hover state."""
        # Start a drag
        event = make_mouse_down_event(3, top_half=True)
        model, _ = update(event, self.var_and_exp, self.model, self.value)

        # Move with button held - should NOT set hover
        event = make_mouse_move_event(5, buttons=1, top_half=True)
        model, _ = update(event, self.var_and_exp, model, self.value)

        self.assertIsNone(model.get('hoverIdx'))

    # --- Rendering tests ---

    def test_hover_emits_no_hover_class_and_keeps_the_char_grouped(self):
        """hoverIdx drives which match's labels show; it no longer emits a
        'hover' char class (no CSS rule ever styled it) nor breaks the hovered
        plain char out of its text group just to carry that class."""
        model = init_model(self.value)
        model['hoverIdx'] = 4  # 'l' in "hello" (new internal index)

        html_output = visualize(self.value, model, None, None)

        self.assertNotIn('class="chr hover"', html_output)
        # Without the class there is no reason to individually render the
        # hovered plain char: it stays inside its grouped text span.
        self.assertNotIn('snc-idx="4"', html_output)

    def test_hover_does_not_affect_highlighted_char(self):
        """A char in a selected segment renders its highlight classes only."""
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        # Hover on index 3 which is inside the 'hello' literal segment (new index space).
        model['hoverIdx'] = 3

        html_output = visualize(self.value, model, None, None)

        import re as _re
        m = _re.search(r'<span class="([^"]+)" snc-idx="1"', html_output)
        self.assertIsNotNone(m)
        # Already highlighted; should not also get the standalone hover class.
        self.assertNotIn('hover', m.group(1).split())
        self.assertIn('highlight', m.group(1).split())


class TestMoveListenersAndMouseUpNotify(unittest.TestCase):
    """Every idle mouse move costs a full program run, so the markup only asks
    for moves where they matter: match chars carry an explicit snc-mouse-move
    (hover reveals that occurrence's labels); everything else tracks moves only
    while a drag is in progress. A drag's mouseup can land outside the widget,
    so while one is in progress the container carries snc-notify-mouse-is-up,
    which the front-end fires (at most once per rendered HTML) on a mouseup or
    a no-buttons move, letting the stuck drag finalize."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_idle_only_match_chars_listen_for_moves(self):
        model = init_model(self.value)
        model['search'] = r"r'world'"

        out = visualize(self.value, model, None, None)

        # Boundary chars w and d carry explicit move listeners; the grouped
        # interior asks for hover moves via snc-hover-moves instead.
        self.assertEqual(out.count('snc-mouse-move='), 2)
        self.assertEqual(out.count('snc-hover-moves'), 1)
        self.assertNotIn('snc-notify-mouse-is-up', out)

    def test_drag_in_progress_renders_the_notify_attr(self):
        model, _ = update(make_mouse_down_event(5, top_half=True),
                          self.var_and_exp, self.model, self.value)
        self.assertTrue(model['dragging'])

        out = visualize(self.value, model, None, None)

        self.assertIn('snc-notify-mouse-is-up="NotifyMouseIsUp()"', out)

    def test_handle_drag_renders_the_notify_attr(self):
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)

        out = visualize(self.value, model, None, None)

        self.assertIn('snc-notify-mouse-is-up="NotifyMouseIsUp()"', out)

    def test_notify_mouse_is_up_finalizes_a_stuck_drag(self):
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)

        ev = {'pythonEventStr': repr(NotifyMouseIsUp()), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, self.var_and_exp, model, self.value)

        self.assertFalse(model['dragging'])
        self.assertEqual(model['search'], r"r'hello'")

    def test_notify_mouse_is_up_finalizes_a_stuck_handle_drag(self):
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(7),
                          self.var_and_exp, model, self.value)

        ev = {'pythonEventStr': repr(NotifyMouseIsUp()), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, self.var_and_exp, model, self.value)

        self.assertIsNone(model.get('handleDrag'))
        self.assertEqual(model['search'], r"r'(hello\ )'")

    def test_notify_mouse_is_up_without_a_drag_is_a_no_op(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"

        ev = {'pythonEventStr': repr(NotifyMouseIsUp()), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], r"r'hello'")
        self.assertFalse(model.get('dragging'))
        self.assertIsNone(model.get('handleDrag'))


class TestHandlesOnlyOnActiveSegment(unittest.TestCase):
    """Interactive segments render resize handles only while active (hovered,
    mid-drag, or with their dropdown open) -- the same gate the labels use.
    Rendered unconditionally they were dead weight: a dense pattern has
    thousands of matches, and two handle spans per match dwarfed the string
    itself. Slices keep theirs unconditionally -- there is only one."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    def test_idle_segments_render_no_handles(self):
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        out = visualize(self.value, model, None, None)
        self.assertNotIn('chr-resize-handle', out)

    def test_hovered_segment_renders_its_handles(self):
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model['hoverIdx'] = 3
        out = visualize(self.value, model, None, None)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", out)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", out)

    def test_only_the_hovered_match_offers_handles(self):
        value = 'ab ab'
        model = init_model(value)
        model['search'] = r"r'(ab)'"
        model['hoverIdx'] = 1  # inside the first 'ab'
        out = visualize(value, model, None, None)
        self.assertEqual(out.count('chr-resize-handle left'), 1)
        self.assertEqual(out.count('chr-resize-handle right'), 1)

    def test_slice_handles_stay_without_hover(self):
        model = init_model(self.value)
        model['search'] = '2:5'
        out = visualize(self.value, model, None, None)
        self.assertIn('chr-resize-handle left', out)
        self.assertIn('chr-resize-handle right', out)

    def test_handle_drag_keeps_the_dragged_segments_handles(self):
        model = init_model(self.value)
        model['search'] = r"r'(hello)'"
        model, _ = update(make_handle_mouse_down_event(0, 'right'),
                          self.var_and_exp, model, self.value)
        out = visualize(self.value, model, None, None)
        self.assertIn('chr-resize-handle', out)


class TestSeamHandleRendering(unittest.TestCase):
    """The boundary between two span-adjacent segments of the same match gets
    ONE seam handle (owned by the right segment) instead of two stacked,
    single-segment handles that each move only their own side."""

    var_and_exp = ('x', 'x')

    def rendered(self, value, search, hover=None):
        model = init_model(value)
        model['search'] = search
        if hover is not None:
            model['hoverIdx'] = hover
        return visualize(value, model, None, None)

    def test_literal_literal_seam_renders_one_seam_handle(self):
        # "hello world": (hello) is internal 1-6, (\ world) is 6-12.
        out = self.rendered("hello world", r"r'(hello)(\ world)'", hover=3)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;seam&#x27;, match_index=0)", out)
        self.assertEqual(out.count('chr-resize-handle seam'), 1)

    def test_no_plain_handles_at_the_seam(self):
        # Hovering the left segment: its left (open) edge keeps a handle, but
        # its right edge is the seam.
        out = self.rendered("hello world", r"r'(hello)(\ world)'", hover=3)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", out)
        self.assertNotIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", out)

        # Hovering the right segment: no plain left handle either.
        out = self.rendered("hello world", r"r'(hello)(\ world)'", hover=8)
        self.assertNotIn("HandleMouseDown(segment_index=1, side=&#x27;left&#x27;, match_index=0)", out)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;right&#x27;, match_index=0)", out)

    def test_seam_active_from_either_neighbor(self):
        for hover in (3, 8):
            out = self.rendered("hello world", r"r'(hello)(\ world)'", hover=hover)
            self.assertIn('chr-resize-handle seam', out,
                          f'seam handle missing with hover at {hover}')

    def test_literal_fuzzy_seam(self):
        # r'hello\s*': the fuzzy's left edge abuts (hello); its right edge is
        # open, so it keeps a plain right handle when active.
        out = self.rendered("hello world", r"r'hello\s*'", hover=3)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;seam&#x27;, match_index=0)", out)

        out = self.rendered("hello world", r"r'hello\s*'", hover=6)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;right&#x27;, match_index=0)", out)

    def test_no_seam_between_abutting_matches(self):
        # 'abab': the two (ab) matches touch at internal 3, but a seam only
        # exists inside one match.
        out = self.rendered('abab', r"r'(ab)'", hover=1)
        self.assertNotIn('chr-resize-handle seam', out)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", out)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", out)

    def test_seam_only_on_the_active_match(self):
        # 'a b a b': two matches of (a)(\ b); only the hovered one shows its seam.
        out = self.rendered('a b a b', r"r'(a)(\ b)'", hover=1)
        self.assertEqual(out.count('chr-resize-handle seam'), 1)
        self.assertIn("HandleMouseDown(segment_index=1, side=&#x27;seam&#x27;, match_index=0)", out)
        self.assertNotIn("side=&#x27;seam&#x27;, match_index=1", out)

    def test_single_segment_outer_handles_unchanged(self):
        out = self.rendered("hello world", r"r'(hello)'", hover=3)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", out)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", out)
        self.assertNotIn('chr-resize-handle seam', out)

    def test_idle_renders_no_handles(self):
        out = self.rendered("hello world", r"r'(hello)(\ world)'")
        self.assertNotIn('chr-resize-handle', out)

    def test_slice_handles_untouched(self):
        out = self.rendered("hello world", '2:5')
        self.assertIn('chr-resize-handle left', out)
        self.assertIn('chr-resize-handle right', out)
        self.assertNotIn('chr-resize-handle seam', out)


class TestSeamDragUpdate(unittest.TestCase):
    """Dragging a seam handle moves the boundary: the character under the
    cursor becomes the first character of the right segment, so one side
    grows by exactly what the other gives up."""

    var_and_exp = ('x', 'x')

    def start_drag(self, value, search, segment_index, match_index=0):
        model = init_model(value)
        model['search'] = search
        model, _ = update(make_handle_mouse_down_event(segment_index, 'seam',
                                                       match_index=match_index),
                          self.var_and_exp, model, value)
        return model

    def drag_seam(self, value, search, segment_index, to_idx, match_index=0):
        model = self.start_drag(value, search, segment_index, match_index)
        model, _ = update(make_mouse_up_event(to_idx, legacy_index=False),
                          self.var_and_exp, model, value)
        return model

    def test_literal_literal_drag_right(self):
        model = self.drag_seam('hello world', r"r'(hello)(\ world)'", 1, 8)
        self.assertEqual(model['search'], r"r'(hello\ w)(orld)'")

    def test_literal_literal_drag_left(self):
        model = self.drag_seam('hello world', r"r'(hello)(\ world)'", 1, 3)
        self.assertEqual(model['search'], r"r'(he)(llo\ world)'")

    def test_clamps_so_each_side_keeps_a_char(self):
        model = self.drag_seam('hello world', r"r'(hello)(\ world)'", 1, 0)
        self.assertEqual(model['search'], r"r'(h)(ello\ world)'")

        model = self.drag_seam('hello world', r"r'(hello)(\ world)'", 1, 20)
        self.assertEqual(model['search'], r"r'(hello\ worl)(d)'")

    def test_literal_grows_into_fuzzy(self):
        # 'a  b' with r'a\s*b': the literal 'a' absorbs a space; the fuzzy is
        # re-synthesized over its remaining span.
        model = self.drag_seam('a  b', r"r'a\s*b'", 1, 3)
        self.assertEqual(model['search'], r"r'a\ \s*b'")

    def test_fuzzy_yields_to_literal(self):
        # Drag the \s*|b seam left: 'b' absorbs a space; the shrunk fuzzy is
        # lazified since \s* could now swallow the '\ ' that follows it.
        model = self.drag_seam('a  b', r"r'a\s*b'", 2, 3)
        self.assertEqual(model['search'], r"r'a\s*?\ b'")

    def test_counted_fuzzy_is_resynthesized_not_adjusted(self):
        # 'ABBC' with r'A[A-Z]{2}C': shrinking the {2} fuzzy by one re-runs
        # inference over the smaller span rather than decrementing the count.
        model = self.drag_seam('ABBC', r"r'A[A-Z]{2}C'", 2, 3)
        self.assertEqual(model['search'], r"r'A[A-Z]*?BC'")

    def test_seam_on_later_match_uses_that_matchs_spans(self):
        # 'a b a b' with r'(a)(\ b)': the second match spans internal 5-8.
        model = self.drag_seam('a b a b', r"r'(a)(\ b)'", 1, 7, match_index=1)
        self.assertEqual(model['search'], r"r'(a\ )(b)'")

    def test_mid_drag_leaves_search_untouched(self):
        model = self.start_drag('hello world', r"r'(hello)(\ world)'", 1)
        model, _ = update(make_mouse_move_event(8, legacy_index=False),
                          self.var_and_exp, model, 'hello world')
        self.assertEqual(model['search'], r"r'(hello)(\ world)'")
        self.assertEqual(model['handleDrag']['cursorIdx'], 8)

    def test_notify_mouse_is_up_finalizes(self):
        model = self.start_drag('hello world', r"r'(hello)(\ world)'", 1)
        model, _ = update(make_mouse_move_event(8, legacy_index=False),
                          self.var_and_exp, model, 'hello world')
        model, _ = update({'pythonEventStr': repr(NotifyMouseIsUp()), 'eventJSON': {}},
                          self.var_and_exp, model, 'hello world')
        self.assertEqual(model['search'], r"r'(hello\ w)(orld)'")
        self.assertIsNone(model['handleDrag'])

    def test_undo_restores_pre_drag_regex(self):
        model = self.drag_seam('hello world', r"r'(hello)(\ world)'", 1, 8)
        self.assertEqual(model['undoHistory'][-1], r"r'(hello)(\ world)'")

        model, _ = update(make_key_down_event('z', meta_key=True),
                          self.var_and_exp, model, 'hello world')
        self.assertEqual(model['search'], r"r'(hello)(\ world)'")


class TestMatchInteriorGrouping(unittest.TestCase):
    """Interior chars of a segment ride in one grouped span (like plain text)
    carrying the segment's highlight classes; only the boundary chars stay
    individual, since they hold the rounding, labels, and handles. The
    front-end derives exact indices from snc-idx-start, and snc-hover-moves
    marks interactive interiors as wanting idle hover moves (hovering a match
    is how its labels appear)."""

    def test_interior_chars_share_one_span(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'world'"
        out = visualize(value, model, None, None)

        m = re.search(r'<span class="([^"]*)" snc-idx-start="8" snc-hover-moves>orl</span>', out)
        self.assertIsNotNone(m, "interior 'orl' should be one grouped span")
        classes = m.group(1).split()
        self.assertIn('chr', classes)
        self.assertIn('highlight', classes)
        self.assertIn('literal', classes)
        # Boundary chars keep their own spans (rounding, labels, handles).
        self.assertIn('snc-idx="7"', out)
        self.assertIn('snc-idx="11"', out)
        for interior in (8, 9, 10):
            self.assertNotIn(f'snc-idx="{interior}"', out)

    def test_short_matches_have_no_interior_group(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'lo'"
        out = visualize(value, model, None, None)
        # [4,6): both chars are boundaries; nothing to group.
        self.assertIn('snc-idx="4"', out)
        self.assertIn('snc-idx="5"', out)

    def test_fuzzy_interior_groups_with_fuzzy_classes(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'(h)(.*)(d)'"
        out = visualize(value, model, None, None)

        m = re.search(r'<span class="([^"]*)" snc-idx-start="3" snc-hover-moves>llo wor</span>', out)
        self.assertIsNotNone(m, "fuzzy interior should be one grouped span")
        self.assertIn('fuzzy', m.group(1).split())

    def test_pick_regions_group_and_stay_hover_silent(self):
        """Pick-mode prefix/suffix regions span the whole string; per-char
        spans there made switching tools on a big string take seconds. The
        interiors group like any segment, carrying the region's click target
        and drag expression ONCE -- and no char asks for hover moves, since
        pick mode has no hover-driven UI (CSS :hover does the brightening)."""
        value = "hello world!"
        model = init_model(value)
        model['search'] = r"r'world'"
        model['tool'] = 'pick'
        out = visualize(value, model, None, None, var_and_exp=('x', 'x'))

        # Prefix region [1,7): interior 'ello' (2-5) is one grouped span with
        # the region's listeners; boundary chars keep individual spans.
        m = re.search(
            r'<span class="chr highlight segment-region" '
            r'snc-idx-start="2" snc-mouse-down="SegmentToggle\([^"]*"[^>]*>ello</span>',
            out)
        self.assertIsNotNone(m, "prefix interior should be one grouped span with SegmentToggle")
        # Match region [7,12): interior 'orl' (8-10) grouped as segment-group.
        self.assertIn('segment-group" snc-idx-start="8"', out)
        for interior in (2, 3, 4, 5, 8, 9, 10):
            self.assertNotIn(f'snc-idx="{interior}"', out)
        # Nothing in pick mode listens for moves.
        self.assertNotIn('snc-mouse-move=', out)
        self.assertNotIn('snc-hover-moves', out)

    def test_slice_interior_groups_without_hover_moves(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = '2:9'
        out = visualize(value, model, None, None)

        # Slice [3,10): interior 4-8. No hover-driven UI for slices, so the
        # group does not ask for idle moves.
        m = re.search(r'<span class="([^"]*)" snc-idx-start="4">lo wo</span>', out)
        self.assertIsNotNone(m, "slice interior should be one grouped span")
        self.assertIn('slice', m.group(1).split())


class TestRegexAnchorClass(unittest.TestCase):
    """In effective index mode the visualizer should hide regex anchors (^/$)
    but keep escape-sequence displays (\\n, \\t) visible, since those represent
    real characters in the string. The Python side tags only the anchor
    chars with `regex-anchor`; the CSS targets only that class for the
    index-mode hide rule, so escape displays remain visible.
    """

    def _classes_at(self, html_output: str, mouse_index: int):
        import re as _re
        m = _re.search(
            rf'<span class="([^"]+)" snc-idx="{mouse_index}"',
            html_output,
        )
        self.assertIsNotNone(m, f"Should find chr at index {mouse_index}")
        return m.group(1).split()

    def test_string_start_caret_has_is_regex_anchor(self):
        """The leading ^ at internal index 0 gets `regex-anchor`."""
        value = "hi"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 0)
        self.assertIn('special', classes)
        self.assertIn('regex-anchor', classes)

    def test_string_end_dollar_has_is_regex_anchor(self):
        """The trailing $ gets `regex-anchor`."""
        value = "hi"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        end_index = compute_internal_length(value) - 1
        classes = self._classes_at(html_output, end_index)
        self.assertIn('special', classes)
        self.assertIn('regex-anchor', classes)

    def test_synth_dollar_before_newline_has_is_regex_anchor(self):
        """The synthesized $ rendered before a \\n display gets `regex-anchor`."""
        value = "a\nb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 2)
        self.assertIn('special', classes)
        self.assertIn('regex-anchor', classes)

    def test_synth_caret_after_newline_has_is_regex_anchor(self):
        """The synthesized ^ rendered after a \\n display gets `regex-anchor`."""
        value = "a\nb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 4)
        self.assertIn('special', classes)
        self.assertIn('regex-anchor', classes)

    def test_newline_display_is_special_but_not_anchor(self):
        """The \\n escape display is `special` but NOT `regex-anchor`."""
        value = "a\nb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 3)
        self.assertIn('special', classes)
        self.assertNotIn('regex-anchor', classes)

    def test_tab_display_is_special_but_not_anchor(self):
        """The \\t escape display is `special` but NOT `regex-anchor`."""
        value = "a\tb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 2)
        self.assertIn('special', classes)
        self.assertNotIn('regex-anchor', classes)

    def test_carriage_return_display_is_special_but_not_anchor(self):
        """The \\r escape display is `special` but NOT `regex-anchor`."""
        value = "a\rb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        classes = self._classes_at(html_output, 2)
        self.assertIn('special', classes)
        self.assertNotIn('regex-anchor', classes)

    def test_carriage_return_renders_as_escape_not_raw(self):
        """A raw CR must never reach the HTML (under white-space:pre it is a
        segment break, splitting the line); it displays as the \\r escape."""
        value = "a\rb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        self.assertNotIn('\r', html_output)
        self.assertIn('\\r', html_output)

    def test_char_span_is_a_single_span(self):
        """Each char is ONE span carrying both the visual classes and the
        snc-idx listener - no wrapper container element."""
        value = "hi"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        self.assertNotIn('chr-container', html_output)

    def test_caret_anchors_carry_is_anchor_start(self):
        """Both string-start ^ and synthesized ^ after \\n carry anchor-start
        (not anchor-end). The CSS hides these (but keeps their glyph slot)
        in index mode so the string doesn't shift left."""
        value = "a\nb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        for idx in (0, 4):  # ^ at string start, synth ^ after \n
            classes = self._classes_at(html_output, idx)
            self.assertIn('anchor-start', classes)
            self.assertNotIn('anchor-end', classes)

    def test_dollar_anchors_carry_is_anchor_end(self):
        """Both synthesized $ before \\n and string-end $ carry anchor-end
        (not anchor-start). The CSS collapses these (display:none) in index
        mode so \\n displays sit flush with the end of their line."""
        value = "a\nb"
        model = init_model(value)
        html_output = visualize(value, model, None, None)
        for idx in (2, 6):  # synth $ before \n, $ at string end
            classes = self._classes_at(html_output, idx)
            self.assertIn('anchor-end', classes)
            self.assertNotIn('anchor-start', classes)


# =============================================================================
# Run Tests
# =============================================================================

class TestGetFields(unittest.TestCase):
    """Test get_fields on string_visualizer."""

    def test_returns_none(self):
        from string_visualizer import get_fields
        self.assertIsNone(get_fields("hello"))

    def test_returns_none_for_empty_string(self):
        from string_visualizer import get_fields
        self.assertIsNone(get_fields(""))


class TestSmallParameter(unittest.TestCase):
    """Test that small=True hides the search box."""

    def test_visualize_accepts_small_parameter(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertIn('hello', output)

    def test_search_box_present_when_not_small(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=False)
        self.assertIn('Search', output)
        self.assertIn('<input', output)

    def test_search_box_hidden_when_small(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('<input', output)
        self.assertNotIn('Search', output)

    def test_search_box_present_by_default(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('Search', output)

    def test_small_self_wraps_with_var_and_exp(self):
        """The preview has nothing of its own to hover -- no per-character
        anchors, no chips -- so the whole of it is the handle for the string,
        the way a generic visualizer's whole output is."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True,
                           var_and_exp=(None, 'words[0]'))
        self.assertTrue(output.startswith(f'<span {exp_attr("words[0]")} '
                                          'draggable="true" '
                                          'class="py-exp-grab">'))
        self.assertTrue(output.endswith('</span>'))

    def test_small_self_wrap_is_the_only_handle(self):
        """One handle over the preview, not one per piece of it."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True,
                           var_and_exp=(None, 'words[0]'))
        self.assertEqual(output.count('py-exp-grab'), 1)
        self.assertEqual(output.count('snc-py-exps'), 1)

    def test_small_no_self_wrap_without_var_and_exp(self):
        """Small mode without an expression renders bare (no drag wrapper)."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('py-exp-grab', output)

    def test_small_expand_toggle_stays_out_of_the_drag_zone(self):
        """The one control the preview still offers is a click target, so it
        opts out of the handle wrapped around it (see render_expand_toggle)."""
        model = init_model("a\nb\nc\nd\ne")
        output = visualize("a\nb\nc\nd\ne", model, None, None, small=True,
                           var_and_exp=(None, 'words[0]'))
        self.assertIn('class="py-exp-grab"', output)
        self.assertIn('expand-toggle', output)
        self.assertIn('draggable="false"', output)

    def test_full_mode_not_draggable_even_with_var_and_exp(self):
        """Full (interactive) mode is never wrapped as a drag handle: the
        characters carry their own handles, and one over the whole area would
        claim every hover inside it."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=False,
                           var_and_exp=(None, 'words[0]'))
        self.assertNotIn('class="py-exp-grab"', output)

    def test_tool_toolbar_hidden_when_small_short_string(self):
        """The compact tool toolbar (literal/fuzzy/index/pick) should not render when small=True."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('tool-toolbar', output)
        self.assertNotIn('tool-dropdown-trigger', output)

    def test_tool_toolbar_hidden_when_small_tall_string(self):
        """The vertical tool toolbar (used for 4+ line strings) should not render when small=True."""
        model = init_model("a\nb\nc\nd\ne")
        output = visualize("a\nb\nc\nd\ne", model, None, None, small=True)
        self.assertNotIn('tool-toolbar', output)

    def test_tool_toolbar_present_when_not_small(self):
        """The tool toolbar should render when small=False (default)."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=False)
        self.assertIn('tool-toolbar', output)

    def test_small_mode_omits_regex_anchors(self):
        """Small mode's fast path doesn't generate the ^/$ regex anchors."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('regex-anchor', output)
        self.assertNotIn('special', output)

    def test_small_mode_omits_highlights(self):
        """Small mode skips selection/highlight computation entirely."""
        model = init_model("hello")
        model['search'] = r"r'l'"
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('highlight', output)
        self.assertNotIn('chr', output)

    def test_small_mode_prints_raw_string(self):
        """Small mode prints the string as one plain text node (wrapped in quotes),
        with no per-character elements and no index wrapper around it."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertIn('<div>&#x27;hello&#x27;</div>', output)

    def test_small_mode_escapes_html(self):
        """Small mode still HTML-escapes the string content."""
        model = init_model("a<b>&'\"")
        output = visualize("a<b>&'\"", model, None, None, small=True)
        self.assertIn('a&lt;b&gt;&amp;&#x27;&quot;', output)

    def test_small_mode_preserves_newlines_literally(self):
        """Small mode renders \\n as a literal newline (white-space:pre handles it),
        not as an escape display with anchors. Newlines after the first get a
        leading space for vertical alignment under the opening quote."""
        model = init_model("a\nb")
        output = visualize("a\nb", model, None, None, small=True)
        self.assertIn('a\n b', output)
        self.assertNotIn('\\n', output)


class TestSmallModeQuotes(unittest.TestCase):
    """Small (non-focused) mode wraps the string in leading/trailing ' quotes."""

    def test_small_mode_shows_leading_and_trailing_quote(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertIn("&#x27;hello&#x27;", output)

    def test_small_mode_empty_string_shows_quotes(self):
        model = init_model("")
        output = visualize("", model, None, None, small=True)
        self.assertIn("&#x27;&#x27;", output)

    def test_full_mode_does_not_show_wrapping_quotes(self):
        """Focused (full) mode must not add the leading/trailing ' quotes."""
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=False)
        self.assertNotIn("&#x27;hello&#x27;", output)

    def test_small_mode_multiline_indents_subsequent_lines(self):
        """Each newline after the first gets a leading space so lines align
        vertically under the first line's content (which is shifted right by
        the opening quote)."""
        model = init_model("a\nb\nc")
        output = visualize("a\nb\nc", model, None, None, small=True)
        self.assertIn("&#x27;a\n b\n c&#x27;", output)

    def test_small_mode_single_line_no_extra_space(self):
        """A single-line string has no newline, so no leading spaces are added."""
        model = init_model("abc")
        output = visualize("abc", model, None, None, small=True)
        self.assertIn("&#x27;abc&#x27;", output)
        self.assertNotIn("&#x27; abc", output)


class TestSmallModeIsNotCharAddressable(unittest.TestCase):
    """The non-focused preview carries no per-character addressing at all.

    snc-idx-start is the front-end's hook for turning a caret offset into an
    internal index, and the preview cannot honour it: a newline prints one
    character but spends three internal indices ($, the \\n display, ^), so
    every character after one would name the wrong index. Nothing needs those
    indices either -- a non-focused child only ever acts on the mousedown that
    pins its focus, and that ignores the payload -- so the preview drops the
    addressing and keeps one container-level mousedown."""

    def test_no_text_start_index_single_line(self):
        model = init_model("abc")
        self.assertNotIn('snc-idx-start', visualize("abc", model, None, None, small=True))

    def test_no_text_start_index_multiline(self):
        model = init_model("ab\ncd\nef")
        self.assertNotIn('snc-idx-start',
                         visualize("ab\ncd\nef", model, None, None, small=True))

    def test_no_per_character_mouse_listeners(self):
        """The whole point of the preview is to stay cheap: one text node, not
        one element per character."""
        output = visualize("abcdef", init_model("abcdef"), None, None, small=True)
        self.assertNotIn('snc-idx=', output)

    def test_multiline_preview_is_still_one_text_node(self):
        """Newlines must not split the string into a span per line."""
        output = visualize("a\nb\nc\nd", init_model("a\nb\nc\nd"), None, None, small=True)
        self.assertEqual(output.count('<span'), 0)

    def test_container_carries_a_mousedown_so_it_can_be_focused(self):
        """A nested preview is focused by clicking it (route_child_event pins
        focus on the first mousedown), so something has to dispatch one."""
        output = visualize("abc", init_model("abc"), None, None, small=True)
        self.assertIn('snc-mouse-down=', output)

    def test_focused_render_still_groups_text(self):
        """Only the preview drops the addressing; the focused render batches
        plain characters into indexed groups exactly as before."""
        output = visualize("abcdef", init_model("abcdef"), None, None, small=False)
        self.assertIn('snc-idx-start', output)


class TestTextGrouping(unittest.TestCase):
    """Test that consecutive plain characters are grouped into a single span
    using snc-idx-start instead of individual snc-idx spans."""

    def test_plain_string_uses_grouped_span(self):
        """For 'hello' with no highlights/hover, the 5 plain chars should be
        in a single snc-idx-start span, not 5 individual snc-idx spans."""
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('snc-idx-start="1"', output)
        import re as _re
        individual_plain = _re.findall(r'snc-idx="[1-5]"', output)
        self.assertEqual(len(individual_plain), 0,
                         "Plain chars should not have individual snc-idx spans")

    def test_grouped_span_contains_all_plain_chars(self):
        """The grouped span's text content should contain the full plain text."""
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('snc-idx-start="1"', output)
        import re as _re
        match = _re.search(r'<span [^>]*snc-idx-start="1"[^>]*>([^<]+)</span>', output)
        self.assertIsNotNone(match, "Should find grouped span starting at index 1")
        self.assertEqual(match.group(1), "hello")

    def test_special_chars_always_individual_spans(self):
        """Prefix/suffix markers and \\n/\\t always get individual snc-idx spans."""
        model = init_model("a\nb")
        output = visualize("a\nb", model, None, None)
        # Prefix anchor (^) at internal index 0.
        self.assertIn('snc-idx="0"', output)
        # Newline expands to multiple individual char spans.
        for special_idx in [2, 3, 4]:
            self.assertIn(f'snc-idx="{special_idx}"', output,
                          f"Newline expansion index {special_idx} should be individual span")

    def test_group_flushes_at_newline(self):
        """'ab\\ncd' should produce groups for 'ab' and 'cd', with \\n chars individual."""
        model = init_model("ab\ncd")
        output = visualize("ab\ncd", model, None, None)
        self.assertIn('snc-idx-start="1"', output)
        self.assertIn('snc-idx-start="6"', output)

    def test_group_flushes_at_tab(self):
        """'ab\\tcd' should produce groups for 'ab' and 'cd', with \\t individual."""
        model = init_model("ab\tcd")
        output = visualize("ab\tcd", model, None, None)
        self.assertIn('snc-idx-start="1"', output)
        self.assertIn('snc-idx-start="4"', output)
        self.assertIn('snc-idx="3"', output)

    def test_group_flushes_at_carriage_return(self):
        """'ab\\rcd' should produce groups for 'ab' and 'cd', with \\r individual."""
        model = init_model("ab\rcd")
        output = visualize("ab\rcd", model, None, None)
        self.assertIn('snc-idx-start="1"', output)
        self.assertIn('snc-idx-start="4"', output)
        self.assertIn('snc-idx="3"', output)

    def test_hover_does_not_break_group(self):
        """hoverIdx used to pull the hovered plain char out of its text group
        to carry a 'hover' class no CSS rule styled. It renders nothing now,
        so the group stays intact."""
        model = init_model("hello")
        model['hoverIdx'] = 4
        output = visualize("hello", model, None, None)
        self.assertNotIn('snc-idx="4"', output)
        self.assertIn('snc-idx-start="1"', output)

    def test_highlight_boundaries_break_group(self):
        """Segment boundary chars get individual spans (rounding, labels,
        handles); interior match chars group like plain text, with the
        segment's classes (TestMatchInteriorGrouping)."""
        model = init_model("hello world")
        model['search'] = r"r'(hello)'"
        output = visualize("hello world", model, None, None)
        for idx in (1, 5):
            self.assertIn(f'snc-idx="{idx}"', output,
                          f"Boundary char at index {idx} should be individual span")
        self.assertIn('snc-idx-start="2"', output)  # interior 'ell'
        self.assertIn('snc-idx-start="6"', output)  # plain ' world'

    def test_start_index_correctness_across_groups(self):
        """With 'ab\\tcd', verify snc-idx-start values match internal indexing."""
        model = init_model("ab\tcd")
        output = visualize("ab\tcd", model, None, None)
        import re as _re
        starts = _re.findall(r'snc-idx-start="(\d+)"', output)
        self.assertIn('1', starts, "First group should start at index 1")
        self.assertIn('4', starts, "Second group should start at index 4")

    def test_html_escape_in_grouped_span(self):
        """Characters like < and & are HTML-escaped inside grouped spans."""
        model = init_model("a<b")
        output = visualize("a<b", model, None, None)
        import re as _re
        match = _re.search(r'<span [^>]*snc-idx-start="1"[^>]*>(.*?)</span>', output)
        self.assertIsNotNone(match)
        self.assertIn('&lt;', match.group(1))

    def test_single_plain_char_still_grouped(self):
        """Even a single plain char between specials should use grouped span."""
        model = init_model("\na\n")
        output = visualize("\na\n", model, None, None)
        self.assertIn('snc-idx-start="4"', output)

    def test_empty_string_no_grouped_spans(self):
        """An empty string should have no snc-idx-start spans."""
        model = init_model("")
        output = visualize("", model, None, None)
        self.assertNotIn('snc-idx-start', output)

    def test_grouped_span_has_no_class(self):
        """Grouped text spans carry only snc-idx-start - no CSS class (nothing
        styles them, so the class attribute would just bloat the HTML)."""
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertNotIn('string-visualizer-text-group', output)
        self.assertIn('<span snc-idx-start="1">', output)


class TestRunEmissionEdgeCases(unittest.TestCase):
    """Pin the char-emission behaviors the run-based visualize_els walk must
    preserve: which chars get individual spans, where groups start, and how
    abutting/sentinel-adjacent matches split."""

    def test_adjacent_single_char_matches_all_individual(self):
        """r's' on 'sss': every match char is its own start AND end, so all
        three get individual highlighted spans and nothing groups."""
        model = init_model("sss")
        model['search'] = r"r's'"
        output = visualize("sss", model, None, None)
        for idx in (1, 2, 3):
            self.assertIn(f'snc-idx="{idx}"', output)
        self.assertNotIn('snc-idx-start', output)

    def test_abutting_two_char_matches_all_boundary(self):
        """r'ss' on 'ssss' matches [1,3) and [3,5); every char is a boundary
        char of its match, so no interior groups form."""
        model = init_model("ssss")
        model['search'] = r"r'ss'"
        output = visualize("ssss", model, None, None)
        for idx in (1, 2, 3, 4):
            self.assertIn(f'snc-idx="{idx}"', output)
        self.assertNotIn('snc-idx-start', output)

    def test_abutting_interiors_group_separately(self):
        """r'aaaa|bbbb' on 'aaaabbbb': interiors 'aa' (idx 2) and 'bb' (idx 6)
        each group under their own match; the seam at 4|5 stays individual."""
        model = init_model("aaaabbbb")
        model['search'] = r"r'aaaa|bbbb'"
        output = visualize("aaaabbbb", model, None, None)
        import re as _re
        m1 = _re.search(r'<span class="([^"]*)" snc-idx-start="2"[^>]*>aa</span>', output)
        m2 = _re.search(r'<span class="([^"]*)" snc-idx-start="6"[^>]*>bb</span>', output)
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        for idx in (1, 4, 5, 8):
            self.assertIn(f'snc-idx="{idx}"', output)

    def test_match_ending_at_line_end(self):
        """r'b' on 'ab\\ncd': the match char just before the newline sentinels
        renders as an individual highlighted span at internal index 2."""
        model = init_model("ab\ncd")
        model['search'] = r"r'b'"
        output = visualize("ab\ncd", model, None, None)
        import re as _re
        m = _re.search(r'<span class="([^"]*)" snc-idx="2"', output)
        self.assertIsNotNone(m)
        self.assertIn('highlight', m.group(1))

    def test_match_spanning_newline_keeps_sentinels_individual(self):
        """r'b\\nc' on 'ab\\ncd' covers the $/\\n/^ expansion; those stay
        individual spans and pick up the highlight."""
        model = init_model("ab\ncd")
        model['search'] = r"r'b\nc'"
        output = visualize("ab\ncd", model, None, None)
        import re as _re
        for idx in (2, 3, 4, 5, 6):
            m = _re.search(rf'<span class="([^"]*)" snc-idx="{idx}"', output)
            self.assertIsNotNone(m, f"index {idx} should be an individual span")
            self.assertIn('highlight', m.group(1))

    def test_escaping_inside_highlighted_group(self):
        """Interior match chars that need HTML escaping are escaped in the
        grouped span."""
        model = init_model("x<<<<y")
        model['search'] = r"r'<<<<'"
        output = visualize("x<<<<y", model, None, None)
        import re as _re
        m = _re.search(r'<span class="[^"]*highlight[^"]*" snc-idx-start="3"[^>]*>&lt;&lt;</span>', output)
        self.assertIsNotNone(m)

    def test_empty_line_groups_resume_correctly(self):
        """'a\\n\\nb': groups re-form after the double newline expansion with
        the right internal start index."""
        model = init_model("a\n\nb")
        output = visualize("a\n\nb", model, None, None)
        # ^=0 a=1 $=2 \n=3 ^=4 $=5 \n=6 ^=7 b=8 $=9
        self.assertIn('snc-idx-start="1"', output)
        self.assertIn('snc-idx-start="8"', output)

    def test_match_of_whole_string(self):
        """A match covering the whole string: boundary chars individual, one
        interior group between them."""
        model = init_model("abcdef")
        model['search'] = r"r'abcdef'"
        output = visualize("abcdef", model, None, None)
        import re as _re
        self.assertIn('snc-idx="1"', output)
        self.assertIn('snc-idx="6"', output)
        m = _re.search(r'<span class="[^"]*highlight[^"]*" snc-idx-start="2"[^>]*>bcde</span>', output)
        self.assertIsNotNone(m)


# =============================================================================
# First-Match Toggle Tests
# =============================================================================

class TestIsFirstMatchMode(unittest.TestCase):
    """Test is_first_match_mode helper function."""

    def test_none_is_not_first_match(self):
        self.assertFalse(is_first_match_mode(None))

    def test_many_match_default(self):
        self.assertFalse(is_first_match_mode(r"r'hello'"))

    def test_first_match_with_1_postfix(self):
        self.assertTrue(is_first_match_mode(r"r'hello'1"))

    def test_complex_pattern_many_match(self):
        self.assertFalse(is_first_match_mode(r"r'hello.*world'"))

    def test_complex_pattern_first_match(self):
        self.assertTrue(is_first_match_mode(r"r'hello.*world'1"))

    def test_empty_pattern_not_first_match(self):
        self.assertFalse(is_first_match_mode(r"r''"))

    def test_empty_pattern_first_match(self):
        self.assertTrue(is_first_match_mode(r"r''1"))


class TestGetRegexInnerPatternWithPostfix(unittest.TestCase):
    """Test get_regex_inner_pattern strips /1 postfix correctly."""

    def test_many_match_pattern(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'"), 'hello')

    def test_first_match_pattern_strips_1(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'1"), 'hello')

    def test_complex_first_match(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello.*world'1"), 'hello.*world')

    def test_none_returns_none(self):
        self.assertIsNone(get_regex_inner_pattern(None))


class TestFirstMatchToggle(unittest.TestCase):
    """Test the FirstMatchToggle event toggles between first and many match mode."""

    def setUp(self):
        self.value = "hello world hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_from_many_to_first(self):
        """Toggling from many-match adds /1 postfix."""
        self.model['search'] = r"r'hello'"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'1")

    def test_toggle_from_first_to_many(self):
        """Toggling from first-match removes /1 postfix."""
        self.model['search'] = r"r'hello'1"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

    def test_toggle_with_no_search_creates_bare_flags(self):
        """Toggling with no search creates bare backtick form with flag."""
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '``1')

    def test_toggle_off_bare_flags_returns_to_none(self):
        """Toggling off the only flag on bare form returns search to None."""
        self.model['search'] = '``1'
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIsNone(model['search'])

    def test_toggle_saves_undo(self):
        """Toggling saves to undo history."""
        self.model['search'] = r"r'hello'"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIn(r"r'hello'", model['undoHistory'])

    def test_double_toggle_roundtrip(self):
        """Toggling twice returns to original state."""
        self.model['search'] = r"r'hello'"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'1")
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")


class TestManyMatchHighlighting(unittest.TestCase):
    """Test that many-match mode highlights ALL matches, not just the first."""

    def test_many_match_highlights_all_occurrences(self):
        """Many-match mode should return highlights for all matches."""
        value = "abc abc abc"
        highlights = parse_regex_for_highlighting(r"r'abc'", value)
        match_starts = [h[0] for h in highlights]
        self.assertGreater(len(match_starts), 1,
                           "Many-match should highlight more than one occurrence")

    def test_first_match_highlights_only_first(self):
        """First-match mode should return highlights for only the first match."""
        value = "abc abc abc"
        highlights = parse_regex_for_highlighting(r"r'abc'1", value)
        match_count = len(set(h[0] for h in highlights))
        self.assertEqual(match_count, 1,
                         "First-match should highlight only one occurrence")

    def test_many_match_correct_positions(self):
        """Many-match mode highlights at correct string positions."""
        value = "ab ab"
        # "ab" appears at string positions 0-2 and 3-5
        # Internal indices: +2 offset, so first "ab" at 2-4, second at 5-7
        highlights = parse_regex_for_highlighting(r"r'ab'", value)
        starts = sorted(set(h[0] for h in highlights))
        self.assertEqual(len(starts), 2, "Should find two 'ab' matches")

    def test_many_match_with_fuzzy_pattern(self):
        """Many-match with fuzzy pattern highlights multiple matches."""
        value = "12 34 56"
        highlights = parse_regex_for_highlighting(r"r'\d+'", value)
        starts = sorted(set(h[0] for h in highlights))
        self.assertGreaterEqual(len(starts), 3,
                                "Should find three digit groups")

    def test_many_match_no_matches(self):
        """Many-match with no matches returns empty."""
        value = "hello world"
        highlights = parse_regex_for_highlighting(r"r'xyz'", value)
        self.assertEqual(len(highlights), 0)


class TestFirstMatchEnterCodeGen(unittest.TestCase):
    """Test Enter code gen differs between first-match and many-match modes."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_many_match_enter_generates_finditer(self):
        """Default many-match Enter generates list(re.finditer(...))."""
        self.model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(", expr)

    def test_first_match_enter_generates_search(self):
        """First-match Enter generates re.search(...)."""
        self.model['search'] = r"r'hello'1"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_substring")
        self.assertIn("next(iter(re.findall(", expr)
        self.assertNotIn("finditer", expr)

    def test_first_match_enter_with_complex_pattern(self):
        """First-match Enter with grouped pattern uses re.search."""
        self.model['search'] = r"r'(hello)(.*)(world)'1"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIn("next(iter(re.findall(", expr)


class TestFirstMatchBackspaceCodeGen(unittest.TestCase):
    """Test Backspace code gen differs between first-match and many-match modes."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_many_match_backspace_generates_sub(self):
        """Default many-match Backspace generates re.sub without count."""
        self.model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertIn("re.sub(", expr)
        self.assertNotIn("count=1", expr)

    def test_first_match_backspace_generates_sub_with_count(self):
        """First-match Backspace generates re.sub with count=1."""
        self.model['search'] = r"r'hello'1"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertIn("re.sub(", expr)
        self.assertIn("count=1", expr)


class TestFirstMatchToggleRendering(unittest.TestCase):
    """Test that the first-match toggle button renders in the search box.

    The button is now icon-only (no '1st' text label), so we identify it by
    its FirstMatchToggle event handler.
    """

    def test_toggle_button_present(self):
        """The first-match toggle button should be present in the search box HTML."""
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        self.assertIn('FirstMatchToggle', output)

    def test_toggle_button_inactive_by_default(self):
        """The toggle should be marked inactive by default (no /1 flag)."""
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        self.assertIn('FirstMatchToggle', output)
        # In the search-button block surrounding FirstMatchToggle, the inactive class is applied by default.
        import re as _re
        m = _re.search(r'<span class="search-button (\w+)"[^>]*snc-mouse-down="FirstMatchToggle', output)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), 'inactive')

    def test_toggle_button_active_when_first_match(self):
        """The toggle should be marked active when search has /1 flag."""
        model = init_model("hello world")
        model['search'] = r"r'hello'1"
        output = visualize("hello world", model, None, None)
        import re as _re
        m = _re.search(r'<span class="search-button (\w+)"[^>]*snc-mouse-down="FirstMatchToggle', output)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), 'active')

    def test_toggle_hidden_when_small(self):
        """The toggle should be hidden when small=True (no search box)."""
        model = init_model("hello world")
        output = visualize("hello world", model, None, None, small=True)
        self.assertNotIn('FirstMatchToggle', output)


class TestSearchBoxValueWithPostfix(unittest.TestCase):
    """Test that the search box displays the full value including /1 postfix."""

    def test_search_box_shows_postfix(self):
        """The search box value should include the 1 postfix when in first-match mode."""
        import html as html_mod
        model = init_model("hello world")
        model['search'] = r"r'hello'1"
        output = visualize("hello world", model, None, None)
        self.assertIn(html_mod.escape(r"r'hello'1"), output)

    def test_search_box_input_preserves_postfix(self):
        """Typing r'hello'1 in the search box sets first-match mode."""
        model = init_model("hello world")
        model, _ = update(make_search_box_input_event(r"r'hello'1"),
                          ('x', 'x'), model, "hello world")
        self.assertEqual(model['search'], r"r'hello'1")
        self.assertTrue(is_first_match_mode(model['search']))


def make_first_match_toggle_event() -> dict:
    """Create a FirstMatchToggle event dict."""
    return {
        'pythonEventStr': repr(FirstMatchToggle()),
        'eventJSON': {},
    }


def make_case_sensitive_toggle_event() -> dict:
    """Create a CaseSensitiveToggle event dict."""
    return {
        'pythonEventStr': repr(CaseSensitiveToggle()),
        'eventJSON': {},
    }


# =============================================================================
# Case-Sensitive Toggle Tests
# =============================================================================

class TestGetSearchFlags(unittest.TestCase):
    """Test get_search_flags helper that extracts postfix flags."""

    def test_no_flags(self):
        self.assertEqual(get_search_flags(r"r'hello'"), '')

    def test_first_match_flag(self):
        self.assertEqual(get_search_flags(r"r'hello'1"), '1')

    def test_case_insensitive_flag(self):
        self.assertEqual(get_search_flags(r"r'hello'i"), 'i')

    def test_combined_flags_1i(self):
        self.assertEqual(get_search_flags(r"r'hello'1i"), '1i')

    def test_combined_flags_i1(self):
        self.assertEqual(get_search_flags(r"r'hello'i1"), 'i1')

    def test_none_returns_empty(self):
        self.assertEqual(get_search_flags(None), '')

    def test_pattern_with_slash(self):
        """Slash inside the regex pattern doesn't confuse flag extraction."""
        self.assertEqual(get_search_flags(r"r'a\/b'i"), 'i')


class TestIsCaseInsensitive(unittest.TestCase):
    """Test is_case_insensitive helper."""

    def test_none_is_case_sensitive(self):
        self.assertFalse(is_case_insensitive(None))

    def test_no_flag_is_case_sensitive(self):
        self.assertFalse(is_case_insensitive(r"r'hello'"))

    def test_i_flag_is_case_insensitive(self):
        self.assertTrue(is_case_insensitive(r"r'hello'i"))

    def test_1i_flag_is_case_insensitive(self):
        self.assertTrue(is_case_insensitive(r"r'hello'1i"))

    def test_1_flag_only_is_case_sensitive(self):
        self.assertFalse(is_case_insensitive(r"r'hello'1"))


class TestGetRegexInnerPatternWithFlags(unittest.TestCase):
    """Test get_regex_inner_pattern strips all postfix flags."""

    def test_no_flags(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'"), 'hello')

    def test_1_flag(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'1"), 'hello')

    def test_i_flag(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'i"), 'hello')

    def test_1i_flags(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'1i"), 'hello')

    def test_i1_flags(self):
        self.assertEqual(get_regex_inner_pattern(r"r'hello'i1"), 'hello')

    def test_pattern_with_slash(self):
        """Slash inside the regex pattern is preserved verbatim."""
        self.assertEqual(get_regex_inner_pattern(r"r'a\/b'i"), r'a\/b')


class TestIsFirstMatchModeWithCombinedFlags(unittest.TestCase):
    """Test is_first_match_mode works with combined flag postfixes."""

    def test_1_flag(self):
        self.assertTrue(is_first_match_mode(r"r'hello'1"))

    def test_1i_flag(self):
        self.assertTrue(is_first_match_mode(r"r'hello'1i"))

    def test_i1_flag(self):
        self.assertTrue(is_first_match_mode(r"r'hello'i1"))

    def test_i_flag_only(self):
        self.assertFalse(is_first_match_mode(r"r'hello'i"))

    def test_no_flags(self):
        self.assertFalse(is_first_match_mode(r"r'hello'"))


class TestCaseSensitiveToggle(unittest.TestCase):
    """Test the CaseSensitiveToggle event."""

    def setUp(self):
        self.value = "Hello hello HELLO"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_to_case_insensitive(self):
        """Toggling from case-sensitive adds i flag."""
        self.model['search'] = r"r'hello'"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'i")

    def test_toggle_to_case_sensitive(self):
        """Toggling from case-insensitive removes i flag."""
        self.model['search'] = r"r'hello'i"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'")

    def test_toggle_preserves_first_match_flag(self):
        """Toggling case preserves the 1 flag."""
        self.model['search'] = r"r'hello'1"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'1i")

    def test_toggle_off_preserves_first_match_flag(self):
        """Toggling case off with 1 flag preserves 1."""
        self.model['search'] = r"r'hello'1i"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'1")

    def test_toggle_with_no_search_creates_bare_flags(self):
        """Toggling with no search creates bare backtick form with i flag."""
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '``i')

    def test_toggle_off_bare_flags_returns_to_none(self):
        """Toggling off the only flag on bare form returns search to None."""
        self.model['search'] = '``i'
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIsNone(model['search'])

    def test_toggle_saves_undo(self):
        self.model['search'] = r"r'hello'"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIn(r"r'hello'", model['undoHistory'])

    def test_double_toggle_roundtrip(self):
        self.model['search'] = r"r'hello'"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'i")
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello'")


class TestCaseInsensitiveHighlighting(unittest.TestCase):
    """Test that case-insensitive flag affects highlighting."""

    def test_case_insensitive_matches_different_cases(self):
        """Case-insensitive search highlights all case variants."""
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting(r"r'hello'i", value)
        starts = sorted(set(h[0] for h in highlights))
        self.assertEqual(len(starts), 3, "Should match all three 'hello' variants")

    def test_case_sensitive_matches_exact_case_only(self):
        """Case-sensitive search only matches exact case."""
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting(r"r'hello'", value)
        starts = sorted(set(h[0] for h in highlights))
        self.assertEqual(len(starts), 1, "Should match only exact 'hello'")

    def test_case_insensitive_first_match(self):
        """Case-insensitive + first-match highlights only first case variant."""
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting(r"r'hello'1i", value)
        match_count = len(set(h[0] for h in highlights))
        self.assertEqual(match_count, 1, "First-match should highlight only one")


class TestCaseInsensitiveEnterCodeGen(unittest.TestCase):
    """Test Enter generates code with re.I flag when case-insensitive."""

    def setUp(self):
        self.value = "Hello hello"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_case_sensitive_enter_no_re_I(self):
        """Case-sensitive Enter should NOT include re.I in flags."""
        self.model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertNotIn('re.I', expr)

    def test_case_insensitive_enter_has_re_I(self):
        """Case-insensitive Enter should include re.I in flags."""
        self.model['search'] = r"r'hello'i"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('re.I', expr)
        self.assertIn('re.M', expr)

    def test_case_insensitive_first_match_enter(self):
        """Case-insensitive + first-match Enter uses re.search with re.I."""
        self.model['search'] = r"r'hello'1i"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIn('next(iter(re.findall(', expr)
        self.assertIn('re.I', expr)
        self.assertEqual(suggest_name, "x_substring")


class TestCaseInsensitiveBackspaceCodeGen(unittest.TestCase):
    """Test Backspace generates code with re.I flag when case-insensitive."""

    def setUp(self):
        self.value = "Hello hello"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_case_sensitive_backspace_no_re_I(self):
        self.model['search'] = r"r'hello'"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertNotIn('re.I', expr)

    def test_case_insensitive_backspace_has_re_I(self):
        self.model['search'] = r"r'hello'i"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('re.I', expr)
        self.assertIn('re.M', expr)

    def test_case_insensitive_first_match_backspace(self):
        """Case-insensitive + first-match Backspace uses count=1 and re.I."""
        self.model['search'] = r"r'hello'1i"
        model, commands = update(make_key_down_event('Backspace', meta_key=True),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('count=1', expr)
        self.assertIn('re.I', expr)


class TestCaseSensitiveToggleRendering(unittest.TestCase):
    """Test that the case-sensitive toggle button renders in the search box.

    The button is now icon-only (the literal 'Aa' label was replaced with an
    SVG glyph), so we identify it by its CaseSensitiveToggle event handler.
    """

    def test_aa_button_present(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('CaseSensitiveToggle', output)

    def test_aa_button_active_by_default(self):
        """Toggle should be marked as the case-sensitive active state by default."""
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('CaseSensitiveToggle', output)
        # The active class is applied to the button when case-sensitive (the default).
        self.assertIn('search-button active', output)

    def test_aa_button_hidden_when_small(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('CaseSensitiveToggle', output)


# =============================================================================
# Capture Groups Toggle Tests
# =============================================================================

def make_capture_groups_toggle_event() -> dict:
    """Create a CaptureGroupsToggle event dict."""
    return {
        'pythonEventStr': repr(CaptureGroupsToggle()),
        'eventJSON': {},
    }


class TestIsCaptureGroupsMode(unittest.TestCase):
    """Test the is_capture_groups_mode flag checker."""

    def test_c_flag_present(self):
        self.assertTrue(is_capture_groups_mode(r"r'hello'c"))

    def test_c_flag_absent(self):
        self.assertFalse(is_capture_groups_mode(r"r'hello'"))

    def test_c_with_other_flags(self):
        self.assertTrue(is_capture_groups_mode(r"r'hello'1ic"))

    def test_none_returns_false(self):
        self.assertFalse(is_capture_groups_mode(None))

    def test_no_flags(self):
        self.assertFalse(is_capture_groups_mode(r"r'hello'"))


class TestEnsureAllGroups(unittest.TestCase):
    """Test the ensure_all_groups function."""

    def test_ungrouped_becomes_grouped(self):
        """Canonical /hello.*world/ becomes /(hello)(.*)(world)/."""
        self.assertEqual(ensure_all_groups(r"r'hello.*world'"), r"r'(hello)(.*)(world)'")

    def test_already_grouped_unchanged(self):
        """Already fully-grouped regex is unchanged."""
        self.assertEqual(ensure_all_groups(r"r'(hello)(.*)(world)'"), r"r'(hello)(.*)(world)'")

    def test_single_literal(self):
        """Single literal gets grouped."""
        self.assertEqual(ensure_all_groups(r"r'hello'"), r"r'(hello)'")

    def test_preserves_flags(self):
        """Flags are preserved after re-grouping."""
        self.assertEqual(ensure_all_groups(r"r'hello.*world'1i"), r"r'(hello)(.*)(world)'1i")

    def test_preserves_c_flag(self):
        """The c flag is preserved."""
        self.assertEqual(ensure_all_groups(r"r'hello.*world'c"), r"r'(hello)(.*)(world)'c")

    def test_none_returns_none(self):
        self.assertIsNone(ensure_all_groups(None))

    def test_non_regex_returns_unchanged(self):
        """Non-regex search strings pass through unchanged."""
        self.assertEqual(ensure_all_groups("'hello'"), "'hello'")

    def test_adjacent_literals_grouped(self):
        """Adjacent literals that canonicalize normally get fully grouped."""
        result = ensure_all_groups(r"r'(hello)(world)'")
        self.assertEqual(result, r"r'(hello)(world)'")


class TestCaptureGroupsToggle(unittest.TestCase):
    """Test the CaptureGroupsToggle event."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_on_adds_c_flag_and_groups(self):
        """Toggling on adds 'c' flag and fully groups the pattern."""
        self.model['search'] = r"r'hello.*world'"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIn('c', get_search_flags(model['search']))
        self.assertEqual(model['search'], r"r'(hello)(.*)(world)'c")

    def test_toggle_off_removes_c_flag_and_canonicalizes(self):
        """Toggling off removes 'c' flag and re-canonicalizes."""
        self.model['search'] = r"r'(hello)(.*)(world)'c"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertNotIn('c', get_search_flags(model['search']))
        self.assertEqual(model['search'], r"r'hello.*world'")

    def test_toggle_preserves_other_flags(self):
        """Toggling c preserves existing i and 1 flags."""
        self.model['search'] = r"r'hello'1i"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'(hello)'1ic")

    def test_toggle_off_preserves_other_flags(self):
        """Toggling c off preserves i and 1 flags."""
        self.model['search'] = r"r'(hello)'1ic"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'hello'1i")

    def test_toggle_with_no_search_does_nothing(self):
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIsNone(model['search'])

    def test_toggle_saves_undo(self):
        self.model['search'] = r"r'hello'"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertIn(r"r'hello'", model['undoHistory'])

    def test_double_toggle_roundtrip(self):
        self.model['search'] = r"r'hello.*world'"
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], r"r'(hello)(.*)(world)'c")
        model, _ = update(make_capture_groups_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], r"r'hello.*world'")


class TestCaptureGroupsToggleRendering(unittest.TestCase):
    """Test that the '(Cap)(Grps)' toggle renders in the search box."""

    def test_button_present(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None)
        self.assertIn('CaptureGroupsToggle', output)

    def test_button_hidden_when_small(self):
        model = init_model("hello")
        output = visualize("hello", model, None, None, small=True)
        self.assertNotIn('(Cap)', output)


class TestCaptureGroupsFlagAwareSegmentFunctions(unittest.TestCase):
    """Test that segment manipulation functions properly handle postfix flags."""

    def test_append_segment_preserves_flags(self):
        """append_segment_to_regex with flags doesn't corrupt the pattern."""
        result = append_segment_to_regex(r"r'hello'1i", 'literal', 'world')
        self.assertIn('hello', result)
        self.assertIn('world', result)
        self.assertIn('1i', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertNotIn('/', inner)

    def test_append_segment_with_c_flag_groups_all(self):
        """append_segment_to_regex with 'c' flag produces fully-grouped result."""
        result = append_segment_to_regex(r"r'hello'c", 'fuzzy', '.*')
        self.assertIn('c', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertTrue(inner.startswith('('), f"Expected grouped inner, got: {inner}")

    def test_replace_segment_pattern_preserves_flags(self):
        """replace_segment_pattern with flags doesn't corrupt the pattern."""
        result = replace_segment_pattern(r"r'(hello)(\s*)'1i", 0, r'\d')
        self.assertIn('1i', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertNotIn('/', inner)

    def test_replace_segment_repetition_preserves_flags(self):
        """replace_segment_repetition with flags doesn't corrupt the pattern."""
        result = replace_segment_repetition(r"r'(hello)(\s*)'1i", 1, '+')
        self.assertIn('1i', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertNotIn('/', inner)

    def test_resize_literal_preserves_flags(self):
        """resize_literal_segment with flags doesn't corrupt the pattern."""
        value = "hello world"
        result = resize_literal_segment(r"r'(hello)'1i", 0, value, _legacy_internal_index(2), _legacy_internal_index(7))
        self.assertIn('1i', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertNotIn('/', inner)

    def test_canonicalize_preserves_adjacent_literal_groups_with_c_flag(self):
        """When c flag is on, all groups are kept after canonicalize."""
        result = append_segment_to_regex(r"r'(hello)(.*)'c", 'literal', 'world')
        self.assertIn('c', get_search_flags(result))
        inner = get_regex_inner_pattern(result)
        self.assertEqual(inner.count('('), inner.count(')'))
        self.assertTrue(inner.startswith('('))


class TestCaptureGroupsCodeGeneration(unittest.TestCase):
    """Test that code generation preserves groups when 'c' flag is on."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_enter_with_c_flag_preserves_groups_in_code(self):
        """Enter with 'c' flag generates code with capture groups."""
        self.model['search'] = r"r'(hello)(.*)(world)'c"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('(hello)', expr)
        self.assertIn('(world)', expr)

    def test_enter_without_c_flag_strips_groups(self):
        """Enter without 'c' flag strips capture groups from code."""
        self.model['search'] = r"r'(hello)(.*)(world)'"
        model, commands = update(make_key_down_event('Enter'),
                                self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("hello.*world", expr)
        self.assertNotIn('(hello)', expr)


class TestCaptureGroupsBuildPreviewRegex(unittest.TestCase):
    """Test that build_preview_regex respects the 'c' flag."""

    def test_selection_with_c_flag_produces_grouped_regex(self):
        """When 'c' is in the current search flags, new selections keep all groups."""
        value = "hello world"
        model = init_model(value)
        var_and_exp = ('x', 'x')

        model['search'] = r"r'(hello)'c"
        end_idx = get_last_segment_end_internal_idx(model['search'], value)

        model, _ = update(make_mouse_down_event(end_idx, legacy_index=False, top_half=False),
                          var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(end_idx, legacy_index=False, alt_key=True),
                          var_and_exp, model, value)

        self.assertIn('c', get_search_flags(model['search']))
        inner = get_regex_inner_pattern(model['search'])
        self.assertTrue(inner.startswith('('), f"Expected grouped, got: {inner}")


# =============================================================================
# String Search Tests
# =============================================================================

class TestFindClosingDelimiter(unittest.TestCase):
    """Test _find_closing_delimiter for regex and string searches."""

    def test_regex(self):
        # r'hello' is 8 chars; closing ' is at index 7, function returns one past.
        self.assertEqual(_find_closing_delimiter(r"r'hello'"), 8)

    def test_regex_with_flags(self):
        self.assertEqual(_find_closing_delimiter(r"r'hello'1i"), 8)

    def test_single_quote(self):
        self.assertEqual(_find_closing_delimiter("'hello'"), 7)

    def test_double_quote(self):
        self.assertEqual(_find_closing_delimiter('"hello"'), 7)

    def test_triple_single_quote(self):
        self.assertEqual(_find_closing_delimiter("'''hello'''"), 11)

    def test_triple_double_quote(self):
        self.assertEqual(_find_closing_delimiter('"""hello"""'), 11)

    def test_single_quote_with_flags(self):
        self.assertEqual(_find_closing_delimiter("'hello'i"), 7)

    def test_triple_quote_with_flags(self):
        self.assertEqual(_find_closing_delimiter("'''hello'''1i"), 11)

    def test_f_string(self):
        self.assertEqual(_find_closing_delimiter("f'hello'"), 8)

    def test_r_string(self):
        self.assertEqual(_find_closing_delimiter("r'hello'"), 8)

    def test_b_string(self):
        self.assertEqual(_find_closing_delimiter("b'hello'"), 8)

    def test_fr_string(self):
        self.assertEqual(_find_closing_delimiter("fr'hello'"), 9)

    def test_rb_string(self):
        self.assertEqual(_find_closing_delimiter("rb'hello'"), 9)

    def test_escaped_quote_in_single(self):
        self.assertEqual(_find_closing_delimiter(r"'it\'s'"), 7)

    def test_no_closing_delimiter_returns_none(self):
        self.assertIsNone(_find_closing_delimiter("'hello"))

    def test_none_returns_none(self):
        self.assertIsNone(_find_closing_delimiter(None))

    def test_empty_string_literal(self):
        self.assertEqual(_find_closing_delimiter("''"), 2)

    def test_empty_regex(self):
        # r'' is 3 chars: r ' '
        self.assertEqual(_find_closing_delimiter(r"r''"), 3)

    def test_triple_quote_with_single_inside(self):
        self.assertEqual(_find_closing_delimiter("'''it's'''"), 10)

    def test_double_quote_with_escaped_inside(self):
        self.assertEqual(_find_closing_delimiter(r'"say \"hi\""'), 12)

    def test_raw_string_backslash_doesnt_escape(self):
        # r'\' is a valid raw string containing a single backslash
        self.assertEqual(_find_closing_delimiter(r"r'hello\'"), 9)


class TestIsRegexSearch(unittest.TestCase):
    def test_regex(self):
        self.assertTrue(is_regex_search(r"r'hello'"))

    def test_string(self):
        self.assertFalse(is_regex_search("'hello'"))

    def test_none(self):
        self.assertFalse(is_regex_search(None))


class TestEvalStringSearch(unittest.TestCase):
    """Test eval_string_search evaluates the string literal to a Python str."""

    def test_simple_single_quote(self):
        self.assertEqual(eval_string_search("'hello'"), "hello")

    def test_simple_double_quote(self):
        self.assertEqual(eval_string_search('"hello"'), "hello")

    def test_with_flags(self):
        self.assertEqual(eval_string_search("'hello'i"), "hello")

    def test_escape_sequence(self):
        self.assertEqual(eval_string_search(r"'hello\nworld'"), "hello\nworld")

    def test_triple_quote(self):
        self.assertEqual(eval_string_search("'''hello'''"), "hello")

    def test_raw_string_treated_as_regex(self):
        # r'..' now parses as a regex search, not a string literal.
        self.assertIsNone(eval_string_search(r"r'\n'"))

    def test_regex_returns_none(self):
        self.assertIsNone(eval_string_search(r"r'hello'"))

    def test_none_returns_none(self):
        self.assertIsNone(eval_string_search(None))

    def test_unterminated_returns_none(self):
        self.assertIsNone(eval_string_search("'hello"))

    def test_empty_string(self):
        self.assertEqual(eval_string_search("''"), "")


class TestGetSearchFlagsWithStrings(unittest.TestCase):
    """Test get_search_flags works for both regex and string searches."""

    def test_regex_no_flags(self):
        self.assertEqual(get_search_flags(r"r'hello'"), '')

    def test_regex_flags(self):
        self.assertEqual(get_search_flags(r"r'hello'1i"), '1i')

    def test_string_no_flags(self):
        self.assertEqual(get_search_flags("'hello'"), '')

    def test_string_i_flag(self):
        self.assertEqual(get_search_flags("'hello'i"), 'i')

    def test_string_1i_flags(self):
        self.assertEqual(get_search_flags("'hello'1i"), '1i')

    def test_triple_quote_flags(self):
        self.assertEqual(get_search_flags("'''hello'''1"), '1')

    def test_f_string_flags(self):
        self.assertEqual(get_search_flags("f'hello'i"), 'i')


class TestIsFirstMatchModeWithStrings(unittest.TestCase):
    def test_string_no_flags(self):
        self.assertFalse(is_first_match_mode("'hello'"))

    def test_string_1_flag(self):
        self.assertTrue(is_first_match_mode("'hello'1"))

    def test_string_1i_flags(self):
        self.assertTrue(is_first_match_mode("'hello'1i"))


class TestIsCaseInsensitiveWithStrings(unittest.TestCase):
    def test_string_no_flags(self):
        self.assertFalse(is_case_insensitive("'hello'"))

    def test_string_i_flag(self):
        self.assertTrue(is_case_insensitive("'hello'i"))


class TestToggleFlagWithStrings(unittest.TestCase):
    """Test _toggle_search_flag works with string search format."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_first_match_on_string(self):
        self.model['search'] = "'hello'"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], "'hello'1")

    def test_toggle_case_on_string(self):
        self.model['search'] = "'hello'"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], "'hello'i")

    def test_toggle_both_flags_on_string(self):
        self.model['search'] = "'hello'"
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], "'hello'1i")

    def test_toggle_roundtrip_on_string(self):
        self.model['search'] = "'hello'"
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], "'hello'i")
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], "'hello'")


class TestStringSearchHighlighting(unittest.TestCase):
    """Test that string search produces correct highlighting."""

    def test_single_match(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting("'hello'", value)
        self.assertEqual(len(highlights), 1)
        start, end, seg_type, _, _, _, _ = highlights[0]
        self.assertEqual(seg_type, 'literal')

    def test_many_match(self):
        value = "abc abc abc"
        highlights = parse_regex_for_highlighting("'abc'", value)
        self.assertEqual(len(highlights), 3)

    def test_first_match_only(self):
        value = "abc abc abc"
        highlights = parse_regex_for_highlighting("'abc'1", value)
        self.assertEqual(len(highlights), 1)

    def test_case_insensitive(self):
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting("'hello'i", value)
        self.assertEqual(len(highlights), 3)

    def test_case_sensitive(self):
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting("'hello'", value)
        self.assertEqual(len(highlights), 1)

    def test_no_match(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting("'xyz'", value)
        self.assertEqual(len(highlights), 0)

    def test_special_regex_chars_are_escaped(self):
        """Dots, parens, etc. in the literal should not be treated as regex."""
        value = "hello (world)."
        highlights = parse_regex_for_highlighting("'(world).'", value)
        self.assertEqual(len(highlights), 1)

    def test_escape_sequence(self):
        r"""String with \n should match actual newlines."""
        value = "hello\nworld"
        highlights = parse_regex_for_highlighting(r"'\n'", value)
        self.assertEqual(len(highlights), 1)

    def test_double_quote_string(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting('"hello"', value)
        self.assertEqual(len(highlights), 1)

    def test_triple_quote_string(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting("'''hello'''", value)
        self.assertEqual(len(highlights), 1)

    def test_empty_string_search_no_highlights(self):
        """Empty string literal should not produce highlights."""
        value = "hello"
        highlights = parse_regex_for_highlighting("''", value)
        self.assertEqual(len(highlights), 0)

    def test_combined_first_match_case_insensitive(self):
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting("'hello'1i", value)
        self.assertEqual(len(highlights), 1)


class TestStringSearchEnterCodeGen(unittest.TestCase):
    """Test Enter code generation for string searches."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_many_match_case_sensitive(self):
        self.model['search'] = "'hello'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.escape('hello')", expr)
        self.assertIn("re.findall(", expr)
        self.assertNotIn("re.I", expr)

    def test_first_match_case_sensitive(self):
        self.model['search'] = "'hello'1"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_substring")
        self.assertIn("next(iter(re.findall(", expr)
        self.assertIn("re.escape('hello')", expr)

    def test_many_match_case_insensitive(self):
        self.model['search'] = "'hello'i"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.findall(", expr)
        self.assertIn("re.I", expr)

    def test_first_match_case_insensitive(self):
        self.model['search'] = "'hello'1i"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIn("next(iter(re.findall(", expr)
        self.assertIn("re.I", expr)
        self.assertEqual(suggest_name, "x_substring")

    def test_double_quote_preserved(self):
        """Double-quote string literal preserved in generated code."""
        self.model['search'] = '"hello"'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('re.escape("hello")', expr)


class TestStringSearchBackspaceCodeGen(unittest.TestCase):
    """Test Backspace code generation for string searches."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_many_match_case_sensitive(self):
        self.model['search'] = "'hello'"
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertIn(".replace('hello', '')", expr)
        self.assertNotIn("re.sub", expr)

    def test_first_match_case_sensitive(self):
        self.model['search'] = "'hello'1"
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn(".replace('hello', '', 1)", expr)

    def test_many_match_case_insensitive(self):
        self.model['search'] = "'hello'i"
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.sub(", expr)
        self.assertIn("re.escape('hello')", expr)
        self.assertIn("re.I", expr)

    def test_first_match_case_insensitive(self):
        self.model['search'] = "'hello'1i"
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.sub(", expr)
        self.assertIn("count=1", expr)
        self.assertIn("re.I", expr)


# =============================================================================
# Backtick / Expression Search Tests
# =============================================================================

class TestFindClosingDelimiterBacktick(unittest.TestCase):

    def test_backtick(self):
        self.assertEqual(_find_closing_delimiter('`s`'), 3)

    def test_backtick_with_flags(self):
        self.assertEqual(_find_closing_delimiter('`s`1i'), 3)

    def test_backtick_complex_expr(self):
        self.assertEqual(_find_closing_delimiter('`x.lower()`'), 11)

    def test_backtick_no_close_returns_none(self):
        self.assertIsNone(_find_closing_delimiter('`hello'))

    def test_backtick_empty_expr(self):
        self.assertEqual(_find_closing_delimiter('``'), 2)


class TestParseSearchTerm(unittest.TestCase):
    """parse_search_term returns (kind, term, flags) for all search types."""

    # --- regex ---
    def test_regex_no_flags(self):
        self.assertEqual(parse_search_term(r"r'hello'"), ('regex', 'hello', ''))

    def test_regex_with_flags(self):
        self.assertEqual(parse_search_term(r"r'hello'1i"), ('regex', 'hello', '1i'))

    def test_regex_complex_pattern(self):
        self.assertEqual(parse_search_term(r"r'(\d+)\s+'i"), ('regex', r'(\d+)\s+', 'i'))

    # --- string ---
    def test_string_no_flags(self):
        self.assertEqual(parse_search_term("'hello'"), ('string', "'hello'", ''))

    def test_string_with_flags(self):
        self.assertEqual(parse_search_term("'hello'i"), ('string', "'hello'", 'i'))

    def test_string_with_multiple_flags(self):
        self.assertEqual(parse_search_term("'hello'1i"), ('string', "'hello'", '1i'))

    def test_fstring(self):
        self.assertEqual(parse_search_term("f'hello'"), ('string', "f'hello'", ''))

    def test_triple_quoted(self):
        self.assertEqual(parse_search_term("'''hello'''1i"), ('string', "'''hello'''", '1i'))

    def test_double_quoted(self):
        self.assertEqual(parse_search_term('"hello"'), ('string', '"hello"', ''))

    # --- slice ---
    def test_slice_both(self):
        self.assertEqual(parse_search_term('5:10'), ('slice', ('5', '10'), ''))

    def test_slice_start_only(self):
        self.assertEqual(parse_search_term('5:'), ('slice', ('5', ''), ''))

    def test_slice_stop_only(self):
        self.assertEqual(parse_search_term(':5'), ('slice', ('', '5'), ''))

    # --- expr (backtick) ---
    def test_backtick_no_flags(self):
        self.assertEqual(parse_search_term('`s`'), ('expr', 's', ''))

    def test_backtick_with_flags(self):
        self.assertEqual(parse_search_term('`s`1i'), ('expr', 's', '1i'))

    def test_backtick_complex(self):
        self.assertEqual(parse_search_term('`x.lower()`'), ('expr', 'x.lower()', ''))

    # --- expr (bare) ---
    def test_bare_text(self):
        self.assertEqual(parse_search_term('hello'), ('expr', 'hello', ''))

    def test_bare_expression(self):
        self.assertEqual(parse_search_term('f(x)'), ('expr', 'f(x)', ''))

    # --- None / empty ---
    def test_none_returns_none(self):
        self.assertIsNone(parse_search_term(None))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_search_term(''))



class TestGetSearchFlagsBacktickAndBare(unittest.TestCase):

    def test_backtick_no_flags(self):
        self.assertEqual(get_search_flags('`s`'), '')

    def test_backtick_with_flags(self):
        self.assertEqual(get_search_flags('`s`1i'), '1i')

    def test_bare_no_flags(self):
        """Bare text has no closing delimiter so no flags."""
        self.assertEqual(get_search_flags('s'), '')


class TestToggleFlagBareWrapsInBackticks(unittest.TestCase):
    """Toggling a flag on bare text should wrap it in backticks."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_first_match_on_bare(self):
        self.model['search'] = 's'
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '`s`1')

    def test_toggle_case_on_bare(self):
        self.model['search'] = 's'
        model, _ = update(make_case_sensitive_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '`s`i')

    def test_toggle_on_backtick(self):
        self.model['search'] = '`s`'
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '`s`1')

    def test_toggle_roundtrip_backtick(self):
        self.model['search'] = '`s`'
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['search'], '`s`1')
        model, _ = update(make_first_match_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['search'], '`s`')


class TestExpressionSearchHighlighting(unittest.TestCase):
    """Test highlighting for backtick and bare expression searches."""

    def test_backtick_literal_evals(self):
        """Backtick containing a string literal can be eval'd for highlights."""
        value = "hello world"
        highlights = parse_regex_for_highlighting("`'hello'`", value)
        self.assertEqual(len(highlights), 1)

    def test_backtick_variable_no_highlights(self):
        """Backtick referencing a variable can't be eval'd; no highlights."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('`s`', value)
        self.assertEqual(len(highlights), 0)

    def test_bare_literal_evals(self):
        """Bare string literal expression eval'd for highlights."""
        value = "hello world"
        highlights = parse_regex_for_highlighting("`'hello'`", value)
        self.assertEqual(len(highlights), 1)

    def test_bare_variable_no_highlights(self):
        """Bare variable reference can't be eval'd; no highlights."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('s', value)
        self.assertEqual(len(highlights), 0)

    def test_backtick_case_insensitive(self):
        value = "Hello hello HELLO"
        highlights = parse_regex_for_highlighting("`'hello'`i", value)
        self.assertEqual(len(highlights), 3)

    def test_backtick_first_match(self):
        value = "hello hello hello"
        highlights = parse_regex_for_highlighting("`'hello'`1", value)
        self.assertEqual(len(highlights), 1)

    def test_highlight_segment_indices_are_none(self):
        """Expression search highlights should all have segment_index=None."""
        value = "hello world"
        highlights = parse_regex_for_highlighting("`'hello'`", value)
        for h in highlights:
            self.assertIsNone(h[5], "Expression search highlights should be display-only")


class TestExpressionSearchEnterCodeGen(unittest.TestCase):

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_backtick_many_cs(self):
        self.model['search'] = '`s`'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        name, expr = commands[0][:2]
        self.assertEqual(name, 'x_strings')
        self.assertIn('re.findall(re.escape(s)', expr)
        self.assertNotIn('re.I', expr)

    def test_backtick_first_ci(self):
        self.model['search'] = '`s`1i'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        name, expr = commands[0][:2]
        self.assertEqual(name, 'x_substring')
        self.assertIn('next(iter(re.findall(re.escape(s)', expr)
        self.assertIn('re.I', expr)

    def test_bare_many_cs(self):
        self.model['search'] = 's'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        name, expr = commands[0][:2]
        self.assertIn('re.findall(re.escape(s)', expr)

    def test_bare_complex_expression(self):
        self.model['search'] = 'x.lower()'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('re.escape(x.lower())', expr)


class TestExpressionSearchBackspaceCodeGen(unittest.TestCase):

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_backtick_many_cs(self):
        self.model['search'] = '`s`'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        name, expr = commands[0][:2]
        self.assertEqual(name, 'x')
        self.assertIn('.replace(s, \'\')', expr)

    def test_backtick_first_cs(self):
        self.model['search'] = '`s`1'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        _, expr = commands[0][:2]
        self.assertIn(".replace(s, '', 1)", expr)

    def test_backtick_many_ci(self):
        self.model['search'] = '`s`i'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        _, expr = commands[0][:2]
        self.assertIn('re.sub(re.escape(s)', expr)
        self.assertIn('re.I', expr)

    def test_backtick_first_ci(self):
        self.model['search'] = '`s`1i'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        _, expr = commands[0][:2]
        self.assertIn('re.sub(re.escape(s)', expr)
        self.assertIn('count=1', expr)
        self.assertIn('re.I', expr)


# =============================================================================
# Replace Box Tests
# =============================================================================

def make_replace_box_input_event(value: str) -> dict:
    """Create a ReplaceBoxInput event dict (simulates typing in the replace box)."""
    return {
        'pythonEventStr': "lambda e: ReplaceBoxInput(value=e.get('value', ''))",
        'eventJSON': {
            'type': 'input',
            'value': value,
        }
    }


def make_replace_toggle_event() -> dict:
    """Create a ReplaceToggle event dict (simulates clicking the disclosure triangle)."""
    return {
        'pythonEventStr': repr(ReplaceToggle()),
        'eventJSON': {},
    }


class TestReplaceToggle(unittest.TestCase):
    """Test disclosure triangle toggles replace box visibility."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_toggle_shows_replace_box(self):
        """Clicking disclosure triangle shows the replace box."""
        self.assertFalse(self.model.get('replace_visible', False))
        model, _ = update(make_replace_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertTrue(model['replace_visible'])

    def test_toggle_twice_hides_replace_box(self):
        """Clicking disclosure triangle twice hides the replace box."""
        model, _ = update(make_replace_toggle_event(),
                          self.var_and_exp, self.model, self.value)
        self.assertTrue(model['replace_visible'])
        model, _ = update(make_replace_toggle_event(),
                          self.var_and_exp, model, self.value)
        self.assertFalse(model['replace_visible'])


def make_expand_toggle_event() -> dict:
    """Create an ExpandToggle event dict (simulates clicking the expand/collapse toggle)."""
    return {
        'pythonEventStr': repr(ExpandToggle()),
        'eventJSON': {},
    }


def _tiny_lens(html_str: str) -> list:
    """The readouts on the search box, tags and all, left to right."""
    return re.findall(r'<div class="tiny-len".*?</div>', html_str)


def _tiny_len(html_str: str) -> str:
    """Every readout as one string, for asking what the tab says without
    caring which chip says it."""
    return ''.join(_tiny_lens(html_str))


class TestTinyLen(unittest.TestCase):
    """How long the string is, on the tab above the search box."""

    # The line count is one number with two readings, so its handle offers
    # both and labels them apart: how many, and the lines themselves.
    LINE_EXPS = (PyExp("x.count('\\n') + 1", label='Count'),
                 PyExp('x.splitlines()', label='As list'))

    def setUp(self):
        self.tall_value = "l1\nl2\nl3\nl4\nl5"   # 5 lines -> clipped
        self.short_value = "l1\nl2\nl3\nl4"     # exactly 4 -> not clipped
        self.var_and_exp = ('x', 'x')

    def render(self, value, small=False, var_and_exp=None):
        return visualize(value, init_model(value), None, None, small=small,
                         var_and_exp=var_and_exp)

    def test_the_tab_says_how_long_the_string_is(self):
        self.assertIn('14 chars', _tiny_len(self.render(self.tall_value)))

    def test_a_string_that_fits_counts_itself_too(self):
        # It rides the search box, and every focused string has one.
        self.assertIn('11 chars', _tiny_len(self.render(self.short_value)))

    def test_the_count_hands_over_the_len_of_the_source(self):
        out = self.render(self.tall_value, var_and_exp=self.var_and_exp)
        self.assertIn(exp_attr('len(x)'), _tiny_len(out))
        self.assertIn('draggable="true"', _tiny_len(out))

    def test_the_count_offers_nothing_without_a_source_expression(self):
        # Still shown -- the number is worth having even where there is no
        # access path to hand the editor.
        out = _tiny_len(self.render(self.tall_value))
        self.assertIn('14 chars', out)
        self.assertNotIn('snc-py-exps', out)

    def test_the_count_rides_the_search_box(self):
        out = self.render(self.tall_value)
        self.assertLess(out.index('search-div'), out.index('tiny-len'))

    def test_the_tab_says_how_many_lines_the_string_has(self):
        self.assertIn('5 lines', _tiny_len(self.render(self.tall_value)))

    def test_the_lines_are_counted_the_way_they_are_drawn(self):
        # A trailing newline draws an empty last line, and is counted as one.
        out = self.render("l1\nl2\nl3\nl4\nl5\n")
        self.assertIn('6 lines', _tiny_len(out))

    def test_the_line_count_hands_over_the_code_that_reads_it(self):
        out = _tiny_lens(self.render(self.tall_value,
                                     var_and_exp=self.var_and_exp))[0]
        self.assertIn('5 lines', out)
        self.assertIn(exp_attr(*self.LINE_EXPS), out)
        self.assertIn('draggable="true"', out)

    def test_the_line_count_offers_nothing_without_a_source_expression(self):
        out = _tiny_lens(self.render(self.tall_value))[0]
        self.assertIn('5 lines', out)
        self.assertNotIn('snc-py-exps', out)

    def test_the_lines_come_before_the_chars_they_are_made_of(self):
        lines, chars = _tiny_lens(self.render(self.tall_value))
        self.assertIn('5 lines', lines)
        self.assertIn('14 chars', chars)


class TestExpandToggle(unittest.TestCase):
    """Test the expand/collapse toggle for tall (>4 line) strings."""

    def setUp(self):
        # 5 lines -> more than 4, so the toggle applies.
        self.tall_value = "l1\nl2\nl3\nl4\nl5"
        self.short_value = "l1\nl2\nl3\nl4"  # exactly 4 lines
        self.var_and_exp = ('x', 'x')

    def test_expanded_defaults_false(self):
        """A freshly initialized model is collapsed."""
        model = init_model(self.tall_value)
        self.assertFalse(model.get('expanded', False))

    def test_toggle_flips_expanded(self):
        """ExpandToggle flips the expanded flag on and off."""
        model = init_model(self.tall_value)
        model, _ = update(make_expand_toggle_event(),
                          self.var_and_exp, model, self.tall_value)
        self.assertTrue(model['expanded'])
        model, _ = update(make_expand_toggle_event(),
                          self.var_and_exp, model, self.tall_value)
        self.assertFalse(model['expanded'])

    def test_toggle_rendered_when_more_than_4_lines(self):
        """The toggle is rendered for strings taller than 4 lines."""
        model = init_model(self.tall_value)
        html = visualize(self.tall_value, model, None, None)
        self.assertIn('expand-toggle', html)
        self.assertIn('ExpandToggle()', html)

    def test_toggle_not_rendered_when_4_or_fewer_lines(self):
        """The toggle is not rendered for strings 4 lines or shorter."""
        model = init_model(self.short_value)
        html = visualize(self.short_value, model, None, None)
        self.assertNotIn('expand-toggle', html)
        self.assertNotIn('ExpandToggle', html)

    def test_toggle_rendered_in_small_mode_for_tall_strings(self):
        """The toggle is offered in the non-focused small preview for tall strings,
        marked snc-unfocused-clickable so it works without pinning focus."""
        model = init_model(self.tall_value)
        html = visualize(self.tall_value, model, None, None, small=True)
        self.assertIn('expand-toggle', html)
        self.assertIn('ExpandToggle()', html)
        self.assertIn('snc-unfocused-clickable', html)

    def test_toggle_not_rendered_in_small_mode_for_short_strings(self):
        """Short strings aren't clipped, so no toggle in the small preview either."""
        model = init_model(self.short_value)
        html = visualize(self.short_value, model, None, None, small=True)
        self.assertNotIn('expand-toggle', html)
        self.assertNotIn('ExpandToggle', html)

    def test_expanded_class_present_when_expanded_in_small_mode(self):
        """When expanded, the small-mode container carries the expanded class."""
        model = init_model(self.tall_value)
        model['expanded'] = True
        html = visualize(self.tall_value, model, None, None, small=True)
        self.assertIn('expanded', html)

    def test_expanded_class_present_when_expanded(self):
        """When expanded, the container carries the expanded class."""
        model = init_model(self.tall_value)
        model['expanded'] = True
        html = visualize(self.tall_value, model, None, None)
        self.assertIn('literal-tool-selected expanded', html)

    def test_expanded_class_absent_when_collapsed(self):
        """When collapsed, the container does not carry the expanded class."""
        model = init_model(self.tall_value)
        html = visualize(self.tall_value, model, None, None)
        self.assertNotIn('literal-tool-selected expanded', html)

    def test_fresh_literal_selection_preserves_expanded(self):
        """Starting a fresh literal selection must not collapse an expanded pane.

        MouseDown's fresh-start path re-inits the model (to clear selection
        state) but must preserve UI chrome like expanded.
        """
        model = init_model(self.tall_value)
        model, _ = update(make_expand_toggle_event(),
                          self.var_and_exp, model, self.tall_value)
        self.assertTrue(model['expanded'])

        # Click index 1 ('l' of l1) to start a fresh literal selection.
        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                          self.var_and_exp, model, self.tall_value)
        self.assertTrue(model['expanded'],
                        'fresh MouseDown must preserve expanded=True')
        self.assertTrue(model['dragging'])

    def test_fresh_index_selection_preserves_expanded(self):
        """Starting a fresh index selection must not collapse an expanded pane."""
        model = init_model(self.tall_value)
        model, _ = update(make_expand_toggle_event(),
                          self.var_and_exp, model, self.tall_value)
        model['tool'] = 'index'
        self.assertTrue(model['expanded'])

        model, _ = update(make_mouse_down_event(1, legacy_index=False, top_half=True),
                          self.var_and_exp, model, self.tall_value)
        self.assertTrue(model['expanded'],
                        'index-mode MouseDown must preserve expanded=True')
        self.assertEqual(model['anchorType'], 'index')


class TestReplaceBoxInput(unittest.TestCase):
    """Test replace box input updates model."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['replace_visible'] = True
        self.var_and_exp = ('x', 'x')

    def test_typing_updates_replace_text(self):
        """Typing in replace box updates replace_text."""
        model, _ = update(make_replace_box_input_event("'world'"),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['replace_text'], "'world'")

    def test_clearing_replace_box(self):
        """Clearing the replace box sets replace_text to None."""
        self.model['replace_text'] = "'world'"
        model, _ = update(make_replace_box_input_event(''),
                          self.var_and_exp, self.model, self.value)
        self.assertIsNone(model['replace_text'])


class TestReplaceEnterCodeGen(unittest.TestCase):
    """Test Enter in replace mode generates Transform code (list comprehension).

    Enter in replace mode now produces a list comprehension that maps
    the replace expression over matches. The $ character translates to mtch.
    The old re.sub behavior is accessed via Cmd-R or the Replace button.
    """

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['replace_visible'] = True
        self.var_and_exp = ('x', 'x')

    def test_regex_replace_many_match(self):
        """Regex search + replacement produces list comprehension."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertEqual(expr, "['world' for mtch in re.finditer(r'hello', x, flags=re.M)]")

    def test_regex_replace_first_match(self):
        """Regex search + first-match generates next(...)."""
        self.model['search'] = r"r'hello'1"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertIn("next(", expr)
        self.assertIn("'world' for mtch in", expr)

    def test_regex_replace_case_insensitive(self):
        """Regex search + case-insensitive includes re.M|re.I."""
        self.model['search'] = r"r'hello'i"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.M|re.I", expr)
        self.assertIn("'world' for mtch in", expr)

    def test_string_replace_many_match_case_sensitive(self):
        """String search + replace produces list comprehension."""
        self.model['search'] = "'hello'"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertIn("re.escape('hello')", expr)
        self.assertIn("'world' for mtch in", expr)

    def test_string_replace_first_match_case_sensitive(self):
        """String search + replace, first-match uses next()."""
        self.model['search'] = "'hello'1"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("next(", expr)

    def test_string_replace_case_insensitive(self):
        """String search + replace, case-insensitive includes re.I."""
        self.model['search'] = "'hello'i"
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.I", expr)

    def test_expression_replace_many_match(self):
        """Expression search + replace produces list comprehension."""
        self.model['search'] = '`s`'
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertIn("re.escape(s)", expr)

    def test_dollar_translates_to_match_var(self):
        """$ in replace expression translates to mtch in list comprehension."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("mtch[0].upper() for mtch in", expr)

    def test_backtick_wrapped_expression(self):
        """Backtick-wrapped replace expression is unwrapped and $ translated."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = "`$[0].upper()`"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("mtch[0].upper() for mtch in", expr)

    def test_dollar_method_call(self):
        """$ with method call: $.group(1) -> mtch.group(1) in comprehension."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = "$.group(1)"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("mtch.group(1) for mtch in", expr)

    def test_arbitrary_code_accepted(self):
        """Any non-empty replace text is accepted as Python code."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = 'some_func($[0])'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("some_func(mtch[0]) for mtch in", expr)

    def test_empty_replace_text_does_nothing(self):
        """Enter with empty replace text in replace mode falls back to Get."""
        self.model['search'] = r"r'hello'"
        self.model['replace_text'] = None
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        # With no replace text, Enter does Get (list of matches)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIn("re.findall(", expr)

    def test_replace_visible_false_does_extract(self):
        """Enter with replace_visible=False generates extract code."""
        self.model['search'] = r"r'hello'"
        self.model['replace_visible'] = False
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertIn("re.findall(", expr)

    def test_double_quote_replace(self):
        """Double-quote replacement expression is preserved in comprehension."""
        self.model['search'] = "'hello'"
        self.model['replace_text'] = '"world"'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('"world" for mtch in', expr)

    def test_fstring_replace(self):
        """f-string replacement is preserved in comprehension."""
        self.model['search'] = "'hello'"
        self.model['replace_text'] = "f'hi {name}'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("f'hi {name}' for mtch in", expr)

    def test_no_search_does_nothing(self):
        """Enter in replace mode with no search pattern produces no commands."""
        self.model['search'] = None
        self.model['replace_text'] = "'world'"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])


class TestReplaceBoxVisualize(unittest.TestCase):
    """Test that the replace box renders correctly in visualize output."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    def test_disclosure_triangle_present(self):
        """Disclosure triangle is present in non-small visualize output."""
        model = init_model(self.value)
        html = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('ReplaceToggle()', html)

    def test_replace_box_hidden_by_default(self):
        """Replace input is not visible when replace_visible is False."""
        model = init_model(self.value)
        html = visualize(self.value, model, None, None, max_width=400)
        self.assertNotIn('ReplaceBoxInput', html)

    def test_replace_box_visible_when_toggled(self):
        """Replace input is visible when replace_visible is True."""
        model = init_model(self.value)
        model['replace_visible'] = True
        html = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('ReplaceBoxInput', html)

    def test_replace_input_has_target_class(self):
        """Replace input has the search-box-replace class used by snc-add-target."""
        model = init_model(self.value)
        model['replace_visible'] = True
        html = visualize(self.value, model, None, None, max_width=400)
        # The class is part of the search-box space-separated class list.
        self.assertIn('search-box-replace', html)

    def test_replace_box_preserves_value(self):
        """Replace input preserves the current replace_text value."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['replace_text'] = "'world'"
        html = visualize(self.value, model, None, None, max_width=400)
        self.assertIn("&#x27;world&#x27;", html)  # html.escape("'world'")

    def test_no_replace_box_in_small_mode(self):
        """Small mode doesn't render disclosure triangle or replace box."""
        model = init_model(self.value)
        model['replace_visible'] = True
        html = visualize(self.value, model, None, None, max_width=400, small=True)
        self.assertNotIn('ReplaceToggle', html)
        self.assertNotIn('ReplaceBoxInput', html)


# =============================================================================
# Action Button Test Helpers
# =============================================================================

def make_action_button_event(action: str, copy: bool = False) -> dict:
    """Create an ActionButtonClick event dict."""
    return {
        'pythonEventStr': repr(ActionButtonClick(action=action, copy=copy)),
        'eventJSON': {},
    }


# =============================================================================
# Handled Keys Updated Tests
# =============================================================================

class TestHandledKeysUpdated(unittest.TestCase):
    """Test that init_model includes new handled keys for action shortcuts."""

    def test_init_model_handled_keys(self):
        """handledKeys should include cmd Backspace, cmd r, and NOT plain Backspace."""
        model = init_model("test")
        keys = model['handledKeys']
        self.assertIn('cmd Backspace', keys)
        self.assertIn('cmd r', keys)
        self.assertNotIn('Backspace', keys)
        self.assertIn('Enter', keys)
        self.assertIn('Escape', keys)
        self.assertIn('cmd z', keys)
        self.assertIn('cmd shift z', keys)


# =============================================================================
# Action Button: Get/Transform Tests
# =============================================================================

class TestActionButtonGetTransform(unittest.TestCase):
    """Test Get/Transform action button and Enter key behavior."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_get_button_non_replace(self):
        """ActionButtonClick('find_or_map') with regex produces finditer."""
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_matches")
        self.assertEqual(expr, "list(re.finditer(r'hello', x, flags=re.M))")

    def test_get_button_non_replace_first_match(self):
        """With 1st mode, Get produces re.search."""
        self.model['search'] = r"r'hello'1"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_match")
        self.assertEqual(expr, "re.search(r'hello', x, flags=re.M)")

    def test_transform_button_replace_mode(self):
        """With replace_visible, find_or_map produces list comprehension."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertEqual(expr, "[mtch[0].upper() for mtch in re.finditer(r'hello', x, flags=re.M)]")

    def test_transform_button_first_match(self):
        """With 1st mode + replace, produces next(..., None)."""
        self.model['search'] = r"r'hello'1"
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertEqual(expr, "next((mtch[0].upper() for mtch in re.finditer(r'hello', x, flags=re.M)), None)")

    def test_enter_key_non_replace_unchanged(self):
        """Enter still produces Get in non-replace mode."""
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_strings")
        self.assertEqual(expr, "re.findall(r'hello', x, flags=re.M)")

    def test_enter_key_replace_mode_now_transforms(self):
        """Enter in replace mode now produces Transform (not re.sub)."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_transformed")
        self.assertIn("for mtch in re.finditer(", expr)
        self.assertNotIn("re.sub(", expr)

    def test_copy_find_or_map(self):
        """copy=True produces CopyToClipboard command."""
        _, commands = update(make_action_button_event('find_or_map', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertEqual(cmd.text, "list(re.finditer(r'hello', x, flags=re.M))")

    def test_find_or_map_string_search(self):
        """Get with string search uses re.escape."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.escape('hello')", expr)

    def test_find_or_map_no_search_does_nothing(self):
        """No search pattern produces no commands."""
        self.model['search'] = None
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])


# =============================================================================
# Action Button: Replace Tests
# =============================================================================

class TestActionButtonReplace(unittest.TestCase):
    """Test Replace action button and Cmd-R key."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.model['replace_visible'] = True
        self.model['replace_text'] = "'world'"
        self.var_and_exp = ('x', 'x')

    def test_replace_button(self):
        """Replace button produces re.sub with lambda."""
        _, commands = update(make_action_button_event('replace'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertEqual(expr, "re.sub(r'hello', lambda mtch: 'world', x, flags=re.M)")

    def test_replace_button_first_match(self):
        """Replace with first-match includes count=1."""
        self.model['search'] = r"r'hello'1"
        _, commands = update(make_action_button_event('replace'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "re.sub(r'hello', lambda mtch: 'world', x, count=1, flags=re.M)")

    def test_replace_button_not_in_replace_mode(self):
        """Replace button produces no replace (re.sub) code when not in replace mode."""
        self.model['replace_visible'] = False
        _, commands = update(make_action_button_event('replace'),
                            self.var_and_exp, self.model, self.value)
        self.assertFalse(any('re.sub' in _command_text(c) for c in commands))

    def test_cmd_r_key(self):
        """Cmd-R produces same as replace button."""
        _, commands = update(make_key_down_event('r', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertEqual(expr, "re.sub(r'hello', lambda mtch: 'world', x, flags=re.M)")

    def test_copy_replace(self):
        """copy=True produces CopyToClipboard with re.sub expr."""
        _, commands = update(make_action_button_event('replace', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("re.sub(", cmd.text)

    def test_replace_button_string_search(self):
        """Replace with string search uses re.escape."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('replace'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.sub(re.escape('hello')", expr)


# =============================================================================
# Action Button: Delete Tests
# =============================================================================

class TestActionButtonDelete(unittest.TestCase):
    """Test Delete action button and Cmd-Backspace key."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_delete_button(self):
        """Delete button produces re.sub with empty string."""
        _, commands = update(make_action_button_event('delete'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertEqual(expr, "re.sub(r'hello', '', x, flags=re.M)")

    def test_cmd_backspace_key(self):
        """Cmd-Backspace produces delete code."""
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x")
        self.assertEqual(expr, "re.sub(r'hello', '', x, flags=re.M)")

    def test_plain_backspace_no_longer_deletes(self):
        """Plain Backspace key no longer produces delete commands.

        It may still auto-insert the default find LOC (broad auto-link), but
        never a delete (re.sub) command.
        """
        _, commands = update(make_key_down_event('Backspace'),
                            self.var_and_exp, self.model, self.value)
        self.assertFalse(any('re.sub' in _command_text(c) for c in commands))

    def test_copy_delete(self):
        """copy=True produces CopyToClipboard with delete expr."""
        _, commands = update(make_action_button_event('delete', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("re.sub(", cmd.text)

    def test_delete_string_search(self):
        """Delete with string search, case-sensitive uses .replace()."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('delete'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "x.replace('hello', '')")

    # --- Disabled in Pick mode / when replace box is open -------------------
    # The Delete action mutates the source string. In Pick mode the user is
    # composing an extraction expression (via segment chips) and in
    # Replace-box-open mode they're composing a replacement; in both cases
    # firing Delete would discard the in-progress work, so the button is
    # dimmed and Cmd-Backspace is a no-op.

    def test_delete_button_dimmed_in_pick_mode(self):
        """Delete button is dimmed when Pick tool is active."""
        self.model['tool'] = 'pick'
        html_str = visualize(self.value, self.model, None, None)
        self.assertRegex(
            html_str,
            r"snc-mouse-down=\"ActionButtonClick\(action=&#x27;delete&#x27;,[^\"]*\)\" class=\"action-button dimmed\"",
        )

    def test_delete_button_dimmed_when_replace_visible(self):
        """Delete button is dimmed when the Replace box is open."""
        self.model['replace_visible'] = True
        html_str = visualize(self.value, self.model, None, None)
        self.assertRegex(
            html_str,
            r"snc-mouse-down=\"ActionButtonClick\(action=&#x27;delete&#x27;,[^\"]*\)\" class=\"action-button dimmed\"",
        )

    def test_delete_button_enabled_in_default_mode(self):
        """Delete button is NOT dimmed in literal mode with replace box closed."""
        # Defaults: tool=literal, replace_visible=False, search set in setUp.
        html_str = visualize(self.value, self.model, None, None)
        self.assertRegex(
            html_str,
            r"snc-mouse-down=\"ActionButtonClick\(action=&#x27;delete&#x27;,[^\"]*\)\" class=\"action-button\"",
        )

    def test_cmd_backspace_no_op_in_pick_mode(self):
        """Cmd-Backspace does NOT produce delete commands when Pick tool is active."""
        self.model['tool'] = 'pick'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertFalse(any('re.sub' in _command_text(c) for c in commands))

    def test_cmd_backspace_no_op_when_replace_visible(self):
        """Cmd-Backspace does NOT produce delete commands when Replace box is open."""
        self.model['replace_visible'] = True
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertFalse(any('re.sub' in _command_text(c) for c in commands))


# =============================================================================
# Action Button: Loop Tests
# =============================================================================

class TestActionButtonLoop(unittest.TestCase):
    """Test Loop action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_loop_non_replace(self):
        """Loop produces for loop with enumerate(re.finditer(...))."""
        _, commands = update(make_action_button_event('loop'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("for i, mtch in enumerate(re.finditer(r'hello', x, flags=re.M)):", expr)
        self.assertNotIn("pass", expr)

    def test_copy_loop_copies_runnable_code(self):
        """Copy hands the user a whole statement, so it keeps a body."""
        import ast
        from string_visualizer import CopyToClipboard
        _, commands = update(make_action_button_event('loop', copy=True),
                             self.var_and_exp, self.model, self.value)
        copies = [c for c in commands if isinstance(c, CopyToClipboard)]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].text.endswith('\n    pass'))
        ast.parse(copies[0].text)

    def test_hover_preview_of_loop_is_runnable(self):
        """The preview is copied and dragged into the file, so it needs a body."""
        import ast
        from string_visualizer import _preview_expr
        self.model['_source_expr'] = 'x'
        preview = _preview_expr(self.model, 'loop', None)
        self.assertTrue(preview.endswith('\n    pass'))
        ast.parse(preview)

    def test_loop_replace_mode(self):
        """Loop in replace mode iterates over transformed values."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('loop'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("for i, val in enumerate(", expr)
        self.assertIn("mtch[0].upper() for mtch in re.finditer(", expr)

    def test_loop_suggest_name_none(self):
        """Loop returns suggest_name=None for multiline code."""
        _, commands = update(make_action_button_event('loop'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsNone(commands[0][0])

    def test_copy_loop(self):
        """copy=True produces CopyToClipboard with loop code."""
        _, commands = update(make_action_button_event('loop', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("for i, mtch in enumerate(", cmd.text)


# =============================================================================
# Action Button: Match Strings Tests
# =============================================================================

class TestActionButtonMatchStrings(unittest.TestCase):
    """Test Match Strings action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_match_strings_all(self):
        """Match Strings produces re.findall(...)."""
        _, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(expr, "re.findall(r'hello', x, flags=re.M)")

    def test_match_strings_first(self):
        """Match Strings in first-match mode produces next(iter(re.findall(...)), None)."""
        self.model['search'] = r"r'hello'1"
        _, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(expr, "next(iter(re.findall(r'hello', x, flags=re.M)), None)")

    def test_match_strings_expr_search(self):
        """Match Strings with string search uses re.escape."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.findall(re.escape('hello')", expr)

    def test_match_strings_disabled_in_replace_mode(self):
        """Match Strings produces no match-strings command in replace mode.

        (has_replace=True prevents generation; any command is the find fallback.)
        """
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        model, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertNotEqual(model.get('linked_action'), 'match_strings')
        self.assertTrue(all('finditer' in _command_text(c) for c in commands))

    def test_match_strings_suggest_name(self):
        """Match Strings suggests x_strings."""
        _, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], 'x_strings')

    def test_copy_match_strings(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('match_strings', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("re.findall(", cmd.text)

    def test_match_strings_no_search_does_nothing(self):
        """No search pattern produces no commands."""
        self.model['search'] = None
        _, commands = update(make_action_button_event('match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])


# =============================================================================
# Action Button: Loop Match Strings Tests
# =============================================================================

class TestActionButtonLoopMatchStrings(unittest.TestCase):
    """Test Loop Match Strings action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_loop_match_strings(self):
        """Loop Match Strings produces for loop with enumerate(re.findall(...))."""
        _, commands = update(make_action_button_event('loop_match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("for i, s in enumerate(re.findall(r'hello', x, flags=re.M)):", expr)
        self.assertNotIn("pass", expr)

    def test_loop_match_strings_suggest_name_none(self):
        """Loop Match Strings returns suggest_name=None (statement)."""
        _, commands = update(make_action_button_event('loop_match_strings'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsNone(commands[0][0])

    def test_copy_loop_match_strings(self):
        """copy=True produces CopyToClipboard with loop code."""
        _, commands = update(make_action_button_event('loop_match_strings', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("for i, s in enumerate(re.findall(", cmd.text)


# =============================================================================
# Action Button: Any Tests
# =============================================================================

class TestActionButtonAny(unittest.TestCase):
    """Test Any action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_any_non_replace(self):
        """Any in non-replace mode produces bool(re.search(...))."""
        _, commands = update(make_action_button_event('any'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_any")
        self.assertEqual(expr, "bool(re.search(r'hello', x, flags=re.M))")

    def test_any_replace_mode(self):
        """Any in replace mode produces any(EXPR for mtch in ...)."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('any'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_any")
        self.assertEqual(expr, "any(mtch[0].upper() for mtch in re.finditer(r'hello', x, flags=re.M))")

    def test_copy_any(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('any', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)

    def test_any_string_search(self):
        """Any with string search."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('any'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.search(re.escape('hello')", expr)


# =============================================================================
# Action Button: All Tests
# =============================================================================

class TestActionButtonAll(unittest.TestCase):
    """Test All action button (replace mode only)."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_all_replace_mode(self):
        """All in replace mode produces all(EXPR for mtch in ...)."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('all'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_all")
        self.assertEqual(expr, "all(mtch[0].upper() for mtch in re.finditer(r'hello', x, flags=re.M))")

    def test_all_non_replace_returns_nothing(self):
        """All not in replace mode produces no all(...) command.

        (Any command emitted is the find fallback from broad auto-link.)
        """
        model, commands = update(make_action_button_event('all'),
                            self.var_and_exp, self.model, self.value)
        self.assertNotEqual(model.get('linked_action'), 'all')
        self.assertFalse(any(_command_text(c).startswith('all(') for c in commands))

    def test_copy_all(self):
        """copy=True produces CopyToClipboard."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('all', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)


# =============================================================================
# Action Button: If Any Tests
# =============================================================================

class TestActionButtonIfAny(unittest.TestCase):
    """Test If Any action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_if_any_non_replace(self):
        """If Any in non-replace produces the header if re.search(...):."""
        _, commands = update(make_action_button_event('if_any'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("if re.search(r'hello', x, flags=re.M):", expr)
        self.assertNotIn("pass", expr)

    def test_if_any_replace_mode(self):
        """If Any in replace mode produces the header if any(...):."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('if_any'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("if any(", expr)
        self.assertNotIn("pass", expr)

    def test_copy_if_any(self):
        """Copy If Any copies just the boolean expression."""
        _, commands = update(make_action_button_event('if_any', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        # Copy should be just the boolean expression, no "if" or "pass"
        self.assertNotIn("if ", cmd.text)
        self.assertNotIn("pass", cmd.text)


# =============================================================================
# Action Button: If All Tests
# =============================================================================

class TestActionButtonIfAll(unittest.TestCase):
    """Test If All action button (replace mode only)."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_if_all_replace_mode(self):
        """If All in replace mode produces the header if all(...):."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('if_all'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertIsNone(suggest_name)
        self.assertIn("if all(", expr)
        self.assertNotIn("pass", expr)

    def test_if_all_non_replace_returns_nothing(self):
        """If All not in replace mode produces no if-all command.

        (Any command emitted is the find fallback from broad auto-link.)
        """
        model, commands = update(make_action_button_event('if_all'),
                            self.var_and_exp, self.model, self.value)
        self.assertNotEqual(model.get('linked_action'), 'if_all')
        self.assertFalse(any('if all(' in _command_text(c) for c in commands))

    def test_copy_if_all(self):
        """Copy If All copies just the all(...) expression."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('if_all', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertNotIn("if ", cmd.text)
        self.assertNotIn("pass", cmd.text)


# =============================================================================
# Action Button: Count Tests
# =============================================================================

class TestActionButtonCount(unittest.TestCase):
    """Test Count action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_count_non_replace(self):
        """Count produces sum(1 for _ in re.finditer(...))."""
        _, commands = update(make_action_button_event('count'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_count")
        self.assertEqual(expr, "sum(1 for _ in re.finditer(r'hello', x, flags=re.M))")

    def test_count_replace_mode(self):
        """Count in replace mode filters by replace expr truthiness."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$[0].upper()"
        _, commands = update(make_action_button_event('count'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_count")
        self.assertEqual(expr, "sum(1 for mtch in re.finditer(r'hello', x, flags=re.M) if mtch[0].upper())")

    def test_copy_count(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('count', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)

    def test_count_string_search(self):
        """Count with string search."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('count'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.escape('hello')", expr)


# =============================================================================
# Action Button: Filter Tests
# =============================================================================

class TestActionButtonFilter(unittest.TestCase):
    """Test Filter action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'\w+'"
        self.model['replace_visible'] = True
        self.model['replace_text'] = "len($[0]) > 4"
        self.var_and_exp = ('x', 'x')

    def test_filter_generates_list_comprehension_with_predicate(self):
        """Filter produces [mtch for mtch in re.finditer(...) if EXPR]."""
        _, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_filtered")
        self.assertEqual(expr, r"[mtch for mtch in re.finditer(r'\w+', x, flags=re.M) if len(mtch[0]) > 4]")

    def test_filter_not_in_replace_mode_returns_none(self):
        """Filter without replace mode produces no filter command.

        (Any command emitted is the find fallback from broad auto-link.)
        """
        self.model['replace_visible'] = False
        self.model['replace_text'] = None
        model, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value)
        self.assertNotEqual(model.get('linked_action'), 'filter')
        self.assertTrue(all('findall' in _command_text(c) for c in commands))

    def test_copy_filter(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('filter', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertIn('for mtch in', commands[0].text)

    def test_filter_string_search(self):
        """Filter with string search."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.escape('hello')", expr)
        self.assertIn("if len(mtch[0]) > 4", expr)

    def test_filter_suggest_name_no_var(self):
        """Filter without var name uses 'result_filtered'."""
        self.var_and_exp = (None, "f('hello world')")
        _, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, _ = commands[0][:2]
        self.assertEqual(suggest_name, "result_filtered")

    def test_filter_first_match(self):
        """Filter with first-match uses next(..., None)."""
        self.model['search'] = r"r'\w+'1"
        _, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("next(", expr)
        self.assertIn("if len(mtch[0]) > 4", expr)


# =============================================================================
# Action Button: Find Indices Tests
# =============================================================================

class TestActionButtonFindIndices(unittest.TestCase):
    """Test Find Indices action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'\w+'"
        self.var_and_exp = ('x', 'x')

    def test_find_indices_no_replace_generates_start_list(self):
        """Find Indices without replace produces [mtch.start() for mtch in ...]."""
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_indices")
        self.assertEqual(expr, r"[mtch.start() for mtch in re.finditer(r'\w+', x, flags=re.M)]")

    def test_find_indices_with_replace_generates_filtered_start_list(self):
        """Find Indices with replace produces [mtch.start() for mtch in ... if EXPR]."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "len($[0]) > 4"
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_indices")
        self.assertEqual(expr, r"[mtch.start() for mtch in re.finditer(r'\w+', x, flags=re.M) if len(mtch[0]) > 4]")

    def test_find_indices_first_match_no_replace(self):
        """Find Indices with first-match uses next(..., None)."""
        self.model['search'] = r"r'\w+'1"
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("next(", expr)
        self.assertIn("mtch.start()", expr)

    def test_find_indices_first_match_with_replace(self):
        """Find Indices with first-match and replace uses next(..., None) with if."""
        self.model['search'] = r"r'\w+'1"
        self.model['replace_visible'] = True
        self.model['replace_text'] = "len($[0]) > 4"
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("next(", expr)
        self.assertIn("mtch.start()", expr)
        self.assertIn("if len(mtch[0]) > 4", expr)

    def test_copy_find_indices(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('find_indices', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertIn('mtch.start()', commands[0].text)

    def test_find_indices_string_search(self):
        """Find Indices with string search."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("re.escape('hello')", expr)
        self.assertIn("mtch.start()", expr)

    def test_find_indices_suggest_name_no_var(self):
        """Find Indices without var name uses 'result_indices'."""
        self.var_and_exp = (None, "f('hello world')")
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, _ = commands[0][:2]
        self.assertEqual(suggest_name, "result_indices")


# =============================================================================
# Action Button: Split Tests
# =============================================================================

class TestActionButtonSplit(unittest.TestCase):
    """Test Split action button."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = r"r'hello'"
        self.var_and_exp = ('x', 'x')

    def test_split_regex(self):
        """Split with regex produces re.split(...)."""
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_parts")
        self.assertEqual(expr, "re.split(r'hello', x, flags=re.M)")

    def test_split_first_match(self):
        """Split with first-match uses maxsplit=1."""
        self.model['search'] = r"r'hello'1"
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "re.split(r'hello', x, maxsplit=1, flags=re.M)")

    def test_split_string_search(self):
        """Split with string search uses str.split()."""
        self.model['search'] = "'hello'"
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "x.split('hello')")

    def test_split_string_search_first_match(self):
        """Split with string search and first-match uses maxsplit=1."""
        self.model['search'] = "'hello'1"
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "x.split('hello', 1)")

    def test_split_string_search_case_insensitive(self):
        """Split with string search + case-insensitive uses re.split."""
        self.model['search'] = "'hello'i"
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "re.split(re.escape('hello'), x, flags=re.I)")

    def test_split_case_insensitive(self):
        """Split with regex + case-insensitive."""
        self.model['search'] = r"r'hello'i"
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "re.split(r'hello', x, flags=re.M|re.I)")

    def test_copy_split(self):
        """copy=True produces CopyToClipboard with split expr."""
        _, commands = update(make_action_button_event('split', copy=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)
        self.assertIn("split", cmd.text)

    def test_split_suggest_name_no_var(self):
        """Split without var name uses 'result_parts'."""
        self.var_and_exp = (None, "f('hello world')")
        _, commands = update(make_action_button_event('split'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        suggest_name, _ = commands[0][:2]
        self.assertEqual(suggest_name, "result_parts")


class TestCountViaGrammar(unittest.TestCase):
    """Count preview should use the same grammar-generated expression as the Count button."""

    eis = staticmethod(lambda _c: eval(_c))

    def test_regex_with_predicate(self):
        """Predicate filters: only count matches where predicate is truthy."""
        model = {'search': r"r'\w+'", 'replace_visible': True, 'replace_text': 'len($[0]) > 3'}
        # "hi" (len 2, False), "world" (len 5, True), "hello" (len 5, True)
        self.assertEqual(_eval_count_via_grammar(r"r'\w+'", "hi world hello", model, self.eis), 2)

    def test_regex_without_predicate(self):
        """Without replace, count all matches."""
        model = {'search': r"r'\w+'"}
        self.assertEqual(_eval_count_via_grammar(r"r'\w+'", "hi world hello", model, self.eis), 3)

    def test_string_search_with_predicate(self):
        """String search with predicate filters by truthy results."""
        model = {'search': "'l'", 'replace_visible': True, 'replace_text': '$.start() < 5'}
        # 'l' at positions 2, 3, 9 in "hello world"; start < 5: True, True, False
        self.assertEqual(_eval_count_via_grammar("'l'", "hello world", model, self.eis), 2)

    def test_case_insensitive_with_predicate(self):
        """Case-insensitive search + predicate."""
        model = {'search': r"r'hello'i", 'replace_visible': True, 'replace_text': '$.start() == 0'}
        # "Hello hello HELLO" → matches at 0, 6, 12; start==0 is only first
        self.assertEqual(_eval_count_via_grammar(r"r'hello'i", "Hello hello HELLO", model, self.eis), 1)

    def test_generates_same_code_as_button(self):
        """The count expression should be identical to what generate_action('count') produces."""
        from string_visualizer_grammar import generate_action
        from string_visualizer import replace_dollars_in_py_exp
        model = {'search': r"r'\w+'", 'replace_visible': True, 'replace_text': 'len($[0]) > 3'}
        ctx = {
            'source_expr': '_snc_v',
            'is_first': False, 'is_ci': False, 'is_expr': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': '\\w+',
            'replace_visible': True, 'replace_text': 'len($[0]) > 3',
            'replace_expr': replace_dollars_in_py_exp('len($[0]) > 3', ['mtch']),
        }
        result = generate_action('count', ctx)
        self.assertIsNotNone(result)
        _, grammar_code = result
        _snc_v = "hi world hello"
        expected = eval(grammar_code)
        actual = _eval_count_via_grammar(r"r'\w+'", _snc_v, model, self.eis)
        self.assertEqual(actual, expected)

    def test_no_search_returns_zero(self):
        self.assertEqual(_eval_count_via_grammar(None, "hello", {}, self.eis), 0)

    def test_no_value_returns_zero(self):
        self.assertEqual(_eval_count_via_grammar(r"r'x'", "", {'search': r"r'x'"}, self.eis), 0)


# =============================================================================
# Action Button Rendering Tests
# =============================================================================

class TestActionButtonRendering(unittest.TestCase):
    """Test that action buttons render correctly in visualize output.

    The action-button row was rewritten in commit 11c2fbf1185:
      - All buttons live in a `<span class="action-button">` (with the
        ``dimmed`` class added when disabled — no more inline opacity).
      - Find/Map/Substrs/Idxs/Replace/Delete/Filter/Split labels are now
        the same regardless of first-match mode (the action handler treats
        first-mode differently at click time).
      - Loop and Any/All are hover dropdowns with always-rendered panels
        (no openDropdown state needed to read the labels).
      - Count shows ``Count: N`` instead of ``Count (N)``.
    """

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    # ---- Helpers --------------------------------------------------------------

    def _action_btn_class(self, html_output, action):
        """Return the class attribute of the top-level action button for `action`,
        or None if the button is not present."""
        import re as _re
        m = _re.search(
            rf'<span snc-mouse-down="ActionButtonClick\(action=&#x27;{action}&#x27;,'
            rf' copy=False\)" class="([^"]+)"',
            html_output,
        )
        return m.group(1) if m else None

    def _dropdown_option_class(self, html_output, action):
        """Return the class attribute of the predicate/loop dropdown row for
        `action`, or None if the row is not present."""
        import re as _re
        m = _re.search(
            rf'<div class="([^"]+)"><span snc-mouse-down="ActionButtonClick\(action=&#x27;{action}&#x27;,'
            rf' copy=False\)"',
            html_output,
        )
        return m.group(1) if m else None

    # ---- Presence tests ------------------------------------------------------

    def test_buttons_present_non_small(self):
        """Action buttons render in non-small mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('ActionButtonClick', html_output)
        self.assertIn('find_or_map', html_output)
        self.assertIn('delete', html_output)

    def test_buttons_absent_small(self):
        """No action buttons in small mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400, small=True)
        self.assertNotIn('ActionButtonClick', html_output)

    # ---- Labels --------------------------------------------------------------

    def test_get_label_changes_to_map_in_replace_mode(self):
        """find_or_map label is 'Match Objects' until the replace row is open, then 'Map Matches'."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_get = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Match Objects', html_get)
        self.assertNotIn('Map Matches', html_get)

        model['replace_visible'] = True
        model['replace_text'] = "'world'"
        html_transform = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Map Matches', html_transform)
        self.assertNotIn('Match Objects', html_transform)

    def test_button_labels(self):
        """Standard set of labels is present regardless of first-match mode."""
        for search in (r"r'hello'", r"r'hello'1"):
            model = init_model(self.value)
            model['search'] = search
            html_output = visualize(self.value, model, None, None, max_width=400)
            for label in ('Match Objects', 'Substrs', 'Indexes', 'Loop',
                          'Any/All', 'Delete', 'Split', 'Replace', 'Filter'):
                self.assertIn(label, html_output, f"label {label!r} missing for search={search!r}")

    # ---- Dimmed / enabled state for top-level buttons -------------------------

    def _assert_dimmed(self, html_output, action, msg=None):
        cls = self._action_btn_class(html_output, action)
        self.assertIsNotNone(cls, f"{action!r} button should be present")
        self.assertIn('dimmed', cls.split(), msg or f"{action!r} should be dimmed")

    def _assert_not_dimmed(self, html_output, action, msg=None):
        cls = self._action_btn_class(html_output, action)
        self.assertIsNotNone(cls, f"{action!r} button should be present")
        self.assertNotIn('dimmed', cls.split(), msg or f"{action!r} should be enabled")

    def test_match_strings_disabled_in_replace_mode(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "'world'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_dimmed(html_output, 'match_strings')

    def test_match_strings_enabled_without_replace(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'match_strings')

    def test_filter_button_present(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Filter', html_output)
        self.assertIn("action=&#x27;filter&#x27;", html_output)

    def test_filter_button_grayed_when_no_replace(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_dimmed(html_output, 'filter')

    def test_filter_button_enabled_with_replace(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "len($[0]) > 3"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'filter')

    def test_find_indices_button_present(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn("action=&#x27;find_indices&#x27;", html_output)
        self.assertIn('Indexes', html_output)

    def test_find_indices_button_enabled_without_replace(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'find_indices')

    def test_replace_button_grayed_when_no_replace(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn("action=&#x27;replace&#x27;", html_output)
        self._assert_dimmed(html_output, 'replace')

    def test_split_enabled_when_replace_visible(self):
        """Split now stays enabled regardless of the replace box state."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'split')

    def test_split_enabled_when_replace_hidden(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = False
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'split')

    # ---- Count ---------------------------------------------------------------

    def test_count_shows_match_count(self):
        model = init_model(self.value)
        model['search'] = r"r'l'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        # 'hello world' has 3 'l' characters
        self.assertIn('Count: 3', html_output)

    def test_count_uses_transform_result_when_predicate(self):
        """Count shows truthy transform results when transform/replace is present."""
        model = init_model("hello world hello")
        model['search'] = r"r'\w+'"
        model['replace_visible'] = True
        model['replace_text'] = "len($[0]) > 4"
        html_output = visualize("hello world hello", model, None, eval, max_width=400)
        self.assertIn('Count: 3', html_output)

    def test_count_uses_transform_result_filters_falsy(self):
        """Count with predicate transform only counts truthy results."""
        model = init_model("hi world hello")
        model['search'] = r"r'\w+'"
        model['replace_visible'] = True
        model['replace_text'] = "len($[0]) > 3"
        html_output = visualize("hi world hello", model, None, eval, max_width=400)
        self.assertIn('Count: 2', html_output)

    def test_count_without_transform_uses_match_count(self):
        """Count without transform still shows total match count."""
        model = init_model("hi world hello")
        model['search'] = r"r'\w+'"
        html_output = visualize("hi world hello", model, None, eval, max_width=400)
        self.assertIn('Count: 3', html_output)

    def test_count_enabled_in_first_match_mode(self):
        """Count is enabled even in first-match mode (was previously disabled)."""
        model = init_model(self.value)
        model['search'] = r"r'l'1"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'count')

    def test_count_enabled_in_all_mode(self):
        model = init_model(self.value)
        model['search'] = r"r'l'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self._assert_not_dimmed(html_output, 'count')

    # ---- Loop dropdown -------------------------------------------------------

    def test_loop_dropdown_renders_options(self):
        """The Loop hover-dropdown panel always renders both options."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn("action=&#x27;loop_match_strings&#x27;", html_output)
        self.assertIn("action=&#x27;loop&#x27;", html_output)
        self.assertIn('Over matched strings', html_output)
        self.assertIn('Over match objects', html_output)

    def test_loop_disabled_in_first_match_mode(self):
        """Loop trigger is dimmed in first-match mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'1"
        html_output = visualize(self.value, model, None, None, max_width=400)
        import re as _re
        # The Loop trigger is the snc-dropdown-trigger wrapper containing the Loop label.
        m = _re.search(r'<span class="snc-dropdown-trigger ([^"]*)"><span class="action-button">[^<]*<svg[^<]*(?:<[^>]*>[^<]*)*?</svg>[^<]*<span class="text">Loop', html_output)
        self.assertIsNotNone(m, "Loop trigger should be present")
        self.assertIn('dimmed', m.group(1).split())

    def test_loop_enabled_in_all_mode(self):
        """Loop trigger is enabled in all-match mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        import re as _re
        m = _re.search(r'<span class="snc-dropdown-trigger ?([^"]*)"><span [^>]*class="action-button"[^>]*>[^<]*<svg[^<]*(?:<[^>]*>[^<]*)*?</svg>[^<]*<span class="text">Loop', html_output)
        self.assertIsNotNone(m, "Loop trigger should be present")
        self.assertNotIn('dimmed', m.group(1).split())

    # ---- A click on a menu button fires its first live row ------------------

    def _menu_button_event(self, html_output, label):
        """The mousedown event on the hover-menu button labeled *label*, or None
        if the button carries none."""
        import re as _re
        label_pos = html_output.find(f'<span class="text">{label}</span>')
        self.assertGreater(label_pos, -1, f"{label} button should be present")
        trigger_pos = html_output.rfind('<span class="snc-dropdown-trigger', 0, label_pos)
        m = _re.search(r'<span ([^>]*)class="action-button"', html_output[trigger_pos:label_pos])
        self.assertIsNotNone(m, f"{label} trigger should hold an action-button")
        attrs = _re.search(r'snc-mouse-down="([^"]*)"', m.group(1))
        return _html.unescape(attrs.group(1)) if attrs else None

    def test_loop_button_click_loops_over_matched_strings(self):
        """With every Loop row live, a click on the button itself takes the first."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertEqual(self._menu_button_event(html_output, 'Loop'),
                         "ActionButtonClick(action='loop_match_strings', copy=False)")

    def test_loop_button_click_skips_a_dimmed_first_row(self):
        """A replace predicate dims 'Over matched strings', so the click falls
        through to 'Over mapped'."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertEqual(self._menu_button_event(html_output, 'Loop'),
                         "ActionButtonClick(action='loop', copy=False)")

    def test_loop_button_does_nothing_when_every_row_is_dimmed(self):
        """First-match mode dims both rows: the button carries no event, and the
        trigger is dimmed so it doesn't light up under the mouse."""
        model = init_model(self.value)
        model['search'] = r"r'hello'1"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIsNone(self._menu_button_event(html_output, 'Loop'))

    def test_any_all_button_click_is_any(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertEqual(self._menu_button_event(html_output, 'Any/All'),
                         "ActionButtonClick(action='any', copy=False)")

    def test_any_all_button_does_nothing_without_a_search(self):
        model = init_model(self.value)
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIsNone(self._menu_button_event(html_output, 'Any/All'))
        import re as _re
        m = _re.search(r'<span class="snc-dropdown-trigger ([^"]*)"><span [^>]*class="action-button"[^>]*>[^<]*<svg[^<]*(?:<[^>]*>[^<]*)*?</svg>[^<]*<span class="text">Any/All', html_output)
        self.assertIsNotNone(m, "Any/All trigger should be present")
        self.assertIn('dimmed', m.group(1).split())

    def test_menu_button_hands_over_the_code_its_click_writes(self):
        """The button previews the row it stands in for, like any other button."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['_source_expr'] = 'x'
        html_output = visualize(self.value, model, None, None, max_width=400)
        import re as _re
        m = _re.search(r'<span snc-mouse-down="ActionButtonClick\(action=&#x27;any&#x27;, copy=False\)"'
                       r' class="action-button" data-action-expr=', html_output)
        self.assertIsNotNone(m)

    def test_loop_match_strings_disabled_in_replace_mode(self):
        """The 'Over matched strings' loop row is dimmed when a replace/map/filter predicate is set.

        loop_match_strings generates `for i, s in enumerate(re.findall(...))` which ignores the
        replace_expr, so it doesn't make sense alongside a replace/map/filter predicate (mirrors
        the same restriction on the top-level Substrs button)."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'loop_match_strings')
        self.assertIsNotNone(cls, "Over matched strings dropdown row should be present")
        self.assertIn('dimmed', cls.split())

    def test_loop_match_strings_enabled_without_replace(self):
        """The 'Over matched strings' loop row is enabled when no replace predicate is set."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'loop_match_strings')
        self.assertIsNotNone(cls, "Over matched strings dropdown row should be present")
        self.assertNotIn('dimmed', cls.split())

    def test_loop_match_strings_enabled_when_replace_visible_but_empty(self):
        """The replace box being visible (but empty) doesn't constitute a predicate."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = ""
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'loop_match_strings')
        self.assertIsNotNone(cls, "Over matched strings dropdown row should be present")
        self.assertNotIn('dimmed', cls.split())

    def test_loop_match_objects_enabled_in_replace_mode(self):
        """The 'Over mapped' loop row (the 'loop' action) stays enabled in replace mode (it uses the predicate)."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'loop')
        self.assertIsNotNone(cls, "loop dropdown row should be present")
        self.assertNotIn('dimmed', cls.split())

    # ---- Loop 'Over mapped' / 'Over match objects' label switching ----------

    def test_loop_label_says_over_match_objects_without_replace(self):
        """When the replace box is hidden, the 'loop' row label is 'Over match objects'."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Over match objects', html_output)
        self.assertNotIn('Over mapped', html_output)

    def test_loop_label_says_over_mapped_in_replace_mode(self):
        """When the replace box is visible (map mode), the 'loop' row label is 'Over mapped'.

        Mirrors the find_or_map button label which switches from 'Match Objs' to 'Map Matches'
        once the replace box opens, since the same `loop` action then loops over mapped values."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Over mapped', html_output)
        self.assertNotIn('Over match objects', html_output)

    def test_loop_label_says_over_mapped_with_replace_text(self):
        """The 'Over mapped' label also applies when there's a non-empty replace expression."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Over mapped', html_output)
        self.assertNotIn('Over match objects', html_output)

    # ---- Any/All predicate dropdown -----------------------------------------

    def test_predicate_dropdown_grayed_when_no_search(self):
        """Any/All trigger is dimmed when there is no search pattern."""
        model = init_model(self.value)
        html_output = visualize(self.value, model, None, None, max_width=400)
        import re as _re
        m = _re.search(r'<span class="snc-dropdown-trigger ([^"]*)"><span class="action-button">[^<]*<svg[^<]*(?:<[^>]*>[^<]*)*?</svg>\s*<span class="text">Any/All', html_output)
        self.assertIsNotNone(m, "Any/All trigger should be present")
        self.assertIn('dimmed', m.group(1).split())

    def test_predicate_dropdown_not_grayed_with_search(self):
        """Any/All trigger is enabled when search is present."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        import re as _re
        m = _re.search(r'<span class="snc-dropdown-trigger ?([^"]*)"><span [^>]*class="action-button"[^>]*>[^<]*<svg[^<]*(?:<[^>]*>[^<]*)*?</svg>\s*<span class="text">Any/All', html_output)
        self.assertIsNotNone(m, "Any/All trigger should be present")
        self.assertNotIn('dimmed', m.group(1).split())

    def test_any_shows_true_when_match_exists(self):
        """Any label shows (True) when search pattern matches.

        The True/False predicate value is wrapped in a `snc-code` span so it renders
        in the code font even though the surrounding 'Any (...)' label is UI-font."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Any (<span class="snc-code">True</span>)', html_output)

    def test_any_shows_false_when_no_match(self):
        model = init_model(self.value)
        model['search'] = r"r'xyz'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Any (<span class="snc-code">False</span>)', html_output)

    def test_if_any_shows_true_when_match_exists(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('If Any (<span class="snc-code">True</span>)', html_output)

    def test_if_any_shows_false_when_no_match(self):
        model = init_model(self.value)
        model['search'] = r"r'xyz'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('If Any (<span class="snc-code">False</span>)', html_output)

    def test_all_shows_preview_in_replace_mode(self):
        """All label shows (True)/(False) in replace mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('All (<span class="snc-code">True</span>)', html_output)

    def test_if_all_shows_preview_in_replace_mode(self):
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('If All (<span class="snc-code">True</span>)', html_output)

    def test_all_no_preview_when_disabled(self):
        """All has no (True/False) suffix when not in replace mode (it's disabled)."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertNotIn('All (<span class="snc-code">True</span>)', html_output)
        self.assertNotIn('All (<span class="snc-code">False</span>)', html_output)

    def test_all_disabled_in_first_match_mode(self):
        """All option in the predicate panel is dimmed in first-match mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'1"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'all')
        self.assertIsNotNone(cls, "All dropdown row should be present")
        self.assertIn('dimmed', cls.split())

    def test_if_all_disabled_in_first_match_mode(self):
        """If All option in the predicate panel is dimmed in first-match mode."""
        model = init_model(self.value)
        model['search'] = r"r'hello'1"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, model, None, None, max_width=400)
        cls = self._dropdown_option_class(html_output, 'if_all')
        self.assertIsNotNone(cls, "If All dropdown row should be present")
        self.assertIn('dimmed', cls.split())

    # ---- Dropdown panel font: 'code' class on regex panels -----------------
    #
    # The default `.snc-dropdown-panel` font is the UI font so non-code labels
    # (Repetition title, Loop options, Any/All) render in the same font as the
    # surrounding action buttons. Panels whose contents are regex/code (the
    # fuzzy-pattern picker and repetition picker) opt into the monospace code
    # font by adding a `code` class on the panel element.

    def test_loop_panel_does_not_have_code_class(self):
        """Loop dropdown panel uses default UI font (no 'code' class)."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Over matched strings', html_output)
        # Hover-menu panels (loop, predicate) align left and use data-hover-menu.
        # A 'code' class on either would appear right before that attribute pair.
        self.assertNotIn('code" snc-dropdown-align="left" data-hover-menu', html_output)

    def test_predicate_panel_does_not_have_code_class(self):
        """Predicate (Any/All) dropdown panel uses default UI font (no 'code' class).

        The True/False *values* inside are wrapped in `snc-code` spans for code-font
        rendering; the surrounding label text and panel itself are UI font."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertIn('Any (<span class="snc-code">', html_output)
        self.assertNotIn('code" snc-dropdown-align="left" data-hover-menu', html_output)

    def test_fuzzy_pattern_panel_has_code_class(self):
        """Fuzzy pattern dropdown panel uses code font (has 'code' class)."""
        model = init_model("hello world")
        model['search'] = r"r'(.*)'"
        model['openDropdown'] = {'id': 'fuzzy-pattern-0-0', 'segmentIndex': 0, 'matchIndex': 0}
        html_output = visualize("hello world", model, None, None, max_width=400)
        self.assertIn('snc-dropdown-panel left code"', html_output)

    def test_repetition_panel_has_code_class(self):
        """Repetition dropdown panel uses code font (has 'code' class) for regex options like *, ?, {n,m}.

        The 'Repetition' category-name title still renders in UI font (a CSS rule
        overrides .snc-dropdown-category-name back to UI font even inside .code panels)."""
        model = init_model("hello world")
        model['search'] = r"r'(.*)'"
        model['openDropdown'] = {'id': 'repetition-0-0', 'segmentIndex': 0, 'matchIndex': 0}
        html_output = visualize("hello world", model, None, None, max_width=400)
        self.assertIn('snc-dropdown-panel categorized right code"', html_output)
        self.assertIn('snc-dropdown-category-name">Repetition</div>', html_output)

    # ---- Update behaviour ----------------------------------------------------

    def test_dropdown_closes_on_action_button_click(self):
        """Predicate dropdown closes when an action button is clicked."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        model['replace_visible'] = True
        model['replace_text'] = "$[0].upper()"
        model['openDropdown'] = {'id': 'action-predicate'}
        event = make_action_button_event('any')
        new_model, _ = update(event, ('x', 'x'), model, self.value)
        self.assertIsNone(new_model.get('openDropdown'))


# =============================================================================
# Index / Slice Search Action Bar Tests
# =============================================================================

class TestIndexSearchActionBar(unittest.TestCase):
    """For an index or slice search there are no match objects or matched
    substrings, so most actions have nothing to generate (the grammar gates
    them on is_index/is_slice being False). Buttons whose action can't
    generate must render dimmed instead of silently no-oping, and the
    find_or_map button -- which reaches into the string directly -- is
    labeled 'Slice' rather than 'Match Objects'."""

    # Shared markup helpers (defined on TestActionButtonRendering).
    _action_btn_class = TestActionButtonRendering._action_btn_class
    _dropdown_option_class = TestActionButtonRendering._dropdown_option_class
    _assert_dimmed = TestActionButtonRendering._assert_dimmed
    _assert_not_dimmed = TestActionButtonRendering._assert_not_dimmed

    def setUp(self):
        self.value = "hello world"

    def _html(self, search, **model_updates):
        model = init_model(self.value)
        model['search'] = search
        model.update(model_updates)
        return visualize(self.value, model, None, None, max_width=400)

    # ---- find_or_map label ---------------------------------------------------

    def test_slice_label_for_index_search(self):
        html_output = self._html('5')
        self.assertIn('<span class="text">Slice</span>', html_output)
        self.assertNotIn('Match Objects', html_output)

    def test_slice_label_for_slice_search(self):
        html_output = self._html('2:7')
        self.assertIn('<span class="text">Slice</span>', html_output)
        self.assertNotIn('Match Objects', html_output)

    def test_map_slice_label_with_replace(self):
        html_output = self._html('2:7', replace_visible=True,
                                 replace_text="$.upper()")
        self.assertIn('<span class="text">Map Slice</span>', html_output)
        self.assertNotIn('Map Matches', html_output)

    def test_regex_search_keeps_match_objects_label(self):
        html_output = self._html(r"r'hello'")
        self.assertIn('Match Objects', html_output)
        self.assertNotIn('Slice<', html_output)

    # ---- Dimming of ungeneratable actions ------------------------------------

    def test_substrs_dimmed_for_index_search(self):
        self._assert_dimmed(self._html('5'), 'match_strings')

    def test_substrs_dimmed_for_slice_search(self):
        self._assert_dimmed(self._html('2:7'), 'match_strings')

    def test_indexes_dimmed_for_index_search(self):
        self._assert_dimmed(self._html('5'), 'find_indices')

    def test_count_dimmed_for_index_search(self):
        self._assert_dimmed(self._html('5'), 'count')

    def test_split_dimmed_for_index_search(self):
        self._assert_dimmed(self._html('5'), 'split')

    def test_loop_rows_dimmed_for_index_search(self):
        html_output = self._html('5')
        for action in ('loop', 'loop_match_strings'):
            cls = self._dropdown_option_class(html_output, action)
            self.assertIsNotNone(cls, f"{action!r} row should be present")
            self.assertIn('dimmed', cls.split(), f"{action!r} should be dimmed")

    def test_predicate_rows_dimmed_for_index_search(self):
        html_output = self._html('5')
        for action in ('any', 'if_any'):
            cls = self._dropdown_option_class(html_output, action)
            self.assertIsNotNone(cls, f"{action!r} row should be present")
            self.assertIn('dimmed', cls.split(), f"{action!r} should be dimmed")

    # ---- Actions that do work on an index search stay enabled ----------------

    def test_slice_button_enabled_for_index_search(self):
        self._assert_not_dimmed(self._html('5'), 'find_or_map')

    def test_delete_enabled_for_index_search(self):
        self._assert_not_dimmed(self._html('5'), 'delete')

    def test_regex_search_buttons_stay_enabled(self):
        html_output = self._html(r"r'hello'")
        for action in ('count', 'find_or_map', 'match_strings',
                       'find_indices', 'split'):
            self._assert_not_dimmed(html_output, action)


class TestIndexSearchActionClicks(unittest.TestCase):
    """Clicking an action that can't generate for an index search must leave
    the linked action alone: a dead click that wedged linked_action onto an
    ungeneratable action would silently stop all further linked updates."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')
        self.model = init_model(self.value)
        self.model['search'] = '5'
        # Link via the Slice (find_or_map) button on an index search.
        self.model, first = update(make_action_button_event('find_or_map'),
                                   self.var_and_exp, self.model, self.value)
        self.assertEqual(self.model['linked_action'], 'find_or_map')
        self.assertEqual(first[0][1], 'x[5]')

    def test_substrs_click_emits_nothing(self):
        _, commands = update(make_action_button_event('match_strings'),
                             self.var_and_exp, self.model, self.value)
        self.assertEqual(commands, [])

    def test_substrs_click_keeps_linked_action(self):
        model, _ = update(make_action_button_event('match_strings'),
                          self.var_and_exp, self.model, self.value)
        self.assertEqual(model['linked_action'], 'find_or_map')

    def test_search_edit_after_dead_click_still_updates_linked_line(self):
        model, _ = update(make_action_button_event('match_strings'),
                          self.var_and_exp, self.model, self.value)
        model, commands = update(make_search_box_input_event('6'),
                                 self.var_and_exp, model, self.value)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].expression, 'x[6]')


# =============================================================================
# Transform Preview Tests
# =============================================================================

class TestTransformPreview(unittest.TestCase):
    """Test the live preview below the Map/replace/filter matches input."""

    def setUp(self):
        self.value = "hello world hello"
        self.model = init_model(self.value)
        self.model['replace_visible'] = True
        self.model['search'] = r"r'hello'"

    def preview(self, html_output):
        """The match-object preview alone.

        Scoped rather than asked of the whole render: the Replace box's own
        legend names `$[0]` too, that being the one thing a user writing against
        a match object has to be told, so a search for it across the markup
        would find the legend and answer about the wrong thing.
        """
        m = re.search(r'<div class="match-object-preview">.*?</div>',
                      html_output, re.DOTALL)
        return m.group(0) if m else ''

    def test_no_preview_when_replace_hidden(self):
        """No preview labels when replace_visible is False."""
        model = init_model(self.value)
        model['search'] = r"r'hello'"
        html_output = visualize(self.value, model, None, None, max_width=400)
        self.assertNotIn('$[0]', html_output)
        self.assertNotIn('$.start()', html_output)

    def test_no_preview_when_no_search(self):
        """No preview when there is no search pattern."""
        self.model['search'] = None
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertNotIn('$[0]', self.preview(html_output))

    def test_no_preview_when_no_matches(self):
        """No preview when search matches nothing."""
        self.model['search'] = r"r'zzzzz'"
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertNotIn('$[0]', self.preview(html_output))

    def test_row1_shows_match_labels(self):
        """Row 1 displays $[0], $.start(), $.end() labels."""
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertIn('$[0]', html_output)
        self.assertIn('$.start()', html_output)
        self.assertIn('$.end()', html_output)

    def test_row1_shows_first_match_values(self):
        """Row 1 shows repr values from the first match of /hello/ in 'hello world hello'."""
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        # repr('hello') = "'hello'" -> HTML-escaped: &#x27;hello&#x27;
        import html as html_mod
        self.assertIn(html_mod.escape(repr('hello')), html_output)

    def test_no_row2_without_replace_text(self):
        """No transform-result content when replace_text is empty."""
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertIn('$[0]', html_output)
        self.assertNotIn('transform-preview-content', html_output)

    def test_row2_shows_transform_result(self):
        """The transform-preview shows the evaluated result for a valid transform expression."""
        self.model['replace_text'] = "$[0].upper()"
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertIn('transform-preview-content', html_output)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('HELLO')), html_output)

    def test_row2_shows_runtime_error(self):
        """The transform-preview shows the error message when the expression raises."""
        self.model['replace_text'] = "1/0"
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertIn('transform-preview-content', html_output)
        self.assertIn('division by zero', html_output)

    def test_row2_shows_syntax_error(self):
        """The transform-preview shows an error for an unparseable expression."""
        self.model['replace_text'] = "$[0] +"
        html_output = visualize(self.value, self.model, None, None, max_width=400)
        self.assertIn('transform-preview-content', html_output)

    def test_truncates_long_repr(self):
        """repr values longer than 30 chars are truncated with ellipsis."""
        long_value = "abcdefghijklmnopqrstuvwxyz_extra"
        model = init_model(long_value)
        model['replace_visible'] = True
        # Use \w+ so the search box itself doesn't echo the long value back
        # into the HTML and trip the substring assertion below.
        model['search'] = r"r'\w+'"
        html_output = visualize(long_value, model, None, None, max_width=400)
        import html as html_mod
        full_repr = html_mod.escape(repr(long_value))
        self.assertNotIn(full_repr, html_output)
        self.assertIn('…', html_output)

    def test_no_preview_in_small_mode(self):
        """Preview is not rendered in small mode."""
        html_output = visualize(self.value, self.model, None, None, max_width=400, small=True)
        self.assertNotIn('$[0]', html_output)

    def test_helper_returns_empty_when_no_conditions(self):
        """_render_transform_preview returns '' when replace not visible."""
        model = init_model(self.value)
        eis = lambda _c: eval(_c)
        result = _render_transform_preview(model, self.value, eis)
        self.assertEqual(result, '')

    def test_helper_returns_empty_no_search(self):
        """_render_transform_preview returns '' when no search pattern."""
        model = init_model(self.value)
        model['replace_visible'] = True
        eis = lambda _c: eval(_c)
        result = _render_transform_preview(model, self.value, eis)
        self.assertEqual(result, '')

    def test_helper_returns_empty_no_matches(self):
        """_render_transform_preview returns '' when search has no matches."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'zzzzz'"
        eis = lambda _c: eval(_c)
        result = _render_transform_preview(model, self.value, eis)
        self.assertEqual(result, '')

    def test_helper_returns_html_with_matches(self):
        """_render_match_object_preview returns the chip row when there are matches."""
        eis = lambda _c: eval(_c)
        result = _render_match_object_preview(self.model, self.value, eis)
        self.assertIn('$[0]', result)
        self.assertIn('$.start()', result)
        self.assertIn('$.end()', result)

    def test_row2_resolves_user_scope_variables(self):
        """Transform preview can reference variables from the user's scope."""
        user_locals = {'x': 'REPLACED'}
        eis = lambda _c, _locals=user_locals: eval(_c, {**_locals, '__builtins__': __builtins__})
        self.model['replace_text'] = '`x`'
        html_output = visualize(self.value, self.model, None, eis, max_width=400)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('REPLACED')), html_output)


class TestTransformPreviewCaptureGroups(unittest.TestCase):
    """Test that capture groups show $[1], $[2] etc. in the match-object preview."""

    def setUp(self):
        self.value = "hello world"
        self.eis = lambda _c: eval(_c)

    def test_groups_shown_when_regex_has_groups(self):
        """Match-object preview shows $[1], $[2] etc. when the regex has capture groups."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)(.*)(world)'"
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('$[1]', result)
        self.assertIn('$[2]', result)
        self.assertIn('$[3]', result)

    def test_groups_shown_with_c_flag(self):
        """Match-object preview shows $[1] etc. when 'c' flag makes groups explicit."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)(.*)(world)'c"
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('$[1]', result)
        self.assertIn('$[2]', result)
        self.assertIn('$[3]', result)

    def test_no_groups_for_ungrouped_regex(self):
        """Match-object preview does not show $[1] when regex has no capture groups."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'hello'"
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('$[0]', result)
        self.assertNotIn('$[1]', result)

    def test_group_values_are_correct(self):
        """The group preview values should match actual captured text."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)( )(world)'"
        result = _render_match_object_preview(model, self.value, self.eis)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('hello')), result)
        self.assertIn(html_mod.escape(repr(' ')), result)
        self.assertIn(html_mod.escape(repr('world')), result)

    def test_preview_spans_have_add_at_cursor(self):
        """All preview expression spans should have snc-add-at-cursor and snc-add-target."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)(.*)(world)'"
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('snc-add-at-cursor="$[0]"', result)
        self.assertIn('snc-add-at-cursor="$[1]"', result)
        self.assertIn('snc-add-at-cursor="$.start()"', result)
        self.assertIn('snc-add-at-cursor="$.end()"', result)
        self.assertIn('snc-add-target=".search-box-replace"', result)

    def test_no_groups_still_has_add_at_cursor(self):
        """Preview spans have snc-add-at-cursor even without capture groups."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'hello'"
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('snc-add-at-cursor="$[0]"', result)
        self.assertIn('snc-add-at-cursor="$.start()"', result)

    def test_index_slice_preview_has_add_at_cursor(self):
        """Index/slice preview $ span has snc-add-at-cursor."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = '0'
        result = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('snc-add-at-cursor="$"', result)

    def test_transform_preview_uses_capture_groups(self):
        """Transform $[2] should resolve correctly when groups exist."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)( )(world)'"
        model['replace_text'] = '$[2]'
        result = _render_transform_preview(model, self.value, self.eis)
        import html as html_mod
        self.assertIn(html_mod.escape(repr(' ')), result)
        self.assertNotIn('no such group', result)

    def test_transform_preview_group_expr_no_error(self):
        """Transform using $[1].upper() should not error when groups exist."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = r"r'(hello)( )(world)'"
        model['replace_text'] = '$[1].upper()'
        result = _render_transform_preview(model, self.value, self.eis)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('HELLO')), result)
        self.assertNotIn('no such group', result)


# =============================================================================
# Index and Slice Search Tests
# =============================================================================

class TestIsSliceSearch(unittest.TestCase):
    """Test is_slice_search detects slice expressions."""

    def test_start_only(self):
        self.assertTrue(is_slice_search('5:'))

    def test_stop_only(self):
        self.assertTrue(is_slice_search(':5'))

    def test_start_and_stop(self):
        self.assertTrue(is_slice_search('5:10'))

    def test_variable_start(self):
        self.assertTrue(is_slice_search('x:10'))

    def test_variable_both(self):
        self.assertTrue(is_slice_search('x:y'))

    def test_expression_start(self):
        self.assertTrue(is_slice_search('len(s)-1:'))

    def test_bare_text_no_colon(self):
        self.assertFalse(is_slice_search('hello'))

    def test_number_no_colon(self):
        self.assertFalse(is_slice_search('5'))

    def test_string_literal_with_colon(self):
        self.assertFalse(is_slice_search("'a:b'"))

    def test_regex_with_colon(self):
        self.assertFalse(is_slice_search(r"r'a:b'"))

    def test_dict_literal_not_slice(self):
        self.assertFalse(is_slice_search("{'a':1}"))

    def test_lambda_not_slice(self):
        self.assertFalse(is_slice_search('lambda x: x'))

    def test_none(self):
        self.assertFalse(is_slice_search(None))

    def test_empty(self):
        self.assertFalse(is_slice_search(''))

    def test_colon_only(self):
        self.assertTrue(is_slice_search(':'))

    def test_negative_start(self):
        self.assertTrue(is_slice_search('-3:'))


class TestParseSliceParts(unittest.TestCase):
    """Test parse_slice_parts returns correct (left, right) tuples."""

    def test_start_only(self):
        self.assertEqual(parse_slice_parts('5:'), ('5', ''))

    def test_stop_only(self):
        self.assertEqual(parse_slice_parts(':5'), ('', '5'))

    def test_start_and_stop(self):
        self.assertEqual(parse_slice_parts('5:10'), ('5', '10'))

    def test_variable_start(self):
        self.assertEqual(parse_slice_parts('x:10'), ('x', '10'))

    def test_expression_start(self):
        self.assertEqual(parse_slice_parts('len(s)-1:'), ('len(s)-1', ''))

    def test_colon_only(self):
        self.assertEqual(parse_slice_parts(':'), ('', ''))

    def test_negative_start(self):
        self.assertEqual(parse_slice_parts('-3:'), ('-3', ''))

    def test_none_input(self):
        self.assertIsNone(parse_slice_parts(None))

    def test_empty_input(self):
        self.assertIsNone(parse_slice_parts(''))

    def test_no_colon(self):
        self.assertIsNone(parse_slice_parts('hello'))

    def test_dict_literal(self):
        self.assertIsNone(parse_slice_parts("{'a':1}"))

    def test_lambda(self):
        self.assertIsNone(parse_slice_parts('lambda x: x'))


class TestSliceNotExpression(unittest.TestCase):
    """Slices should parse as 'slice' kind, not 'expr'."""

    def test_slice_is_not_expression(self):
        self.assertEqual(parse_search_term('5:10')[0], 'slice')

    def test_slice_start_only_is_not_expression(self):
        self.assertEqual(parse_search_term('5:')[0], 'slice')

    def test_slice_stop_only_is_not_expression(self):
        self.assertEqual(parse_search_term(':5')[0], 'slice')


class TestIndexSearchHighlighting(unittest.TestCase):
    """Test highlighting when an expression evaluates to an int (index search)."""

    def test_literal_int_one_highlight(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting('5', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)

    def test_literal_int_correct_position(self):
        """Index 0 on 'hello' highlights the 'h' at internal index 2."""
        value = "hello"
        highlights = parse_regex_for_highlighting('0', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)
        start, end = highlights[0][0], highlights[0][1]
        self.assertEqual(start, _legacy_internal_index(2))
        self.assertEqual(end, _legacy_internal_index(3))

    def test_negative_index(self):
        value = "hello"
        highlights = parse_regex_for_highlighting('-1', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)
        start, end = highlights[0][0], highlights[0][1]
        self.assertEqual(start, _legacy_internal_index(6))
        self.assertEqual(end, _legacy_internal_index(7))

    def test_out_of_bounds_no_highlights(self):
        value = "hello"
        highlights = parse_regex_for_highlighting('100', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 0)

    def test_variable_eval_to_int(self):
        user_locals = {'idx': 2}
        eis = lambda c, _l=user_locals: eval(c, {**_l, '__builtins__': __builtins__})
        value = "hello"
        highlights = parse_regex_for_highlighting('idx', value, eval_in_scope=eis)
        self.assertEqual(len(highlights), 1)
        # idx=2 selects 'l' (third char), at internal index 3 in the new layout.
        self.assertEqual(highlights[0][0], _legacy_internal_index(4))
        self.assertEqual(highlights[0][1], _legacy_internal_index(5))

    def test_segment_index_is_none(self):
        """Index search highlights should be display-only (segment_index=None)."""
        value = "hello"
        highlights = parse_regex_for_highlighting('0', value, eval_in_scope=lambda c: eval(c))
        self.assertIsNone(highlights[0][5])


class TestSliceSearchHighlighting(unittest.TestCase):
    """Test highlighting for slice search expressions."""

    def test_start_only(self):
        """'5:' on 'hello world' highlights from index 5 to end."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('5:', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)

    def test_stop_only(self):
        """':5' highlights first 5 characters."""
        value = "hello world"
        highlights = parse_regex_for_highlighting(':5', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)

    def test_start_and_stop(self):
        """'5:10' highlights characters 5 through 9."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('5:10', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)

    def test_variable_in_slice(self):
        user_locals = {'x': 2}
        eis = lambda c, _l=user_locals: eval(c, {**_l, '__builtins__': __builtins__})
        value = "hello world"
        highlights = parse_regex_for_highlighting('x:5', value, eval_in_scope=eis)
        self.assertEqual(len(highlights), 1)

    def test_empty_slice_no_highlights(self):
        """A slice that yields an empty string produces no highlights."""
        value = "hello"
        highlights = parse_regex_for_highlighting('3:3', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 0)

    def test_segment_index_is_zero(self):
        """Slice highlights now have segment_index=0 (interactive) so the
        visualizer can render left/right resize handles like literal segments."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('0:5', value, eval_in_scope=lambda c: eval(c))
        if highlights:
            self.assertEqual(highlights[0][5], 0)

    def test_stop_only_internal_positions(self):
        """':3' on 'hello' highlights internal indices for the first 3 chars."""
        value = "hello"
        highlights = parse_regex_for_highlighting(':3', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)
        # In the new layout, visible chars start at internal index 1 (no \A anchor).
        self.assertEqual(highlights[0][0], _legacy_internal_index(2))
        self.assertEqual(highlights[0][1], _legacy_internal_index(5))

    def test_negative_start(self):
        """'-3:' on 'hello' highlights last 3 chars."""
        value = "hello"
        highlights = parse_regex_for_highlighting('-3:', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1)


class TestIndexSliceTransformPreview(unittest.TestCase):
    """Test transform preview for index/slice: $ is the matched string, not a match object."""

    def setUp(self):
        self.value = "hello world"
        self.eis = lambda c: eval(c)

    def test_index_preview_no_start_end(self):
        """Index search preview should NOT show $.start() or $.end()."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = '0'
        html_output = _render_transform_preview(model, self.value, self.eis)
        self.assertNotIn('$.start()', html_output)
        self.assertNotIn('$.end()', html_output)
        self.assertNotIn('$[0]', html_output)

    def test_index_preview_shows_dollar(self):
        """Index search match-object preview should show $ => the matched character."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = '0'
        html_output = _render_match_object_preview(model, self.value, self.eis)
        self.assertIn('$', html_output)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('h')), html_output)

    def test_index_transform_works_on_string(self):
        """$.upper() should work because $ is a string, not a match object."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = '0'
        model['replace_text'] = '$.upper()'
        html_output = _render_transform_preview(model, self.value, self.eis)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('H')), html_output)

    def test_slice_preview_no_start_end(self):
        """Slice search preview should NOT show $.start() or $.end()."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = ':5'
        html_output = _render_transform_preview(model, self.value, self.eis)
        self.assertNotIn('$.start()', html_output)
        self.assertNotIn('$.end()', html_output)
        self.assertNotIn('$[0]', html_output)

    def test_slice_transform_works_on_string(self):
        """$.upper() on slice ':5' should yield 'HELLO'."""
        model = init_model(self.value)
        model['replace_visible'] = True
        model['search'] = ':5'
        model['replace_text'] = '$.upper()'
        html_output = _render_transform_preview(model, self.value, self.eis)
        import html as html_mod
        self.assertIn(html_mod.escape(repr('HELLO')), html_output)


class TestIndexSliceToggles(unittest.TestCase):
    """Test that index/slice searches force the first-match toggle into the active state."""

    def _first_match_toggle_state(self, html_output):
        """Return 'active' / 'inactive' for the FirstMatchToggle button in HTML."""
        import re as _re
        m = _re.search(r'<span class="search-button (\w+)"[^>]*snc-mouse-down="FirstMatchToggle', html_output)
        return m.group(1) if m else None

    def test_index_search_shows_first_match_highlighted(self):
        """Even without the /1 flag, index search renders the first-match toggle as active."""
        value = "hello world"
        model = init_model(value)
        model['search'] = '0'
        html_output = visualize(value, model, None, lambda c: eval(c), max_width=400)
        self.assertEqual(self._first_match_toggle_state(html_output), 'active')

    def test_slice_search_shows_first_match_highlighted(self):
        """Slice search renders the first-match toggle as active."""
        value = "hello world"
        model = init_model(value)
        model['search'] = ':5'
        html_output = visualize(value, model, None, lambda c: eval(c), max_width=400)
        self.assertEqual(self._first_match_toggle_state(html_output), 'active')


class TestIndexSliceCodeGen(unittest.TestCase):
    """Test Enter code generation for index/slice searches."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_index_enter_generates_indexing(self):
        """Enter with index search '5' generates x[5]."""
        self.model['search'] = '5'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[5]', expr)

    def test_slice_enter_generates_slicing(self):
        """Enter with slice search '5:10' generates x[5:10]."""
        self.model['search'] = '5:10'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[5:10]', expr)

    def test_slice_start_only_enter(self):
        """Enter with slice '5:' generates x[5:]."""
        self.model['search'] = '5:'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[5:]', expr)

    def test_slice_stop_only_enter(self):
        """Enter with slice ':5' generates x[:5]."""
        self.model['search'] = ':5'
        _, commands = update(make_key_down_event('Enter'),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[:5]', expr)

    def test_index_delete_generates_concatenation(self):
        """Backspace with index search '5' generates x[:5] + x[6:]."""
        self.model['search'] = '5'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[:5]', expr)
        self.assertIn('x[5 + 1:]', expr)

    def test_slice_delete_generates_concatenation(self):
        """Backspace with slice '5:10' generates x[:5] + x[10:]."""
        self.model['search'] = '5:10'
        _, commands = update(make_key_down_event('Backspace', meta_key=True),
                            self.var_and_exp, self.model, self.value)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn('x[:5]', expr)
        self.assertIn('x[10:]', expr)


class TestSourceExpr(unittest.TestCase):
    """The access path the render names the value by.

    It comes from the model's _source_expr key, set from the var_and_exp tuple
    -- not from the source_expr parameter the AST rewriter passes, which holds
    internal temp names like _snc_temp_1. The length readout is built from it
    (see TestTinyLen); nothing on a short string is.
    """

    def test_var_name_from_an_assignment(self):
        model = init_model("hello", var_and_exp=('str1', 'str1'))
        self.assertEqual(model['_source_expr'], 'str1')
        self.assertNotIn('_snc_temp', visualize("hello", model, None, None))

    def test_a_bare_expression_names_itself(self):
        """For a bare expression line, _source_expr is the whole expression."""
        model = init_model("hello", var_and_exp=(None, 'my_func()'))
        self.assertEqual(model['_source_expr'], 'my_func()')

    def test_a_short_string_hands_over_only_its_counts(self):
        """The characters are not handles; the counts on the search box's tab
        are the only code a string offers of its own."""
        model = init_model("hello", var_and_exp=('str1', 'str1'))
        out = visualize("hello", model, None, None)
        self.assertEqual(len(re.findall(r'snc-py-exps=', out)), 2)
        self.assertNotIn('snc-py-exps', out.replace(_tiny_len(out), ''))

# =============================================================================
# DSL Grammar Tests via Action Rule
# =============================================================================

class _ActionTestBase(unittest.TestCase):
    """Base class for all DSL Action grammar tests."""

    def setUp(self):
        from string_visualizer_grammar import STRING_VIZ_GRAMMAR, generate_action, parse_generated_code
        from bidirectional_dsl import generate, parse
        self.grammar = STRING_VIZ_GRAMMAR
        self.raw_generate = generate
        self.raw_parse = parse
        self.generate_action = generate_action
        self.parse_generated_code = parse_generated_code

    def _gen(self, action, ctx):
        gen_ctx = {k: v for k, v in ctx.items() if v is not None}
        gen_ctx['action'] = action
        gen_ctx.setdefault('has_replace', bool(ctx.get('replace_expr')))
        if ctx.get('is_slice'):
            gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
            gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
        return self.raw_generate(self.grammar, self.grammar['Action'], gen_ctx)

    # Context keys that the grammar encodes in generated code and should
    # survive a parse roundtrip (metadata like var_name, suggest_base are not
    # encoded in the output and are correctly absent from parsed results).
    _GRAMMAR_KEYS = frozenset({
        'action', 'is_expr', 'is_ci', 'is_first', 'is_index', 'is_slice',
        'has_replace', 'regex_pattern', 'source_expr', 'expr',
        'replace_expr', 'index_expr', 'slice_start', 'slice_stop',
        'has_slice_start', 'has_slice_stop',
    })

    def _roundtrip(self, action, ctx):
        result = self._gen(action, ctx)
        self.assertIsNotNone(result, f"Generation failed for {action}")
        code = result[0]
        parsed = self.raw_parse(self.grammar, self.grammar['Action'], code)
        self.assertIsNotNone(parsed, f"Failed to parse: {code}")
        self.assertEqual(parsed.get('action'), action,
                         f"Parsed action {parsed.get('action')!r} != {action!r} for: {code}")
        gen_ctx = {k: v for k, v in ctx.items() if v is not None}
        gen_ctx['action'] = action
        gen_ctx.setdefault('has_replace', bool(ctx.get('replace_expr')))
        for key in self._GRAMMAR_KEYS:
            if key not in gen_ctx:
                continue
            expected = gen_ctx[key]
            actual = parsed.get(key)
            # False/None in input is equivalent to absent in parsed output
            # (the DSL only sets keys when rules that gate on them match)
            if expected is False and actual is None:
                continue
            if key in parsed:
                self.assertEqual(actual, expected,
                                 f"Parsed {key}={actual!r} != {expected!r} for: {code}")
        regen = self._gen(action, parsed)
        self.assertIsNotNone(regen, f"Regeneration failed from parsed context")
        self.assertEqual(regen[0], code, f"Roundtrip mismatch")

    def _parse_action(self, code):
        return self.raw_parse(self.grammar, self.grammar['Action'], code)


class TestDSLGetTransformNonReplace(_ActionTestBase):
    """Test find_or_map action in non-replace mode (Get variants) via Action rule."""

    ACTION = 'find_or_map'

    def _g(self, ctx):
        return self._gen(self.ACTION, {**ctx, 'has_replace': False})

    def test_get_list_regex(self):
        ctx = {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        }
        result = self._g(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "list(re.finditer(r'hello', x, flags=re.M))")

    def test_get_list_regex_ci(self):
        result = self._g({
            'is_expr': False, 'is_first': False, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "list(re.finditer(r'hello', x, flags=re.M|re.I))")

    def test_get_first_regex(self):
        result = self._g({
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.search(r'hello', x, flags=re.M)")

    def test_get_list_expr(self):
        result = self._g({
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "list(re.finditer(re.escape('hello'), x))")

    def test_get_first_expr_ci(self):
        result = self._g({
            'is_expr': True, 'is_first': True, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.search(re.escape('hello'), x, flags=re.I)")

    def test_get_index(self):
        result = self._g({'is_index': True, 'is_slice': False, 'index_expr': '5', 'source_expr': 'x'})
        self.assertEqual(result[0], "x[5]")

    def test_get_slice(self):
        result = self._g({'is_index': False, 'is_slice': True, 'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x'})
        self.assertEqual(result[0], "x[5:10]")

    def test_roundtrip_get_list_regex(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })

    def test_roundtrip_get_first_expr(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'expr': "'hello'", 'source_expr': 'x',
        })

    def test_roundtrip_get_index(self):
        self._roundtrip(self.ACTION, {
            'is_index': True, 'is_slice': False, 'has_replace': False,
            'index_expr': '5', 'source_expr': 'x',
        })

    def test_roundtrip_get_slice(self):
        self._roundtrip(self.ACTION, {
            'is_index': False, 'is_slice': True, 'has_replace': False,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
        })

    def test_roundtrip_get_list_regex_paren_expr(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': '(my_func())',
        })

    def test_roundtrip_get_index_paren_expr(self):
        self._roundtrip(self.ACTION, {
            'is_index': True, 'is_slice': False, 'has_replace': False,
            'index_expr': '5', 'source_expr': '(my_func())',
        })

    def test_parse_known_get_list_regex(self):
        parsed = self._parse_action("list(re.finditer(r'hello', x, flags=re.M))")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertEqual(parsed['regex_pattern'], 'hello')
        self.assertFalse(parsed.get('has_replace', False))

    def test_parse_known_get_first_regex(self):
        parsed = self._parse_action("re.search(r'hello', x, flags=re.M)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('is_first'))

    def test_parse_known_index(self):
        parsed = self._parse_action("x[5]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('is_index'))

    def test_parse_known_slice(self):
        parsed = self._parse_action("x[5:10]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('is_slice'))


class TestDSLGetTransformReplace(_ActionTestBase):
    """Test find_or_map action in replace mode (Transform variants) via Action rule."""

    ACTION = 'find_or_map'

    def _g(self, ctx):
        return self._gen(self.ACTION, {**ctx, 'has_replace': True})

    def test_transform_list_regex(self):
        result = self._g({
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().upper()",
        })
        self.assertEqual(result[0], "[mtch.group().upper() for mtch in re.finditer(r'hello', x, flags=re.M)]")

    def test_transform_first_regex(self):
        result = self._g({
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().upper()",
        })
        self.assertEqual(result[0], "next((mtch.group().upper() for mtch in re.finditer(r'hello', x, flags=re.M)), None)")

    def test_transform_list_expr(self):
        result = self._g({
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "['world' for mtch in re.finditer(re.escape('hello'), x)]")

    def test_transform_index(self):
        result = self._g({
            'is_index': True, 'is_slice': False,
            'index_expr': '5', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })
        self.assertEqual(result[0], "(lambda mtch: mtch.upper())(x[5])")

    def test_transform_slice(self):
        result = self._g({
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })
        self.assertEqual(result[0], "(lambda mtch: mtch.upper())(x[5:10])")

    def test_roundtrip_transform_list_regex(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': r'\d+', 'source_expr': 'data',
            'replace_expr': "int(mtch.group())",
        })

    def test_roundtrip_transform_first_expr_ci(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': True, 'is_ci': True,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })

    def test_roundtrip_transform_index(self):
        self._roundtrip(self.ACTION, {
            'is_index': True, 'is_slice': False, 'has_replace': True,
            'index_expr': '5', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })

    def test_roundtrip_transform_slice(self):
        self._roundtrip(self.ACTION, {
            'is_index': False, 'is_slice': True, 'has_replace': True,
            'slice_start': '2', 'slice_stop': '7', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })

    def test_parse_known_transform_list(self):
        parsed = self._parse_action("[mtch.group().upper() for mtch in re.finditer(r'hello', x, flags=re.M)]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('has_replace'))

    def test_no_replace_expr_falls_to_get(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "list(re.finditer(r'hello', x, flags=re.M))")


class TestDSLDeleteAction(_ActionTestBase):
    """Test delete action via Action rule."""

    ACTION = 'delete'

    def _g(self, ctx):
        return self._gen(self.ACTION, ctx)

    def test_delete_regex_all(self):
        result = self._g({
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.sub(r'hello', '', x, flags=re.M)")

    def test_delete_regex_first(self):
        result = self._g({
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.sub(r'hello', '', x, count=1, flags=re.M)")

    def test_delete_expr_all(self):
        result = self._g({
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x.replace('hello', '')")

    def test_delete_expr_first(self):
        result = self._g({
            'is_expr': True, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x.replace('hello', '', 1)")

    def test_delete_index(self):
        result = self._g({'is_index': True, 'is_slice': False, 'index_expr': '5', 'source_expr': 'x'})
        self.assertEqual(result[0], "x[:5] + x[5 + 1:]")

    def test_delete_slice_both(self):
        result = self._g({
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x[:5] + x[10:]")

    def test_delete_slice_empty_start(self):
        result = self._g({
            'is_index': False, 'is_slice': True,
            'slice_start': '', 'slice_stop': '10', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "'' + x[10:]")

    def test_delete_slice_empty_stop(self):
        result = self._g({
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x[:5] + ''")

    def test_roundtrip_delete_regex(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_delete_expr_ci(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })

    def test_roundtrip_delete_index(self):
        self._roundtrip(self.ACTION, {
            'is_index': True, 'is_slice': False,
            'index_expr': '5', 'source_expr': 'x',
        })

    def test_roundtrip_delete_slice(self):
        self._roundtrip(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
        })

    def test_roundtrip_delete_slice_empty_start(self):
        self._roundtrip(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '', 'slice_stop': '10', 'source_expr': 'x',
        })

    def test_parse_known_delete_regex(self):
        parsed = self._parse_action("re.sub(r'hello', '', x, flags=re.M)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'delete')

    def test_parse_known_delete_expr(self):
        parsed = self._parse_action("x.replace('hello', '')")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'delete')

    def test_parse_known_delete_slice(self):
        parsed = self._parse_action("x[:5] + x[10:]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'delete')
        self.assertTrue(parsed.get('is_slice'))

    def test_delete_regex_all_with_predicate(self):
        result = self._g({
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\w+', 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "re.sub(r'\\w+', lambda mtch: '' if (len(mtch[0]) > 3) else mtch[0], x, flags=re.M)")

    def test_delete_regex_first_with_predicate(self):
        result = self._g({
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\w+', 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "next((x[:mtch.start()] + x[mtch.end():] for mtch in re.finditer(r'\\w+', x, flags=re.M) if len(mtch[0]) > 3), x)")

    def test_delete_regex_first_with_predicate_ci(self):
        result = self._g({
            'is_expr': False, 'is_first': True, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\w+', 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "next((x[:mtch.start()] + x[mtch.end():] for mtch in re.finditer(r'\\w+', x, flags=re.M|re.I) if len(mtch[0]) > 3), x)")

    def test_delete_expr_all_with_predicate(self):
        result = self._g({
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "re.sub(re.escape('hello'), lambda mtch: '' if (len(mtch[0]) > 3) else mtch[0], x)")

    def test_delete_expr_first_with_predicate(self):
        result = self._g({
            'is_expr': True, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "next((x[:mtch.start()] + x[mtch.end():] for mtch in re.finditer(re.escape('hello'), x) if len(mtch[0]) > 3), x)")

    def test_delete_expr_ci_all_with_predicate(self):
        result = self._g({
            'is_expr': True, 'is_first': False, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "re.sub(re.escape('hello'), lambda mtch: '' if (len(mtch[0]) > 3) else mtch[0], x, flags=re.I)")

    def test_delete_expr_ci_first_with_predicate(self):
        result = self._g({
            'is_expr': True, 'is_first': True, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_visible': True, 'replace_expr': 'len(mtch[0]) > 3',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "next((x[:mtch.start()] + x[mtch.end():] for mtch in re.finditer(re.escape('hello'), x, flags=re.I) if len(mtch[0]) > 3), x)")

    def test_delete_without_predicate_unchanged(self):
        """Existing delete behavior is preserved when no replace is active."""
        result = self._g({
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.sub(r'hello', '', x, flags=re.M)")

class TestDSLLoopAction(_ActionTestBase):
    """Test loop action via Action rule."""

    ACTION = 'loop'

    def test_loop_non_replace(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "for i, mtch in enumerate(re.finditer(r'hello', x, flags=re.M)):")

    def test_loop_replace(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().upper()",
        })
        self.assertEqual(result[0], "for i, val in enumerate(mtch.group().upper() for mtch in re.finditer(r'hello', x, flags=re.M)):")

    def test_roundtrip_loop_non_replace(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_loop_replace(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })

    def test_parse_known_loop(self):
        parsed = self._parse_action("for i, mtch in enumerate(re.finditer(r'hello', x, flags=re.M)):")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'loop')

    def test_parse_known_loop_tolerates_body(self):
        """parse_generated_code normalizes editor text that still has its body."""
        parsed = self.parse_generated_code(
            "for i, mtch in enumerate(re.finditer(r'hello', x, flags=re.M)):\n    pass")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'loop')


class TestDSLMatchStringsAction(_ActionTestBase):
    """Test match_strings action via Action rule."""

    ACTION = 'match_strings'

    def test_match_strings_all(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.findall(r'hello', x, flags=re.M)")

    def test_match_strings_first(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "next(iter(re.findall(r'hello', x, flags=re.M)), None)")

    def test_match_strings_expr(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.findall(re.escape('hello'), x)")

    def test_match_strings_ci(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': True,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.findall(r'hello', x, flags=re.M|re.I)")

    def test_match_strings_not_generated_with_replace(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': 'mtch.group().upper()',
        })
        self.assertIsNone(result)

    def test_roundtrip_match_strings_all(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_match_strings_first(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })

    def test_roundtrip_match_strings_expr(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'expr': "'hello'", 'source_expr': 'x',
        })

    def test_parse_known_match_strings(self):
        parsed = self._parse_action("re.findall(r'hello', x, flags=re.M)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'match_strings')

    def test_parse_known_match_strings_first(self):
        parsed = self._parse_action("next(iter(re.findall(r'hello', x, flags=re.M)), None)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'match_strings')


class TestDSLLoopMatchStringsAction(_ActionTestBase):
    """Test loop_match_strings action via Action rule."""

    ACTION = 'loop_match_strings'

    def test_loop_match_strings(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "for i, s in enumerate(re.findall(r'hello', x, flags=re.M)):")

    def test_loop_match_strings_expr(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "for i, s in enumerate(re.findall(re.escape('hello'), x)):")

    def test_roundtrip_loop_match_strings(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_parse_known_loop_match_strings(self):
        parsed = self._parse_action("for i, s in enumerate(re.findall(r'hello', x, flags=re.M)):")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'loop_match_strings')


class TestDSLBooleanActions(_ActionTestBase):
    """Test any, all, if_any, if_all actions via Action rule."""

    def test_any_non_replace(self):
        result = self._gen('any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "bool(re.search(r'hello', x, flags=re.M))")

    def test_any_replace(self):
        result = self._gen('any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "any(mtch.group().isdigit() for mtch in re.finditer(r'hello', x, flags=re.M))")

    def test_all_action(self):
        result = self._gen('all', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "all(mtch.group().isdigit() for mtch in re.finditer(r'hello', x, flags=re.M))")

    def test_if_any_non_replace(self):
        result = self._gen('if_any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "if re.search(r'hello', x, flags=re.M):")

    def test_if_any_replace(self):
        result = self._gen('if_any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertIn("if any(", result[0])

    def test_if_all_action(self):
        result = self._gen('if_all', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertIn("if all(", result[0])

    def test_roundtrip_any_non_replace(self):
        self._roundtrip('any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })

    def test_roundtrip_any_replace(self):
        self._roundtrip('any', {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })

    def test_roundtrip_if_any_non_replace(self):
        self._roundtrip('if_any', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })

    def test_roundtrip_all(self):
        self._roundtrip('all', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })

    def test_parse_known_any_non_replace(self):
        parsed = self._parse_action("bool(re.search(r'hello', x, flags=re.M))")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'any')

    def test_parse_known_if_any(self):
        parsed = self._parse_action("if re.search(r'hello', x, flags=re.M):")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'if_any')

    def test_parse_known_all(self):
        parsed = self._parse_action("all(mtch.group().isdigit() for mtch in re.finditer(r'hello', x, flags=re.M))")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'all')


class TestDSLCountFilterActions(_ActionTestBase):
    """Test count and filter actions via Action rule."""

    def test_count_non_replace(self):
        result = self._gen('count', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "sum(1 for _ in re.finditer(r'hello', x, flags=re.M))")

    def test_count_replace(self):
        result = self._gen('count', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "sum(1 for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit())")

    def test_filter_list(self):
        result = self._gen('filter', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "[mtch for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit()]")

    def test_filter_first(self):
        result = self._gen('filter', {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertIn("next(", result[0])

    def test_roundtrip_count_non_replace(self):
        self._roundtrip('count', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_count_replace(self):
        self._roundtrip('count', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })

    def test_roundtrip_filter(self):
        self._roundtrip('filter', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })

    def test_parse_known_count(self):
        parsed = self._parse_action("sum(1 for _ in re.finditer(r'hello', x, flags=re.M))")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'count')

    def test_parse_known_filter(self):
        parsed = self._parse_action("[mtch for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit()]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'filter')


class TestDSLFindIndicesAction(_ActionTestBase):
    """Test find_indices action via Action rule."""

    def test_find_indices_list_no_replace(self):
        result = self._gen('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "[mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M)]")

    def test_find_indices_first_no_replace(self):
        result = self._gen('find_indices', {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "next((mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M)), None)")

    def test_find_indices_list_with_replace(self):
        result = self._gen('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "[mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit()]")

    def test_find_indices_first_with_replace(self):
        result = self._gen('find_indices', {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })
        self.assertEqual(result[0], "next((mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit()), None)")

    def test_find_indices_expr_search(self):
        result = self._gen('find_indices', {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "[mtch.start() for mtch in re.finditer(re.escape('hello'), x)]")

    def test_roundtrip_find_indices_no_replace(self):
        self._roundtrip('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_find_indices_with_replace(self):
        self._roundtrip('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False, 'has_replace': True,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "mtch.group().isdigit()",
        })

    def test_parse_known_find_indices(self):
        parsed = self._parse_action("[mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M)]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_indices')

    def test_parse_known_find_indices_with_predicate(self):
        parsed = self._parse_action("[mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M) if mtch.group().isdigit()]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_indices')


class TestDSLSplitAction(_ActionTestBase):
    """Test split action via Action rule."""

    ACTION = 'split'

    def test_split_regex_all(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.split(r'hello', x, flags=re.M)")

    def test_split_regex_first(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.split(r'hello', x, maxsplit=1, flags=re.M)")

    def test_split_expr_all(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x.split('hello')")

    def test_split_expr_first(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "x.split('hello', 1)")

    def test_split_expr_ci(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': True,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })
        self.assertEqual(result[0], "re.split(re.escape('hello'), x, flags=re.I)")

    def test_roundtrip_split_regex(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
        })

    def test_roundtrip_split_expr_first(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
        })

    def test_parse_known_split_regex(self):
        parsed = self._parse_action("re.split(r'hello', x, flags=re.M)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'split')

    def test_parse_known_split_expr(self):
        parsed = self._parse_action("x.split('hello')")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'split')


class TestDSLReplaceAction(_ActionTestBase):
    """Test replace action via Action rule."""

    ACTION = 'replace'

    def test_replace_regex_all(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "re.sub(r'hello', lambda mtch: 'world', x, flags=re.M)")

    def test_replace_regex_first(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "re.sub(r'hello', lambda mtch: 'world', x, count=1, flags=re.M)")

    def test_replace_expr_all(self):
        result = self._gen(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "re.sub(re.escape('hello'), lambda mtch: 'world', x)")

    def test_replace_index(self):
        result = self._gen(self.ACTION, {
            'is_index': True, 'is_slice': False,
            'index_expr': '5', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "x[:5] + str((lambda mtch: 'world')(x[5])) + x[5 + 1:]")

    def test_replace_slice_both(self):
        result = self._gen(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "x[:5] + str((lambda mtch: 'world')(x[5:10])) + x[10:]")

    def test_replace_slice_empty_start(self):
        result = self._gen(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '', 'slice_stop': '10', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "'' + str((lambda mtch: 'world')(x[:10])) + x[10:]")

    def test_replace_slice_empty_stop(self):
        result = self._gen(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '', 'source_expr': 'x',
            'replace_expr': "'world'",
        })
        self.assertEqual(result[0], "x[:5] + str((lambda mtch: 'world')(x[5:])) + ''")

    def test_roundtrip_replace_regex(self):
        self._roundtrip(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': r'\d+', 'source_expr': 'data',
            'replace_expr': "int(mtch.group())",
        })

    def test_roundtrip_replace_expr(self):
        self._roundtrip(self.ACTION, {
            'is_expr': True, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'expr': "'hello'", 'source_expr': 'x',
            'replace_expr': "'world'",
        })

    def test_roundtrip_replace_index(self):
        self._roundtrip(self.ACTION, {
            'is_index': True, 'is_slice': False,
            'index_expr': '5', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })

    def test_roundtrip_replace_slice(self):
        self._roundtrip(self.ACTION, {
            'is_index': False, 'is_slice': True,
            'slice_start': '5', 'slice_stop': '10', 'source_expr': 'x',
            'replace_expr': "'world'",
        })

    def test_parse_known_replace_regex(self):
        parsed = self._parse_action("re.sub(r'hello', lambda mtch: 'world', x, flags=re.M)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'replace')

    def test_parse_known_replace_expr(self):
        parsed = self._parse_action("re.sub(re.escape('hello'), lambda mtch: 'world', x)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'replace')

    def test_parse_known_replace_index(self):
        parsed = self._parse_action("x[:5] + str((lambda mtch: 'world')(x[5])) + x[5 + 1:]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'replace')

    def test_replace_no_replace_expr_returns_none(self):
        result = self._gen(self.ACTION, {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertIsNone(result)


class TestDSLGenerateActionWrapper(_ActionTestBase):
    """Test the generate_action wrapper function."""

    def test_generate_action_find_or_map(self):
        result = self.generate_action('find_or_map', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_matches')
        self.assertEqual(result[1], "list(re.finditer(r'hello', x, flags=re.M))")

    def test_generate_action_find_or_map_replace(self):
        result = self.generate_action('find_or_map', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
            'replace_visible': True, 'replace_expr': "'world'",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_transformed')

    def test_generate_action_delete(self):
        result = self.generate_action('delete', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x')

    def test_generate_action_loop_returns_none_name(self):
        result = self.generate_action('loop', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertIsNone(result[0])

    def test_generate_action_match_strings(self):
        result = self.generate_action('match_strings', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_strings')
        self.assertEqual(result[1], "re.findall(r'hello', x, flags=re.M)")

    def test_generate_action_match_strings_first(self):
        result = self.generate_action('match_strings', {
            'is_expr': False, 'is_first': True, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_substring')
        self.assertEqual(result[1], "next(iter(re.findall(r'hello', x, flags=re.M)), None)")

    def test_generate_action_loop_match_strings_returns_none_name(self):
        result = self.generate_action('loop_match_strings', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertIsNone(result[0])

    def test_generate_action_split(self):
        result = self.generate_action('split', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_parts')

    def test_generate_action_find_indices(self):
        result = self.generate_action('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_indices')
        self.assertEqual(result[1], "[mtch.start() for mtch in re.finditer(r'hello', x, flags=re.M)]")

    def test_generate_action_find_indices_with_replace(self):
        result = self.generate_action('find_indices', {
            'is_expr': False, 'is_first': False, 'is_ci': False,
            'is_index': False, 'is_slice': False,
            'regex_pattern': 'hello', 'source_expr': 'x',
            'has_var': True, 'suggest_base': 'x',
            'replace_visible': True, 'replace_expr': "mtch.group().isdigit()",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'x_indices')

    def test_parse_generated_code_recovers_action(self):
        code = "list(re.finditer(r'hello', x, flags=re.M))"
        result = self.parse_generated_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'find_or_map')


# =============================================================================
# Multi-Index Search: Detection & Highlighting Tests
# =============================================================================

class TestMultiIndexHighlighting(unittest.TestCase):
    """Test highlighting for list-of-int index searches."""

    def setUp(self):
        self.value = "hello"

    def test_list_of_ints_highlights_each_char(self):
        """[0,2,4] highlights 'h', 'l', 'o' individually."""
        highlights = parse_regex_for_highlighting('[0,2,4]', self.value, eval)
        self.assertEqual(len(highlights), 3)

    def test_list_of_ints_with_duplicates(self):
        """[0,0,4,-1] highlights 4 positions (duplicates OK)."""
        highlights = parse_regex_for_highlighting('[0,0,4,-1]', self.value, eval)
        self.assertEqual(len(highlights), 4)

    def test_list_of_ints_negative_index(self):
        """[-1] highlights last character 'o'."""
        highlights = parse_regex_for_highlighting('[-1]', self.value, eval)
        self.assertEqual(len(highlights), 1)

    def test_empty_list_no_highlights(self):
        """[] produces no highlights."""
        highlights = parse_regex_for_highlighting('[]', self.value, eval)
        self.assertEqual(len(highlights), 0)


class TestMultiIndexEval(unittest.TestCase):
    """Test _eval_index_or_slice_match for multi-index modes."""

    def setUp(self):
        self.value = "hello"

    def test_list_of_ints_returns_char_list(self):
        """[0,0,4,-1] returns ['h','h','o','o']."""
        result = _eval_index_or_slice_match('[0,0,4,-1]', self.value, eval)
        self.assertEqual(result, ['h', 'h', 'o', 'o'])

    def test_list_of_ints_single(self):
        """[2] returns ['l']."""
        result = _eval_index_or_slice_match('[2]', self.value, eval)
        self.assertEqual(result, ['l'])

    def test_empty_list_returns_empty(self):
        """[] returns []."""
        result = _eval_index_or_slice_match('[]', self.value, eval)
        self.assertEqual(result, [])

    def test_list_of_pairs_returns_slices(self):
        """[(2,3),(0,4)] returns ['l','hell']."""
        result = _eval_index_or_slice_match('[(2,3),(0,4)]', self.value, eval)
        self.assertEqual(result, ['l', 'hell'])

    def test_is_index_or_slice_for_list_of_ints(self):
        """is_index_or_slice_search returns True for list-of-int."""
        self.assertTrue(is_index_or_slice_search('[0,2,4]', eval))

    def test_is_index_or_slice_for_list_of_pairs(self):
        """is_index_or_slice_search returns True for list-of-pairs."""
        self.assertTrue(is_index_or_slice_search('[(2,3),(0,4)]', eval))


class TestMultiIndexFindMatches(unittest.TestCase):
    """Test _find_matches for multi-index modes."""

    def setUp(self):
        self.value = "hello"

    def test_multi_index_find_matches(self):
        """_find_matches for [0,2,4] returns ['h','l','o']."""
        result = _find_matches('[0,2,4]', self.value, eval)
        self.assertEqual(result, ['h', 'l', 'o'])

    def test_multi_pair_find_matches(self):
        """_find_matches for [(0,2),(3,5)] returns ['he','lo']."""
        result = _find_matches('[(0,2),(3,5)]', self.value, eval)
        self.assertEqual(result, ['he', 'lo'])


# =============================================================================
# Broadcast Slice: Detection & Highlighting Tests
# =============================================================================

class TestBroadcastSliceHighlighting(unittest.TestCase):
    """Test highlighting for broadcast slice searches."""

    def setUp(self):
        self.value = "hello"

    def test_left_list_broadcast(self):
        """[2,3]: highlights 'llo' and 'lo' separately."""
        highlights = parse_regex_for_highlighting('[2,3]:', self.value, eval)
        self.assertEqual(len(highlights), 2)

    def test_both_lists_broadcast(self):
        """[0,1]:[3,2] highlights 'hel' and 'e' separately."""
        highlights = parse_regex_for_highlighting('[0,1]:[3,2]', self.value, eval)
        self.assertEqual(len(highlights), 2)

    def test_right_list_broadcast(self):
        """:[3,2] highlights 'hel' and 'he' separately."""
        highlights = parse_regex_for_highlighting(':[3,2]', self.value, eval)
        self.assertEqual(len(highlights), 2)


class TestBroadcastSliceEval(unittest.TestCase):
    """Test _eval_index_or_slice_match for broadcast slice modes."""

    def setUp(self):
        self.value = "hello"

    def test_left_list_broadcast(self):
        """[2,3]: returns ['llo','lo']."""
        result = _eval_index_or_slice_match('[2,3]:', self.value, eval)
        self.assertEqual(result, ['llo', 'lo'])

    def test_both_lists_broadcast(self):
        """[0,1]:[3,2] returns ['hel','e']."""
        result = _eval_index_or_slice_match('[0,1]:[3,2]', self.value, eval)
        self.assertEqual(result, ['hel', 'e'])

    def test_right_list_broadcast(self):
        """:[3,2] returns ['hel','he']."""
        result = _eval_index_or_slice_match(':[3,2]', self.value, eval)
        self.assertEqual(result, ['hel', 'he'])

    def test_is_index_or_slice_for_broadcast(self):
        """is_index_or_slice_search returns True for broadcast slice."""
        self.assertTrue(is_index_or_slice_search('[2,3]:', eval))

    def test_broadcast_find_matches(self):
        """_find_matches for [2,3]: returns ['llo','lo']."""
        result = _find_matches('[2,3]:', self.value, eval)
        self.assertEqual(result, ['llo', 'lo'])


# =============================================================================
# Multi-Pair Slice: Highlighting Tests
# =============================================================================

class TestMultiPairSliceHighlighting(unittest.TestCase):
    """Test highlighting for list-of-pairs slice searches."""

    def setUp(self):
        self.value = "hello"

    def test_list_of_pairs_highlights(self):
        """[(2,3),(0,4)] highlights 2 regions."""
        highlights = parse_regex_for_highlighting('[(2,3),(0,4)]', self.value, eval)
        self.assertEqual(len(highlights), 2)


# =============================================================================
# Multi-Index: Action Button Code Generation Tests
# =============================================================================

class TestMultiIndexActionButtons(unittest.TestCase):
    """Test action button code generation for multi-index search."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.model['search'] = '[0,0,4,-1]'
        self.var_and_exp = ('x', 'x')

    def test_find_or_map_multi_index(self):
        """Get button produces [x[i] for i in INDICES]."""
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        suggest_name, expr = commands[0][:2]
        self.assertEqual(suggest_name, "x_chars")
        self.assertEqual(expr, "[x[i] for i in [0,0,4,-1]]")

    def test_find_or_map_multi_index_with_replace(self):
        """Map button produces [(lambda mtch: EXPR)(x[i]) for i in INDICES]."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$.upper()"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[(lambda mtch: mtch.upper())(x[i]) for i in [0,0,4,-1]]")

    def test_count_multi_index(self):
        """Count produces len(INDICES)."""
        _, commands = update(make_action_button_event('count'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "len([0,0,4,-1])")

    def test_copy_multi_index(self):
        """copy=True produces CopyToClipboard."""
        _, commands = update(make_action_button_event('find_or_map', copy=True),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)

    def test_loop_multi_index(self):
        """Loop produces for i, mtch in enumerate(...)."""
        _, commands = update(make_action_button_event('loop'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("for i, mtch in enumerate(", expr)

    def test_filter_multi_index(self):
        """Filter with replace produces [mtch for mtch in [...] if EXPR]."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "$ != 'h'"
        _, commands = update(make_action_button_event('filter'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertIn("for mtch in", expr)
        self.assertIn("if mtch != 'h'", expr)

    def test_find_indices_multi_index(self):
        """Find Indices for multi-index returns the index list itself."""
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[0,0,4,-1]")


# =============================================================================
# Broadcast Slice: Action Button Code Generation Tests
# =============================================================================

class TestBroadcastSliceActionButtons(unittest.TestCase):
    """Test action button code generation for broadcast slice search."""

    def setUp(self):
        self.value = "hello"
        self.model = init_model(self.value)
        self.model['search'] = '[2,3]:'
        self.var_and_exp = ('x', 'x')

    def test_find_or_map_broadcast_left(self):
        """Get with left-list broadcast produces [x[i:] for i in [2,3]]."""
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[x[i:] for i in [2,3]]")

    def test_find_or_map_broadcast_both(self):
        """Get with both-lists broadcast produces zip form."""
        self.model['search'] = '[0,1]:[3,2]'
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[x[i:j] for i, j in zip([0,1], [3,2])]")

    def test_find_or_map_broadcast_right(self):
        """Get with right-list broadcast produces [x[:i] for i in [3,2]]."""
        self.model['search'] = ':[3,2]'
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[x[:i] for i in [3,2]]")


# =============================================================================
# Multi-Pair Slice: Action Button Code Generation Tests
# =============================================================================

class TestMultiPairSliceActionButtons(unittest.TestCase):
    """Test action button code generation for list-of-pairs slice search."""

    def setUp(self):
        self.value = "hello"
        self.model = init_model(self.value)
        self.model['search'] = '[(2,3),(0,4)]'
        self.var_and_exp = ('x', 'x')

    def test_find_or_map_multi_pair(self):
        """Get produces [x[i:j] for i, j in PAIRS]."""
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[x[i:j] for i, j in [(2,3),(0,4)]]")

    def test_find_or_map_multi_pair_with_replace(self):
        """Map produces [(lambda mtch: EXPR)(x[i:j]) for ...]."""
        self.model['replace_visible'] = True
        self.model['replace_text'] = "len($)"
        _, commands = update(make_action_button_event('find_or_map'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[(lambda mtch: len(mtch))(x[i:j]) for i, j in [(2,3),(0,4)]]")

    def test_find_indices_multi_pair(self):
        """Find Indices for pairs returns [i for i, j in PAIRS]."""
        _, commands = update(make_action_button_event('find_indices'),
                            self.var_and_exp, self.model, self.value,
                            eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        _, expr = commands[0][:2]
        self.assertEqual(expr, "[i for i, j in [(2,3),(0,4)]]")


# =============================================================================
# Multi-Index DSL Grammar Tests
# =============================================================================

class TestDSLMultiIndexAction(_ActionTestBase):
    """Test multi-index action via Action rule."""

    def test_multi_index_get(self):
        result = self._gen('find_or_map', {
            'is_multi_index': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[x[i] for i in [0,2,4]]")

    def test_multi_index_transform(self):
        result = self._gen('find_or_map', {
            'is_multi_index': True, 'has_replace': True,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
            'replace_expr': "mtch.upper()",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[(lambda mtch: mtch.upper())(x[i]) for i in [0,2,4]]")

    def test_multi_index_count_no_replace(self):
        result = self._gen('count', {
            'is_multi_index': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "len([0,2,4])")

    def test_multi_index_loop(self):
        result = self._gen('loop', {
            'is_multi_index': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertIn("for i, mtch in enumerate(", result[0])

    def test_multi_index_find_indices(self):
        result = self._gen('find_indices', {
            'is_multi_index': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[0,2,4]")

    def test_roundtrip_multi_index_get(self):
        self._roundtrip('find_or_map', {
            'is_multi_index': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'indices_expr': '[0,2,4]', 'source_expr': 'x',
        })

    def test_parse_known_multi_index(self):
        parsed = self._parse_action("[x[i] for i in [0,2,4]]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('is_multi_index'))


class TestDSLMultiPairSliceAction(_ActionTestBase):
    """Test multi-pair-slice action via Action rule."""

    def test_multi_pair_get(self):
        result = self._gen('find_or_map', {
            'is_multi_pair_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'pairs_expr': '[(2,3),(0,4)]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[x[i:j] for i, j in [(2,3),(0,4)]]")

    def test_multi_pair_transform(self):
        result = self._gen('find_or_map', {
            'is_multi_pair_slice': True, 'has_replace': True,
            'is_index': False, 'is_slice': False,
            'pairs_expr': '[(2,3),(0,4)]', 'source_expr': 'x',
            'replace_expr': "len(mtch)",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[(lambda mtch: len(mtch))(x[i:j]) for i, j in [(2,3),(0,4)]]")

    def test_multi_pair_find_indices(self):
        result = self._gen('find_indices', {
            'is_multi_pair_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'pairs_expr': '[(2,3),(0,4)]', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[i for i, j in [(2,3),(0,4)]]")

    def test_roundtrip_multi_pair_get(self):
        self._roundtrip('find_or_map', {
            'is_multi_pair_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'pairs_expr': '[(2,3),(0,4)]', 'source_expr': 'x',
        })

    def test_parse_known_multi_pair(self):
        parsed = self._parse_action("[x[i:j] for i, j in [(2,3),(0,4)]]")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_or_map')
        self.assertTrue(parsed.get('is_multi_pair_slice'))


class TestDSLBroadcastSliceAction(_ActionTestBase):
    """Test broadcast-slice action via Action rule."""

    def test_broadcast_left_get(self):
        result = self._gen('find_or_map', {
            'is_broadcast_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'has_start_list': True, 'has_stop_list': False,
            'start_list_expr': '[2,3]', 'slice_stop': '', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[x[i:] for i in [2,3]]")

    def test_broadcast_right_get(self):
        result = self._gen('find_or_map', {
            'is_broadcast_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'has_start_list': False, 'has_stop_list': True,
            'stop_list_expr': '[3,2]', 'slice_start': '', 'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[x[:i] for i in [3,2]]")

    def test_broadcast_both_get(self):
        result = self._gen('find_or_map', {
            'is_broadcast_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'has_start_list': True, 'has_stop_list': True,
            'start_list_expr': '[0,1]', 'stop_list_expr': '[3,2]',
            'source_expr': 'x',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "[x[i:j] for i, j in zip([0,1], [3,2])]")

    def test_roundtrip_broadcast_left(self):
        self._roundtrip('find_or_map', {
            'is_broadcast_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'has_start_list': True, 'has_stop_list': False,
            'start_list_expr': '[2,3]', 'slice_stop': '', 'source_expr': 'x',
        })

    def test_roundtrip_broadcast_both(self):
        self._roundtrip('find_or_map', {
            'is_broadcast_slice': True, 'has_replace': False,
            'is_index': False, 'is_slice': False,
            'has_start_list': True, 'has_stop_list': True,
            'start_list_expr': '[0,1]', 'stop_list_expr': '[3,2]',
            'source_expr': 'x',
        })

    def test_parse_known_broadcast_left(self):
        parsed = self._parse_action("[x[i:] for i in [2,3]]")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.get('is_broadcast_slice'))

    def test_parse_known_broadcast_both(self):
        parsed = self._parse_action("[x[i:j] for i, j in zip([0,1], [3,2])]")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.get('is_broadcast_slice'))


class TestScrollToMatch(unittest.TestCase):
    """Test snc-scroll-to-match attribute on first match character span."""

    def test_scroll_to_match_after_search_input(self):
        """SearchBoxInput sets _scroll_to_match, first match span gets attribute."""
        value = "hello world"
        model = init_model(value)
        model, _ = update(make_search_box_input_event(r"r'world'"),
                          ('x', 'x'), model, value)
        self.assertTrue(model.get('_scroll_to_match'))
        html = visualize(value, model, None, None)
        self.assertIn('snc-scroll-to-match', html)

    def test_scroll_to_match_on_first_match_only(self):
        """Attribute appears only once even with multiple matches."""
        value = "abcabc"
        model = init_model(value)
        model['search'] = r"r'abc'"
        model['_scroll_to_match'] = True
        html = visualize(value, model, None, None)
        self.assertEqual(html.count('snc-scroll-to-match'), 1)

    def test_no_scroll_to_match_without_flag(self):
        """Without _scroll_to_match flag, no attribute even with matches."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        html = visualize(value, model, None, None)
        self.assertNotIn('snc-scroll-to-match', html)

    def test_no_scroll_to_match_without_search(self):
        """No attribute when there's no search."""
        value = "hello world"
        model = init_model(value)
        model['_scroll_to_match'] = True
        html = visualize(value, model, None, None)
        self.assertNotIn('snc-scroll-to-match', html)

    def test_no_scroll_to_match_when_no_results(self):
        """No attribute when search has no matches."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'xyz'"
        model['_scroll_to_match'] = True
        html = visualize(value, model, None, None)
        self.assertNotIn('snc-scroll-to-match', html)

    def test_scroll_to_match_cleared_on_other_events(self):
        """Non-search events clear _scroll_to_match flag."""
        value = "hello world"
        model = init_model(value)
        model['_scroll_to_match'] = True
        event = make_mouse_down_event(5, top_half=True)
        new_model, _ = update(event, ('x', 'x'), model, value)
        self.assertFalse(new_model.get('_scroll_to_match'))

    def test_scroll_to_match_not_set_on_same_search(self):
        """Typing the same search value does not set _scroll_to_match."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        model, _ = update(make_search_box_input_event(r"r'hello'"),
                          ('x', 'x'), model, value)
        self.assertFalse(model.get('_scroll_to_match'))


class TestActionBtn(unittest.TestCase):
    def test_no_title_parameter(self):
        """_action_btn should not accept a title parameter."""
        import inspect
        sig = inspect.signature(_action_btn)
        self.assertNotIn('title', sig.parameters)

    def test_no_data_action_name(self):
        """_action_btn should never emit data-action-name."""
        result = _action_btn('Count', 'count', enabled=True, expr='len(x)')
        self.assertNotIn('data-action-name', result)

    def test_expr_attr_still_present(self):
        """data-action-expr should still be emitted when expr is given."""
        result = _action_btn('Count', 'count', enabled=True, expr='len(x)')
        self.assertIn(py_exp_attrs('len(x)', draggable=False,
                                   attr='data-action-expr').strip(), result)

    def test_no_expr_attr_when_empty(self):
        result = _action_btn('Count', 'count', enabled=True)
        self.assertNotIn('data-action-expr', result)


class TestDropdownRow(unittest.TestCase):
    def test_no_copy_button(self):
        """_dropdown_row should not contain the snc-dropdown-copy span."""
        result = _dropdown_row('Any', 'any', True, expr='any(x)')
        self.assertNotIn('snc-dropdown-copy', result)
        self.assertNotIn('⧉', result)

    def test_has_snc_py_exp(self):
        """_dropdown_row should emit snc-py-exps with the expression."""
        result = _dropdown_row('Any', 'any', True, expr='any(x)')
        self.assertIn(exp_attr('any(x)'), result)

    def test_has_right_align(self):
        """_dropdown_row should emit snc-py-exp-align=right (tooltip to the right of the row)."""
        result = _dropdown_row('Any', 'any', True, expr='any(x)')
        self.assertIn('snc-py-exp-align="right"', result)

    def test_no_py_exp_when_no_expr(self):
        """No snc-py-exps attribute when expr is empty."""
        result = _dropdown_row('Any', 'any', True)
        self.assertNotIn('snc-py-exps', result)

    def test_still_has_mouse_down(self):
        """Click action should still be wired up."""
        result = _dropdown_row('Any', 'any', True, expr='any(x)')
        self.assertIn('snc-mouse-down', result)

    def test_dimmed_when_disabled(self):
        result = _dropdown_row('Any', 'any', False, expr='any(x)')
        self.assertIn('dimmed', result)


class TestToolToolbar(unittest.TestCase):
    """Tests for the tool toolbar (literal / fuzzy / index) and modifier overrides."""

    def _tool_select_event(self, tool: str) -> dict:
        return {
            'pythonEventStr': repr(ToolSelect(tool=tool)),
            'eventJSON': {},
        }

    def _mouse_down(self, index: int, *, alt: bool = False, shift: bool = False) -> dict:
        return {
            'pythonEventStr': repr(MouseDown(_legacy_internal_index(index))),
            'eventJSON': {
                'altKey': alt,
                'shiftKey': shift,
                'offsetY': 5,
                'elementHeight': 20,
                'buttons': 1,
            },
        }

    def test_init_model_default_tool_is_literal(self):
        model = init_model("hello")
        self.assertEqual(model.get('tool'), 'literal')

    def test_tool_select_updates_model(self):
        value = "hello"
        model = init_model(value)
        for t in ('fuzzy', 'index', 'literal'):
            model, commands = update(self._tool_select_event(t), ('x', 'x'), model, value)
            self.assertEqual(model['tool'], t)
            self.assertEqual(commands, [])

    def test_tool_select_invalid_value_ignored(self):
        value = "hello"
        model = init_model(value)
        model, _ = update(self._tool_select_event('bogus'), ('x', 'x'), model, value)
        self.assertEqual(model['tool'], 'literal')

    def test_mouse_down_no_modifiers_uses_literal_tool(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'literal'
        model, _ = update(self._mouse_down(5), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'literal')
        self.assertTrue(model['dragging'])

    def test_mouse_down_no_modifiers_uses_fuzzy_tool(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'fuzzy'
        model, _ = update(self._mouse_down(5), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'fuzzy')
        self.assertTrue(model['dragging'])

    def test_shift_overrides_fuzzy_tool_to_literal(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'fuzzy'
        model, _ = update(self._mouse_down(5, shift=True), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'literal')

    def test_alt_overrides_literal_tool_to_fuzzy(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'literal'
        model, _ = update(self._mouse_down(5, alt=True), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'fuzzy')

    def test_shift_overrides_index_tool_to_literal(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'index'
        model, _ = update(self._mouse_down(5, shift=True), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'literal')
        self.assertTrue(model['dragging'])

    def test_alt_overrides_index_tool_to_fuzzy(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'index'
        model, _ = update(self._mouse_down(5, alt=True), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'fuzzy')
        self.assertTrue(model['dragging'])

    def test_index_tool_no_modifiers_starts_index_drag(self):
        """With tool=index and no modifiers, MouseDown starts an index-mode drag."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'index'
        model, _ = update(self._mouse_down(5), ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'index')
        self.assertTrue(model['dragging'])
        self.assertIsNotNone(model['anchorIdx'])

    def test_ctrl_overrides_literal_tool_to_index(self):
        """Holding ctrl while tool=literal switches to index for this drag."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'literal'
        ev = self._mouse_down(5)
        ev['eventJSON']['ctrlKey'] = True
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'index')
        self.assertTrue(model['dragging'])

    def test_shift_beats_ctrl(self):
        """Shift takes priority over ctrl in the resolver."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'literal'
        ev = self._mouse_down(5, shift=True)
        ev['eventJSON']['ctrlKey'] = True
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'literal')

    def test_alt_beats_ctrl(self):
        """Alt takes priority over ctrl in the resolver."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'literal'
        ev = self._mouse_down(5, alt=True)
        ev['eventJSON']['ctrlKey'] = True
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['anchorType'], 'fuzzy')

    def test_visualize_renders_tool_toolbar(self):
        # 5 lines so the non-compact (vertical) layout is used and all
        # ab/.*/01 icon labels appear as standalone tool buttons.
        value = "a\nb\nc\nd\ne"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertIn('tool-toolbar', html_str)
        self.assertIn('tool-button', html_str)
        self.assertIn('>ab<', html_str)
        self.assertIn('>.*<', html_str)
        self.assertIn('>01<', html_str)

    def test_fresh_mouse_down_preserves_active_tool(self):
        """A fresh MouseDown (which reinitializes the model) must keep the active tool."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'fuzzy'
        model, _ = update(self._mouse_down(5), ('x', 'x'), model, value)
        self.assertEqual(model['tool'], 'fuzzy')
        self.assertEqual(model['anchorType'], 'fuzzy')

    def test_visualize_marks_active_tool(self):
        # Use a >=4 line value to force the vertical (non-compact) layout
        # so the active class is applied directly to the icon-label button.
        value = "a\nb\nc\nd\ne"
        model = init_model(value)
        model['tool'] = 'fuzzy'
        html_str = visualize(value, model, None, None)
        # The active tool's button should have the 'active' class adjacent to its label.
        self.assertRegex(html_str, r'class="tool-button active"[^>]*>\.\*<')
        self.assertNotRegex(html_str, r'class="tool-button active"[^>]*>ab<')

    def test_tool_buttons_have_name_tooltips(self):
        """Each tool button must carry a data-tooltip with the tool's display name
        (snc-tooltip system - shows on hover faster than the native title attribute)."""
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        model['search'] = r"r'a'"  # so pick button is enabled (still gets a tooltip either way)
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'data-tool="literal"[^>]*data-tooltip="Literal[^"]*"|data-tooltip="Literal[^"]*"[^>]*data-tool="literal"')
        self.assertRegex(html_str, r'data-tool="fuzzy"[^>]*data-tooltip="Fuzzy[^"]*"|data-tooltip="Fuzzy[^"]*"[^>]*data-tool="fuzzy"')
        self.assertRegex(html_str, r'data-tool="index"[^>]*data-tooltip="Index[^"]*"|data-tooltip="Index[^"]*"[^>]*data-tool="index"')
        self.assertRegex(html_str, r'data-tool="pick"[^>]*data-tooltip="Pick"|data-tooltip="Pick"[^>]*data-tool="pick"')

    def _tooltips(self, value):
        model = init_model(value)
        model['search'] = r"r'a'"
        html_str = visualize(value, model, None, None)
        return dict(re.findall(r'data-tool="(\w+)"[^>]*data-tooltip="([^"]*)"', html_str))

    def test_tool_tooltips_name_the_modifier_that_overrides_to_them(self):
        """Holding shift/option/control picks a tool for one gesture without
        switching to it; the tooltip says which key, in the OS's own terms."""
        import visualizer_utils
        with patch.object(visualizer_utils, '_IS_MAC', True):
            tips = self._tooltips("a\nb\nc\nd\ne")
            self.assertEqual(tips['literal'], 'Literal (\u21e7)')
            self.assertEqual(tips['fuzzy'], 'Fuzzy (\u2325)')
            self.assertEqual(tips['index'], 'Index (\u2303)')
            self.assertEqual(tips['pick'], 'Pick')
        with patch.object(visualizer_utils, '_IS_MAC', False):
            tips = self._tooltips("a\nb\nc\nd\ne")
            self.assertEqual(tips['literal'], 'Literal (Shift)')
            self.assertEqual(tips['fuzzy'], 'Fuzzy (Alt)')
            self.assertEqual(tips['index'], 'Index (Ctrl)')

    def test_compact_tool_rows_carry_the_same_tooltips(self):
        import visualizer_utils
        with patch.object(visualizer_utils, '_IS_MAC', True):
            tips = self._tooltips("short")  # under 4 lines: compact dropdown
            self.assertEqual(tips.get('fuzzy'), 'Fuzzy (\u2325)')

    def test_tool_button_tooltips_right_aligned(self):
        """Tool toolbar lives in the upper-right corner, so tooltips show to the
        right of the button (where there's empty editor space) instead of above."""
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        # Each tool button carries data-tooltip-align="right"
        for tool in ('literal', 'fuzzy', 'index', 'pick'):
            self.assertRegex(
                html_str,
                rf'data-tool="{tool}"[^>]*data-tooltip-align="right"'
                rf'|data-tooltip-align="right"[^>]*data-tool="{tool}"',
            )

    def test_dimmed_pick_tool_button_still_has_tooltip(self):
        """Even when the pick tool is dimmed (no search), it should still carry its tooltip."""
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        # No search => pick button is dimmed and click-disabled.
        html_str = visualize(value, model, None, None)
        self.assertRegex(
            html_str,
            r'<span class="tool-button dimmed"[^>]*data-tool="pick"[^>]*data-tooltip="Pick"'
            r'|<span class="tool-button dimmed"[^>]*data-tooltip="Pick"[^>]*data-tool="pick"',
        )

    # --- compact (dropdown) toolbar for short strings -----------------------

    def _long_value(self) -> str:
        """A 5-line string forces the non-compact (vertical) toolbar layout."""
        return "a\nb\nc\nd\ne"

    def test_long_string_uses_vertical_toolbar(self):
        """4 or more lines -> traditional vertical toolbar with all 4 buttons."""
        value = self._long_value()
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertNotIn('tool-toolbar-compact', html_str)
        # All 4 tool icon labels should still render as separate buttons
        self.assertIn('>ab<', html_str)
        self.assertIn('>.*<', html_str)
        self.assertIn('>01<', html_str)

    def test_short_string_uses_compact_dropdown_toolbar(self):
        """Less than 4 lines -> compact dropdown that collapses the 4 tools."""
        value = "hello"  # 1 line
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertIn('tool-toolbar-compact', html_str)
        # The compact toolbar uses the snc-dropdown-trigger pattern (hover panel)
        self.assertIn('snc-dropdown-trigger', html_str)
        self.assertIn('data-hover-menu', html_str)

    def test_compact_dropdown_trigger_shows_chevron(self):
        """Compact dropdown trigger displays a 🞃 chevron next to the active tool icon."""
        value = "hello"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertIn('\U0001F783', html_str)  # 🞃 (U+1F783, DOWN POINTING SMALL TRIANGLE)

    def test_compact_dropdown_includes_all_tool_icons(self):
        """All 4 tool icons live inside the trigger so CSS can swap which
        one is visible based on body.snc-shift-down / snc-alt-down / snc-ctrl-down
        without a Python roundtrip."""
        value = "hello"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        # Each tool's icon (literal=ab, fuzzy=.*, index=01) appears as a .tool-icon
        # span inside the trigger. The 'pick' icon is HTML so we just check for
        # its data-tool attribute.
        self.assertRegex(html_str, r'class="tool-icon"[^>]*data-tool="literal"[^>]*>ab<')
        self.assertRegex(html_str, r'class="tool-icon"[^>]*data-tool="fuzzy"[^>]*>\.\*<')
        self.assertRegex(html_str, r'class="tool-icon"[^>]*data-tool="index"[^>]*>01<')
        self.assertRegex(html_str, r'class="tool-icon"[^>]*data-tool="pick"')

    def test_compact_dropdown_does_not_show_tool_name_in_trigger(self):
        """The compact dropdown trigger shows the icon, not the name."""
        value = "hello"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        # The full word "Literal" must not appear inside the trigger button itself
        # (it does appear inside the dropdown panel option rows).
        # Find the trigger button content and assert "Literal" isn't in it.
        import re as _re
        # DOTALL: the pick chip holds an inline SVG, which spans lines.
        m = _re.search(r'<span class="tool-button active tool-dropdown-trigger-button[^"]*">(.*?)</span>(?=<div class="snc-dropdown-panel)', html_str, _re.DOTALL)
        self.assertIsNotNone(m, f"Could not find compact dropdown trigger button in HTML")
        trigger_content = m.group(1)
        for name in ('Literal', 'Fuzzy', 'Index', 'Pick'):
            self.assertNotIn(name, trigger_content,
                             f"Tool name {name!r} should not appear in compact dropdown trigger (icon-only)")

    def test_compact_dropdown_marks_active_tool(self):
        """The trigger marks the model's active tool so default CSS shows it."""
        value = "hello"
        model = init_model(value)
        model['tool'] = 'fuzzy'
        html_str = visualize(value, model, None, None)
        # The dropdown trigger element carries the active tool as data-active-tool
        self.assertRegex(
            html_str,
            r'class="[^"]*tool-toolbar-compact[^"]*"[^>]*data-active-tool="fuzzy"'
            r'|data-active-tool="fuzzy"[^>]*class="[^"]*tool-toolbar-compact',
        )

    def test_compact_dropdown_panel_has_all_four_tool_options(self):
        """The hover-menu panel inside the compact dropdown lists all 4 tools."""
        value = "hello"
        model = init_model(value)
        model['search'] = r"r'hello'"  # so pick is enabled
        html_str = visualize(value, model, None, None)
        # Each of the 4 tools has a clickable option in the panel
        for tool in ('literal', 'fuzzy', 'index', 'pick'):
            self.assertRegex(
                html_str,
                rf'snc-mouse-down="ToolSelect\(tool=&#x27;{tool}&#x27;\)"',
            )

    def test_compact_dropdown_panel_includes_tool_names(self):
        """The hover-menu rows show each tool's display name (Literal / Fuzzy / Index / Pick)."""
        value = "hello"
        model = init_model(value)
        model['search'] = r"r'hello'"
        html_str = visualize(value, model, None, None)
        for name in ('Literal', 'Fuzzy', 'Index', 'Pick'):
            self.assertRegex(html_str, rf'class="tool-dropdown-name">{name}<')

    def test_compact_dropdown_pick_option_dimmed_when_no_search(self):
        """In the compact panel, the pick row is dimmed (no click) when there's no search."""
        value = "hello"
        model = init_model(value)
        # No search -> pick dimmed
        html_str = visualize(value, model, None, None)
        # The Pick row inside the panel must be marked dimmed and must NOT
        # carry a snc-mouse-down handler (clicks are no-ops).
        self.assertRegex(
            html_str,
            r'class="[^"]*tool-dropdown-option[^"]*dimmed[^"]*"[^>]*data-tool="pick"',
        )
        self.assertNotRegex(
            html_str,
            r'data-tool="pick"[^>]*snc-mouse-down=',
        )

    def test_compact_dropdown_trigger_has_active_class(self):
        """The trigger button uses the same .tool-button.active styling as a vertical button."""
        value = "hello"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'class="tool-button active[^"]*"')

    def test_three_line_string_is_compact(self):
        """3 lines (<4) -> compact dropdown."""
        value = "a\nb\nc"  # 3 lines
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertIn('tool-toolbar-compact', html_str)

    def test_four_line_string_is_not_compact(self):
        """4 lines (not <4) -> normal vertical toolbar."""
        value = "a\nb\nc\nd"  # 4 lines
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertNotIn('tool-toolbar-compact', html_str)


class TestIndexSelection(unittest.TestCase):
    """Tests for index-mode mouse selection (ctrl hotkey or persistent 'index' tool).

    An index-mode drag produces a Python slice expression `start:stop` in
    model['search'], using STRING (not internal/augmented) coordinates.
    """

    def _mouse_down(self, internal_index: int, *, ctrl: bool = False,
                    shift: bool = False, alt: bool = False) -> dict:
        return {
            'pythonEventStr': repr(MouseDown(internal_index)),
            'eventJSON': {
                'ctrlKey': ctrl, 'shiftKey': shift, 'altKey': alt,
                'offsetY': 5, 'elementHeight': 20, 'buttons': 1,
            },
        }

    def _mouse_move(self, internal_index: int, *, ctrl: bool = False,
                    buttons: int = 1) -> dict:
        return {
            'pythonEventStr': repr(MouseMove(internal_index)),
            'eventJSON': {'buttons': buttons, 'ctrlKey': ctrl},
        }

    def _mouse_up(self, internal_index: int, *, ctrl: bool = False) -> dict:
        return {
            'pythonEventStr': repr(MouseUp(internal_index)),
            'eventJSON': {'buttons': 0, 'ctrlKey': ctrl},
        }

    def test_ctrl_drag_two_chars_produces_slice(self):
        """ctrl-drag from 'h' to 'e' in 'hello' (n=5) produces canonical slice ':2'.

        With start=0 elision: '0:2' becomes ':2'. (k=3, but n=5 < 7 so no neg form.)
        """
        value = "hello"
        model = init_model(value)
        model, _ = update(self._mouse_down(1, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_move(2, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(2, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], ':2')
        self.assertTrue(is_slice_search(model['search']))

    def test_ctrl_single_click_produces_bare_index(self):
        """ctrl-click on a single char (far from end) produces a bare positive index."""
        value = "0123456789"  # n=10
        model = init_model(value)
        # Click on '4' (internal index 5 = string index 4). k=6, no neg shorthand.
        model, _ = update(self._mouse_down(5, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(5, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '4')

    def test_ctrl_single_click_last_char_uses_neg_one(self):
        """ctrl-click on the last char emits '-1' (negative-index shorthand)."""
        value = "0123456789"  # n=10
        model = init_model(value)
        # Last char '9' is at internal index 10
        model, _ = update(self._mouse_down(10, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(10, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '-1')

    def test_ctrl_single_click_second_to_last_uses_neg_two(self):
        """ctrl-click on second-to-last char emits '-2'."""
        value = "0123456789"  # n=10
        model = init_model(value)
        # Second-to-last '8' is at internal index 9 (string index 8). k=2, n>4.
        model, _ = update(self._mouse_down(9, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(9, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '-2')

    def test_ctrl_drag_across_newline_uses_neg_end(self):
        """Drag from 'b' to 'c' across \\n in 'ab\\ncd' (n=5) produces '1:-1'.

        Resolved slice = 1:4. start=1 (no zero-elision), stop=4, k=1, n>2 -> neg.
        """
        value = "ab\ncd"
        model = init_model(value)
        # Drag from 'b' (internal 2) to 'c' (internal 6)
        model, _ = update(self._mouse_down(2, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_move(6, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(6, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '1:-1')

    def test_index_tool_drag_to_end_elides_len(self):
        """Persistent index tool drag to last char emits 'start:' (end elision)."""
        value = "hello world"  # n=11
        model = init_model(value)
        model['tool'] = 'index'
        # Drag from 'w' (internal 7 = string 6) to 'd' (internal 11 = string 10).
        # Because cursor is on the LAST char, end=11=n, so emit '6:'.
        model, _ = update(self._mouse_down(7), ('x', 'x'), model, value)
        model, _ = update(self._mouse_move(11), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(11), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '6:')

    def test_index_drag_does_not_extend_existing_regex(self):
        """Index drag is always a fresh selection; never appends to an existing regex."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        # ctrl-click on a single char should REPLACE the regex with a bare index.
        model, _ = update(self._mouse_down(7, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(7, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['search'], '6')

    def test_index_drag_preserves_active_tool(self):
        """An index-mode drag must not lose the persistent 'tool' state."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'fuzzy'  # persistent fuzzy, but transient ctrl override
        model, _ = update(self._mouse_down(2, ctrl=True), ('x', 'x'), model, value)
        model, _ = update(self._mouse_up(2, ctrl=True), ('x', 'x'), model, value)
        self.assertEqual(model['tool'], 'fuzzy')

    def test_visualize_adds_tool_class_to_container(self):
        """Visualizer container gets a {literal|fuzzy|index}-tool-selected class so CSS can react."""
        value = "hello"
        for t in ('literal', 'fuzzy', 'index'):
            model = init_model(value)
            model['tool'] = t
            html_str = visualize(value, model, None, None)
            self.assertIn(f'{t}-tool-selected', html_str,
                          f'Expected class {t}-tool-selected in container HTML for tool={t!r}')


class TestSliceExprFormatting(unittest.TestCase):
    """Unit tests for _format_slice_expr (canonical Python slice expression).

    Rules:
      - start == 0 AND stop == n   -> ':'              (whole string)
      - start == 0                 -> ':<stop>' or ':-<k>' shorthand
      - stop == n                  -> '<start>:'       (end elision)
      - general                    -> '<start>:<stop>' or '<start>:-<k>'
    Negative-end shorthand applies for k = n - stop in {1, 2, 3} only when
    n > 2*k (i.e., the forward stop is at least k+1, matching the user-spec
    "forward would be at least :2 :3 :4 respectively").
    """

    def test_whole_string(self):
        self.assertEqual(_format_slice_expr(0, 10, 10), ':')

    def test_start_zero_elision(self):
        self.assertEqual(_format_slice_expr(0, 5, 11), ':5')

    def test_stop_eq_len_elision(self):
        self.assertEqual(_format_slice_expr(5, 11, 11), '5:')

    def test_general(self):
        self.assertEqual(_format_slice_expr(2, 5, 11), '2:5')

    def test_neg_one_when_start_zero(self):
        self.assertEqual(_format_slice_expr(0, 9, 10), ':-1')

    def test_neg_two_when_start_zero(self):
        self.assertEqual(_format_slice_expr(0, 8, 10), ':-2')

    def test_neg_three_when_start_zero(self):
        self.assertEqual(_format_slice_expr(0, 7, 10), ':-3')

    def test_neg_one_with_nonzero_start(self):
        self.assertEqual(_format_slice_expr(3, 9, 10), '3:-1')

    def test_neg_three_with_nonzero_start(self):
        self.assertEqual(_format_slice_expr(2, 7, 10), '2:-3')

    def test_no_neg_when_too_short_for_neg1(self):
        self.assertEqual(_format_slice_expr(0, 1, 2), ':1')

    def test_no_neg_when_too_short_for_neg2(self):
        self.assertEqual(_format_slice_expr(0, 2, 4), ':2')

    def test_no_neg_when_too_short_for_neg3(self):
        self.assertEqual(_format_slice_expr(0, 3, 6), ':3')

    def test_neg1_at_threshold(self):
        self.assertEqual(_format_slice_expr(0, 2, 3), ':-1')

    def test_neg2_at_threshold(self):
        self.assertEqual(_format_slice_expr(0, 3, 5), ':-2')

    def test_neg3_at_threshold(self):
        self.assertEqual(_format_slice_expr(0, 4, 7), ':-3')

    def test_no_neg_when_distance_too_far(self):
        self.assertEqual(_format_slice_expr(0, 6, 10), ':6')

    def test_no_neg_when_k_is_four(self):
        self.assertEqual(_format_slice_expr(0, 96, 100), ':96')

    def test_neg3_with_long_string(self):
        self.assertEqual(_format_slice_expr(0, 97, 100), ':-3')


class TestIndexExprFormatting(unittest.TestCase):
    """Unit tests for _format_index_expr (canonical bare-index expression)."""

    def test_first_char(self):
        self.assertEqual(_format_index_expr(0, 10), '0')

    def test_middle_char(self):
        self.assertEqual(_format_index_expr(5, 11), '5')

    def test_last_char_uses_neg_one(self):
        self.assertEqual(_format_index_expr(9, 10), '-1')

    def test_second_to_last_uses_neg_two(self):
        self.assertEqual(_format_index_expr(8, 10), '-2')

    def test_third_to_last_uses_neg_three(self):
        self.assertEqual(_format_index_expr(7, 10), '-3')

    def test_no_neg_for_short_string(self):
        # n=2, last char idx=1, k=1. n > 2 is FALSE. Use '1'.
        self.assertEqual(_format_index_expr(1, 2), '1')

    def test_no_neg_when_distance_too_far(self):
        self.assertEqual(_format_index_expr(6, 10), '6')


class TestSliceLabelRendering(unittest.TestCase):
    """Tests that slice highlights carry labels matching the SELECTION EXPRESSION
    (with '·' (U+00B7 middle dot) substituted for omitted start/end, visually
    distinct from a negative-int label like '-1'). Labels mirror what the user
    typed/dragged into:
        '2:5'   -> labels '2' and '5'
        ':5'    -> labels '·' and '5'
        '5:'    -> labels '5' and '·'
        ':'     -> labels '·' and '·'
        ':-1'   -> labels '·' and '-1'
        '5:-3'  -> labels '5' and '-3'
        '5'     -> single centered label '5'
        '-1'    -> single centered label '-1'
    """

    def _slice_labels(self, search: str, value: str) -> list:
        highlights = parse_regex_for_highlighting(search, value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1, f'Expected 1 highlight for {search!r}')
        return highlights[0][3].split('|')

    def _index_label(self, search: str, value: str) -> str:
        highlights = parse_regex_for_highlighting(search, value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(len(highlights), 1, f'Expected 1 highlight for {search!r}')
        pat_str = highlights[0][3]
        self.assertNotIn('|', pat_str, f'Expected single (non-pipe) label for {search!r}')
        return pat_str

    def test_slice_highlight_uses_slice_seg_type(self):
        value = "hello world"
        highlights = parse_regex_for_highlighting('2:5', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(highlights[0][2], 'slice')

    def test_slice_labels_match_explicit_bounds(self):
        self.assertEqual(self._slice_labels('2:5', 'hello world'), ['2', '5'])

    def test_slice_labels_dot_for_omitted_start(self):
        self.assertEqual(self._slice_labels(':5', 'hello world'), ['·', '5'])

    def test_slice_labels_dot_for_omitted_end(self):
        self.assertEqual(self._slice_labels('5:', 'hello world'), ['5', '·'])

    def test_slice_labels_dot_for_both_omitted(self):
        self.assertEqual(self._slice_labels(':', 'hello world'), ['·', '·'])

    def test_slice_labels_negative_end(self):
        # ':-1' must render as '·' and '-1' (not the resolved positive)
        self.assertEqual(self._slice_labels(':-1', '0123456789'), ['·', '-1'])

    def test_slice_labels_negative_end_with_start(self):
        self.assertEqual(self._slice_labels('5:-3', '0123456789'), ['5', '-3'])

    def test_slice_labels_preserve_variable_expression(self):
        """Variable names in slice expressions are preserved as labels."""
        eis = lambda c, _l={'x': 2}: eval(c, {**_l, '__builtins__': __builtins__})
        highlights = parse_regex_for_highlighting('x:5', 'hello world', eval_in_scope=eis)
        self.assertEqual(highlights[0][3].split('|'), ['x', '5'])

    def test_index_highlight_single_label_matches_expression(self):
        self.assertEqual(self._index_label('2', 'hello'), '2')

    def test_index_highlight_negative_label_matches_expression(self):
        self.assertEqual(self._index_label('-1', 'hello'), '-1')

    # The index labels are now wrapped in a click-to-edit dropdown trigger
    # (snc-mouse-down attribute between the class and the closing `>`), so the
    # regexes use [^>]* to permit those extra attributes.

    def test_visualize_renders_slice_labels(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = '2:5'
        html_str = visualize(value, model, None, None)
        self.assertIn('index-label', html_str)
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>2<')
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>5<')

    def test_visualize_renders_dot_for_omitted_start(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = ':5'
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>\xb7<')
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>5<')

    def test_visualize_renders_dot_for_omitted_end(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = '5:'
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>5<')
        self.assertRegex(html_str, r'class="segment-label index-label[^"]*"[^>]*>\xb7<')

    def test_visualize_renders_negative_end_label(self):
        value = "0123456789"
        model = init_model(value)
        model['search'] = ':-1'
        html_str = visualize(value, model, None, None)
        labels = re.findall(r'class="segment-label index-label[^"]*"[^>]*>([^<]+)<', html_str)
        self.assertEqual(labels, ['·', '-1'])

    def test_visualize_renders_single_label_for_index(self):
        value = "hello"
        model = init_model(value)
        model['search'] = '2'
        html_str = visualize(value, model, None, None)
        labels = re.findall(r'class="segment-label index-label[^"]*"[^>]*>([^<]+)<', html_str)
        self.assertEqual(labels, ['2'])

    def test_visualize_renders_single_label_for_negative_index(self):
        value = "hello"
        model = init_model(value)
        model['search'] = '-1'
        html_str = visualize(value, model, None, None)
        labels = re.findall(r'class="segment-label index-label[^"]*"[^>]*>([^<]+)<', html_str)
        self.assertEqual(labels, ['-1'])


class TestSliceResizeHandles(unittest.TestCase):
    """Tests for resize handles on slice (index-mode) selections.

    Slice highlights get segment_index=0 (one segment per slice) so they're
    interactive, and the visualizer renders left+right handles like for
    literal regex segments. Dragging a handle reissues the slice expression
    canonically (with elision/negative-end shorthand re-applied).
    """

    def _start_handle_drag(self, value, search, side, cursor_internal_idx) -> dict:
        """Helper: set up a model mid-drag on the given slice's left/right handle."""
        model = init_model(value)
        model['search'] = search
        # Find the slice highlight to pick its segment_index (always 0).
        highlights = parse_regex_for_highlighting(search, value, eval_in_scope=lambda c: eval(c))
        self.assertGreater(len(highlights), 0, f'no highlight for {search!r}')
        model['handleDrag'] = {
            'segmentIndex': highlights[0][5] if highlights[0][5] is not None else 0,
            'side': side,
            'cursorIdx': cursor_internal_idx,
        }
        return model

    def test_slice_highlight_is_interactive(self):
        """Slice highlights need a non-None segment_index so handles can target them."""
        value = "hello world"
        highlights = parse_regex_for_highlighting('2:5', value, eval_in_scope=lambda c: eval(c))
        self.assertEqual(highlights[0][5], 0)

    def test_visualize_renders_handles_for_slice(self):
        """Slice selections render both a left and a right resize handle."""
        value = "hello world"
        model = init_model(value)
        model['search'] = '2:5'
        html_str = visualize(value, model, None, None)
        self.assertIn('chr-resize-handle left', html_str)
        self.assertIn('chr-resize-handle right', html_str)
        # Handles are wired to HandleMouseDown for segment 0.
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;left&#x27;, match_index=0)", html_str)
        self.assertIn("HandleMouseDown(segment_index=0, side=&#x27;right&#x27;, match_index=0)", html_str)

    def test_visualize_no_handles_for_single_index(self):
        """A bare-index pick (single centered label) does NOT render handles."""
        value = "hello"
        model = init_model(value)
        model['search'] = '2'
        html_str = visualize(value, model, None, None)
        self.assertNotIn('chr-resize-handle', html_str)

    def test_handle_drag_right_extends_slice(self):
        """Dragging the right handle past the current end extends the slice.

        Uses a long enough string that the negative-end shorthand does NOT
        kick in for the new end (so we can assert the bare '2:9' form).
        """
        value = "0123456789abcde"  # n=15
        # Drag right handle to internal 9 (cursor_idx -> string idx 9 included).
        model = self._start_handle_drag(value, '2:5', 'right', 9)
        ev = {'pythonEventStr': repr(MouseUp(9)), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['search'], '2:9')
        self.assertIsNone(model['handleDrag'])

    def test_handle_drag_left_shrinks_slice_start(self):
        """Dragging the left handle moves the slice's start position."""
        value = "hello world"
        model = self._start_handle_drag(value, '2:5', 'left', 5)
        # cursor internal 5 = 'o' (string idx 4). New start = 4.
        ev = {'pythonEventStr': repr(MouseUp(5)), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['search'], '4:5')

    def test_handle_drag_right_to_end_uses_end_elision(self):
        """Dragging right handle to the last char emits 'start:' (end elision)."""
        value = "hello world"  # n=11
        # Internal index 11 = 'd' (string idx 10, last char).
        model = self._start_handle_drag(value, '2:5', 'right', 11)
        ev = {'pythonEventStr': repr(MouseUp(11)), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['search'], '2:')

    def test_handle_drag_left_to_first_char_uses_start_elision(self):
        """Dragging left handle to the first char emits ':stop' (start elision)."""
        value = "hello world"
        # Internal index 1 = 'h' (string idx 0).
        model = self._start_handle_drag(value, '2:5', 'left', 1)
        ev = {'pythonEventStr': repr(MouseUp(1)), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['search'], ':5')

    def test_handle_drag_right_uses_neg_end_when_applicable(self):
        """Right-handle drag re-applies negative-end shorthand when threshold holds."""
        value = "0123456789"  # n=10
        # Start with ':3' (string 0..3). Drag right handle to internal 9 (string 8 = '8').
        # New end = string 9. k=1, n>2 -> ':-1'.
        model = self._start_handle_drag(value, ':3', 'right', 9)
        ev = {'pythonEventStr': repr(MouseUp(9)), 'eventJSON': {'buttons': 0}}
        model, _ = update(ev, ('x', 'x'), model, value)
        self.assertEqual(model['search'], ':-1')


class TestSliceLabelEditing(unittest.TestCase):
    """Slice/index labels are click-to-edit. Click a label opens a small
    one-input dropdown (re-using the openDropdown machinery) prefilled with
    that side's current value. Typing into the input fires SliceLabelInput
    which rewrites the slice expression - so '5' can be replaced with a
    variable name like 'n', or the elided '·' side filled in.

    Dropdown ID format: 'slice-label-{start|end|center}'.
    """

    # --- The trigger renders snc-mouse-down=DropdownToggle('slice-label-...') -

    def _label_trigger_events(self, html_str: str) -> list[str]:
        """Return the dropdown IDs targeted by snc-mouse-down on .index-label
        spans (i.e. the trigger events for the slice labels)."""
        return re.findall(
            r'<span class="segment-label index-label[^"]*"[^>]*'
            r'snc-mouse-down="DropdownToggle\(dropdown_id=&#x27;([^&]+)&#x27;\)"',
            html_str,
        )

    def test_slice_start_and_end_labels_are_clickable(self):
        value = "hello world"
        model = init_model(value)
        model['search'] = '2:5'
        html_str = visualize(value, model, None, None)
        self.assertEqual(self._label_trigger_events(html_str),
                         ['slice-label-start', 'slice-label-end'])

    def test_center_label_is_clickable(self):
        value = "hello"
        model = init_model(value)
        model['search'] = '2'
        html_str = visualize(value, model, None, None)
        self.assertEqual(self._label_trigger_events(html_str), ['slice-label-center'])

    # --- DropdownToggle seeds the input value from the current slice -------

    def _open_label(self, value, search, side):
        """Open the slice-label-{side} dropdown for the given search."""
        model = init_model(value)
        model['search'] = search
        ev = {'pythonEventStr': repr(DropdownToggle(f'slice-label-{side}')),
              'eventJSON': {}}
        model, _ = update(ev, None, model, value)
        return model

    def test_open_start_label_seeds_left_value(self):
        """Opening slice-label-start for '2:5' seeds dropdown value with '2'."""
        m = self._open_label("hello world", '2:5', 'start')
        od = m.get('openDropdown')
        self.assertIsNotNone(od)
        self.assertEqual(od.get('id'), 'slice-label-start')
        self.assertEqual(od.get('value'), '2')

    def test_open_end_label_seeds_right_value(self):
        m = self._open_label("hello world", '2:5', 'end')
        self.assertEqual(m['openDropdown'].get('value'), '5')

    def test_open_start_label_for_elided_seeds_empty(self):
        """For ':5', the start label's seeded value is '' (no left bound)."""
        m = self._open_label("hello world", ':5', 'start')
        self.assertEqual(m['openDropdown'].get('value'), '')

    def test_open_center_label_seeds_full_value(self):
        m = self._open_label("hello", '5', 'center')
        self.assertEqual(m['openDropdown'].get('value'), '5')

    # --- SliceLabelInput buffers; the slice is committed on close ----------

    def _type_label(self, model, value, side, typed):
        ev = {'pythonEventStr': repr(SliceLabelInput(side=side, value=typed)),
              'eventJSON': {}}
        return update(ev, None, model, value)[0]

    def _close_label(self, model, value, side):
        ev = {'pythonEventStr': repr(DropdownToggle(f'slice-label-{side}')),
              'eventJSON': {}}
        return update(ev, None, model, value)[0]

    def test_typing_into_start_label_does_not_change_search_yet(self):
        """Typing only buffers - the slice highlight (search) stays put.

        This is the whole point: we don't want a transient invalid expression
        to make the slice (and the popup) disappear mid-edit.
        """
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        self.assertEqual(m['search'], '2:5')  # unchanged
        self.assertEqual(m['openDropdown']['value'], 'n')
        self.assertIsNotNone(m.get('openDropdown'))

    def test_close_commits_buffered_start_value(self):
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        m = self._close_label(m, value, 'start')
        self.assertEqual(m['search'], 'n:5')
        self.assertIsNone(m.get('openDropdown'))

    def test_close_commits_buffered_end_value(self):
        value = "hello world"
        m = self._open_label(value, '2:5', 'end')
        m = self._type_label(m, value, 'end', 'n')
        m = self._close_label(m, value, 'end')
        self.assertEqual(m['search'], '2:n')

    def test_close_commits_buffered_center_value(self):
        value = "hello"
        m = self._open_label(value, '5', 'center')
        m = self._type_label(m, value, 'center', 'n')
        m = self._close_label(m, value, 'center')
        self.assertEqual(m['search'], 'n')

    def test_close_commits_empty_start_as_elided(self):
        """Clearing then closing collapses to ':5' (start elided)."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', '')
        m = self._close_label(m, value, 'start')
        self.assertEqual(m['search'], ':5')

    def test_close_commits_empty_end_as_elided(self):
        """Clearing then closing collapses to '2:' (end elided)."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'end')
        m = self._type_label(m, value, 'end', '')
        m = self._close_label(m, value, 'end')
        self.assertEqual(m['search'], '2:')

    def test_close_commits_fill_in_for_elided_start(self):
        """Filling in the start of ':5' then closing produces 'n:5'."""
        value = "hello world"
        m = self._open_label(value, ':5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        m = self._close_label(m, value, 'start')
        self.assertEqual(m['search'], 'n:5')

    def test_undo_saved_on_commit_only(self):
        """Undo entry is appended only when the dropdown closes (commit), not on each keystroke."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        self.assertNotIn('2:5', m.get('undoHistory', []))
        m = self._close_label(m, value, 'start')
        self.assertIn('2:5', m['undoHistory'])

    def test_typing_keeps_dropdown_open_for_further_edits(self):
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        self.assertIsNotNone(m.get('openDropdown'))
        self.assertEqual(m['openDropdown'].get('value'), 'n')

    def test_mousedown_elsewhere_commits_buffered_value(self):
        """A click on a char closes the popup AND commits the buffered value."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        ev = {
            'pythonEventStr': repr(MouseDown(3)),
            'eventJSON': {'altKey': False, 'shiftKey': False, 'ctrlKey': False,
                          'offsetY': 5, 'elementHeight': 20, 'buttons': 1},
        }
        m, _ = update(ev, ('x', 'x'), m, value)
        self.assertEqual(m['search'], 'n:5')
        self.assertIsNone(m.get('openDropdown'))

    def test_escape_discards_buffered_value(self):
        """Escape closes the popup WITHOUT committing - search stays put."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        m = self._type_label(m, value, 'start', 'n')
        ev = make_key_down_event('Escape')
        m, _ = update(ev, ('x', 'x'), m, value)
        self.assertEqual(m['search'], '2:5')  # unchanged
        self.assertIsNone(m.get('openDropdown'))

    # --- The dropdown panel renders an input prefilled with the value -------

    def test_visualize_renders_prefilled_input_when_label_dropdown_open(self):
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        html_str = visualize(value, m, None, None)
        # The panel contains an input with snc-input wired to SliceLabelInput
        # for side='start' and value='2' prefilled.
        self.assertRegex(html_str, r'snc-input="[^"]*SliceLabelInput[^"]*side=&#x27;start&#x27;')
        self.assertRegex(html_str, r'<input[^/]*snc-input="[^"]*SliceLabelInput[^"]*"[^/]*value="2"')

    def test_visualize_renders_empty_input_for_elided_side(self):
        value = "hello world"
        m = self._open_label(value, ':5', 'start')
        html_str = visualize(value, m, None, None)
        self.assertRegex(html_str, r'<input[^/]*snc-input="[^"]*SliceLabelInput[^"]*"[^/]*value=""')

    def test_visualize_input_has_autofocus_and_select_all(self):
        """The slice-label edit input must have autofocus + snc-select-all so
        the framework focuses it and selects its text on open - editing the
        label is the only thing the user can do here, so they should be able
        to immediately type a replacement."""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        html_str = visualize(value, m, None, None)
        self.assertRegex(
            html_str,
            r'<input[^/]*class="[^"]*slice-label-input[^"]*"[^/]*autofocus[^/]*snc-select-all',
        )

    # --- MouseDown elsewhere closes the slice-label dropdown ---------------

    def test_mousedown_elsewhere_closes_slice_label_dropdown(self):
        """The existing 'click closes openDropdown' behavior also dismisses
        a slice-label edit popup. (Commit behavior covered separately above.)"""
        value = "hello world"
        m = self._open_label(value, '2:5', 'start')
        ev = {
            'pythonEventStr': repr(MouseDown(3)),
            'eventJSON': {'altKey': False, 'shiftKey': False, 'ctrlKey': False,
                          'offsetY': 5, 'elementHeight': 20, 'buttons': 1},
        }
        m, _ = update(ev, ('x', 'x'), m, value)
        self.assertIsNone(m.get('openDropdown'))


# =============================================================================
# Segment Selection Tool Tests
# =============================================================================

class TestSegmentSelection(unittest.TestCase):
    """Tests for the segment selection tool (4th tool in the toolbar).

    With the segment tool active, only the first match is highlighted, and
    each visible feature of that match (start/end indices, prefix/suffix
    substrings, and capture groups) becomes a clickable chip with an
    snc-py-exps. Clicking chips toggles them into model['selectedSegments']
    and overwrites the Replace box with a simplified concat/tuple expression.
    """

    def _tool_select_event(self, tool: str) -> dict:
        return {
            'pythonEventStr': repr(ToolSelect(tool=tool)),
            'eventJSON': {},
        }

    def _segment_toggle_event(self, segment_id: str) -> dict:
        return {
            'pythonEventStr': repr(SegmentToggle(segment_id=segment_id)),
            'eventJSON': {},
        }

    # --- model + tool wiring ------------------------------------------------

    def test_init_model_includes_selected_segments_empty(self):
        model = init_model("hello")
        self.assertEqual(model.get('selectedSegments'), [])

    def test_tool_select_segment_sets_tool(self):
        value = "hello"
        model = init_model(value)
        model, _ = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertEqual(model['tool'], 'pick')

    def test_tool_select_segment_auto_opens_replace_box(self):
        value = "hello"
        model = init_model(value)
        self.assertFalse(model.get('replace_visible', False))
        model, _ = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertTrue(model.get('replace_visible'))

    def test_tool_select_pick_switches_linked_action_to_find_or_map(self):
        """Pick only makes sense with Map Matches, so switch the linked action to it."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        model['linked_action'] = 'match_strings'
        model['linked_source_expr'] = 'x'
        model['last_linked_expr'] = "re.findall(r'hello', x, flags=re.M)"
        model['auto_linked_once'] = True
        model, commands = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertEqual(model['linked_action'], 'find_or_map')
        self.assertTrue(model.get('replace_visible'))
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(
            change_cmds[0].expression,
            "list(re.finditer(r'hello', x, flags=re.M))",
        )

    def test_tool_select_pick_keeps_find_or_map_when_already_linked(self):
        """Entering Pick while already on find_or_map stays on Map Matches and opens replace."""
        value = "hello world"
        model = init_model(value)
        model['search'] = r"r'hello'"
        model['linked_action'] = 'find_or_map'
        model['linked_source_expr'] = 'x'
        model['last_linked_expr'] = "list(re.finditer(r'hello', x, flags=re.M))"
        model['auto_linked_once'] = True
        model, commands = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertEqual(model['linked_action'], 'find_or_map')
        self.assertTrue(model.get('replace_visible'))
        # No replace_text yet, so the generated find_or_map expr is unchanged.
        self.assertEqual(commands, [])

    def test_tool_select_segment_auto_enables_capgroups_for_multi_segment(self):
        """Multi-segment regex /(hello)(world)/ -> 'c' flag flips on entering segment."""
        value = "helloworld"
        model = init_model(value)
        model['search'] = r"r'hello.*world'"  # 3 segments after grouping
        model, _ = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertTrue(is_capture_groups_mode(model['search']))

    def test_tool_select_segment_does_not_enable_capgroups_for_single_segment(self):
        """Single-segment regex /hello/ -> 'c' flag stays off."""
        value = "hello"
        model = init_model(value)
        model['search'] = r"r'hello'"
        model, _ = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertFalse(is_capture_groups_mode(model['search']))

    def test_tool_select_segment_clears_stale_selections(self):
        value = "hello"
        model = init_model(value)
        model['selectedSegments'] = ['group_0']
        model, _ = update(self._tool_select_event('pick'), ('x', 'x'), model, value)
        self.assertEqual(model['selectedSegments'], [])

    def test_tool_select_away_from_segment_clears_selections(self):
        """Switching to another tool clears selections so they don't drive Replace."""
        value = "hello"
        model = init_model(value)
        model['tool'] = 'pick'
        model['selectedSegments'] = ['group_0']
        model, _ = update(self._tool_select_event('literal'), ('x', 'x'), model, value)
        self.assertEqual(model['selectedSegments'], [])

    # --- SegmentToggle event ------------------------------------------------

    def test_segment_toggle_adds_then_removes(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'1"  # first-match mode
        model, _ = update(self._segment_toggle_event('group_0'), ('x', 'x'), model, value)
        self.assertIn('group_0', model['selectedSegments'])
        model, _ = update(self._segment_toggle_event('group_0'), ('x', 'x'), model, value)
        self.assertNotIn('group_0', model['selectedSegments'])

    def test_segment_toggle_orders_canonically(self):
        """Toggling group_2 then group_1 produces the canonical [group_1, group_2]."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello) (world)'1c"
        model, _ = update(self._segment_toggle_event('group_2'), ('x', 'x'), model, value)
        model, _ = update(self._segment_toggle_event('group_1'), ('x', 'x'), model, value)
        self.assertEqual(model['selectedSegments'], ['group_1', 'group_2'])

    def test_segment_toggle_updates_replace_text_first_match(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello) (world)'1c"
        model, _ = update(self._segment_toggle_event('group_1'), ('x', 'x'), model, value)
        self.assertEqual(model['replace_text'], '$[1]')

    def test_segment_toggle_updates_replace_text_uses_first_match_flavor(self):
        """Replace text always uses the first-match flavor, even without '1' flag.

        Action buttons (Loop / Map / Find Indices / etc.) handle the multi-match
        wrapping; building list comprehensions here would double-wrap them.
        """
        value = "ab ab ab"
        model = init_model(value)
        model['tool'] = 'pick'
        # Cap groups on so segment chips operate on capture groups.
        model['search'] = r"r'(a)(b)'c"
        model, _ = update(self._segment_toggle_event('group_1'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '$[1]')

    def test_segment_toggle_clears_replace_text_when_empty(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello) (world)'1c"
        model, _ = update(self._segment_toggle_event('group_1'), ('x', 'x'), model, value)
        self.assertEqual(model['replace_text'], '$[1]')
        model, _ = update(self._segment_toggle_event('group_1'), ('x', 'x'), model, value)
        self.assertIsNone(model['replace_text'])

    def test_segment_toggle_auto_opens_replace_box(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'1"
        self.assertFalse(model.get('replace_visible', False))
        model, _ = update(self._segment_toggle_event('group_0'), ('x', 'x'), model, value)
        self.assertTrue(model['replace_visible'])

    # --- simplifications ----------------------------------------------------

    def test_simplify_all_groups_to_group_zero(self):
        """Selecting all capture groups collapses to $[0]."""
        value = "helloworld"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello)(world)'1c"
        model, _ = update(self._segment_toggle_event('group_1'), ('x', 'x'), model, value)
        model, _ = update(self._segment_toggle_event('group_2'), ('x', 'x'), model, value)
        self.assertEqual(model['replace_text'], '$[0]')

    def test_simplify_group0_plus_suffix_to_tail_slice(self):
        """{group_0, suffix} -> '<src>[$.start():]'."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'1"  # single segment, cap groups off
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('suffix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[$.start():]')

    def test_simplify_prefix_plus_group0_to_head_slice(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:$.end()]')

    def test_simplify_full_coverage_to_var_name(self):
        """{prefix, group_0, suffix} -> '<src>'."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'1"
        for sid in ('prefix', 'group_0', 'suffix'):
            model, _ = update(self._segment_toggle_event(sid), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1')

    def test_simplify_all_groups_then_suffix_to_tail_slice(self):
        """{all groups, suffix} should also collapse via group_0."""
        value = "helloworld!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello)(world)'1c"
        for sid in ('group_1', 'group_2', 'suffix'):
            model, _ = update(self._segment_toggle_event(sid), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[$.start():]')

    def test_adjacent_strings_join_with_plus(self):
        """Selecting prefix + group_1 (adjacent strings) joins with ' + '."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(world)'1c"
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('group_1'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:$.start()] + $[1]')

    def test_non_adjacent_strings_emit_tuple(self):
        """Non-adjacent strings (with a gap) -> tuple."""
        value = "abcdef"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(b)(c)(d)'1c"
        # Skip group_2 -> [group_1, group_3] is non-adjacent
        model, _ = update(self._segment_toggle_event('group_1'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('group_3'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '($[1], $[3])')

    def test_index_with_segment_emits_tuple(self):
        """Mixing an index (start/end) with a string segment yields a tuple."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello)'1c"
        model, _ = update(self._segment_toggle_event('start'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('group_1'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '($.start(), $[1])')

    def test_single_index_selection(self):
        """Selecting only the start index produces the bare expression."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        model, _ = update(self._segment_toggle_event('start'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '$.start()')

    def test_single_prefix_selection(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:$.start()]')

    def test_single_suffix_selection(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'1"
        model, _ = update(self._segment_toggle_event('suffix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[$.end():]')

    # --- toolbar rendering --------------------------------------------------

    def test_render_tool_toolbar_includes_pick_button(self):
        # 5 lines so the vertical (non-compact) toolbar is rendered
        value = "a\nb\nc\nd\ne"
        model = init_model(value)
        html_str = visualize(value, model, None, None)
        self.assertIn('data-tool="pick"', html_str)
        # The chip holds the pick-tool icon, drawn as an inline SVG.
        self.assertRegex(html_str, r'data-tool="pick"[^>]*><svg class="search-icon"')

    def test_pick_tool_button_dimmed_when_no_search(self):
        """The pick tool button is meaningless without a search, so dim it."""
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        # No search yet
        html_str = visualize(value, model, None, None)
        # The pick button has both the dimmed class AND no snc-mouse-down.
        self.assertRegex(
            html_str,
            r'<span class="tool-button dimmed"[^>]*data-tool="pick"[^>]*>',
        )
        self.assertNotRegex(
            html_str,
            r'data-tool="pick"[^>]*snc-mouse-down=',
        )

    def test_pick_tool_button_enabled_when_search(self):
        """With a search, the pick button is fully enabled."""
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        model['search'] = r"r'hello'"
        html_str = visualize(value, model, None, None)
        # Button is NOT dimmed and DOES have a click handler.
        self.assertNotRegex(
            html_str,
            r'<span class="tool-button dimmed"[^>]*data-tool="pick"',
        )
        self.assertRegex(
            html_str,
            r'data-tool="pick"[^>]*snc-mouse-down="ToolSelect',
        )

    def test_visualize_marks_pick_tool_active(self):
        value = "a\nb\nc\nd\ne"  # vertical layout
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'hello'"  # required so the tool button isn't dimmed
        html_str = visualize(value, model, None, None)
        # The pick tool's button should be the active one.
        self.assertRegex(
            html_str,
            r'class="tool-button active"[^>]*data-tool="pick"',
        )

    def test_visualize_adds_tool_pick_class_to_container(self):
        value = "hello"
        model = init_model(value)
        model['tool'] = 'pick'
        html_str = visualize(value, model, None, None)
        self.assertIn('pick-tool-selected', html_str)

    # --- segment-mode rendering ---------------------------------------------

    def test_visualize_segment_mode_only_highlights_first_match(self):
        """Even with multiple matches, only the first match's chars get highlighted."""
        value = "ab ab ab"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'ab'"  # matches 3x
        html_str = visualize(value, model, None, None)
        # There should be exactly one 'a' span with .highlight class for 'ab' literal,
        # but counting is awkward since spans wrap. As a proxy: count `highlight literal`
        # appearances. With 3 matches non-segment-mode you'd get many; with 1 match
        # you should get fewer than 6 (3 matches * 2 chars * 2 transitions).
        # Specifically the 2nd 'a' (string idx 3) should NOT be in any highlight.
        non_first_count = html_str.count('highlight literal')
        # In segment mode only the first match is highlighted, so highlight count
        # should be low (just the first match's chars and start/end markers).
        self.assertLess(non_first_count, 6,
                        f"Expected only first match highlighted, got {non_first_count} 'highlight literal' classes")

    def test_visualize_segment_mode_renders_start_chip_with_snc_py_exp(self):
        """Match start has a chip with snc-py-exps = '$.start()' (1st mode)."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        self.assertIn(exp_attr('$.start()'), html_str)

    def test_visualize_segment_mode_renders_end_chip_with_snc_py_exp(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        self.assertIn(exp_attr('$.end()'), html_str)

    def test_visualize_segment_mode_chips_have_segment_toggle_handlers(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        self.assertIn("SegmentToggle(segment_id=&#x27;start&#x27;)", html_str)
        self.assertIn("SegmentToggle(segment_id=&#x27;end&#x27;)", html_str)
        self.assertIn("SegmentToggle(segment_id=&#x27;group_0&#x27;)", html_str)

    def test_visualize_segment_mode_renders_prefix_suffix_regions(self):
        """Prefix and suffix substrings are highlighted as selectable regions."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        # Prefix and suffix get their own seg_type 'segment-region' highlight class.
        self.assertIn('segment-region', html_str)
        self.assertIn("SegmentToggle(segment_id=&#x27;prefix&#x27;)", html_str)
        self.assertIn("SegmentToggle(segment_id=&#x27;suffix&#x27;)", html_str)

    def test_visualize_segment_mode_no_search_renders_no_chips(self):
        """Without a search, segment mode shouldn't render any segment chips."""
        value = "hello"
        model = init_model(value)
        model['tool'] = 'pick'
        html_str = visualize(value, model, None, None)
        self.assertNotIn('SegmentToggle', html_str)

    def test_visualize_segment_mode_capgroups_on_renders_group_chips(self):
        """With cap groups on and multiple groups, each group has its own chip."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello) (world)'1c"
        html_str = visualize(value, model, None, None)
        self.assertIn("SegmentToggle(segment_id=&#x27;group_1&#x27;)", html_str)
        self.assertIn("SegmentToggle(segment_id=&#x27;group_2&#x27;)", html_str)

    # --- index / slice search support ---------------------------------------

    def test_segment_works_with_slice_search_replace_text(self):
        """Slice search /2:7/ - clicking group_0 puts str1[2:7] in Replace box."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[2:7]')

    def test_segment_works_with_slice_search_prefix(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:2]')

    def test_segment_works_with_slice_search_suffix(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('suffix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[7:]')

    def test_segment_works_with_slice_search_start_index(self):
        """Start label for a slice puts the start expression directly."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('start'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '2')

    def test_segment_works_with_slice_search_end_index(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('end'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '7')

    def test_segment_slice_simplify_full_coverage(self):
        """Selecting prefix+group_0+suffix in a slice search collapses to <src>."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        for sid in ('prefix', 'group_0', 'suffix'):
            model, _ = update(self._segment_toggle_event(sid), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1')

    def test_segment_slice_simplify_tail(self):
        """{group_0, suffix} in a slice search collapses to <src>[<start>:]."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('suffix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[2:]')

    def test_segment_slice_simplify_head(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:7]')

    def test_segment_works_with_index_search(self):
        """Single-index search '5' - group_0 = str[5]."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '5'
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[5]')

    def test_segment_works_with_index_search_prefix(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '5'
        model, _ = update(self._segment_toggle_event('prefix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[:5]')

    def test_segment_works_with_index_search_suffix(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '5'
        model, _ = update(self._segment_toggle_event('suffix'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[5+1:]')

    def test_segment_visualize_renders_for_slice_search(self):
        """Visualizer in segment mode for a slice search emits chips & py-exps."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        html_str = visualize(value, model, None, None)
        # group_0 char span carries the slice expression.
        self.assertRegex(
            html_str,
            rf'<span class="chr[^"]*"[^>]*{re.escape(exp_attr("str[2:7]"))}',
        )
        # start chip carries the literal start index.
        self.assertIn(exp_attr('2'), html_str)
        self.assertIn(exp_attr('7'), html_str)

    def test_segment_visualize_renders_for_index_search(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '5'
        html_str = visualize(value, model, None, None)
        self.assertRegex(
            html_str,
            rf'<span class="chr[^"]*"[^>]*{re.escape(exp_attr("str[5]"))}',
        )

    # --- literal string / string-expression searches ------------------------
    #
    # A literal search ('asdf' / "asdf") or an expression search evaluating to
    # a string (`x`) matches through re.finditer(re.escape(...)), so it has the
    # same match object the regex path picks from: start / end / prefix /
    # group_0 / suffix all apply. Only capture groups are unavailable.

    def test_segment_works_with_string_search_replace_text(self):
        """Literal search 'world' picks like a single-segment regex."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'world'1"
        model, _ = update(self._segment_toggle_event('group_0'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '$[0]')

    def test_visualize_renders_chips_for_string_search(self):
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'world'1"
        html_str = visualize(value, model, None, None)
        for seg_id in ('start', 'end', 'prefix', 'group_0', 'suffix'):
            self.assertIn(f"SegmentToggle(segment_id=&#x27;{seg_id}&#x27;)", html_str)

    def test_visualize_renders_chips_for_double_quoted_string_search(self):
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '"world"1'
        html_str = visualize(value, model, None, None)
        self.assertIn("SegmentToggle(segment_id=&#x27;group_0&#x27;)", html_str)

    def test_visualize_renders_chips_for_string_var_search(self):
        """A backtick expression evaluating to a string picks like a literal."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '`x`1'
        html_str = visualize(value, model, None, lambda c: eval(c, {'x': 'world'}))
        for seg_id in ('start', 'end', 'prefix', 'group_0', 'suffix'):
            self.assertIn(f"SegmentToggle(segment_id=&#x27;{seg_id}&#x27;)", html_str)

    def test_visualize_renders_chips_for_bare_string_var_search(self):
        """Bare (undelimited) expression text works the same as backticked."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = 'x'
        html_str = visualize(value, model, None, lambda c: eval(c, {'x': 'world'}))
        self.assertIn("SegmentToggle(segment_id=&#x27;group_0&#x27;)", html_str)

    def test_string_search_chip_exprs_are_first_match_flavor(self):
        """With the '1' flag the chips carry the match-object expressions."""
        value = "hello world!"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = "'world'1"
        html_str = visualize(value, model, None, None)
        self.assertIn(exp_attr('$[0]'), html_str)
        self.assertIn(exp_attr('$.start()'), html_str)
        self.assertIn(exp_attr('str1[:$.start()]'), html_str)
        self.assertIn(exp_attr('str1[$.end():]'), html_str)

    def test_visualize_string_search_only_first_match_gets_chips(self):
        """Multiple literal matches, but only the first one is pickable."""
        value = "ab ab ab"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'ab'"  # matches 3x
        html_str = visualize(value, model, None, None)
        # One 'segment-group' class per char of the FIRST match only (2 chars).
        self.assertEqual(html_str.count('segment-group'), 2)

    def test_string_search_multi_match_chip_exprs_use_finditer_list_comp(self):
        """Without the '1' flag a dragged-out chip covers every match."""
        value = "ab ab ab"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = "'ab'"
        html_str = visualize(value, model, None, None)
        self.assertIn(
            exp_attr("[m[0] for m in re.finditer(re.escape('ab'), str1)]"), html_str)
        self.assertIn(
            exp_attr("[m.start() for m in re.finditer(re.escape('ab'), str1)]"), html_str)

    def test_string_search_chip_finditer_matches_generated_code_flags(self):
        """Chip finditer calls spell flags the way Map Matches generates them.

        For a literal search that is `re.finditer(re.escape(s), src)` with no
        re.M (there are no anchors to make it mean anything), plus
        `, flags=re.I` when the search is case-insensitive.
        """
        value = "ab AB ab"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = "'ab'i"
        html_str = visualize(value, model, None, None)
        self.assertIn(
            exp_attr("[m[0] for m in re.finditer(re.escape('ab'), str1, flags=re.I)]"),
            html_str)

    def test_string_var_search_chip_exprs_reference_the_variable(self):
        value = "ab ab ab"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = '`x`'
        html_str = visualize(value, model, None, lambda c: eval(c, {'x': 'ab'}))
        self.assertIn(
            exp_attr("[m[0] for m in re.finditer(re.escape(x), str1)]"), html_str)

    def test_string_search_start_chip_labels_are_numeric_positions(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'world'1"  # match at positions 6..11
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>6</span>')
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>11</span>')

    def test_string_search_simplify_full_coverage(self):
        """{prefix, group_0, suffix} on a literal search collapses to <src>."""
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'world'1"
        for seg_id in ('prefix', 'group_0', 'suffix'):
            model, _ = update(self._segment_toggle_event(seg_id), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1')

    def test_string_search_simplify_tail(self):
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'hello'1"
        for seg_id in ('group_0', 'suffix'):
            model, _ = update(self._segment_toggle_event(seg_id), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], 'str1[$.start():]')

    def test_string_search_no_match_renders_no_chips(self):
        """A literal with no match has nothing to pick."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = "'nope'"
        html_str = visualize(value, model, None, None)
        self.assertNotIn('SegmentToggle', html_str)

    def test_multi_index_expression_search_renders_no_chips(self):
        """A list-of-ints search still has no first match to pick from."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '`[1, 3]`'
        html_str = visualize(value, model, None, lambda c: eval(c))
        self.assertNotIn('SegmentToggle', html_str)

    # --- snc-py-exps vs Replace box differ for multi-match regex -------------

    def test_chip_snc_py_exp_uses_list_comp_for_multi_match_regex(self):
        """For regex without '1' flag, snc-py-exps on chips should use the
        list-comp form so a dragged-out expression is fully self-contained.

        (The Replace box content from CLICKING the chip stays first-match flavor,
        because the action buttons handle the multi-match wrapping.)
        """
        value = "ab ab ab"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = r"r'(a)(b)'c"   # no '1' flag => multi-match
        html_str = visualize(value, model, ('str1', 'str1'), None)
        # Each capture group's wrapper carries a list-comprehension snc-py-exps.
        self.assertIn(exp_attr(FINDITER.format('[1]')), html_str)
        # And the start/end chips also carry list-comp form.
        self.assertIn(exp_attr(FINDITER.format('.start()')), html_str)

    def test_chip_snc_py_exp_uses_first_match_form_with_1_flag(self):
        """With '1' flag, snc-py-exps matches the Replace-box first-match form."""
        value = "ab ab ab"
        model = init_model(value)
        model['_source_expr'] = 'str1'
        model['tool'] = 'pick'
        model['search'] = r"r'(a)(b)'1c"
        html_str = visualize(value, model, ('str1', 'str1'), None)
        self.assertIn(exp_attr('$[1]'), html_str)
        self.assertIn(exp_attr('$.start()'), html_str)

    def test_replace_text_uses_first_match_even_for_multi_match_search(self):
        """Even when the search has no '1' flag, the Replace box uses first-match
        flavor (action buttons handle the multi-match wrapping)."""
        value = "ab ab ab"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(a)(b)'c"   # no '1' flag
        model, _ = update(self._segment_toggle_event('group_1'), ('str1', 'str1'), model, value)
        self.assertEqual(model['replace_text'], '$[1]')

    # --- start/end labels show numeric index --------------------------------

    def test_start_chip_label_is_numeric_position_for_regex(self):
        """Match start label is the numeric position in the source string."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"    # match at positions 6..11
        html_str = visualize(value, model, None, None)
        # The start chip's display text is "6", end chip's is "11".
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>6</span>')
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>11</span>')

    def test_start_chip_label_is_numeric_position_for_slice(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = '2:7'
        html_str = visualize(value, model, None, None)
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>2</span>')
        self.assertRegex(html_str, r'<span class="segment-chip[^"]*"[^>]*>7</span>')

    def test_chip_labels_no_longer_show_word_start_or_end(self):
        """Per spec: start/end chips show numeric index, not the literal words."""
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        # Within a segment-chip element, must not contain 'start' or 'end' as text.
        for m in re.finditer(r'<span class="segment-chip[^"]*"[^>]*>(.*?)</span>', html_str):
            self.assertNotEqual(m.group(1), 'start')
            self.assertNotEqual(m.group(1), 'end')

    def test_visualize_segment_mode_marks_selected_segments(self):
        value = "hello world"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'(hello)'1c"
        model['selectedSegments'] = ['group_1']
        html_str = visualize(value, model, None, None)
        self.assertIn('segment-selected', html_str)

    def test_visualize_segment_mode_snc_py_exp_on_char_spans_not_chips(self):
        """Per spec: snc-py-exps for prefix/group/suffix segments goes on the
        highlighted chr itself, not as a floating chip above.

        Only the start/end indices remain as floating labels.
        """
        value = "hello world!"
        model = init_model(value)
        model['tool'] = 'pick'
        model['search'] = r"r'world'1"
        html_str = visualize(value, model, None, None)
        # First match's char spans carry snc-py-exps pointing at $[0].
        self.assertRegex(
            html_str,
            rf'<span class="chr[^"]*"[^>]*{re.escape(exp_attr("$[0]"))}',
        )
        # Prefix char spans carry snc-py-exps for the slice expression.
        self.assertRegex(
            html_str,
            rf'<span class="chr[^"]*"[^>]*'
            rf'{re.escape(exp_attr("str[:$.start()]"))}',
        )
        # Suffix char spans carry snc-py-exps for the tail slice.
        self.assertRegex(
            html_str,
            rf'<span class="chr[^"]*"[^>]*'
            rf'{re.escape(exp_attr("str[$.end():]"))}',
        )
        # No floating chip with the segment's label expression text - only the
        # bare 'start' / 'end' index chips are allowed as floating labels.
        # Confirm no segment-chip element carries the prefix/suffix expressions.
        self.assertNotRegex(
            html_str,
            rf'<span class="segment-chip[^"]*"[^>]*'
            rf'{re.escape(exp_attr("str[:$.start()]"))}',
        )


# =============================================================================
# Pythonic r'pattern' Regex Syntax
# =============================================================================
#
# The search box uses Python's raw-string regex syntax to mirror what users
# write in real Python code (re.findall(r'pat', s)):
#   r'pattern'flags         single-quoted (preferred)
#   r"pattern"flags         double-quoted (when pattern contains ')
#   r'''pattern'''flags     triple single-quoted (when pattern contains ' and ")
#   r"""pattern"""flags     triple double-quoted (last resort)
#   R'pattern'              uppercase R also accepted
#
# Other prefixes (b'..', f'..', rb'..', fr'..', etc.) remain string literal
# searches; only a bare "r" / "R" prefix marks the value as a regex.

from string_visualizer import make_regex_search


class TestMakeRegexSearch(unittest.TestCase):
    """make_regex_search picks the smallest quoting that holds the pattern verbatim."""

    def test_simple_pattern_uses_single_quotes(self):
        self.assertEqual(make_regex_search('hello'), "r'hello'")

    def test_simple_pattern_with_flags(self):
        self.assertEqual(make_regex_search('hello', 'i'), "r'hello'i")

    def test_pattern_with_multiple_flags(self):
        self.assertEqual(make_regex_search('hello', '1i'), "r'hello'1i")

    def test_empty_pattern(self):
        self.assertEqual(make_regex_search(''), "r''")

    def test_pattern_with_single_quote_uses_double_quotes(self):
        self.assertEqual(make_regex_search("don't"), 'r"don\'t"')

    def test_pattern_with_double_quote_uses_single_quotes(self):
        self.assertEqual(make_regex_search('say "hi"'), 'r\'say "hi"\'')

    def test_pattern_with_both_quotes_uses_triple_single(self):
        self.assertEqual(make_regex_search('mix \' and "'), "r'''mix ' and \"'''")

    def test_regex_metacharacters_passed_through(self):
        self.assertEqual(make_regex_search(r'\d+\s+'), "r'\\d+\\s+'")

    def test_grouped_pattern(self):
        self.assertEqual(make_regex_search('(hello)(world)'), "r'(hello)(world)'")


class TestParseSearchTermRawString(unittest.TestCase):
    """parse_search_term recognizes r'pattern' / r\"pattern\" forms as regex."""

    def test_r_single_quote(self):
        self.assertEqual(parse_search_term("r'hello'"), ('regex', 'hello', ''))

    def test_r_double_quote(self):
        self.assertEqual(parse_search_term('r"hello"'), ('regex', 'hello', ''))

    def test_uppercase_r(self):
        self.assertEqual(parse_search_term("R'hello'"), ('regex', 'hello', ''))

    def test_r_with_flag(self):
        self.assertEqual(parse_search_term("r'hello'i"), ('regex', 'hello', 'i'))

    def test_r_with_multi_flag(self):
        self.assertEqual(parse_search_term("r'hello'1i"), ('regex', 'hello', '1i'))

    def test_r_triple_single(self):
        self.assertEqual(parse_search_term("r'''hello'''"), ('regex', 'hello', ''))

    def test_r_triple_double(self):
        self.assertEqual(parse_search_term('r"""hello"""1i'), ('regex', 'hello', '1i'))

    def test_r_with_regex_metacharacters(self):
        self.assertEqual(parse_search_term(r"r'(\d+)\s+'i"), ('regex', r'(\d+)\s+', 'i'))

    def test_empty_r_string(self):
        self.assertEqual(parse_search_term("r''"), ('regex', '', ''))

    def test_double_letter_prefix_still_string(self):
        """rb'..', br'..', fr'..', rf'..' are bytes/format raw strings, not regex."""
        self.assertEqual(parse_search_term("rb'hello'"), ('string', "rb'hello'", ''))
        self.assertEqual(parse_search_term("br'hello'"), ('string', "br'hello'", ''))
        self.assertEqual(parse_search_term("fr'hello'"), ('string', "fr'hello'", ''))
        self.assertEqual(parse_search_term("rf'hello'"), ('string', "rf'hello'", ''))

    def test_other_prefixes_still_string(self):
        self.assertEqual(parse_search_term("f'hello'"), ('string', "f'hello'", ''))
        self.assertEqual(parse_search_term("b'hello'"), ('string', "b'hello'", ''))


class TestIsRegexSearchRawString(unittest.TestCase):
    def test_r_single_quote_is_regex(self):
        self.assertTrue(is_regex_search("r'hello'"))

    def test_r_double_quote_is_regex(self):
        self.assertTrue(is_regex_search('r"hello"'))

    def test_uppercase_r_is_regex(self):
        self.assertTrue(is_regex_search("R'hello'"))

    def test_r_triple_quote_is_regex(self):
        self.assertTrue(is_regex_search("r'''hello'''"))

    def test_string_with_other_prefix_not_regex(self):
        self.assertFalse(is_regex_search("rb'hello'"))
        self.assertFalse(is_regex_search("f'hello'"))


class TestGetRegexInnerPatternRawString(unittest.TestCase):
    def test_r_single_quote(self):
        self.assertEqual(get_regex_inner_pattern("r'hello'"), 'hello')

    def test_r_double_quote(self):
        self.assertEqual(get_regex_inner_pattern('r"hello"'), 'hello')

    def test_r_triple_single(self):
        self.assertEqual(get_regex_inner_pattern("r'''hello'''"), 'hello')

    def test_r_with_flags(self):
        self.assertEqual(get_regex_inner_pattern("r'hello'1i"), 'hello')

    def test_string_returns_none(self):
        self.assertIsNone(get_regex_inner_pattern("'hello'"))


class TestGetSearchFlagsRawString(unittest.TestCase):
    def test_no_flags(self):
        self.assertEqual(get_search_flags("r'hello'"), '')

    def test_one_flag(self):
        self.assertEqual(get_search_flags("r'hello'i"), 'i')

    def test_multi_flag(self):
        self.assertEqual(get_search_flags("r'hello'1i"), '1i')

    def test_double_quoted_with_flags(self):
        self.assertEqual(get_search_flags('r"hello"1ic'), '1ic')


class TestEvalStringSearchIgnoresRawString(unittest.TestCase):
    """eval_string_search returns None for r'...' since those are regex now."""

    def test_r_single_quote(self):
        self.assertIsNone(eval_string_search("r'hello'"))

    def test_r_double_quote(self):
        self.assertIsNone(eval_string_search('r"hello"'))

    def test_other_prefixes_still_evaluate(self):
        self.assertEqual(eval_string_search("'hello'"), 'hello')


class TestCanonicalizeRegexEmitsRawString(unittest.TestCase):
    """canonicalize_regex outputs the new r'...' form."""

    def test_simple_pattern(self):
        self.assertEqual(canonicalize_regex("r'hello'"), "r'hello'")

    def test_strips_unneeded_groups(self):
        # Single-segment, no adjacent literals -> drop outer group
        self.assertEqual(canonicalize_regex("r'(hello)'"), "r'hello'")

    def test_keeps_groups_for_adjacent_literals(self):
        self.assertEqual(canonicalize_regex("r'(hello)(world)'"), "r'(hello)(world)'")

    def test_drops_groups_around_fuzzy(self):
        self.assertEqual(canonicalize_regex("r'(hello)(.*)(world)'"), "r'hello.*world'")


class TestEnsureAllGroupsEmitsRawString(unittest.TestCase):
    def test_wraps_each_segment(self):
        self.assertEqual(ensure_all_groups("r'hello.*world'"), "r'(hello)(.*)(world)'")

    def test_preserves_flags(self):
        self.assertEqual(ensure_all_groups("r'hello.*'i"), "r'(hello)(.*)'i")


class TestSelectionEmitsRawStringForm(unittest.TestCase):
    """Mouse selections should produce r'pattern' instead of /pattern/."""

    def setUp(self):
        self.value = "hello world"
        self.model = init_model(self.value)
        self.var_and_exp = ('x', 'x')

    def test_literal_selection_uses_raw_string_form(self):
        # Select 'hello' (indices 2-6 in legacy index space)
        model, _ = update(make_mouse_down_event(2, top_half=True),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_move_event(6),
                          self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_up_event(6),
                          self.var_and_exp, model, self.value)

        self.assertEqual(model['search'], "r'hello'")

    def test_fuzzy_selection_uses_raw_string_form(self):
        # Bottom-half drag selects ' ' (index 7) as a fuzzy whitespace segment
        model, _ = update(make_mouse_down_event(7, top_half=False),
                          self.var_and_exp, self.model, self.value)
        model, _ = update(make_mouse_up_event(7, alt_key=True),
                          self.var_and_exp, model, self.value)
        # Should be an r'\s+' style fuzzy
        self.assertTrue(model['search'].startswith("r'"))
        self.assertTrue(is_regex_search(model['search']))


class TestSearchBoxInputAcceptsRawString(unittest.TestCase):
    """Typing r'pattern' into the search box stores it and recognizes it as regex."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    def _input_event(self, val):
        return {
            'pythonEventStr': repr(SearchBoxInput(value=val)),
            'eventJSON': {},
        }

    def test_single_quoted_raw_string_input(self):
        model, _ = update(self._input_event("r'hello'"),
                          self.var_and_exp, init_model(self.value), self.value)
        self.assertEqual(model['search'], "r'hello'")
        self.assertTrue(is_regex_search(model['search']))

    def test_double_quoted_raw_string_input(self):
        model, _ = update(self._input_event('r"hello"'),
                          self.var_and_exp, init_model(self.value), self.value)
        self.assertEqual(model['search'], 'r"hello"')
        self.assertTrue(is_regex_search(model['search']))

    def test_raw_string_with_flags_input(self):
        model, _ = update(self._input_event("r'hello'1i"),
                          self.var_and_exp, init_model(self.value), self.value)
        self.assertEqual(model['search'], "r'hello'1i")
        self.assertTrue(is_first_match_mode(model['search']))
        self.assertTrue(is_case_insensitive(model['search']))

    def test_raw_string_highlighting(self):
        highlights = parse_regex_for_highlighting("r'hello'", self.value)
        self.assertEqual(len(highlights), 1)


class TestSearchToggleTooltips(unittest.TestCase):
    """The icon-only search toggles (capture groups, match case, first match)
    must carry data-tooltip attributes so the snc-tooltip system shows their
    name on hover (matches the tool toolbar pattern)."""

    def test_capture_groups_toggle_has_tooltip(self):
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        m = re.search(
            r'<span class="search-button [^"]*"([^>]*)snc-mouse-down="CaptureGroupsToggle',
            output,
        )
        self.assertIsNotNone(m, "CaptureGroupsToggle button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Use capture groups"', attrs)

    def test_case_sensitive_toggle_has_tooltip(self):
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        m = re.search(
            r'<span class="search-button [^"]*"([^>]*)snc-mouse-down="CaseSensitiveToggle',
            output,
        )
        self.assertIsNotNone(m, "CaseSensitiveToggle button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Match case"', attrs)

    def test_first_match_toggle_has_tooltip(self):
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        m = re.search(
            r'<span class="search-button [^"]*"([^>]*)snc-mouse-down="FirstMatchToggle',
            output,
        )
        self.assertIsNotNone(m, "FirstMatchToggle button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="First match only"', attrs)

    def test_dimmed_toggles_still_have_tooltip(self):
        """When index/slice forces toggles to be dimmed/non-interactive, they
        still carry their tooltip so users can discover what the icons mean."""
        model = init_model("hello world")
        model['search'] = '0'  # int index forces dimmed cap-groups + match-case
        output = visualize("hello world", model, None, None)
        dimmed_buttons = re.findall(
            r'<span class="search-button inactive dimmed"([^>]*)>',
            output,
        )
        self.assertTrue(dimmed_buttons, "Expected at least one dimmed search-button")
        for attrs in dimmed_buttons:
            self.assertIn('data-tooltip="', attrs,
                          f"Dimmed search-button missing data-tooltip: {attrs!r}")


class TestDisclosureButtonTooltip(unittest.TestCase):
    """The disclosure button (>) toggles the replace box; it's icon-only so
    needs an info tooltip describing what it does."""

    def test_disclosure_button_has_tooltip_when_collapsed(self):
        model = init_model("hello world")
        output = visualize("hello world", model, None, None)
        m = re.search(
            r'<span snc-mouse-down="ReplaceToggle\(\)"([^>]*)class="search-button disclosure-button"',
            output,
        )
        self.assertIsNotNone(m, "Disclosure button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Toggle replace/map/filter"', attrs)

    def test_disclosure_button_has_tooltip_when_expanded(self):
        model = init_model("hello world")
        model['replace_visible'] = True
        output = visualize("hello world", model, None, None)
        m = re.search(
            r'<span snc-mouse-down="ReplaceToggle\(\)"([^>]*)class="search-button disclosure-button"',
            output,
        )
        self.assertIsNotNone(m, "Disclosure button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Toggle replace/map/filter"', attrs)


from string_visualizer_grammar import generate_action, code_imports
from visualizer_utils import CHILD_SOURCE_BINDER


class TestNestedScopeRoundTrip(unittest.TestCase):
    """Nested in a cell, $ is the match and $$ is the string being searched.
    The replace box shows those; generated code shows neither."""

    def _nested_ctx(self, replace_text):
        from string_visualizer import _get_search_context
        model = init_model('foo bar')
        model['search'] = "r'foo'"
        model['replace_visible'] = True
        model['replace_text'] = replace_text
        return model, _get_search_context(
            model, (None, CHILD_SOURCE_BINDER),
            eval_in_scope=lambda code: eval(code))

    def test_generated_code_binds_both_levels(self):
        _model, ctx = self._nested_ctx('($$)[:$.start()]')
        code = generate_action('find_or_map', ctx)[1]
        self.assertEqual(
            code,
            "[(_snc_cell_)[:mtch.start()] for mtch in "
            "re.finditer(r'foo', _snc_cell_, flags=re.M)]")

    def test_parsing_generated_code_restores_the_dollar_levels(self):
        from string_visualizer import _ctx_to_model, parse_generated_code_or_assignment
        _model, ctx = self._nested_ctx('($$)[:$.start()]')
        code = generate_action('find_or_map', ctx)[1]
        parsed, _prefix = parse_generated_code_or_assignment(code)
        round_tripped = {}
        _ctx_to_model(parsed, round_tripped)
        self.assertEqual(round_tripped['replace_text'], '($$)[:$.start()]')

    def test_pick_builds_replace_text_in_dollar_levels(self):
        from string_visualizer import _build_segment_replace_text
        model = init_model('foo bar')
        model['search'] = "r'foo'"
        model['selectedSegments'] = ['suffix']
        self.assertEqual(
            _build_segment_replace_text(model, (None, CHILD_SOURCE_BINDER),
                                        'foo bar', lambda code: eval(code)),
            '$$[$.end():]')


class TestGeneratedCodeSaysWhatItNeeds(unittest.TestCase):
    """The grammar owns the templates that reach for the re module, so it is
    what declares the import. Nothing downstream reads the code to guess."""

    def imports(self, action, model_search, text='foo bar'):
        from string_visualizer import _get_search_context
        model = init_model(text)
        model['search'] = model_search
        ctx = _get_search_context(model, ('s', 's'),
                                  eval_in_scope=lambda code: eval(code))
        return code_imports(generate_action(action, ctx)[1])

    def test_a_search_needs_the_re_module(self):
        self.assertEqual(self.imports('find_or_map', "r'foo'"), ('import re',))

    def test_code_that_does_not_reach_for_re_needs_nothing(self):
        self.assertEqual(code_imports("s[1:3]"), ())
        self.assertEqual(code_imports("s.upper()"), ())

    def test_a_name_ending_in_re_is_not_the_module(self):
        self.assertEqual(code_imports("score.upper()"), ())


# === What the Find and Replace boxes say their dollars mean ==================
#
# The two boxes speak different languages, and only one of them speaks dollars
# at all. What `$` binds to in the Replace box turns on what was searched for:
# a regex or a piece of text matches through `re.finditer`, so `$` is a match
# object; an index or a slice reaches into the string directly, so `$` is the
# text that came back.

import html as _html
from string_visualizer import FIND_TOOLTIP, replace_scope


def _box_tooltip(html_str, needle):
    """The data-tooltip on the box whose tag holds *needle*."""
    for tag in re.findall(r'<input[^>]*>', html_str):
        if needle in tag:
            tip = re.search(r'data-tooltip="([^"]*)"', tag)
            return _html.unescape(tip.group(1)) if tip else None
    raise AssertionError(f'no box holding {needle!r}')


class TestSearchBoxLegends(unittest.TestCase):
    """The Find box takes no dollars -- what it takes is a pattern, an index or
    a slice, and a `$` typed into one is the regex anchor rather than a scope."""

    VALUE = 'hello world'

    def render(self, search=None):
        model = init_model(self.VALUE)
        model['replace_visible'] = True
        if search is not None:
            model['search'] = search
        return visualize(self.VALUE, model, None, lambda code: eval(code, {}),
                         max_width=600)

    def test_the_find_box_says_what_goes_in_it(self):
        self.assertEqual(_box_tooltip(self.render(), 'placeholder="Find"'),
                         FIND_TOOLTIP)

    def test_the_find_box_legend_never_calls_a_dollar_a_scope(self):
        # `$` there is the regex end anchor. Saying otherwise would teach the
        # wrong thing about the one box where a bare `$` is legal syntax.
        self.assertNotIn('$$', FIND_TOOLTIP)

    def test_a_regex_search_makes_the_replace_box_a_match(self):
        out = self.render("r'o'")
        self.assertEqual(_box_tooltip(out, 'search-box-replace'), replace_scope(False).legend)

    def test_the_match_legend_points_at_the_matched_text(self):
        # `$` is an re.Match, so the text is a subscript away -- the one thing
        # a user writing a replacement needs to be told.
        self.assertIn('$[0]', replace_scope(False).legend)

    def test_a_slice_search_makes_the_replace_box_the_text_itself(self):
        out = self.render('2:5')
        self.assertEqual(_box_tooltip(out, 'search-box-replace'),
                         replace_scope(True).legend)

    def test_an_index_search_does_the_same(self):
        out = self.render('4')
        self.assertEqual(_box_tooltip(out, 'search-box-replace'),
                         replace_scope(True).legend)

    def test_either_way_the_outer_run_is_the_whole_string(self):
        for legend in (replace_scope(False).legend, replace_scope(True).legend):
            with self.subTest(legend=legend):
                self.assertIn('$$ the whole string', legend)


class TestActionsReadDownEveryRow(unittest.TestCase):
    """A string in a table's CELL: an action is two questions at once.

    Clicking one always generalized -- the code goes up and becomes a column,
    one expression every row answers. Only the PREVIEW named a single row, so
    the button offered `re.split(r',', parts[0], ...)` while the column it was
    about to write said `re.split(r',', $, ...)`. Both readings are offered now.
    """

    import json as _json
    import html as _html
    import re as _re

    VALUE = 'id,name,age'
    ROWS = [VALUE, 'a,b,c']

    def every_row(self, column_expr):
        """Stands in for the table lifting a column expression."""
        return [f'[{column_expr.replace("$", "item")} for item in parts]']

    def render(self, every_row=True):
        from string_visualizer import _render_action_buttons
        scope = {'parts': self.ROWS, 're': re}
        eval_in_scope = lambda code: eval(code, scope)
        model = init_model(self.VALUE, None, eval_in_scope=eval_in_scope,
                           var_and_exp=(None, 'parts[0]'))
        model['_source_expr'] = 'parts[0]'
        model['search'] = "r','"
        return _render_action_buttons(
            model, self.VALUE, eval_in_scope, None,
            self.every_row if every_row else None)

    def action_exps(self, out):
        return [[e['expr'] for e in self._json.loads(self._html.unescape(a))]
                for a in self._re.findall(r'data-action-expr="([^"]*)"', out)]

    def test_split_offers_the_every_row_reading_too(self):
        pairs = [e for e in self.action_exps(self.render())
                 if e and e[0].startswith('re.split(')]
        self.assertEqual(
            pairs,
            [["re.split(r',', parts[0], flags=re.M)",
              "[re.split(r',', item, flags=re.M) for item in parts]"]])

    def test_this_rows_answer_is_what_the_button_hands_over(self):
        # The user is looking at THIS string; the column reading is the extra.
        for exps in self.action_exps(self.render()):
            if len(exps) > 1:
                self.assertNotIn(' for item in parts]', exps[0])

    def test_with_no_table_above_there_is_only_the_one_reading(self):
        for exps in self.action_exps(self.render(every_row=False)):
            self.assertEqual(len(exps), 1)



class TestLiveOnly(unittest.TestCase):
    """Under clickacode.liveOnlyVisualizers the focused string is a plain preview:
    the text and the expand bar, none of the machinery that builds code."""

    def setUp(self):
        from visualizer_utils import set_live_only
        set_live_only(True)

    def tearDown(self):
        from visualizer_utils import set_live_only
        set_live_only(False)

    def render(self, value, small=False):
        model = init_model(value)
        return visualize(value, model, None, lambda c: eval(c), small=small,
                         var_and_exp=('str1', 'str1'))

    def test_focused_render_has_no_code_affordances(self):
        out = self.render("hello world")
        self.assertIn('hello world', out)
        for marker in ('snc-py-exps', 'data-action-expr', 'snc-mouse-down',
                       'snc-input', 'snc-add-at-cursor', 'action-button',
                       'tool-toolbar', 'search-box', 'draggable="true"', 'py-exp-grab',
                       'snc-key-down'):
            self.assertNotIn(marker, out, marker)

    def test_focused_render_keeps_the_expand_bar_for_a_tall_string(self):
        # The counts don't come with it: they ride the search box, which a
        # live-only render doesn't draw.
        out = self.render("a\nb\nc\nd\ne\nf")
        self.assertIn('expand-and-len', out)
        self.assertNotIn('tiny-len', out)
        self.assertNotIn('snc-py-exps', out)

    def test_small_render_has_no_drag_handle(self):
        out = self.render("hello", small=True)
        self.assertIn('hello', out)
        self.assertNotIn('snc-py-exps', out)
        self.assertNotIn('py-exp-grab', out)


# =============================================================================
# Fetch Menu
# =============================================================================
#
# A string that names a place to read from -- a URL, a path -- is one read away
# from the value it stands for. Dragging the file or the URL in writes that read
# (pythonDropProvider.ts); the Fetch menu writes the same read for a string the
# program has already got hold of.

import os as _os
import tempfile as _tempfile

from string_visualizer import FetchClick


def make_fetch_event(source: str, fmt: str) -> dict:
    """Create a FetchClick event dict."""
    return {
        'pythonEventStr': repr(FetchClick(source=source, fmt=fmt)),
        'eventJSON': {},
    }


def fetch_event_attr(source: str, fmt: str) -> str:
    """The mousedown attribute value a Fetch row carries, as it reads in HTML."""
    import html as _html
    return _html.escape(repr(FetchClick(source=source, fmt=fmt)))


class TestFetchMenuWrites(unittest.TestCase):
    """The line each Fetch row writes, and what it says it can't run without."""

    URL = 'https://example.com/data.json'

    def fetch(self, source, fmt, value=None, var_and_exp=('url1', 'url1')):
        value = self.URL if value is None else value
        model = init_model(value, var_and_exp=var_and_exp)
        _, commands = update(make_fetch_event(source, fmt), var_and_exp,
                             model, value)
        self.assertEqual(len(commands), 1)
        return commands[0]

    def test_a_url_as_a_string(self):
        cmd = self.fetch('url', 'text')
        self.assertEqual(cmd[:2],
                         ('url1_text',
                          'urllib.request.urlopen(url1).read().decode()'))
        self.assertEqual(cmd[2], ('import urllib.request',))

    def test_a_url_as_json(self):
        cmd = self.fetch('url', 'json')
        self.assertEqual(cmd[:2],
                         ('url1_data', 'json.load(urllib.request.urlopen(url1))'))
        self.assertEqual(cmd[2], ('import json', 'import urllib.request'))

    def test_a_file_as_a_string(self):
        cmd = self.fetch('file', 'text', var_and_exp=('path1', 'path1'))
        self.assertEqual(cmd[:2], ('path1_text', 'open(path1).read()'))
        self.assertEqual(len(cmd), 2, 'a builtin read needs no import')

    def test_a_file_as_csv(self):
        cmd = self.fetch('file', 'csv', var_and_exp=('path1', 'path1'))
        self.assertEqual(cmd[:2],
                         ('path1_rows',
                          "list(csv.reader(open(path1, newline='')))"))
        self.assertEqual(cmd[2], ('import csv',))

    def test_a_file_as_json(self):
        cmd = self.fetch('file', 'json', var_and_exp=('path1', 'path1'))
        self.assertEqual(cmd[:2], ('path1_data', 'json.load(open(path1))'))
        self.assertEqual(cmd[2], ('import json',))

    def test_a_file_as_excel(self):
        # Every sheet, because which one holds the data isn't ours to guess --
        # the same read the drop provider writes for a dropped spreadsheet.
        cmd = self.fetch('file', 'excel', var_and_exp=('path1', 'path1'))
        self.assertEqual(
            cmd[:2],
            ('path1_sheets',
             "{sheet_name: pd.read_excel(path1, sheet_name=sheet_name)"
             ".to_dict('records') for sheet_name in "
             "pd.ExcelFile(path1).sheet_names}"))
        self.assertEqual(cmd[2], ('import pandas as pd',))

    def test_a_string_with_no_name_of_its_own_writes_a_result(self):
        cmd = self.fetch('url', 'text', var_and_exp=(None, "rows[0]['url']"))
        self.assertEqual(
            cmd[:2],
            ('result_text',
             "urllib.request.urlopen(rows[0]['url']).read().decode()"))

    def test_a_cell_reads_by_the_binder_and_names_a_result(self):
        # Nested in a table cell the value is bound to a name the parent
        # substitutes into, which is no name to call the answer by.
        from visualizer_utils import CHILD_SOURCE_BINDER as binder
        cmd = self.fetch('url', 'text', var_and_exp=(None, binder))
        self.assertEqual(cmd[0], 'result_text')
        self.assertEqual(cmd[1],
                         f'urllib.request.urlopen({binder}).read().decode()')

    def test_a_fetch_leaves_a_linked_line_alone(self):
        # Reading what the string names is about the string rather than about
        # the search, so it writes a line of its own and rewrites nothing.
        value = self.URL
        var_and_exp = ('url1', 'url1')
        model = init_model(value, var_and_exp=var_and_exp)
        model['search'] = r"r'example'"
        model['linked_action'] = 'find_or_map'
        model['linked_source_expr'] = 'url1'
        model['auto_linked_once'] = True
        _, commands = update(make_fetch_event('url', 'text'), var_and_exp,
                             model, value)
        self.assertEqual([type(c) for c in commands], [tuple])
        self.assertEqual(model['linked_action'], 'find_or_map')


class TestFetchMenuRender(unittest.TestCase):
    """Which rows the menu offers live, read off the string itself."""

    URL = 'https://example.com/data.json'

    def setUp(self):
        self.dir = _tempfile.TemporaryDirectory()
        self.path = _os.path.join(self.dir.name, 'data.csv')
        with open(self.path, 'w') as f:
            f.write('a,b\n1,2\n')

    def tearDown(self):
        self.dir.cleanup()

    def render(self, value, var_and_exp=('str1', 'str1')):
        model = init_model(value, var_and_exp=var_and_exp)
        return visualize(value, model, None, lambda c: eval(c), max_width=400,
                         var_and_exp=var_and_exp)

    def submenu_class(self, out, label):
        """The classes on the row that opens *label*'s submenu."""
        m = re.search(r'<div class="([^"]*)"><div class="snc-dropdown-option">'
                      r'<span class="snc-dropdown-option-label">' + label, out)
        return m.group(1).split() if m else None

    def test_the_button_is_there_for_any_string(self):
        out = self.render('hello world')
        self.assertIn('>Fetch<', out)
        self.assertIn('Fetch URL', out)
        self.assertIn('Read Filepath', out)

    def test_a_string_that_names_nowhere_dims_the_button(self):
        out = self.render('hello world')
        m = re.search(r'<span class="([^"]*)"><span class="action-button">'
                      r'<span class="text">Fetch</span>', out)
        self.assertIsNotNone(m)
        self.assertIn('dimmed', m.group(1).split())
        self.assertIn('dimmed', self.submenu_class(out, 'Fetch URL'))
        self.assertIn('dimmed', self.submenu_class(out, 'Read Filepath'))

    def test_a_url_lights_the_url_rows_only(self):
        out = self.render(self.URL, var_and_exp=('url1', 'url1'))
        self.assertNotIn('dimmed', self.submenu_class(out, 'Fetch URL'))
        self.assertIn('dimmed', self.submenu_class(out, 'Read Filepath'))
        self.assertIn(fetch_event_attr('url', 'json'), out)

    def test_a_path_to_a_file_that_is_there_lights_the_file_rows_only(self):
        out = self.render(self.path, var_and_exp=('path1', 'path1'))
        self.assertNotIn('dimmed', self.submenu_class(out, 'Read Filepath'))
        self.assertIn('dimmed', self.submenu_class(out, 'Fetch URL'))

    def test_a_path_to_a_file_that_is_not_there_is_no_path(self):
        out = self.render(_os.path.join(self.dir.name, 'gone.csv'),
                          var_and_exp=('path1', 'path1'))
        self.assertIn('dimmed', self.submenu_class(out, 'Read Filepath'))

    def test_a_long_string_is_asked_of_the_filesystem_without_raising(self):
        # A path too long to be one is not one; the OS says so by raising,
        # which is the same no.
        out = self.render('x' * 5000 + '\nmore', var_and_exp=('str1', 'str1'))
        self.assertIn('dimmed', self.submenu_class(out, 'Read Filepath'))

    def test_a_live_row_hands_over_the_code_it_would_write(self):
        out = self.render(self.path, var_and_exp=('path1', 'path1'))
        self.assertIn(exp_attr(PyExp("list(csv.reader(open(path1, newline='')))",
                                     ('import csv',))), out)

    def test_a_dimmed_row_hands_over_nothing(self):
        out = self.render('hello world')
        self.assertNotIn('urlopen', out)

    def button_event(self, out):
        """The mousedown event on the Fetch button itself, or None."""
        m = re.search(r'<span class="[^"]*"><span ([^>]*)class="action-button"[^>]*>'
                      r'<span class="text">Fetch</span>', out)
        self.assertIsNotNone(m)
        e = re.search(r'snc-mouse-down="([^"]*)"', m.group(1))
        return _html.unescape(e.group(1)) if e else None

    def test_a_click_on_the_button_reads_a_url_as_a_string(self):
        out = self.render(self.URL, var_and_exp=('url1', 'url1'))
        self.assertEqual(self.button_event(out), repr(FetchClick(source='url', fmt='text')))

    def test_a_click_on_the_button_reads_a_file_as_a_string(self):
        out = self.render(self.path, var_and_exp=('path1', 'path1'))
        self.assertEqual(self.button_event(out), repr(FetchClick(source='file', fmt='text')))

    def test_a_click_on_the_button_does_nothing_for_a_string_naming_nowhere(self):
        out = self.render('hello world')
        self.assertIsNone(self.button_event(out))

    def test_the_menu_is_a_hover_menu_with_hover_submenus(self):
        # The CSS opens the submenus (a hover menu is a static clone the front
        # end positions, and nothing walks into one looking for triggers), so
        # the shape it keys off is part of what this renders.
        out = self.render(self.URL, var_and_exp=('url1', 'url1'))
        self.assertIn('snc-dropdown-panel left fetch-menu-panel has-submenu"'
                      ' snc-dropdown-align="left" data-hover-menu', out)
        self.assertIn('snc-dropdown-panel flyout fetch-format-panel"'
                      ' snc-dropdown-align="flyout" data-hover-menu', out)


# =============================================================================
# What a menu row reads as, when the string is a cell
# =============================================================================
#
# A row of a menu is a button like the ones beside it: clicked in a table's
# cell, what it writes becomes a COLUMN. So its handle has the same two
# readings a button's has -- this row's answer, and the column's -- and says
# which is which. A row whose code is a statement has only the one: a column
# holds an expression, so there is no list reading to offer.

import html as _html_mod
import json as _json

from visualizer_utils import label_readings


class TestMenuRowReadings(unittest.TestCase):

    def every_row(self, sub_expr):
        """Stands in for the table: a column expression, read down the list."""
        return [f'[{sub_expr.replace("$", "item")} for item in x]']

    def render(self, value, var_and_exp, every_row=True, **model_keys):
        model = init_model(value, var_and_exp=var_and_exp)
        model.update(model_keys)
        return visualize(value, model, None, lambda c: eval(c, {'re': re}),
                         max_width=400, var_and_exp=var_and_exp,
                         every_row_exps=self.every_row if every_row else None)

    def readings(self, out, label):
        """What the menu row labelled *label* offers, as the tooltip gets it."""
        m = re.search(r'<div class="snc-dropdown-option[^"]*" '
                      r'snc-py-exps="([^"]*)"[^>]*><span snc-mouse-down="[^"]*"'
                      r' class="snc-dropdown-option-label">' + re.escape(label),
                      out)
        return _json.loads(_html_mod.unescape(m.group(1))) if m else None

    # --- Fetch --------------------------------------------------------------

    def fetch_render(self, **kw):
        d = _tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = _os.path.join(d.name, 'data.csv')
        with open(path, 'w') as f:
            f.write('a,b\n')
        return self.render(path, (None, "rows[0]"), **kw), path

    def test_a_fetch_row_offers_the_column_it_would_write(self):
        out, path = self.fetch_render()
        self.assertIn(
            py_exp_attrs(label_readings(
                PyExp('open(rows[0]).read()'),
                [PyExp('[open(item).read() for item in x]')]),
                draggable=False, align='right').strip(),
            out)

    def test_a_fetch_rows_column_reading_carries_the_import_too(self):
        # The column is evaluated in the user's scope, so a read that names a
        # module needs it there whichever reading is taken.
        out, _path = self.fetch_render()
        csv_row = self.readings(out, 'as CSV')
        self.assertEqual([r['label'] for r in csv_row], ['One', 'List'])
        self.assertEqual(csv_row[1]['imports'], ['import csv'])

    def test_with_no_table_above_a_fetch_row_has_the_one_reading(self):
        out, _path = self.fetch_render(every_row=False)
        rows = self.readings(out, 'as string')
        self.assertEqual([r.get('label') for r in rows], [None])

    # --- Any/All and Loop ---------------------------------------------------

    def predicate_render(self, **kw):
        return self.render('foo bar', ('str1', 'str1'), search=r"r'foo'", **kw)

    def test_a_predicate_row_offers_the_column_it_would_write(self):
        rows = self.readings(self.predicate_render(), 'Any')
        self.assertEqual([r['label'] for r in rows], ['One', 'List'])
        self.assertTrue(rows[1]['expr'].endswith('for item in x]'),
                        rows[1]['expr'])

    def test_a_row_that_writes_a_statement_has_no_column_reading(self):
        # `if any(...):` is a line and only ever a line -- a column holds an
        # expression, so there is nothing here to read down a list.
        rows = self.readings(self.predicate_render(), 'If Any')
        self.assertEqual([r.get('label') for r in rows], [None])

    def test_a_loop_row_writes_a_statement_too(self):
        rows = self.readings(self.predicate_render(), 'Over match objects')
        self.assertEqual([r.get('label') for r in rows], [None])


# =============================================================================
# Every Match Is A Place To Work From
# =============================================================================

class TestEveryMatchCarriesSegmentIndices(unittest.TestCase):
    """Highlights name their pattern segment AND which occurrence they are.

    A segment index is a position in the *pattern*, so it is the same number in
    every match; the match index is what tells two occurrences of it apart.
    """

    def test_each_occurrence_gets_the_same_segment_index(self):
        highlights = parse_regex_for_highlighting(r"r'(ab)'", 'ab ab ab')
        self.assertEqual([h[5] for h in highlights], [0, 0, 0])
        self.assertEqual([h[6] for h in highlights], [0, 1, 2])

    def test_multi_segment_pattern_numbers_segments_within_each_match(self):
        highlights = parse_regex_for_highlighting(r"r'(a)(b)'", 'ab ab')
        self.assertEqual([h[5] for h in highlights], [0, 1, 0, 1])
        self.assertEqual([h[6] for h in highlights], [0, 0, 1, 1])

    def test_first_match_mode_still_yields_one_match(self):
        highlights = parse_regex_for_highlighting(r"r'(ab)'1", 'ab ab ab')
        self.assertEqual([h[6] for h in highlights], [0])


class TestExtendFromAnyMatch(unittest.TestCase):
    """Clicking beside any occurrence extends the regex, rather than throwing
    it away and starting a new selection from that spot."""

    var_and_exp = ('str1', 'str1')

    def down_up(self, model, value, idx, top_half=True):
        model, _ = update(make_mouse_down_event(idx, top_half=top_half, legacy_index=False),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(idx, legacy_index=False),
                          self.var_and_exp, model, value)
        return model

    def test_click_right_of_the_last_match_appends_a_segment(self):
        # 'foo1 foo2 foo3': internal index = string index + 1, so the '3' of the
        # third match sits at 14, right where that match ends.
        value = 'foo1 foo2 foo3'
        model = init_model(value)
        model['search'] = r"r'(foo)'"
        model = self.down_up(model, value, 14)
        self.assertEqual(model['search'], r"r'(foo)(3)'")

    def test_click_right_of_a_middle_match_appends_a_segment(self):
        value = 'foo1 foo2 foo3'
        model = init_model(value)
        model['search'] = r"r'(foo)'"
        model = self.down_up(model, value, 9)  # the '2' of the second match
        self.assertEqual(model['search'], r"r'(foo)(2)'")

    def test_click_left_of_a_later_match_prepends_a_segment(self):
        # 'xfoo yfoo': the 'y' at internal 6 abuts the second match's start (7).
        value = 'xfoo yfoo'
        model = init_model(value)
        model['search'] = r"r'(foo)'"
        model = self.down_up(model, value, 6)
        self.assertEqual(model['search'], r"r'(y)(foo)'")

    def test_click_inside_a_later_matchs_fuzzy_segment_opens_its_menu(self):
        # 'a1b\na2b': the second match's (.*) covers the '2' at internal 8.
        value = 'a1b\na2b'
        model = init_model(value)
        model['search'] = r"r'(a)(.*)(b)'"
        model, _ = update(make_mouse_down_event(8, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['openDropdown']['id'], 'segment-menu-1-1')
        self.assertEqual(model['search'], r"r'(a)(.*)(b)'")

    def test_a_click_that_abuts_nothing_still_starts_over(self):
        # 'foo1   foo2': internal 6 is the middle of the three spaces, touching
        # neither the first match (ends at 4) nor the second (starts at 8).
        value = 'foo1   foo2'
        model = init_model(value)
        model['search'] = r"r'(foo)'"
        model = self.down_up(model, value, 6)
        self.assertEqual(model['search'], r"r'\ '")


class TestHandleDragOnAnyMatch(unittest.TestCase):
    """A resize handle resizes its own occurrence's span, not the first one's."""

    var_and_exp = ('str1', 'str1')

    def test_dragging_the_second_matchs_right_handle_uses_that_match(self):
        # 'a1 a2': the second 'a' is at internal 4, its '2' at 5.
        value = 'a1 a2'
        model = init_model(value)
        model['search'] = r"r'(a)'"
        model, _ = update(make_handle_mouse_down_event(0, 'right', match_index=1),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(5, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'(a2)'")

    def test_dragging_the_first_matchs_right_handle_still_uses_the_first(self):
        value = 'a1 a2'
        model = init_model(value)
        model['search'] = r"r'(a)'"
        model, _ = update(make_handle_mouse_down_event(0, 'right', match_index=0),
                          self.var_and_exp, model, value)
        model, _ = update(make_mouse_up_event(2, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertEqual(model['search'], r"r'(a1)'")


class TestEveryMatchLooksTheSame(unittest.TestCase):
    """No occurrence is rendered as the privileged one."""

    def rendered(self, value, search, **model_kw):
        model = init_model(value)
        model['search'] = search
        model.update(model_kw)
        return visualize(value, model, None, None)

    def test_every_matched_char_is_interactive(self):
        out = self.rendered('ab ab', r"r'(ab)'")
        self.assertEqual(out.count('is-interactive'), 4)

    def test_idle_matches_offer_no_resize_handles(self):
        # Uniformity holds the other way now: no match has handles until one
        # is made active by pointing at it (TestHandlesOnlyOnActiveSegment).
        out = self.rendered('ab ab', r"r'(ab)'")
        self.assertEqual(out.count('chr-resize-handle'), 0)

    def test_pick_mode_still_singles_out_the_first_match(self):
        out = self.rendered('ab ab', r"r'(ab)'", tool='pick')
        self.assertEqual(out.count('segment-group'), 2)  # one match, 2 chars


class TestScrollToFirstMatch(unittest.TestCase):
    """The first match is scrolled into view when the user did not point at
    one themselves -- typing a search, or switching to the pick tool."""

    var_and_exp = ('str1', 'str1')

    def scroll_target_index(self, html_out):
        """The internal index of the char carrying snc-scroll-to-match."""
        m = re.search(r'snc-idx="(\d+)"[^>]*snc-scroll-to-match', html_out)
        return int(m.group(1)) if m else None

    def test_selecting_the_pick_tool_scrolls_to_the_match(self):
        value = 'x' * 200 + 'needle'
        model = init_model(value)
        model['search'] = r"r'(needle)'"
        model, _ = update({'pythonEventStr': repr(ToolSelect(tool='pick')),
                           'eventJSON': {}},
                          self.var_and_exp, model, value)
        self.assertTrue(model['_scroll_to_match'])
        out = visualize(value, model, None, None)
        self.assertEqual(self.scroll_target_index(out), 201)

    def test_typing_a_search_scrolls_to_the_match(self):
        value = 'x' * 200 + 'needle'
        model = init_model(value)
        model, _ = update({'pythonEventStr': repr(SearchBoxInput(value=r"r'needle'")),
                           'eventJSON': {}},
                          self.var_and_exp, model, value)
        self.assertTrue(model['_scroll_to_match'])

    def test_clicking_in_the_string_does_not_scroll(self):
        value = 'x' * 200 + 'needle'
        model = init_model(value)
        model['search'] = r"r'(needle)'"
        model, _ = update(make_mouse_down_event(3, legacy_index=False),
                          self.var_and_exp, model, value)
        self.assertFalse(model['_scroll_to_match'])
        out = visualize(value, model, None, None)
        self.assertNotIn('snc-scroll-to-match', out)


if __name__ == '__main__':
    unittest.main()


# =============================================================================
# Lazy repetition options and option tooltips
# =============================================================================

class TestLazyRepetitionOptions(unittest.TestCase):
    """The repetition dropdown offers `*?` and `+?` (lazy: as few as possible)."""

    def test_options_are_offered(self):
        values = [value for value, _ in REPETITION_OPTIONS]
        self.assertIn('*?', values)
        self.assertIn('+?', values)

    def test_selecting_lazy_star(self):
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}
        model, _ = update(make_dropdown_select_event('repetition-1', '*?'), None, model, "hello world")
        self.assertEqual(model['search'], r"r'hello.*?world'")

    def test_selecting_lazy_plus(self):
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['openDropdown'] = {'id': 'repetition-1', 'segmentIndex': 1}
        model, _ = update(make_dropdown_select_event('repetition-1', '+?'), None, model, "hello world")
        self.assertEqual(model['search'], r"r'hello.+?world'")

    def test_replace_repetition_with_lazy_star(self):
        self.assertEqual(replace_segment_repetition(r"r'(.+)'", 0, '*?'), r"r'.*?'")

    def _open_on_middle_segment(self, search):
        model = init_model("hello world")
        model['search'] = search
        model['hoverIdx'] = 6
        # Dropdown ids are keyed by match as well as segment
        # (repetition-{match_index}-{segment_index}); only the open one renders.
        model['openDropdown'] = {'id': 'repetition-0-1', 'segmentIndex': 1}
        return visualize("hello world", model, None, None)

    def test_lazy_star_is_the_selected_option_and_the_label(self):
        html = self._open_on_middle_segment(r"r'hello.*?world'")
        self.assertRegex(html, r'snc-dropdown-option selected"[^>]*>\*\?</div>')
        self.assertNotRegex(html, r'snc-dropdown-option selected"[^>]*>\*</div>')
        self.assertRegex(html, r'class="segment-label repetition[^"]*"[^>]*>\*\?</span>')

    def test_lazy_plus_is_the_selected_option_and_the_label(self):
        html = self._open_on_middle_segment(r"r'hello.+?world'")
        self.assertRegex(html, r'snc-dropdown-option selected"[^>]*>\+\?</div>')
        self.assertNotRegex(html, r'snc-dropdown-option selected"[^>]*>\+</div>')
        self.assertRegex(html, r'class="segment-label repetition[^"]*"[^>]*>\+\?</span>')

    def test_greedy_star_is_still_the_selected_option(self):
        html = self._open_on_middle_segment(r"r'hello.*world'")
        self.assertRegex(html, r'snc-dropdown-option selected"[^>]*>\*</div>')
        self.assertNotRegex(html, r'snc-dropdown-option selected"[^>]*>\*\?</div>')


class TestRepetitionOptionTooltips(unittest.TestCase):
    """Each repetition option explains itself on hover."""

    def test_every_option_has_a_tooltip(self):
        model = init_model("hello world")
        model['search'] = r"r'hello.*world'"
        model['hoverIdx'] = 6
        model['openDropdown'] = {'id': 'repetition-0-1', 'segmentIndex': 1}
        html = visualize("hello world", model, None, None)
        for value, label in REPETITION_OPTIONS:
            with self.subTest(option=value):
                self.assertRegex(
                    html,
                    r'snc-dropdown-option[^>]*data-tooltip="[^"]+"[^>]*>' + re.escape(label) + '</div>')

    def test_tooltips_say_what_the_options_do(self):
        tips = dict(REPETITION_TOOLTIPS)
        self.assertIn('exactly', tips['1'].lower())
        self.assertIn('fewest', tips['*?'].lower())
        self.assertIn('fewest', tips['+?'].lower())
        self.assertIn('one or more', tips['+'].lower())


# =============================================================================
# Substrs is the default output; a map switches to Map Matches
# =============================================================================

class TestSubstrsIsTheDefaultOutput(unittest.TestCase):
    """The first interaction links a `re.findall` line (Substrs). As soon as a
    map expression exists -- typed into the replace box, composed with the
    pick tool's chips -- the line becomes Map Matches, the one action that
    consumes it."""

    def setUp(self):
        self.value = "hello world"
        self.var_and_exp = ('x', 'x')

    def _select_hello(self):
        model = init_model(self.value)
        model, _ = update(make_mouse_down_event(2, top_half=True), self.var_and_exp, model, self.value)
        model, _ = update(make_mouse_move_event(6), self.var_and_exp, model, self.value)
        return update(make_mouse_up_event(6), self.var_and_exp, model, self.value)

    def test_a_drag_links_substrs(self):
        model, commands = self._select_hello()
        self.assertEqual(model['linked_action'], 'match_strings')
        self.assertEqual(commands[0][:2], ('x_strings', "re.findall(r'hello', x, flags=re.M)"))

    def test_typing_a_pattern_links_substrs(self):
        model = init_model(self.value)
        model, commands = update(make_search_box_input_event(r"r'hello'"), self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'match_strings')
        self.assertIn("re.findall(r'hello'", commands[0][1])

    def test_enter_keeps_substrs_when_there_is_no_map(self):
        model, _ = self._select_hello()
        model, commands = update(make_key_down_event('Enter'), self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'match_strings')
        self.assertEqual(commands, [])

    def test_typing_a_map_expression_switches_to_map_matches(self):
        model, _ = self._select_hello()
        model, _ = update(make_replace_toggle_event(), self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'match_strings')  # box open but empty: still substrs
        model, commands = update(make_replace_box_input_event('$[0].upper()'), self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'find_or_map')
        self.assertEqual(len(commands), 1)
        self.assertIn('finditer', commands[0].expression)
        self.assertIn('.upper()', commands[0].expression)

    def test_the_pick_tool_switches_to_map_matches(self):
        model, _ = self._select_hello()
        model, _ = update({'pythonEventStr': repr(ToolSelect(tool='pick')), 'eventJSON': {}},
                          self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'find_or_map')

    def test_a_first_interaction_with_a_map_already_present_links_map_matches(self):
        model = init_model(self.value)
        model['replace_visible'] = True
        model['replace_text'] = '$[0].upper()'
        model, commands = update(make_search_box_input_event(r"r'hello'"), self.var_and_exp, model, self.value)
        self.assertEqual(model['linked_action'], 'find_or_map')
        self.assertIn('finditer', commands[0][1])
