"""
Tests for list_visualizer.py - list composition with child visualizers.

Run:
    python3 -m pytest list_visualizer_tests.py -v
"""

import unittest
import html
import os
import re
import shutil
import tempfile

from visualizer_utils import ChildEvent, wrap_drag_grab, MAX_NEST_DEPTH
import list_visualizer


# Isolate the entire test module from the user's cwd so that stray
# .snc_list_columns.json files (or other dotfiles created by other tests)
# don't influence column auto-detection.
#
# Strategy: chdir to a tempdir for the whole module, AND neutralise the
# save/load helpers so that one test's save can't pollute the next. Tests
# that genuinely exercise the dotfile (TestColumnDotfile) stop these
# patches in their own setUp.
import unittest.mock as _mock

_module_orig_cwd: str | None = None
_module_tmp_dir: str | None = None
_module_patches: list = []


def setUpModule():
    global _module_orig_cwd, _module_tmp_dir
    _module_orig_cwd = os.getcwd()
    _module_tmp_dir = tempfile.mkdtemp()
    os.chdir(_module_tmp_dir)

    p_load = _mock.patch('list_visualizer.load_columns_from_dotfile',
                         return_value=None)
    p_save = _mock.patch('list_visualizer.save_columns_to_dotfile')
    p_load.start()
    p_save.start()
    _module_patches.extend([p_load, p_save])


def tearDownModule():
    for p in _module_patches:
        p.stop()
    _module_patches.clear()
    if _module_orig_cwd is not None:
        os.chdir(_module_orig_cwd)
    if _module_tmp_dir is not None:
        shutil.rmtree(_module_tmp_dir, ignore_errors=True)
from list_visualizer import (
    can_visualize, init_model, visualize, update,
    AddColumnClick, ColumnInput, ColumnSelect, ColumnClick,
    RemoveColumnClick, ColumnDragStart, ColumnDragOver, ColumnDragEnd,
    ColumnKeyDown, COLUMN_DOTFILE_NAME, CELL_KEY_SEP,
    CopyToClipboard, ChangeSelectedText,
    load_columns_from_dotfile, save_columns_to_dotfile,
    _get_item_type_key, _get_column_suggestions, _get_all_possible_columns,
)


# === Mock event types for the mock string visualizer ===

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class MouseDown:
    index: int


# === Test helpers ===

class MockStringVisualizer:
    """Mimics a string visualizer with interactive model."""
    def can_visualize(self, value):
        return isinstance(value, str)
    def get_fields(self, value):
        return None
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return {'selection': None, 'handledKeys': ['Escape', 'Enter']}
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        inner = f'<span snc-mouse-down="MouseDown(index=0)">{html.escape(value)}</span>'
        # Mirror real visualizers: self-wrap for drag only in small mode.
        if small and var_and_exp:
            return wrap_drag_grab(inner, var_and_exp)
        return inner
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        model = dict(model)
        model['last_event'] = event['pythonEventStr']
        return (model, [])


class SmallTrackingVisualizer:
    """Mock visualizer that records the small= kwarg passed to visualize()."""
    def __init__(self):
        self.visualize_calls = []
    def can_visualize(self, value):
        return isinstance(value, str)
    def get_fields(self, value):
        return None
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return {'handledKeys': []}
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        self.visualize_calls.append({'value': value, 'small': small})
        return f'<span>{html.escape(value)}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class MockIntVisualizer:
    """Mimics a simple int visualizer (no interactive model -> generic).

    Echoes the access-path expression it receives via var_and_exp so tests can
    assert the parent delegates drag setup to the child."""
    def can_visualize(self, value):
        return isinstance(value, int)
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        expr = var_and_exp[1] if var_and_exp else ''
        return f'<span child-expr={expr}>{value}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class MockDictVisualizer:
    """Mimics a dict visualizer with get_fields support."""
    def can_visualize(self, value):
        return isinstance(value, dict)
    def get_fields(self, value):
        return [f"^[{repr(k)}]" for k in value.keys()]
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return f'<span>{html.escape(repr(value))}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class MockObjectVisualizer:
    """Mimics an object visualizer with get_fields support."""
    def can_visualize(self, value):
        return True
    def get_fields(self, value):
        if value is None or isinstance(value, (int, float)):
            return None
        names = sorted([name for name in dir(value) if not name.startswith('_')])
        return [f'^.{name}' for name in names]
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return f'<span>{html.escape(repr(value))}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class ListVisualizerAdapter:
    """Wraps the list_visualizer module to act like a visualizer object."""
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


_mock_string_vis = MockStringVisualizer()
_mock_int_vis = MockIntVisualizer()
_mock_dict_vis = MockDictVisualizer()
_mock_obj_vis = MockObjectVisualizer()
_mock_list_vis = ListVisualizerAdapter()


def mock_get_visualizer(value):
    if isinstance(value, list):
        return _mock_list_vis
    if isinstance(value, str):
        return _mock_string_vis
    if isinstance(value, dict):
        return _mock_dict_vis
    if isinstance(value, int):
        return _mock_int_vis
    return _mock_obj_vis


def make_child_mouse_event(child_key: str, py_ev_str: str) -> dict:
    """Create a ChildEvent mouse-down event for testing update()."""
    ce = ChildEvent(child_key=child_key, py_ev_str=py_ev_str)
    return {
        'pythonEventStr': repr(ce),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


# === Tests ===

class TestCanVisualize(unittest.TestCase):
    def test_list(self):
        self.assertTrue(can_visualize([1, 2, 3]))

    def test_empty_list(self):
        self.assertTrue(can_visualize([]))

    def test_not_list(self):
        self.assertFalse(can_visualize("hello"))
        self.assertFalse(can_visualize(42))
        self.assertFalse(can_visualize((1, 2)))


class TestInitModel(unittest.TestCase):
    def test_stores_child_models_by_composite_key(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn('children', model)
        self.assertIn('0\x00^', model['children'])
        self.assertIn('1\x00^', model['children'])

    def test_child_models_come_from_child_visualizer(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        child_model = model['children']['0\x00^']
        self.assertEqual(child_model, _mock_string_vis.init_model("hello"))

    def test_int_child_model(self):
        lst = [42]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model['children']['0\x00^'])

    def test_aggregates_handled_keys(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn('handledKeys', model)
        self.assertIn('Escape', model['handledKeys'])
        self.assertIn('Enter', model['handledKeys'])

    def test_empty_list(self):
        model = init_model([], mock_get_visualizer)
        self.assertEqual(model['children'], {})
        self.assertIsInstance(model['handledKeys'], list)


class TestVisualize(unittest.TestCase):
    def test_output_contains_wrapped_child_events(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('snc-child-key=', output)

    def test_child_html_is_wrapped_with_correct_key(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        matches = re.findall(r'snc-child-key="([^"]*)"', output)
        self.assertTrue(len(matches) > 0)
        self.assertEqual(eval(html.unescape(matches[0])), '0\x00^')

    def test_multiple_items_have_different_keys(self):
        lst = ["a", "b"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        matches = re.findall(r'snc-child-key="([^"]*)"', output)
        keys = {eval(html.unescape(m)) for m in matches}
        self.assertIn('0\x00^', keys)
        self.assertIn('1\x00^', keys)

    def test_contains_child_content(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('hello', output)

    def test_renders_table(self):
        lst = [42]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<table', output)

    def test_empty_list(self):
        lst = []
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<table', output)


class TestUpdate(unittest.TestCase):
    def test_child_event_routes_to_child_visualizer(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        # Pre-focus the child so the mousedown dispatches; the first mousedown
        # on an unfocused child only pins focus (see TestFocusTracking).
        model['focused_child'] = '0\x00^'
        event = make_child_mouse_event('0\x00^', 'MouseDown(index=0)')
        new_model, commands = update(event, ('x', 'x'), model, lst, mock_get_visualizer)
        child_model = new_model['children']['0\x00^']
        self.assertIn('last_event', child_model)

    def test_child_event_preserves_other_children(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event('0\x00^', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn('1\x00^', new_model['children'])
        self.assertNotIn('last_event', new_model['children']['1\x00^'])

    def test_null_event_is_noop(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        new_model, commands = update(None, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_empty_event_is_noop(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        new_model, commands = update({}, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_child_commands_propagated(self):
        class CmdVis:
            def can_visualize(self, v): return True
            def init_model(self, v, get_visualizer=None, eval_in_scope=None, var_and_exp=None): return {}
            def visualize(self, v, m, gv, eval_in_scope=None, max_width=None, max_height=None): return '<span snc-mouse-down="X">x</span>'
            def update(self, event, var_and_exp, model, value, gv=None, eval_in_scope=None):
                return (model, ['test_command'])

        cmd_vis = CmdVis()
        get_vis = lambda v: cmd_vis

        lst = ["x"]
        model = init_model(lst, get_vis)
        model['focused_child'] = '0\x00^'  # see TestFocusTracking
        event = make_child_mouse_event('0\x00^', 'X')
        _, commands = update(event, None, model, lst, get_vis)
        self.assertIn('test_command', commands)

    def test_handled_keys_updated_after_child_event(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event('0\x00^', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn('handledKeys', new_model)


class TestNestedComposition(unittest.TestCase):
    """Test list of lists works (nested composition)."""

    def test_nested_list_is_table_mode(self):
        lst = [[1, 2], [3, 4]]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ['^[0]', '^[1]'])
        self.assertIn('0\x00^[0]', model['children'])
        self.assertIn('0\x00^[1]', model['children'])
        self.assertIn('1\x00^[0]', model['children'])
        self.assertIn('1\x00^[1]', model['children'])


class TestGetFields(unittest.TestCase):
    """Test get_fields and eval_caret_expr integration on list_visualizer."""

    def test_returns_string_indices(self):
        from list_visualizer import get_fields
        self.assertEqual(get_fields([10, 20, 30]), ['^[0]', '^[1]', '^[2]'])

    def test_empty_list(self):
        from list_visualizer import get_fields
        self.assertEqual(get_fields([]), [])

    def test_eval_caret_expr_roundtrip(self):
        from list_visualizer import get_fields
        from visualizer_utils import eval_caret_expr
        lst = [10, 20, 30]
        fields = get_fields(lst)
        self.assertEqual(eval_caret_expr(fields[0], lst), 10)
        self.assertEqual(eval_caret_expr(fields[2], lst), 30)


class TestTableDetection(unittest.TestCase):
    """Test that init_model detects table mode for homogeneous lists."""

    def test_list_of_dicts_is_table_mode(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("^['name']", model['columns'])
        self.assertIn("^['age']", model['columns'])

    def test_list_of_strings_is_table_mode_with_caret_column(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ['^'])

    def test_empty_list_is_table_mode(self):
        model = init_model([], mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ['^'])

    def test_list_of_lists_is_table_mode(self):
        lst = [[1, 2, 3], [4, 5, 6]]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ['^[0]', '^[1]', '^[2]'])

    def test_mixed_types_is_table_mode_with_caret_column(self):
        lst = ["hello", 42]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ['^'])

    def test_union_columns_from_different_field_sets(self):
        lst = [{'a': 1, 'b': 2}, {'b': 3, 'c': 4}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        cols = model['columns']
        self.assertIn("^['a']", cols)
        self.assertIn("^['b']", cols)
        self.assertIn("^['c']", cols)

    def test_list_of_objects_is_table_mode(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        lst = [Point(1, 2), Point(3, 4)]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn('^.x', model['columns'])
        self.assertIn('^.y', model['columns'])

    def test_single_item_list_of_dicts_is_table_mode(self):
        lst = [{'x': 1}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')

    def test_table_mode_has_cell_children(self):
        """In table mode, children are keyed by composite row\\x00field keys."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("0\x00^['name']", model['children'])
        self.assertIn("1\x00^['name']", model['children'])


class TestTableRendering(unittest.TestCase):
    """Test that visualize() renders HTML tables correctly in table mode."""

    def test_renders_table_element(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<table', output)
        self.assertIn('</table>', output)

    def test_renders_column_headers(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        unescaped = html.unescape(output)
        self.assertIn("^['name']", unescaped)
        self.assertIn("^['age']", unescaped)
        self.assertIn('<th', output)

    def test_renders_row_index_column(self):
        lst = [{'x': 1}, {'x': 2}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        # Row indices should appear
        self.assertIn('0', output)
        self.assertIn('1', output)

    def test_renders_cell_content(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Alice', output)

    def test_cell_html_wrapped_with_composite_key(self):
        """Cell HTML should be inside a snc-child-key span with composite key."""
        lst = [{'name': 'test_str'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        matches = re.findall(r'snc-child-key="([^"]*)"', output)
        found_composite = False
        for m in matches:
            key = eval(html.unescape(m))
            if '\x00' in key:
                found_composite = True
                break
        self.assertTrue(found_composite, "Expected composite key in snc-child-key")

    def test_missing_field_renders_empty_cell(self):
        lst = [{'a': 1}, {'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        unescaped = html.unescape(output)
        self.assertIn("^['a']", unescaped)
        self.assertIn("^['b']", unescaped)
        self.assertIn('<td></td>', output) # missing cell

    def test_string_list_renders_as_table(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<table', output)
        self.assertIn('hello', output)
        self.assertIn('world', output)

    def test_list_of_lists_renders_table(self):
        lst = [[1, 2], [3, 4]]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<table', output)
        self.assertIn('1', output)
        self.assertIn('4', output)


class TestTableEventRouting(unittest.TestCase):
    """Test that update() routes events to the correct cell in table mode."""

    def test_cell_event_routes_to_correct_cell(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        composite_key = "0\x00^['name']"
        model['focused_child'] = composite_key  # see TestFocusTracking
        event = make_child_mouse_event(composite_key, 'MouseDown(index=0)')
        new_model, commands = update(event, None, model, lst, mock_get_visualizer)
        cell_model = new_model['children'][composite_key]
        self.assertIn('last_event', cell_model)

    def test_cell_event_preserves_other_cells(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event("0\x00^['name']", 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        bob_key = "1\x00^['name']"
        self.assertIn(bob_key, new_model['children'])
        bob_model = new_model['children'][bob_key]
        if bob_model and isinstance(bob_model, dict):
            self.assertNotIn('last_event', bob_model)

    def test_null_event_is_noop_in_table_mode(self):
        lst = [{'x': 1}]
        model = init_model(lst, mock_get_visualizer)
        new_model, commands = update(None, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model, model)
        self.assertEqual(commands, [])

    def test_cell_commands_propagated(self):
        class CmdVis:
            def can_visualize(self, v): return isinstance(v, str)
            def init_model(self, v, get_visualizer=None, eval_in_scope=None, var_and_exp=None): return {}
            def visualize(self, v, m, gv, eval_in_scope=None, max_width=None, max_height=None): return '<span snc-mouse-down="X">x</span>'
            def update(self, event, var_and_exp, model, value, gv=None, eval_in_scope=None):
                return (model, ['table_cmd'])

        cmd_vis = CmdVis()

        def get_vis(v):
            if isinstance(v, dict):
                return _mock_dict_vis
            if isinstance(v, str):
                return cmd_vis
            return _mock_int_vis

        lst = [{'k': 'val'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['k']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00^['k']", 'X')
        _, commands = update(event, None, model, lst, get_vis)
        self.assertIn('table_cmd', commands)


class TestVisualizeMaxDimensions(unittest.TestCase):
    """Test that visualize() accepts optional max_width and max_height."""

    def test_accepts_max_width_and_max_height(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        output_default = visualize(lst, model, mock_get_visualizer, None)
        output_with_dims = visualize(lst, model, mock_get_visualizer, None, max_width=100, max_height=50)
        self.assertIn('<table', output_default)
        self.assertIn('<table', output_with_dims)

    def test_dict_list_accepts_max_width_and_max_height(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None, max_width=200, max_height=100)
        self.assertIn('<table', output)

    def test_empty_list_accepts_max_width_and_max_height(self):
        lst = []
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None, max_width=50, max_height=50)
        self.assertIn('<table', output)


class TestSmallParameter(unittest.TestCase):
    """Test that visualize() passes small=True to nested children, except focused."""

    def test_visualize_accepts_small_parameter(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None, small=True)
        self.assertIn('hello', output)

    def test_children_receive_small_true_by_default(self):
        tracker = SmallTrackingVisualizer()
        get_vis = lambda v: tracker
        lst = ["a", "b"]
        model = init_model(lst, get_vis)
        visualize(lst, model, get_vis, None)
        self.assertEqual(len(tracker.visualize_calls), 2)
        self.assertTrue(tracker.visualize_calls[0]['small'])
        self.assertTrue(tracker.visualize_calls[1]['small'])

    def test_focused_child_receives_small_false(self):
        tracker = SmallTrackingVisualizer()
        get_vis = lambda v: tracker
        lst = ["a", "b"]
        model = init_model(lst, get_vis)
        model['focused_child'] = '1\x00^'
        tracker.visualize_calls.clear()
        visualize(lst, model, get_vis, None)
        a_call = next(c for c in tracker.visualize_calls if c['value'] == 'a')
        b_call = next(c for c in tracker.visualize_calls if c['value'] == 'b')
        self.assertTrue(a_call['small'])
        self.assertFalse(b_call['small'])

    def test_no_focused_child_all_small(self):
        tracker = SmallTrackingVisualizer()
        get_vis = lambda v: tracker
        lst = ["a"]
        model = init_model(lst, get_vis)
        visualize(lst, model, get_vis, None)
        self.assertTrue(tracker.visualize_calls[0]['small'])

    def test_table_mode_children_receive_small_true(self):
        tracker = SmallTrackingVisualizer()
        def get_vis(v):
            if isinstance(v, dict):
                return _mock_dict_vis
            return tracker
        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        tracker.visualize_calls.clear()
        visualize(lst, model, get_vis, None)
        self.assertTrue(all(c['small'] for c in tracker.visualize_calls))

    def test_table_mode_focused_child_receives_small_false(self):
        tracker = SmallTrackingVisualizer()
        def get_vis(v):
            if isinstance(v, dict):
                return _mock_dict_vis
            return tracker
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"
        tracker.visualize_calls.clear()
        visualize(lst, model, get_vis, None)
        alice_call = next(c for c in tracker.visualize_calls if c['value'] == 'Alice')
        bob_call = next(c for c in tracker.visualize_calls if c['value'] == 'Bob')
        self.assertFalse(alice_call['small'])
        self.assertTrue(bob_call['small'])

class TestFocusTracking(unittest.TestCase):
    """Test that update() sets focused_child when routing child events."""

    def test_child_event_sets_focused_child(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event('0\x00^', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model.get('focused_child'), '0\x00^')

    def test_second_child_event_changes_focus(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        event1 = make_child_mouse_event('0\x00^', 'MouseDown(index=0)')
        model, _ = update(event1, None, model, lst, mock_get_visualizer)
        self.assertEqual(model.get('focused_child'), '0\x00^')
        event2 = make_child_mouse_event('1\x00^', 'MouseDown(index=0)')
        model, _ = update(event2, None, model, lst, mock_get_visualizer)
        self.assertEqual(model.get('focused_child'), '1\x00^')

    def test_table_cell_event_sets_focused_child(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        composite_key = "0\x00^['name']"
        event = make_child_mouse_event(composite_key, 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model.get('focused_child'), composite_key)


import json
from unittest.mock import patch


# === Column management test helpers ===

def make_column_mouse_event(python_event_str, detail=1, buttons=1):
    """Create a mouse down event for column management."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mousedown',
            'button': 0,
            'buttons': buttons,
            'detail': detail,
            'offsetY': 5,
            'elementHeight': 20,
            'timeStamp': 1000.0,
        },
    }


def make_column_key_event(key):
    """Create a ColumnKeyDown event."""
    return {
        'pythonEventStr': repr(ColumnKeyDown()),
        'eventJSON': {
            'type': 'keydown',
            'key': key,
            'metaKey': False,
            'shiftKey': False,
            'ctrlKey': False,
            'altKey': False,
        },
    }


def make_column_input_event(value):
    """Create a ColumnInput event."""
    return {
        'pythonEventStr': f"lambda e: ColumnInput(value=e.get('value', ''))",
        'eventJSON': {'type': 'input', 'value': value},
    }


def make_column_mouse_move_event(python_event_str, buttons=1):
    """Create a mouse move event for column drag."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mousemove',
            'buttons': buttons,
        },
    }


def make_column_mouse_up_event(python_event_str):
    """Create a mouse up event for column drag."""
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mouseup',
            'buttons': 0,
        },
    }


# === Column management tests ===

class TestColumnManagementInitModel(unittest.TestCase):
    """Test that init_model returns column management fields in table mode."""

    def test_table_mode_has_column_management_fields(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIsNone(model['editing_column_index'])
        self.assertFalse(model['adding_column'])
        self.assertEqual(model['column_input_value'], '')
        self.assertIsNone(model['selected_suggestion_index'])
        self.assertIsNone(model['column_drag_from'])
        self.assertIsNone(model['column_drag_over'])

    def test_string_list_has_column_management_fields(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIsNone(model['editing_column_index'])
        self.assertFalse(model['adding_column'])
        self.assertEqual(model['column_input_value'], '')

    def test_table_mode_has_own_handled_keys(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn('Enter', model['handledKeys'])
        self.assertIn('Escape', model['handledKeys'])
        self.assertIn('ArrowUp', model['handledKeys'])
        self.assertIn('ArrowDown', model['handledKeys'])
        self.assertIn('Tab', model['handledKeys'])

    def test_no_get_visualizer_has_column_management_fields(self):
        lst = [1, 2, 3]
        model = init_model(lst)
        self.assertIn('editing_column_index', model)
        self.assertIn('adding_column', model)


class TestColumnAdd(unittest.TestCase):
    """Test adding columns to the table."""

    def test_add_column_click_sets_adding_true(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(AddColumnClick()))
        new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertTrue(new_model['adding_column'])
        self.assertEqual(new_model['column_input_value'], '')
        self.assertIsNone(new_model['editing_column_index'])

    def test_column_select_adds_column_when_adding(self):
        lst = [{'name': 'Alice', 'age': 30, 'city': 'NYC'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "^['ci"
        event = make_column_mouse_event(repr(ColumnSelect(name="^['city']")))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn("^['city']", new_model['columns'])
        self.assertFalse(new_model['adding_column'])
        self.assertEqual(new_model['column_input_value'], '')

    def test_enter_commits_add_column(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "^['age']"
        event = make_column_key_event('Enter')
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn("^['age']", new_model['columns'])
        self.assertFalse(new_model['adding_column'])
        self.assertEqual(new_model['column_input_value'], '')

    def test_enter_with_empty_input_does_not_add(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        original_cols = list(model['columns'])
        model['adding_column'] = True
        model['column_input_value'] = ''
        event = make_column_key_event('Enter')
        new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], original_cols)
        self.assertFalse(new_model['adding_column'])

    def test_add_column_saves_dotfile(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        event = make_column_mouse_event(repr(ColumnSelect(name="^['extra']")))
        with patch('list_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()


class TestColumnEdit(unittest.TestCase):
    """Test editing existing columns."""

    def test_double_click_starts_editing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(ColumnClick(index=0)), detail=2)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['editing_column_index'], 0)
        self.assertEqual(new_model['column_input_value'], model['columns'][0])
        self.assertFalse(new_model['adding_column'])

    def test_single_click_does_not_start_editing(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(ColumnClick(index=0)), detail=1)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column_index'])

    def test_column_select_replaces_column_when_editing(self):
        lst = [{'name': 'Alice', 'age': 30, 'city': 'NYC'}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['ci"
        old_col = model['columns'][0]
        event = make_column_mouse_event(repr(ColumnSelect(name="^['city']")))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'][0], "^['city']")
        self.assertIsNone(new_model['editing_column_index'])

    def test_enter_commits_edit(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['age']"
        event = make_column_key_event('Enter')
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'][0], "^['age']")
        self.assertIsNone(new_model['editing_column_index'])

    def test_escape_cancels_edit(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        original_col = model['columns'][0]
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['bogus']"
        event = make_column_key_event('Escape')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column_index'])
        self.assertEqual(new_model['column_input_value'], '')
        self.assertEqual(new_model['columns'][0], original_col)


class TestColumnRemove(unittest.TestCase):
    """Test removing columns."""

    def test_remove_column_removes_from_list(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn("^['name']", model['columns'])
        name_idx = model['columns'].index("^['name']")
        event = make_column_mouse_event(repr(RemoveColumnClick(index=name_idx)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertNotIn("^['name']", new_model['columns'])

    def test_remove_column_saves_dotfile(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(RemoveColumnClick(index=0)))
        with patch('list_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()

    def test_remove_column_cleans_up_children(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        name_idx = model['columns'].index("^['name']")
        self.assertIn("0\x00^['name']", model['children'])
        event = make_column_mouse_event(repr(RemoveColumnClick(index=name_idx)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertNotIn("0\x00^['name']", new_model['children'])
        self.assertNotIn("1\x00^['name']", new_model['children'])

    def test_remove_out_of_range_is_noop(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        original_cols = list(model['columns'])
        event = make_column_mouse_event(repr(RemoveColumnClick(index=99)))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], original_cols)

    def test_remove_cancels_editing_if_index_matches(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['name']"
        event = make_column_mouse_event(repr(RemoveColumnClick(index=0)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column_index'])
        self.assertEqual(new_model['column_input_value'], '')

    def test_remove_adjusts_editing_index_when_before_editing(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 2
        model['column_input_value'] = model['columns'][2]
        event = make_column_mouse_event(repr(RemoveColumnClick(index=0)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['editing_column_index'], 1)


class TestColumnReorder(unittest.TestCase):
    """Test drag-and-drop column reordering."""

    def test_drag_start_sets_drag_from(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(ColumnDragStart(index=1)))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['column_drag_from'], 1)
        self.assertEqual(new_model['column_drag_over'], 1)

    def test_drag_over_sets_drag_over(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = 2
        event = make_column_mouse_move_event(repr(ColumnDragOver(index=0)), buttons=1)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['column_drag_over'], 0)

    def test_drag_over_cancels_on_button_release(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = 0
        model['column_drag_over'] = 1
        event = make_column_mouse_move_event(repr(ColumnDragOver(index=1)), buttons=0)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['column_drag_from'])
        self.assertIsNone(new_model['column_drag_over'])

    def test_drag_end_reorders_forward(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = 0
        model['column_drag_over'] = 2
        event = make_column_mouse_up_event(repr(ColumnDragEnd(index=2)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'][0], original[1])
        self.assertEqual(new_model['columns'][1], original[2])
        self.assertEqual(new_model['columns'][2], original[0])
        self.assertIsNone(new_model['column_drag_from'])
        self.assertIsNone(new_model['column_drag_over'])

    def test_drag_end_reorders_backward(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = 2
        model['column_drag_over'] = 0
        event = make_column_mouse_up_event(repr(ColumnDragEnd(index=0)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'][0], original[2])
        self.assertEqual(new_model['columns'][1], original[0])
        self.assertEqual(new_model['columns'][2], original[1])

    def test_drag_end_same_position_is_noop(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = 0
        model['column_drag_over'] = 0
        event = make_column_mouse_up_event(repr(ColumnDragEnd(index=0)))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], original)

    def test_drag_end_saves_dotfile(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = 0
        model['column_drag_over'] = 1
        event = make_column_mouse_up_event(repr(ColumnDragEnd(index=1)))
        with patch('list_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()

    def test_drag_end_without_drag_is_noop(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        event = make_column_mouse_up_event(repr(ColumnDragEnd(index=1)))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], original)


class TestColumnKeyboard(unittest.TestCase):
    """Test keyboard interaction in column input."""

    def test_escape_cancels_add(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "^['na"
        event = make_column_key_event('Escape')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertFalse(new_model['adding_column'])
        self.assertEqual(new_model['column_input_value'], '')
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_arrow_down_selects_first_suggestion(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = ''
        model['columns'] = []
        event = make_column_key_event('ArrowDown')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_arrow_up_selects_last_suggestion(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = ''
        model['columns'] = []
        event = make_column_key_event('ArrowUp')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, [], '')
        expected = min(len(suggestions), 10) - 1
        self.assertEqual(new_model['selected_suggestion_index'], expected)

    def test_arrow_down_wraps_around(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = ''
        model['columns'] = []
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, [], '')
        last_idx = min(len(suggestions), 10) - 1
        model['selected_suggestion_index'] = last_idx
        event = make_column_key_event('ArrowDown')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_tab_commits_selected_suggestion(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = ''
        model['columns'] = []
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, [], '')
        model['selected_suggestion_index'] = 0
        expected_col = suggestions[0]
        event = make_column_key_event('Tab')
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn(expected_col, new_model['columns'])
        self.assertFalse(new_model['adding_column'])
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_arrow_keys_noop_when_not_input_active(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_key_event('ArrowDown')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['selected_suggestion_index'])

    def test_column_input_updates_value(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        event = make_column_input_event("^['na")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['column_input_value'], "^['na")

    def test_column_input_auto_highlights_first_suggestion(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['columns'] = []
        event = make_column_input_event("^['n")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_column_input_clears_selection_when_no_suggestions(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['selected_suggestion_index'] = 0
        event = make_column_input_event("^['zzzzz")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['selected_suggestion_index'])


class TestColumnAutocomplete(unittest.TestCase):
    """Test column autocomplete suggestions."""

    def test_get_all_possible_columns_from_dicts(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'city': 'NYC'}]
        cols = _get_all_possible_columns(lst, mock_get_visualizer)
        self.assertIn("^['name']", cols)
        self.assertIn("^['age']", cols)
        self.assertIn("^['city']", cols)

    def test_get_column_suggestions_filters_existing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, ["^['name']"], '')
        self.assertNotIn("^['name']", suggestions)
        self.assertIn("^['age']", suggestions)

    def test_get_column_suggestions_filters_by_prefix(self):
        lst = [{'name': 'Alice', 'age': 30}]
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, [], "^['n")
        self.assertIn("^['name']", suggestions)
        self.assertNotIn("^['age']", suggestions)

    def test_get_all_possible_columns_empty_list(self):
        self.assertEqual(_get_all_possible_columns([], mock_get_visualizer), [])

    def test_get_all_possible_columns_from_objects(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        lst = [Point(1, 2), Point(3, 4)]
        cols = _get_all_possible_columns(lst, mock_get_visualizer)
        self.assertIn('^.x', cols)
        self.assertIn('^.y', cols)


class TestColumnDotfile(unittest.TestCase):
    """Test dotfile persistence for column configurations."""

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.chdir(self.tmp_dir)
        # The module-level setUp neuters load/save so they don't pollute other
        # tests; this class genuinely exercises them, so undo the patches for
        # the duration of each test.
        for p in _module_patches:
            p.stop()

    def tearDown(self):
        for p in _module_patches:
            p.start()
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_load_columns_missing_file(self):
        result = load_columns_from_dotfile('builtins.dict')
        self.assertIsNone(result)

    def test_save_and_load_columns(self):
        save_columns_to_dotfile('builtins.dict', [], ["^['name']", "^['age']"])
        result = load_columns_from_dotfile('builtins.dict')
        self.assertEqual(result, [{'expr': "^['name']"}, {'expr': "^['age']"}])

    def test_save_preserves_other_types(self):
        save_columns_to_dotfile('type.A', [], ['^.x'])
        save_columns_to_dotfile('type.B', [], ['^.y'])
        self.assertEqual(load_columns_from_dotfile('type.A'), [{'expr': '^.x'}])
        self.assertEqual(load_columns_from_dotfile('type.B'), [{'expr': '^.y'}])

    def test_load_corrupt_file(self):
        with open(COLUMN_DOTFILE_NAME, 'w') as f:
            f.write('not json{{{')
        result = load_columns_from_dotfile('builtins.dict')
        self.assertIsNone(result)

    def test_get_item_type_key_for_dict(self):
        self.assertEqual(_get_item_type_key([{'a': 1}]), 'builtins.dict')

    def test_get_item_type_key_for_empty_list(self):
        self.assertIsNone(_get_item_type_key([]))

    def test_get_item_type_key_for_custom_class(self):
        class Foo:
            pass
        key = _get_item_type_key([Foo()])
        self.assertIn('Foo', key)

    def test_init_model_loads_from_dotfile(self):
        save_columns_to_dotfile('builtins.dict', [], ["^['age']", "^['name']"])
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model['columns'], ["^['age']", "^['name']"])

    def test_init_model_falls_back_when_no_dotfile(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("^['name']", model['columns'])
        self.assertIn("^['age']", model['columns'])


class TestColumnVisualize(unittest.TestCase):
    """Test HTML rendering of column management controls in table mode."""

    def test_table_has_add_column_button(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('AddColumnClick', output)

    def test_table_headers_have_remove_button(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('RemoveColumnClick(index=0)', output)

    def test_table_headers_have_drag_handle(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ColumnDragStart(index=0)', output)
        self.assertIn('ColumnDragOver(index=0)', output)
        self.assertIn('ColumnDragEnd(index=0)', output)

    def test_table_headers_have_click_handler(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ColumnClick(index=0)', output)
        self.assertIn('ColumnClick(index=1)', output)

    def test_table_has_key_down_handler(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ColumnKeyDown', output)
        self.assertIn('snc-key-down', output)

    def test_table_shows_input_when_adding(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "^['na"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<input', output)
        self.assertIn('snc-input', output)
        self.assertIn('ColumnInput', output)

    def test_table_shows_input_when_editing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['name']"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<input', output)
        self.assertIn('snc-select-all', output)

    def test_table_shows_autocomplete_suggestions(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['columns'] = []
        model['column_input_value'] = "^['"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ColumnSelect', output)
        self.assertIn('snc-dropdown-panel', output)

    def test_input_has_autofocus_when_adding(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = ''
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('autofocus', output)

    def test_input_has_autofocus_when_editing(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column_index'] = 0
        model['column_input_value'] = "^['name']"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('autofocus', output)

    def test_child_events_still_route_in_table_mode(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        composite_key = "0\x00^['name']"
        model['focused_child'] = composite_key  # see TestFocusTracking
        event = make_child_mouse_event(composite_key, 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        cell_model = new_model['children'].get(composite_key)
        if cell_model and isinstance(cell_model, dict):
            self.assertIn('last_event', cell_model)


class TestColumnManagementForStringLists(unittest.TestCase):
    """Column management works for string lists (always table mode)."""

    def test_add_column_works_for_string_list(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        event = make_column_mouse_event(repr(AddColumnClick()))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertTrue(new_model['adding_column'])

    def test_remove_caret_column_from_string_list(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['columns'], ['^'])
        event = make_column_mouse_event(repr(RemoveColumnClick(index=0)))
        with patch('list_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], [])


class TestColumnHeaderExpression(unittest.TestCase):
    """Test that column headers in table mode have draggable snc-py-exp."""

    def test_column_header_no_snc_py_exp_without_source(self):
        """Column headers do not have snc-py-exp when var_and_exp is not provided."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('snc-py-exp', html_output)

    def test_column_header_has_snc_py_exp_with_source(self):
        """Column headers have snc-py-exp with list comprehension expression."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model.get('_source_expr'), 'people')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # Column ^['name'] -> [item['name'] for item in people]
        self.assertIn("snc-py-exp", html_output)
        expected_expr = html.escape("[item['name'] for item in people]")
        self.assertIn(f'snc-py-exp="{expected_expr}"', html_output)

    def test_column_header_is_draggable(self):
        """Column header snc-py-exp span should have draggable=true."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        expected_expr = html.escape("[item['name'] for item in people]")
        self.assertIn(f'snc-py-exp="{expected_expr}" draggable="true"', html_output)

    def test_column_header_bare_expression(self):
        """For a bare expression line (no assignment), uses the whole expression."""
        lst = [{'x': 1}, {'x': 2}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=(None, 'get_items()'))
        self.assertEqual(model.get('_source_expr'), 'get_items()')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        expected_expr = html.escape("[item['x'] for item in get_items()]")
        self.assertIn(f'snc-py-exp="{expected_expr}"', html_output)


class TestCellDraggablePyExp(unittest.TestCase):
    """Test that table cells have draggable snc-py-exp attributes."""

    def test_no_snc_py_exp_without_source(self):
        """Cells do not have snc-py-exp when var_and_exp is not provided."""
        lst = [{'age': 25}, {'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('snc-py-exp', html_output)

    def test_generic_cell_delegates_drag_to_child(self):
        """Generic cells (int, model=None) get NO parent-emitted wrapper; the
        child receives var_and_exp and self-wraps. The mock generic visualizer
        echoes the expression it was given so we can verify propagation."""
        lst = [{'age': 25}, {'age': 30}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # The child was handed the per-cell expression via var_and_exp.
        self.assertIn("child-expr=people[0]['age']", html_output)
        self.assertIn("child-expr=people[1]['age']", html_output)
        # Parent does not also wrap generic cells in py-exp-cell.
        self.assertNotIn('class="py-exp-cell"', html_output)

    def test_nongeneric_small_cell_whole_area_grab(self):
        """Non-generic small (non-focused) cells use whole-area py-exp-grab,
        not the old py-exp-cell border."""
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        expected_expr = html.escape("people[0]['name']")
        self.assertIn(f'snc-py-exp="{expected_expr}" draggable="true"', html_output)
        self.assertIn('class="py-exp-grab"', html_output)
        # The bulky border pattern is gone.
        self.assertNotIn('class="py-exp-cell"', html_output)
        self.assertNotIn('draggable="false"', html_output)

    def test_nongeneric_focused_cell_not_draggable(self):
        """The focused (interactive, small=False) non-generic cell gets NO drag
        wrapper - it needs its mouse events."""
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        model['focused_child'] = f"0{CELL_KEY_SEP}^['name']"
        html_output = visualize(lst, model, mock_get_visualizer, None)
        expected_expr = html.escape("people[0]['name']")
        # No drag wrapper around the focused cell.
        self.assertNotIn(f'snc-py-exp="{expected_expr}"', html_output)
        self.assertNotIn('class="py-exp-grab"', html_output)
        self.assertNotIn('class="py-exp-cell"', html_output)

    def test_nongeneric_cell_content_preserved(self):
        """Non-generic cell visualizer content should be present inside the wrapper."""
        lst = [{'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # MockStringVisualizer renders: <span snc-mouse-down="MouseDown(index=0)">Bob</span>
        self.assertIn('Bob</span>', html_output)


class TestListSelfWrapSmall(unittest.TestCase):
    """The list visualizer self-wraps as a drag handle when rendered small."""

    def test_small_with_var_and_exp_self_wraps(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('nums', 'nums'))
        html_output = visualize(lst, model, mock_get_visualizer, None,
                                small=True, var_and_exp=(None, 'nums'))
        self.assertIn('snc-py-exp="nums"', html_output)
        self.assertIn('draggable="true"', html_output)
        self.assertIn('class="py-exp-grab"', html_output)

    def test_small_without_var_and_exp_renders_bare(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('nums', 'nums'))
        html_output = visualize(lst, model, mock_get_visualizer, None, small=True)
        self.assertNotIn('py-exp-grab', html_output)

    def test_full_mode_not_self_wrapped(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('nums', 'nums'))
        html_output = visualize(lst, model, mock_get_visualizer, None,
                                small=False, var_and_exp=(None, 'nums'))
        # The list container itself is not a drag handle in full mode.
        self.assertFalse(html_output.startswith('<span snc-py-exp'))


class TestSourceExprInModel(unittest.TestCase):
    """Test that _source_expr is stored in the list model."""

    def test_source_expr_stored_in_table_model(self):
        lst = [{'x': 1}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        self.assertEqual(model['_source_expr'], 'data')

    def test_source_expr_none_without_var_and_exp(self):
        lst = [{'x': 1}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model.get('_source_expr'))

    def test_source_expr_stored_in_list_model(self):
        lst = ['a', 'b']
        model = init_model(lst, mock_get_visualizer, var_and_exp=('items', 'items'))
        self.assertEqual(model.get('_source_expr'), 'items')


# ============================================================================
# Search feature tests
# ============================================================================

from list_visualizer import (
    SearchBoxInput, FirstMatchToggle, ActionButtonClick, DropdownToggle,
    CopyToClipboard,
    parse_search_term, needs_implicit_caret,
    _get_search_context, generate_action, _get_matching_indices,
)


def make_search_input_event(value):
    """Create a SearchBoxInput event."""
    return {
        'pythonEventStr': f"lambda e: SearchBoxInput(value=e.get('value', ''))",
        'eventJSON': {'type': 'input', 'value': value},
    }


def make_search_key_event(key, meta=False, shift=False):
    """Create a key event for the search/action area."""
    return {
        'pythonEventStr': repr(ColumnKeyDown()),
        'eventJSON': {
            'type': 'keydown',
            'key': key,
            'metaKey': meta,
            'shiftKey': shift,
            'ctrlKey': False,
            'altKey': False,
        },
    }


def make_action_button_event(action, copy=False):
    """Create an ActionButtonClick event."""
    return {
        'pythonEventStr': repr(ActionButtonClick(action=action, copy=copy)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


def make_first_match_toggle_event():
    """Create a FirstMatchToggle event."""
    return {
        'pythonEventStr': repr(FirstMatchToggle()),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


def make_dropdown_toggle_event(dropdown_id):
    """Create a DropdownToggle event."""
    return {
        'pythonEventStr': repr(DropdownToggle(dropdown_id=dropdown_id)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


# === Search parsing tests ===

class TestParseSearchTerm(unittest.TestCase):
    """Test parse_search_term for classifying search text."""

    def test_none_returns_none(self):
        self.assertIsNone(parse_search_term(None))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_search_term(''))

    def test_slice_two_bounds(self):
        result = parse_search_term('2:5')
        self.assertEqual(result, ('slice', ('2', '5')))

    def test_slice_left_only(self):
        result = parse_search_term('2:')
        self.assertEqual(result, ('slice', ('2', '')))

    def test_slice_right_only(self):
        result = parse_search_term(':5')
        self.assertEqual(result, ('slice', ('', '5')))

    def test_bare_expression(self):
        result = parse_search_term('^ > 100')
        self.assertEqual(result, ('expr', '^ > 100'))

    def test_integer_literal_is_expr(self):
        result = parse_search_term('5')
        self.assertEqual(result, ('expr', '5'))

    def test_list_literal_is_expr(self):
        result = parse_search_term('[1,3,5]')
        self.assertEqual(result, ('expr', '[1,3,5]'))

    def test_predicate_with_caret(self):
        result = parse_search_term('^.name == "Alice"')
        self.assertEqual(result, ('expr', '^.name == "Alice"'))

    def test_complex_slice(self):
        result = parse_search_term('len(x):')
        self.assertEqual(result, ('slice', ('len(x)', '')))

    def test_string_with_colon_is_not_slice(self):
        result = parse_search_term('"a:b"')
        self.assertNotEqual(result[0], 'slice')


class TestNeedsImplicitCaret(unittest.TestCase):
    """Test detection of binary operators needing implicit ^ prepend."""

    def test_greater_than(self):
        self.assertTrue(needs_implicit_caret('> 100'))

    def test_less_than(self):
        self.assertTrue(needs_implicit_caret('< 50'))

    def test_greater_equal(self):
        self.assertTrue(needs_implicit_caret('>= 10'))

    def test_less_equal(self):
        self.assertTrue(needs_implicit_caret('<= 10'))

    def test_double_equals(self):
        self.assertTrue(needs_implicit_caret('== "hello"'))

    def test_not_equals(self):
        self.assertTrue(needs_implicit_caret('!= 0'))

    def test_in_operator(self):
        self.assertTrue(needs_implicit_caret('in [1,2,3]'))

    def test_not_in_operator(self):
        self.assertTrue(needs_implicit_caret('not in [1,2,3]'))

    def test_is_operator(self):
        self.assertTrue(needs_implicit_caret('is None'))

    def test_is_not_operator(self):
        self.assertTrue(needs_implicit_caret('is not None'))

    def test_dot_attribute(self):
        self.assertTrue(needs_implicit_caret('.startswith("foo")'))

    def test_no_implicit_for_caret_expr(self):
        self.assertFalse(needs_implicit_caret('^ > 100'))

    def test_no_implicit_for_integer(self):
        self.assertFalse(needs_implicit_caret('5'))

    def test_no_implicit_for_list(self):
        self.assertFalse(needs_implicit_caret('[1,2,3]'))

    def test_no_implicit_for_variable(self):
        self.assertFalse(needs_implicit_caret('len(^) > 3'))

    def test_no_implicit_for_none(self):
        self.assertFalse(needs_implicit_caret('None'))

    def test_with_leading_whitespace(self):
        self.assertTrue(needs_implicit_caret(' > 100'))


class TestGetMatchingIndices(unittest.TestCase):
    """Test _get_matching_indices for various search types."""

    def test_predicate_match(self):
        lst = [10, 20, 30, 40, 50]
        indices = _get_matching_indices('^ > 25', lst, eval)
        self.assertEqual(indices, [2, 3, 4])

    def test_predicate_no_match(self):
        lst = [1, 2, 3]
        indices = _get_matching_indices('^ > 100', lst, eval)
        self.assertEqual(indices, [])

    def test_implicit_caret(self):
        lst = [10, 20, 30]
        indices = _get_matching_indices('> 15', lst, eval)
        self.assertEqual(indices, [1, 2])

    def test_index_search(self):
        lst = [10, 20, 30]
        indices = _get_matching_indices('1', lst, eval)
        self.assertEqual(indices, [1])

    def test_slice_search(self):
        lst = [10, 20, 30, 40, 50]
        indices = _get_matching_indices('1:3', lst, eval)
        self.assertEqual(indices, [1, 2])

    def test_multi_index_search(self):
        lst = [10, 20, 30, 40, 50]
        indices = _get_matching_indices('[0, 2, 4]', lst, eval)
        self.assertEqual(indices, [0, 2, 4])

    def test_empty_search(self):
        lst = [1, 2, 3]
        indices = _get_matching_indices('', lst, eval)
        self.assertEqual(indices, [])

    def test_none_search(self):
        lst = [1, 2, 3]
        indices = _get_matching_indices(None, lst, eval)
        self.assertEqual(indices, [])

    def test_predicate_with_equality(self):
        lst = ['alice', 'bob', 'alice']
        indices = _get_matching_indices('^ == "alice"', lst, eval)
        self.assertEqual(indices, [0, 2])


# === Code generation tests ===

class TestGetSearchContext(unittest.TestCase):
    """Test _get_search_context builds correct context dicts."""

    def test_predicate_context(self):
        model = {'search': '^ > 100', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['source_expr'], 'data')
        self.assertTrue(ctx['is_predicate'])
        self.assertEqual(ctx['predicate_expr'], 'item > 100')
        self.assertFalse(ctx['is_first'])

    def test_index_context(self):
        model = {'search': '5', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_index'])
        self.assertEqual(ctx['index_expr'], '5')

    def test_slice_context(self):
        model = {'search': '2:5', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_slice'])
        self.assertEqual(ctx['slice_start'], '2')
        self.assertEqual(ctx['slice_stop'], '5')

    def test_multi_index_context(self):
        model = {'search': '[1,3,5]', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_multi_index'])
        self.assertEqual(ctx['indices_expr'], '[1,3,5]')

    def test_implicit_caret_in_context(self):
        model = {'search': '> 100', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_predicate'])
        self.assertEqual(ctx['predicate_expr'], 'item > 100')

    def test_first_match_flag(self):
        model = {'search': '^ > 100', 'first_match': True}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertTrue(ctx['is_first'])

    def test_no_search_returns_none(self):
        model = {'search': None, 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNone(ctx)

    def test_no_source_returns_none(self):
        model = {'search': '^ > 0', 'first_match': False}
        ctx = _get_search_context(model, eval_in_scope=eval)
        self.assertIsNone(ctx)

    def test_dot_access_predicate(self):
        model = {'search': '.startswith("a")', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_predicate'])
        self.assertEqual(ctx['predicate_expr'], 'item.startswith("a")')

    # --- Broadcast slice contexts ---

    def test_broadcast_slice_start_list(self):
        model = {'search': '[1,2,4]:', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_broadcast_slice'])
        self.assertTrue(ctx['has_start_list'])
        self.assertFalse(ctx['has_stop_list'])
        self.assertEqual(ctx['start_list_expr'], '[1,2,4]')

    def test_broadcast_slice_stop_list(self):
        model = {'search': ':[3,5,7]', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_broadcast_slice'])
        self.assertFalse(ctx['has_start_list'])
        self.assertTrue(ctx['has_stop_list'])
        self.assertEqual(ctx['stop_list_expr'], '[3,5,7]')

    def test_broadcast_slice_both_lists(self):
        model = {'search': '[0,1]:[3,2]', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_broadcast_slice'])
        self.assertTrue(ctx['has_start_list'])
        self.assertTrue(ctx['has_stop_list'])
        self.assertEqual(ctx['start_list_expr'], '[0,1]')
        self.assertEqual(ctx['stop_list_expr'], '[3,2]')

    # --- Int-pair context ---

    def test_multi_pair_context(self):
        model = {'search': '[(0,2),(3,5)]', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_multi_pair'])
        self.assertEqual(ctx['pairs_expr'], '[(0,2),(3,5)]')


class TestGenerateAction(unittest.TestCase):
    """Test generate_action produces correct code for each action type."""

    def _predicate_ctx(self, predicate='item > 100', first=False, src='data'):
        return {
            'source_expr': src,
            'has_var': True,
            'suggest_base': src,
            'is_predicate': True,
            'predicate_expr': predicate,
            'is_first': first,
            'is_index': False,
            'is_slice': False,
            'is_multi_index': False,
        }

    def _index_ctx(self, index='5', src='data'):
        return {
            'source_expr': src,
            'has_var': True,
            'suggest_base': src,
            'is_index': True,
            'index_expr': index,
            'is_predicate': False,
            'is_first': True,
            'is_slice': False,
            'is_multi_index': False,
        }

    def _slice_ctx(self, start='2', stop='5', src='data'):
        return {
            'source_expr': src,
            'has_var': True,
            'suggest_base': src,
            'is_slice': True,
            'slice_start': start,
            'slice_stop': stop,
            'is_predicate': False,
            'is_first': True,
            'is_index': False,
            'is_multi_index': False,
        }

    def _multi_index_ctx(self, indices='[1,3,5]', src='data'):
        return {
            'source_expr': src,
            'has_var': True,
            'suggest_base': src,
            'is_multi_index': True,
            'indices_expr': indices,
            'is_predicate': False,
            'is_first': False,
            'is_index': False,
            'is_slice': False,
        }

    # --- Filter/Find One ---

    def test_filter_predicate(self):
        result = generate_action('filter', self._predicate_ctx())
        self.assertIsNotNone(result)
        name, code = result
        self.assertEqual(code, '[item for item in data if item > 100]')

    def test_filter_predicate_first(self):
        result = generate_action('filter', self._predicate_ctx(first=True))
        name, code = result
        self.assertEqual(code, 'next((item for item in data if item > 100), None)')

    def test_filter_index(self):
        result = generate_action('filter', self._index_ctx())
        name, code = result
        self.assertEqual(code, 'data[5]')

    def test_filter_slice(self):
        result = generate_action('filter', self._slice_ctx())
        name, code = result
        self.assertEqual(code, 'data[2:5]')

    def test_filter_multi_index(self):
        result = generate_action('filter', self._multi_index_ctx())
        name, code = result
        self.assertEqual(code, '[data[i] for i in [1,3,5]]')

    # --- Loop ---

    def test_loop_no_idx_predicate(self):
        result = generate_action('loop_no_idx', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, 'for item in (item for item in data if item > 100):\n    pass')

    def test_loop_orig_idx_predicate(self):
        result = generate_action('loop_orig_idx', self._predicate_ctx())
        name, code = result
        self.assertIn('for i, item in enumerate(data)', code)
        self.assertIn('if item > 100', code)

    def test_loop_new_idx_predicate(self):
        result = generate_action('loop_new_idx', self._predicate_ctx())
        name, code = result
        self.assertIn('for i, item in enumerate', code)
        self.assertIn('if item > 100', code)

    def test_loop_orig_idx_multi_index(self):
        result = generate_action('loop_orig_idx', self._multi_index_ctx())
        name, code = result
        self.assertIn('for i in [1,3,5]', code)

    # --- Any/All ---

    def test_any_predicate(self):
        result = generate_action('any', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, 'any(item > 100 for item in data)')

    def test_all_predicate(self):
        result = generate_action('all', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, 'all(item > 100 for item in data)')

    def test_if_any_predicate(self):
        result = generate_action('if_any', self._predicate_ctx())
        name, code = result
        self.assertIn('if any(item > 100 for item in data)', code)
        self.assertIn('pass', code)

    def test_if_all_predicate(self):
        result = generate_action('if_all', self._predicate_ctx())
        name, code = result
        self.assertIn('if all(item > 100 for item in data)', code)
        self.assertIn('pass', code)

    # --- Delete ---

    def test_delete_predicate(self):
        result = generate_action('delete', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, '[item for item in data if not (item > 100)]')

    def test_delete_predicate_first(self):
        result = generate_action('delete', self._predicate_ctx(first=True))
        name, code = result
        self.assertIn('data[:i]', code)
        self.assertIn('data[i+1:]', code)

    def test_delete_index(self):
        result = generate_action('delete', self._index_ctx())
        name, code = result
        self.assertEqual(code, 'data[:5] + data[5+1:]')

    def test_delete_slice(self):
        result = generate_action('delete', self._slice_ctx())
        name, code = result
        self.assertEqual(code, 'data[:2] + data[5:]')

    # --- Find Indices ---

    def test_find_indices_predicate(self):
        result = generate_action('find_indices', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, '[i for i, item in enumerate(data) if item > 100]')

    def test_find_indices_predicate_first(self):
        result = generate_action('find_indices', self._predicate_ctx(first=True))
        name, code = result
        self.assertEqual(code, 'next((i for i, item in enumerate(data) if item > 100), None)')

    def test_find_indices_index(self):
        result = generate_action('find_indices', self._index_ctx())
        name, code = result
        self.assertEqual(code, '5')

    def test_find_indices_multi_index(self):
        result = generate_action('find_indices', self._multi_index_ctx())
        name, code = result
        self.assertEqual(code, '[1,3,5]')

    # --- Count ---

    def test_count_predicate(self):
        result = generate_action('count', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, 'sum(1 for item in data if item > 100)')

    def test_count_multi_index(self):
        result = generate_action('count', self._multi_index_ctx())
        name, code = result
        self.assertEqual(code, 'len([1,3,5])')

    # --- Suggest names ---

    def test_filter_suggest_name(self):
        result = generate_action('filter', self._predicate_ctx())
        name, _ = result
        self.assertEqual(name, 'data_filtered')

    def test_filter_first_suggest_name(self):
        result = generate_action('filter', self._predicate_ctx(first=True))
        name, _ = result
        self.assertEqual(name, 'data_match')

    def test_count_suggest_name(self):
        result = generate_action('count', self._predicate_ctx())
        name, _ = result
        self.assertEqual(name, 'data_count')

    def test_find_indices_suggest_name(self):
        result = generate_action('find_indices', self._predicate_ctx())
        name, _ = result
        self.assertEqual(name, 'data_indices')

    def test_loop_suggest_name_is_none(self):
        result = generate_action('loop_orig_idx', self._predicate_ctx())
        name, _ = result
        self.assertIsNone(name)

    def test_delete_suggest_name(self):
        result = generate_action('delete', self._predicate_ctx())
        name, _ = result
        self.assertEqual(name, 'data')

    # --- Broadcast slice generation ---

    def _broadcast_start_ctx(self, starts='[1,2,4]', stop='', src='data'):
        return {
            'source_expr': src, 'has_var': True, 'suggest_base': src,
            'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': False,
            'start_list_expr': starts, 'slice_stop': stop,
            'is_predicate': False, 'is_index': False, 'is_slice': False,
            'is_multi_index': False, 'is_first': False,
        }

    def _broadcast_stop_ctx(self, start='', stops='[3,5,7]', src='data'):
        return {
            'source_expr': src, 'has_var': True, 'suggest_base': src,
            'is_broadcast_slice': True, 'has_start_list': False, 'has_stop_list': True,
            'stop_list_expr': stops, 'slice_start': start,
            'is_predicate': False, 'is_index': False, 'is_slice': False,
            'is_multi_index': False, 'is_first': False,
        }

    def _broadcast_both_ctx(self, starts='[0,1]', stops='[3,2]', src='data'):
        return {
            'source_expr': src, 'has_var': True, 'suggest_base': src,
            'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': True,
            'start_list_expr': starts, 'stop_list_expr': stops,
            'is_predicate': False, 'is_index': False, 'is_slice': False,
            'is_multi_index': False, 'is_first': False,
        }

    def _multi_pair_ctx(self, pairs='[(0,2),(3,5)]', src='data'):
        return {
            'source_expr': src, 'has_var': True, 'suggest_base': src,
            'is_multi_pair': True, 'pairs_expr': pairs,
            'is_predicate': False, 'is_index': False, 'is_slice': False,
            'is_multi_index': False, 'is_first': False,
        }

    def test_filter_broadcast_start(self):
        result = generate_action('filter', self._broadcast_start_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[i:] for i in [1,2,4]]')

    def test_filter_broadcast_stop(self):
        result = generate_action('filter', self._broadcast_stop_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[:i] for i in [3,5,7]]')

    def test_filter_broadcast_both(self):
        result = generate_action('filter', self._broadcast_both_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[i:j] for i, j in zip([0,1], [3,2])]')

    def test_filter_broadcast_start_with_fixed_stop(self):
        result = generate_action('filter', self._broadcast_start_ctx(stop='5'))
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[i:5] for i in [1,2,4]]')

    def test_filter_broadcast_stop_with_fixed_start(self):
        result = generate_action('filter', self._broadcast_stop_ctx(start='1'))
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[1:i] for i in [3,5,7]]')

    def test_filter_multi_pair(self):
        result = generate_action('filter', self._multi_pair_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[data[i:j] for i, j in [(0,2),(3,5)]]')

    def test_delete_broadcast_start(self):
        result = generate_action('delete', self._broadcast_start_ctx(starts='[2]'))
        self.assertIsNotNone(result)

    def test_delete_multi_pair(self):
        result = generate_action('delete', self._multi_pair_ctx())
        self.assertIsNotNone(result)

    def test_count_broadcast_start(self):
        result = generate_action('count', self._broadcast_start_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'len([1,2,4])')

    def test_count_broadcast_both(self):
        result = generate_action('count', self._broadcast_both_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'len([0,1])')

    def test_count_multi_pair(self):
        result = generate_action('count', self._multi_pair_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'len([(0,2),(3,5)])')

    def test_find_indices_broadcast_start(self):
        result = generate_action('find_indices', self._broadcast_start_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[1,2,4]')

    def test_find_indices_multi_pair(self):
        result = generate_action('find_indices', self._multi_pair_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, '[i for i, j in [(0,2),(3,5)]]')

    def test_loop_no_idx_broadcast_start(self):
        result = generate_action('loop_no_idx', self._broadcast_start_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertIn('for item in [data[i:]', code)

    def test_loop_no_idx_multi_pair(self):
        result = generate_action('loop_no_idx', self._multi_pair_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertIn('for item in [data[i:j]', code)

    def test_any_broadcast_start(self):
        result = generate_action('any', self._broadcast_start_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'len([1,2,4]) > 0')

    def test_all_broadcast_both(self):
        result = generate_action('all', self._broadcast_both_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'len([0,1]) == len(data)')

    # --- Whole list (no search) ---

    def _whole_list_ctx(self, src='data'):
        return {
            'source_expr': src,
            'has_var': True,
            'suggest_base': src,
            'is_whole_list': True,
            'is_predicate': False,
            'is_index': False,
            'is_slice': False,
            'is_multi_index': False,
            'is_first': False,
        }

    def test_whole_list_loop_no_idx(self):
        result = generate_action('loop_no_idx', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'for item in data:\n    pass')

    def test_whole_list_loop_orig_idx(self):
        result = generate_action('loop_orig_idx', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'for i, item in enumerate(data):\n    pass')

    def test_whole_list_loop_new_idx(self):
        result = generate_action('loop_new_idx', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'for i, item in enumerate(data):\n    pass')

    def test_whole_list_any(self):
        result = generate_action('any', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'any(data)')

    def test_whole_list_all(self):
        result = generate_action('all', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'all(data)')

    def test_whole_list_if_any(self):
        result = generate_action('if_any', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'if any(data):\n    pass')

    def test_whole_list_if_all(self):
        result = generate_action('if_all', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'if all(data):\n    pass')

    def test_whole_list_count(self):
        result = generate_action('count', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'sum(1 for item in data if item)')

    def test_whole_list_filter_returns_none(self):
        result = generate_action('filter', self._whole_list_ctx())
        self.assertIsNone(result)

    def test_whole_list_delete_returns_none(self):
        result = generate_action('delete', self._whole_list_ctx())
        self.assertIsNone(result)

    def test_whole_list_find_indices_returns_none(self):
        result = generate_action('find_indices', self._whole_list_ctx())
        self.assertIsNone(result)

    def test_whole_list_suggest_names(self):
        result = generate_action('count', self._whole_list_ctx())
        name, _ = result
        self.assertEqual(name, 'data_count')
        result = generate_action('any', self._whole_list_ctx())
        name, _ = result
        self.assertEqual(name, 'data_any')
        result = generate_action('loop_no_idx', self._whole_list_ctx())
        name, _ = result
        self.assertIsNone(name)

    # --- Join ---

    def test_join_predicate(self):
        ctx = self._predicate_ctx()
        ctx['join_separator'] = "', '"
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "', '.join(str(item) for item in data if item > 100)")

    def test_join_predicate_empty_sep(self):
        ctx = self._predicate_ctx()
        ctx['join_separator'] = "''"
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "''.join(str(item) for item in data if item > 100)")

    def test_join_whole_list(self):
        ctx = self._whole_list_ctx()
        ctx['join_separator'] = "', '"
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "', '.join(str(item) for item in data)")

    def test_join_multi_index(self):
        ctx = self._multi_index_ctx()
        ctx['join_separator'] = "','"
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "','.join(str(data[i]) for i in [1,3,5])")

    def test_join_slice(self):
        ctx = self._slice_ctx()
        ctx['join_separator'] = "'\\n'"
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "'\\n'.join(str(item) for item in data[2:5])")

    def test_join_index_returns_none(self):
        ctx = self._index_ctx()
        ctx['join_separator'] = "','"
        result = generate_action('join', ctx)
        self.assertIsNone(result)

    def test_join_suggest_name(self):
        ctx = self._predicate_ctx()
        ctx['join_separator'] = "','"
        result = generate_action('join', ctx)
        name, _ = result
        self.assertEqual(name, 'data_joined')

    def test_join_bare_expression(self):
        ctx = self._predicate_ctx()
        ctx['join_separator'] = 'chr(10)'
        result = generate_action('join', ctx)
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, "chr(10).join(str(item) for item in data if item > 100)")


# === Matching tests for broadcast/pair ===

class TestBroadcastAndPairMatching(unittest.TestCase):
    """Test _get_matching_indices handles broadcast slices and int pairs."""

    def test_broadcast_start_list_matching(self):
        lst = list(range(10))
        indices = _get_matching_indices('[1,3]:', lst, eval)
        self.assertIn(1, indices)
        self.assertIn(3, indices)
        self.assertIn(9, indices)
        self.assertNotIn(0, indices)

    def test_broadcast_stop_list_matching(self):
        lst = list(range(10))
        indices = _get_matching_indices(':[3,5]', lst, eval)
        self.assertIn(0, indices)
        self.assertIn(4, indices)
        self.assertNotIn(5, indices)

    def test_broadcast_both_lists_matching(self):
        lst = list(range(10))
        indices = _get_matching_indices('[0,5]:[3,8]', lst, eval)
        self.assertIn(0, indices)
        self.assertIn(2, indices)
        self.assertIn(5, indices)
        self.assertIn(7, indices)
        self.assertNotIn(3, indices)
        self.assertNotIn(8, indices)

    def test_multi_pair_matching(self):
        lst = list(range(10))
        indices = _get_matching_indices('[(1,3),(6,8)]', lst, eval)
        self.assertIn(1, indices)
        self.assertIn(2, indices)
        self.assertIn(6, indices)
        self.assertIn(7, indices)
        self.assertNotIn(0, indices)
        self.assertNotIn(3, indices)
        self.assertNotIn(8, indices)


# === Event handling tests ===

class TestSearchBoxInput(unittest.TestCase):
    """Test SearchBoxInput event handling in update()."""

    def test_search_input_sets_model_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        event = make_search_input_event('^ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['search'], '^ > 15')

    def test_empty_search_input_clears_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_search_input_event('')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model.get('search'))

    def test_search_input_preserves_other_model_state(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        original_columns = list(model['columns'])
        event = make_search_input_event('^ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['columns'], original_columns)


class TestAutoLinkOnInteraction(unittest.TestCase):
    """First interaction that yields a parseable expression auto-inserts a
    linked filter LOC; subsequent interactions update it via ChangeSelectedText."""

    def test_first_search_input_auto_inserts_linked_filter(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        event = make_search_input_event('^ > 15')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)

        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIsInstance(cmd, tuple)
        self.assertIn('item for item in data if item > 15', cmd[1])
        self.assertEqual(new_model['linked_action'], 'filter')
        self.assertTrue(new_model.get('auto_linked_once'))

    def test_second_search_input_updates_via_change_selected_text(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model, first = update(make_search_input_event('^ > 15'), ('data', 'data'),
                              model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsInstance(first[0], tuple)

        model, commands = update(make_search_input_event('^ > 25'), ('data', 'data'),
                                 model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)
        self.assertIn('item > 25', commands[0].expression)
        self.assertTrue(model.get('auto_linked_once'))

    def test_linked_bare_expression_keeps_result_name(self):
        """A linked source expression must not become a variable-name prefix."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model, commands = update(
            make_search_input_event('^ > 15'),
            (None, 'data'),
            model,
            lst,
            mock_get_visualizer,
            eval_in_scope=eval,
        )
        self.assertEqual(commands[0][0], 'result_filtered')
        self.assertEqual(model['linked_source_expr'], '(data)')

        model, commands = update(
            make_action_button_event('count'),
            (None, 'data'),
            model,
            lst,
            mock_get_visualizer,
            eval_in_scope=eval,
        )
        self.assertEqual(commands[0].suggested_var_name, 'result_count')

    def test_no_var_and_exp_does_not_auto_link(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        # var_and_exp=None -> no source context -> no auto-insert.
        new_model, commands = update(make_search_input_event('^ > 15'), None,
                                     model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertIsNone(new_model.get('linked_action'))


class TestActionButtonClickAutoLinks(unittest.TestCase):
    """Clicking an action button while unlinked inserts the LOC and links it."""

    def test_action_button_click_inserts_and_links(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, commands = update(make_action_button_event('filter'),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 1)
        self.assertEqual(model['linked_action'], 'filter')
        self.assertEqual(model['linked_source_expr'], 'data')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertEqual(model['last_linked_expr'], tuples[0][1])

    def test_next_interaction_updates_in_place(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, first = update(make_action_button_event('filter'),
                              ('data', 'data'), model, lst,
                              mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(any(isinstance(c, tuple) for c in first))
        model, commands = update(make_search_input_event('^ > 25'),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))

    def test_copy_click_does_not_link(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, commands = update(make_action_button_event('filter', copy=True),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model.get('linked_action'))


class TestNoUnlinkButtonInActionBar(unittest.TestCase):
    """The unlink affordance moved to the front-end chain icon, so the
    visualizer no longer renders an 'Unlink' action button when linked."""

    def test_linked_render_has_no_unlink_button(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['linked_action'] = 'filter'
        html_out = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('Unlink', html_out)


class TestFirstMatchToggle(unittest.TestCase):
    """Test FirstMatchToggle event handling in update()."""

    def test_toggle_on(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['first_match'] = False
        event = make_first_match_toggle_event()
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertTrue(new_model['first_match'])

    def test_toggle_off(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['first_match'] = True
        event = make_first_match_toggle_event()
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertFalse(new_model['first_match'])


class TestActionButtonClick(unittest.TestCase):
    """Test ActionButtonClick event handling in update()."""

    def test_filter_action_emits_new_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_action_button_event('filter', copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        cmd = commands[0]
        self.assertIsInstance(cmd, tuple)
        self.assertIn('item for item in data if item > 15', cmd[1])

    def test_filter_copy_emits_clipboard(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_action_button_event('filter', copy=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        cmd = commands[0]
        self.assertIsInstance(cmd, CopyToClipboard)

    def test_no_search_filter_no_command(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event('filter', copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])

    def test_no_search_loop_emits_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event('loop_no_idx', copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn('for item in data', commands[0][1])

    def test_no_search_count_emits_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event('count', copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn('sum(1 for item in data if item)', commands[0][1])

    def test_no_search_any_emits_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event('any', copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertEqual(commands[0][1], 'any(data)')

    def test_no_search_copy_emits_clipboard(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event('count', copy=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertIn('sum(1 for item in data if item)', commands[0].text)

    def test_join_action_with_search_emits_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_action_button_event("join:','", copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn("','.join(str(item) for item in data if item > 15)", commands[0][1])

    def test_join_action_no_search_emits_code(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_action_button_event("join:', '", copy=False)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn("', '.join(str(item) for item in data)", commands[0][1])

    def test_join_copy_emits_clipboard(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_action_button_event("join:'\\n'", copy=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], CopyToClipboard)

    def test_join_custom_input_stored_in_dropdown(self):
        from list_visualizer import JoinSeparatorInput
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': 'action-join'}
        event = {
            'pythonEventStr': "lambda e: JoinSeparatorInput(value=e.get('value', ''))",
            'eventJSON': {'type': 'input', 'value': "' | '"},
        }
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['openDropdown']['customSep'], "' | '")

    def test_join_enter_key_with_custom_sep(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['openDropdown'] = {'id': 'action-join', 'customSep': "' | '"}
        event = make_search_key_event('Enter')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn("' | '.join(str(item) for item in data if item > 15)", commands[0][1])
        self.assertIsNone(new_model.get('openDropdown'))

    def test_join_enter_key_no_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        model['openDropdown'] = {'id': 'action-join', 'customSep': "','"}
        event = make_search_key_event('Enter')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn("','.join(str(item) for item in data)", commands[0][1])
        self.assertIsNone(new_model.get('openDropdown'))

    def test_join_enter_key_default_sep(self):
        """Enter with join dropdown open but no custom input uses default ''."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        model['openDropdown'] = {'id': 'action-join'}
        event = make_search_key_event('Enter')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIn("''.join(str(item) for item in data)", commands[0][1])


class TestDropdownToggle(unittest.TestCase):
    """Test DropdownToggle event handling for ? menu."""

    def test_open_dropdown(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        event = make_dropdown_toggle_event('action-predicate')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNotNone(new_model.get('openDropdown'))
        self.assertEqual(new_model['openDropdown']['id'], 'action-predicate')

    def test_close_dropdown(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': 'action-predicate'}
        event = make_dropdown_toggle_event('action-predicate')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model.get('openDropdown'))


# === Rendering tests ===

class TestSearchBoxRendering(unittest.TestCase):
    """Test search box HTML rendering."""

    def test_search_box_rendered_when_not_small(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('SearchBoxInput', output)
        self.assertIn('placeholder="Search"', output)

    def test_search_box_hidden_when_small(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None, small=True)
        self.assertNotIn('SearchBoxInput', output)

    def test_search_box_shows_current_value(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('value="^ &gt; 15"', output)

    def test_first_match_toggle_rendered(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('FirstMatchToggle', output)
        self.assertIn('1', output)

    def test_first_match_toggle_highlighted_when_on(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('search-button active', output)

    def test_no_replace_box(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('ReplaceBoxInput', output)
        self.assertNotIn('snc-replace-input', output)

    def test_no_case_sensitive_toggle(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('CaseSensitiveToggle', output)

    def test_no_capture_groups_toggle(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('CaptureGroupsToggle', output)


class TestActionButtonsRendering(unittest.TestCase):
    """Test action buttons HTML rendering."""

    def test_action_buttons_rendered_when_not_small(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ActionButtonClick', output)

    def test_action_buttons_hidden_when_small(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None, small=True)
        self.assertNotIn('ActionButtonClick', output)

    def test_filter_button_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("action=&#x27;filter&#x27;", output)

    def test_filter_label_changes_with_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Find One', output)

    def test_filter_label_without_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = False
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Filter', output)

    def test_loop_dropdown_trigger_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('snc-dropdown-trigger', output)
        self.assertIn('Loop', output)

    def test_delete_button_label_changes_with_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Delete First', output)

    def test_delete_button_label_without_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = False
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Delete All', output)

    def test_find_indices_button_label(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('First Index', output)

    def test_find_indices_disabled_for_index_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '1'
        output = visualize(lst, model, mock_get_visualizer, eval)
        find_idx_pos = output.find("action=&#x27;find_indices&#x27;, copy=False")
        self.assertGreater(find_idx_pos, -1)
        # The .action-button span starts before the snc-mouse-down attribute;
        # walk back to that <span class="..."> to inspect its class list.
        span_start = output.rfind('<span class="', 0, find_idx_pos)
        span_end = output.find('"', span_start + len('<span class="'))
        cls = output[span_start + len('<span class="'):span_end]
        self.assertIn('dimmed', cls)

    def test_count_button_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("action=&#x27;count&#x27;", output)

    def test_count_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        count_pos = output.find("action=&#x27;count&#x27;, copy=False")
        self.assertGreater(count_pos, -1)
        span_start = output.rfind('<span class="', 0, count_pos)
        span_end = output.find('"', span_start + len('<span class="'))
        cls = output[span_start + len('<span class="'):span_end]
        self.assertIn('dimmed', cls)

    def test_question_dropdown_button(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        # The Any/All trigger is a hover-menu (no DropdownToggle event); look
        # for the panel options to confirm it's rendered.
        self.assertIn("action=&#x27;any&#x27;", output)
        self.assertIn("action=&#x27;if_any&#x27;", output)
        self.assertIn('Any/All', output)

    def test_copy_buttons_present(self):
        # Inline copy buttons were replaced by the snc-action-tooltip system;
        # action buttons now expose the copy/drag expression via data-action-expr.
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('data-action-expr=', output)

    def test_filter_disabled_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, None)
        filter_pos = output.find("action=&#x27;filter&#x27;, copy=False")
        self.assertGreater(filter_pos, -1)
        span_start = output.rfind('<span class="', 0, filter_pos)
        span_end = output.find('"', span_start + len('<span class="'))
        cls = output[span_start + len('<span class="'):span_end]
        self.assertIn('dimmed', cls)

    def test_loop_enabled_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, None)
        loop_pos = output.find('Loop')
        self.assertGreater(loop_pos, -1)
        # Walk back to the .snc-dropdown-trigger span and check it's not dimmed.
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, loop_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertNotIn('dimmed', cls)

    def test_question_enabled_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, None)
        q_pos = output.find('Any/All')
        self.assertGreater(q_pos, -1)
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, q_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertNotIn('dimmed', cls)

    def test_count_enabled_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, None)
        count_pos = output.find("action=&#x27;count&#x27;, copy=False")
        self.assertGreater(count_pos, -1)
        span_start = output.rfind('<span class="', 0, count_pos)
        span_end = output.find('"', span_start + len('<span class="'))
        cls = output[span_start + len('<span class="'):span_end]
        self.assertNotIn('dimmed', cls)

    def test_count_shows_list_length_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('Count: 3', output)


class TestRowHighlighting(unittest.TestCase):
    """Test that matching rows are highlighted."""

    def test_matched_rows_have_border(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('row-match', output)

    def test_unmatched_rows_dimmed(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('row-dim', output)

    def test_all_rows_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('>10<', output)
        self.assertIn('>20<', output)
        self.assertIn('>30<', output)

    def test_no_highlight_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, eval)
        tr_sections = output.split('<tr')
        for section in tr_sections[2:]:
            self.assertNotIn('row-match', section.split('</tr>')[0])
            self.assertNotIn('row-dim', section.split('</tr>')[0])

    def test_first_match_mode_highlights_only_first(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        border_count = output.count('row-match')
        self.assertEqual(border_count, 1)
        self.assertIn('>10<', output)
        self.assertIn('>20<', output)
        self.assertIn('>30<', output)

    def test_no_hidden_rows_message(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertNotIn('rows hidden', output)
        self.assertNotIn('row hidden', output)

    def test_index_search_highlights_single_row(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '1'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('row-match', output)
        self.assertIn('>10<', output)
        self.assertIn('>20<', output)
        self.assertIn('>30<', output)


class TestEnterKeyFilter(unittest.TestCase):
    """Test that Enter key triggers filter action when search is active."""

    def test_enter_triggers_filter(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_search_key_event('Enter')
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn('item for item in data if item > 15', commands[0][1])

    def test_enter_no_op_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_search_key_event('Enter')
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])

    def test_enter_column_commit_takes_priority(self):
        """When adding a column, Enter commits the column (the column commit
        path doesn't filter; any auto-inserted LOC is the broad-link fallback)."""
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['adding_column'] = True
        model['column_input_value'] = '^.x'
        event = make_search_key_event('Enter')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)
        # The column was committed (not left in adding-column state).
        self.assertFalse(new_model['adding_column'])
        self.assertIn('^.x', new_model['columns'])


class TestCmdDeleteKey(unittest.TestCase):
    """Test that Cmd+Backspace triggers delete action."""

    def test_cmd_backspace_triggers_delete(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        event = make_search_key_event('Backspace', meta=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], tuple)
        self.assertIn('not (item > 15)', commands[0][1])

    def test_cmd_backspace_no_op_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        event = make_search_key_event('Backspace', meta=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])


class TestLoopDropdown(unittest.TestCase):
    """Test loop dropdown with 3 loop variants."""

    def test_loop_dropdown_rendered(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Loop', output)
        # Loop is now a hover-menu (data-hover-menu); options live in the
        # always-rendered panel.
        self.assertIn('data-hover-menu', output)

    def test_loop_dropdown_options_when_open(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['openDropdown'] = {'id': 'action-loop'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('loop_no_idx', output)
        self.assertIn('loop_orig_idx', output)
        self.assertIn('loop_new_idx', output)

    def test_loop_dropdown_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        loop_pos = output.find('Loop')
        self.assertGreater(loop_pos, -1)
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, loop_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertIn('dimmed', cls)

    def test_loop_dropdown_options_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        model['openDropdown'] = {'id': 'action-loop'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('loop_no_idx', output)
        self.assertIn('loop_orig_idx', output)
        self.assertIn('loop_new_idx', output)


class TestJoinDropdown(unittest.TestCase):
    """Test Join dropdown button rendering and behavior."""

    def test_join_dropdown_present(self):
        # Join is a hover-menu (no DropdownToggle event); check the panel
        # markup + JoinSeparatorInput row is always rendered.
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Join', output)
        self.assertIn('JoinSeparatorInput', output)

    def test_join_dropdown_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        join_pos = output.find('Join')
        self.assertGreater(join_pos, -1)
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, join_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertIn('dimmed', cls)

    def test_join_dropdown_enabled_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        output = visualize(lst, model, mock_get_visualizer, None)
        join_pos = output.find('Join')
        self.assertGreater(join_pos, -1)
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, join_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertNotIn('dimmed', cls)

    def test_join_dropdown_enabled_for_slice(self):
        # A plain slice selects a contiguous, multi-item region, so Join
        # applies even though `first` is forced True for slices.
        lst = [10, 20, 30, 40, 50]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '2:5'
        output = visualize(lst, model, mock_get_visualizer, None)
        join_pos = output.find('Join')
        self.assertGreater(join_pos, -1)
        trigger_start = output.rfind('<span class="snc-dropdown-trigger', 0, join_pos)
        trigger_end = output.find('"', trigger_start + len('<span class="'))
        cls = output[trigger_start + len('<span class="'):trigger_end]
        self.assertNotIn('dimmed', cls)

    def test_join_slice_preview_expr_present(self):
        # The slice Join rows should carry a runnable preview expression.
        lst = [10, 20, 30, 40, 50]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '2:5'
        output = visualize(lst, model, mock_get_visualizer, lambda c: eval(c, {'data': lst}))
        self.assertIn("&#x27;,&#x27;.join(str(item) for item in data[2:5])", output)

    def test_join_dropdown_highlighted_when_linked(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['linked_action'] = 'join'
        output = visualize(lst, model, mock_get_visualizer, None)
        join_pos = output.find('Join')
        self.assertGreater(join_pos, -1)
        # The Join button's <span class="action-button ... linked"> is just before "Join".
        btn_start = output.rfind('<span class="action-button', 0, join_pos)
        btn_end = output.find('"', btn_start + len('<span class="'))
        cls = output[btn_start + len('<span class="'):btn_end]
        self.assertIn('linked', cls)

    def test_join_dropdown_options_when_open(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['openDropdown'] = {'id': 'action-join'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("join:&#x27;&#x27;", output)
        self.assertIn("join:&#x27; &#x27;", output)
        self.assertIn("join:&#x27;,&#x27;", output)

    def test_join_custom_input_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['openDropdown'] = {'id': 'action-join'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('JoinSeparatorInput', output)

    def test_join_dropdown_options_without_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = None
        model['openDropdown'] = {'id': 'action-join'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("join:", output)
        self.assertIn('JoinSeparatorInput', output)


class TestPredicatePreview(unittest.TestCase):
    """Any/All dropdown shows a live True/False preview (like the string visualizer)."""

    def _scope(self, lst):
        return lambda c: eval(c, {'data': lst})

    def _viz(self, lst, search, **model_overrides):
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = search
        model.update(model_overrides)
        return visualize(lst, model, mock_get_visualizer, self._scope(lst))

    def test_any_shows_true_when_predicate_matches(self):
        out = self._viz([10, 20, 30], '^ > 15')
        self.assertIn('Any (<span class="snc-code">True</span>)', out)

    def test_any_shows_false_when_no_match(self):
        out = self._viz([10, 20, 30], '^ > 100')
        self.assertIn('Any (<span class="snc-code">False</span>)', out)

    def test_if_any_shows_preview(self):
        out = self._viz([10, 20, 30], '^ > 15')
        self.assertIn('If Any (<span class="snc-code">True</span>)', out)

    def test_all_shows_true_when_all_match(self):
        out = self._viz([10, 20, 30], '^ > 5')
        self.assertIn('All (<span class="snc-code">True</span>)', out)

    def test_all_shows_false_when_not_all_match(self):
        out = self._viz([10, 20, 30], '^ > 15')
        self.assertIn('All (<span class="snc-code">False</span>)', out)

    def test_if_all_shows_preview(self):
        out = self._viz([10, 20, 30], '^ > 5')
        self.assertIn('If All (<span class="snc-code">True</span>)', out)

    def test_no_preview_without_source_expr(self):
        # Without a source expr the expression can't be built, so no suffix.
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        out = visualize(lst, model, mock_get_visualizer, self._scope(lst))
        self.assertNotIn('Any (<span class="snc-code">', out)

    def test_no_preview_without_eval_in_scope(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = '^ > 15'
        out = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('Any (<span class="snc-code">', out)

    def test_all_no_preview_in_first_match_mode(self):
        out = self._viz([10, 20, 30], '^ > 15', first_match=True)
        # All is disabled in first-match mode → no suffix, but Any still previews.
        self.assertNotIn('All (<span class="snc-code">', out)
        self.assertIn('Any (<span class="snc-code">True</span>)', out)


class TestSearchInitModel(unittest.TestCase):
    """Test that init_model includes search-related fields."""

    def test_model_has_search_field(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model.get('search'))

    def test_model_has_first_match_field(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        self.assertFalse(model.get('first_match', False))

    def test_model_without_get_visualizer_has_search_fields(self):
        lst = [1, 2, 3]
        model = init_model(lst)
        self.assertIn('search', model)
        self.assertIn('first_match', model)


class TestScrollToMatch(unittest.TestCase):
    """Test snc-scroll-to-match attribute on first match row."""

    def test_scroll_to_match_after_search_input(self):
        """SearchBoxInput sets _scroll_to_match, first match row gets attribute."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        event = make_search_input_event('^ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertTrue(new_model.get('_scroll_to_match'))
        output = visualize(lst, new_model, mock_get_visualizer, eval)
        self.assertIn('snc-scroll-to-match', output)

    def test_scroll_to_match_on_first_matched_row_only(self):
        """Attribute appears on the first matched row, not subsequent matches."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 10'
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertEqual(output.count('snc-scroll-to-match'), 1)

    def test_no_scroll_to_match_without_flag(self):
        """Without _scroll_to_match flag, no attribute even with matches."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertNotIn('snc-scroll-to-match', output)

    def test_no_scroll_to_match_without_search(self):
        """No attribute when there's no search."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertNotIn('snc-scroll-to-match', output)

    def test_no_scroll_to_match_when_no_results(self):
        """No attribute when search has no matches."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 100'
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertNotIn('snc-scroll-to-match', output)

    def test_scroll_to_match_cleared_on_other_events(self):
        """Non-search events clear _scroll_to_match flag."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['_scroll_to_match'] = True
        event = make_first_match_toggle_event()
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertFalse(new_model.get('_scroll_to_match'))

    def test_scroll_to_match_with_first_match_mode(self):
        """In first-match mode, attribute still appears on the single match."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['first_match'] = True
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertEqual(output.count('snc-scroll-to-match'), 1)

    def test_scroll_to_match_on_tr_element(self):
        """The attribute should be on a <tr> element."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        idx = output.find('snc-scroll-to-match')
        preceding = output[max(0, idx - 60):idx]
        self.assertIn('<tr', preceding)


# =============================================================================
# Linked Editing Tests (bidirectional parsing integration)
# =============================================================================

from visualizer_utils import Unlink, Relink


def make_unlink_event():
    """Create an Unlink event."""
    return {
        'pythonEventStr': repr(Unlink()),
        'eventJSON': {},
    }


def make_relink_event(mode='insert', text=''):
    """Create a Relink event."""
    return {
        'pythonEventStr': repr(Relink(mode=mode, text=text)),
        'eventJSON': {'type': 'relink', 'mode': mode, 'text': text},
    }


class TestRelinkViaChainIcon(unittest.TestCase):
    """The chain icon re-establishes a link after Unlink, resuming the prior
    action. 'insert' emits a NewCode tuple; 'takeover' emits ChangeSelectedText."""

    def _linked_then_unlinked(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, _ = update(make_action_button_event('filter'), ('data', 'data'),
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_unlink_event(), ('data', 'data'),
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model.get('linked_action'))
        return model, lst

    def test_relink_insert_emits_new_code_and_resumes_action(self):
        model, lst = self._linked_then_unlinked()
        model, commands = update(make_relink_event('insert'), ('data', 'data'),
                                 model, lst, mock_get_visualizer, eval_in_scope=eval)
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 1)
        self.assertEqual(model['linked_action'], 'filter')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertEqual(model['last_linked_expr'], tuples[0][1])

    def test_relink_takeover_emits_change_selected_text_and_resumes_action(self):
        model, lst = self._linked_then_unlinked()
        model, commands = update(make_relink_event('takeover'), ('data', 'data'),
                                 model, lst, mock_get_visualizer, eval_in_scope=eval)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertEqual(model['linked_action'], 'filter')
        self.assertTrue(model['linked_has_assignment'])

    def test_relink_defaults_to_auto_link_action_when_none_stashed(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, _ = update(make_relink_event('insert'), ('data', 'data'),
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['linked_action'], 'filter')

    def test_relink_without_context_is_noop(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        # var_and_exp=None -> no source context -> no relink.
        model, commands = update(make_relink_event('insert'), None,
                                 model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertIsNone(model.get('linked_action'))


class TestRelinkTakeoverAdoptsExistingLine(unittest.TestCase):
    """On relink-takeover with a fresh model, the taken-over line is parsed and
    adopted into the model (its text left untouched) instead of being clobbered
    by a default-generated expression."""

    def setUp(self):
        self.lst = [1, 2, 3, 4, 5]
        self.var_and_exp = ('data', 'data')
        # A previously-generated linked line still present after a file reopen.
        self.line = 'data_filtered = [item for item in data if item > 3]'

    def test_fresh_takeover_adopts_line_without_commands(self):
        model = init_model(self.lst, mock_get_visualizer)
        model, commands = update(make_relink_event('takeover', text=self.line),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'filter')
        self.assertEqual(model.get('linked_source_expr'), 'data')
        self.assertTrue(model.get('linked_has_assignment'))
        self.assertTrue(model.get('auto_linked_once'))
        self.assertIsNotNone(model.get('search'))
        # The line is already in the editor; adoption must not rewrite it.
        self.assertEqual(commands, [])

    def test_interaction_after_adoption_emits_change_selected_text(self):
        model = init_model(self.lst, mock_get_visualizer)
        model, _ = update(make_relink_event('takeover', text=self.line),
                          self.var_and_exp, model, self.lst,
                          mock_get_visualizer, eval_in_scope=eval)
        model, commands = update(make_search_input_event('^ > 2'),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))
        self.assertFalse(any(isinstance(c, tuple) for c in commands))

    def test_stashed_unlink_action_wins_over_adoption(self):
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '^ > 15'
        model, _ = update(make_action_button_event('filter'), self.var_and_exp,
                          model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_unlink_event(), self.var_and_exp, model, self.lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model.get('linked_action'))
        model, commands = update(make_relink_event('takeover', text=self.line),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(model.get('linked_action'), 'filter')

    def test_unparseable_takeover_falls_back_to_generate(self):
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '^ > 3'
        model, commands = update(
            make_relink_event('takeover', text='???  not parseable  ???'),
            self.var_and_exp, model, self.lst, mock_get_visualizer,
            eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'filter')
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))


class TestCtxToModel(unittest.TestCase):
    """Test _ctx_to_model sets model search/first_match from parsed context."""

    def test_predicate_ctx_to_model(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item > 100', 'is_first': False}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '^ > 100')
        self.assertFalse(model['first_match'])

    def test_predicate_first_ctx_to_model(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item > 100', 'is_first': True}
        _ctx_to_model(ctx, model)
        self.assertTrue(model['first_match'])

    def test_index_ctx_to_model(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_index': True, 'index_expr': '5'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '5')

    def test_slice_ctx_to_model(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_slice': True, 'slice_start': '2', 'slice_stop': '5'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '2:5')

    def test_multi_index_ctx_to_model(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_multi_index': True, 'indices_expr': '[1,3,5]'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '[1,3,5]')

    def test_predicate_with_method_call(self):
        from list_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item.startswith("a")', 'is_first': False}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '^.startswith("a")')


class TestLinkedEditingBehavior(unittest.TestCase):
    """Downstream linked-editing behavior once a link is established.

    Formerly set up via the removed EditorTextSelect event; now the link is
    established the way it is in production — a fresh model adopting an existing
    generated line via Relink(mode='takeover')."""

    def setUp(self):
        self.var_and_exp = ('data', 'data')
        self.lst = [1, 2, 3, 4, 5]

    def _adopt(self, text):
        """Create a fresh model that has adopted an existing linked line."""
        model = init_model(self.lst, mock_get_visualizer, var_and_exp=self.var_and_exp)
        model, _ = update(make_relink_event('takeover', text=text), self.var_and_exp,
                          model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def test_unlink_clears_linked_state(self):
        model = self._adopt('[item for item in data if item > 3]')
        self.assertIsNotNone(model.get('linked_action'))
        event = make_unlink_event()
        model, _ = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertIsNone(model.get('linked_action'))
        self.assertIsNone(model.get('linked_source_expr'))
        self.assertIsNone(model.get('linked_has_assignment'))

    def test_linked_action_button_emits_change_selected_text(self):
        from list_visualizer import ChangeSelectedText
        model = self._adopt('[item for item in data if item > 3]')
        event = make_action_button_event('delete')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'delete')
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertTrue(len(change_cmds) > 0)

    def test_action_change_carries_new_var_name(self):
        """Switching action on an assignment-linked line suggests a new var name."""
        from list_visualizer import ChangeSelectedText
        # Assignment-form line links with target 'data_filtered'.
        model = self._adopt('data_filtered = [item for item in data if item > 3]')
        self.assertTrue(model.get('linked_has_assignment'))
        self.assertNotIn('linked_prefix', model)
        # Switch to delete -> suggested name becomes 'data'.
        event = make_action_button_event('delete')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(change_cmds[0].suggested_var_name, 'data')

    def test_unchanged_name_carries_no_new_var_name(self):
        """A search change that keeps the same action keeps the same name."""
        from list_visualizer import ChangeSelectedText
        model = self._adopt('data_filtered = [item for item in data if item > 3]')
        event = make_search_input_event('^ > 2')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertTrue(len(change_cmds) > 0)
        self.assertIsNone(change_cmds[0].suggested_var_name)

    def test_linked_join_menu_updates_selected_text(self):
        from list_visualizer import ChangeSelectedText
        model = self._adopt("''.join(str(item) for item in data)")
        self.assertEqual(model.get('linked_action'), 'join')
        event = make_action_button_event("join:', '")
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'join')
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(change_cmds[0].expression, "', '.join(str(item) for item in data)")

    def test_linked_search_change_emits_change_selected_text(self):
        from list_visualizer import ChangeSelectedText
        model = self._adopt('[item for item in data if item > 3]')
        event = make_search_input_event('^ > 2')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertTrue(len(change_cmds) > 0)

    def test_linked_enter_changes_action_to_filter(self):
        model = self._adopt('[item for item in data if item > 3]')
        model['linked_action'] = 'delete'
        event = make_search_key_event('Enter')
        model, _ = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'filter')

    def test_linked_cmd_backspace_changes_action_to_delete(self):
        model = self._adopt('[item for item in data if item > 3]')
        event = make_search_key_event('Backspace', meta=True)
        model, _ = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'delete')

    def test_nonlinked_action_button_emits_new_code(self):
        """Without linked mode, action buttons emit NewCode tuples, not ChangeSelectedText."""
        model = init_model(self.lst, mock_get_visualizer, var_and_exp=self.var_and_exp)
        model['search'] = '^ > 3'
        event = make_action_button_event('filter')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        tuple_cmds = [c for c in commands if isinstance(c, tuple)]
        self.assertTrue(len(tuple_cmds) > 0)


# =============================================================================
# DSL Grammar Roundtrip Tests (bidirectional parsing)
# =============================================================================

class _ListActionTestBase(unittest.TestCase):
    """Base class for list visualizer DSL grammar roundtrip tests."""

    def setUp(self):
        from list_visualizer_grammar import LIST_VIZ_GRAMMAR, generate_action as grammar_generate, parse_generated_code
        from bidirectional_dsl import generate, parse
        self.grammar = LIST_VIZ_GRAMMAR
        self.raw_generate = generate
        self.raw_parse = parse
        self.generate_action = grammar_generate
        self.parse_generated_code = parse_generated_code

    def _gen(self, action, ctx):
        gen_ctx = {k: v for k, v in ctx.items() if v is not None}
        gen_ctx['action'] = action
        if ctx.get('is_slice'):
            gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
            gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
        return self.raw_generate(self.grammar, self.grammar['Action'], gen_ctx)

    _GRAMMAR_KEYS = frozenset({
        'action', 'is_predicate', 'is_index', 'is_slice', 'is_multi_index',
        'is_first', 'source_expr', 'predicate_expr', 'index_expr',
        'slice_start', 'slice_stop', 'indices_expr',
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
        for key in self._GRAMMAR_KEYS:
            if key not in gen_ctx:
                continue
            expected = gen_ctx[key]
            actual = parsed.get(key)
            if expected is False and actual is None:
                continue
            if key in parsed:
                self.assertEqual(actual, expected,
                                 f"Parsed {key}={actual!r} != {expected!r} for: {code}")
        regen = self._gen(action, parsed)
        self.assertIsNotNone(regen, f"Regeneration failed from parsed context")
        self.assertEqual(regen[0], code, f"Roundtrip mismatch")


class TestListGrammarFilter(_ListActionTestBase):
    """Roundtrip tests for filter action."""

    def test_roundtrip_filter_predicate(self):
        self._roundtrip('filter', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_filter_predicate_first(self):
        self._roundtrip('filter', {
            'is_predicate': True, 'is_first': True,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_filter_index(self):
        self._roundtrip('filter', {
            'is_index': True, 'is_slice': False, 'is_multi_index': False,
            'index_expr': '5', 'source_expr': 'data',
        })

    def test_roundtrip_filter_slice(self):
        self._roundtrip('filter', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '2', 'slice_stop': '5', 'source_expr': 'data',
        })

    def test_roundtrip_filter_multi_index(self):
        self._roundtrip('filter', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })

    def test_roundtrip_filter_paren_source(self):
        self._roundtrip('filter', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 0', 'source_expr': '(get_list())',
        })


class TestListGrammarDelete(_ListActionTestBase):
    """Roundtrip tests for delete action."""

    def test_roundtrip_delete_predicate(self):
        self._roundtrip('delete', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_delete_predicate_first(self):
        self._roundtrip('delete', {
            'is_predicate': True, 'is_first': True,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_delete_index(self):
        self._roundtrip('delete', {
            'is_index': True, 'is_slice': False, 'is_multi_index': False,
            'index_expr': '5', 'source_expr': 'data',
        })

    def test_roundtrip_delete_slice_both(self):
        self._roundtrip('delete', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '2', 'slice_stop': '5', 'source_expr': 'data',
        })

    def test_roundtrip_delete_slice_start_only(self):
        self._roundtrip('delete', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '2', 'slice_stop': '', 'source_expr': 'data',
        })

    def test_roundtrip_delete_slice_stop_only(self):
        self._roundtrip('delete', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '', 'slice_stop': '5', 'source_expr': 'data',
        })

    def test_roundtrip_delete_multi_index(self):
        self._roundtrip('delete', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })


class TestListGrammarFindIndices(_ListActionTestBase):
    """Roundtrip tests for find_indices action."""

    def test_roundtrip_find_indices_predicate(self):
        self._roundtrip('find_indices', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_find_indices_predicate_first(self):
        self._roundtrip('find_indices', {
            'is_predicate': True, 'is_first': True,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_generate_find_indices_index(self):
        """Bare-expression patterns can't roundtrip (too greedy for parse) but must generate."""
        result = self.generate_action('find_indices', {
            'is_index': True, 'is_slice': False, 'is_multi_index': False,
            'index_expr': '5', 'source_expr': 'data', 'has_var': True, 'suggest_base': 'data',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[1], '5')

    def test_roundtrip_find_indices_slice(self):
        self._roundtrip('find_indices', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '2', 'slice_stop': '5', 'source_expr': 'data',
        })

    def test_find_indices_slice_empty_start_generates_and_parses(self):
        """Empty start generates list(range(0, ...)) which parses back with start='0'."""
        result = self.generate_action('find_indices', {
            'is_slice': True, 'is_index': False, 'is_multi_index': False,
            'slice_start': '', 'slice_stop': '5', 'source_expr': 'data',
            'has_var': True, 'suggest_base': 'data',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 'list(range(0, 5))')
        parsed = self.parse_generated_code(result[1])
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['action'], 'find_indices')

    def test_generate_find_indices_multi_index(self):
        """Bare-expression patterns can't roundtrip (too greedy for parse) but must generate."""
        result = self.generate_action('find_indices', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data', 'has_var': True, 'suggest_base': 'data',
        })
        self.assertIsNotNone(result)
        self.assertEqual(result[1], '[1,3,5]')


class TestListGrammarCount(_ListActionTestBase):
    """Roundtrip tests for count action."""

    def test_roundtrip_count_predicate(self):
        self._roundtrip('count', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_count_multi_index(self):
        self._roundtrip('count', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })


class TestListGrammarAnyAll(_ListActionTestBase):
    """Roundtrip tests for any/all actions."""

    def test_roundtrip_any_predicate(self):
        self._roundtrip('any', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_all_predicate(self):
        self._roundtrip('all', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_if_any_predicate(self):
        self._roundtrip('if_any', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_if_all_predicate(self):
        self._roundtrip('if_all', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_any_multi_index(self):
        self._roundtrip('any', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })

    def test_roundtrip_all_multi_index(self):
        self._roundtrip('all', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })


class TestListGrammarLoop(_ListActionTestBase):
    """Roundtrip tests for loop actions."""

    def test_roundtrip_loop_no_idx_predicate(self):
        self._roundtrip('loop_no_idx', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_loop_orig_idx_predicate(self):
        self._roundtrip('loop_orig_idx', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_loop_new_idx_predicate(self):
        self._roundtrip('loop_new_idx', {
            'is_predicate': True, 'is_first': False,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'item > 100', 'source_expr': 'data',
        })

    def test_roundtrip_loop_no_idx_multi_index(self):
        self._roundtrip('loop_no_idx', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })

    def test_roundtrip_loop_orig_idx_multi_index(self):
        self._roundtrip('loop_orig_idx', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })

    def test_roundtrip_loop_new_idx_multi_index(self):
        self._roundtrip('loop_new_idx', {
            'is_multi_index': True, 'is_index': False, 'is_slice': False,
            'indices_expr': '[1,3,5]', 'source_expr': 'data',
        })


class TestListGrammarParse(_ListActionTestBase):
    """Test parse_generated_code on known code strings."""

    def test_parse_filter_predicate(self):
        result = self.parse_generated_code('[item for item in data if item > 100]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'filter')
        self.assertEqual(result['source_expr'], 'data')
        self.assertEqual(result['predicate_expr'], 'item > 100')

    def test_parse_filter_predicate_first(self):
        result = self.parse_generated_code('next((item for item in data if item > 100), None)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'filter')
        self.assertTrue(result.get('is_first'))

    def test_parse_filter_index(self):
        result = self.parse_generated_code('data[5]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'filter')
        self.assertEqual(result['index_expr'], '5')

    def test_parse_filter_slice(self):
        result = self.parse_generated_code('data[2:5]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'filter')

    def test_parse_delete_predicate(self):
        result = self.parse_generated_code('[item for item in data if not (item > 100)]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'delete')

    def test_parse_delete_index(self):
        result = self.parse_generated_code('data[:5] + data[5+1:]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'delete')

    def test_parse_count_predicate(self):
        result = self.parse_generated_code('sum(1 for item in data if item > 100)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'count')

    def test_parse_any_predicate(self):
        result = self.parse_generated_code('any(item > 100 for item in data)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'any')

    def test_parse_all_predicate(self):
        result = self.parse_generated_code('all(item > 100 for item in data)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'all')

    def test_parse_loop_no_idx_predicate(self):
        result = self.parse_generated_code('for item in (item for item in data if item > 100):\n    pass')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'loop_no_idx')

    def test_parse_find_indices_predicate(self):
        result = self.parse_generated_code('[i for i, item in enumerate(data) if item > 100]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'find_indices')

    def test_parse_nonmatching_returns_none(self):
        result = self.parse_generated_code('print("hello")')
        self.assertIsNone(result)

    def test_parse_assignment_form(self):
        from list_visualizer_grammar import parse_generated_code_or_assignment
        ctx, prefix = parse_generated_code_or_assignment('result = [item for item in data if item > 100]')
        self.assertIsNotNone(ctx)
        self.assertEqual(prefix, 'result = ')
        self.assertEqual(ctx['action'], 'filter')

    def test_parse_join_whole_list(self):
        result = self.parse_generated_code("''.join(str(item) for item in data)")
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'join')
        self.assertEqual(result['source_expr'], 'data')

    def test_parse_join_assignment_form(self):
        from list_visualizer_grammar import parse_generated_code_or_assignment
        ctx, prefix = parse_generated_code_or_assignment("result = ''.join(str(item) for item in data)")
        self.assertIsNotNone(ctx)
        self.assertEqual(prefix, 'result = ')
        self.assertEqual(ctx['action'], 'join')


class TestChildNewCodeBecomesColumn(unittest.TestCase):
    """When a nested visualizer in a table cell produces NewCode, it becomes a column."""

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def _make_newcode_vis(self, commands_to_return):
        """Create a mock visualizer that returns the given commands from update()."""
        class NewCodeVis:
            def can_visualize(self, v): return isinstance(v, str)
            def get_fields(self, v): return None
            def init_model(self, v, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'handledKeys': []}
            def visualize(self, v, m, gv, eval_in_scope=None, max_width=None, max_height=None, small=False):
                return '<span snc-mouse-down="X">x</span>'
            def update(self, event, var_and_exp, model, value, gv=None, eval_in_scope=None):
                return (model, list(commands_to_return))
        return NewCodeVis()

    def _get_vis_for(self, str_vis):
        def get_vis(v):
            if isinstance(v, dict): return _mock_dict_vis
            if isinstance(v, str): return str_vis
            return _mock_int_vis
        return get_vis

    def test_child_newcode_tuple_becomes_column(self):
        nc_vis = self._make_newcode_vis([('result', "len(^['name'])")])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"  # see TestFocusTracking
        original_columns = list(model['columns'])
        event = make_child_mouse_event("0\x00^['name']", 'X')
        new_model, commands = update(event, ('x', 'x'), model, lst, get_vis)

        self.assertEqual(commands, [], "NewCode tuple should not propagate as a command")
        self.assertIn("len(^['name'])", new_model['columns'],
                       "NewCode expr should be added as a new column")

    def test_child_newcode_tuple_not_inserted_to_buffer(self):
        nc_vis = self._make_newcode_vis([('filtered', '[x for x in ^]')])
        get_vis = self._get_vis_for(nc_vis)

        lst = ['hello', 'world']
        model = init_model(lst, get_vis)
        model['focused_child'] = '0\x00^'  # see TestFocusTracking
        event = make_child_mouse_event('0\x00^', 'X')
        _, commands = update(event, ('x', 'x'), model, lst, get_vis)

        for cmd in commands:
            self.assertFalse(
                isinstance(cmd, tuple) and len(cmd) == 2,
                "No (suggest_var_name, expr) tuples should reach the command list")

    def test_child_copy_to_clipboard_passes_through(self):
        nc_vis = self._make_newcode_vis([CopyToClipboard(text='hello')])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00^['name']", 'X')
        _, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertEqual(commands[0].text, 'hello')

    def test_child_change_selected_text_passes_through(self):
        nc_vis = self._make_newcode_vis([ChangeSelectedText(expression='new_text')])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00^['name']", 'X')
        _, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)

    def test_child_receives_column_as_var_and_exp(self):
        """The child should receive (None, column_expr) as var_and_exp."""
        captured = {}
        class CapturingVis:
            def can_visualize(self, v): return isinstance(v, str)
            def get_fields(self, v): return None
            def init_model(self, v, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'handledKeys': []}
            def visualize(self, v, m, gv, eval_in_scope=None, max_width=None, max_height=None, small=False):
                return '<span snc-mouse-down="X">x</span>'
            def update(self, event, var_and_exp, model, value, gv=None, eval_in_scope=None):
                captured['var_and_exp'] = var_and_exp
                return (model, [])

        cap_vis = CapturingVis()
        get_vis = self._get_vis_for(cap_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00^['name']", 'X')
        update(event, ('x', 'x'), model, lst, get_vis)

        self.assertEqual(captured['var_and_exp'], (None, "^['name']"),
                         "Child should receive (None, column_expr) as var_and_exp")

    def test_mixed_commands_only_newcode_intercepted(self):
        """When child returns both NewCode and CopyToClipboard, only NewCode is intercepted."""
        nc_vis = self._make_newcode_vis([
            ('result', "^['name'].upper()"),
            CopyToClipboard(text='copied'),
        ])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00^['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00^['name']", 'X')
        new_model, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1, "Only CopyToClipboard should pass through")
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertIn("^['name'].upper()", new_model['columns'])


class TestColumnHeaderTooltips(unittest.TestCase):
    """The icon-only column header controls (drag handle, remove, add) must
    use the snc-tooltip system (data-tooltip) instead of the native title
    attribute, matching the string visualizer's tool toolbar pattern."""

    def test_remove_column_button_has_data_tooltip(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        m = re.search(
            r'<span snc-mouse-down="RemoveColumnClick[^"]*"([^>]*?)>',
            output,
        )
        self.assertIsNotNone(m, "RemoveColumnClick button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Remove column"', attrs)
        self.assertNotIn('title="Remove column"', attrs,
                         "Should use data-tooltip instead of native title")

    def test_drag_handle_has_data_tooltip(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        m = re.search(
            r'<span snc-mouse-down="ColumnDragStart[^"]*"([^>]*?)>',
            output,
        )
        self.assertIsNotNone(m, "ColumnDragStart handle not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Drag to reorder"', attrs)
        self.assertNotIn('title="Drag to reorder"', attrs,
                         "Should use data-tooltip instead of native title")

    def test_add_column_button_has_data_tooltip(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        m = re.search(
            r'<th([^>]*?)snc-mouse-down="AddColumnClick[^"]*"([^>]*?)>',
            output,
        )
        self.assertIsNotNone(m, "AddColumnClick (+) button not found")
        attrs = m.group(1) + ' ' + m.group(2)
        self.assertIn('data-tooltip="Add column"', attrs)


class TestSearchBoxTooltips(unittest.TestCase):
    """The first-match toggle in the list search box is icon-only and must
    carry a data-tooltip describing what the icon does."""

    def test_first_match_toggle_has_data_tooltip(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        m = re.search(
            r'<span class="search-button [^"]*"([^>]*)snc-mouse-down="FirstMatchToggle',
            output,
        )
        self.assertIsNotNone(m, "FirstMatchToggle button not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="First match only"', attrs)


_FINDALL_COL = "re.findall(r'[A-Z]{3}', (^), flags=re.M)"


class TestNestedSlotsConfig(unittest.TestCase):
    """The list config is nested: a list-producing column does not re-apply the
    type config to its cell sub-list (which would recurse forever); the sub-list
    uses the column's explicitly-nested config or a non-recursive default."""

    def _findall_key(self, row=0):
        return f"{row}\x00{_FINDALL_COL}"

    def test_list_of_str_with_list_column_does_not_recurse(self):
        slots = [{'expr': '^'}, {'expr': _FINDALL_COL}]
        with patch('list_visualizer.load_columns_from_dotfile', return_value=slots):
            # 'ABCdef' -> re.findall -> ['ABC'] -> ['ABC'] -> ... pre-fix recursion
            model = init_model(['ABCdef'], mock_get_visualizer)
        self.assertEqual(model['columns'], ['^', _FINDALL_COL])
        # The re.findall cell is a list[str]; with no nested config it must fall
        # back to the default single column, NOT re-read builtins.str's config.
        child = model['children'][self._findall_key()]
        self.assertEqual(child['columns'], ['^'])

    def test_explicit_nested_children_applies(self):
        slots = [
            {'expr': '^'},
            {'expr': _FINDALL_COL,
             'children': {'builtins.str': [{'expr': '^.lower()'}]}},
        ]
        with patch('list_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['ABCdef'], mock_get_visualizer)
        child = model['children'][self._findall_key()]
        self.assertEqual(child['columns'], ['^.lower()'])

    def test_root_model_stores_config_fields(self):
        slots = [{'expr': '^'}]
        with patch('list_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['x'], mock_get_visualizer)
        self.assertEqual(model['_config_root_type'], 'builtins.str')
        self.assertEqual(model['_config_root_dotfile'],
                         list_visualizer.COLUMN_DOTFILE_NAME)
        self.assertEqual(model['_config_path'], [])
        self.assertEqual(model['_slot_children'], {})

    def test_nested_child_carries_path_and_root(self):
        slots = [{'expr': _FINDALL_COL,
                  'children': {'builtins.str': [{'expr': '^'}]}}]
        with patch('list_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['ABCdef'], mock_get_visualizer)
        child = model['children'][self._findall_key()]
        self.assertEqual(child['_config_root_type'], 'builtins.str')
        self.assertEqual(child['_config_path'],
                         [(_FINDALL_COL, 'builtins.str')])

    def test_cyclic_list_is_depth_capped_not_recursion_error(self):
        a = []
        a.append(a)  # a == [a]; would recurse forever via auto-detected columns
        with patch('list_visualizer.load_columns_from_dotfile', return_value=None):
            model = init_model(a, mock_get_visualizer)  # must not RecursionError
        # Walk down the single nested child chain; a leaf must be marked too deep.
        m, depth, hit_cap = model, 0, False
        while m.get('children'):
            key = next(iter(m['children']))
            m = m['children'][key]
            depth += 1
            if m.get('_too_deep'):
                hit_cap = True
                break
            if depth > MAX_NEST_DEPTH + 2:
                break
        self.assertTrue(hit_cap, 'expected a depth-capped leaf model')
        self.assertLessEqual(depth, MAX_NEST_DEPTH + 1)


class TestNestedSlotsSave(unittest.TestCase):
    """Column edits persist via the path-scoped writer using the model's path."""

    def test_add_column_saves_with_path_scoped_signature(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        event = make_column_mouse_event(repr(ColumnSelect(name="^['x']")))
        with patch('list_visualizer.save_columns_to_dotfile') as mock_save:
            update(event, None, model, lst, mock_get_visualizer)
        mock_save.assert_called_once()
        args = mock_save.call_args.args
        # New signature: (root_type, path, exprs, [dotfile])
        self.assertEqual(args[0], 'builtins.dict')
        self.assertEqual(args[1], [])
        self.assertIn("^['x']", args[2])


if __name__ == '__main__':
    unittest.main()
