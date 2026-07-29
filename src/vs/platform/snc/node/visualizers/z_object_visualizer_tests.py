"""
Tests for z_object_visualizer.py - configurable field visualization.

These tests follow TDD: written before the implementation.

Run this test file directly:
    python3 src/vs/platform/snc/node/visualizers/z_object_visualizer_tests.py

Or use pytest with verbose output:
    python3 -m pytest src/vs/platform/snc/node/visualizers/z_object_visualizer_tests.py -v
"""

import unittest
import json
import os
import tempfile
import shutil
from unittest.mock import patch

import html as html_module

from z_object_visualizer import (
    visualize, init_model, update, can_visualize,
    TRIVIAL_NAMES, DEFAULT_FIELDS_FOR_TYPE, DOTFILE_NAME,
    AddFieldClick, FieldInput, FieldSelect, FieldClick, KeyDown,
    RemoveFieldClick, DragStart, DragOver, DragEnd,
    load_fields_from_dotfile, save_fields_to_dotfile,
    _get_autocomplete_suggestions, _resolve_fields,
)
from visualizer_utils import ChildEvent, get_full_class_name as _get_full_class_name, wrap_drag_grab, MAX_NEST_DEPTH
import z_object_visualizer
import list_visualizer


class _GenericVis:
    """Fallback visualizer for tests (matches GenericVisualizer in python_runner)."""
    def can_visualize(self, value):
        return True
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        inner = html_module.escape(repr(value))
        expr = var_and_exp[1] if var_and_exp else None
        if expr:
            return (f'<span snc-py-exp="{html_module.escape(expr)}" draggable="true" '
                    f'class="py-exp-grab">{inner}</span>')
        return inner
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])

class _ZObjectVisAdapter:
    """Adapter wrapping the z_object_visualizer module as a visualizer object."""
    SUPPORTS_NESTED_CONFIG = True
    def can_visualize(self, value):
        return z_object_visualizer.can_visualize(value)
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None, **kwargs):
        return z_object_visualizer.init_model(value, get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp, **kwargs)
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return z_object_visualizer.visualize(value, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small)
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return z_object_visualizer.update(event, var_and_exp, model, value, get_visualizer, eval_in_scope=eval_in_scope)


class _ListVisAdapter:
    """Adapter wrapping the list_visualizer module (for cross-type nesting tests)."""
    SUPPORTS_NESTED_CONFIG = True
    def can_visualize(self, value):
        return list_visualizer.can_visualize(value)
    def get_fields(self, value):
        return list_visualizer.get_fields(value)
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None, **kwargs):
        return list_visualizer.init_model(value, get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp, **kwargs)
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return list_visualizer.visualize(value, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small)
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return list_visualizer.update(event, var_and_exp, model, value, get_visualizer, eval_in_scope=eval_in_scope)

_generic_vis = _GenericVis()
_zobj_vis = _ZObjectVisAdapter()
_list_vis = _ListVisAdapter()

def _get_visualizer(value):
    """Simple visualizer resolver for tests."""
    return _generic_vis


def _get_nesting_visualizer(value):
    """Resolver that composes the real list + object visualizers (matches the
    runtime priority: lists -> list visualizer, objects -> z_object, primitives
    -> generic)."""
    if isinstance(value, list):
        return _list_vis
    if value is None or isinstance(value, (int, float, str, bool)):
        return _generic_vis
    return _zobj_vis


# =============================================================================
# Test Helpers
# =============================================================================

class TestObj:
    """Simple test object with known attributes."""
    def __init__(self):
        self.x = 10
        self.y = 20
        self.name = "test"


class AnotherObj:
    """Another test object to test dotfile with multiple types."""
    def __init__(self):
        self.alpha = 1
        self.beta = 2


def make_input_event(value: str) -> dict:
    """Create a FieldInput event dict (from snc-input)."""
    return {
        'pythonEventStr': f"lambda e: FieldInput(value=e.get('value', ''))",
        'eventJSON': {'type': 'input', 'value': value},
    }


def make_mouse_down_event(python_event_str: str, detail: int = 1) -> dict:
    """Create a mouse down event dict with the given pythonEventStr."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mousedown',
            'button': 0,
            'buttons': 1,
            'detail': detail,
            'offsetY': 5,
            'elementHeight': 20,
            'timeStamp': 1000.0,
        },
    }


def make_key_down_event(key: str) -> dict:
    """Create a KeyDown event dict."""
    return {
        'pythonEventStr': repr(KeyDown()),
        'eventJSON': {
            'type': 'keydown',
            'key': key,
            'metaKey': False,
            'shiftKey': False,
            'ctrlKey': False,
            'altKey': False,
        },
    }


# =============================================================================
# TestInitModel
# =============================================================================

class TestInitModel(unittest.TestCase):
    """Test init_model returns correct initial state."""

    def test_init_model_returns_expected_structure(self):
        """init_model returns a dict with all expected keys."""
        obj = TestObj()
        model = init_model(obj)

        self.assertIn('fields', model)
        self.assertIn('editing_index', model)
        self.assertIn('adding_field', model)
        self.assertIn('input_value', model)
        self.assertIn('selected_suggestion_index', model)
        self.assertIn('handledKeys', model)

        self.assertIsInstance(model['fields'], list)
        self.assertIsNone(model['editing_index'])
        self.assertFalse(model['adding_field'])
        self.assertEqual(model['input_value'], "")
        self.assertIsNone(model['selected_suggestion_index'])
        self.assertIn('Enter', model['handledKeys'])
        self.assertIn('Escape', model['handledKeys'])
        self.assertIn('ArrowUp', model['handledKeys'])
        self.assertIn('ArrowDown', model['handledKeys'])
        self.assertIn('Tab', model['handledKeys'])

    def test_init_model_uses_non_trivial_names_for_unknown_type(self):
        """For a custom object with no DEFAULT_FIELDS_FOR_TYPE, use dir() minus TRIVIAL_NAMES."""
        obj = TestObj()
        model = init_model(obj)

        # TestObj has ^.x, ^.y, ^.name attributes
        self.assertIn('^.x', model['fields'])
        self.assertIn('^.y', model['fields'])
        self.assertIn('^.name', model['fields'])

        # Should NOT contain trivial names like __class__, __init__, etc.
        for field in model['fields']:
            attr_name = field.lstrip('^.')
            self.assertNotIn(attr_name, TRIVIAL_NAMES,
                             f"Trivial name '{attr_name}' should not be in fields")

    def test_init_model_uses_default_fields_for_known_type(self):
        """For types in DEFAULT_FIELDS_FOR_TYPE (when no dotfile), use those defaults."""
        import re
        match = re.search(r'hello', 'hello world')
        self.assertIsNotNone(match)

        # Ensure no dotfile interferes
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=None):
            model = init_model(match)

        self.assertEqual(model['fields'], DEFAULT_FIELDS_FOR_TYPE['re.Match'])

    def test_init_model_loads_from_dotfile(self):
        """When dotfile has fields for this type, use those."""
        obj = TestObj()
        full_class_name = _get_full_class_name(obj)
        saved_fields = ['^.x', '^.name']

        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=saved_fields):
            model = init_model(obj)

        self.assertEqual(model['fields'], saved_fields)

    def test_init_model_falls_back_when_type_not_in_dotfile(self):
        """Dotfile exists but doesn't have this type → fall back to non-trivial names."""
        obj = TestObj()

        # load_fields_from_dotfile returns None (type not in dotfile)
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=None):
            model = init_model(obj)

        # Should still have the non-trivial attributes
        self.assertIn('^.x', model['fields'])
        self.assertIn('^.y', model['fields'])
        self.assertIn('^.name', model['fields'])


class TestResolveFields(unittest.TestCase):
    """Test the shared field resolution helper."""

    def test_resolve_fields_prefers_dotfile(self):
        obj = TestObj()
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=['^.name']):
            self.assertEqual(_resolve_fields(obj), ['^.name'])

    def test_resolve_fields_uses_defaults_when_dotfile_missing(self):
        import re
        match = re.search(r'hello', 'hello world')
        self.assertIsNotNone(match)

        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=None):
            self.assertEqual(_resolve_fields(match), DEFAULT_FIELDS_FOR_TYPE['re.Match'])

    def test_resolve_fields_falls_back_to_non_trivial_names(self):
        obj = TestObj()
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=None):
            resolved = _resolve_fields(obj)
        self.assertIn('^.x', resolved)
        self.assertIn('^.y', resolved)
        self.assertIn('^.name', resolved)


# =============================================================================
# TestVisualize
# =============================================================================

class TestVisualize(unittest.TestCase):
    """Test the visualize function renders correct HTML."""

    def test_visualize_primitives_unchanged(self):
        """None, int, float should still return repr."""
        self.assertEqual(visualize(None, None, _get_visualizer, None), repr(None))
        self.assertEqual(visualize(42, None, _get_visualizer, None), repr(42))
        self.assertEqual(visualize(3.14, None, _get_visualizer, None), repr(3.14))
        self.assertEqual(visualize(True, None, _get_visualizer, None), repr(True))

    def test_visualize_object_shows_field_table(self):
        """Object visualization should contain table with field names and values."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('.x', html_output)
        self.assertIn('.name', html_output)
        self.assertIn('10', html_output)  # value of .x
        self.assertIn('test', html_output)  # value of .name (in repr form)
        self.assertIn('<table', html_output)

    def test_visualize_shows_add_button(self):
        """HTML should contain a (+) button with snc-mouse-down for AddFieldClick."""
        obj = TestObj()
        model = init_model(obj)
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('snc-mouse-down', html_output)
        self.assertIn('AddFieldClick', html_output)
        self.assertIn('+', html_output)

    def test_visualize_shows_input_when_adding(self):
        """When adding_field=True, shows an <input> with snc-input handler."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['input_value'] = '^.na'
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('<input', html_output)
        self.assertIn('snc-input', html_output)
        self.assertIn('FieldInput', html_output)

    def test_visualize_shows_input_when_editing(self):
        """When editing_index is set, that row shows an <input>."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        model['editing_index'] = 0
        model['input_value'] = '^.x'
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('<input', html_output)
        self.assertIn('snc-input', html_output)

    def test_visualize_shows_autocomplete_suggestions(self):
        """When adding/editing with input, shows autocomplete suggestions."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []  # no existing fields
        model['adding_field'] = True
        model['input_value'] = '^.x'
        html_output = visualize(obj, model, _get_visualizer, None)

        # Should show ^.x as a suggestion (since it starts with '^.x')
        self.assertIn('FieldSelect', html_output)

    def test_visualize_filters_autocomplete_by_input(self):
        """Typing '^.na' should show '^.name' but not '^.x'."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.na'
        html_output = visualize(obj, model, _get_visualizer, None)

        # Should have ^.name as suggestion
        self.assertIn('^.name', html_output)
        # Should NOT have FieldSelect for ^.x (doesn't match '^.na' prefix)
        # .x is still shown in... hmm actually .x might not appear at all if no fields
        # Let's check FieldSelect specifically
        self.assertNotIn("FieldSelect(accessor=&#x27;^.x&#x27;)", html_output)

    def test_visualize_excludes_already_shown_from_autocomplete(self):
        """Fields already in model['fields'] should not appear in autocomplete."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.name']
        model['adding_field'] = True
        model['input_value'] = '^.'  # matches everything
        html_output = visualize(obj, model, _get_visualizer, None)

        # ^.name is already shown, so FieldSelect for ^.name should not be in autocomplete
        # But ^.x and ^.y should be
        # Note: repr uses single quotes which get HTML-escaped to &#x27; in the output
        self.assertIn("FieldSelect(accessor=&#x27;^.x&#x27;)", html_output)
        self.assertIn("FieldSelect(accessor=&#x27;^.y&#x27;)", html_output)
        # ^.name should NOT be in autocomplete selections
        self.assertNotIn("FieldSelect(accessor=&#x27;^.name&#x27;)", html_output)

    def test_visualize_shows_live_value_for_partial_input(self):
        """When typing a partial accessor, the value column should attempt to eval it."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True
        model['input_value'] = '^.name'
        html_output = visualize(obj, model, _get_visualizer, None)

        # ^.name evaluates to 'test', should be shown
        self.assertIn('test', html_output)

    def test_visualize_shows_class_name_header(self):
        """Should show the full class name in the header."""
        obj = TestObj()
        model = init_model(obj)
        html_output = visualize(obj, model, _get_visualizer, None)

        full_name = _get_full_class_name(obj)
        self.assertIn('TestObj', html_output)

    def test_visualize_field_has_double_click_handler(self):
        """Normal field names should have snc-mouse-down with FieldClick for double-click."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('FieldClick(index=0)', html_output)
        self.assertIn('FieldClick(index=1)', html_output)

    def test_visualize_shows_remove_button(self):
        """Each field row should have a remove (×) button with RemoveFieldClick."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('RemoveFieldClick(index=0)', html_output)
        self.assertIn('RemoveFieldClick(index=1)', html_output)
        # Remove button uses CSS class for hover visibility
        self.assertIn('snc-hover-hidden', html_output)
        self.assertIn('snc-hover-hidden-parent', html_output)

    def test_visualize_input_has_autofocus_when_adding(self):
        """Input should have autofocus attribute when adding a field."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['input_value'] = ''
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('autofocus', html_output)

    def test_visualize_input_has_autofocus_when_editing(self):
        """Input should have autofocus attribute when editing a field."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        model['editing_index'] = 0
        model['input_value'] = '^.x'
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('autofocus', html_output)

    def test_visualize_input_has_select_all_when_editing(self):
        """Input should have snc-select-all when editing (not when adding)."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        model['editing_index'] = 0
        model['input_value'] = '^.x'
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('snc-select-all', html_output)

    def test_visualize_input_no_select_all_when_adding(self):
        """Input should NOT have snc-select-all when adding."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['input_value'] = ''
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertNotIn('snc-select-all', html_output)

    def test_visualize_highlights_selected_suggestion(self):
        """Selected suggestion should have highlight background."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        model['selected_suggestion_index'] = 0
        html_output = visualize(obj, model, _get_visualizer, None)

        # The first suggestion should have the selected class
        self.assertIn('class="snc-dropdown-option selected"', html_output)

    def test_visualize_autocomplete_uses_dropdown_hoisting(self):
        """Autocomplete should use snc-dropdown-trigger/panel classes for hoisting."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('snc-dropdown-trigger', html_output)
        self.assertIn('snc-dropdown-panel', html_output)
        self.assertIn('snc-dropdown-option', html_output)


# =============================================================================
# TestUpdate
# =============================================================================

class TestUpdate(unittest.TestCase):
    """Test the update function processes events correctly."""

    def test_null_event_returns_unchanged(self):
        """Passing None event returns model unchanged."""
        obj = TestObj()
        model = init_model(obj)
        new_model, commands = update(None, ('x', 'x'), model, obj)
        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_empty_event_returns_unchanged(self):
        """Passing empty event dict returns model unchanged."""
        obj = TestObj()
        model = init_model(obj)
        new_model, commands = update({}, ('x', 'x'), model, obj)
        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_add_field_click_sets_adding_true(self):
        """AddFieldClick event sets adding_field=True and clears input."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']

        event = make_mouse_down_event(repr(AddFieldClick()))
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertTrue(new_model['adding_field'])
        self.assertEqual(new_model['input_value'], '')
        self.assertIsNone(new_model['editing_index'])

    def test_field_input_updates_input_value(self):
        """FieldInput event updates input_value in model."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True

        event = make_input_event('^.na')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['input_value'], '^.na')

    def test_field_select_adds_field_when_adding(self):
        """FieldSelect during add mode appends accessor to fields."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True
        model['input_value'] = '^.na'

        event = make_mouse_down_event(repr(FieldSelect(accessor='^.name')))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIn('^.name', new_model['fields'])
        self.assertFalse(new_model['adding_field'])
        self.assertEqual(new_model['input_value'], '')

    def test_field_select_replaces_field_when_editing(self):
        """FieldSelect during edit mode replaces the field at editing_index."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.y']
        model['editing_index'] = 0
        model['input_value'] = '^.na'

        event = make_mouse_down_event(repr(FieldSelect(accessor='^.name')))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'][0], '^.name')
        self.assertEqual(new_model['fields'][1], '^.y')
        self.assertIsNone(new_model['editing_index'])
        self.assertEqual(new_model['input_value'], '')

    def test_double_click_starts_editing(self):
        """FieldClick with detail=2 sets editing_index and input_value."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']

        event = make_mouse_down_event(repr(FieldClick(index=0)), detail=2)
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['editing_index'], 0)
        self.assertEqual(new_model['input_value'], '^.x')
        self.assertFalse(new_model['adding_field'])

    def test_single_click_does_not_start_editing(self):
        """FieldClick with detail=1 does NOT start editing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']

        event = make_mouse_down_event(repr(FieldClick(index=0)), detail=1)
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['editing_index'])

    def test_enter_commits_add(self):
        """Enter key during add mode appends input_value to fields."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True
        model['input_value'] = '^.name'

        event = make_key_down_event('Enter')
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIn('^.name', new_model['fields'])
        self.assertFalse(new_model['adding_field'])
        self.assertEqual(new_model['input_value'], '')

    def test_enter_commits_edit(self):
        """Enter key during edit mode replaces field at editing_index."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.y']
        model['editing_index'] = 0
        model['input_value'] = '^.name'

        event = make_key_down_event('Enter')
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'][0], '^.name')
        self.assertIsNone(new_model['editing_index'])

    def test_enter_with_empty_input_does_not_add(self):
        """Enter with empty input_value during add should not add empty field."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True
        model['input_value'] = ''

        event = make_key_down_event('Enter')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(len(new_model['fields']), 1)
        self.assertFalse(new_model['adding_field'])

    def test_escape_cancels_add(self):
        """Escape key during add mode cancels adding."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['input_value'] = '^.na'

        event = make_key_down_event('Escape')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertFalse(new_model['adding_field'])
        self.assertEqual(new_model['input_value'], '')

    def test_escape_cancels_edit(self):
        """Escape key during edit mode cancels editing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        model['editing_index'] = 0
        model['input_value'] = '^.foo'

        event = make_key_down_event('Escape')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['editing_index'])
        self.assertEqual(new_model['input_value'], '')
        # Field should be unchanged
        self.assertEqual(new_model['fields'][0], '^.x')

    def test_field_select_saves_dotfile(self):
        """FieldSelect commit should call save_fields_to_dotfile."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True

        event = make_mouse_down_event(repr(FieldSelect(accessor='^.name')))
        with patch('z_object_visualizer.save_fields_to_dotfile') as mock_save:
            new_model, commands = update(event, ('x', 'x'), model, obj)
            mock_save.assert_called_once()
            # Should save with the updated fields list
            saved_fields = mock_save.call_args[0][2]
            self.assertIn('^.name', saved_fields)

    def test_enter_saves_dotfile(self):
        """Enter commit should call save_fields_to_dotfile."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']
        model['adding_field'] = True
        model['input_value'] = '^.name'

        event = make_key_down_event('Enter')
        with patch('z_object_visualizer.save_fields_to_dotfile') as mock_save:
            new_model, commands = update(event, ('x', 'x'), model, obj)
            mock_save.assert_called_once()

    def test_none_model_gets_initialized(self):
        """Passing None model initializes a fresh model."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        event = make_mouse_down_event(repr(AddFieldClick()))
        new_model, commands = update(event, ('x', 'x'), model, obj)
        self.assertIsNotNone(new_model)
        self.assertTrue(new_model['adding_field'])

    def test_arrow_down_selects_first_suggestion(self):
        """ArrowDown from no selection selects the first suggestion."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'

        event = make_key_down_event('ArrowDown')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_arrow_down_wraps_around(self):
        """ArrowDown wraps from last suggestion back to first."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        # Get the count of suggestions to set index to last
        from z_object_visualizer import _get_autocomplete_suggestions
        suggestions = _get_autocomplete_suggestions(obj, [], '^.')
        last_idx = min(len(suggestions), 10) - 1
        model['selected_suggestion_index'] = last_idx

        event = make_key_down_event('ArrowDown')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_arrow_up_selects_last_suggestion(self):
        """ArrowUp from no selection selects the last suggestion."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'

        event = make_key_down_event('ArrowUp')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        from z_object_visualizer import _get_autocomplete_suggestions
        suggestions = _get_autocomplete_suggestions(obj, [], '^.')
        expected = min(len(suggestions), 10) - 1
        self.assertEqual(new_model['selected_suggestion_index'], expected)

    def test_arrow_up_wraps_around(self):
        """ArrowUp from first suggestion wraps to last."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        model['selected_suggestion_index'] = 0

        event = make_key_down_event('ArrowUp')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        from z_object_visualizer import _get_autocomplete_suggestions
        suggestions = _get_autocomplete_suggestions(obj, [], '^.')
        expected = min(len(suggestions), 10) - 1
        self.assertEqual(new_model['selected_suggestion_index'], expected)

    def test_enter_commits_selected_suggestion(self):
        """Enter with a selected suggestion commits that suggestion, not the input text."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        # Get suggestions and pick the first one
        from z_object_visualizer import _get_autocomplete_suggestions
        suggestions = _get_autocomplete_suggestions(obj, [], '^.')
        model['selected_suggestion_index'] = 0
        expected_field = suggestions[0]

        event = make_key_down_event('Enter')
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIn(expected_field, new_model['fields'])
        self.assertFalse(new_model['adding_field'])
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_field_input_auto_highlights_first_suggestion(self):
        """Typing in the input should auto-highlight the first matching suggestion."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']  # ^.name is NOT already shown
        model['adding_field'] = True
        model['selected_suggestion_index'] = None

        event = make_input_event('^.na')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        # ^.name matches '^.na' and is not in fields, so first suggestion should be selected
        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_field_input_clears_selection_when_no_suggestions(self):
        """Typing something with no matches should clear the selection."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['selected_suggestion_index'] = 0

        event = make_input_event('^.zzzzz')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_field_input_clears_selection_when_empty(self):
        """Clearing input should clear the selection."""
        obj = TestObj()
        model = init_model(obj)
        model['adding_field'] = True
        model['selected_suggestion_index'] = 0

        event = make_input_event('')
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_tab_commits_selected_suggestion(self):
        """Tab with a selected suggestion commits it like Enter."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = []
        model['adding_field'] = True
        model['input_value'] = '^.'
        suggestions = _get_autocomplete_suggestions(obj, [], '^.')
        model['selected_suggestion_index'] = 0
        expected_field = suggestions[0]

        event = make_key_down_event('Tab')
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIn(expected_field, new_model['fields'])
        self.assertFalse(new_model['adding_field'])
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_arrow_keys_noop_when_not_input_active(self):
        """ArrowDown/Up should do nothing when not adding or editing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']

        event = make_key_down_event('ArrowDown')
        new_model, commands = update(event, ('x', 'x'), model, obj)
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_remove_field_removes_from_list(self):
        """RemoveFieldClick removes the field at the given index."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']

        event = make_mouse_down_event(repr(RemoveFieldClick(index=1)))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.x', '^.y'])

    def test_remove_field_saves_dotfile(self):
        """RemoveFieldClick should persist the updated fields to dotfile."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']

        event = make_mouse_down_event(repr(RemoveFieldClick(index=0)))
        with patch('z_object_visualizer.save_fields_to_dotfile') as mock_save:
            new_model, commands = update(event, ('x', 'x'), model, obj)
            mock_save.assert_called_once()
            saved_fields = mock_save.call_args[0][2]
            self.assertEqual(saved_fields, ['^.name'])

    def test_remove_field_out_of_range_is_noop(self):
        """RemoveFieldClick with invalid index does nothing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x']

        event = make_mouse_down_event(repr(RemoveFieldClick(index=5)))
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.x'])

    def test_remove_field_cancels_editing_if_index_matches(self):
        """Removing the field being edited should cancel editing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        model['editing_index'] = 0
        model['input_value'] = '^.x'

        event = make_mouse_down_event(repr(RemoveFieldClick(index=0)))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['editing_index'])
        self.assertEqual(new_model['input_value'], '')
        self.assertEqual(new_model['fields'], ['^.name'])


# =============================================================================
# TestDotfile
# =============================================================================

# =============================================================================
# TestDragReorder
# =============================================================================

def make_mouse_move_event(python_event_str: str, buttons: int = 1) -> dict:
    """Create a mouse move event dict."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mousemove',
            'buttons': buttons,
        },
    }


def make_mouse_up_event(python_event_str: str) -> dict:
    """Create a mouse up event dict."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mouseup',
            'buttons': 0,
        },
    }


class TestDragReorder(unittest.TestCase):
    """Test drag-and-drop field reordering."""

    def test_drag_start_sets_drag_from_index(self):
        """DragStart sets drag_from_index in model."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']

        event = make_mouse_down_event(repr(DragStart(index=1)))
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['drag_from_index'], 1)

    def test_drag_over_sets_drag_over_index(self):
        """DragOver while dragging sets drag_over_index."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 2

        event = make_mouse_move_event(repr(DragOver(index=0)), buttons=1)
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['drag_over_index'], 0)

    def test_drag_over_cancels_on_button_release(self):
        """DragOver with buttons=0 cancels drag."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 2
        model['drag_over_index'] = 0

        event = make_mouse_move_event(repr(DragOver(index=1)), buttons=0)
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model['drag_from_index'])
        self.assertIsNone(new_model['drag_over_index'])

    def test_drag_over_ignored_when_not_dragging(self):
        """DragOver without active drag is ignored."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']

        event = make_mouse_move_event(repr(DragOver(index=1)), buttons=1)
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertIsNone(new_model.get('drag_over_index'))

    def test_drag_end_reorders_forward(self):
        """DragEnd moves field from index 0 to index 2."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 0
        model['drag_over_index'] = 2

        event = make_mouse_up_event(repr(DragEnd(index=2)))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.name', '^.y', '^.x'])
        self.assertIsNone(new_model['drag_from_index'])
        self.assertIsNone(new_model['drag_over_index'])

    def test_drag_end_reorders_backward(self):
        """DragEnd moves field from index 2 to index 0."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 2
        model['drag_over_index'] = 0

        event = make_mouse_up_event(repr(DragEnd(index=0)))
        with patch('z_object_visualizer.save_fields_to_dotfile'):
            new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.y', '^.x', '^.name'])
        self.assertIsNone(new_model['drag_from_index'])
        self.assertIsNone(new_model['drag_over_index'])

    def test_drag_end_same_position_is_noop(self):
        """DragEnd to the same position doesn't change order."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 1
        model['drag_over_index'] = 1

        event = make_mouse_up_event(repr(DragEnd(index=1)))
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.x', '^.name', '^.y'])

    def test_drag_end_saves_dotfile(self):
        """DragEnd should save reordered fields to dotfile."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']
        model['drag_from_index'] = 0
        model['drag_over_index'] = 2

        event = make_mouse_up_event(repr(DragEnd(index=2)))
        with patch('z_object_visualizer.save_fields_to_dotfile') as mock_save:
            new_model, commands = update(event, ('x', 'x'), model, obj)
            mock_save.assert_called_once()

    def test_drag_end_without_drag_is_noop(self):
        """DragEnd without active drag does nothing."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name', '^.y']

        event = make_mouse_up_event(repr(DragEnd(index=1)))
        new_model, commands = update(event, ('x', 'x'), model, obj)

        self.assertEqual(new_model['fields'], ['^.x', '^.name', '^.y'])

    def test_visualize_shows_drag_handles(self):
        """Each field row should have a drag handle."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('DragStart(index=0)', html_output)
        self.assertIn('DragStart(index=1)', html_output)

    def test_visualize_shows_drag_target_indicators(self):
        """Each field row should have DragOver and DragEnd handlers."""
        obj = TestObj()
        model = init_model(obj)
        model['fields'] = ['^.x', '^.name']
        html_output = visualize(obj, model, _get_visualizer, None)

        self.assertIn('DragOver(index=0)', html_output)
        self.assertIn('DragEnd(index=0)', html_output)


class TestDotfile(unittest.TestCase):
    """Test dotfile load/save operations."""

    def setUp(self):
        """Create a temp directory for dotfile tests."""
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.chdir(self.tmp_dir)

    def tearDown(self):
        """Restore original cwd and clean up temp dir."""
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_load_fields_missing_file(self):
        """No dotfile → returns None."""
        result = load_fields_from_dotfile('some.Type')
        self.assertIsNone(result)

    def test_load_fields_from_dotfile(self):
        """Valid dotfile with type key → returns fields list."""
        data = {'some.Type': ['^.x', '^.y']}
        with open(DOTFILE_NAME, 'w') as f:
            json.dump(data, f)

        result = load_fields_from_dotfile('some.Type')
        self.assertEqual(result, ['^.x', '^.y'])

    def test_load_fields_type_not_in_dotfile(self):
        """Dotfile exists but doesn't have this type → returns None."""
        data = {'other.Type': ['.a', '.b']}
        with open(DOTFILE_NAME, 'w') as f:
            json.dump(data, f)

        result = load_fields_from_dotfile('some.Type')
        self.assertIsNone(result)

    def test_load_fields_corrupt_file(self):
        """Bad JSON → returns None (doesn't crash)."""
        with open(DOTFILE_NAME, 'w') as f:
            f.write('this is not json{{{')

        result = load_fields_from_dotfile('some.Type')
        self.assertIsNone(result)

    def test_save_fields_to_dotfile(self):
        """Saves correct JSON structure (nested slot format)."""
        save_fields_to_dotfile('some.Type', [], ['^.x', '^.y'])

        with open(DOTFILE_NAME, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['some.Type'], [{'expr': '^.x'}, {'expr': '^.y'}])

    def test_save_preserves_other_types(self):
        """Saving for type A doesn't clobber type B entries."""
        save_fields_to_dotfile('type.A', [], ['^.a1', '^.a2'])
        save_fields_to_dotfile('type.B', [], ['^.b1', '^.b2'])

        with open(DOTFILE_NAME, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['type.A'], [{'expr': '^.a1'}, {'expr': '^.a2'}])
        self.assertEqual(data['type.B'], [{'expr': '^.b1'}, {'expr': '^.b2'}])

    def test_save_overwrites_same_type(self):
        """Saving the same type again overwrites the previous entry."""
        save_fields_to_dotfile('some.Type', [], ['^.x'])
        save_fields_to_dotfile('some.Type', [], ['^.x', '^.y'])

        with open(DOTFILE_NAME, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['some.Type'], [{'expr': '^.x'}, {'expr': '^.y'}])


# =============================================================================
# TestGetFullClassName
# =============================================================================

class TestGetFullClassName(unittest.TestCase):
    """Test _get_full_class_name helper."""

    def test_builtin_type(self):
        """Built-in types should return module.qualname."""
        result = _get_full_class_name("hello")
        self.assertEqual(result, 'builtins.str')

    def test_custom_type(self):
        """Custom types should include module and qualname."""
        obj = TestObj()
        result = _get_full_class_name(obj)
        self.assertIn('TestObj', result)


# =============================================================================
# Subvisualizer Composition Tests
# =============================================================================

class CompositionTestObj:
    """Test object specifically for composition tests - has string fields."""
    greeting = "hello"
    count = 42

class MockInteractiveVis:
    """A mock interactive visualizer for composition tests."""
    def can_visualize(self, value):
        return isinstance(value, str)
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return {'vis_type': 'mock_interactive', 'handledKeys': ['Escape']}
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        inner = f'<span snc-mouse-down="MockClick()">{html_module.escape(repr(value))}</span>'
        # Stands in for a third-party visualizer that self-wraps when small, to
        # check the parent hands down the expression and doesn't wrap children.
        if small and var_and_exp:
            return wrap_drag_grab(inner, var_and_exp)
        return inner
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        model = dict(model)
        model['updated'] = True
        return (model, [])

_mock_interactive_vis = MockInteractiveVis()

def _interactive_get_visualizer(value):
    """Returns the mock interactive vis for strings, generic for everything else."""
    if isinstance(value, str):
        return _mock_interactive_vis
    return _generic_vis


class TestComposition(unittest.TestCase):
    """Test subvisualizer composition in z_object_visualizer."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_model_contains_children_dict(self):
        obj = CompositionTestObj()
        model = init_model(obj, _get_visualizer)
        self.assertIn('children', model)
        self.assertIsInstance(model['children'], dict)

    def test_children_keyed_by_accessor(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        # ^.greeting is a string -> should have a child model from mock vis
        self.assertIn('^.greeting', model['children'])
        self.assertEqual(model['children']['^.greeting']['vis_type'], 'mock_interactive')

    def test_callable_fields_have_no_child_model(self):
        """Callable fields (methods) should not be subvisualized."""
        class WithMethod:
            def my_method(self):
                pass
            x = 42
        obj = WithMethod()
        model = init_model(obj, _interactive_get_visualizer)
        # ^.my_method is callable -> should NOT have a child model
        self.assertNotIn('^.my_method', model.get('children', {}))

    def test_visualize_wraps_field_values_with_child_key(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        output = visualize(obj, model, _interactive_get_visualizer, None)
        self.assertIn('snc-child-key=', output)

    def test_visualize_child_key_has_accessor(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        output = visualize(obj, model, _interactive_get_visualizer, None)
        import re
        matches = re.findall(r'snc-child-key="([^"]*)"', output)
        found_accessor_key = False
        for m in matches:
            try:
                key = eval(html_module.unescape(m))
                if key.startswith('^'):
                    found_accessor_key = True
                    break
            except:
                pass
        self.assertTrue(found_accessor_key,
                       "Expected at least one snc-child-key with accessor string")

    def test_update_routes_child_event_by_accessor(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        self.assertIn('^.greeting', model['children'])
        # Pre-focus the child so the mousedown dispatches; the first mousedown
        # on an unfocused child only pins focus (click-to-focus).
        model['focused_child'] = '^.greeting'
        ce = ChildEvent(child_key='^.greeting', py_ev_str='MockClick()')
        event = {
            'pythonEventStr': repr(ce),
            'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
        }
        new_model, _ = update(event, None, model, obj, _interactive_get_visualizer)
        child_model = new_model['children'].get('^.greeting')
        self.assertIsNotNone(child_model)
        self.assertTrue(child_model.get('updated', False))

    def test_remove_field_cleans_up_child_model(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        self.assertIn('^.greeting', model['children'])
        greeting_idx = model['fields'].index('^.greeting')
        event = {
            'pythonEventStr': repr(RemoveFieldClick(index=greeting_idx)),
            'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
        }
        new_model, _ = update(event, None, model, obj, _interactive_get_visualizer)
        self.assertNotIn('^.greeting', new_model.get('fields', []))
        self.assertNotIn('^.greeting', new_model.get('children', {}))

    def test_drag_reorder_preserves_child_model_association(self):
        """Reordering fields should keep child models associated by accessor key."""
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        if len(model['fields']) < 2:
            self.skipTest("Need at least 2 fields")

        original_children = dict(model['children'])
        first_field = model['fields'][0]
        second_field = model['fields'][1]

        # Start drag from index 0
        event_start = {
            'pythonEventStr': repr(DragStart(index=0)),
            'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
        }
        model, _ = update(event_start, None, model, obj, _interactive_get_visualizer)

        # Drag over index 1
        event_over = {
            'pythonEventStr': repr(DragOver(index=1)),
            'eventJSON': {'type': 'mousemove', 'buttons': 1},
        }
        model, _ = update(event_over, None, model, obj, _interactive_get_visualizer)

        # End drag
        event_end = {
            'pythonEventStr': repr(DragEnd(index=1)),
            'eventJSON': {'type': 'mouseup', 'button': 0, 'buttons': 0},
        }
        model, _ = update(event_end, None, model, obj, _interactive_get_visualizer)

        # Fields should be reordered
        self.assertEqual(model['fields'][0], second_field)
        self.assertEqual(model['fields'][1], first_field)

        # Child models should still be keyed by accessor, not index
        if first_field in original_children:
            self.assertEqual(model['children'].get(first_field), original_children[first_field])
        if second_field in original_children:
            self.assertEqual(model['children'].get(second_field), original_children[second_field])

    def test_handled_keys_aggregates_children(self):
        obj = CompositionTestObj()
        model = init_model(obj, _interactive_get_visualizer)
        # The mock interactive vis has handledKeys: ['Escape']
        # z_object's own keys include 'Enter', 'Escape', etc.
        self.assertIn('Enter', model['handledKeys'])
        self.assertIn('Escape', model['handledKeys'])


class TestInputRowEvalInScope(unittest.TestCase):
    """Test that the input row live preview uses eval_in_scope."""

    def test_input_row_evaluates_field_expr(self):
        """When editing a field, the live value preview evaluates field expressions."""
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        p = Point(1, 2)
        model = init_model(p, _get_visualizer)
        model['adding_field'] = True
        model['input_value'] = '^.x'

        html_output = visualize(p, model, _get_visualizer, None)
        self.assertIn('1', html_output)

    def test_input_row_without_eval_in_scope_still_works(self):
        """Without eval_in_scope, the preview falls back to local eval."""
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        p = Point(1, 2)
        model = init_model(p, _get_visualizer)
        model['adding_field'] = True
        model['input_value'] = '^.x'

        html_output = visualize(p, model, _get_visualizer, None)
        self.assertIn('1', html_output)


class TestDotfileCaretHandling(unittest.TestCase):
    """Test that load_fields_from_dotfile returns fields as stored."""

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_load_preserves_embedded_caret(self):
        """Fields with ^ embedded (not leading) are returned as-is."""
        data = {'re.Match': ['str3[^.start():]']}
        with open(DOTFILE_NAME, 'w') as f:
            json.dump(data, f)
        result = load_fields_from_dotfile('re.Match')
        self.assertEqual(result, ['str3[^.start():]'])

    def test_load_preserves_leading_caret(self):
        """Fields with leading ^ are returned as-is."""
        data = {'re.Match': ['^[0]', '^.start()']}
        with open(DOTFILE_NAME, 'w') as f:
            json.dump(data, f)
        result = load_fields_from_dotfile('re.Match')
        self.assertEqual(result, ['^[0]', '^.start()'])


# =============================================================================
# TestSmallView
# =============================================================================

class ManyFieldsObj:
    """Object with many fields for truncation tests."""
    def __init__(self):
        self.aaa = 1
        self.bbb = 2
        self.ccc = 3
        self.ddd = 4
        self.eee = 5
        self.fff = 6
        self.ggg = 7
        self.hhh = 8

class LongReprObj:
    """Object with a field whose repr is very long."""
    def __init__(self):
        self.data = "x" * 200

class ErrorFieldObj:
    """Object where accessing a property raises."""
    @property
    def bad(self):
        raise RuntimeError("boom")
    x = 42

class CallableFieldObj:
    """Object with a method and a data attribute."""
    def my_method(self):
        pass
    x = 99


class TestSmallView(unittest.TestCase):
    """Test the compact small=True visualization."""

    def _small(self, obj, model=None, max_width=None, max_height=None):
        if model is None:
            model = init_model(obj, _get_visualizer)
        return visualize(obj, model, _get_visualizer, None,
                         max_width=max_width, max_height=max_height, small=True)

    def test_primitives_still_return_repr(self):
        """Primitives render as repr even with small=True."""
        self.assertEqual(self._small(None), repr(None))
        self.assertEqual(self._small(42), repr(42))
        self.assertEqual(self._small(3.14), repr(3.14))

    def test_contains_class_name(self):
        obj = TestObj()
        html_out = self._small(obj)
        self.assertIn('TestObj', html_out)

    def test_shows_key_value_pairs(self):
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.name']
        html_out = self._small(obj, model)
        self.assertIn('.x', html_out)
        self.assertIn('10', html_out)
        self.assertIn('.name', html_out)
        self.assertIn('test', html_out)

    def test_no_table_or_interactive_controls(self):
        """Small view should not contain interactive table elements."""
        obj = TestObj()
        html_out = self._small(obj)
        self.assertNotIn('<table', html_out)
        self.assertNotIn('AddFieldClick', html_out)
        self.assertNotIn('FieldClick', html_out)
        self.assertNotIn('DragStart', html_out)
        self.assertNotIn('RemoveFieldClick', html_out)
        self.assertNotIn('<input', html_out)

    def test_no_child_visualizer_markup(self):
        """Small view should not use nested visualizers (no snc-child-key)."""
        obj = TestObj()
        model = init_model(obj, _interactive_get_visualizer)
        html_out = visualize(obj, model, _interactive_get_visualizer, None, small=True)
        self.assertNotIn('snc-child-key', html_out)

    def test_truncates_long_values(self):
        """Long repr values should be truncated with ellipsis."""
        obj = LongReprObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.data']
        html_out = self._small(obj, model, max_width=300)
        # The 200-char string should be truncated, not fully present
        self.assertNotIn('x' * 200, html_out)
        self.assertIn('…', html_out)

    def test_skips_callable_fields(self):
        """Callable fields (methods) should be omitted in small view."""
        obj = CallableFieldObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.my_method', '^.x']
        html_out = self._small(obj, model)
        self.assertNotIn('my_method', html_out)
        self.assertIn('.x', html_out)
        self.assertIn('99', html_out)

    def test_overflow_indicator_when_budget_exceeded(self):
        """When fields don't fit the budget, show a +N indicator."""
        obj = ManyFieldsObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.aaa', '^.bbb', '^.ccc', '^.ddd', '^.eee', '^.fff', '^.ggg', '^.hhh']
        html_out = self._small(obj, model, max_width=150, max_height=18)
        # With tight width and 1 line, can't fit all 8 fields
        self.assertIn('+', html_out)

    def test_empty_fields_shows_class_name_only(self):
        """Object with no fields shows just ClassName()."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = []
        html_out = self._small(obj, model)
        self.assertIn('TestObj', html_out)
        # Should have empty parens or similar
        self.assertNotIn('.x', html_out)

    def test_single_line_fits_in_one_line(self):
        """With max_height ~18px (one line), output should use nowrap."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.y']
        html_out = self._small(obj, model, max_height=18)
        self.assertIn('nowrap', html_out)

    def test_multiline_allows_wrapping(self):
        """With larger max_height, output should allow wrapping."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.y']
        html_out = self._small(obj, model, max_height=100)
        self.assertNotIn('nowrap', html_out)

    def test_error_field_shown_differently(self):
        """Error fields should be styled with error color."""
        obj = ErrorFieldObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.bad']
        html_out = self._small(obj, model)
        self.assertIn('boom', html_out)
        self.assertIn('class="error"', html_out)

    def test_uses_short_class_name(self):
        """Small view should use short class name, not fully qualified."""
        obj = TestObj()
        html_out = self._small(obj)
        self.assertIn('TestObj', html_out)
        self.assertNotIn('z_object_visualizer_tests.TestObj', html_out)

    def test_skips_dunder_fields(self):
        """Dunder attributes like __dict__, __module__ should be omitted."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.__dict__', '^.__module__', '^.x', '^.y']
        html_out = self._small(obj, model)
        self.assertNotIn('__dict__', html_out)
        self.assertNotIn('__module__', html_out)
        self.assertIn('.x', html_out)
        self.assertIn('.y', html_out)


# =============================================================================
# TestSmallViewPyExp
# =============================================================================

class TestSmallObjectSelfWrap(unittest.TestCase):
    """The object visualizer is never itself a drag handle: the field chips it
    renders carry their own (more specific) handles, and a whole-area handle
    would claim every hover over them. Only the generic visualizers, which have
    no content of their own, self-wrap."""

    def test_small_with_var_and_exp_not_self_wrapped(self):
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        html_out = visualize(obj, model, _get_visualizer, None, small=True,
                             var_and_exp=(None, 'obj'))
        self.assertFalse(html_out.startswith('<span snc-py-exp'))
        self.assertNotIn('snc-py-exp="obj"', html_out)

    def test_depth_capped_leaf_not_self_wrapped(self):
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['_too_deep'] = True
        html_out = visualize(obj, model, _get_visualizer, None, small=True,
                             var_and_exp=(None, 'obj'))
        self.assertNotIn('py-exp-grab', html_out)

    def test_small_without_var_and_exp_not_self_wrapped(self):
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        html_out = visualize(obj, model, _get_visualizer, None, small=True)
        self.assertFalse(html_out.startswith('<span snc-py-exp'))

    def test_full_mode_object_not_self_wrapped(self):
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        html_out = visualize(obj, model, _get_visualizer, None, small=False,
                             var_and_exp=(None, 'obj'))
        self.assertFalse(html_out.startswith('<span snc-py-exp'))


class TestSmallViewPyExp(unittest.TestCase):
    """Test snc-py-exp on the compact small=True visualization."""

    def _small(self, obj, model=None, max_width=None, max_height=None):
        if model is None:
            model = init_model(obj, _get_visualizer)
        return visualize(obj, model, _get_visualizer, None,
                         max_width=max_width, max_height=max_height, small=True)

    def test_no_py_exp_without_source_expr(self):
        """Without _source_expr, small view should not have snc-py-exp."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.name']
        html_out = self._small(obj, model)
        self.assertNotIn('snc-py-exp', html_out)
        self.assertNotIn('draggable', html_out)

    def test_py_exp_with_source_expr(self):
        """With _source_expr, each field pair gets snc-py-exp and draggable."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x', '^.name']
        html_out = self._small(obj, model)
        self.assertIn('snc-py-exp="obj.x"', html_out)
        self.assertIn('snc-py-exp="obj.name"', html_out)
        self.assertIn('draggable="true"', html_out)

    def test_py_exp_with_caret_source(self):
        """With _source_expr='^', bracket accessors stay as caret expressions."""
        import re
        m = re.search(r'hello', 'hello world')
        model = {
            'fields': ['^[0]', '^.start()', '^.end()'],
            '_source_expr': '^',
        }
        html_out = self._small(m, model)
        self.assertIn('snc-py-exp="^[0]"', html_out)
        self.assertIn('snc-py-exp="^.start()"', html_out)
        self.assertIn('snc-py-exp="^.end()"', html_out)

    def test_add_at_cursor_with_add_target(self):
        """With _add_target, fields also get snc-add-at-cursor and snc-add-target."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x']
        model['_add_target'] = '.my-input'
        html_out = self._small(obj, model)
        self.assertIn('snc-add-at-cursor="obj.x"', html_out)
        self.assertIn('snc-add-target=".my-input"', html_out)

    def test_no_add_at_cursor_without_add_target(self):
        """Without _add_target, no snc-add-at-cursor appears."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x']
        html_out = self._small(obj, model)
        self.assertNotIn('snc-add-at-cursor', html_out)

    def test_no_py_exp_on_error_fields(self):
        """Error fields should not get snc-py-exp."""
        obj = ErrorFieldObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.bad', '^.x']
        html_out = self._small(obj, model)
        self.assertNotIn('snc-py-exp="obj.bad"', html_out)
        self.assertIn('snc-py-exp="obj.x"', html_out)

    def test_py_exp_uses_py_exp_grab_class(self):
        """Draggable fields in small view use the py-exp-grab class."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x']
        html_out = self._small(obj, model)
        self.assertIn('py-exp-grab', html_out)

    def test_match_object_fields(self):
        """re.Match with custom fields shows group data with snc-py-exp."""
        import re
        m = re.search(r'(hel)(lo)', 'hello world')
        model = {
            'fields': ['^[0]', '^.start()', '^.end()', '^[1]', '^[2]'],
            '_source_expr': '^',
            '_add_target': '.search-box-replace',
        }
        html_out = self._small(m, model)
        self.assertIn('snc-py-exp="^[0]"', html_out)
        self.assertIn('snc-py-exp="^[1]"', html_out)
        self.assertIn('snc-py-exp="^[2]"', html_out)
        self.assertIn('snc-add-at-cursor="^[0]"', html_out)
        self.assertIn('hello', html_out)
        self.assertIn('hel', html_out)
        self.assertIn('lo', html_out)


# =============================================================================
# TestPyExpExtractable
# =============================================================================

class TestPyExpExtractable(unittest.TestCase):
    """Test snc-py-exp drag-to-extract on object field values."""

    def test_no_py_exp_without_var_and_exp(self):
        """Without var_and_exp, no snc-py-exp attributes should appear."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.name']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertNotIn('snc-py-exp', html_out)

    def test_py_exp_on_plain_value(self):
        """Plain text values get snc-py-exp with the correct expression."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertIn('snc-py-exp="obj.x"', html_out)
        self.assertIn('draggable="true"', html_out)

    def test_py_exp_uses_var_name(self):
        """When var_and_exp has a var_name, use it as source expression."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('my_point', 'my_point'))
        model['fields'] = ['^.x', '^.name']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertIn('snc-py-exp="my_point.x"', html_out)
        self.assertIn('snc-py-exp="my_point.name"', html_out)

    def test_py_exp_uses_expression_when_no_var_name(self):
        """When var_and_exp has no var_name, use the expression."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=(None, 'get_obj()'))
        model['fields'] = ['^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertIn('snc-py-exp="get_obj().x"', html_out)

    def test_py_exp_on_small_child_visualizer_uses_whole_area_grab(self):
        """Non-focused (small) child visualizer values use whole-area grab,
        not the old py-exp-cell border."""
        obj = TestObj()
        model = init_model(obj, _interactive_get_visualizer,
                           var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.name']
        html_out = visualize(obj, model, _interactive_get_visualizer, None)
        self.assertIn('snc-py-exp="obj.name"', html_out)
        self.assertIn('class="py-exp-grab"', html_out)
        # The bulky border pattern is gone.
        self.assertNotIn('class="py-exp-cell"', html_out)
        self.assertNotIn('draggable="false"', html_out)
        self.assertNotIn('class="py-exp-inner"', html_out)

    def test_py_exp_on_focused_child_visualizer_not_draggable(self):
        """The focused (interactive) child visualizer gets NO drag wrapper - it
        needs its mouse events."""
        obj = TestObj()
        model = init_model(obj, _interactive_get_visualizer,
                           var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.name']
        model['focused_child'] = '^.name'
        html_out = visualize(obj, model, _interactive_get_visualizer, None)
        self.assertNotIn('snc-py-exp="obj.name"', html_out)
        self.assertNotIn('class="py-exp-grab"', html_out)
        self.assertNotIn('class="py-exp-cell"', html_out)

    def test_py_exp_plain_value_uses_grab(self):
        """Plain text values use the simple grab wrapper."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertIn('class="py-exp-grab"', html_out)

    def test_no_py_exp_on_callable_fields(self):
        """Callable fields should not get snc-py-exp."""
        obj = CallableFieldObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.my_method', '^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertNotIn('snc-py-exp="obj.my_method"', html_out)
        self.assertIn('snc-py-exp="obj.x"', html_out)

    def test_no_py_exp_on_error_fields(self):
        """Error fields should not get snc-py-exp."""
        obj = ErrorFieldObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('obj', 'obj'))
        model['fields'] = ['^.bad', '^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        self.assertNotIn('snc-py-exp="obj.bad"', html_out)
        self.assertIn('snc-py-exp="obj.x"', html_out)

    def test_source_expr_stored_in_model(self):
        """init_model should store _source_expr from var_and_exp."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer, var_and_exp=('p', 'p'))
        self.assertEqual(model['_source_expr'], 'p')

    def test_source_expr_none_without_var_and_exp(self):
        """init_model without var_and_exp should store None."""
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        self.assertIsNone(model['_source_expr'])

    def test_bracket_accessor_expression(self):
        """Bracket accessor like ^[0] should produce correct expression."""
        import re
        match = re.search(r'hello', 'hello world')
        model = init_model(match, _get_visualizer, var_and_exp=('m', 'm'))
        model['fields'] = ['^[0]']
        html_out = visualize(match, model, _get_visualizer, None)
        self.assertIn('snc-py-exp="m[0]"', html_out)


class TestGetFields(unittest.TestCase):
    """Test get_fields and eval_caret_expr integration on z_object_visualizer."""

    def test_returns_accessor_codes_for_object(self):
        from z_object_visualizer import get_fields
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        p = Point(1, 2)
        fields = get_fields(p)
        self.assertIn('^.x', fields)
        self.assertIn('^.y', fields)

    def test_primitives_return_none(self):
        from z_object_visualizer import get_fields
        self.assertIsNone(get_fields(None))
        self.assertIsNone(get_fields(42))
        self.assertIsNone(get_fields(3.14))

    def test_eval_caret_expr_returns_raw_value(self):
        from visualizer_utils import eval_caret_expr
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        p = Point(1, 2)
        self.assertEqual(eval_caret_expr('^.x', p), 1)
        self.assertEqual(eval_caret_expr('^.y', p), 2)

    def test_eval_caret_expr_raises_on_error(self):
        from visualizer_utils import eval_caret_expr
        class Empty:
            pass
        with self.assertRaises(AttributeError):
            eval_caret_expr('^.nonexistent', Empty())


class TestObjectVisualizerTooltips(unittest.TestCase):
    """The icon-only object visualizer controls (drag handle, remove field,
    add field) must use the snc-tooltip system (data-tooltip) instead of the
    native title attribute, matching the string visualizer's tool toolbar."""

    def test_remove_field_button_has_data_tooltip(self):
        import re
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.y']
        html_out = visualize(obj, model, _get_visualizer, None)
        m = re.search(
            r'<td snc-mouse-down="RemoveFieldClick[^"]*"([^>]*?)>',
            html_out,
        )
        self.assertIsNotNone(m, "RemoveFieldClick button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Remove attribute"', attrs)
        self.assertNotIn('title="Remove field"', attrs,
                         "Should use data-tooltip instead of native title")

    def test_drag_handle_has_data_tooltip(self):
        import re
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x', '^.y']
        html_out = visualize(obj, model, _get_visualizer, None)
        m = re.search(
            r'<td snc-mouse-down="DragStart[^"]*"([^>]*?)>',
            html_out,
        )
        self.assertIsNotNone(m, "DragStart handle not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Drag to reorder"', attrs)
        self.assertNotIn('title="Drag to reorder"', attrs,
                         "Should use data-tooltip instead of native title")

    def test_add_field_button_has_data_tooltip(self):
        import re
        obj = TestObj()
        model = init_model(obj, _get_visualizer)
        model['fields'] = ['^.x']
        html_out = visualize(obj, model, _get_visualizer, None)
        m = re.search(
            r'<tr snc-mouse-down="AddFieldClick[^"]*"([^>]*?)>',
            html_out,
        )
        self.assertIsNotNone(m, "AddFieldClick (+) row not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Add attribute"', attrs)


class TestNestedSlotsConfig(unittest.TestCase):
    """The object config is nested: a field whose value is the same type does
    NOT re-apply the type config (which would recurse); nesting uses the field's
    explicit children config or a depth-capped default."""

    def test_root_model_stores_config_fields(self):
        o = TestObj()
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=['^.x']):
            model = init_model(o, _get_nesting_visualizer)
        self.assertEqual(model['_config_root_type'], _get_full_class_name(o))
        self.assertEqual(model['_config_root_dotfile'], DOTFILE_NAME)
        self.assertEqual(model['_config_path'], [])
        self.assertEqual(model['_slot_children'], {})

    def test_nested_fields_config_applies(self):
        class Inner:
            def __init__(self):
                self.a = 1
                self.b = 2

        class Outer:
            def __init__(self):
                self.inner = Inner()

        o = Outer()
        inner_type = _get_full_class_name(o.inner)
        slots = [{'expr': '^.inner', 'children': {inner_type: [{'expr': '^.a'}]}}]
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=slots):
            model = init_model(o, _get_nesting_visualizer)
        child = model['children']['^.inner']
        self.assertEqual(child['fields'], ['^.a'])

    def test_cross_type_object_field_list_uses_nested_columns(self):
        class Holder:
            def __init__(self):
                self.items = ['ABCdef', 'GHIjkl']

        o = Holder()
        slots = [{'expr': '^.items',
                  'children': {'builtins.str': [{'expr': '^.lower()'}]}}]
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=slots):
            model = init_model(o, _get_nesting_visualizer)
        child = model['children']['^.items']  # a list-visualizer model
        self.assertEqual(child['columns'], ['^.lower()'])

    def test_cyclic_object_is_depth_capped_not_recursion_error(self):
        class Node:
            def __init__(self):
                self.me = None

        o = Node()
        o.me = o  # self-referential; would recurse forever via dir() fallback
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=None):
            model = init_model(o, _get_nesting_visualizer)  # must not RecursionError

        def find_too_deep(m):
            if not isinstance(m, dict):
                return False
            if m.get('_too_deep'):
                return True
            return any(find_too_deep(c) for c in (m.get('children') or {}).values())

        def max_path_len(m):
            if not isinstance(m, dict):
                return 0
            here = len(m.get('_config_path') or [])
            children = (m.get('children') or {}).values()
            return max([here] + [max_path_len(c) for c in children])

        self.assertTrue(find_too_deep(model), 'expected a depth-capped leaf model')
        self.assertLessEqual(max_path_len(model), MAX_NEST_DEPTH)

    def test_field_add_saves_with_path_scoped_signature(self):
        o = TestObj()
        with patch('z_object_visualizer.load_fields_from_dotfile', return_value=['^.x']):
            model = init_model(o, _get_nesting_visualizer)
        model['adding_field'] = True
        event = make_mouse_down_event(repr(FieldSelect(accessor='^.y')))
        with patch('z_object_visualizer.save_fields_to_dotfile') as mock_save:
            update(event, None, model, o, _get_nesting_visualizer)
        mock_save.assert_called_once()
        args = mock_save.call_args.args
        self.assertEqual(args[0], _get_full_class_name(o))
        self.assertEqual(args[1], [])
        self.assertIn('^.y', args[2])


if __name__ == '__main__':
    unittest.main()
