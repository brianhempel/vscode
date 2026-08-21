"""
Tests for table_visualizer.py - list composition with child visualizers.

Run:
    python3 -m pytest table_visualizer_tests.py -v
"""

import ast
import copy
import json
import math
import unittest
import html
import os
import re
import shutil
import tempfile

from visualizer_utils import (ChildEvent, wrap_drag_grab, MAX_NEST_DEPTH,
                              replace_dollars_in_py_exp, py_exp_attrs, PyExp,
                              with_pass_body, AddImports, CHILD_SOURCE_BINDER)
import table_visualizer


def exp_attr(*exprs):
    """The `snc-py-exps` attribute a handle offering these expressions carries,
    as it reads inside the tag it was written into."""
    return py_exp_attrs(list(exprs), draggable=False).strip()


def handles_in(html_str):
    """Every handle in *html_str* as the editor reads it back: one list of
    `{expr, imports?, label?}` entries per handle."""
    return [json.loads(html.unescape(attr))
            for attr in re.findall(r'snc-py-exps="([^"]*)"', html_str)]


def exps_in(html_str):
    """The same, kept to the expressions: one list per handle."""
    return [[entry['expr'] for entry in handle]
            for handle in handles_in(html_str)]



# Isolate the entire test module from the user's cwd so that stray
# .snc_table_columns.json files (or other dotfiles created by other tests)
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

    p_load = _mock.patch('table_visualizer.load_columns_from_dotfile',
                         return_value=None)
    p_save = _mock.patch('table_visualizer.save_columns_to_dotfile')
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
from table_visualizer import (
    can_visualize, init_model, visualize, update,
    AddColumnClick, ColumnInput, ColumnSelect, ColumnClick,
    RemoveColumnClick, ColumnDragStart, ColumnDragOver, ColumnDragEnd,
    ColumnKeyDown, ExpandToggle, COLUMN_DOTFILE_NAME, CELL_KEY_SEP, SUBCOL_SEP,
    CopyToClipboard, ChangeSelectedText,
    load_columns_from_dotfile, save_columns_to_dotfile,
    _get_column_suggestions, _get_all_possible_columns,
    Row, _rows, _row_at, _split_splat, _is_valid_python_expression,
    _table_child_value_getter, _leaf_columns, _column_groups,
    _col_add, _col_at, _col_rename_at, _col_remove_at,
    _leaf_values_expr, _menu_targets, _named_column, _col_subs,
    _promote_expr, _adopt_expr,
    _col_move, _col_subs,
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
        # Stands in for a third-party visualizer that self-wraps when small, to
        # check the parent hands down the expression and doesn't wrap children.
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
        return [f"$[{repr(k)}]" for k in value.keys()]
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
        return [f'$.{name}' for name in names]
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return f'<span>{html.escape(repr(value))}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class TableVisualizerAdapter:
    """Wraps the table_visualizer module to act like a visualizer object.

    Covers both of the types the engine claims -- list and dict -- so a test
    that opts dicts into the engine gets the real thing, not a mock of it."""
    def can_visualize(self, value):
        return table_visualizer.can_visualize(value)
    def get_fields(self, value):
        return table_visualizer.get_fields(value)
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None, **kwargs):
        return table_visualizer.init_model(value, get_visualizer, eval_in_scope=eval_in_scope, var_and_exp=var_and_exp, **kwargs)
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return table_visualizer.visualize(value, model, get_visualizer, eval_in_scope, max_width=max_width, max_height=max_height, small=small)
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return table_visualizer.update(event, var_and_exp, model, value, get_visualizer, eval_in_scope=eval_in_scope)


class MockCodeVisualizer:
    """A child that answers every event with a line of generated code, so tests
    can watch where the parent sends one."""
    def can_visualize(self, value):
        return True
    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return {'handledKeys': []}
    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
        return f'<span>{html.escape(repr(value))}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [('x', CHILD_SOURCE_BINDER)])


_mock_string_vis = MockStringVisualizer()
_mock_int_vis = MockIntVisualizer()
_mock_dict_vis = MockDictVisualizer()
_mock_obj_vis = MockObjectVisualizer()
_mock_code_vis = MockCodeVisualizer()
_mock_table_vis = TableVisualizerAdapter()
_mock_list_vis = _mock_table_vis  # legacy name, still used widely below


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


def mock_get_visualizer_dict_tables(value):
    """Opt-in variant of `mock_get_visualizer` that routes dicts to the table
    engine, the way the real runtime does now that the engine claims them.

    The default above deliberately keeps sending dicts to MockDictVisualizer.
    Flipping it would rewrite the expectations of a large fraction of the
    suite -- every list-of-dicts table has dict cells -- and drown out the
    signal from the tests that are actually about this behaviour. Tests that
    want a real dict child ask for it by using this."""
    if isinstance(value, (list, dict)):
        return _mock_table_vis
    if isinstance(value, str):
        return _mock_string_vis
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
        self.assertIn('0\x00$', model['children'])
        self.assertIn('1\x00$', model['children'])

    def test_child_models_come_from_child_visualizer(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        child_model = model['children']['0\x00$']
        self.assertEqual(child_model, _mock_string_vis.init_model("hello"))

    def test_int_child_model(self):
        lst = [42]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model['children']['0\x00$'])

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
        self.assertEqual(eval(html.unescape(matches[0])), '0\x00$')

    def test_multiple_items_have_different_keys(self):
        lst = ["a", "b"]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        matches = re.findall(r'snc-child-key="([^"]*)"', output)
        keys = {eval(html.unescape(m)) for m in matches}
        self.assertIn('0\x00$', keys)
        self.assertIn('1\x00$', keys)

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
        model['focused_child'] = '0\x00$'
        event = make_child_mouse_event('0\x00$', 'MouseDown(index=0)')
        new_model, commands = update(event, ('x', 'x'), model, lst, mock_get_visualizer)
        child_model = new_model['children']['0\x00$']
        self.assertIn('last_event', child_model)

    def test_child_event_preserves_other_children(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event('0\x00$', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn('1\x00$', new_model['children'])
        self.assertNotIn('last_event', new_model['children']['1\x00$'])

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
        model['focused_child'] = '0\x00$'  # see TestFocusTracking
        event = make_child_mouse_event('0\x00$', 'X')
        _, commands = update(event, None, model, lst, get_vis)
        self.assertIn('test_command', commands)

    def test_handled_keys_updated_after_child_event(self):
        lst = ["hello"]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event('0\x00$', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn('handledKeys', new_model)


class TestNestedComposition(unittest.TestCase):
    """Test list of lists works (nested composition)."""

    def test_nested_list_is_table_mode(self):
        lst = [[1, 2], [3, 4]]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ['$[0]', '$[1]'])
        self.assertIn('0\x00$[0]', model['children'])
        self.assertIn('0\x00$[1]', model['children'])
        self.assertIn('1\x00$[0]', model['children'])
        self.assertIn('1\x00$[1]', model['children'])


class TestGetFields(unittest.TestCase):
    """Test get_fields and eval_dollar_expr integration on table_visualizer."""

    def test_returns_string_indices(self):
        from table_visualizer import get_fields
        self.assertEqual(get_fields([10, 20, 30]), ['$[0]', '$[1]', '$[2]'])

    def test_empty_list(self):
        from table_visualizer import get_fields
        self.assertEqual(get_fields([]), [])

    def test_eval_dollar_expr_roundtrip(self):
        from table_visualizer import get_fields
        from visualizer_utils import eval_dollar_expr
        lst = [10, 20, 30]
        fields = get_fields(lst)
        self.assertEqual(eval_dollar_expr(fields[0], lst), 10)
        self.assertEqual(eval_dollar_expr(fields[2], lst), 30)


class TestRows(unittest.TestCase):
    """One description of what a row is, whatever container gave it up.

    Shaped for splat now so Landing 2 fills the fields in rather than
    reworking callers: every row is its own span of 1 until then."""

    def test_a_list_row_binds_the_item_and_its_index(self):
        rows = _rows(['a', 'b'])
        self.assertEqual([r.key for r in rows], ['0', '1'])
        self.assertEqual([r.index for r in rows], [0, 1])
        self.assertEqual([r.item for r in rows], ['a', 'b'])
        self.assertEqual([r.bindings for r in rows], [{'i': 0}, {'i': 1}])

    def test_a_dict_row_binds_the_pair_beside_the_key_and_value(self):
        rows = _rows({'a': 1, 'b': 2})
        self.assertEqual([r.key for r in rows], ['0', '1'])
        self.assertEqual([r.index for r in rows], [0, 1])
        # Bare $ for a dict is the (key, value) pair.
        self.assertEqual([r.item for r in rows], [('a', 1), ('b', 2)])
        self.assertEqual(rows[0].bindings, {'i': 0, 'k': 'a', 'v': 1})

    def test_row_index_is_the_root_row_number_for_both(self):
        # $i is the root row's number -- n in enumerate(d.items()) -- which for
        # a dict is also the key's position, forever. That is why there is no
        # separate $ki.
        self.assertEqual([r.index for r in _rows({'x': 9, 'y': 8})], [0, 1])

    def test_every_row_owns_its_own_span_until_splat(self):
        for container in (['a', 'b'], {'a': 1, 'b': 2}):
            with self.subTest(container=container):
                for r in _rows(container):
                    self.assertTrue(r.span_start)
                    self.assertEqual(r.span, 1)

    def test_empty_containers_give_no_rows(self):
        self.assertEqual(_rows([]), [])
        self.assertEqual(_rows({}), [])

    def test_row_key_is_a_string_not_an_int(self):
        # The format the tests pin is the one splat needs: under a splat two
        # rendered rows of one root row are "3.0" and "3.1", so an int key
        # would collide on the same leaf column.
        self.assertIsInstance(_rows(['a'])[0].key, str)
        self.assertIsInstance(_rows({'a': 1})[0].key, str)


class TestSplatSigil(unittest.TestCase):
    """A `*` prefix on a column expression, evocative of *my_list: the column's
    value is a list, and its items become rows.

    `*$` is a SyntaxError in eval mode -- as are `*x` and `*$.members` -- so it
    can never collide with a legitimate column expression. For the same reason
    the validators have to strip it before asking whether the rest parses."""

    def test_a_splat_column_validates(self):
        for col in ('*$', '*$v', '*$.members', "*$['items']"):
            with self.subTest(col=col):
                self.assertTrue(_is_valid_python_expression(col))

    def test_the_thing_being_splatted_still_has_to_parse(self):
        self.assertFalse(_is_valid_python_expression('*$ +'))
        self.assertFalse(_is_valid_python_expression('*'))

    def test_it_is_read_apart_into_the_star_and_the_expression(self):
        self.assertEqual(_split_splat('*$.members'), (True, '$.members'))
        self.assertEqual(_split_splat('  *$v  '), (True, '$v'))
        self.assertEqual(_split_splat('$.members'), (False, '$.members'))

    def test_a_multiplication_is_not_a_splat(self):
        # The star has to LEAD; `$ * 2` is arithmetic.
        self.assertEqual(_split_splat('$ * 2'), (False, '$ * 2'))


class TestSplatRows(unittest.TestCase):
    """A root row that splats a list occupies several rendered rows. The first
    carries span_start and draws the cells of every column that did NOT splat,
    with rowspan=span."""

    def test_a_splat_column_turns_one_root_row_into_several(self):
        lst = [{'name': 'A', 'members': [1, 2, 3]}]
        rows = _rows(lst, ["$['name']", "*$['members']"])
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.key for r in rows], ['0.0', '0.1', '0.2'])

    def test_only_the_first_row_of_a_group_owns_the_span(self):
        lst = [{'name': 'A', 'members': [1, 2, 3]}]
        rows = _rows(lst, ["$['name']", "*$['members']"])
        self.assertEqual([r.span_start for r in rows], [True, False, False])
        self.assertEqual([r.span for r in rows], [3, 3, 3])

    def test_every_row_of_a_group_shares_the_root_index(self):
        # $i is the ROOT row's number, so it rowspans like any other unsplatted
        # value. The flat rendered position gets no sigil.
        lst = [{'m': [1, 2]}, {'m': [3]}]
        rows = _rows(lst, ['*$["m"]'])
        self.assertEqual([r.index for r in rows], [0, 0, 1])

    def test_the_position_within_a_group_binds_to_j(self):
        lst = [{'m': [1, 2, 3]}]
        rows = _rows(lst, ['*$["m"]'])
        self.assertEqual([r.bindings['j'] for r in rows], [0, 1, 2])

    def test_the_splatted_element_is_reachable_from_the_row(self):
        lst = [{'m': [10, 20]}]
        rows = _rows(lst, ['*$["m"]'])
        self.assertEqual([r.splats['*$["m"]'] for r in rows], [10, 20])

    def test_two_splats_zip_and_pad(self):
        # Align by position, blank the short one; the group is as long as the
        # longest splat.
        lst = [{'a': [1, 2, 3], 'b': ['x']}]
        rows = _rows(lst, ['*$["a"]', '*$["b"]'])
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.splats['*$["a"]'] for r in rows], [1, 2, 3])
        self.assertEqual([r.splats['*$["b"]'] for r in rows], ['x', None, None])

    def test_an_empty_splat_still_leaves_the_root_row_one_row(self):
        # Otherwise a row would vanish from the table for having an empty list.
        lst = [{'m': []}, {'m': [1]}]
        rows = _rows(lst, ['*$["m"]'])
        self.assertEqual([r.index for r in rows], [0, 1])
        self.assertEqual([r.span for r in rows], [1, 1])

    def test_a_splat_of_something_that_is_not_a_list_is_one_row(self):
        lst = [{'m': 5}]
        rows = _rows(lst, ['*$["m"]'])
        self.assertEqual(len(rows), 1)

    def test_the_dict_of_lists_grouped_view(self):
        # The payoff the whole plan was aiming at, and it is not a dict feature:
        # the key cell spans its group precisely because $k did NOT splat.
        d = {'k1': ['a', 'b'], 'k2': ['c']}
        rows = _rows(d, ['$k', '*$v'])
        self.assertEqual([r.key for r in rows], ['0.0', '0.1', '1.0'])
        self.assertEqual([r.bindings['k'] for r in rows], ['k1', 'k1', 'k2'])
        self.assertEqual([r.splats['*$v'] for r in rows], ['a', 'b', 'c'])
        self.assertEqual([r.span_start for r in rows], [True, False, True])
        self.assertEqual([r.span for r in rows], [2, 2, 1])

    def test_no_splat_columns_is_exactly_what_it_was(self):
        lst = ['a', 'b']
        self.assertEqual(_rows(lst, ["$"]), _rows(lst))
        self.assertEqual([r.key for r in _rows(lst, ['$'])], ['0', '1'])


class TestSplatRendering(unittest.TestCase):
    """What the mockup asked for: the key cell spans its group -- precisely
    because $k did NOT splat, not because it is a key."""

    @staticmethod
    def render(value, columns, gv=None):
        gv = gv or mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=('d', 'd'))
        model['columns'] = list(columns)
        return visualize(value, model, gv, None)

    @staticmethod
    def cells(html_out):
        return [re.sub(r'<[^>]+>', '', c)
                for c in re.findall(r'<td[^>]*>(.*?)</td>', html_out, re.S)]

    def test_a_splat_column_draws_one_cell_per_element(self):
        html_out = self.render({'k1': ['a', 'b']}, ['$k', '*$v'])
        self.assertIn('a', html_out)
        self.assertIn('b', html_out)

    def test_the_unsplatted_column_rowspans_its_group(self):
        html_out = self.render({'k1': ['a', 'b', 'c']}, ['$k', '*$v'])
        self.assertIn('rowspan="3"', html_out)

    def test_a_group_of_one_needs_no_rowspan(self):
        html_out = self.render({'k1': ['a']}, ['$k', '*$v'])
        self.assertNotIn('rowspan', html_out)

    def test_the_key_cell_itself_spans_the_group(self):
        # Drawn once AND spanning: without the rowspan the cell occupies the
        # first row only and every row under it shifts left.
        html_out = self.render({'k1': ['a', 'b', 'c']}, ['$k', '*$v'])
        # Matched on the cell's TEXT: 'k1' also appears in the splat cells'
        # drag expressions, d['k1'][j].
        key_cells = [t for t, c in re.findall(r'<td([^>]*)>(.*?)</td>',
                                              html_out, re.S)
                     if re.sub(r'<[^>]+>', '', c).strip() == 'k1']
        self.assertEqual(len(key_cells), 1)
        self.assertIn('rowspan="3"', key_cells[0])

    def test_the_splat_cells_do_not_span(self):
        html_out = self.render({'k1': ['a', 'b']}, ['$k', '*$v'])
        splat_cells = [t for t, c in re.findall(r'<td([^>]*)>(.*?)</td>',
                                                html_out, re.S)
                       if re.sub(r'<[^>]+>', '', c).strip() in ('a', 'b')]
        self.assertEqual(len(splat_cells), 2)
        for t in splat_cells:
            self.assertNotIn('rowspan', t)

    def test_the_key_is_drawn_once_not_once_per_element(self):
        html_out = self.render({'k1': ['a', 'b', 'c']}, ['$k', '*$v'])
        self.assertEqual(len([c for c in self.cells(html_out) if 'k1' in c]), 1)

    def test_the_row_index_rowspans_too(self):
        # It shows row.index, which is a root-row value like any other.
        html_out = self.render({'k1': ['a', 'b']}, ['$k', '*$v'])
        rows = [r for r in re.findall(r'<tr[^>]*>.*?</tr>', html_out, re.S)
                if 'col-header' not in r]
        self.assertEqual(len(rows), 2)
        self.assertIn('rowspan="2"', rows[0])
        self.assertNotIn('row-index', rows[1])

    def test_a_list_of_lists_flattens_into_rows(self):
        html_out = self.render([[1, 2], [3]], ['*$'], mock_get_visualizer)
        rows = [r for r in re.findall(r'<tr[^>]*>.*?</tr>', html_out, re.S)
                if 'col-header' not in r]
        self.assertEqual(len(rows), 3)

    def test_a_splat_cell_hands_over_the_element_not_the_column(self):
        html_out = self.render({'k1': ['a', 'b']}, ['$k', '*$v'])
        self.assertIn("d[&#x27;k1&#x27;][1]", html_out)
        self.assertNotIn('*d[', html_out)

    def test_columns_without_a_splat_render_exactly_as_before(self):
        d = {'a': 1, 'b': 2}
        gv = mock_get_visualizer_dict_tables
        model = init_model(d, gv, var_and_exp=('d', 'd'))
        plain = visualize(d, model, gv, None)
        self.assertNotIn('rowspan', plain)


class TestColumnsDict(unittest.TestCase):
    """`columns` is an ordered map of column expression -> that column's config.

    One structure rather than a list beside a sibling map, duplicates
    impossible by construction, and order is insertion order -- which JSON
    round-trips. A column with nothing configured is `{}`; only a splat with
    sub-columns pays for the nesting."""

    def sample(self):
        return {'$k': {}, '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}

    def test_the_common_case_is_an_empty_config(self):
        model = init_model({'a': 1, 'b': 2}, mock_get_visualizer_dict_tables)
        self.assertEqual(model['columns'], {'$k': {}, '$v': {}})

    def test_iteration_gives_the_columns_in_order(self):
        self.assertEqual(list(self.sample()), ['$k', '*$v'])

    def test_a_column_cannot_be_added_twice(self):
        cols = {'$a': {}}
        _col_add(cols, '$a')
        self.assertEqual(list(cols), ['$a'])
        _col_add(cols, '$b')
        self.assertEqual(list(cols), ['$a', '$b'])

    def test_positional_access(self):
        cols = self.sample()
        self.assertEqual(_col_at(cols, 0), '$k')
        self.assertEqual(_col_at(cols, 1), '*$v')
        self.assertIsNone(_col_at(cols, 2))
        self.assertIsNone(_col_at(cols, -1))

    def test_renaming_keeps_the_position_and_the_config(self):
        cols = self.sample()
        _col_rename_at(cols, 1, '*$w')
        self.assertEqual(list(cols), ['$k', '*$w'])
        self.assertEqual(list(cols['*$w']['cols']), ["$['who']", "$['age']"])

    def test_renaming_onto_an_existing_name_is_refused(self):
        cols = {'$a': {}, '$b': {}}
        self.assertFalse(_col_rename_at(cols, 1, '$a'))
        self.assertEqual(list(cols), ['$a', '$b'])

    def test_removing_by_position(self):
        cols = self.sample()
        self.assertEqual(_col_remove_at(cols, 0), '$k')
        self.assertEqual(list(cols), ['*$v'])

    def test_moving_a_column_preserves_every_config(self):
        cols = self.sample()
        _col_move(cols, 1, 0)
        self.assertEqual(list(cols), ['*$v', '$k'])
        self.assertEqual(list(cols['*$v']['cols']), ["$['who']", "$['age']"])

    def test_sub_columns_are_read_off_the_column(self):
        self.assertEqual(list(_col_subs(self.sample(), '*$v')),
                         ["$['who']", "$['age']"])
        self.assertEqual(_col_subs(self.sample(), '$k'), {})

    def test_it_round_trips_through_json_in_order(self):
        import json
        self.assertEqual(list(json.loads(json.dumps(self.sample()))),
                         ['$k', '*$v'])


class TestLeafColumns(unittest.TestCase):
    """Store nested, render flat. `columns` plus the sub-column map expand into
    one list of leaves, and every per-column feature works on the leaves."""

    def test_a_table_with_no_splat_is_its_own_leaves(self):
        leaves = _leaf_columns({'$.a': {}, '$.b': {}})
        self.assertEqual([l.expr for l in leaves], ['$.a', '$.b'])
        self.assertEqual([l.splat for l in leaves], [None, None])

    def test_a_splat_without_sub_columns_is_one_leaf(self):
        leaves = _leaf_columns({'$k': {}, '*$v': {}})
        self.assertEqual([l.expr for l in leaves], ['$k', '*$v'])
        self.assertEqual([l.splat for l in leaves], [None, '*$v'])
        # The whole element is what the cell shows.
        self.assertEqual(leaves[1].sub, '$')

    def test_a_splat_expands_into_one_leaf_per_sub_column(self):
        leaves = _leaf_columns({'$.name': {}, '*$.members': {
            'cols': {'$.who': {}, '$.age': {}}}})
        self.assertEqual([l.sub for l in leaves], [None, '$.who', '$.age'])
        self.assertEqual([l.splat for l in leaves],
                         [None, '*$.members', '*$.members'])

    def test_leaf_identities_are_unique_across_two_splats(self):
        # Two splats can carry the same sub-column; the identity must still
        # tell their cells apart, or one column's children overwrite the other's.
        leaves = _leaf_columns({'*$.a': {'cols': {'$.x': {}}},
                                '*$.b': {'cols': {'$.x': {}}}})
        self.assertEqual(len({l.expr for l in leaves}), 2)

    def test_the_header_path_is_what_the_two_rows_show(self):
        leaves = _leaf_columns({'$.name': {}, '*$.members': {
            'cols': {'$.who': {}, '$.age': {}}}})
        self.assertEqual([l.header for l in leaves],
                         [('$.name',), ('*$.members', '$.who'),
                          ('*$.members', '$.age')])

    def test_the_splat_group_knows_how_wide_it_is(self):
        groups = _column_groups({'$.name': {}, '*$.members': {
            'cols': {'$.who': {}, '$.age': {}}}})
        self.assertEqual([(g.col, g.width) for g in groups],
                         [('$.name', 1), ('*$.members', 2)])


class TestMenuTargets(unittest.TestCase):
    """What a column event's index names. Leaves first, so a table with no
    sub-columns has exactly the index space it always had; then one entry per
    splat that carries sub-columns, which is what its own group header points
    at -- the splat itself is not a leaf, but it can still be renamed and
    removed."""

    def test_without_sub_columns_the_targets_are_the_columns(self):
        cols = {"$['a']": {}, "$['b']": {}}
        self.assertEqual(_menu_targets(cols), ["$['a']", "$['b']"])

    def test_a_splat_with_no_sub_columns_is_its_own_target(self):
        self.assertEqual(_menu_targets({'$k': {}, '*$v': {}}), ['$k', '*$v'])

    def test_a_split_splat_contributes_its_leaves_then_itself(self):
        cols = {'$k': {}, '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}
        targets = _menu_targets(cols)
        self.assertEqual(targets[0], '$k')
        self.assertEqual(targets[1], "*$v\x01$['who']")
        self.assertEqual(targets[2], "*$v\x01$['age']")
        self.assertEqual(targets[3], '*$v')

    def test_named_column_answers_for_a_column_that_is_there(self):
        # An event names its column; what the table has to say is whether it
        # still has one by that name -- a splat and its sub-columns alike.
        model = {'columns': {'$k': {}, '*$v': {'cols': {"$['x']": {}}}}}
        for target in ('$k', "*$v\x01$['x']", '*$v'):
            self.assertEqual(_named_column(model, target), target)

    def test_a_column_that_is_gone_answers_nothing(self):
        # Where a stale POSITION would have landed on whoever took its place.
        model = {'columns': {'$k': {}, '*$v': {'cols': {"$['x']": {}}}}}
        self.assertIsNone(_named_column(model, "$['was here']"))
        self.assertIsNone(_named_column(model, None))


class TestSubColumnMenuEvents(unittest.TestCase):
    """A sub-column is a column: it has a menu, and removing or renaming it
    changes its splat's `cols` rather than the top-level list."""

    def model(self):
        d = {'t1': [{'who': 'ann', 'age': 30}]}
        m = init_model(d, mock_get_visualizer_dict_tables,
                       var_and_exp=('d', 'd'))
        m['columns'] = {'$k': {},
                        '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}
        return d, m

    def test_removing_a_sub_column_leaves_the_splat_standing(self):
        d, model = self.model()
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, 1))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, d, mock_get_visualizer_dict_tables)
        self.assertEqual(list(new_model['columns']), ['$k', '*$v'])
        self.assertEqual(list(_col_subs(new_model['columns'], '*$v')),
                         ["$['age']"])

    def test_removing_the_splat_takes_its_sub_columns_with_it(self):
        d, model = self.model()
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, 3))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, d, mock_get_visualizer_dict_tables)
        self.assertEqual(list(new_model['columns']), ['$k'])

    def test_renaming_a_sub_column_keeps_it_under_its_splat(self):
        d, model = self.model()
        model['editing_column'] = col_at(model, 1)
        model['column_input_value'] = "$['name']"
        event = make_column_key_event('Enter')
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, d, mock_get_visualizer_dict_tables)
        self.assertEqual(list(_col_subs(new_model['columns'], '*$v')),
                         ["$['name']", "$['age']"])

    def test_a_sub_column_search_is_keyed_on_the_leaf(self):
        d, model = self.model()
        leaf = _leaf_columns(model['columns'])[1]
        _set_column_search(model, leaf.expr, op='>', text='2', compose='and')
        self.assertTrue(_column_search_active(model, leaf.expr))
        self.assertFalse(_column_search_active(model, '$k'))

    def test_the_sub_header_carries_a_menu_trigger(self):
        d, model = self.model()
        html_out = visualize(d, model, mock_get_visualizer_dict_tables, None)
        # The sub-column names itself, control character and all, the way
        # every id that carries an expression is written.
        self.assertIn(html.escape(repr(menu_id(model, index=1))), html_out)


class TestPromoteAndAdopt(unittest.TestCase):
    """Dragging a column across parents. `$` means the element inside a splat
    and the row outside it, so the expression is rewritten as it moves."""

    def test_promote_reads_the_sub_across_the_splats_list(self):
        # Out of the splat the column is read per ROOT ROW, and the root row
        # has a list where the sub had one element.
        self.assertEqual(_promote_expr("$['who']", '*$v'),
                         "[item2['who'] for item2 in $v]")

    def test_promoting_the_whole_element_is_just_the_list(self):
        self.assertEqual(_promote_expr('$', '*$v'), '[item2 for item2 in $v]')

    def test_promote_brings_the_root_row_back_a_level(self):
        # $$ inside a splat is the root row; outside, that is $.
        self.assertEqual(_promote_expr("$$['n']", '*$v'),
                         "[$['n'] for item2 in $v]")

    def test_adopt_deepens_every_run_by_one(self):
        # Inside the splat $ is the element, so what was the row is now $$.
        self.assertEqual(_adopt_expr("$['x']"), "$$['x']")
        self.assertEqual(_adopt_expr('len($) + $$'), 'len($$) + $$$')

    def test_adopt_refuses_a_column_naming_a_sigil(self):
        # Landing 1's known gap: suffixes bind at depth 1 only, so $$k names
        # nothing. Refused rather than deepened into silence.
        for col in ('$k', '$v', '$i', '$v > 3'):
            with self.subTest(col=col):
                self.assertIsNone(_adopt_expr(col))

    def test_adopt_leaves_string_content_alone(self):
        self.assertEqual(_adopt_expr('"$"'), '"$"')


class TestCrossParentDrag(unittest.TestCase):
    """The drag itself, end to end."""

    def model(self):
        d = {'t1': [{'who': 'ann', 'age': 30}]}
        m = init_model(d, mock_get_visualizer_dict_tables,
                       var_and_exp=('d', 'd'))
        m['columns'] = {'$k': {},
                        '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}
        return d, m

    def drag(self, d, model, frm, to):
        model['column_drag_from'] = col_at(model, frm)
        model['column_drag_over'] = col_at(model, to)
        event = make_column_mouse_event(repr(ColumnDragEnd(col=col_at(model, to))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, d,
                                  mock_get_visualizer_dict_tables)
        return new_model

    def test_reordering_within_a_splat_stays_inside_it(self):
        d, model = self.model()
        # targets: 0 $k, 1 who, 2 age, 3 *$v
        new_model = self.drag(d, model, 2, 1)
        self.assertEqual(list(_col_subs(new_model['columns'], '*$v')),
                         ["$['age']", "$['who']"])
        self.assertEqual(list(new_model['columns']), ['$k', '*$v'])

    def test_dragging_a_sub_column_out_promotes_it(self):
        d, model = self.model()
        new_model = self.drag(d, model, 1, 0)
        self.assertIn("[item2['who'] for item2 in $v]", new_model['columns'])
        # and it is gone from the splat
        self.assertEqual(list(_col_subs(new_model['columns'], '*$v')),
                         ["$['age']"])

    def test_dragging_a_top_level_column_in_adopts_it(self):
        d = {'t1': [{'who': 'ann'}]}
        m = init_model(d, mock_get_visualizer_dict_tables, var_and_exp=('d', 'd'))
        m['columns'] = {"$['meta']": {}, '*$v': {'cols': {"$['who']": {}}}}
        new_model = self.drag(d, m, 0, 1)
        self.assertNotIn("$['meta']", new_model['columns'])
        self.assertIn("$$['meta']", _col_subs(new_model['columns'], '*$v'))

    def test_adopting_a_sigil_column_is_refused(self):
        d, model = self.model()
        before = dict(model['columns'])
        new_model = self.drag(d, model, 0, 1)   # $k onto a sub-column
        self.assertEqual(list(new_model['columns']), list(before))
        self.assertEqual(list(_col_subs(new_model['columns'], '*$v')),
                         ["$['who']", "$['age']"])

    def test_the_promoted_expression_actually_evaluates(self):
        d = {'t1': [{'who': 'ann'}, {'who': 'bo'}]}
        expr = _promote_expr("$['who']", '*$v')
        row = _rows(d, {'$k': {}, '*$v': {}})[0]
        from visualizer_utils import eval_dollar_expr
        self.assertEqual(eval_dollar_expr(expr, row.item, bindings=row.bindings),
                         ['ann', 'bo'])


class TestLeafDerivedExpressions(unittest.TestCase):
    """A leaf under a splat has a whole-column expression of its own -- the
    flattened comprehension -- which is what the header hands to a drag and
    what the tally and the aggregations read."""

    @staticmethod
    def leaf(columns, n):
        return _leaf_columns(columns)[n]

    def test_a_plain_column_is_unchanged(self):
        leaf = self.leaf({'$k': {}}, 0)
        self.assertEqual(_leaf_values_expr(leaf, 'd', _binds_for({'a': 1})),
                         'list(d)')

    def test_a_splat_with_no_sub_columns_flattens_the_lists(self):
        leaf = self.leaf({'*$v': {}}, 0)
        self.assertEqual(_leaf_values_expr(leaf, 'd', _binds_for({'a': 1})),
                         '[item2 for v in d.values() for item2 in v]')

    def test_a_sub_column_reads_off_each_element(self):
        cols = {'*$v': {'cols': {"$['who']": {}}}}
        self.assertEqual(
            _leaf_values_expr(self.leaf(cols, 0), 'd', _binds_for({'a': 1})),
            "[item2['who'] for v in d.values() for item2 in v]")

    def test_a_list_source_binds_the_row(self):
        cols = {"*$['members']": {'cols': {"$['who']": {}}}}
        self.assertEqual(_leaf_values_expr(self.leaf(cols, 0), 'teams'),
                         "[item2['who'] for item in teams for item2 in item['members']]")

    def test_the_derived_expression_actually_runs(self):
        d = {'t1': [{'who': 'ann'}, {'who': 'bo'}], 't2': [{'who': 'cy'}]}
        cols = {'*$v': {'cols': {"$['who']": {}}}}
        code = _leaf_values_expr(self.leaf(cols, 0), 'd', _binds_for(d))
        self.assertEqual(eval(code, {'d': d}), ['ann', 'bo', 'cy'])

    def test_column_values_reads_a_leaf_flat(self):
        d = {'t1': [{'who': 'ann'}, {'who': 'bo'}], 't2': [{'who': 'cy'}]}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['columns'] = {'$k': {}, '*$v': {'cols': {"$['who']": {}}}}
        leaf = _leaf_columns(model['columns'])[1]
        self.assertEqual(_column_values(leaf.expr, d, model), ['ann', 'bo', 'cy'])

    def test_a_tally_over_a_sub_column_counts_the_elements(self):
        d = {'t1': [{'x': 1}, {'x': 2}], 't2': [{'x': 1}]}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['columns'] = {'*$v': {'cols': {"$['x']": {}}}}
        leaf = _leaf_columns(model['columns'])[0]
        self.assertEqual(_tally(_column_values(leaf.expr, d, model)), {1: 2, 2: 1})


class TestSplatSubColumnRendering(unittest.TestCase):
    """A splat's sub-columns each get their own cell, read off the splatted
    element -- and a second header row under the splat's own header."""

    @staticmethod
    def render(value, columns, slot_cols):
        gv = mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=('d', 'd'))
        model['columns'] = {c: ({'cols': {s: {} for s in slot_cols[c]}}
                                if c in slot_cols else {})
                            for c in columns}
        return visualize(value, model, gv, None)

    def value(self):
        return {'t1': [{'who': 'ann', 'age': 30},
                       {'who': 'bo', 'age': 25}]}

    def test_each_sub_column_gets_its_own_cell(self):
        html_out = self.render(self.value(), ['$k', '*$v'],
                               {'*$v': ["$['who']", "$['age']"]})
        for text in ('ann', '30', 'bo', '25'):
            with self.subTest(text=text):
                self.assertIn(text, html_out)

    def test_the_splat_header_spans_its_sub_columns(self):
        html_out = self.render(self.value(), ['$k', '*$v'],
                               {'*$v': ["$['who']", "$['age']"]})
        self.assertIn('colspan="2"', html_out)

    def test_the_key_still_spans_the_group(self):
        html_out = self.render(self.value(), ['$k', '*$v'],
                               {'*$v': ["$['who']", "$['age']"]})
        self.assertIn('rowspan="2"', html_out)

    def test_a_header_reads_as_the_expression_the_user_wrote(self):
        # No abbreviating away the dollar: the header shows the expression as
        # written, which is also what double-clicking it puts in the box.
        html_out = self.render(self.value(), ['$k', '*$v'],
                               {'*$v': ["$['who']", "$['age']"]})
        for text in ('>$k<', '>*$v<', '>' + html.escape("$['who']")):
            with self.subTest(text=text):
                self.assertIn(text, html_out)

    def test_a_sub_header_hands_over_its_flattened_column(self):
        # Dragging a sub-column header gives the whole column, flattened
        # across every group -- the same list the tally counts.
        html_out = self.render(self.value(), ['$k', '*$v'],
                               {'*$v': ["$['who']", "$['age']"]})
        self.assertIn("for item2 in v]", html_out)
        self.assertIn("item2[&#x27;who&#x27;]", html_out)

    def test_a_table_without_sub_columns_has_one_header_row(self):
        d = {'a': 1}
        gv = mock_get_visualizer_dict_tables
        model = init_model(d, gv, var_and_exp=('d', 'd'))
        html_out = visualize(d, model, gv, None)
        self.assertNotIn('colspan', html_out)


class TestHeaderRowGroup(unittest.TestCase):
    """Every header row lives in one <thead>, the way the aggregations live in
    one <tfoot>: a row group can stick as a block, so a sub-column header pins
    under the header above it without anything having to measure its height."""

    @staticmethod
    def render(value, columns=None, subcols=()):
        gv = mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=('d', 'd'))
        if columns is not None:
            model['columns'] = {c: ({'cols': {s: {} for s in subcols}}
                                    if c == '*$v' and subcols else {})
                                for c in columns}
        return visualize(value, model, gv, None)

    @staticmethod
    def head_of(html_out):
        return html_out[html_out.index('<thead'):html_out.index('</thead>')]

    def test_the_header_rows_are_a_row_group(self):
        out = self.render({'a': 1})
        self.assertIn('<thead', out)
        self.assertIn('</thead>', out)

    def test_the_body_rows_are_outside_the_head(self):
        out = self.render({'a': 1})
        self.assertLess(out.index('</thead>'), out.index('<td'))

    def test_a_sub_column_header_is_in_the_same_group(self):
        # The whole point: the second header row has to stick along with the
        # first, so it has to be in the group that sticks.
        out = self.render({'t1': [{'who': 'ann', 'age': 30}]},
                          ['$k', '*$v'], ["$['who']", "$['age']"])
        self.assertIn('col-subheader', self.head_of(out))

    def test_the_add_column_button_is_in_the_head(self):
        # It sits in the top header row, so it pins with it.
        out = self.render({'a': 1})
        self.assertIn('col-add', self.head_of(out))


class TestRowIndexHeader(unittest.TestCase):
    """The row-index column heads itself with the sigil that names it: a column
    expression asking about the same number writes `$i`, so the column of
    numbers says `$i` rather than nothing at all."""

    @staticmethod
    def render(value, columns=None, subcols=(), small=False):
        gv = mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=('d', 'd'))
        if columns is not None:
            model['columns'] = {c: ({'cols': {s: {} for s in subcols}}
                                    if c == '*$v' and subcols else {})
                                for c in columns}
        return visualize(value, model, gv, None, small=small)

    @staticmethod
    def index_header(html_out):
        head = html_out[html_out.index('<thead'):html_out.index('</thead>')]
        # The first cell of the first header row is the one over the indices.
        return head[head.index('<th'):head.index('</th>') + len('</th>')]

    def test_the_index_column_is_headed_by_the_sigil(self):
        self.assertIn('$i', self.index_header(self.render([1, 2, 3])))

    def test_the_header_is_marked_as_the_index_column(self):
        # Dimming is CSS's half of this; the class is what it hangs on. Its own
        # class rather than the cells' `row-index`, since a header cell is
        # weighted and aligned as a header, not as one of the numbers.
        self.assertIn('row-index-header',
                      self.index_header(self.render([1, 2, 3])))

    def test_a_dict_is_headed_the_same_way(self):
        # `$i` is bound over a dict's entries too, so the column that shows it
        # says so there as well.
        self.assertIn('$i', self.index_header(self.render({'a': 1})))

    def test_an_empty_container_still_says_it(self):
        # The header is about the scope, not about the rows, and a table with
        # no rows is exactly where a reader needs telling what a column means.
        self.assertIn('$i', self.index_header(self.render([])))

    def test_a_small_table_says_it_too(self):
        self.assertIn('$i', self.index_header(self.render([1, 2, 3],
                                                          small=True)))

    def test_it_still_reaches_down_past_the_sub_column_row(self):
        # The cell spans every header row, so the sub-column row doesn't slide
        # a column to the left underneath it.
        out = self.render({'t1': [{'who': 'ann', 'age': 30}]},
                          ['$k', '*$v'], ["$['who']", "$['age']"])
        self.assertIn('rowspan="2"', self.index_header(out))

    def test_it_says_what_the_number_is(self):
        # The same phrase the code boxes' legends use for `$i`, off the same
        # declaration -- a reader who hovers here and hovers there is told one
        # thing, not two.
        self.assertIn('the row number', self.index_header(self.render([1, 2])))

    def test_a_dict_counts_entries(self):
        self.assertIn('the entry number',
                      self.index_header(self.render({'a': 1})))


class TestEditingAHeaderKeepsItsSpans(unittest.TestCase):
    """Double-clicking a header swaps the cell for an input box -- but the cell
    still covers exactly what it covered, or every column to its right shifts."""

    @staticmethod
    def render(value, columns, subcols, editing):
        gv = mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=('d', 'd'))
        model['columns'] = {c: ({'cols': {s: {} for s in subcols}}
                                if c == '*$v' else {})
                            for c in columns}
        model['editing_column'] = editing
        return visualize(value, model, gv, None)

    @staticmethod
    def input_cell(html_out):
        """The <th> open tag holding the box, spans and all."""
        at = html_out.index('col-input')
        start = html_out.rindex('<th', 0, at)
        return html_out[start:html_out.index('>', start) + 1]

    def value(self):
        return {'t1': [{'who': 'ann', 'age': 30},
                       {'who': 'bo', 'age': 25}]}

    def test_editing_a_column_beside_sub_columns_keeps_its_rowspan(self):
        # `$k` spans down past the sub-column row; an unspanned box would let
        # the first sub-column header slide underneath it.
        out = self.render(self.value(), ['$k', '*$v'],
                          ["$['who']", "$['age']"], '$k')
        self.assertIn('rowspan="2"', self.input_cell(out))

    def test_editing_a_splat_keeps_its_colspan(self):
        # The splat's header covers its sub-columns; narrowed to one cell, the
        # + button and everything right of it walk left.
        out = self.render(self.value(), ['$k', '*$v'],
                          ["$['who']", "$['age']"], '*$v')
        self.assertIn('colspan="2"', self.input_cell(out))

    def test_editing_a_sub_column_needs_no_span(self):
        sub = f'*$v{SUBCOL_SEP}' + "$['who']"
        out = self.render(self.value(), ['$k', '*$v'],
                          ["$['who']", "$['age']"], sub)
        cell = self.input_cell(out)
        self.assertNotIn('rowspan', cell)
        self.assertNotIn('colspan', cell)

    def test_editing_a_column_in_a_flat_table_needs_no_span(self):
        d = {'a': 1, 'b': 2}
        gv = mock_get_visualizer_dict_tables
        model = init_model(d, gv, var_and_exp=('d', 'd'))
        model['editing_column'] = col_at(model)
        out = visualize(d, model, gv, None)
        cell = self.input_cell(out)
        self.assertNotIn('rowspan', cell)
        self.assertNotIn('colspan', cell)


class TestSplatCellLookup(unittest.TestCase):
    """A cell key under splat is "3.1", so the row is found by the key rather
    than by int() -- which raises on it."""

    @staticmethod
    def splat_model(d):
        gv = mock_get_visualizer_dict_tables
        model = init_model(d, gv, var_and_exp=('d', 'd'))
        model['columns'] = ['$k', '*$v']
        return model

    def test_a_splat_cell_value_is_the_element(self):
        d = {'k1': ['a', 'b']}
        model = self.splat_model(d)
        self.assertEqual(
            _table_child_value_getter(f'0.1{CELL_KEY_SEP}*$v', d, model), 'b')

    def test_the_unsplatted_cell_of_a_group_is_the_root_value(self):
        d = {'k1': ['a', 'b']}
        model = self.splat_model(d)
        self.assertEqual(
            _table_child_value_getter(f'0.0{CELL_KEY_SEP}$k', d, model), 'k1')

    def test_a_root_key_still_works_without_a_dot(self):
        lst = [10, 20]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('d', 'd'))
        self.assertEqual(
            _table_child_value_getter(f'1{CELL_KEY_SEP}$', lst, model), 20)


class TestRowAt(unittest.TestCase):
    """One row without building the rest -- what the per-cell and sampling
    paths need, and the reason _rows must not be the only way in."""

    def test_it_agrees_with_rows_on_a_list(self):
        lst = ['a', 'b', 'c']
        for i in range(len(lst)):
            with self.subTest(i=i):
                self.assertEqual(_row_at(lst, i), _rows(lst)[i])

    def test_it_agrees_with_rows_on_a_dict(self):
        d = {'a': 1, 'b': 2, 'c': 3}
        for i in range(len(d)):
            with self.subTest(i=i):
                self.assertEqual(_row_at(d, i), _rows(d)[i])

    def test_it_reaches_a_dict_row_by_position_not_by_key(self):
        # d[1] would be a key lookup; the second row is what's wanted.
        d = {'a': 1, 'b': 2}
        self.assertEqual(_row_at(d, 1).item, ('b', 2))

    def test_an_integer_keyed_dict_still_indexes_by_position(self):
        # The case where a key lookup would silently succeed with the wrong row.
        d = {10: 'x', 11: 'y'}
        self.assertEqual(_row_at(d, 0).item, (10, 'x'))
        self.assertEqual(_row_at(d, 1).item, (11, 'y'))


class TestCanVisualizeClaimsDicts(unittest.TestCase):
    """The engine claims dicts as well as lists, so dict_visualizer.py can go."""

    def test_claims_lists(self):
        self.assertTrue(can_visualize([1, 2, 3]))
        self.assertTrue(can_visualize([]))

    def test_claims_dicts(self):
        self.assertTrue(can_visualize({'a': 1}))
        self.assertTrue(can_visualize({}))

    def test_declines_everything_else(self):
        for value in ('hi', 3, 3.5, None, (1, 2), {1, 2}):
            with self.subTest(value=value):
                self.assertFalse(can_visualize(value))


class TestDictGetFields(unittest.TestCase):
    """Addressing a dict from *outside* -- when a dict is a cell in another
    table. Folded in from dict_visualizer_tests.py, which retires with this.
    Unrelated to the $k/$v column sigils, which address it from inside."""

    def test_string_keys(self):
        from table_visualizer import get_fields
        self.assertEqual(get_fields({'name': 'Alice', 'age': 30}),
                         ["$['name']", "$['age']"])

    def test_empty_dict(self):
        from table_visualizer import get_fields
        self.assertEqual(get_fields({}), [])

    def test_int_keys(self):
        from table_visualizer import get_fields
        self.assertEqual(get_fields({1: 'a', 2: 'b'}), ['$[1]', '$[2]'])

    def test_string_key_roundtrip(self):
        from table_visualizer import get_fields
        from visualizer_utils import eval_dollar_expr
        d = {'name': 'Alice', 'age': 30}
        fields = get_fields(d)
        self.assertEqual(eval_dollar_expr(fields[0], d), 'Alice')
        self.assertEqual(eval_dollar_expr(fields[1], d), 30)

    def test_int_key_roundtrip(self):
        from table_visualizer import get_fields
        from visualizer_utils import eval_dollar_expr
        d = {1: 'a', 2: 'b'}
        fields = get_fields(d)
        self.assertEqual(eval_dollar_expr(fields[0], d), 'a')
        self.assertEqual(eval_dollar_expr(fields[1], d), 'b')

    def test_tuple_key_roundtrip(self):
        from table_visualizer import get_fields
        from visualizer_utils import eval_dollar_expr
        d = {(1, 2): 'pair'}
        fields = get_fields(d)
        self.assertEqual(eval_dollar_expr(fields[0], d), 'pair')


class TestDictCellsBecomeTables(unittest.TestCase):
    """Pins the behaviour change: a dict cell inside a list is a nested table
    now, not a compact {a: 1} span -- the same way a list cell already is.

    Asserted here rather than discovered in the UI. The engine's own column
    expressions for dicts land later; all this pins is *which visualizer* the
    cell gets, which is what widening can_visualize decides."""

    def test_dict_cell_gets_a_table_child_model(self):
        lst = [{'info': {'x': 1}}, {'info': {'x': 2}}]
        model = init_model(lst, mock_get_visualizer_dict_tables)
        child = model['children'][f"0{CELL_KEY_SEP}$['info']"]
        # MockDictVisualizer would have handed back None here.
        self.assertIsInstance(child, dict)
        self.assertIn('display_mode', child)

    def test_dict_survives_init_model_and_visualize(self):
        # PR A's actual guarantee: the engine accepts a dict end-to-end. The
        # column expressions that make it *read* correctly ($k/$v) land with
        # the sigils; until then a dict takes the ['$'] fallback. What must
        # not happen is a crash -- the sampling path indexes positionally,
        # which on a dict is a key lookup.
        for d in ({'a': 1, 'b': 2}, {}, {(1, 2): 'pair'}, {'x': {'y': 1}}):
            with self.subTest(d=d):
                model = init_model(d, mock_get_visualizer_dict_tables)
                self.assertIsInstance(model, dict)
                html_out = visualize(d, model, mock_get_visualizer_dict_tables, None)
                self.assertIsInstance(html_out, str)

    def test_a_simple_dict_gets_the_two_column_layout(self):
        # Reached by the FALLBACK, not by sampling: sampling the values of
        # {'a': 1} asks an int for its fields, and ints fall to a visualizer
        # with no get_fields attribute at all, so require_all bails. Written
        # explicitly or the implementation lands on ['$k'].
        model = init_model({'a': 1, 'b': 2}, mock_get_visualizer_dict_tables)
        self.assertEqual(list(model['columns']), ['$k', '$v'])

    def test_a_dict_of_records_detects_the_values_fields(self):
        d = {'alice': {'age': 30, 'city': 'SD'},
             'bob': {'age': 25, 'city': 'LA'}}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(list(model['columns']), ['$k', "$v['age']", "$v['city']"])

    def test_the_leading_dollar_is_rewritten_through_the_substitution(self):
        # Not str.replace: a field with a $ inside a string literal is exactly
        # the trap dollar_expr_names_index exists to avoid.
        d = {'x': {'a$b': 1}}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(list(model['columns']), ['$k', "$v['a$b']"])

    def test_an_empty_dict_still_gets_the_two_columns(self):
        model = init_model({}, mock_get_visualizer_dict_tables)
        self.assertEqual(list(model['columns']), ['$k', '$v'])

    def test_a_dict_renders_key_and_value_side_by_side(self):
        # What the whole landing is for: a simple dict renders exactly as if it
        # were a two-column list of key and value.
        d = {'alice': 30}
        model = init_model(d, mock_get_visualizer_dict_tables)
        html_out = visualize(d, model, mock_get_visualizer_dict_tables, None)
        self.assertIn('alice', html_out)
        self.assertIn('30', html_out)

    def test_a_bare_dollar_column_still_reads_as_the_pair(self):
        # The columns are $k/$v by default now, but a user who types `$` gets
        # the row itself, which for a dict is the (key, value) pair.
        d = {'alice': 30}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_column_values('$', d, model), [('alice', 30)])

    def test_default_mock_still_routes_dicts_to_the_compact_mock(self):
        # Guards the opt-in: if this ever flips, the rest of the suite is
        # silently testing something else.
        lst = [{'info': {'x': 1}}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model['children'][f"0{CELL_KEY_SEP}$['info']"])


class TestTableDetection(unittest.TestCase):
    """Test that init_model detects table mode for homogeneous lists."""

    def test_list_of_dicts_is_table_mode(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("$['name']", model['columns'])
        self.assertIn("$['age']", model['columns'])

    def test_list_of_strings_is_table_mode_with_dollar_column(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ['$'])

    def test_empty_list_is_table_mode(self):
        model = init_model([], mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ['$'])

    def test_list_of_lists_is_table_mode(self):
        lst = [[1, 2, 3], [4, 5, 6]]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ['$[0]', '$[1]', '$[2]'])

    def test_mixed_types_is_table_mode_with_dollar_column(self):
        lst = ["hello", 42]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ['$'])

    def test_union_columns_from_different_field_sets(self):
        lst = [{'a': 1, 'b': 2}, {'b': 3, 'c': 4}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        cols = model['columns']
        self.assertIn("$['a']", cols)
        self.assertIn("$['b']", cols)
        self.assertIn("$['c']", cols)

    def test_list_of_objects_is_table_mode(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        lst = [Point(1, 2), Point(3, 4)]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn('$.x', model['columns'])
        self.assertIn('$.y', model['columns'])

    def test_single_item_list_of_dicts_is_table_mode(self):
        lst = [{'x': 1}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')

    def test_table_mode_has_cell_children(self):
        """In table mode, children are keyed by composite row\\x00field keys."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("0\x00$['name']", model['children'])
        self.assertIn("1\x00$['name']", model['children'])


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
        self.assertIn("$['name']", unescaped)
        self.assertIn("$['age']", unescaped)
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
        self.assertIn("$['a']", unescaped)
        self.assertIn("$['b']", unescaped)
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
        composite_key = "0\x00$['name']"
        model['focused_child'] = composite_key  # see TestFocusTracking
        event = make_child_mouse_event(composite_key, 'MouseDown(index=0)')
        new_model, commands = update(event, None, model, lst, mock_get_visualizer)
        cell_model = new_model['children'][composite_key]
        self.assertIn('last_event', cell_model)

    def test_cell_event_preserves_other_cells(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        event = make_child_mouse_event("0\x00$['name']", 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        bob_key = "1\x00$['name']"
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
        model['focused_child'] = "0\x00$['k']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00$['k']", 'X')
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
        model['focused_child'] = '1\x00$'
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
        model['focused_child'] = "0\x00$['name']"
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
        event = make_child_mouse_event('0\x00$', 'MouseDown(index=0)')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model.get('focused_child'), '0\x00$')

    def test_second_child_event_changes_focus(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        event1 = make_child_mouse_event('0\x00$', 'MouseDown(index=0)')
        model, _ = update(event1, None, model, lst, mock_get_visualizer)
        self.assertEqual(model.get('focused_child'), '0\x00$')
        event2 = make_child_mouse_event('1\x00$', 'MouseDown(index=0)')
        model, _ = update(event2, None, model, lst, mock_get_visualizer)
        self.assertEqual(model.get('focused_child'), '1\x00$')

    def test_table_cell_event_sets_focused_child(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        composite_key = "0\x00$['name']"
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
        self.assertIsNone(model['editing_column'])
        self.assertFalse(model['adding_column'])
        self.assertEqual(model['column_input_value'], '')
        self.assertIsNone(model['selected_suggestion_index'])
        self.assertIsNone(model['column_drag_from'])
        self.assertIsNone(model['column_drag_over'])

    def test_string_list_has_column_management_fields(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIsNone(model['editing_column'])
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
        self.assertIn('editing_column', model)
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
        self.assertIsNone(new_model['editing_column'])

    def test_column_select_adds_column_when_adding(self):
        lst = [{'name': 'Alice', 'age': 30, 'city': 'NYC'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "$['ci"
        event = make_column_mouse_event(repr(ColumnSelect(name="$['city']")))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn("$['city']", new_model['columns'])
        self.assertFalse(new_model['adding_column'])
        self.assertEqual(new_model['column_input_value'], '')

    def test_enter_commits_add_column(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "$['age']"
        event = make_column_key_event('Enter')
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, cmds = update(event, None, model, lst, mock_get_visualizer)
        self.assertIn("$['age']", new_model['columns'])
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
        self.assertEqual(list(new_model['columns']), original_cols)
        self.assertFalse(new_model['adding_column'])

    def test_add_column_saves_dotfile(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        event = make_column_mouse_event(repr(ColumnSelect(name="$['extra']")))
        with patch('table_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()


class TestColumnEdit(unittest.TestCase):
    """Test editing existing columns."""

    def test_double_click_starts_editing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(ColumnClick(col=col_at(model))), detail=2)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['editing_column'], col_at(model))
        self.assertEqual(new_model['column_input_value'], list(model['columns'])[0])
        self.assertFalse(new_model['adding_column'])

    def test_single_click_does_not_start_editing(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(ColumnClick(col=col_at(model))), detail=1)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column'])

    def test_column_select_replaces_column_when_editing(self):
        # The suggestion list only ever offers columns the table doesn't
        # already show, so the replacement here is one that isn't present --
        # a name already in the table is refused, since columns are a map.
        lst = [{'name': 'Alice', 'age': 30, 'city': 'NYC'}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['zi"
        event = make_column_mouse_event(repr(ColumnSelect(name="$['zip']")))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns'])[0], "$['zip']")
        self.assertIsNone(new_model['editing_column'])

    def test_enter_commits_edit(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['nick']"
        event = make_column_key_event('Enter')
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns'])[0], "$['nick']")
        self.assertIsNone(new_model['editing_column'])

    def test_committing_a_name_the_table_already_has_is_refused(self):
        # `columns` is a map, so two columns cannot share a name -- and they
        # never usefully could: cell identity is the column expression, so a
        # duplicate was always a second cell wearing the first one's identity.
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        before = list(model['columns'])
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['age']"
        event = make_column_key_event('Enter')
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), before)

    def test_escape_cancels_edit(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        original_col = list(model['columns'])[0]
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['bogus']"
        event = make_column_key_event('Escape')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column'])
        self.assertEqual(new_model['column_input_value'], '')
        self.assertEqual(list(new_model['columns'])[0], original_col)


class TestColumnRemove(unittest.TestCase):
    """Test removing columns."""

    def test_remove_column_removes_from_list(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn("$['name']", model['columns'])
        name_idx = list(model['columns']).index("$['name']")
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, name_idx))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertNotIn("$['name']", new_model['columns'])

    def test_remove_column_saves_dotfile(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model))))
        with patch('table_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()

    def test_remove_column_cleans_up_children(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        name_idx = list(model['columns']).index("$['name']")
        self.assertIn("0\x00$['name']", model['children'])
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, name_idx))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertNotIn("0\x00$['name']", new_model['children'])
        self.assertNotIn("1\x00$['name']", new_model['children'])

    def test_remove_out_of_range_is_noop(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        original_cols = list(model['columns'])
        event = make_column_mouse_event(repr(RemoveColumnClick(col='$.gone')))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), original_cols)

    def test_remove_cancels_editing_if_index_matches(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['name']"
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['editing_column'])
        self.assertEqual(new_model['column_input_value'], '')

    def test_removing_another_column_leaves_the_open_box_alone(self):
        # Nothing to adjust: what is being edited is named, so a column going
        # from in front of it doesn't move it.
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        edited = col_at(model, 2)
        model['editing_column'] = edited
        model['column_input_value'] = edited
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['editing_column'], edited)


def _first_column_header(output):
    """Return the markup of the first non-index column header cell."""
    m = re.search(r'<th class="[^"]*col-header[^"]*".*?</th>', output, re.DOTALL)
    assert m is not None, 'no column header found'
    return m.group(0)


def col_at(model, index=0):
    """The column at a position -- what a test means by "the first column".

    Events name their column, so a test that wants to click the first one asks
    what it is called rather than spelling a position the table may not keep.
    """
    from table_visualizer import _menu_targets
    return _menu_targets(model['columns'])[index]


def menu_id(model, kind='col-menu', index=0):
    """The id of a menu or chip on the column at *index*.

    The tests' twin of `_menu_id`: the ids name their column, so a test that
    wants "the menu on the first column" asks for it rather than spelling a
    position that the column may not keep.
    """
    from table_visualizer import _menu_id, _menu_targets
    return _menu_id(kind, _menu_targets(model['columns'])[index])


class TestColumnMenu(unittest.TestCase):
    """The per-column ▾ menu: a click-toggled, state-driven dropdown pinned to the
    right edge of each header. Remove Column lives here rather than as a bare × in
    the header itself."""

    def test_header_renders_menu_trigger_after_the_name(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        # Flex ordering is what puts the ▾ at the right edge, so DOM order and the
        # inner wrapper are the parts a string assertion can hold onto.
        self.assertEqual(
            [c for c in ('col-header-inner', 'col-handle', 'col-name', 'col-menu-trigger')
             if c in th],
            ['col-header-inner', 'col-handle', 'col-name', 'col-menu-trigger'])
        self.assertLess(th.index('col-name'), th.index('col-menu-trigger'))

    def test_closed_header_has_no_remove_button_and_no_panel(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('RemoveColumnClick', output)
        self.assertNotIn('col-menu-panel', output)

    def test_toggle_opens_then_closes(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        opened, _ = update(make_dropdown_toggle_event(menu_id(model)), None,
                           model, lst, mock_get_visualizer)
        self.assertEqual(opened['openDropdown'], {'id': menu_id(opened)})
        closed, _ = update(make_dropdown_toggle_event(menu_id(opened)), None,
                           opened, lst, mock_get_visualizer)
        self.assertIsNone(closed['openDropdown'])

    def test_toggle_switches_between_columns(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': menu_id(model)}
        new_model, _ = update(make_dropdown_toggle_event('col-menu-1'), None, model,
                              lst, mock_get_visualizer)
        self.assertEqual(new_model['openDropdown'], {'id': 'col-menu-1'})

    def test_open_menu_renders_flyout_aligned_state_driven_panel(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': menu_id(model)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        self.assertIn('snc-dropdown-panel flyout col-menu-panel', th)
        self.assertIn('snc-dropdown-align="flyout"', th)
        # data-hover-menu would route this to the clone-on-hover path instead of
        # the hoisting path, and the menu would vanish when the pointer left it.
        self.assertNotIn('data-hover-menu', th)
        self.assertIn('Remove Column', th)
        # Trigger stays visible while its panel is hoisted out of the header.
        self.assertIn('col-menu snc-hover-hidden full-opacity-on-hover open', th)

    def test_menu_removes_column_and_closes(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        name_idx = list(model['columns']).index("$['name']")
        model['openDropdown'] = {'id': menu_id(model, index=name_idx)}
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, name_idx))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertNotIn("$['name']", new_model['columns'])
        self.assertIsNone(new_model['openDropdown'])

    def test_column_edits_close_an_open_menu(self):
        # Not because the menu could land on the wrong column any more -- the
        # ids name theirs -- but because an edit is finished with the menu.
        lst = [{'name': 'Alice', 'age': 30}]
        for make_event, detail in ((lambda m: ColumnClick(col=col_at(m)), 2),
                                   (lambda m: AddColumnClick(), 1),
                                   (lambda m: ColumnDragStart(col=col_at(m)), 1)):
            model = init_model(lst, mock_get_visualizer)
            event = make_column_mouse_event(repr(make_event(model)), detail=detail)
            with self.subTest(event=event['pythonEventStr']):
                model['openDropdown'] = {'id': menu_id(model)}
                new_model, _ = update(event, None, model, lst, mock_get_visualizer)
                self.assertIsNone(new_model['openDropdown'])


class TestColumnReorder(unittest.TestCase):
    """Test drag-and-drop column reordering."""

    def test_drag_start_sets_drag_from(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        dragged = col_at(model, 1)
        event = make_column_mouse_event(repr(ColumnDragStart(col=dragged)))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        # The column being dragged, by name: it is held across the moves that
        # follow, and a position could go out of date under it.
        self.assertEqual(new_model['column_drag_from'], dragged)
        self.assertEqual(new_model['column_drag_over'], dragged)

    def test_drag_over_sets_drag_over(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = col_at(model, 2)
        event = make_column_mouse_move_event(repr(ColumnDragOver(col=col_at(model))), buttons=1)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['column_drag_over'], col_at(model))

    def test_drag_over_cancels_on_button_release(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = col_at(model, 0)
        model['column_drag_over'] = col_at(model, 1)
        event = make_column_mouse_move_event(repr(ColumnDragOver(col=col_at(model, 1))), buttons=0)
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['column_drag_from'])
        self.assertIsNone(new_model['column_drag_over'])

    def test_drag_end_reorders_forward(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = col_at(model, 0)
        model['column_drag_over'] = col_at(model, 2)
        event = make_column_mouse_up_event(repr(ColumnDragEnd(col=col_at(model, 2))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns'])[0], original[1])
        self.assertEqual(list(new_model['columns'])[1], original[2])
        self.assertEqual(list(new_model['columns'])[2], original[0])
        self.assertIsNone(new_model['column_drag_from'])
        self.assertIsNone(new_model['column_drag_over'])

    def test_drag_end_reorders_backward(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = col_at(model, 2)
        model['column_drag_over'] = col_at(model, 0)
        event = make_column_mouse_up_event(repr(ColumnDragEnd(col=col_at(model))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns'])[0], original[2])
        self.assertEqual(list(new_model['columns'])[1], original[0])
        self.assertEqual(list(new_model['columns'])[2], original[1])

    def test_drag_end_same_position_is_noop(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        model['column_drag_from'] = col_at(model, 0)
        model['column_drag_over'] = col_at(model, 0)
        event = make_column_mouse_up_event(repr(ColumnDragEnd(col=col_at(model))))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), original)

    def test_drag_end_saves_dotfile(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['column_drag_from'] = col_at(model, 0)
        model['column_drag_over'] = col_at(model, 1)
        event = make_column_mouse_up_event(repr(ColumnDragEnd(col=col_at(model, 1))))
        with patch('table_visualizer.save_columns_to_dotfile') as mock_save:
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
            mock_save.assert_called_once()

    def test_drag_end_without_drag_is_noop(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        original = list(model['columns'])
        event = make_column_mouse_up_event(repr(ColumnDragEnd(col=col_at(model, 1))))
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), original)


class TestColumnKeyboard(unittest.TestCase):
    """Test keyboard interaction in column input."""

    def test_escape_cancels_add(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['column_input_value'] = "$['na"
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
        with patch('table_visualizer.save_columns_to_dotfile'):
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
        event = make_column_input_event("$['na")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['column_input_value'], "$['na")

    def test_column_input_auto_highlights_first_suggestion(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['columns'] = []
        event = make_column_input_event("$['n")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['selected_suggestion_index'], 0)

    def test_column_input_clears_selection_when_no_suggestions(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['selected_suggestion_index'] = 0
        event = make_column_input_event("$['zzzzz")
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model['selected_suggestion_index'])


class TestColumnAutocomplete(unittest.TestCase):
    """Test column autocomplete suggestions."""

    def test_get_all_possible_columns_from_dicts(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'city': 'NYC'}]
        cols = _get_all_possible_columns(lst, mock_get_visualizer)
        self.assertIn("$['name']", cols)
        self.assertIn("$['age']", cols)
        self.assertIn("$['city']", cols)

    def test_get_column_suggestions_filters_existing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, ["$['name']"], '')
        self.assertNotIn("$['name']", suggestions)
        self.assertIn("$['age']", suggestions)

    def test_get_column_suggestions_filters_by_prefix(self):
        lst = [{'name': 'Alice', 'age': 30}]
        suggestions = _get_column_suggestions(lst, mock_get_visualizer, [], "$['n")
        self.assertIn("$['name']", suggestions)
        self.assertNotIn("$['age']", suggestions)

    def test_get_all_possible_columns_empty_list(self):
        self.assertEqual(_get_all_possible_columns([], mock_get_visualizer), [])

    def test_get_all_possible_columns_from_objects(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        lst = [Point(1, 2), Point(3, 4)]
        cols = _get_all_possible_columns(lst, mock_get_visualizer)
        self.assertIn('$.x', cols)
        self.assertIn('$.y', cols)


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
        save_columns_to_dotfile('builtins.dict', [], ["$['name']", "$['age']"])
        result = load_columns_from_dotfile('builtins.dict')
        self.assertEqual(result, [{'expr': "$['name']"}, {'expr': "$['age']"}])

    def test_save_preserves_other_types(self):
        save_columns_to_dotfile('type.A', [], ['$.x'])
        save_columns_to_dotfile('type.B', [], ['$.y'])
        self.assertEqual(load_columns_from_dotfile('type.A'), [{'expr': '$.x'}])
        self.assertEqual(load_columns_from_dotfile('type.B'), [{'expr': '$.y'}])

    def test_load_corrupt_file(self):
        with open(COLUMN_DOTFILE_NAME, 'w') as f:
            f.write('not json{{{')
        result = load_columns_from_dotfile('builtins.dict')
        self.assertIsNone(result)

    def test_init_model_loads_from_dotfile(self):
        save_columns_to_dotfile('builtins.dict', [], ["$['age']", "$['name']"])
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(list(model['columns']), ["$['age']", "$['name']"])

    def test_init_model_falls_back_when_no_dotfile(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        self.assertIn("$['name']", model['columns'])
        self.assertIn("$['age']", model['columns'])


class TestColumnVisualize(unittest.TestCase):
    """Test HTML rendering of column management controls in table mode."""

    def test_table_has_add_column_button(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('AddColumnClick', output)

    def test_table_headers_have_menu_button(self):
        # Remove lives in this menu now, not as a bare × in the header.
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(
            f'DropdownToggle(dropdown_id={html.escape(repr(menu_id(model)))})',
            output)

    def test_table_headers_have_drag_handle(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(html.escape(repr(ColumnDragStart(col=col_at(model)))), output)
        self.assertIn(html.escape(repr(ColumnDragEnd(col=col_at(model)))), output)
        # Movement is only tracked once a drag has started -- see
        # TestHeaderTracksTheMouseOnlyWhileDragging.
        self.assertNotIn(html.escape(repr(ColumnDragOver(col=col_at(model)))), output)
        model['column_drag_from'] = col_at(model, 0)
        self.assertIn(html.escape(repr(ColumnDragOver(col=col_at(model)))),
                      visualize(lst, model, mock_get_visualizer, None))

    def test_table_headers_have_click_handler(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(html.escape(repr(ColumnClick(col=col_at(model)))), output)
        self.assertIn(html.escape(repr(ColumnClick(col=col_at(model, 1)))), output)

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
        model['column_input_value'] = "$['na"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<input', output)
        self.assertIn('snc-input', output)
        self.assertIn('ColumnInput', output)

    def test_table_shows_input_when_editing(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['name']"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('<input', output)
        self.assertIn('snc-select-all', output)

    def test_table_shows_autocomplete_suggestions(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        model['columns'] = []
        model['column_input_value'] = "$['"
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
        model['editing_column'] = col_at(model)
        model['column_input_value'] = "$['name']"
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('autofocus', output)

    def test_child_events_still_route_in_table_mode(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        composite_key = "0\x00$['name']"
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

    def test_remove_dollar_column_from_string_list(self):
        lst = ["hello", "world"]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(list(model['columns']), ['$'])
        event = make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model))))
        with patch('table_visualizer.save_columns_to_dotfile'):
            new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), [])


class TestColumnHeaderExpression(unittest.TestCase):
    """Test that column headers in table mode have draggable snc-py-exps."""

    def test_column_header_no_snc_py_exp_without_source(self):
        """Column headers do not have snc-py-exps when var_and_exp is not provided."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(model['display_mode'], 'table')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('snc-py-exps', html_output)

    def test_column_header_has_snc_py_exp_with_source(self):
        """Column headers have snc-py-exps with list comprehension expression."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        self.assertEqual(model['display_mode'], 'table')
        self.assertEqual(model.get('_source_expr'), 'people')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # Column $['name'] -> [item['name'] for item in people]
        self.assertIn(exp_attr("[item['name'] for item in people]"),
                      html_output)

    def test_column_header_is_draggable(self):
        """Column header snc-py-exps span should have draggable=true."""
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(f'{exp_attr("[item[\'name\'] for item in people]")} '
                      'draggable="true"', html_output)

    def test_column_header_bare_expression(self):
        """For a bare expression line (no assignment), uses the whole expression."""
        lst = [{'x': 1}, {'x': 2}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=(None, 'get_items()'))
        self.assertEqual(model.get('_source_expr'), 'get_items()')
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(exp_attr("[item['x'] for item in get_items()]"),
                      html_output)


class TestCellDraggablePyExp(unittest.TestCase):
    """Test that table cells have draggable snc-py-exps attributes."""

    def test_no_snc_py_exp_without_source(self):
        """Cells do not have snc-py-exps when var_and_exp is not provided."""
        lst = [{'age': 25}, {'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('snc-py-exps', html_output)

    def test_generic_cell_delegates_drag_to_child(self):
        """Generic cells (int, model=None) get NO parent-emitted wrapper; the
        child receives var_and_exp and self-wraps. The mock generic visualizer
        echoes the expression it was given so we can verify propagation."""
        lst = [{'age': 25}, {'age': 30}, {'age': 35}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # The child was handed the per-cell expression via var_and_exp. The
        # last row is handed `[-1]` instead (see _names_from_end), so the rows
        # asked about here are ones with a row after them.
        self.assertIn("child-expr=people[0]['age']", html_output)
        self.assertIn("child-expr=people[1]['age']", html_output)
        self.assertIn("child-expr=people[-1]['age']", html_output)
        # Parent does not also wrap generic cells in py-exp-cell.
        self.assertNotIn('class="py-exp-cell"', html_output)

    def test_nongeneric_small_cell_whole_area_grab(self):
        """Non-generic small (non-focused) cells use whole-area py-exp-grab,
        not the old py-exp-cell border."""
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn(f'{exp_attr("people[0][\'name\']")} draggable="true"',
                      html_output)
        self.assertIn('class="py-exp-grab"', html_output)
        # The bulky border pattern is gone.
        self.assertNotIn('class="py-exp-cell"', html_output)
        self.assertNotIn('draggable="false"', html_output)

    def test_nongeneric_focused_cell_not_draggable(self):
        """The focused (interactive, small=False) non-generic cell gets NO drag
        wrapper - it needs its mouse events."""
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        model['focused_child'] = f"0{CELL_KEY_SEP}$['name']"
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # No drag wrapper around the focused cell. Asked of the cell rather
        # than the whole table: the row's own handle names this row by its one
        # visible column, which is the same expression from somewhere else.
        cell = re.search(r'<td>.*?</td>', html_output, re.DOTALL).group(0)
        self.assertNotIn(exp_attr("people[0]['name']"), cell)
        self.assertNotIn('class="py-exp-grab"', html_output)
        self.assertNotIn('class="py-exp-cell"', html_output)

    def test_nongeneric_cell_content_preserved(self):
        """Non-generic cell visualizer content should be present inside the wrapper."""
        lst = [{'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('people', 'people'))
        html_output = visualize(lst, model, mock_get_visualizer, None)
        # MockStringVisualizer renders: <span snc-mouse-down="MouseDown(index=0)">Bob</span>
        self.assertIn('Bob</span>', html_output)


class TestListNeverSelfWraps(unittest.TestCase):
    """The list visualizer is never itself a drag handle, in either size. A
    handle over its whole area claims every hover inside it, so the expression
    tooltip pops over content that has its own (more specific) handle. Only the
    generic visualizers, which have no content of their own, self-wrap."""

    def test_small_with_var_and_exp_renders_bare(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('nums', 'nums'))
        html_output = visualize(lst, model, mock_get_visualizer, None,
                                small=True, var_and_exp=(None, 'nums'))
        self.assertFalse(html_output.startswith('<span snc-py-exps'))
        # The $ column header does hand over the whole list -- that is the
        # column -- but from inside the table, not from a wrapper around it.
        self.assertNotIn('py-exp-grab', html_output)

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
        self.assertFalse(html_output.startswith('<span snc-py-exps'))

    def test_depth_capped_leaf_renders_bare(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('nums', 'nums'))
        model['_too_deep'] = True
        html_output = visualize(lst, model, mock_get_visualizer, None,
                                small=True, var_and_exp=(None, 'nums'))
        self.assertNotIn('py-exp-grab', html_output)


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

from table_visualizer import (
    SearchBoxInput, FirstMatchToggle, ActionButtonClick, DropdownToggle,
    CopyToClipboard,
    parse_search_term, needs_implicit_dollar,
    _get_search_context, generate_action, _get_matching_indices,
    compose_column_searches,
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
        result = parse_search_term('$ > 100')
        self.assertEqual(result, ('expr', '$ > 100'))

    def test_integer_literal_is_expr(self):
        result = parse_search_term('5')
        self.assertEqual(result, ('expr', '5'))

    def test_list_literal_is_expr(self):
        result = parse_search_term('[1,3,5]')
        self.assertEqual(result, ('expr', '[1,3,5]'))

    def test_predicate_with_dollar(self):
        result = parse_search_term('$.name == "Alice"')
        self.assertEqual(result, ('expr', '$.name == "Alice"'))

    def test_complex_slice(self):
        result = parse_search_term('len(x):')
        self.assertEqual(result, ('slice', ('len(x)', '')))

    def test_string_with_colon_is_not_slice(self):
        result = parse_search_term('"a:b"')
        self.assertNotEqual(result[0], 'slice')


class TestNeedsImplicitDollar(unittest.TestCase):
    """Test detection of binary operators needing implicit $ prepend."""

    def test_greater_than(self):
        self.assertTrue(needs_implicit_dollar('> 100'))

    def test_less_than(self):
        self.assertTrue(needs_implicit_dollar('< 50'))

    def test_greater_equal(self):
        self.assertTrue(needs_implicit_dollar('>= 10'))

    def test_less_equal(self):
        self.assertTrue(needs_implicit_dollar('<= 10'))

    def test_double_equals(self):
        self.assertTrue(needs_implicit_dollar('== "hello"'))

    def test_not_equals(self):
        self.assertTrue(needs_implicit_dollar('!= 0'))

    def test_in_operator(self):
        self.assertTrue(needs_implicit_dollar('in [1,2,3]'))

    def test_not_in_operator(self):
        self.assertTrue(needs_implicit_dollar('not in [1,2,3]'))

    def test_is_operator(self):
        self.assertTrue(needs_implicit_dollar('is None'))

    def test_is_not_operator(self):
        self.assertTrue(needs_implicit_dollar('is not None'))

    def test_dot_attribute(self):
        self.assertTrue(needs_implicit_dollar('.startswith("foo")'))

    def test_no_implicit_for_dollar_expr(self):
        self.assertFalse(needs_implicit_dollar('$ > 100'))

    def test_no_implicit_for_integer(self):
        self.assertFalse(needs_implicit_dollar('5'))

    def test_no_implicit_for_list(self):
        self.assertFalse(needs_implicit_dollar('[1,2,3]'))

    def test_no_implicit_for_variable(self):
        self.assertFalse(needs_implicit_dollar('len($) > 3'))

    def test_no_implicit_for_none(self):
        self.assertFalse(needs_implicit_dollar('None'))

    def test_with_leading_whitespace(self):
        self.assertTrue(needs_implicit_dollar(' > 100'))


class TestGetMatchingIndices(unittest.TestCase):
    """Test _get_matching_indices for various search types."""

    def test_predicate_match(self):
        lst = [10, 20, 30, 40, 50]
        indices = _get_matching_indices('$ > 25', lst, eval)
        self.assertEqual(indices, [2, 3, 4])

    def test_predicate_no_match(self):
        lst = [1, 2, 3]
        indices = _get_matching_indices('$ > 100', lst, eval)
        self.assertEqual(indices, [])

    def test_implicit_dollar(self):
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
        indices = _get_matching_indices('$ == "alice"', lst, eval)
        self.assertEqual(indices, [0, 2])


def program_scope(**names):
    """An eval_in_scope for a user program that defined `names`.

    The real one is `lambda _c: eval(_c)` compiled into the user's module, so
    the code it runs resolves against the program's globals and nothing else.
    Passing the `eval` builtin instead -- what most tests here do -- resolves
    against whichever visualizer module happens to be calling it, which is
    exactly the confusion these tests are about.
    """
    program_globals = dict(names)
    return lambda code: eval(code, program_globals)


class TestSearchesSeeTheProgramScope(unittest.TestCase):
    """A search is written where the user is looking, so the names in it are
    the program's names -- `== s`, not just `== 'a'`."""

    def test_predicate_names_a_variable(self):
        lst = ['a', 'b', 'c']
        scope = program_scope(s='a')
        self.assertEqual(_get_matching_indices('$ == s', lst, scope), [0])

    def test_implicit_dollar_predicate_names_a_variable(self):
        lst = ['a', 'b', 'c']
        scope = program_scope(s='a')
        self.assertEqual(_get_matching_indices('== s', lst, scope), [0])

    def test_predicate_names_a_function(self):
        lst = [1, 2, 3, 4]
        scope = program_scope(is_even=lambda n: n % 2 == 0)
        self.assertEqual(_get_matching_indices('is_even($)', lst, scope),
                         [1, 3])

    def test_predicate_names_a_collection_to_test_membership(self):
        lst = ['a', 'b', 'c']
        scope = program_scope(keep=['a', 'c'])
        self.assertEqual(_get_matching_indices('$ in keep', lst, scope),
                         [0, 2])

    def test_the_array_is_still_two_dollars(self):
        # $$ is bound by the matcher itself, so reaching into the program's
        # scope must not cost the bindings the matcher supplies.
        lst = [1, 5, 3, 5]
        scope = program_scope(max=max)
        self.assertEqual(_get_matching_indices('$ == max($$)', lst, scope),
                         [1, 3])

    def test_an_unknown_name_matches_nothing(self):
        lst = ['a', 'b', 'c']
        self.assertEqual(_get_matching_indices('$ == nope', lst,
                                               program_scope()), [])

    def test_a_column_search_naming_a_variable_matches_rows(self):
        # What the user types in a column's search box is lifted into the main
        # search box, so a name typed there has the same program scope to
        # resolve against.
        lst = ['a', 'b', 'c']
        scope = program_scope(s='a')
        composed = compose_column_searches(['$'], {'$': {'op': '==',
                                                         'text': 's'}}, scope)
        self.assertEqual(composed, '$ == s')
        self.assertEqual(_get_matching_indices(composed, lst, scope), [0])

    def test_count_counts_the_matches_of_a_search_naming_a_variable(self):
        lst = ['a', 'b', 'c']
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ == s'
        output = visualize(lst, model, mock_get_visualizer,
                           program_scope(s='a', strs=lst))
        self.assertIn('Count: 1', output)

    def test_only_the_matching_row_is_highlighted_for_a_search_naming_a_variable(self):
        lst = ['a', 'b', 'c']
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ == s'
        output = visualize(lst, model, mock_get_visualizer,
                           program_scope(s='a', strs=lst))
        self.assertEqual(output.count('class="row-match"'), 1)
        self.assertEqual(output.count('class="row-dim"'), 2)


# === Code generation tests ===

class TestGetSearchContext(unittest.TestCase):
    """Test _get_search_context builds correct context dicts."""

    def test_predicate_context(self):
        model = {'search': '$ > 100', 'first_match': False}
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

    def test_implicit_dollar_in_context(self):
        model = {'search': '> 100', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['is_predicate'])
        self.assertEqual(ctx['predicate_expr'], 'item > 100')

    def test_first_match_flag(self):
        model = {'search': '$ > 100', 'first_match': True}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertTrue(ctx['is_first'])

    def test_no_search_returns_none(self):
        model = {'search': None, 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'), eval_in_scope=eval)
        self.assertIsNone(ctx)

    def test_no_source_returns_none(self):
        model = {'search': '$ > 0', 'first_match': False}
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
        self.assertEqual(code, 'for item in (item for item in data if item > 100):')

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
        self.assertEqual(code, 'if any(item > 100 for item in data):')

    def test_if_all_predicate(self):
        result = generate_action('if_all', self._predicate_ctx())
        name, code = result
        self.assertEqual(code, 'if all(item > 100 for item in data):')

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

    def test_find_indices_broadcast_stop_starts_at_zero(self):
        # `:[3,5,7]` -- every band starts at the front, so every band reports 0.
        _, code = generate_action('find_indices', self._broadcast_stop_ctx())
        self.assertEqual(code, '[0] * len([3,5,7])')
        self.assertEqual(eval(code), [0, 0, 0])

    def test_find_indices_broadcast_stop_reads_the_start_it_was_given(self):
        # `1:[3,5,7]` -- the bands are data[1:3], data[1:5], data[1:7], so they
        # start at 1. This used to hardcode the 0 and claim they started at 0.
        _, code = generate_action('find_indices',
                                  self._broadcast_stop_ctx(start='1'))
        self.assertEqual(code, '[1] * len([3,5,7])')
        self.assertEqual(eval(code), [1, 1, 1])
        # The band expression it has to agree with:
        _, filter_code = generate_action('filter',
                                         self._broadcast_stop_ctx(start='1'))
        self.assertEqual(filter_code, '[data[1:i] for i in [3,5,7]]')

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
        self.assertEqual(code, 'for item in data:')

    def test_whole_list_loop_orig_idx(self):
        result = generate_action('loop_orig_idx', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'for i, item in enumerate(data):')

    def test_whole_list_loop_new_idx(self):
        result = generate_action('loop_new_idx', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'for i, item in enumerate(data):')

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
        self.assertEqual(code, 'if any(data):')

    def test_whole_list_if_all(self):
        result = generate_action('if_all', self._whole_list_ctx())
        self.assertIsNotNone(result)
        _, code = result
        self.assertEqual(code, 'if all(data):')

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
        event = make_search_input_event('$ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(new_model['search'], '$ > 15')

    def test_empty_search_input_clears_search(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        event = make_search_input_event('')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertIsNone(new_model.get('search'))

    def test_search_input_preserves_other_model_state(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        original_columns = list(model['columns'])
        event = make_search_input_event('$ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertEqual(list(new_model['columns']), original_columns)


class TestAutoLinkOnInteraction(unittest.TestCase):
    """First interaction that yields a parseable expression auto-inserts a
    linked filter LOC; subsequent interactions update it via ChangeSelectedText."""

    def test_first_search_input_auto_inserts_linked_filter(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        event = make_search_input_event('$ > 15')
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
        model, first = update(make_search_input_event('$ > 15'), ('data', 'data'),
                              model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsInstance(first[0], tuple)

        model, commands = update(make_search_input_event('$ > 25'), ('data', 'data'),
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
            make_search_input_event('$ > 15'),
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
        new_model, commands = update(make_search_input_event('$ > 15'), None,
                                     model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertIsNone(new_model.get('linked_action'))


class TestActionButtonClickAutoLinks(unittest.TestCase):
    """Clicking an action button while unlinked inserts the LOC and links it."""

    def test_action_button_click_inserts_and_links(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        model, first = update(make_action_button_event('filter'),
                              ('data', 'data'), model, lst,
                              mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(any(isinstance(c, tuple) for c in first))
        model, commands = update(make_search_input_event('$ > 25'),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))

    def test_copy_click_does_not_link(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        event = make_action_button_event("join:'\\n'", copy=True)
        _, commands = update(event, ('data', 'data'), model, lst,
                             mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(len(commands) > 0)
        self.assertIsInstance(commands[0], CopyToClipboard)

    def test_join_custom_input_stored_in_dropdown(self):
        from table_visualizer import JoinSeparatorInput
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('value="$ &gt; 15"', output)

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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('ActionButtonClick', output)

    def test_action_buttons_hidden_when_small(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None, small=True)
        self.assertNotIn('ActionButtonClick', output)

    def test_filter_button_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("action=&#x27;filter&#x27;", output)

    def test_filter_label_changes_with_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Find One', output)

    def test_filter_label_without_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model['first_match'] = False
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Filter', output)

    def test_loop_dropdown_trigger_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('snc-dropdown-trigger', output)
        self.assertIn('Loop', output)

    def test_delete_button_label_changes_with_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model['first_match'] = True
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Delete First', output)

    def test_delete_button_label_without_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model['first_match'] = False
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Delete All', output)

    def test_find_indices_button_label(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("action=&#x27;count&#x27;", output)

    def test_count_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('row-match', output)

    def test_unmatched_rows_dimmed(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertIn('row-dim', output)

    def test_all_rows_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        model['adding_column'] = True
        model['column_input_value'] = '$.x'
        event = make_search_key_event('Enter')
        new_model, commands = update(event, ('data', 'data'), model, lst,
                                     mock_get_visualizer, eval_in_scope=eval)
        # The column was committed (not left in adding-column state).
        self.assertFalse(new_model['adding_column'])
        self.assertIn('$.x', new_model['columns'])


class TestCmdDeleteKey(unittest.TestCase):
    """Test that Cmd+Backspace triggers delete action."""

    def test_cmd_backspace_triggers_delete(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Loop', output)
        # Loop is now a hover-menu (data-hover-menu); options live in the
        # always-rendered panel.
        self.assertIn('data-hover-menu', output)

    def test_loop_dropdown_options_when_open(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model['openDropdown'] = {'id': 'action-loop'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('loop_no_idx', output)
        self.assertIn('loop_orig_idx', output)
        self.assertIn('loop_new_idx', output)

    def test_loop_dropdown_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('Join', output)
        self.assertIn('JoinSeparatorInput', output)

    def test_join_dropdown_disabled_in_first_match(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
        model['openDropdown'] = {'id': 'action-join'}
        output = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn("join:&#x27;&#x27;", output)
        self.assertIn("join:&#x27; &#x27;", output)
        self.assertIn("join:&#x27;,&#x27;", output)

    def test_join_custom_input_present(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        out = self._viz([10, 20, 30], '$ > 15')
        self.assertIn('Any (<span class="snc-code">True</span>)', out)

    def test_any_shows_false_when_no_match(self):
        out = self._viz([10, 20, 30], '$ > 100')
        self.assertIn('Any (<span class="snc-code">False</span>)', out)

    def test_if_any_shows_preview(self):
        out = self._viz([10, 20, 30], '$ > 15')
        self.assertIn('If Any (<span class="snc-code">True</span>)', out)

    def test_all_shows_true_when_all_match(self):
        out = self._viz([10, 20, 30], '$ > 5')
        self.assertIn('All (<span class="snc-code">True</span>)', out)

    def test_all_shows_false_when_not_all_match(self):
        out = self._viz([10, 20, 30], '$ > 15')
        self.assertIn('All (<span class="snc-code">False</span>)', out)

    def test_if_all_shows_preview(self):
        out = self._viz([10, 20, 30], '$ > 5')
        self.assertIn('If All (<span class="snc-code">True</span>)', out)

    def test_no_preview_without_source_expr(self):
        # Without a source expr the expression can't be built, so no suffix.
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        out = visualize(lst, model, mock_get_visualizer, self._scope(lst))
        self.assertNotIn('Any (<span class="snc-code">', out)

    def test_no_preview_without_eval_in_scope(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = '$ > 15'
        out = visualize(lst, model, mock_get_visualizer, None)
        self.assertNotIn('Any (<span class="snc-code">', out)

    def test_all_no_preview_in_first_match_mode(self):
        out = self._viz([10, 20, 30], '$ > 15', first_match=True)
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
        event = make_search_input_event('$ > 15')
        new_model, _ = update(event, None, model, lst, mock_get_visualizer)
        self.assertTrue(new_model.get('_scroll_to_match'))
        output = visualize(lst, new_model, mock_get_visualizer, eval)
        self.assertIn('snc-scroll-to-match', output)

    def test_scroll_to_match_on_first_matched_row_only(self):
        """Attribute appears on the first matched row, not subsequent matches."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 10'
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertEqual(output.count('snc-scroll-to-match'), 1)

    def test_no_scroll_to_match_without_flag(self):
        """Without _scroll_to_match flag, no attribute even with matches."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 100'
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
        model['search'] = '$ > 15'
        model['first_match'] = True
        model['_scroll_to_match'] = True
        output = visualize(lst, model, mock_get_visualizer, eval)
        self.assertEqual(output.count('snc-scroll-to-match'), 1)

    def test_scroll_to_match_on_tr_element(self):
        """The attribute should be on a <tr> element."""
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model['search'] = '$ > 15'
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
        # The line still holds what the filter action wrote before the unlink.
        taken_over = 'data_filtered = [item for item in data if item > 15]'
        model, commands = update(make_relink_event('takeover', text=taken_over),
                                 ('data', 'data'),
                                 model, lst, mock_get_visualizer, eval_in_scope=eval)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        self.assertEqual(model['linked_action'], 'filter')
        self.assertTrue(model['linked_has_assignment'])

    def test_relink_defaults_to_auto_link_action_when_none_stashed(self):
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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
        model, commands = update(make_search_input_event('$ > 2'),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertTrue(any(isinstance(c, ChangeSelectedText) for c in commands))
        self.assertFalse(any(isinstance(c, tuple) for c in commands))

    def test_stashed_unlink_action_wins_over_adoption(self):
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 15'
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

    def test_unparseable_takeover_links_without_overwriting(self):
        """An unrecognized line is still a valid link target, but the relink
        must not write over it — only the user's next interaction may."""
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 3'
        model, commands = update(
            make_relink_event('takeover', text='???  not parseable  ???'),
            self.var_and_exp, model, self.lst, mock_get_visualizer,
            eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'filter')
        self.assertEqual(commands, [])


class TestCtxToModel(unittest.TestCase):
    """Test _ctx_to_model sets model search/first_match from parsed context."""

    def test_predicate_ctx_to_model(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item > 100', 'is_first': False}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '$ > 100')
        self.assertFalse(model['first_match'])

    def test_predicate_first_ctx_to_model(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item > 100', 'is_first': True}
        _ctx_to_model(ctx, model)
        self.assertTrue(model['first_match'])

    def test_index_ctx_to_model(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_index': True, 'index_expr': '5'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '5')

    def test_slice_ctx_to_model(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_slice': True, 'slice_start': '2', 'slice_stop': '5'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '2:5')

    def test_multi_index_ctx_to_model(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_multi_index': True, 'indices_expr': '[1,3,5]'}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '[1,3,5]')

    def test_predicate_with_method_call(self):
        from table_visualizer import _ctx_to_model
        model = {'search': None, 'first_match': False}
        ctx = {'is_predicate': True, 'predicate_expr': 'item.startswith("a")', 'is_first': False}
        _ctx_to_model(ctx, model)
        self.assertEqual(model['search'], '$.startswith("a")')


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
        from table_visualizer import ChangeSelectedText
        model = self._adopt('[item for item in data if item > 3]')
        event = make_action_button_event('delete')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'delete')
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertTrue(len(change_cmds) > 0)

    def test_action_change_carries_new_var_name(self):
        """Switching action on an assignment-linked line suggests a new var name."""
        from table_visualizer import ChangeSelectedText
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
        from table_visualizer import ChangeSelectedText
        model = self._adopt('data_filtered = [item for item in data if item > 3]')
        event = make_search_input_event('$ > 2')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertTrue(len(change_cmds) > 0)
        self.assertIsNone(change_cmds[0].suggested_var_name)

    def test_linked_join_menu_updates_selected_text(self):
        from table_visualizer import ChangeSelectedText
        model = self._adopt("''.join(str(item) for item in data)")
        self.assertEqual(model.get('linked_action'), 'join')
        event = make_action_button_event("join:', '")
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer)
        self.assertEqual(model.get('linked_action'), 'join')
        change_cmds = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(change_cmds), 1)
        self.assertEqual(change_cmds[0].expression, "', '.join(str(item) for item in data)")

    def test_linked_search_change_emits_change_selected_text(self):
        from table_visualizer import ChangeSelectedText
        model = self._adopt('[item for item in data if item > 3]')
        event = make_search_input_event('$ > 2')
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
        model['search'] = '$ > 3'
        event = make_action_button_event('filter')
        model, commands = update(event, self.var_and_exp, model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        tuple_cmds = [c for c in commands if isinstance(c, tuple)]
        self.assertTrue(len(tuple_cmds) > 0)


class TestStatementActionsGenerateHeadersOnly(unittest.TestCase):
    """Statement actions generate a bare header. The body below the header
    belongs to the user, so a linked update must never re-emit one — that is
    what stacked a second `pass` under the loop on every action change."""

    def setUp(self):
        self.lst = [10, 20, 30]
        self.var_and_exp = ('data', 'data')

    def _clicked(self, action, model=None):
        model = model or init_model(self.lst, mock_get_visualizer)
        model.setdefault('search', '$ > 15')
        return update(make_action_button_event(action), self.var_and_exp,
                      model, self.lst, mock_get_visualizer, eval_in_scope=eval)

    def test_inserted_statement_is_header_only(self):
        model, commands = self._clicked('loop_no_idx')
        tuples = [c for c in commands if isinstance(c, tuple)]
        self.assertEqual(len(tuples), 1)
        _, code = tuples[0]
        self.assertTrue(code.rstrip().endswith(':'))
        self.assertNotIn('pass', code)

    def test_linked_action_change_emits_header_without_body(self):
        from table_visualizer import ChangeSelectedText
        model, _ = self._clicked('loop_no_idx')
        self.assertEqual(model['linked_action'], 'loop_no_idx')
        model, commands = self._clicked('loop_new_idx', model)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].expression.rstrip().endswith(':'))
        self.assertNotIn('pass', changes[0].expression)

    def test_linked_search_change_still_updates_a_statement(self):
        """The syntax guard must not silently drop statement updates."""
        from table_visualizer import ChangeSelectedText
        model, _ = self._clicked('loop_no_idx')
        model, commands = update(make_search_input_event('$ > 25'), self.var_and_exp,
                                 model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertIn('item > 25', changes[0].expression)

    def test_copy_statement_action_copies_runnable_code(self):
        from table_visualizer import CopyToClipboard
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 15'
        model, commands = update(make_action_button_event('loop_no_idx', copy=True),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        copies = [c for c in commands if isinstance(c, CopyToClipboard)]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].text.endswith('\n    pass'))
        ast.parse(copies[0].text)

    def test_hover_preview_of_statement_action_is_runnable(self):
        """The preview is copied and dragged into the file, so it needs a body."""
        from table_visualizer import _preview_expr
        model = init_model(self.lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = '$ > 15'
        preview = _preview_expr(model, 'loop_no_idx', eval)
        self.assertTrue(preview.endswith('\n    pass'))
        ast.parse(preview)

    def test_hover_preview_of_expression_action_is_unchanged(self):
        from table_visualizer import _preview_expr
        model = init_model(self.lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        model['search'] = '$ > 15'
        self.assertEqual(_preview_expr(model, 'filter', eval),
                         '[item for item in data if item > 15]')


class TestRelinkTakeoverOfStatementHeader(unittest.TestCase):
    """A `for`/`if` header is a legitimate link target, so takeover must adopt
    it like any other generated line rather than treating it as an assignment."""

    def setUp(self):
        self.lst = [1, 2, 3, 4, 5]
        self.var_and_exp = ('data', 'data')
        self.header = 'for item in (item for item in data if item > 3):'

    def test_fresh_takeover_adopts_header_without_commands(self):
        model = init_model(self.lst, mock_get_visualizer)
        model, commands = update(make_relink_event('takeover', text=self.header),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'loop_no_idx')
        self.assertEqual(model.get('linked_source_expr'), 'data')
        self.assertFalse(model.get('linked_has_assignment'))
        self.assertEqual(commands, [])

    def test_takeover_tolerates_a_body_in_the_taken_over_text(self):
        model = init_model(self.lst, mock_get_visualizer)
        model, commands = update(
            make_relink_event('takeover', text=self.header + '\n    pass'),
            self.var_and_exp, model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'loop_no_idx')
        self.assertEqual(commands, [])

    def test_resumed_statement_action_is_not_marked_as_assignment(self):
        """Unlink then relink a statement: the stashed action is regenerated,
        and marking it as an assignment would make its updates unparseable."""
        from table_visualizer import ChangeSelectedText
        model = self._unlinked_after('loop_no_idx')
        model, commands = update(make_relink_event('takeover', text=self.header),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertEqual(model.get('linked_action'), 'loop_no_idx')
        self.assertFalse(model.get('linked_has_assignment'))

    def _unlinked_after(self, action):
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 3'
        model, _ = update(make_action_button_event(action), self.var_and_exp,
                          model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_unlink_event(), self.var_and_exp, model, self.lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model.get('linked_action'))
        return model

    def test_fresh_takeover_adopts_whole_list_loop_header(self):
        """A plain `for item in xs:` is the whole-list loop this visualizer
        writes when there is no search, so takeover must recognize it."""
        model = init_model(self.lst, mock_get_visualizer)
        model, commands = update(make_relink_event('takeover', text='for item in data:'),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model.get('linked_action'), 'loop_no_idx')
        self.assertEqual(model.get('linked_source_expr'), 'data')
        self.assertFalse(model.get('linked_has_assignment'))
        self.assertEqual(commands, [])


class TestRelinkTakeoverOfForeignLine(unittest.TestCase):
    """Taking over a line this visualizer did not write.

    The chain icon means "own the next line", so the link is established, but
    nothing is written: the line changes only when the user next interacts. The
    link must be recorded in the model even though no command is emitted —
    otherwise the front-end is linked to a line Python knows nothing about, and
    the next interaction inserts a duplicate line instead of editing it."""

    def setUp(self):
        self.lst = [1, 2, 3, 4, 5]
        self.var_and_exp = ('item_matches', 'item_matches')
        # Derived from `item`, not from this visualizer's `item_matches`.
        self.foreign = "codons = re.findall(r'[A-Z]{3}', item, flags=re.M)"

    def _took_over(self, text, search=None):
        model = init_model(self.lst, mock_get_visualizer)
        if search:
            model['search'] = search
        model, commands = update(make_relink_event('takeover', text=text),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        return model, commands

    def test_links_without_touching_the_line(self):
        model, commands = self._took_over(self.foreign)
        self.assertEqual(commands, [])
        self.assertIsNotNone(model.get('linked_action'))
        self.assertEqual(model.get('linked_source_expr'), 'item_matches')
        self.assertTrue(model.get('auto_linked_once'))
        self.assertTrue(model.get('linked_has_assignment'))

    def test_next_interaction_edits_the_line_instead_of_inserting(self):
        from table_visualizer import ChangeSelectedText
        model, _ = self._took_over(self.foreign)
        model, commands = update(make_search_input_event('$ > 2'), self.var_and_exp,
                                 model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertFalse(any(isinstance(c, tuple) for c in commands))
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertIn('item for item in item_matches if item > 2', changes[0].expression)

    def test_takeover_with_a_search_still_edits_the_line_next(self):
        """The takeover writes nothing, so the expression it would have written
        must not be remembered as already-written. Otherwise the next
        interaction that regenerates it is suppressed as a no-op and the
        foreign text sits there forever under a chain icon claiming a link."""
        model, _ = self._took_over(self.foreign, search='$ > 2')
        model, commands = update(make_search_input_event('$ > 2'), self.var_and_exp,
                                 model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual([(type(c).__name__, c.expression) for c in commands],
                         [('ChangeSelectedText',
                           '[item for item in item_matches if item > 2]')])

    def test_header_takeover_links_a_statement_action(self):
        """Linking to a header must pick an action that generates a header, or
        the first interaction would replace the block and orphan its body."""
        from table_visualizer_grammar import _STATEMENT_ACTIONS
        model, commands = self._took_over('if flag:')
        self.assertEqual(commands, [])
        self.assertIn(model.get('linked_action'), _STATEMENT_ACTIONS)
        self.assertFalse(model.get('linked_has_assignment'))

    def test_next_interaction_after_header_takeover_stays_a_header(self):
        from table_visualizer import ChangeSelectedText
        model, _ = self._took_over('if flag:')
        model, commands = update(make_search_input_event('$ > 2'), self.var_and_exp,
                                 model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        changes = [c for c in commands if isinstance(c, ChangeSelectedText)]
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].expression.rstrip().endswith(':'))

    def test_stashed_expression_action_is_dropped_for_a_header(self):
        """A stashed `filter` would write a comprehension over the header."""
        from table_visualizer_grammar import _STATEMENT_ACTIONS
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 3'
        model, _ = update(make_action_button_event('filter'), self.var_and_exp,
                          model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_unlink_event(), self.var_and_exp, model, self.lst,
                          mock_get_visualizer, eval_in_scope=eval)
        model, commands = update(make_relink_event('takeover', text='if flag:'),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertIn(model.get('linked_action'), _STATEMENT_ACTIONS)

    def test_stashed_statement_action_is_dropped_for_an_assignment(self):
        """The mirror case: a stashed loop would leave `x = for item in ...:`."""
        from table_visualizer_grammar import _STATEMENT_ACTIONS
        model = init_model(self.lst, mock_get_visualizer)
        model['search'] = '$ > 3'
        model, _ = update(make_action_button_event('loop_no_idx'), self.var_and_exp,
                          model, self.lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_unlink_event(), self.var_and_exp, model, self.lst,
                          mock_get_visualizer, eval_in_scope=eval)
        model, commands = update(make_relink_event('takeover', text='x = compute()'),
                                 self.var_and_exp, model, self.lst,
                                 mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(commands, [])
        self.assertNotIn(model.get('linked_action'), _STATEMENT_ACTIONS)


# =============================================================================
# DSL Grammar Roundtrip Tests (bidirectional parsing)
# =============================================================================

class _ListActionTestBase(unittest.TestCase):
    """Base class for list visualizer DSL grammar roundtrip tests."""

    def setUp(self):
        from table_visualizer_grammar import TABLE_VIZ_GRAMMAR, generate_action as grammar_generate, parse_generated_code
        from bidirectional_dsl import generate, parse
        self.grammar = TABLE_VIZ_GRAMMAR
        self.raw_generate = generate
        self.raw_parse = parse
        self.generate_action = grammar_generate
        self.parse_generated_code = parse_generated_code

    def _gen(self, action, ctx):
        gen_ctx = {k: v for k, v in ctx.items() if v is not None}
        gen_ctx['action'] = action
        gen_ctx['has_pick'] = bool(ctx.get('pick_expr'))
        if ctx.get('is_slice'):
            gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
            gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
        return self.raw_generate(self.grammar, self.grammar['Action'], gen_ctx)

    _GRAMMAR_KEYS = frozenset({
        'action', 'is_predicate', 'is_index', 'is_slice', 'is_multi_index',
        'is_first', 'source_expr', 'predicate_expr', 'index_expr',
        'slice_start', 'slice_stop', 'indices_expr',
        'has_slice_start', 'has_slice_stop',
        'pick_expr', 'needs_index', 'is_dict',
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

    def test_parse_loop_no_idx_header_alone(self):
        """A linked header comes back from the editor without its body."""
        result = self.parse_generated_code('for item in (item for item in data if item > 100):')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'loop_no_idx')

    def test_parse_nested_loop_header_alone(self):
        result = self.parse_generated_code('for i, item in enumerate(data):\n    if item > 100:')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'loop_orig_idx')

    # --- Whole-list forms (no search) ---
    #
    # These are the actions available before the user types a search. They are
    # generated by table_visualizer.generate_action, so the grammar has to parse
    # them too or a relink can never recognize a plain `for item in xs:` as a
    # line this visualizer wrote.

    def test_parse_whole_list_loop(self):
        result = self.parse_generated_code('for item in data:')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'loop_no_idx')
        self.assertEqual(result['source_expr'], 'data')
        self.assertTrue(result.get('is_whole_list'))

    def test_parse_whole_list_loop_with_index(self):
        result = self.parse_generated_code('for i, item in enumerate(data):')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'loop_orig_idx')
        self.assertTrue(result.get('is_whole_list'))

    def test_parse_whole_list_if_any(self):
        result = self.parse_generated_code('if any(data):')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'if_any')
        self.assertTrue(result.get('is_whole_list'))

    def test_parse_whole_list_if_all(self):
        result = self.parse_generated_code('if all(data):')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'if_all')

    def test_parse_whole_list_any(self):
        result = self.parse_generated_code('any(data)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'any')

    def test_parse_whole_list_all(self):
        result = self.parse_generated_code('all(data)')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'all')

    def test_predicate_forms_still_win_over_whole_list(self):
        """The whole-list templates must not swallow the more specific forms."""
        for code, action in [
            ('for item in (item for item in data if item > 1):', 'loop_no_idx'),
            ('for i, item in enumerate(item for item in data if item > 1):', 'loop_new_idx'),
            ('any(item > 1 for item in data)', 'any'),
            ('if any(item > 1 for item in data):', 'if_any'),
        ]:
            with self.subTest(code=code):
                result = self.parse_generated_code(code)
                self.assertIsNotNone(result)
                self.assertEqual(result['action'], action)
                self.assertTrue(result.get('is_predicate'))
                self.assertIsNone(result.get('is_whole_list'))


class TestWholeListGrammarMatchesGeneration(unittest.TestCase):
    """The grammar and table_visualizer.generate_action must agree on whole-list
    code, since one writes the line and the other reads it back."""

    WHOLE_LIST_ACTIONS = ['loop_no_idx', 'loop_orig_idx', 'loop_new_idx',
                          'if_any', 'if_all', 'any', 'all']

    def setUp(self):
        from table_visualizer_grammar import generate_action as grammar_generate
        from table_visualizer_grammar import parse_generated_code
        self.grammar_generate = grammar_generate
        self.parse_generated_code = parse_generated_code
        self.ctx = {
            'source_expr': 'data', 'has_var': True, 'suggest_base': 'data',
            'is_whole_list': True, 'is_predicate': False, 'is_index': False,
            'is_slice': False, 'is_multi_index': False, 'is_first': False,
        }

    def test_grammar_generates_what_the_visualizer_generates(self):
        for action in self.WHOLE_LIST_ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(self.grammar_generate(action, self.ctx),
                                 generate_action(action, self.ctx))

    def test_generated_code_parses_back(self):
        for action in self.WHOLE_LIST_ACTIONS:
            with self.subTest(action=action):
                code = generate_action(action, self.ctx)[1]
                parsed = self.parse_generated_code(code)
                self.assertIsNotNone(parsed, f'{action} generated unparseable {code!r}')
                self.assertTrue(parsed.get('is_whole_list'))
                self.assertEqual(parsed['source_expr'], 'data')
                # loop_orig_idx and loop_new_idx generate identical whole-list
                # code, so parsing can only recover one of them.
                if action != 'loop_new_idx':
                    self.assertEqual(parsed['action'], action)

    def test_parse_find_indices_predicate(self):
        result = self.parse_generated_code('[i for i, item in enumerate(data) if item > 100]')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'find_indices')

    def test_parse_nonmatching_returns_none(self):
        result = self.parse_generated_code('print("hello")')
        self.assertIsNone(result)

    def test_parse_assignment_form(self):
        from table_visualizer_grammar import parse_generated_code_or_assignment
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
        from table_visualizer_grammar import parse_generated_code_or_assignment
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
        nc_vis = self._make_newcode_vis([('result', "len($['name'])")])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00$['name']"  # see TestFocusTracking
        original_columns = list(model['columns'])
        event = make_child_mouse_event("0\x00$['name']", 'X')
        new_model, commands = update(event, ('x', 'x'), model, lst, get_vis)

        self.assertEqual(commands, [], "NewCode tuple should not propagate as a command")
        self.assertIn("len($['name'])", new_model['columns'],
                       "NewCode expr should be added as a new column")

    def test_child_newcode_tuple_not_inserted_to_buffer(self):
        nc_vis = self._make_newcode_vis([('filtered', '[x for x in $]')])
        get_vis = self._get_vis_for(nc_vis)

        lst = ['hello', 'world']
        model = init_model(lst, get_vis)
        model['focused_child'] = '0\x00$'  # see TestFocusTracking
        event = make_child_mouse_event('0\x00$', 'X')
        _, commands = update(event, ('x', 'x'), model, lst, get_vis)

        for cmd in commands:
            self.assertFalse(
                isinstance(cmd, tuple) and len(cmd) in (2, 3),
                "No (suggest_var_name, expr) tuples should reach the command list")

    def test_child_copy_to_clipboard_passes_through(self):
        nc_vis = self._make_newcode_vis([CopyToClipboard(text='hello')])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00$['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00$['name']", 'X')
        _, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertEqual(commands[0].text, 'hello')

    def test_child_change_selected_text_passes_through(self):
        nc_vis = self._make_newcode_vis([ChangeSelectedText(expression='new_text')])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00$['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00$['name']", 'X')
        _, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1)
        self.assertIsInstance(commands[0], ChangeSelectedText)

    def test_child_receives_binder_as_var_and_exp(self):
        """The child gets a bound NAME for the cell value, not the column expr.

        The column's $ means the row; the child's $ means whatever it binds
        innermost. Handing over a name instead keeps the two apart, so the code
        the child generates is dollar-free and the column expression goes back in
        afterwards (see nest_generated_expr)."""
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
        model['focused_child'] = "0\x00$['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00$['name']", 'X')
        update(event, ('x', 'x'), model, lst, get_vis)

        self.assertEqual(captured['var_and_exp'], (None, CHILD_SOURCE_BINDER),
                         "Child should receive the cell binder as var_and_exp")

    def test_mixed_commands_only_newcode_intercepted(self):
        """When child returns both NewCode and CopyToClipboard, only NewCode is intercepted."""
        nc_vis = self._make_newcode_vis([
            ('result', "$['name'].upper()"),
            CopyToClipboard(text='copied'),
        ])
        get_vis = self._get_vis_for(nc_vis)

        lst = [{'name': 'Alice'}]
        model = init_model(lst, get_vis)
        model['focused_child'] = "0\x00$['name']"  # see TestFocusTracking
        event = make_child_mouse_event("0\x00$['name']", 'X')
        new_model, commands = update(event, None, model, lst, get_vis)

        self.assertEqual(len(commands), 1, "Only CopyToClipboard should pass through")
        self.assertIsInstance(commands[0], CopyToClipboard)
        self.assertIn("$['name'].upper()", new_model['columns'])


class TestColumnHeaderTooltips(unittest.TestCase):
    """The icon-only column header controls (drag handle, remove, add) must
    use the snc-tooltip system (data-tooltip) instead of the native title
    attribute, matching the string visualizer's tool toolbar pattern."""

    def test_column_menu_button_has_data_tooltip(self):
        lst = [{'name': 'Alice'}, {'name': 'Bob'}]
        model = init_model(lst, mock_get_visualizer)
        output = visualize(lst, model, mock_get_visualizer, None)
        m = re.search(
            r'<span snc-mouse-down="DropdownToggle\('
            + re.escape(f'dropdown_id={html.escape(repr(menu_id(model)))}')
            + r'\)"([^>]*?)>',
            output,
        )
        self.assertIsNotNone(m, "column menu trigger not found")
        attrs = m.group(1)
        self.assertIn('data-tooltip="Column actions"', attrs)
        self.assertNotIn('title="Column actions"', attrs,
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


_FINDALL_COL = "re.findall(r'[A-Z]{3}', ($), flags=re.M)"


class TestNestedSlotsConfig(unittest.TestCase):
    """The list config is nested: a list-producing column does not re-apply the
    type config to its cell sub-list (which would recurse forever); the sub-list
    uses the column's explicitly-nested config or a non-recursive default."""

    def _findall_key(self, row=0):
        return f"{row}\x00{_FINDALL_COL}"

    def test_list_of_str_with_list_column_does_not_recurse(self):
        slots = [{'expr': '$'}, {'expr': _FINDALL_COL}]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            # 'ABCdef' -> re.findall -> ['ABC'] -> ['ABC'] -> ... pre-fix recursion
            model = init_model(['ABCdef'], mock_get_visualizer)
        self.assertEqual(list(model['columns']), ['$', _FINDALL_COL])
        # The re.findall cell is a list[str]; with no nested config it must fall
        # back to the default single column, NOT re-read builtins.str's config.
        child = model['children'][self._findall_key()]
        self.assertEqual(list(child['columns']), ['$'])

    def test_explicit_nested_children_applies(self):
        slots = [
            {'expr': '$'},
            {'expr': _FINDALL_COL,
             'children': {'builtins.str': [{'expr': '$.lower()'}]}},
        ]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['ABCdef'], mock_get_visualizer)
        child = model['children'][self._findall_key()]
        self.assertEqual(list(child['columns']), ['$.lower()'])

    def test_root_model_stores_config_fields(self):
        slots = [{'expr': '$'}]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['x'], mock_get_visualizer)
        self.assertEqual(model['_config_root_type'], 'builtins.str')
        self.assertEqual(model['_config_root_dotfile'],
                         table_visualizer.COLUMN_DOTFILE_NAME)
        self.assertEqual(model['_config_path'], [])
        self.assertEqual(model['_slot_children'], {})

    def test_nested_child_carries_path_and_root(self):
        slots = [{'expr': _FINDALL_COL,
                  'children': {'builtins.str': [{'expr': '$'}]}}]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['ABCdef'], mock_get_visualizer)
        child = model['children'][self._findall_key()]
        self.assertEqual(child['_config_root_type'], 'builtins.str')
        self.assertEqual(child['_config_path'],
                         [(_FINDALL_COL, 'builtins.str')])

    def test_cyclic_list_is_depth_capped_not_recursion_error(self):
        a = []
        a.append(a)  # a == [a]; would recurse forever via auto-detected columns
        with patch('table_visualizer.load_columns_from_dotfile', return_value=None):
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


class TestNestedConfigIsOfferedBySignature(unittest.TestCase):
    """Whether a cell visualizer gets the nesting kwargs is read off its
    init_model signature -- no SUPPORTS_NESTED_CONFIG constant to also set."""

    class RecordingNestedVis:
        """Asks for the nesting kwargs by naming them, and nothing else."""
        def __init__(self):
            self.calls = []
        def can_visualize(self, value):
            return True
        def init_model(self, value, get_visualizer=None, eval_in_scope=None,
                       var_and_exp=None, slots_config=None, config_root_type=None,
                       config_root_dotfile=None, config_path=None):
            self.calls.append({'slots_config': slots_config,
                               'config_root_type': config_root_type,
                               'config_root_dotfile': config_root_dotfile,
                               'config_path': config_path})
            return {'handledKeys': []}
        def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
            return f'<span>{html.escape(repr(value))}</span>'
        def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
            return (model, [])

    class PlainVis:
        """An old-style visualizer that knows nothing of nested config."""
        def can_visualize(self, value):
            return True
        def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
            return {'handledKeys': []}
        def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None, max_height=None, small=False, var_and_exp=None):
            return f'<span>{html.escape(repr(value))}</span>'
        def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
            return (model, [])

    def _get_visualizer_for(self, cell_vis):
        def get_visualizer(value):
            return _mock_list_vis if isinstance(value, list) else cell_vis
        return get_visualizer

    def test_child_naming_the_params_receives_the_nested_config(self):
        cell_vis = self.RecordingNestedVis()
        slots = [{'expr': '$', 'children': {'builtins.str': [{'expr': '$.lower()'}]}}]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            init_model(['ABC'], self._get_visualizer_for(cell_vis))
        self.assertEqual(len(cell_vis.calls), 1)
        call = cell_vis.calls[0]
        self.assertEqual(call['slots_config'], [{'expr': '$.lower()'}])
        self.assertEqual(call['config_root_type'], 'builtins.str')
        self.assertEqual(call['config_root_dotfile'],
                         table_visualizer.COLUMN_DOTFILE_NAME)
        self.assertEqual(call['config_path'], [('$', 'builtins.str')])

    def test_child_not_naming_the_params_is_not_handed_them(self):
        # Would TypeError if the nesting kwargs were passed regardless.
        slots = [{'expr': '$', 'children': {'builtins.str': [{'expr': '$.lower()'}]}}]
        with patch('table_visualizer.load_columns_from_dotfile', return_value=slots):
            model = init_model(['ABC'], self._get_visualizer_for(self.PlainVis()))
        self.assertEqual(model['children'][f'0\x00$'], {'handledKeys': []})


class TestNestedSlotsSave(unittest.TestCase):
    """Column edits persist via the path-scoped writer using the model's path."""

    def test_add_column_saves_with_path_scoped_signature(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['adding_column'] = True
        event = make_column_mouse_event(repr(ColumnSelect(name="$['x']")))
        with patch('table_visualizer.save_columns_to_dotfile') as mock_save:
            update(event, None, model, lst, mock_get_visualizer)
        mock_save.assert_called_once()
        args = mock_save.call_args.args
        # New signature: (root_type, path, exprs, [dotfile])
        self.assertEqual(args[0], 'builtins.dict')
        self.assertEqual(args[1], [])
        self.assertIn("$['x']", args[2])


class TestNestedStringCellProducesUsableColumn(unittest.TestCase):
    """A real string visualizer inside a cell speaks its own scope: $ is the
    match, $$ the cell's string. The column it hands back must be in the LIST's
    scope, where $ is the row -- and must evaluate for every row.
    """

    def _drive(self, rows, column, events, search="r'foo'"):
        """Run *events* through the string visualizer in row 0's cell of a list
        whose single column is *column*. Returns (model, commands).

        *search* is what the cell is searching for -- a regex by default, which
        is what clicking a character writes; a literal for the cases where the
        difference matters, since only the regex spelling generates `re.` code.
        """
        import string_visualizer
        eval_in_scope = lambda code: eval(code, {'re': re, 'rows': rows})
        get_vis = lambda v: string_visualizer if isinstance(v, str) else table_visualizer

        with patch('table_visualizer.load_columns_from_dotfile', return_value=[column]):
            model = init_model(rows, get_vis, eval_in_scope=eval_in_scope,
                               var_and_exp=('rows', 'rows'))
        key = f'0{CELL_KEY_SEP}{column}'
        model['focused_child'] = key
        cell = model['children'][key]
        cell['search'] = search
        cell['replace_visible'] = True
        cell['tool'] = 'pick'

        commands = []
        for py_ev in events:
            event = {'pythonEventStr': repr(ChildEvent(child_key=key, py_ev_str=repr(py_ev))),
                     'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1, 'detail': 1}}
            model, cmds = update(event, ('rows', 'rows'), model, rows, get_vis,
                                 eval_in_scope=eval_in_scope)
            commands += cmds
        return model, commands, eval_in_scope

    def test_pick_then_action_yields_a_column_that_evaluates_for_every_row(self):
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        model, _cmds, eval_in_scope = self._drive(rows, '$', [
            string_visualizer.SegmentToggle(segment_id='prefix'),
            string_visualizer.ActionButtonClick(action='find_or_map', copy=False),
        ])
        added = [c for c in model['columns'] if c != '$']
        self.assertEqual(len(added), 1, f"expected one new column, got {model['columns']}")
        col = added[0]
        values = [eval_in_scope(replace_dollars_in_py_exp(col, [f'rows[{i}]']))
                  for i in range(len(rows))]
        self.assertEqual(values, [[''], ['baz ']])

    def test_cell_chips_drag_out_the_concrete_access_path(self):
        """Chips are dragged into the editor, so they must name the cell
        concretely -- neither the $$ the replace box shows nor a placeholder."""
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        model, _cmds, eval_in_scope = self._drive(rows, '$', [
            string_visualizer.SegmentToggle(segment_id='suffix'),
        ])
        get_vis = lambda v: string_visualizer if isinstance(v, str) else table_visualizer
        rendered = visualize(rows, model, get_vis, eval_in_scope)
        chips = {expr for handle in exps_in(rendered) for expr in handle}
        placeholder = [c for c in chips if c.startswith('str[')]
        self.assertEqual(placeholder, [],
                         'cell chips fell back to the literal name "str"')
        self.assertTrue([c for c in chips if 'rows[0]' in c and '.end()' in c],
                        f'no cell chip names the concrete path; got {sorted(chips)}')

    def test_a_cell_never_links(self):
        """A cell's code becomes a column, not a line the visualizer owns.

        There is no chain icon on a cell to break a link with, and a linked cell
        would rewrite an editor line on every mouse event -- so a nested
        visualizer neither auto-links nor emits ChangeSelectedText."""
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        model, commands, _eval = self._drive(rows, '$', [
            string_visualizer.SegmentToggle(segment_id='prefix'),
            string_visualizer.SegmentToggle(segment_id='suffix'),
            string_visualizer.ActionButtonClick(action='find_or_map', copy=False),
            string_visualizer.SegmentToggle(segment_id='start'),
        ])
        self.assertEqual([c for c in commands if isinstance(c, ChangeSelectedText)], [],
                         'a cell must not rewrite editor text')
        cell = model['children'][f'0{CELL_KEY_SEP}$']
        self.assertIsNone(cell.get('linked_action'))
        # The one explicit action click is the only thing that adds a column.
        self.assertEqual(len([c for c in model['columns'] if c != '$']), 1)

    def test_copy_from_a_cell_yields_pasteable_code(self):
        """Clipboard text is pasted into the editor as-is, so unlike a stored
        column it must name the cell concretely rather than relative to a row."""
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        # 'foo bar' matching r'foo': prefix is '', suffix is ' bar'.
        for action, segment, expected in (('find_or_map', 'prefix', ['']),
                                          ('if_any', 'suffix', True)):
            with self.subTest(action=action):
                _model, commands, eval_in_scope = self._drive(rows, '$', [
                    string_visualizer.SegmentToggle(segment_id=segment),
                    string_visualizer.ActionButtonClick(action=action, copy=True),
                ])
                # The child's own command class travels out unwrapped.
                copies = [c for c in commands
                          if isinstance(c, string_visualizer.CopyToClipboard)]
                self.assertEqual(len(copies), 1, f'expected one copy, got {commands}')
                self.assertEqual(eval_in_scope(copies[0].text), expected)

    def test_copy_of_a_statement_from_a_cell_is_pasteable(self):
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        _model, commands, eval_in_scope = self._drive(rows, '$', [
            string_visualizer.SegmentToggle(segment_id='prefix'),
            string_visualizer.ActionButtonClick(action='loop', copy=True),
        ])
        text = [c for c in commands
                if isinstance(c, string_visualizer.CopyToClipboard)][0].text
        self.assertNotIn(CHILD_SOURCE_BINDER, text)
        ast.parse(text)  # raises if the pasted block wouldn't compile

    def test_the_column_a_string_op_leaves_carries_its_import(self):
        """A nested action writes its code into a column of this table rather
        than into the file, so the declaration it made travels no further. The
        column still reaches the editor everywhere the table hands it out --
        the header, the cell, the row handle -- and the file it lands in has no
        reason to have an `import re` already.
        """
        import string_visualizer
        rows = ['foo bar', 'baz foo']
        model, _cmds, _eval = self._drive(rows, '$', [
            string_visualizer.ActionButtonClick(action='delete', copy=False),
        ])
        get_vis = lambda v: string_visualizer if isinstance(v, str) else table_visualizer
        rendered = visualize(rows, model, get_vis,
                             lambda code: eval(code, {'re': re, 'rows': rows}))
        offered = [entry for handle in handles_in(rendered) for entry in handle
                   if 're.' in entry['expr']]
        self.assertTrue(offered, 'no handle offers the column the op wrote')
        for entry in offered:
            with self.subTest(expr=entry['expr']):
                scope = {'rows': rows}  # a file with no import in it
                for line in entry.get('imports', ()):
                    exec(line, scope)
                exec(with_pass_body(entry['expr']), scope)

    def test_the_action_asks_for_the_import_even_with_no_line_to_show_for_it(self):
        """A nested action writes a column rather than a line, but the column
        is code the user's program has to be able to run: it is evaluated in
        their scope on every run, so without the import there is nothing for
        the column to show. The action asks for it the way any other would."""
        import string_visualizer
        rows = ['a,b,c', 'd,e,f']
        model, commands, _eval = self._drive(rows, '$', [
            string_visualizer.ActionButtonClick(action='split', copy=False),
        ], search="r','")
        self.assertIn("re.split(r',', ($), flags=re.M)", model['columns'])
        self.assertEqual([c for c in commands if isinstance(c, AddImports)],
                         [AddImports(imports=('import re',))])

    def test_an_action_that_needs_nothing_asks_for_nothing(self):
        import string_visualizer
        rows = ['a,b,c', 'd,e,f']
        model, commands, _eval = self._drive(rows, '$', [
            string_visualizer.ActionButtonClick(action='split', copy=False),
        ], search="','")
        self.assertIn("($).split(',')", model['columns'])
        self.assertEqual([c for c in commands if isinstance(c, AddImports)], [])

    def test_a_line_written_over_that_column_carries_it_too(self):
        """Sorting by the column writes a line of the file, and the column's
        code goes into it -- so the line needs what the column needs."""
        import string_visualizer
        from table_visualizer import SortCodeClick
        rows = ['foo bar', 'baz foo']
        model, _cmds, _eval = self._drive(rows, '$', [
            string_visualizer.ActionButtonClick(action='delete', copy=False),
        ])
        col = [c for c in model['columns'] if c != '$'][0]
        event = make_column_mouse_event(
            repr(SortCodeClick(col=col, direction='asc')))
        _model, cmds = update(event, ('rows', 'rows'), model, rows,
                              lambda v: string_visualizer if isinstance(v, str) else table_visualizer,
                              eval_in_scope=lambda code: eval(code, {'re': re, 'rows': rows}))
        written = [c for c in cmds if isinstance(c, tuple)]
        self.assertEqual(len(written), 1, f'expected one line, got {cmds}')
        self.assertIn('re.', written[0][1])
        self.assertEqual(written[0][2:], (('import re',),))

    def test_column_is_row_generic_for_a_non_trivial_column(self):
        import string_visualizer

        class Row:
            def __init__(self, name):
                self.name = name

        rows = [Row('foo bar'), Row('baz foo')]
        model, _cmds, eval_in_scope = self._drive(rows, '$.name', [
            string_visualizer.SegmentToggle(segment_id='prefix'),
            string_visualizer.ActionButtonClick(action='find_or_map', copy=False),
        ])
        added = [c for c in model['columns'] if c != '$.name']
        self.assertEqual(len(added), 1, f"expected one new column, got {model['columns']}")
        col = added[0]
        values = [eval_in_scope(replace_dollars_in_py_exp(col, [f'rows[{i}]']))
                  for i in range(len(rows))]
        self.assertEqual(values, [[''], ['baz ']])


# === Pick tool ===

from table_visualizer import (
    ToolSelect, PickToggle,
    _pick_region_ids, _pick_region_expr, _build_pick_expr, _pick_needs_index,
    _pick_edge_class, _pick_is_array, pick_filter_expr, PICK_IDX_COLUMN,
)


def make_tool_select_event(tool):
    """Create a ToolSelect event."""
    return {
        'pythonEventStr': repr(ToolSelect(tool=tool)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


def make_pick_toggle_event(region_id):
    """Create a PickToggle event."""
    return {
        'pythonEventStr': repr(PickToggle(region_id=region_id)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


# The worked example from the plan: a match on row 2 of 5, two columns.
PICK_STRS = ['abc', 'efg', 'Asdfasdz', 'sdfd', '']
PICK_COLUMNS = ['$', 'len($)']
PICK_SEARCH = 'len($) > 4'


def pick_eval(code):
    return eval(code, {'strs': list(PICK_STRS)})


def make_pick_model(picked=None, columns=None, search=PICK_SEARCH, tool='pick'):
    """A table model parked in pick mode over PICK_STRS."""
    model = init_model(PICK_STRS, mock_get_visualizer, eval_in_scope=pick_eval,
                       var_and_exp=('strs', 'strs'))
    model['columns'] = list(PICK_COLUMNS if columns is None else columns)
    model['search'] = search
    model['tool'] = tool
    model['first_match'] = True
    model['picked'] = list(picked) if picked else None
    model['pick_expr'] = _build_pick_expr(model, 'strs')
    return model


class TestPickToolToolbar(unittest.TestCase):
    """The Normal/Pick toolbar in the upper-right corner."""

    def test_renders_both_tools(self):
        model = make_pick_model(tool='normal')
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        self.assertEqual(re.findall(r'data-tool="(\w+)"', output),
                         ['normal', 'pick'])

    def test_active_tool_marked(self):
        model = make_pick_model()
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        self.assertIn('class="tool-button active" data-tool="pick"', output)

    def test_hidden_when_small(self):
        model = make_pick_model()
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval,
                           small=True)
        self.assertNotIn('tool-toolbar', output)

    def test_pick_dimmed_without_search(self):
        model = make_pick_model(search=None, tool='normal')
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        pick_btn = re.search(r'<span class="([^"]*)" data-tool="pick"', output)
        self.assertIn('dimmed', pick_btn.group(1))
        # Dimmed means click-inert, so no handler at all.
        self.assertNotIn('ToolSelect(tool=\'pick\')', html.unescape(output))

    def test_container_carries_tool_class(self):
        model = make_pick_model()
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        self.assertIn('pick-tool-selected', output)

    def test_selecting_pick_forces_first_match(self):
        model = make_pick_model(tool='normal')
        model['first_match'] = False
        new_model, _ = update(make_tool_select_event('pick'), ('strs', 'strs'),
                              model, PICK_STRS, mock_get_visualizer, pick_eval)
        self.assertEqual(new_model['tool'], 'pick')
        self.assertTrue(new_model['first_match'])

    def test_leaving_pick_clears_selection(self):
        model = make_pick_model(picked=['match_col_1'])
        self.assertIsNotNone(model['pick_expr'])
        new_model, _ = update(make_tool_select_event('normal'), ('strs', 'strs'),
                              model, PICK_STRS, mock_get_visualizer, pick_eval)
        self.assertEqual(new_model['tool'], 'normal')
        self.assertIsNone(new_model['picked'])
        self.assertIsNone(new_model['pick_expr'])

    def test_escape_leaves_pick_mode(self):
        model = make_pick_model(picked=['match_col_1'])
        new_model, _ = update(make_search_key_event('Escape'), ('strs', 'strs'),
                              model, PICK_STRS, mock_get_visualizer, pick_eval)
        self.assertEqual(new_model['tool'], 'normal')
        self.assertIsNone(new_model['pick_expr'])

    def test_first_match_toggle_inert_in_pick_mode(self):
        model = make_pick_model()
        new_model, _ = update(make_first_match_toggle_event(), ('strs', 'strs'),
                              model, PICK_STRS, mock_get_visualizer, pick_eval)
        self.assertTrue(new_model['first_match'])

    def test_delete_disabled_in_pick_mode(self):
        output = visualize(PICK_STRS, make_pick_model(), mock_get_visualizer,
                           pick_eval)
        delete_btn = re.search(
            r'<span class="([^"]*)" snc-mouse-down="ActionButtonClick\(action=&#x27;delete',
            output)
        self.assertIn('dimmed', delete_btn.group(1))


class TestPickRegions(unittest.TestCase):
    """The 3 x (1 + columns) grid of pickable regions."""

    def test_region_ids_for_worked_example(self):
        self.assertEqual(
            _pick_region_ids(PICK_COLUMNS, 2, 5),
            ['pre_idx', 'match_idx', 'post_idx',
             'pre_col_0', 'match_col_0', 'post_col_0',
             'pre_col_1', 'match_col_1', 'post_col_1'])

    def test_no_pre_band_when_match_is_first_row(self):
        ids = _pick_region_ids(PICK_COLUMNS, 0, 5)
        self.assertEqual([i for i in ids if i.startswith('pre_')], [])
        self.assertEqual(len(ids), 6)

    def test_no_post_band_when_match_is_last_row(self):
        ids = _pick_region_ids(PICK_COLUMNS, 4, 5)
        self.assertEqual([i for i in ids if i.startswith('post_')], [])
        self.assertEqual(len(ids), 6)

    def test_single_row_list_has_only_match_band(self):
        self.assertEqual(_pick_region_ids(['$'], 0, 1),
                         ['match_idx', 'match_col_0'])

    def test_region_expressions(self):
        got = {rid: _pick_region_expr(rid, PICK_COLUMNS, 'strs')
               for rid in _pick_region_ids(PICK_COLUMNS, 2, 5)}
        self.assertEqual(got, {
            'pre_idx': 'list(range(i))',
            'match_idx': 'i',
            'post_idx': 'list(range(i + 1, len(strs)))',
            # The identity column is the sublist itself -- no comprehension.
            'pre_col_0': 'strs[:i]',
            'match_col_0': '$',
            'post_col_0': 'strs[i + 1:]',
            'pre_col_1': '[len(x) for x in strs[:i]]',
            'match_col_1': 'len($)',
            'post_col_1': '[len(x) for x in strs[i + 1:]]',
        })

    def test_edge_classes_across_a_multi_row_band(self):
        # Match on row 3 of 6: the pre band spans rows 0-2.
        got = [_pick_edge_class(row, 3, 6) for row in range(6)]
        self.assertEqual(got, [
            'pick-region-first', 'pick-region-mid', 'pick-region-last',
            'pick-region-only',
            'pick-region-first', 'pick-region-last',
        ])

    def test_overlay_rendered_in_every_cell(self):
        output = visualize(PICK_STRS, make_pick_model(), mock_get_visualizer,
                           pick_eval)
        # 5 rows x (row index + 2 columns).
        self.assertEqual(output.count('class="pick-region'), 15)

    def test_row_striping_replaced_by_bands(self):
        output = visualize(PICK_STRS, make_pick_model(), mock_get_visualizer,
                           pick_eval)
        # Matched on the full attribute: 'pick-row-match' contains 'row-match'.
        self.assertNotIn('class="row-match"', output)
        self.assertNotIn('class="row-dim"', output)
        self.assertIn('pick-row-pre', output)
        self.assertIn('pick-row-match', output)
        self.assertIn('pick-row-post', output)

    def test_selected_region_marked(self):
        output = visualize(PICK_STRS, make_pick_model(picked=['match_col_1']),
                           mock_get_visualizer, pick_eval)
        selected = re.findall(r'class="(pick-region[^"]*selected[^"]*)"', output)
        self.assertEqual(len(selected), 1)

    def test_regions_carry_self_contained_expressions(self):
        output = visualize(PICK_STRS, make_pick_model(), mock_get_visualizer,
                           pick_eval)
        exprs = [expr for handle in exps_in(output) for expr in handle]
        # Every region offers a draggable expression that stands on its own.
        pre_col1 = ('next(([len(x) for x in strs[:i]] for i, item in '
                    'enumerate(strs) if len(item) > 4), None)')
        self.assertIn(pre_col1, exprs)
        self.assertEqual(pick_eval(pre_col1), [3, 3])

    def test_no_regions_in_small_mode(self):
        output = visualize(PICK_STRS, make_pick_model(), mock_get_visualizer,
                           pick_eval, small=True)
        self.assertNotIn('pick-region', output)

    def test_no_regions_without_a_search(self):
        model = make_pick_model(search=None)
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        self.assertNotIn('pick-region', output)

    def test_stale_region_ids_are_dropped(self):
        # col_5 doesn't exist; the surviving pick still assembles.
        model = make_pick_model(picked=['match_col_5', 'match_col_1'])
        self.assertEqual(model['pick_expr'], 'len($)')


class TestPickExpr(unittest.TestCase):
    """Assembling picked regions into one expression."""

    def _expr(self, picked):
        return make_pick_model(picked=picked)['pick_expr']

    def test_nothing_picked(self):
        self.assertIsNone(self._expr([]))

    def test_single_region_is_bare(self):
        self.assertEqual(self._expr(['match_col_1']), 'len($)')

    def test_multiple_regions_become_a_tuple(self):
        self.assertEqual(self._expr(['match_idx', 'match_col_1']), '(i, len($))')

    def test_canonical_order_regardless_of_click_order(self):
        self.assertEqual(self._expr(['match_col_1', 'match_idx']),
                         self._expr(['match_idx', 'match_col_1']))

    def test_all_three_bands_collapse_to_whole_column(self):
        self.assertEqual(
            self._expr(['pre_col_1', 'match_col_1', 'post_col_1']),
            '[len(x) for x in strs]')

    def test_pre_plus_match_collapses_to_head(self):
        self.assertEqual(self._expr(['pre_col_1', 'match_col_1']),
                         '[len(x) for x in strs[:i + 1]]')

    def test_match_plus_post_collapses_to_tail(self):
        self.assertEqual(self._expr(['match_col_1', 'post_col_1']),
                         '[len(x) for x in strs[i:]]')

    def test_pre_plus_post_has_a_hole_so_does_not_collapse(self):
        self.assertEqual(self._expr(['pre_col_1', 'post_col_1']),
                         '([len(x) for x in strs[:i]], '
                         '[len(x) for x in strs[i + 1:]])')

    def test_index_column_collapses_too(self):
        self.assertEqual(self._expr(['pre_idx', 'match_idx', 'post_idx']),
                         'list(range(len(strs)))')
        self.assertEqual(self._expr(['pre_idx', 'match_idx']),
                         'list(range(i + 1))')
        self.assertEqual(self._expr(['match_idx', 'post_idx']),
                         'list(range(i, len(strs)))')

    def test_identity_column_collapses_without_a_comprehension(self):
        self.assertEqual(self._expr(['pre_col_0', 'match_col_0', 'post_col_0']),
                         'strs')

    def test_collapses_are_per_column(self):
        self.assertEqual(
            self._expr(['pre_col_0', 'match_col_0', 'post_col_0', 'match_idx']),
            '(i, strs)')

    def test_needs_index(self):
        self.assertFalse(_pick_needs_index('len($)'))
        self.assertFalse(_pick_needs_index('$'))
        self.assertTrue(_pick_needs_index('i'))
        self.assertTrue(_pick_needs_index('strs[:i]'))
        self.assertTrue(_pick_needs_index('(i, len($))'))


class TestPickGeneratedCode(unittest.TestCase):
    """The line of code a pick produces, and what it evaluates to."""

    def _generate(self, picked):
        model = make_pick_model(picked=picked)
        ctx = _get_search_context(model, ('strs', 'strs'), eval_in_scope=pick_eval)
        return generate_action('filter', ctx)[1]

    def test_scalar_pick_needs_no_enumerate(self):
        code = self._generate(['match_col_1'])
        self.assertEqual(
            code, 'next((len(item) for item in strs if len(item) > 4), None)')
        self.assertEqual(pick_eval(code), 8)

    def test_index_pick_enumerates(self):
        code = self._generate(['match_idx'])
        self.assertEqual(
            code,
            'next((i for i, item in enumerate(strs) if len(item) > 4), None)')
        self.assertEqual(pick_eval(code), 2)

    def test_tuple_pick(self):
        code = self._generate(['match_idx', 'match_col_1'])
        self.assertEqual(pick_eval(code), (2, 8))

    def test_band_pick(self):
        code = self._generate(['pre_col_0', 'match_col_0'])
        self.assertEqual(
            code,
            'next((strs[:i + 1] for i, item in enumerate(strs) '
            'if len(item) > 4), None)')
        self.assertEqual(pick_eval(code), ['abc', 'efg', 'Asdfasdz'])

    def test_no_pick_generates_the_plain_filter(self):
        self.assertEqual(
            self._generate([]),
            'next((item for item in strs if len(item) > 4), None)')

    def test_picking_the_whole_row_degenerates_to_the_plain_filter(self):
        # $ IS the item, so this is the ordinary first-match filter.
        self.assertEqual(
            self._generate(['match_col_0']),
            'next((item for item in strs if len(item) > 4), None)')

    def test_hand_written_and_grammar_generation_agree(self):
        from table_visualizer_grammar import generate_action as grammar_generate
        for picked in [['match_col_1'], ['match_idx'], ['pre_col_0', 'match_col_0'],
                       ['match_idx', 'match_col_1'], ['pre_col_1', 'post_col_1']]:
            with self.subTest(picked=picked):
                model = make_pick_model(picked=picked)
                ctx = _get_search_context(model, ('strs', 'strs'),
                                          eval_in_scope=pick_eval)
                self.assertEqual(grammar_generate('filter', ctx)[1],
                                 generate_action('filter', ctx)[1])


class TestPickPreview(unittest.TestCase):
    """The preview line under the search box."""

    def _preview(self, model):
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        m = re.search(r'pick-preview-value">([^<]*)<', output)
        return m.group(1) if m else None

    def test_shows_the_picked_value(self):
        self.assertEqual(self._preview(make_pick_model(picked=['match_col_1'])),
                         '8')

    def test_shows_a_list_for_a_band_pick(self):
        self.assertEqual(
            self._preview(make_pick_model(picked=['pre_col_1'])), '[3, 3]')

    def test_absent_when_nothing_picked(self):
        self.assertIsNone(self._preview(make_pick_model()))

    def test_absent_outside_pick_mode(self):
        model = make_pick_model(picked=['match_col_1'])
        model['tool'] = 'normal'
        self.assertIsNone(self._preview(model))

    def test_reports_the_error_for_a_broken_column(self):
        model = make_pick_model(picked=['match_col_1'],
                                columns=['$', '$.nope'])
        self.assertIn('attribute', (self._preview(model) or '').lower())


class TestPickUpdateFlow(unittest.TestCase):
    """PickToggle through update(), and the code it links."""

    def _send(self, model, event):
        return update(event, ('strs', 'strs'), model, PICK_STRS,
                      mock_get_visualizer, pick_eval)

    def test_toggle_on_and_off(self):
        model = make_pick_model()
        model, _ = self._send(model, make_pick_toggle_event('match_col_1'))
        self.assertEqual(model['picked'], ['match_col_1'])
        self.assertEqual(model['pick_expr'], 'len($)')
        model, _ = self._send(model, make_pick_toggle_event('match_col_1'))
        self.assertIsNone(model['picked'])
        self.assertIsNone(model['pick_expr'])

    def test_toggle_emits_linked_code(self):
        model = make_pick_model()
        model, cmds = self._send(model, make_pick_toggle_event('match_col_1'))
        exprs = [c.expression for c in cmds if isinstance(c, ChangeSelectedText)]
        exprs += [c[1] for c in cmds if isinstance(c, tuple)]
        self.assertEqual(
            exprs, ['next((len(item) for item in strs if len(item) > 4), None)'])

    def test_toggle_ignored_outside_pick_mode(self):
        model = make_pick_model(tool='normal')
        model, _ = self._send(model, make_pick_toggle_event('match_col_1'))
        self.assertIsNone(model['picked'])

    def test_clearing_the_search_leaves_pick_mode(self):
        model = make_pick_model(picked=['match_col_1'])
        model, _ = self._send(model, make_search_input_event(''))
        self.assertEqual(model['tool'], 'normal')
        self.assertIsNone(model['pick_expr'])

    def test_table_keeps_its_borders_when_pick_cannot_apply(self):
        # tool='pick' with no search must not strip the cell borders.
        model = make_pick_model(search=None)
        output = visualize(PICK_STRS, model, mock_get_visualizer, pick_eval)
        self.assertIn('normal-tool-selected', output)
        self.assertNotIn('pick-tool-selected', output)


class TestPickIsArray(unittest.TestCase):
    """A pick is an array when it covers one contiguous run of rows in one column."""

    def _is_array(self, picked, columns=None):
        return _pick_is_array(make_pick_model(picked=picked, columns=columns))

    def test_contiguous_runs_of_one_column_are_arrays(self):
        for picked in [['pre_col_1'], ['post_col_1'],
                       ['pre_col_1', 'match_col_1'],
                       ['match_col_1', 'post_col_1'],
                       ['pre_col_1', 'match_col_1', 'post_col_1'],
                       ['pre_idx'], ['pre_idx', 'match_idx']]:
            with self.subTest(picked=picked):
                self.assertTrue(self._is_array(picked))

    def test_lone_match_row_is_a_scalar(self):
        self.assertFalse(self._is_array(['match_col_1']))
        self.assertFalse(self._is_array(['match_idx']))

    def test_pre_plus_post_has_a_hole(self):
        self.assertFalse(self._is_array(['pre_col_1', 'post_col_1']))

    def test_two_columns_make_a_tuple(self):
        self.assertFalse(self._is_array(['match_idx', 'match_col_1']))
        self.assertFalse(self._is_array(['pre_col_0', 'pre_col_1']))

    def test_nothing_picked(self):
        self.assertFalse(self._is_array([]))

    def test_false_outside_pick_mode(self):
        model = make_pick_model(picked=['pre_col_1', 'match_col_1'], tool='normal')
        self.assertFalse(_pick_is_array(model))

    def test_stale_column_ids_do_not_count_as_a_second_column(self):
        # col_9 is gone, so this is still a single-column contiguous run.
        self.assertTrue(self._is_array(['pre_col_1', 'match_col_1', 'match_col_9']))


class TestPickArrayActions(unittest.TestCase):
    """Loop and Join apply to an array pick; Any/All and Find Indices do not."""

    def _trigger_class(self, output, label):
        pos = output.find(f'>{label}<')
        start = output.rfind('<span class="snc-dropdown-trigger', 0, pos)
        end = output.find('"', start + len('<span class="'))
        return output[start + len('<span class="'):end]

    def _button_class(self, output, action):
        pat = (r'<span class="([^"]*)" snc-mouse-down="ActionButtonClick\(action='
               r'&#x27;' + action + r'&#x27;')
        return re.search(pat, output).group(1)

    def _render(self, picked, tool='pick'):
        return visualize(PICK_STRS, make_pick_model(picked=picked, tool=tool),
                         mock_get_visualizer, pick_eval)

    def test_loop_and_join_enabled_for_an_array_pick(self):
        out = self._render(['pre_col_1', 'match_col_1'])
        self.assertNotIn('dimmed', self._trigger_class(out, 'Loop'))
        self.assertNotIn('dimmed', self._trigger_class(out, 'Join'))

    def test_loop_and_join_disabled_for_a_scalar_pick(self):
        out = self._render(['match_col_1'])
        self.assertIn('dimmed', self._trigger_class(out, 'Loop'))
        self.assertIn('dimmed', self._trigger_class(out, 'Join'))

    def test_loop_and_join_disabled_for_a_tuple_pick(self):
        out = self._render(['pre_col_1', 'post_col_1'])
        self.assertIn('dimmed', self._trigger_class(out, 'Loop'))
        self.assertIn('dimmed', self._trigger_class(out, 'Join'))

    def test_original_indices_row_disabled_for_an_array_pick(self):
        # A projection of a row range has no meaningful original index.
        out = self._render(['pre_col_1', 'match_col_1'])
        row = re.search(r'<div class="([^"]*)"[^>]*>'
                        r'<span[^>]*>Original indices<', out)
        self.assertIn('dimmed', row.group(1))

    def test_any_all_disabled_in_pick_mode(self):
        out = self._render(['pre_col_1', 'match_col_1'])
        self.assertIn('dimmed', self._trigger_class(out, 'Any/All'))

    def test_find_indices_disabled_in_pick_mode(self):
        out = self._render(['pre_col_1', 'match_col_1'])
        self.assertIn('dimmed', self._button_class(out, 'find_indices'))

    def test_any_all_and_find_indices_available_outside_pick_mode(self):
        out = self._render(None, tool='normal')
        self.assertNotIn('dimmed', self._trigger_class(out, 'Any/All'))
        self.assertNotIn('dimmed', self._button_class(out, 'find_indices'))


class TestPickArrayGeneratedCode(unittest.TestCase):
    """Loop and Join run over the picked array itself."""

    def _ctx(self, picked, **extra):
        model = make_pick_model(picked=picked)
        ctx = _get_search_context(model, ('strs', 'strs'), eval_in_scope=pick_eval)
        ctx.update(extra)
        return ctx

    def test_loop_no_idx_iterates_the_picked_array(self):
        code = generate_action('loop_no_idx', self._ctx(['pre_col_1', 'match_col_1']))[1]
        self.assertEqual(
            code,
            'for item in next(([len(x) for x in strs[:i + 1]] '
            'for i, item in enumerate(strs) if len(item) > 4), None):')
        seen = []
        exec(code + '\n    seen.append(item)',
             {'strs': list(PICK_STRS), 'seen': seen})
        self.assertEqual(seen, [3, 3, 8])

    def test_loop_new_idx_enumerates_the_picked_array(self):
        code = generate_action('loop_new_idx', self._ctx(['post_col_0']))[1]
        seen = []
        exec(code + '\n    seen.append((i, item))',
             {'strs': list(PICK_STRS), 'seen': seen})
        self.assertEqual(seen, [(0, 'sdfd'), (1, '')])

    def test_join_joins_the_picked_array(self):
        code = generate_action(
            'join', self._ctx(['pre_col_1', 'match_col_1'], join_separator="'|'"))[1]
        self.assertEqual(eval(code, {'strs': list(PICK_STRS)}), '3|3|8')

    def test_loop_orig_idx_refused_for_an_array_pick(self):
        self.assertIsNone(
            generate_action('loop_orig_idx', self._ctx(['pre_col_1', 'match_col_1'])))

    def test_scalar_pick_falls_back_to_the_match_set(self):
        # Loop is dimmed for a scalar pick, so it keeps the plain predicate form
        # rather than trying to iterate a scalar.
        code = generate_action('loop_no_idx', self._ctx(['match_col_1']))[1]
        self.assertEqual(code, 'for item in (item for item in strs if len(item) > 4):')

    def test_tuple_pick_falls_back_to_the_match_set(self):
        code = generate_action('join', self._ctx(['pre_col_1', 'post_col_1'],
                                                 join_separator="'|'"))[1]
        self.assertEqual(code, "'|'.join(str(item) for item in strs if len(item) > 4)")

    def test_filter_and_the_loop_wrapper_agree(self):
        ctx = self._ctx(['pre_col_1', 'match_col_1'])
        self.assertEqual(generate_action('filter', ctx)[1], pick_filter_expr(ctx))


class TestListGrammarPick(_ListActionTestBase):
    """Roundtrip tests for picked filter lines."""

    def test_roundtrip_pick_no_index(self):
        self._roundtrip('filter', {
            'is_predicate': True, 'is_first': True,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'len(item) > 4', 'source_expr': 'strs',
            'pick_expr': 'len(item)', 'needs_index': False,
        })

    def test_roundtrip_pick_with_index(self):
        self._roundtrip('filter', {
            'is_predicate': True, 'is_first': True,
            'is_index': False, 'is_slice': False, 'is_multi_index': False,
            'predicate_expr': 'len(item) > 4', 'source_expr': 'strs',
            'pick_expr': 'strs[:i + 1]', 'needs_index': True,
        })

    def test_plain_filter_still_parses_as_a_plain_filter(self):
        # This also matches the pick template with pick_expr='item'; the plain
        # form is listed first so it wins.
        parsed = self.parse_generated_code(
            'next((item for item in strs if len(item) > 4), None)')
        self.assertEqual(parsed.get('action'), 'filter')
        self.assertIsNone(parsed.get('pick_expr'))

    def test_ctx_to_model_restores_the_picked_expression(self):
        from table_visualizer import _ctx_to_model
        code = 'next((len(item) for item in strs if len(item) > 4), None)'
        parsed = self.parse_generated_code(code)
        model = {}
        _ctx_to_model(parsed, model)
        self.assertEqual(model['pick_expr'], 'len($)')
        self.assertEqual(model['tool'], 'pick')
        self.assertTrue(model['first_match'])
        # Region ids aren't recoverable from the expression, so nothing is
        # highlighted until the user picks again.
        self.assertIsNone(model['picked'])

    def test_roundtrip_loop_over_an_array_pick(self):
        for action in ['loop_no_idx', 'loop_new_idx']:
            with self.subTest(action=action):
                self._roundtrip(action, {
                    'is_predicate': True, 'is_first': True,
                    'is_index': False, 'is_slice': False, 'is_multi_index': False,
                    'predicate_expr': 'len(item) > 4', 'source_expr': 'strs',
                    'pick_expr': 'strs[:i + 1]', 'needs_index': True,
                    'pick_is_array': True,
                })

    def test_grammar_matches_generation_for_array_pick_loops(self):
        from table_visualizer_grammar import generate_action as grammar_generate
        model = make_pick_model(picked=['pre_col_1', 'match_col_1'])
        ctx = _get_search_context(model, ('strs', 'strs'), eval_in_scope=pick_eval)
        for action in ['loop_no_idx', 'loop_new_idx']:
            with self.subTest(action=action):
                self.assertEqual(grammar_generate(action, ctx)[1],
                                 generate_action(action, ctx)[1])

    def test_picked_join_is_not_misread_as_a_whole_list_join(self):
        # The iterable is the pick's next(...) wrapper, not a list. Reading it as
        # a whole-list source would make the wrapper the "source expression" and
        # quietly strip the pick, so it must not parse at all.
        model = make_pick_model(picked=['pre_col_1', 'match_col_1'])
        ctx = _get_search_context(model, ('strs', 'strs'), eval_in_scope=pick_eval)
        ctx['join_separator'] = "'|'"
        code = generate_action('join', ctx)[1]
        self.assertIsNone(self.parse_generated_code(code))

    def test_plain_whole_list_join_still_parses(self):
        parsed = self.parse_generated_code("''.join(str(item) for item in data)")
        self.assertEqual(parsed['action'], 'join')
        self.assertEqual(parsed['source_expr'], 'data')

    def test_ctx_to_model_clears_pick_for_an_unpicked_line(self):
        from table_visualizer import _ctx_to_model
        parsed = self.parse_generated_code('[item for item in strs if len(item) > 4]')
        model = {'tool': 'pick', 'pick_expr': 'len($)', 'picked': ['match_col_1']}
        _ctx_to_model(parsed, model)
        self.assertIsNone(model['pick_expr'])
        self.assertEqual(model['tool'], 'normal')


# === Per-column search tests ===

from table_visualizer import (
    ColumnSearchInput, ColumnSearchOpSelect, ColumnSearchComposeSelect,
    ColumnSearchDropdownToggle, COLUMN_SEARCH_OPS, COLUMN_SEARCH_COMPOSE,
    column_search_predicate, lift_column_predicate, compose_column_searches,
    decompose_search, _column_search_row, _column_search_active,
    _set_column_search, _tally_selection, unlift_term,
)


def make_column_search_input_event(col, value):
    """Create a ColumnSearchInput event for the column at *index*."""
    return {
        'pythonEventStr': (f"lambda e: ColumnSearchInput(col={col!r}, "
                           f"value=e.get('value', ''))"),
        'eventJSON': {'type': 'input', 'value': value},
    }


def make_column_search_op_event(col, op):
    return {
        'pythonEventStr': repr(ColumnSearchOpSelect(col=col, op=op)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


def make_column_search_compose_event(col, compose):
    return {
        'pythonEventStr': repr(ColumnSearchComposeSelect(col=col, compose=compose)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


def make_column_search_toggle_event(dropdown_id):
    return {
        'pythonEventStr': repr(ColumnSearchDropdownToggle(dropdown_id=dropdown_id)),
        'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1},
    }


class TestColumnSearchPredicate(unittest.TestCase):
    """One column's [op] + text becomes a predicate in COLUMN scope, where $ is
    the column value."""

    def test_operator_prepends_the_column_value(self):
        cases = [
            ('>=', '3', '$ >= 3'),
            ('>', '3', '$ > 3'),
            ('==', "'ATG'", "$ == 'ATG'"),
            ('!=', "'ATG'", "$ != 'ATG'"),
            ('<', '3', '$ < 3'),
            ('<=', '3', '$ <= 3'),
            ('in', "['a', 'b']", "$ in ['a', 'b']"),
            ('not in', "['a', 'b']", "$ not in ['a', 'b']"),
        ]
        for op, text, expected in cases:
            with self.subTest(op=op):
                self.assertEqual(column_search_predicate(op, text), expected)

    def test_every_offered_operator_is_handled(self):
        for op in COLUMN_SEARCH_OPS:
            with self.subTest(op=op):
                pred = column_search_predicate(op, '3')
                self.assertIsNotNone(pred)
                self.assertTrue(dollar_expr_parses_helper(pred), pred)

    def test_empty_text_is_inactive_whatever_the_operator(self):
        for op in COLUMN_SEARCH_OPS:
            with self.subTest(op=op):
                self.assertIsNone(column_search_predicate(op, ''))
                self.assertIsNone(column_search_predicate(op, '   '))
                self.assertIsNone(column_search_predicate(op, None))

    def test_blank_operator_keeps_an_expression_that_names_the_column(self):
        self.assertEqual(column_search_predicate('', 'isOdd($) and $ > 5'),
                         'isOdd($) and $ > 5')

    def test_blank_operator_calls_a_bare_predicate_function(self):
        self.assertEqual(column_search_predicate('', 'isOdd'), 'isOdd($)')

    def test_blank_operator_calls_a_dotted_predicate_function(self):
        self.assertEqual(column_search_predicate('', 'str.isdigit'),
                         'str.isdigit($)')

    def test_blank_operator_asks_the_scope_whether_a_name_is_callable(self):
        scope = {'isOdd': lambda n: n % 2 == 1, 'threshold': 5}
        eval_in_scope = lambda code: eval(code, {}, scope)
        self.assertEqual(column_search_predicate('', 'isOdd', eval_in_scope),
                         'isOdd($)')
        # A name bound to a value isn't a predicate to call - it stands on its
        # own, exactly as it would in the main search box.
        self.assertEqual(column_search_predicate('', 'threshold', eval_in_scope),
                         'threshold')

    def test_blank_operator_still_honors_a_leading_operator(self):
        self.assertEqual(column_search_predicate('', '>= 3'), '$ >= 3')
        self.assertEqual(column_search_predicate('', '.isdigit()'),
                         '$.isdigit()')

    def test_blank_operator_leaves_a_plain_value_verbatim(self):
        # Same as typing it into the main box: a truthy literal matches
        # everything rather than silently becoming an equality test.
        self.assertEqual(column_search_predicate('', "'ATG'"), "'ATG'")


def dollar_expr_parses_helper(s):
    """Whether a column-scope predicate is syntactically usable."""
    from visualizer_utils import dollar_expr_parses
    return dollar_expr_parses(s)


class TestLiftColumnPredicate(unittest.TestCase):
    """A column-scope predicate lifts into ITEM scope (what the main search box
    speaks): $ becomes the column expression, and every longer dollar run loses
    one level -- $$ (the item) becomes $, $$$ (the array) becomes $$."""

    def test_column_expression_replaces_the_single_dollar(self):
        self.assertEqual(lift_column_predicate("$ == 'ATG'", 'len($)'),
                         "len($) == 'ATG'")

    def test_identity_column_lifts_to_itself(self):
        self.assertEqual(lift_column_predicate('$ >= 3', '$'), '$ >= 3')

    def test_subscript_column_needs_no_parens(self):
        self.assertEqual(lift_column_predicate("$ == 'a'", "$['name']"),
                         "$['name'] == 'a'")

    def test_non_atomic_column_is_parenthesized(self):
        self.assertEqual(lift_column_predicate('$ * 2 > 5', '$ + 1'),
                         '($ + 1) * 2 > 5')

    def test_item_level_loses_a_dollar(self):
        self.assertEqual(lift_column_predicate('$ == $$', 'len($)'),
                         'len($) == $')

    def test_array_level_loses_a_dollar(self):
        self.assertEqual(lift_column_predicate('$ == max($$$)', 'len($)'),
                         'len($) == max($$)')

    def test_dollars_inside_string_literals_are_left_alone(self):
        self.assertEqual(lift_column_predicate("$ == '$$'", 'len($)'),
                         "len($) == '$$'")

    def test_every_occurrence_is_lifted(self):
        self.assertEqual(lift_column_predicate('isOdd($) and $ > 5', 'len($)'),
                         'isOdd(len($)) and len($) > 5')


class TestSigilsCrossLiftUntouched(unittest.TestCase):
    """Every sigil names something about the row, not a scope, so lifting a
    column predicate into item scope leaves it exactly where it is -- the rule
    $i already followed, now that $k, $v and $j exist to follow it too.

    The round-trip is the part that matters: unlift_term only accepts a reading
    that lifts back verbatim, so a sigil mangled on either side fails safe and
    the visible symptom is a main search that silently stops populating the
    column search box."""

    def test_each_sigil_crosses_the_lift_untouched(self):
        for sigil in ('i', 'k', 'v', 'j'):
            with self.subTest(sigil=sigil):
                self.assertEqual(
                    lift_column_predicate(f'$ > ${sigil}', 'len($)'),
                    f'len($) > ${sigil}')

    def test_a_sigil_does_not_read_as_a_deeper_run(self):
        # The defect the captured groups fix: '$k'.rstrip('i') is '$k', so the
        # old depth idiom read $k as a run of two and lifted the column into
        # the wrong level.
        self.assertEqual(lift_column_predicate('$k == 3', '$'), '$k == 3')

    def test_each_sigil_survives_the_round_trip(self):
        for sigil in ('i', 'k', 'v', 'j'):
            with self.subTest(sigil=sigil):
                pred = f'$ > ${sigil}'
                term = lift_column_predicate(pred, "$['age']")
                self.assertEqual(unlift_term(term, "$['age']"), pred)

    def test_a_sigil_beside_a_deeper_run_still_round_trips(self):
        pred = '$ == $$ and $k > 1'
        term = lift_column_predicate(pred, 'len($)')
        self.assertEqual(term, 'len($) == $ and $k > 1')
        self.assertEqual(unlift_term(term, 'len($)'), pred)

    def test_a_sigil_in_a_string_literal_is_left_alone(self):
        self.assertEqual(lift_column_predicate("$ == '$k'", 'len($)'),
                         "len($) == '$k'")


class TestComposeColumnSearches(unittest.TestCase):
    """Active column searches fold into one main-search string: the `and` terms
    form a group, then the `or` terms are or'd against it."""

    @staticmethod
    def row(text, op='==', compose='and'):
        return {'compose': compose, 'op': op, 'text': text}

    def test_nothing_active_is_none(self):
        self.assertIsNone(compose_column_searches(['$'], {}))
        self.assertIsNone(compose_column_searches(['$'], None))

    def test_empty_text_is_skipped(self):
        self.assertIsNone(compose_column_searches(['$'], {'$': self.row('')}))

    def test_single_column(self):
        self.assertEqual(
            compose_column_searches(['len($)'], {'len($)': self.row("'ATG'")}),
            "len($) == 'ATG'")

    def test_two_and_columns_join_in_column_order(self):
        columns = ['len($)', "$['name']"]
        searches = {"$['name']": self.row("'a'"), 'len($)': self.row('3', op='>=')}
        self.assertEqual(compose_column_searches(columns, searches),
                         "len($) >= 3 and $['name'] == 'a'")

    def test_or_column_is_ord_against_the_and_group(self):
        columns = ['a($)', 'b($)', 'c($)']
        searches = {
            'a($)': self.row('1'),
            'b($)': self.row('2'),
            'c($)': self.row('3', compose='or'),
        }
        self.assertEqual(compose_column_searches(columns, searches),
                         '(a($) == 1 and b($) == 2) or c($) == 3')

    def test_a_single_and_term_needs_no_group_parens(self):
        # `and` already binds tighter than `or`.
        columns = ['a($)', 'c($)']
        searches = {'a($)': self.row('1'), 'c($)': self.row('3', compose='or')}
        self.assertEqual(compose_column_searches(columns, searches),
                         'a($) == 1 or c($) == 3')

    def test_only_or_columns(self):
        columns = ['a($)', 'c($)']
        searches = {'a($)': self.row('1', compose='or'),
                    'c($)': self.row('3', compose='or')}
        self.assertEqual(compose_column_searches(columns, searches),
                         'a($) == 1 or c($) == 3')

    def test_the_and_group_leads_regardless_of_column_order(self):
        # The dropdown marks each term as part of the group or or'd against it,
        # so the group comes first even when its column sits later.
        columns = ['a($)', 'b($)']
        searches = {'a($)': self.row('1', compose='or'), 'b($)': self.row('2')}
        self.assertEqual(compose_column_searches(columns, searches),
                         'b($) == 2 or a($) == 1')

    def test_an_or_inside_the_group_is_parenthesized(self):
        columns = ['$', "$['x']"]
        searches = {
            '$': self.row('$ == 1 or $ == 2', op=''),
            "$['x']": self.row('0', op='>'),
        }
        self.assertEqual(compose_column_searches(columns, searches),
                         "($ == 1 or $ == 2) and $['x'] > 0")

    def test_column_order_drives_term_order(self):
        columns = ["$['b']", "$['a']"]
        searches = {"$['a']": self.row('1'), "$['b']": self.row('2')}
        self.assertEqual(compose_column_searches(columns, searches),
                         "$['b'] == 2 and $['a'] == 1")

    def test_a_lone_term_stands_as_it_was_written(self):
        # Parens keep a join from reading a term differently; with nothing to
        # join it to there is nothing to protect it from.
        searches = {'$': self.row('$ == 1 or $ == 2', op='')}
        self.assertEqual(compose_column_searches(['$'], searches),
                         '$ == 1 or $ == 2')


def leftover(text, index=0, compose='and'):
    return {'compose': compose, 'text': text, 'index': index}


class TestComposeLeftovers(unittest.TestCase):
    """Terms of the main search that no column claimed are kept as leftovers,
    and compose back in at the position they were written."""

    row = staticmethod(TestComposeColumnSearches.row)

    def test_a_leftover_alone_is_the_search_verbatim(self):
        self.assertEqual(
            compose_column_searches([], {}, leftovers=[leftover('$ == 1 or $ == 2')]),
            '$ == 1 or $ == 2')

    def test_a_leftover_composes_before_the_column_it_preceded(self):
        self.assertEqual(
            compose_column_searches(["$['a']"], {"$['a']": self.row('1')},
                                    leftovers=[leftover('len($) > 3', index=0)]),
            "len($) > 3 and $['a'] == 1")

    def test_a_leftover_composes_after_the_column_it_followed(self):
        self.assertEqual(
            compose_column_searches(["$['a']"], {"$['a']": self.row('1')},
                                    leftovers=[leftover('len($) > 3', index=1)]),
            "$['a'] == 1 and len($) > 3")

    def test_a_leftover_joins_the_group_it_was_written_in(self):
        self.assertEqual(
            compose_column_searches(["$['a']"], {"$['a']": self.row('1')},
                                    leftovers=[leftover('len($) > 3', index=0,
                                                        compose='or')]),
            "$['a'] == 1 or len($) > 3")

    def test_several_leftovers_keep_their_order(self):
        self.assertEqual(
            compose_column_searches(["$['a']"], {"$['a']": self.row('1')},
                                    leftovers=[leftover('b', index=2),
                                               leftover('a', index=0)]),
            "a and $['a'] == 1 and b")

    def test_an_index_past_the_end_lands_last(self):
        self.assertEqual(
            compose_column_searches(["$['a']"], {"$['a']": self.row('1')},
                                    leftovers=[leftover('len($) > 3', index=9)]),
            "$['a'] == 1 and len($) > 3")

    def test_an_empty_leftover_is_not_a_term(self):
        self.assertIsNone(compose_column_searches([], {}, leftovers=[leftover('  ')]))


class TestDecomposeSearch(unittest.TestCase):
    """The main search box reads back as per-column searches, plus whatever
    terms no column claimed."""

    def test_nothing_to_read(self):
        self.assertEqual(decompose_search(None, ["$['a']"]), ({}, []))
        self.assertEqual(decompose_search('', ["$['a']"]), ({}, []))

    def test_an_operator_comes_back_as_the_operator_chip(self):
        # The tally reads its checkmarks out of the operator, so `==` has to
        # come back as `==` rather than as the whole predicate.
        self.assertEqual(decompose_search("$['a'] == 1", ["$['a']"]),
                         ({"$['a']": {'compose': 'and', 'op': '==', 'text': '1'}},
                          []))

    def test_every_operator_reads_back(self):
        for op in ['>=', '>', '==', '!=', '<', '<=']:
            with self.subTest(op=op):
                searches, leftovers = decompose_search(f"$['a'] {op} 3", ["$['a']"])
                self.assertEqual(searches["$['a']"]['op'], op)
                self.assertEqual(searches["$['a']"]['text'], '3')
                self.assertEqual(leftovers, [])

    def test_membership_reads_back_with_its_collection(self):
        searches, _ = decompose_search("$['a'] in ['x', 'y']", ["$['a']"])
        self.assertEqual(searches["$['a']"], {'compose': 'and', 'op': 'in',
                                              'text': "['x', 'y']"})

    def test_a_predicate_that_is_not_a_comparison_keeps_the_blank_operator(self):
        searches, _ = decompose_search("isOdd($['a'])", ["$['a']"])
        self.assertEqual(searches["$['a']"], {'compose': 'and', 'op': '',
                                              'text': 'isOdd($)'})

    def test_a_non_atomic_column_sheds_the_parens_it_was_lifted_with(self):
        searches, _ = decompose_search('($ + 1) > 3', ['$ + 1'])
        self.assertEqual(searches['$ + 1'], {'compose': 'and', 'op': '>',
                                             'text': '3'})

    def test_a_deeper_dollar_run_comes_back_down_a_level(self):
        searches, _ = decompose_search("len($['a']) == len($)", ["$['a']"])
        self.assertEqual(searches["$['a']"], {'compose': 'and', 'op': '',
                                              'text': 'len($) == len($$)'})

    def test_two_and_columns(self):
        columns = ["$['a']", "$['b']"]
        searches, leftovers = decompose_search("$['a'] == 1 and $['b'] == 2",
                                               columns)
        self.assertEqual(searches["$['a']"]['compose'], 'and')
        self.assertEqual(searches["$['b']"]['text'], '2')
        self.assertEqual(leftovers, [])

    def test_an_or_column_reads_back_as_or(self):
        columns = ["$['a']", "$['b']", "$['c']"]
        search = "($['a'] == 1 and $['b'] == 2) or $['c'] == 3"
        searches, leftovers = decompose_search(search, columns)
        self.assertEqual(searches["$['c']"]['compose'], 'or')
        self.assertEqual(searches["$['a']"]['compose'], 'and')
        self.assertEqual(leftovers, [])

    def test_a_term_no_column_claims_is_a_leftover(self):
        columns = ["$['a']"]
        searches, leftovers = decompose_search("$['a'] == 1 and len($) > 3",
                                               columns)
        self.assertEqual(searches["$['a']"]['text'], '1')
        self.assertEqual(leftovers, [leftover('len($) > 3', index=1)])

    def test_a_whole_row_search_belongs_to_no_column(self):
        # `$` is the row, not the column value: a column must actually appear in
        # a term to claim it, or every search would land in the first column.
        self.assertEqual(decompose_search('$ == 3', ["$['name']"]),
                         ({}, [leftover('$ == 3')]))

    def test_the_column_that_appears_claims_the_term(self):
        searches, leftovers = decompose_search("$['a'] == 1", ['$', "$['a']"])
        self.assertEqual(list(searches), ["$['a']"])
        self.assertEqual(searches["$['a']"]['text'], '1')
        self.assertEqual(leftovers, [])

    def test_the_row_column_claims_a_search_written_against_the_row(self):
        searches, _ = decompose_search('$ == 3', ['$'])
        self.assertEqual(searches['$'], {'compose': 'and', 'op': '==',
                                         'text': '3'})

    def test_terms_written_out_of_column_order_stay_where_they_were(self):
        # The columns compose in column order, so the second term can't be the
        # first column's -- but the first term is still the second column's, and
        # what is left keeps its place in the search.
        columns = ["$['name']", "$['age']"]
        search = "$['age'] >= 30 and $['name'] == 'a'"
        searches, leftovers = decompose_search(search, columns)
        self.assertEqual(list(searches), ["$['age']"])
        self.assertEqual(leftovers, [leftover("$['name'] == 'a'", index=1)])

    def test_a_search_that_does_not_parse_is_all_leftover(self):
        self.assertEqual(decompose_search("$['a'] ==", ["$['a']"]),
                         ({}, [leftover("$['a'] ==")]))

    def test_spacing_the_columns_would_not_have_written_is_kept_as_typed(self):
        # The operator chip only ever writes `$ == 1`, so this reads as the
        # whole predicate instead. Either way the box is never rewritten under
        # the user's cursor.
        self.assertEqual(decompose_search("$['a']==1", ["$['a']"]),
                         ({"$['a']": {'compose': 'and', 'op': '',
                                      'text': '$==1'}}, []))

    def test_what_it_reads_composes_back_to_what_it_read(self):
        columns = ['$', "$['a']", 'len($)']
        searches = [
            "$['a'] == 1",
            "$['a'] in ['x', 'y']",
            "$['a'] == 1 and len($) > 3",
            "$['a'] == 1 or len($) > 3",
            "($['a'] == 1 and len($) > 3) or $ == 2",
            "isOdd($['a'])",
            'len($) > 3 and unclaimable(x)',
            'nothing here for a column',
            "$['a'] ==",
        ]
        for search in searches:
            with self.subTest(search=search):
                rows, leftovers = decompose_search(search, columns)
                self.assertEqual(
                    compose_column_searches(columns, rows, leftovers=leftovers),
                    search)


class TestColumnSearchEvents(unittest.TestCase):
    """The column search rows live in the model keyed by column expression, and
    every edit rewrites the main search box."""

    def make_model(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bo', 'age': 20}]
        model = init_model(lst, mock_get_visualizer)
        return lst, model

    def test_typing_stores_the_text_and_recomposes_the_main_search(self):
        lst, model = self.make_model()
        col = list(model['columns'])[0]
        new_model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                              None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(new_model['column_searches'][col]['text'], "'Alice'")
        self.assertEqual(new_model['search'], f"{col} == 'Alice'")
        self.assertTrue(new_model['_scroll_to_match'])

    def test_default_operator_is_equality_and_default_compose_is_and(self):
        lst, model = self.make_model()
        col = list(model['columns'])[0]
        new_model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                              None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        row = new_model['column_searches'][col]
        self.assertEqual(row['op'], '==')
        self.assertEqual(row['compose'], 'and')

    def test_choosing_an_operator_recomposes_and_closes_the_chip_menu(self):
        lst, model = self.make_model()
        col = list(model['columns'])[1]
        model, _ = update(make_column_search_input_event(col_at(model, 1), '25'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model['col_search_dropdown'] = 'op-1'
        new_model, _ = update(make_column_search_op_event(col_at(model, 1), '>='),
                              None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(new_model['column_searches'][col]['op'], '>=')
        self.assertEqual(new_model['search'], f'{col} >= 25')
        self.assertIsNone(new_model['col_search_dropdown'])

    def test_choosing_a_compose_operator(self):
        lst, model = self.make_model()
        col = list(model['columns'])[0]
        model['col_search_dropdown'] = menu_id(model, 'compose')
        new_model, _ = update(make_column_search_compose_event(col_at(model), 'or'),
                              None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(new_model['column_searches'][col]['compose'], 'or')
        self.assertIsNone(new_model['col_search_dropdown'])

    def test_only_offered_values_are_accepted(self):
        lst, model = self.make_model()
        model, _ = update(make_column_search_op_event(col_at(model), 'DROP TABLE'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertFalse(model.get('column_searches'))
        model, _ = update(make_column_search_compose_event(col_at(model), 'xor'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertFalse(model.get('column_searches'))

    def test_chip_dropdown_toggles_without_closing_the_column_menu(self):
        lst, model = self.make_model()
        model['openDropdown'] = {'id': menu_id(model)}
        opened, _ = update(make_column_search_toggle_event(menu_id(model, 'op')),
                           None, model, lst, mock_get_visualizer,
                           eval_in_scope=eval)
        self.assertEqual(opened['col_search_dropdown'], menu_id(opened, 'op'))
        self.assertEqual(opened['openDropdown'], {'id': menu_id(opened)})
        closed, _ = update(make_column_search_toggle_event(menu_id(opened, 'op')),
                           None, opened, lst, mock_get_visualizer,
                           eval_in_scope=eval)
        self.assertIsNone(closed['col_search_dropdown'])

    def test_clearing_the_text_clears_the_main_search(self):
        lst, model = self.make_model()
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_search_input_event(col_at(model), ''),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['search'])

    def test_removing_a_column_drops_its_search_and_recomposes(self):
        lst, model = self.make_model()
        first, second = list(model['columns'])[0], list(model['columns'])[1]
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_search_input_event(col_at(model, 1), '30'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model)))),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertNotIn(first, model['column_searches'])
        self.assertEqual(model['search'], f'{second} == 30')

    def test_removing_the_last_searched_column_clears_the_main_search(self):
        lst, model = self.make_model()
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model)))),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['search'])

    def re_express(self, model, lst, index, expr):
        """Double-click a header and commit a new expression for the column."""
        model['editing_column'] = col_at(model, index)
        model['column_input_value'] = expr
        return update(make_column_key_event('Enter'), None, model, lst,
                      mock_get_visualizer, eval_in_scope=eval)[0]

    def test_re_expressing_a_column_drops_its_search(self):
        # The search was written against the old expression, so it goes with it
        # -- out of the menu and out of the main box both.
        lst, model = self.make_model()
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model = self.re_express(model, lst, 0, 'len($)')
        self.assertFalse(model.get('column_searches'))
        self.assertIsNone(model['search'])

    def test_re_expressing_a_column_leaves_the_other_columns_alone(self):
        lst, model = self.make_model()
        second = list(model['columns'])[1]
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_search_input_event(col_at(model, 1), '30'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model = self.re_express(model, lst, 0, 'len($)')
        self.assertEqual(model['column_searches'][second]['text'], '30')
        self.assertEqual(model['search'], f'{second} == 30')

    def test_re_expressing_a_column_keeps_its_aggregations(self):
        # An aggregation describes the column rather than filtering it, so it
        # follows the column to its new expression.
        lst, model = self.make_model()
        old = list(model['columns'])[0]
        _set_column_computes(model, old, ['min($)'])
        model = self.re_express(model, lst, 0, 'len($)')
        self.assertEqual(_column_computes(model, 'len($)'), ['min($)'])

    def test_reordering_columns_recomposes_in_the_new_order(self):
        lst, model = self.make_model()
        first, second = list(model['columns'])[0], list(model['columns'])[1]
        model, _ = update(make_column_search_input_event(col_at(model), "'Alice'"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_search_input_event(col_at(model, 1), '30'),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model['column_drag_from'] = col_at(model, 1)
        model, _ = update(make_column_mouse_event(repr(ColumnDragEnd(col=col_at(model)))),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['search'], f"{second} == 30 and {first} == 'Alice'")

    def test_a_hand_written_main_search_survives_a_column_removal(self):
        # Nothing was pushed from a column, so there is nothing to push -- the
        # main box is the user's.
        lst, model = self.make_model()
        model, _ = update(make_search_input_event('$ == 3'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        model, _ = update(make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model)))),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['search'], '$ == 3')

    def test_column_searches_default_to_none_not_a_shared_dict(self):
        lst, _ = self.make_model()
        a = init_model(lst, mock_get_visualizer)
        b = init_model(lst, mock_get_visualizer)
        self.assertIsNone(a['column_searches'])
        a, _ = update(make_column_search_input_event(col_at(a), "'Alice'"), None, a, lst,
                      mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(b['column_searches'])


class TestSearchBoxReadsBackIntoTheColumns(unittest.TestCase):
    """The main search box is the other end of the same filter: what is typed
    there reads back into the column rows, and what no column claims is kept so
    the next column edit doesn't drop it."""

    def make_model(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bo', 'age': 20}]
        model = init_model(lst, mock_get_visualizer)
        return lst, model

    def search(self, model, lst, text):
        return update(make_search_input_event(text), None, model, lst,
                      mock_get_visualizer, eval_in_scope=eval)[0]

    def test_typing_a_column_search_fills_in_the_column_row(self):
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        model = self.search(model, lst, f'{age} >= 30')
        row = _column_search_row(model, age)
        self.assertEqual((row['op'], row['text']), ('>=', '30'))
        self.assertTrue(_column_search_active(model, age))

    def test_typing_a_membership_search_checks_the_tally_rows(self):
        lst, model = self.make_model()
        name = list(model['columns'])[0]
        model = self.search(model, lst, f"{name} in ['Alice', 'Bo']")
        self.assertEqual(_tally_selection(_column_search_row(model, name)),
                         (["'Alice'", "'Bo'"], False))

    def test_editing_the_search_re_reads_it(self):
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        model = self.search(model, lst, f'{age} >= 30')
        model = self.search(model, lst, f'{age} < 25')
        self.assertEqual(_column_search_row(model, age)['op'], '<')
        self.assertEqual(_column_search_row(model, age)['text'], '25')

    def test_clearing_the_search_clears_the_column_rows(self):
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        model = self.search(model, lst, f'{age} >= 30')
        model = self.search(model, lst, '')
        self.assertFalse(model.get('column_searches'))
        self.assertFalse(model.get('search_leftovers'))
        self.assertIsNone(model['search'])

    def test_a_search_no_column_claims_leaves_the_rows_empty(self):
        lst, model = self.make_model()
        model = self.search(model, lst, 'len($) > 1')
        self.assertFalse(model.get('column_searches'))
        self.assertEqual(model['search'], 'len($) > 1')

    def test_the_half_no_column_claims_survives_a_column_edit(self):
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        model = self.search(model, lst, f'{age} >= 30 and len($) > 1')
        self.assertEqual(_column_search_row(model, age)['text'], '30')
        model, _ = update(make_column_search_input_event(col_at(model, 1), '25'), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['search'], f'{age} >= 25 and len($) > 1')

    def test_removing_a_column_takes_the_search_that_was_typed_for_it(self):
        # The term was the column's, however it was written, so it leaves with
        # the column rather than lingering as a term nothing explains.
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        model = self.search(model, lst, f'{age} >= 30 and len($) > 1')
        model, _ = update(make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model, 1)))),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['search'], 'len($) > 1')

    def test_relinking_from_code_fills_in_the_column_rows(self):
        from table_visualizer import _ctx_to_model
        lst, model = self.make_model()
        age = list(model['columns'])[1]
        _ctx_to_model({'is_predicate': True,
                       'predicate_expr': f"{age.replace('$', 'item')} >= 30"},
                      model)
        self.assertEqual(_column_search_row(model, age)['op'], '>=')
        self.assertEqual(_column_search_row(model, age)['text'], '30')


class TestColumnSearchMembershipBrackets(unittest.TestCase):
    """`in` and `not in` want a collection on the right, so picking one hands the
    user the brackets and drops the cursor inside them."""

    def make_model(self):
        lst = [{'name': 'Alice'}, {'name': 'Bo'}]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': menu_id(model)}
        return lst, model, list(model['columns'])[0]

    def pick_op(self, model, lst, op, index=0):
        col = col_at(model, index)
        return update(make_column_search_op_event(col, op), None, model, lst,
                      mock_get_visualizer, eval_in_scope=eval)[0]

    def test_picking_a_membership_operator_inserts_the_brackets(self):
        for op in ['in', 'not in']:
            with self.subTest(op=op):
                lst, model, col = self.make_model()
                model = self.pick_op(model, lst, op)
                self.assertEqual(model['column_searches'][col]['text'], '[]')

    def test_the_brackets_do_not_overwrite_what_the_user_typed(self):
        lst, model, col = self.make_model()
        model, _ = update(make_column_search_input_event(col_at(model), "'ATG'"), None,
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        model = self.pick_op(model, lst, 'in')
        self.assertEqual(model['column_searches'][col]['text'], "'ATG'")

    def test_the_other_operators_insert_nothing(self):
        for op in COLUMN_SEARCH_OPS:
            if op in ('in', 'not in'):
                continue
            with self.subTest(op=op):
                lst, model, col = self.make_model()
                model = self.pick_op(model, lst, op)
                self.assertEqual(_column_search_row(model, col)['text'], '')

    def test_empty_brackets_are_not_a_search_yet(self):
        # Otherwise picking `in` would empty the table before the user has said
        # what to look for.
        for text in ['[]', '[ ]', '()', '{}']:
            with self.subTest(text=text):
                self.assertIsNone(column_search_predicate('in', text))
                self.assertIsNone(column_search_predicate('', text))

    def test_picking_in_leaves_the_main_search_alone(self):
        lst, model, col = self.make_model()
        model = self.pick_op(model, lst, 'in')
        self.assertIsNone(model['search'])
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        self.assertNotIn('col-filtered', th)

    def test_filling_in_the_brackets_searches(self):
        lst, model, col = self.make_model()
        model = self.pick_op(model, lst, 'in')
        model, _ = update(make_column_search_input_event(col_at(model), "['Alice', 'Bo']"),
                          None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['search'], f"{col} in ['Alice', 'Bo']")

    def test_leaving_membership_takes_the_untouched_brackets_back(self):
        lst, model, col = self.make_model()
        model = self.pick_op(model, lst, 'in')
        model = self.pick_op(model, lst, '==')
        self.assertEqual(_column_search_row(model, col)['text'], '')

    def test_leaving_membership_keeps_a_filled_in_collection(self):
        lst, model, col = self.make_model()
        model = self.pick_op(model, lst, 'in')
        model, _ = update(make_column_search_input_event(col_at(model), "['Alice']"), None,
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        model = self.pick_op(model, lst, '==')
        self.assertEqual(model['column_searches'][col]['text'], "['Alice']")

    def test_the_cursor_lands_between_the_brackets(self):
        lst, model, col = self.make_model()
        model = self.pick_op(model, lst, 'in')
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        m = re.search(r'<input[^>]*col-search-input[^>]*>', th)
        self.assertIsNotNone(m)
        self.assertIn('autofocus', m.group(0))
        self.assertIn('snc-cursor-pos="1"', m.group(0))

    def test_the_column_menu_does_not_grab_focus_on_its_own(self):
        # Only the bracket insertion asks for focus; opening a menu or typing
        # must leave it wherever the user put it.
        lst, model, col = self.make_model()
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        self.assertNotIn('autofocus', th)

        model = self.pick_op(model, lst, 'in')
        model, _ = update(make_column_search_input_event(col_at(model), "['a']"), None,
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        self.assertNotIn('autofocus', th)


class TestColumnSearchRendering(unittest.TestCase):
    """The search row lives in the per-column ▾ menu, below the action rows."""

    def open_menu_html(self, model, lst, column=0):
        model['openDropdown'] = {'id': menu_id(model, index=column)}
        return visualize(lst, model, mock_get_visualizer, None)

    def search_row(self, th):
        """The search row's markup: the last thing in the column menu."""
        return th[th.index('<div class="col-search-area">'):]

    def test_closed_menu_renders_no_search_row(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertNotIn('col-search-area',
                         visualize(lst, model, mock_get_visualizer, None))

    def test_open_menu_renders_both_chips_and_the_input(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        th = _first_column_header(self.open_menu_html(model, lst))
        self.assertIn('col-search-area', th)
        self.assertIn('col-search-compose', th)
        self.assertIn('col-search-op', th)
        self.assertIn('col-search-input', th)
        self.assertIn(html.escape(f'ColumnSearchInput(col={col_at(model)!r}'), th)
        # The search row comes after the action rows, per the menu's TODO order.
        self.assertLess(th.index('Remove Column'), th.index('col-search-area'))

    def test_chips_show_the_current_choice(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        col = list(model['columns'])[0]
        model['column_searches'] = {col: {'compose': 'or', 'op': '>=',
                                          'text': '3'}}
        row = self.search_row(_first_column_header(self.open_menu_html(model, lst)))
        self.assertIn('or', row)
        self.assertIn('&gt;=', row)
        self.assertIn('value="3"', row)

    def test_the_chips_ride_on_top_of_the_search_box(self):
        # Same construction as the string visualizer's toggles over its Find box
        # (see .search-box-wrapper): the input is the whole control, so it keeps
        # the search box look, and the chips are positioned over its padding.
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        row = self.search_row(_first_column_header(self.open_menu_html(model, lst)))
        self.assertIn('search-box-wrapper', row)
        input_html = re.search(r'<input[^>]*col-search-input[^>]*>', row).group(0)
        self.assertIn('search-box', input_html)
        # The chips paint over the input, so they come after it.
        self.assertLess(row.index('col-search-input'), row.index('col-search-chips'))
        # The operator reads first, at the box's left edge, the way it reads in
        # the predicate it writes; how the column composes with the others is a
        # separate question and sits at the far end.
        self.assertLess(row.index('col-search-op'), row.index('col-search-chips-right'))
        self.assertLess(row.index('col-search-op'), row.index('col-search-compose'))

    def test_chip_options_render_only_while_that_chip_is_open(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        th = _first_column_header(self.open_menu_html(model, lst))
        self.assertNotIn('ColumnSearchOpSelect', th)

        model['col_search_dropdown'] = menu_id(model, 'op')
        th = _first_column_header(self.open_menu_html(model, lst))
        self.assertIn('ColumnSearchOpSelect', th)
        self.assertIn('(code)', th)
        for op in COLUMN_SEARCH_OPS:
            if op:
                self.assertIn(html.escape(op), th)
        # A nested panel, hoisted and flyout-aligned like the menu itself.
        self.assertIn('col-search-chip-panel', th)
        self.assertIn('snc-dropdown-align="flyout"', th)
        self.assertNotIn('ColumnSearchComposeSelect', th)

    def test_compose_chip_offers_and_or(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['col_search_dropdown'] = menu_id(model, 'compose')
        th = _first_column_header(self.open_menu_html(model, lst))
        for compose in COLUMN_SEARCH_COMPOSE:
            self.assertIn(html.escape(f'compose={compose!r}'), th)

    def test_an_active_search_marks_the_header(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        col = list(model['columns'])[0]
        model['column_searches'] = {col: {'compose': 'and', 'op': '==',
                                          'text': "'Alice'"}}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        # Pinned visible so a filtered column is legible with the menu closed.
        self.assertIn('col-filtered', th)
        self.assertIn('col-menu snc-hover-hidden full-opacity-on-hover active', th)

    def test_an_inactive_row_does_not_mark_the_header(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        col = list(model['columns'])[0]
        model['column_searches'] = {col: {'compose': 'and', 'op': '>=', 'text': ''}}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer, None))
        self.assertNotIn('col-filtered', th)

    def test_escape_closes_the_chip_menu_before_the_column_menu(self):
        lst = [{'name': 'Alice'}]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'op')
        model, _ = update(make_column_key_event('Escape'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['col_search_dropdown'])
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})
        model, _ = update(make_column_key_event('Escape'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['openDropdown'])

    def test_reopening_a_column_menu_closes_a_stale_chip_menu(self):
        lst = [{'name': 'Alice', 'age': 30}]
        model = init_model(lst, mock_get_visualizer)
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'op')
        model, _ = update(make_dropdown_toggle_event('col-menu-1'), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['col_search_dropdown'])


class TestColumnSearchDrivesTheExistingSearch(unittest.TestCase):
    """A column search filters and generates code through the main search box,
    so it needs no matching or code-generation path of its own."""

    def test_composed_search_matches_rows(self):
        lst = ['a', 'abcd', 'ab', 'abcde']
        self.assertEqual(_get_matching_indices('len($) >= 3', lst, eval),
                         [1, 3])

    def test_main_search_can_name_the_array_with_two_dollars(self):
        lst = [1, 5, 3, 5]
        self.assertEqual(_get_matching_indices('$ == max($$)', lst, eval),
                         [1, 3])

    def test_generated_code_inlines_the_array_for_two_dollars(self):
        model = {'search': '$ == max($$)', 'first_match': False}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'),
                                  eval_in_scope=eval)
        self.assertEqual(ctx['predicate_expr'], 'item == max(data)')
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[item for item in data if item == max(data)]')

    def column_search_model(self):
        lst = [{'name': 'Alice', 'age': 30}, {'name': 'Bo', 'age': 20}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['len($["name"])']
        eval_in_scope = lambda code: eval(code, {'len': len, 'max': max},
                                          {'data': lst})
        return lst, model, eval_in_scope

    def test_a_column_search_auto_links_a_filter_over_the_column(self):
        # Same as typing into the main box: the first meaningful edit inserts a
        # line of code and links it.
        lst, model, eval_in_scope = self.column_search_model()
        model, commands = update(make_column_search_input_event(col_at(model), '3'),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval_in_scope)
        self.assertEqual(model['search'], 'len($["name"]) == 3')
        self.assertEqual([c[1] for c in commands if isinstance(c, tuple)],
                         ['[item for item in data if len(item["name"]) == 3]'])
        self.assertEqual(model['linked_action'], 'filter')

    def test_editing_a_column_search_rewrites_the_linked_line(self):
        lst, model, eval_in_scope = self.column_search_model()
        model, _ = update(make_column_search_input_event(col_at(model), '3'),
                          ('data', 'data'), model, lst, mock_get_visualizer,
                          eval_in_scope=eval_in_scope)
        model, commands = update(make_column_search_op_event(col_at(model), '>='),
                                 ('data', 'data'), model, lst,
                                 mock_get_visualizer, eval_in_scope=eval_in_scope)
        self.assertEqual([c.expression for c in commands
                          if isinstance(c, ChangeSelectedText)],
                         ['[item for item in data if len(item["name"]) >= 3]'])


# === Column tally tests ===

from table_visualizer import (
    TallyItemToggle, TallySelectAll, TallySelectNone, TallyExcludeToggle,
    TallyFilterInput, TallySortSelect, TallyCountFilterInput, TallyCountOpSelect,
    TALLY_MAX_CARDINALITY, TALLY_TOO_MANY, TALLY_UNHASHABLE,
    TALLY_SORTS, TALLY_SORT_DEFAULT, TALLY_COUNT_OPS, TALLY_COUNT_OP_DEFAULT,
    TALLY_COUNT_EXTREME_OPS,
    _column_values, _tally, _tally_literal, _tally_selection,
    _write_tally_selection, _tally_literals, _tally_shows, _sorted_tally,
    _tally_count_shows, _tally_extreme,
    _column_values_expr, _tally_exprs, _column_tally_rows, _tally_lists,
    _column_binding, _column_cell_expr, _column_values, _binds_for,
    _get_matching_indices, _render_action_buttons, _render_tool_toolbar,
    _agg_value, ROW_AGGS, NO_ANSWER, _tally, _tally_counter_expr,
    _get_whole_list_context, _agg_col_code, _agg_row_index_code,
    TALLY_UNHASHABLE,
    _tally_row_count_expr,
)

from collections import Counter


# The list from the tally sketch in the TODO: 'c' 5, 'aa' 2, 'b' 3, first seen
# in that order.
TALLY_LIST = ['c', 'aa', 'b', 'c', 'b', 'c', 'c', 'c', 'aa', 'b']


def tally_model(lst=None):
    """A one-column ('$') table model over *lst*."""
    lst = TALLY_LIST if lst is None else lst
    model = init_model(lst, mock_get_visualizer)
    model['columns'] = ['$']
    return lst, model


class TestColumnValues(unittest.TestCase):
    """A column's values for every row, which is what there is to tally. The
    table itself only ever evaluates one cell at a time."""

    def test_the_item_column_needs_no_eval_at_all(self):
        lst, model = tally_model()
        self.assertEqual(_column_values('$', lst, model), lst)

    def test_a_computed_column_is_gathered_in_one_eval(self):
        # One comprehension over the whole list, not one eval per row: the same
        # expression the header already builds for its drag payload.
        lst = [{'name': 'Alice'}, {'name': 'Bo'}]
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        calls = []

        def counting_eval(code):
            calls.append(code)
            return eval(code, {}, {'data': lst})

        self.assertEqual(_column_values("$['name']", lst, model, counting_eval),
                         ['Alice', 'Bo'])
        self.assertEqual(len(calls), 1)
        self.assertIn('for item in data', calls[0])

    def test_falls_back_to_one_eval_per_row_without_a_scope(self):
        lst = [{'name': 'Alice'}, {'name': 'Bo'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIsNone(model.get('_source_expr'))
        self.assertEqual(_column_values("$['name']", lst, model),
                         ['Alice', 'Bo'])

    def test_a_row_the_column_cannot_be_read_from_is_dropped(self):
        # A summary shouldn't cost the other n-1 rows.
        lst = [{'name': 'Alice'}, {}, {'name': 'Bo'}]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(_column_values("$['name']", lst, model),
                         ['Alice', 'Bo'])

    def test_one_bad_row_falls_the_whole_comprehension_back_to_per_row(self):
        lst = [{'name': 'Alice'}, {}, {'name': 'Bo'}]
        model = init_model(lst, mock_get_visualizer)
        model['_source_expr'] = 'data'
        eval_in_scope = lambda code: eval(code, {}, {'data': lst})
        self.assertEqual(_column_values("$['name']", lst, model, eval_in_scope),
                         ['Alice', 'Bo'])


class TestTally(unittest.TestCase):
    """Distinct values and their counts, or a reason there's no tally to show."""

    def test_counts_in_first_seen_order(self):
        self.assertEqual(list(_tally(TALLY_LIST).items()),
                         [('c', 5), ('aa', 2), ('b', 3)])

    def test_no_rows_is_no_tally(self):
        self.assertIsNone(_tally([]))

    def test_a_named_column_the_cardinality_limit_still_tallies(self):
        tally = _tally(list(range(TALLY_MAX_CARDINALITY)))
        self.assertEqual(len(tally), TALLY_MAX_CARDINALITY)

    def test_too_many_distinct_values_gives_up(self):
        self.assertEqual(_tally(list(range(TALLY_MAX_CARDINALITY + 1))),
                         TALLY_TOO_MANY)

    def test_unhashable_values_cannot_be_counted(self):
        self.assertEqual(_tally([{'a': 1}, {'a': 2}]), TALLY_UNHASHABLE)
        self.assertEqual(_tally([[1], [2]]), TALLY_UNHASHABLE)

    def test_none_is_a_value_like_any_other(self):
        self.assertEqual(_tally([None, 1, None]), {None: 2, 1: 1})


class TestTallyLiteral(unittest.TestCase):
    """A tally row is only clickable when its value can be written back into the
    search box as Python that means the same thing."""

    def test_values_whose_repr_round_trips(self):
        cases = [('c', "'c'"), (5, '5'), (3.5, '3.5'), (None, 'None'),
                 (True, 'True'), ((1, 'a'), "(1, 'a')"), ("it's", '"it\'s"')]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_tally_literal(value), expected)

    def test_an_object_repr_is_not_a_literal(self):
        class Thing:
            pass
        self.assertIsNone(_tally_literal(Thing()))

    def test_a_value_that_does_not_compare_equal_to_itself_is_not_offered(self):
        # `$ == nan` matches nothing, so there is no filter to offer.
        self.assertIsNone(_tally_literal(float('nan')))

    def test_the_literal_evaluates_back_to_the_value(self):
        for value in ('c', 5, None, True, (1, 'a')):
            with self.subTest(value=value):
                self.assertEqual(ast.literal_eval(_tally_literal(value)), value)


class TestTallySelection(unittest.TestCase):
    """Which rows are checked is read back out of the column search, so the
    search box stays the only place the filter lives."""

    def test_a_comparison_checks_one_value(self):
        self.assertEqual(_tally_selection({'op': '==', 'text': "'c'"}),
                         (["'c'"], False))

    def test_membership_checks_several(self):
        self.assertEqual(_tally_selection({'op': 'in', 'text': "['c', 'b']"}),
                         (["'c'", "'b'"], False))

    def test_the_negative_operators_read_as_excluding(self):
        self.assertEqual(_tally_selection({'op': '!=', 'text': "'c'"}),
                         (["'c'"], True))
        self.assertEqual(_tally_selection({'op': 'not in', 'text': "['c', 'b']"}),
                         (["'c'", "'b'"], True))

    def test_a_hand_typed_literal_is_normalized_to_match_its_row(self):
        # The tally renders 'c'; a search typed as "c" means the same value and
        # should show up as the same checked row.
        self.assertEqual(_tally_selection({'op': '==', 'text': '"c"'}),
                         (["'c'"], False))
        self.assertEqual(_tally_selection({'op': 'in', 'text': '("c",)'}),
                         (["'c'"], False))

    def test_a_search_the_tally_did_not_write_checks_nothing(self):
        for row in [{'op': '>=', 'text': '3'},
                    {'op': '', 'text': 'isOdd'},
                    {'op': '==', 'text': '$$ + 1'},
                    {'op': '==', 'text': ''},
                    {'op': 'in', 'text': '[]'},
                    {'op': 'in', 'text': 'threshold'}]:
            with self.subTest(row=row):
                self.assertEqual(_tally_selection(row)[0], [])

    def test_an_operator_the_tally_cannot_read_leaves_exclude_to_the_stored_bit(self):
        self.assertEqual(_tally_selection({'op': '>=', 'text': '3',
                                           'exclude': True}), ([], True))
        self.assertEqual(_tally_selection({'op': '>=', 'text': '3',
                                           'exclude': False}), ([], False))

    def test_the_operator_wins_over_a_stale_stored_bit(self):
        self.assertEqual(_tally_selection({'op': '!=', 'text': "'c'",
                                           'exclude': False}), (["'c'"], True))
        self.assertEqual(_tally_selection({'op': '==', 'text': "'c'",
                                           'exclude': True}), (["'c'"], False))


class TestWriteTallySelection(unittest.TestCase):
    """The 0/1/many choice of operator lives in one place, so every tally
    control agrees on it."""

    def write(self, literals, exclude=False):
        lst, model = tally_model()
        _write_tally_selection(model, '$', literals, exclude)
        return model

    def test_nothing_selected_is_no_filter(self):
        model = self.write([])
        self.assertIsNone(model['column_searches'])
        self.assertFalse(_column_search_active(model, '$'))

    def test_one_value_compares(self):
        row = self.write(["'c'"])['column_searches']['$']
        self.assertEqual((row['op'], row['text']), ('==', "'c'"))

    def test_several_values_use_membership(self):
        row = self.write(["'c'", "'b'"])['column_searches']['$']
        self.assertEqual((row['op'], row['text']), ('in', "['c', 'b']"))

    def test_excluding_negates_the_operator(self):
        row = self.write(["'c'"], exclude=True)['column_searches']['$']
        self.assertEqual((row['op'], row['text']), ('!=', "'c'"))
        row = self.write(["'c'", "'b'"], exclude=True)['column_searches']['$']
        self.assertEqual((row['op'], row['text']), ('not in', "['c', 'b']"))

    def test_excluding_nothing_keeps_the_bit_without_filtering(self):
        # Exclude can be ticked before any value is picked, and there is no
        # operator or text that says so.
        model = self.write([], exclude=True)
        self.assertTrue(model['column_searches']['$']['exclude'])
        self.assertFalse(_column_search_active(model, '$'))

    def test_the_written_search_round_trips_through_the_selection(self):
        for literals, exclude in [([], False), (["'c'"], False),
                                  (["'c'", "'b'"], False), (["'c'"], True),
                                  (["'c'", "'b'"], True), ([], True)]:
            with self.subTest(literals=literals, exclude=exclude):
                model = self.write(literals, exclude)
                self.assertEqual(_tally_selection(_column_search_row(model, '$')),
                                 (literals, exclude))


class TestTallyLiterals(unittest.TestCase):
    """The selectable literals of a column, in the order the tally shows them."""

    def test_in_first_seen_order(self):
        lst, model = tally_model()
        self.assertEqual(_tally_literals('$', model, lst),
                         ["'c'", "'aa'", "'b'"])

    def test_values_with_no_literal_are_left_out(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', Thing()]
        _, model = tally_model(lst)
        self.assertEqual(_tally_literals('$', model, lst), ["'c'"])

    def test_a_column_with_no_tally_offers_nothing(self):
        lst = list(range(TALLY_MAX_CARDINALITY + 1))
        _, model = tally_model(lst)
        self.assertEqual(_tally_literals('$', model, lst), [])


class TestTallyEvents(unittest.TestCase):
    """Clicking a tally row writes the column search, which is what filters."""

    def click(self, model, lst, event):
        return update(make_column_mouse_event(repr(event)), None, model, lst,
                      mock_get_visualizer, eval_in_scope=eval)

    def row(self, model):
        return _column_search_row(model, '$')

    def test_checking_one_value_compares_against_it(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('==', "'c'"))
        self.assertEqual(model['search'], "$ == 'c'")

    def test_checking_a_second_value_switches_to_membership(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'b'"))
        self.assertEqual(self.row(model)['text'], "['c', 'b']")
        self.assertEqual(model['search'], "$ in ['c', 'b']")

    def test_the_membership_list_follows_the_tally_order_not_the_click_order(self):
        # So the generated search is the same however the user got there.
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'b'"))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        self.assertEqual(self.row(model)['text'], "['c', 'b']")

    def test_unchecking_back_down_to_one_compares_again(self):
        lst, model = tally_model()
        for literal in ("'c'", "'aa'", "'b'"):
            model, _ = self.click(model, lst,
                                  TallyItemToggle(col=col_at(model), literal=literal))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        self.assertEqual(self.row(model)['text'], "['c', 'b']")
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'b'"))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('==', "'c'"))

    def test_unchecking_the_last_value_clears_the_filter(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        self.assertIsNone(model['column_searches'])
        self.assertIsNone(model['search'])

    def test_the_menu_stays_open_across_a_click(self):
        # The whole point is picking several values in a row.
        lst, model = tally_model()
        model['openDropdown'] = {'id': menu_id(model)}
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})

    def test_select_all_checks_every_value(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.row(model)['text'], "['c', 'aa', 'b']")

    def test_select_all_then_unchecking_a_few_is_the_quick_way_to_most_of_them(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        self.assertEqual(self.row(model)['text'], "['c', 'b']")

    def test_select_all_under_exclude_rejects_every_value(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        model, _ = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('not in', "['c', 'aa', 'b']"))

    def test_select_none_clears_the_filter(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model, _ = self.click(model, lst, TallySelectNone(col=col_at(model)))
        self.assertIsNone(model['search'])

    def test_select_none_keeps_exclude_and_compose(self):
        lst, model = tally_model()
        _set_column_search(model, '$', compose='or')
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        model, _ = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model, _ = self.click(model, lst, TallySelectNone(col=col_at(model)))
        self.assertTrue(self.row(model)['exclude'])
        self.assertEqual(self.row(model)['compose'], 'or')

    def test_excluding_a_selection_negates_the_operator_and_keeps_the_values(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('!=', "'c'"))
        self.assertEqual(model['search'], "$ != 'c'")
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'b'"))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('not in', "['c', 'b']"))

    def test_unexcluding_puts_the_operator_back(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        self.assertEqual((self.row(model)['op'], self.row(model)['text']),
                         ('==', "'c'"))

    def test_excluding_before_picking_anything_filters_nothing_yet(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        self.assertTrue(self.row(model)['exclude'])
        self.assertIsNone(model['search'])
        self.assertFalse(_column_search_active(model, '$'))

    def test_exclude_ticked_first_is_honored_by_the_next_click(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyExcludeToggle(col=col_at(model)))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        self.assertEqual(model['search'], "$ != 'c'")

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model()
        for event in [TallyItemToggle(col='$.gone', literal="'c'"),
                      TallySelectAll(col='$.gone'), TallySelectNone(col='$.gone'),
                      TallyExcludeToggle(col='$.gone')]:
            with self.subTest(event=event):
                model, _ = self.click(model, lst, event)
                self.assertIsNone(model['column_searches'])

    def test_a_tally_click_auto_links_a_filter_like_any_other_search(self):
        # The tally writes the column search and stops there: filtering and code
        # generation are the search box's job, unchanged.
        lst, model = tally_model()
        eval_in_scope = lambda code: eval(code, {}, {'data': lst})
        model, commands = update(
            make_column_mouse_event(repr(TallyItemToggle(col=col_at(model), literal="'c'"))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=eval_in_scope)
        self.assertEqual([c[1] for c in commands if isinstance(c, tuple)],
                         ["[item for item in data if item == 'c']"])
        self.assertEqual(model['linked_action'], 'filter')

    def test_the_tally_filters_the_rows_it_counted(self):
        lst, model = tally_model()
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model, _ = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        self.assertEqual(_get_matching_indices(model['search'], lst, eval),
                         [0, 1, 3, 5, 6, 7, 8])


class TestTallyRendering(unittest.TestCase):
    """The tally sits at the bottom of the column ▾ menu, below the search row
    it writes into."""

    def open_menu_html(self, model, lst, column=0):
        model['openDropdown'] = {'id': menu_id(model, index=column)}
        return _first_column_header(visualize(lst, model, mock_get_visualizer,
                                              None))

    def tally(self, th):
        self.assertIn('<div class="col-tally">', th)
        return th[th.index('<div class="col-tally">'):]

    def rows(self, tally):
        return re.findall(r'<div class="col-tally-row[^"]*".*?</div>', tally,
                          re.DOTALL)

    def checkboxes(self, markup):
        return re.findall(r'<input[^>]*col-tally-check[^>]*>', markup)

    def test_a_closed_menu_counts_nothing(self):
        lst, model = tally_model()
        self.assertNotIn('col-tally', visualize(lst, model, mock_get_visualizer,
                                                None))

    def test_items_and_counts_in_first_seen_order(self):
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertEqual(re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally),
                         [html.escape(repr(v)) for v in ('c', 'aa', 'b')])
        self.assertEqual(re.findall(r'col-tally-count">([^<]*)<', tally),
                         ['5', '2', '3'])

    def test_the_section_says_what_it_is(self):
        # The title sits on the border, so it reads before everything below it.
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn('<div class="col-tally-title"><span '
                      'class="col-tally-title-text">Tally</span></div>', tally)
        self.assertLess(tally.index('col-tally-title'),
                        tally.index('col-tally-row'))

    def test_the_two_columns_of_values_are_named(self):
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertEqual(
            re.findall(r'col-tally-(?:item|count)-header">([^<]*)<', tally),
            ['Items', 'Counts'])
        # The names head the list, so they read before it and not among it.
        self.assertLess(tally.index('col-tally-list-header'),
                        tally.index('col-tally-list"'))
        self.assertNotIn('-header', tally[tally.index('col-tally-list"'):])

    def test_a_note_stands_in_for_the_columns_that_are_not_there(self):
        # Nothing is listed, so naming columns for it would name nothing.
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn('col-tally-title', tally)
        self.assertNotIn('col-tally-list-header', tally)

    def test_the_tally_comes_after_the_search_row_it_writes_into(self):
        lst, model = tally_model()
        th = self.open_menu_html(model, lst)
        self.assertLess(th.index('col-search-area'), th.index('col-tally'))

    def test_each_row_carries_its_own_literal(self):
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn(html.escape(repr(TallyItemToggle(col=col_at(model), literal="'c'"))),
                      tally)

    def test_every_row_carries_a_real_checkbox(self):
        # Not a glyph: it should look and read like any other checkbox. The row
        # owns the click, so the box only ever reports what the search says.
        lst, model = tally_model()
        boxes = self.checkboxes(self.tally(self.open_menu_html(model, lst)))
        self.assertEqual(len(boxes), 4)  # one per value, plus Exclude
        for box in boxes:
            self.assertIn('type="checkbox"', box)

    def test_the_checked_row_is_the_one_the_search_names(self):
        lst, model = tally_model()
        _set_column_search(model, '$', op='==', text="'aa'")
        rows = self.rows(self.tally(self.open_menu_html(model, lst)))
        self.assertEqual([' checked' in row for row in rows],
                         [False, True, False])
        self.assertEqual([' checked' in self.checkboxes(row)[0] for row in rows],
                         [False, True, False])

    def test_a_hand_written_search_checks_nothing(self):
        lst, model = tally_model()
        _set_column_search(model, '$', op='', text='isOdd')
        rows = self.rows(self.tally(self.open_menu_html(model, lst)))
        self.assertEqual([' checked' in row for row in rows], [False] * 3)

    def test_a_value_with_no_literal_cannot_be_checked(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', Thing()]
        _, model = tally_model(lst)
        rows = self.rows(self.tally(self.open_menu_html(model, lst)))
        self.assertEqual(len(rows), 2)
        self.assertIn('TallyItemToggle', rows[0])
        self.assertNotIn('TallyItemToggle', rows[1])
        self.assertIn('unselectable', rows[1])
        # Its box says as much, rather than looking clickable and doing nothing.
        self.assertNotIn('disabled', self.checkboxes(rows[0])[0])
        self.assertIn('disabled', self.checkboxes(rows[1])[0])

    def test_the_header_offers_select_all_select_none_and_exclude(self):
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn(html.escape(repr(TallySelectAll(col=col_at(model)))), tally)
        self.assertIn(html.escape(repr(TallySelectNone(col=col_at(model)))), tally)
        self.assertIn(html.escape(repr(TallyExcludeToggle(col=col_at(model)))), tally)
        self.assertIn('Exclude', tally)
        # The header reads before the values it acts on.
        self.assertLess(tally.index('col-tally-controls'),
                        tally.index('col-tally-row'))

    def test_exclude_shows_whether_it_is_ticked(self):
        # It heads the tally, so its box is the first one.
        lst, model = tally_model()
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertNotIn(' checked', self.checkboxes(tally)[0])
        _set_column_search(model, '$', op='!=', text="'c'")
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn(' checked', self.checkboxes(tally)[0])

    def test_too_many_distinct_values_says_so_instead(self):
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn('col-tally-note', tally)
        self.assertIn(str(TALLY_MAX_CARDINALITY), tally)
        self.assertEqual(self.rows(tally), [])
        self.assertNotIn('TallySelectAll', tally)

    def test_values_that_cannot_be_counted_say_so_instead(self):
        lst = [{'a': 1}, {'a': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['$']
        tally = self.tally(self.open_menu_html(model, lst))
        self.assertIn('col-tally-note', tally)
        self.assertEqual(self.rows(tally), [])

    def test_an_empty_table_has_no_tally_at_all(self):
        lst = []
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['$']
        model['openDropdown'] = {'id': menu_id(model)}
        self.assertNotIn('col-tally',
                         visualize(lst, model, mock_get_visualizer, None))

    def test_a_computed_column_tallies_its_own_values(self):
        lst = [{'name': 'Alice'}, {'name': 'Bo'}, {'name': 'Cy'}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['len($["name"])']
        model['openDropdown'] = {'id': menu_id(model)}
        eval_in_scope = lambda code: eval(code, {'len': len}, {'data': lst})
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            eval_in_scope))
        tally = self.tally(th)
        self.assertEqual(re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally),
                         ['5', '2'])
        self.assertEqual(re.findall(r'col-tally-count">([^<]*)<', tally),
                         ['1', '2'])

    def test_a_long_value_is_truncated_for_display_but_not_for_the_filter(self):
        lst = ['x' * 200, 'y']
        _, model = tally_model(lst)
        tally = self.tally(self.open_menu_html(model, lst))
        shown = re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally)[0]
        self.assertIn('…', shown)
        self.assertIn(html.escape(repr('x' * 200)), tally)


def make_tally_filter_event(col, value):
    """Create a TallyFilterInput event for the column at *index*."""
    return {
        'pythonEventStr': (f"lambda e: TallyFilterInput(col={col!r}, "
                           f"value=e.get('value', ''))"),
        'eventJSON': {'type': 'input', 'value': value},
    }


class TestTallyShows(unittest.TestCase):
    """What the tally's filter box keeps on show: a plain substring of the row,
    read the way the row reads."""

    def test_a_substring_of_the_row_shows_it(self):
        self.assertTrue(_tally_shows('a', "'aa'"))
        self.assertFalse(_tally_shows('z', "'aa'"))

    def test_no_text_shows_everything(self):
        self.assertTrue(_tally_shows('', "'aa'"))

    def test_surrounding_space_is_not_part_of_the_search(self):
        # A trailing space shouldn't empty the list out from under the user.
        self.assertTrue(_tally_shows('  ', "'aa'"))
        self.assertTrue(_tally_shows(' a ', "'aa'"))

    def test_case_does_not_matter(self):
        self.assertTrue(_tally_shows('ALI', "'Alice'"))
        self.assertTrue(_tally_shows('ali', "'ALICE'"))

    def test_the_row_is_matched_as_it_reads(self):
        # Which is the repr, quotes and all -- the same string the row's
        # literal is, so the search box and the display agree on what showed.
        self.assertTrue(_tally_shows("'a", "'aa'"))
        self.assertTrue(_tally_shows('1', '10'))
        self.assertFalse(_tally_shows('1', '20'))


class TestTallyFilterBox(unittest.TestCase):
    """The box above the tally narrows which values the menu lists. It's a way
    of finding a value to click, not a filter on the table: nothing it does
    reaches the column search."""

    def type(self, model, lst, text, index=0, col=None):
        col = col_at(model, index) if col is None else col
        model, _ = update(make_tally_filter_event(col, text), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def click(self, model, lst, event):
        model, _ = update(make_column_mouse_event(repr(event)), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def tally(self, model, lst, column=0):
        model['openDropdown'] = {'id': menu_id(model, index=column)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertIn('<div class="col-tally">', th)
        return th[th.index('<div class="col-tally">'):]

    def items(self, tally):
        return re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally)

    def counts(self, tally):
        return re.findall(r'col-tally-count">([^<]*)<', tally)

    def text(self, model):
        return _column_search_row(model, '$')['text']

    def test_the_box_sits_above_the_values_it_narrows(self):
        lst, model = tally_model()
        tally = self.tally(model, lst)
        self.assertIn('col-tally-filter', tally)
        self.assertIn(html.escape(f'TallyFilterInput(col={col_at(model)!r}'), tally)
        self.assertLess(tally.index('col-tally-filter'),
                        tally.index('col-tally-row'))

    def test_typing_narrows_the_values_shown(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('aa'))])

    def test_the_counts_are_still_of_the_whole_column(self):
        # Hiding a row doesn't change how many rows the ones left have.
        lst, model = tally_model()
        model = self.type(model, lst, 'b')
        self.assertEqual(self.counts(self.tally(model, lst)), ['3'])

    def test_the_box_shows_what_was_typed(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'aa')
        self.assertIn('value="aa"', self.tally(model, lst))

    def test_a_value_is_matched_past_where_it_is_elided(self):
        # The row shows a middle-elided repr; the filter reads the whole one.
        lst = ['x' * 200 + 'zed', 'y']
        _, model = tally_model(lst)
        model = self.type(model, lst, 'zed')
        self.assertEqual(len(self.items(self.tally(model, lst))), 1)

    def test_a_value_with_no_literal_is_narrowed_like_any_other(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', Thing()]
        _, model = tally_model(lst)
        model = self.type(model, lst, 'thing')
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [html.escape('<thing>')])
        self.assertIn('unselectable', tally)

    def test_nothing_matching_says_so_rather_than_showing_a_blank(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'zzz')
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [])
        self.assertIn('col-tally-note', tally)
        # And the box stays, since it's the only way back to the values.
        self.assertIn('col-tally-filter', tally)

    def test_a_tally_that_is_only_a_note_has_nothing_to_narrow(self):
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        self.assertNotIn('col-tally-filter', self.tally(model, lst))

    def test_narrowing_the_list_is_not_a_filter_on_the_table(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'aa')
        self.assertIsNone(model['column_searches'])
        self.assertIsNone(model['search'])

    def test_a_checked_value_stays_checked_while_it_is_hidden(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model = self.type(model, lst, 'aa')
        self.assertEqual(model['search'], "$ == 'c'")

    def test_the_box_survives_picking_values(self):
        # Narrowing down and then ticking a few is the whole point of it.
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        self.assertEqual(model['tally_filter'], 'a')
        self.assertEqual(model['search'], "$ == 'aa'")

    def test_select_all_takes_only_the_values_on_show(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "'aa'")

    def test_select_all_leaves_a_hidden_selection_alone(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model = self.type(model, lst, 'b')
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "['c', 'b']")

    def test_select_none_only_unchecks_what_is_on_show(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model = self.type(model, lst, 'b')
        model = self.click(model, lst, TallySelectNone(col=col_at(model)))
        self.assertEqual(self.text(model), "['c', 'aa']")

    def test_an_empty_box_still_reaches_every_value(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'b')
        model = self.type(model, lst, '')
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "['c', 'aa', 'b']")

    def test_closing_the_menu_forgets_what_was_typed(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-0'))
        self.assertEqual(model['tally_filter'], '')

    def test_another_column_starts_with_an_empty_box(self):
        lst, model = tally_model()
        model['columns'] = ['$', 'len($)']
        model = self.type(model, lst, 'a')
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-1'))
        self.assertEqual(model['tally_filter'], '')

    def test_escape_forgets_what_was_typed(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        model['openDropdown'] = {'id': menu_id(model)}
        model, _ = update(make_column_key_event('Escape'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['tally_filter'], '')

    def test_a_menu_the_columns_moved_out_from_under_forgets_it_too(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a')
        model = self.click(model, lst, AddColumnClick())
        self.assertEqual(model['tally_filter'], '')

    def test_typing_into_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model()
        model = self.type(model, lst, 'a', col='$.gone')
        self.assertEqual(model['tally_filter'], '')


class TestSortedTally(unittest.TestCase):
    """The order the tally lists a column's values in."""

    def sorted(self, tally, sort):
        return [value for value, _count in _sorted_tally(tally, sort)]

    def test_first_is_the_order_the_values_were_counted_in(self):
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'first'),
                         ['c', 'aa', 'b'])

    def test_common_puts_the_most_frequent_first(self):
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'common'),
                         ['c', 'b', 'aa'])

    def test_rare_puts_the_least_frequent_first(self):
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'rare'),
                         ['aa', 'b', 'c'])

    def test_the_item_orders_sort_by_the_value_itself(self):
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'item asc'),
                         ['aa', 'b', 'c'])
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'item desc'),
                         ['c', 'b', 'aa'])

    def test_numbers_sort_as_numbers_and_not_as_text(self):
        self.assertEqual(self.sorted(_tally([2, 10, 9]), 'item asc'),
                         [2, 9, 10])

    def test_counts_travel_with_their_values(self):
        self.assertEqual(_sorted_tally(_tally(TALLY_LIST), 'common'),
                         [('c', 5), ('b', 3), ('aa', 2)])

    def test_values_an_order_cannot_tell_apart_keep_first_seen_order(self):
        self.assertEqual(self.sorted({'b': 2, 'a': 2, 'c': 1}, 'common'),
                         ['b', 'a', 'c'])
        self.assertEqual(self.sorted({'b': 1, 'a': 1, 'c': 2}, 'rare'),
                         ['b', 'a', 'c'])

    def test_values_that_cannot_be_compared_fall_back_to_how_they_read(self):
        # A mixed column has no order of its own, but its rows still read in
        # some order: sorting the reprs is at least the order shown on screen.
        self.assertEqual(self.sorted({1: 1, 'a': 1, 2: 1}, 'item asc'),
                         ['a', 1, 2])
        self.assertEqual(self.sorted({1: 1, 'a': 1, 2: 1}, 'item desc'),
                         [2, 1, 'a'])

    def test_an_order_it_does_not_know_is_first_seen_order(self):
        self.assertEqual(self.sorted(_tally(TALLY_LIST), 'sideways'),
                         ['c', 'aa', 'b'])


class TestTallySortMenu(unittest.TestCase):
    """The Sort by chip above the tally sets the order its values are listed
    in. Display only, like the filter box beside it: it decides what the menu
    shows, never what the column search says."""

    def click(self, model, lst, event):
        model, _ = update(make_column_mouse_event(repr(event)), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def tally(self, model, lst, column=0):
        model['openDropdown'] = {'id': menu_id(model, index=column)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertIn('<div class="col-tally">', th)
        return th[th.index('<div class="col-tally">'):]

    def chip(self, tally):
        """The chip itself, cut off before the panel of options below it."""
        start = tally.index('col-tally-sort')
        end = tally.find('snc-dropdown-panel', start)
        return tally[start:end if end != -1 else len(tally)]

    def items(self, tally):
        return re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally)

    def counts(self, tally):
        return re.findall(r'col-tally-count">([^<]*)<', tally)

    def text(self, model):
        return _column_search_row(model, '$')['text']

    def open_chip(self, model, index=0):
        model['col_search_dropdown'] = menu_id(model, 'tally-sort', index)
        return model

    def test_a_column_starts_in_first_seen_order(self):
        _, model = tally_model()
        self.assertEqual(model['tally_sort'], TALLY_SORT_DEFAULT)
        self.assertEqual(TALLY_SORT_DEFAULT, 'first')

    def test_the_chip_sits_above_the_values_it_orders(self):
        lst, model = tally_model()
        tally = self.tally(model, lst)
        self.assertIn('col-tally-sort', tally)
        self.assertIn('Sort:', tally)
        self.assertLess(tally.index('col-tally-sort'),
                        tally.index('col-tally-row'))

    def test_the_chip_shows_the_order_in_force(self):
        lst, model = tally_model()
        self.assertIn('First', self.chip(self.tally(model, lst)))
        model['tally_sort'] = 'item desc'
        self.assertIn('Item Desc', self.chip(self.tally(model, lst)))

    def test_the_orders_read_as_menu_items_rather_than_as_model_values(self):
        lst, model = tally_model()
        tally = self.tally(self.open_chip(model), lst)
        self.assertEqual(re.findall(r'col-tally-sort-value[^>]*>([^<]*)<',
                                    tally),
                         ['First', 'First', 'Common', 'Rare', 'Item Asc',
                          'Item Desc'])  # the chip, then its five options

    def test_the_open_chip_offers_every_order(self):
        lst, model = tally_model()
        tally = self.tally(self.open_chip(model), lst)
        for sort in TALLY_SORTS:
            with self.subTest(sort=sort):
                self.assertIn(
                    html.escape(repr(TallySortSelect(col=col_at(model), sort=sort))),
                    tally)
        self.assertEqual(TALLY_SORTS,
                         ('first', 'common', 'rare', 'item asc', 'item desc'))

    def test_the_order_in_force_is_the_marked_option(self):
        lst, model = tally_model()
        model['tally_sort'] = 'rare'
        tally = self.tally(self.open_chip(model), lst)
        marked = re.findall(r'snc-dropdown-option selected.*?>([^<]*)</span>',
                            tally)
        self.assertEqual(marked, ['Rare'])

    def test_picking_an_order_records_it_and_closes_the_chip(self):
        lst, model = tally_model()
        model = self.open_chip(model)
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        self.assertEqual(model['tally_sort'], 'common')
        self.assertIsNone(model['col_search_dropdown'])

    def test_the_column_menu_stays_open_across_a_pick(self):
        # Reordering is a step on the way to picking values, not a way out.
        lst, model = tally_model()
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})

    def test_an_order_it_does_not_know_is_ignored(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='sideways'))
        self.assertEqual(model['tally_sort'], 'first')

    def test_picking_on_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col='$.gone', sort='common'))
        self.assertEqual(model['tally_sort'], 'first')

    def test_reordering_is_not_a_filter_on_the_table(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        self.assertIsNone(model['column_searches'])
        self.assertIsNone(model['search'])

    def test_the_rows_are_listed_in_the_chosen_order(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally),
                         [html.escape(repr(v)) for v in ('c', 'b', 'aa')])
        self.assertEqual(self.counts(tally), ['5', '3', '2'])

    def test_reordering_leaves_the_checked_rows_checked(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        rows = re.findall(r'<div class="col-tally-row[^"]*".*?</div>',
                          self.tally(model, lst), re.DOTALL)
        self.assertEqual([' checked' in row for row in rows],
                         [False, False, True])
        self.assertEqual(model['search'], "$ == 'aa'")

    def test_the_selectable_literals_follow_the_chosen_order(self):
        lst, model = tally_model()
        model['tally_sort'] = 'item asc'
        self.assertEqual(_tally_literals('$', model, lst),
                         ["'aa'", "'b'", "'c'"])

    def test_the_membership_list_follows_the_chosen_order(self):
        # The search reads the way the list the user clicked through read.
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='rare'))
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'c'"))
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        self.assertEqual(self.text(model), "['aa', 'c']")

    def test_select_all_follows_the_chosen_order(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "['c', 'b', 'aa']")

    def test_the_filter_box_narrows_whatever_order_is_in_force(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='item asc'))
        model, _ = update(make_tally_filter_event(col_at(model), 'a'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('aa'))])

    def test_a_tally_that_is_only_a_note_has_nothing_to_order(self):
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        self.assertNotIn('col-tally-sort', self.tally(model, lst))

    def test_closing_the_menu_forgets_the_order(self):
        # Like the filter box: a way of reaching a value, not a setting to keep.
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-0'))
        self.assertEqual(model['tally_sort'], TALLY_SORT_DEFAULT)

    def test_another_column_starts_in_first_seen_order(self):
        lst, model = tally_model()
        model['columns'] = ['$', 'len($)']
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-1'))
        self.assertEqual(model['tally_sort'], TALLY_SORT_DEFAULT)

    def test_escape_forgets_the_order(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        model['openDropdown'] = {'id': menu_id(model)}
        model, _ = update(make_column_key_event('Escape'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['tally_sort'], TALLY_SORT_DEFAULT)

    def test_a_menu_the_columns_moved_out_from_under_forgets_it_too(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='common'))
        model = self.click(model, lst, AddColumnClick())
        self.assertEqual(model['tally_sort'], TALLY_SORT_DEFAULT)


def make_tally_count_filter_event(col, value):
    """Create a TallyCountFilterInput event for the column at *index*."""
    return {
        'pythonEventStr': (f"lambda e: TallyCountFilterInput(col={col!r}, "
                           f"value=e.get('value', ''))"),
        'eventJSON': {'type': 'input', 'value': value},
    }


class TestTallyCountShows(unittest.TestCase):
    """What the tally's count box keeps on show: a comparison against how many
    rows a value has, or -- for Min and Max -- against the extreme count the
    list itself has."""

    def test_no_number_shows_everything(self):
        for op in TALLY_COUNT_OPS:
            if op in TALLY_COUNT_EXTREME_OPS:
                continue
            with self.subTest(op=op):
                self.assertTrue(_tally_count_shows(op, '', 3))

    def test_at_least_keeps_the_counts_that_reach_it(self):
        self.assertTrue(_tally_count_shows('>=', '3', 5))
        self.assertTrue(_tally_count_shows('>=', '3', 3))
        self.assertFalse(_tally_count_shows('>=', '3', 2))

    def test_exactly_keeps_only_that_count(self):
        self.assertTrue(_tally_count_shows('==', '3', 3))
        self.assertFalse(_tally_count_shows('==', '3', 2))
        self.assertFalse(_tally_count_shows('==', '3', 4))

    def test_at_most_keeps_the_counts_under_it(self):
        self.assertTrue(_tally_count_shows('<=', '3', 2))
        self.assertTrue(_tally_count_shows('<=', '3', 3))
        self.assertFalse(_tally_count_shows('<=', '3', 5))

    def test_surrounding_space_is_not_part_of_the_number(self):
        self.assertTrue(_tally_count_shows('==', ' 3 ', 3))

    def test_text_that_is_not_yet_a_count_filters_nothing(self):
        # A half-typed number shouldn't empty the list out from under the user,
        # and neither should one that never becomes a count.
        for text in ('-', '1.5', 'abc', '3a'):
            with self.subTest(text=text):
                self.assertTrue(_tally_count_shows('>=', text, 1))

    def test_an_operator_it_does_not_know_filters_nothing(self):
        self.assertTrue(_tally_count_shows('in', '3', 5))

    def test_min_and_max_keep_only_the_extreme_count(self):
        for op in TALLY_COUNT_EXTREME_OPS:
            with self.subTest(op=op):
                self.assertTrue(_tally_count_shows(op, '', 2, 2))
                self.assertFalse(_tally_count_shows(op, '', 3, 2))

    def test_the_typed_number_has_nothing_to_say_to_min_and_max(self):
        # They disable the box, so whatever it was left holding is not a filter.
        self.assertTrue(_tally_count_shows('min', '9', 2, 2))
        self.assertFalse(_tally_count_shows('min', '3', 3, 2))

    def test_min_and_max_with_no_extreme_to_speak_of_show_nothing(self):
        for op in TALLY_COUNT_EXTREME_OPS:
            with self.subTest(op=op):
                self.assertFalse(_tally_count_shows(op, '', 2, None))


class TestTallyCountFilterNamesTheProgramsValues(unittest.TestCase):
    """The count box compares against a whole number, and a number can be
    written the way every other box in the visualizer writes one: as the
    program's own names and expressions, not only as digits."""

    def test_a_variable_is_the_count_to_compare_against(self):
        scope = program_scope(n=3)
        self.assertTrue(_tally_count_shows('>=', 'n', 5, eval_in_scope=scope))
        self.assertTrue(_tally_count_shows('>=', 'n', 3, eval_in_scope=scope))
        self.assertFalse(_tally_count_shows('>=', 'n', 2, eval_in_scope=scope))

    def test_an_expression_is_the_count_to_compare_against(self):
        scope = program_scope(strs=['a', 'b', 'c', 'd'])
        self.assertTrue(_tally_count_shows('==', 'len(strs) // 2', 2,
                                           eval_in_scope=scope))
        self.assertFalse(_tally_count_shows('==', 'len(strs) // 2', 3,
                                            eval_in_scope=scope))

    def test_digits_still_ask_the_scope_for_nothing(self):
        # The common case stays what it was, scope or no scope: a box holding a
        # number has no name in it to look up.
        for scope in (None, program_scope()):
            with self.subTest(scope=scope):
                self.assertTrue(_tally_count_shows('>=', '3', 3,
                                                   eval_in_scope=scope))
                self.assertFalse(_tally_count_shows('>=', '3', 2,
                                                    eval_in_scope=scope))

    def test_a_name_the_program_does_not_define_filters_nothing(self):
        # Same as a half-typed number: an empty list is a poor answer to text
        # the box can't compare against.
        for count in (1, 5):
            with self.subTest(count=count):
                self.assertTrue(_tally_count_shows('==', 'nope', count,
                                                   eval_in_scope=program_scope()))

    def test_an_expression_that_is_not_a_whole_number_filters_nothing(self):
        scope = program_scope(n=5)
        for text in ('n / 2', "'a'", 'None', '[1]'):
            with self.subTest(text=text):
                self.assertTrue(_tally_count_shows('==', text, 2,
                                                   eval_in_scope=scope))

    def test_a_whole_number_that_arrived_as_a_float_is_still_a_count(self):
        scope = program_scope(n=4)
        self.assertTrue(_tally_count_shows('==', 'n / 2', 2,
                                           eval_in_scope=scope))
        self.assertFalse(_tally_count_shows('==', 'n / 2', 3,
                                            eval_in_scope=scope))

    def test_a_boolean_is_not_a_count(self):
        # True == 1, but nobody means "values one row has" by naming a flag.
        scope = program_scope(flag=True)
        for count in (1, 2):
            with self.subTest(count=count):
                self.assertTrue(_tally_count_shows('==', 'flag', count,
                                                   eval_in_scope=scope))

    def test_min_and_max_still_ignore_whatever_the_box_holds(self):
        scope = program_scope(n=9)
        self.assertTrue(_tally_count_shows('min', 'n', 2, 2,
                                           eval_in_scope=scope))
        self.assertFalse(_tally_count_shows('min', 'n', 3, 2,
                                            eval_in_scope=scope))

    def test_an_expression_narrows_the_values_the_menu_lists(self):
        # 'c' has 5 rows, 'b' 3 and 'aa' 2, so `>= n` with n = 3 drops 'aa'.
        lst, model = tally_model()
        model['tally_count_filter'] = 'n'
        model['openDropdown'] = {'id': menu_id(model)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            program_scope(n=3)))
        self.assertEqual(re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', th),
                         [html.escape(repr(v)) for v in ('c', 'b')])

    def test_all_reaches_only_what_the_expression_leaves_on_show(self):
        lst, model = tally_model()
        model['tally_count_filter'] = 'n'
        model, _ = update(make_column_mouse_event(repr(TallySelectAll(col=col_at(model)))),
                          None, model, lst, mock_get_visualizer,
                          eval_in_scope=program_scope(n=3))
        self.assertEqual(_column_search_row(model, '$')['text'], "['c', 'b']")


class TestTallyExtreme(unittest.TestCase):
    """The count Min and Max are looking for: how many rows the least or most
    common value on show has."""

    ROWS = [("'c'", 5, "'c'"), ("'aa'", 2, "'aa'"), ("'b'", 3, "'b'")]

    def model(self, op, filter_text=''):
        return {'tally_count_op': op, 'tally_filter': filter_text}

    def test_a_comparison_is_not_looking_for_one(self):
        for op in ('>=', '==', '<='):
            with self.subTest(op=op):
                self.assertIsNone(_tally_extreme(self.model(op), self.ROWS))

    def test_min_is_the_count_of_the_least_common_value(self):
        self.assertEqual(_tally_extreme(self.model('min'), self.ROWS), 2)

    def test_max_is_the_count_of_the_most_common_value(self):
        self.assertEqual(_tally_extreme(self.model('max'), self.ROWS), 5)

    def test_the_filter_box_narrows_first(self):
        # Min and Max answer about the list in front of the user, not one it's
        # hiding -- so the two boxes together can't argue their way to nothing.
        self.assertEqual(_tally_extreme(self.model('max', 'a'), self.ROWS), 2)
        self.assertEqual(_tally_extreme(self.model('min', 'b'), self.ROWS), 3)

    def test_nothing_left_to_be_extreme_is_no_count_at_all(self):
        self.assertIsNone(_tally_extreme(self.model('min', 'zz'), self.ROWS))
        self.assertIsNone(_tally_extreme(self.model('min'), []))

    def test_a_value_with_no_literal_still_counts_towards_it(self):
        # It's a row of the list the user is reading, so it's part of what the
        # least and most common are measured against.
        rows = [("'c'", 5, "'c'"), ('<thing>', 1, None)]
        self.assertEqual(_tally_extreme(self.model('min'), rows), 1)


class TestTallyCountFilterBox(unittest.TestCase):
    """The count box beside the Sort by chip narrows the tally to the values of
    a given frequency. Display only, like the boxes around it: it decides which
    values the menu lists, never what the column search says."""

    def type(self, model, lst, text, index=0, col=None):
        col = col_at(model, index) if col is None else col
        model, _ = update(make_tally_count_filter_event(col, text), None,
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def type_value(self, model, lst, text, index=0, col=None):
        col = col_at(model, index) if col is None else col
        model, _ = update(make_tally_filter_event(col, text), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def click(self, model, lst, event):
        model, _ = update(make_column_mouse_event(repr(event)), None, model,
                          lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def tally(self, model, lst, column=0):
        model['openDropdown'] = {'id': menu_id(model, index=column)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertIn('<div class="col-tally">', th)
        return th[th.index('<div class="col-tally">'):]

    def chip(self, tally):
        """The chip itself, cut off before the panel of options below it."""
        start = tally.index('col-tally-count-op')
        end = tally.find('snc-dropdown-panel', start)
        return tally[start:end if end != -1 else len(tally)]

    def items(self, tally):
        return re.findall(r'col-tally-item[ "][^>]*>([^<]*)<', tally)

    def counts(self, tally):
        return re.findall(r'col-tally-count">([^<]*)<', tally)

    def text(self, model):
        return _column_search_row(model, '$')['text']

    def open_chip(self, model, index=0):
        model['col_search_dropdown'] = menu_id(model, 'tally-count-op', index)
        return model

    def test_a_column_starts_out_comparing_with_at_least(self):
        _, model = tally_model()
        self.assertEqual(model['tally_count_op'], TALLY_COUNT_OP_DEFAULT)
        self.assertEqual(model['tally_count_filter'], '')
        self.assertEqual(TALLY_COUNT_OP_DEFAULT, '>=')

    def test_the_box_sits_above_the_values_it_narrows(self):
        lst, model = tally_model()
        tally = self.tally(model, lst)
        self.assertIn('col-tally-count-filter', tally)
        self.assertIn(html.escape(f'TallyCountFilterInput(col={col_at(model)!r}'), tally)
        self.assertLess(tally.index('col-tally-count-filter'),
                        tally.index('col-tally-row'))

    def test_typing_a_count_narrows_the_values_shown(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally),
                         [html.escape(repr(v)) for v in ('c', 'b')])
        # And the counts are still of the whole column.
        self.assertEqual(self.counts(tally), ['5', '3'])

    def test_the_box_shows_what_was_typed(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        self.assertIn('value="3"', self.tally(model, lst))

    def test_the_chip_shows_the_comparison_in_force(self):
        lst, model = tally_model()
        self.assertIn('&gt;=', self.chip(self.tally(model, lst)))
        model['tally_count_op'] = '<='
        self.assertIn('&lt;=', self.chip(self.tally(model, lst)))

    def test_the_open_chip_offers_the_five_choices_and_no_others(self):
        lst, model = tally_model()
        tally = self.tally(self.open_chip(model), lst)
        for op in TALLY_COUNT_OPS:
            with self.subTest(op=op):
                self.assertIn(
                    html.escape(repr(TallyCountOpSelect(col=col_at(model), op=op))), tally)
        self.assertEqual(TALLY_COUNT_OPS, ('>=', '==', '<=', 'min', 'max'))
        for op in ('>', '<', '!=', 'in', 'not in'):
            with self.subTest(op=op):
                self.assertNotIn(
                    html.escape(repr(TallyCountOpSelect(col=col_at(model), op=op))), tally)

    def test_the_comparison_in_force_is_the_marked_option(self):
        lst, model = tally_model()
        model['tally_count_op'] = '<='
        tally = self.tally(self.open_chip(model), lst)
        marked = re.findall(r'snc-dropdown-option selected.*?>([^<]*)</span>',
                            tally)
        self.assertEqual(marked, ['&lt;='])

    def test_picking_a_comparison_records_it_and_closes_the_chip(self):
        lst, model = tally_model()
        model = self.open_chip(model)
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='=='))
        self.assertEqual(model['tally_count_op'], '==')
        self.assertIsNone(model['col_search_dropdown'])

    def test_picking_a_comparison_narrows_what_was_already_typed(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='=='))
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('b'))])

    def test_the_column_menu_stays_open_across_a_pick(self):
        # Narrowing is a step on the way to picking values, not a way out.
        lst, model = tally_model()
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='<='))
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})

    def test_a_comparison_it_does_not_know_is_ignored(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='>'))
        self.assertEqual(model['tally_count_op'], TALLY_COUNT_OP_DEFAULT)

    def test_acting_on_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3', col='$.gone')
        self.assertEqual(model['tally_count_filter'], '')
        model = self.click(model, lst, TallyCountOpSelect(col='$.gone', op='=='))
        self.assertEqual(model['tally_count_op'], TALLY_COUNT_OP_DEFAULT)

    def test_narrowing_by_count_is_not_a_filter_on_the_table(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='<='))
        self.assertIsNone(model['column_searches'])
        self.assertIsNone(model['search'])

    def test_the_two_boxes_narrow_together(self):
        lst, model = tally_model()
        model = self.type_value(model, lst, 'a')
        model = self.type(model, lst, '2')
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('aa'))])
        model = self.type(model, lst, '3')
        self.assertEqual(self.items(self.tally(model, lst)), [])

    def test_a_value_with_no_literal_is_narrowed_like_any_other(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', 'c', Thing()]
        _, model = tally_model(lst)
        model = self.type(model, lst, '2')
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [html.escape(repr('c'))])
        self.assertNotIn('unselectable', tally)

    def test_nothing_matching_says_so_rather_than_showing_a_blank(self):
        lst, model = tally_model()
        model = self.type(model, lst, '9')
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [])
        self.assertIn('col-tally-note', tally)
        # And the box stays, since it's the only way back to the values.
        self.assertIn('col-tally-count-filter', tally)

    def test_a_tally_that_is_only_a_note_has_nothing_to_narrow(self):
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        self.assertNotIn('col-tally-count-filter', self.tally(model, lst))

    def test_a_checked_value_stays_checked_while_it_is_hidden(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyItemToggle(col=col_at(model), literal="'aa'"))
        model = self.type(model, lst, '3')
        self.assertEqual(model['search'], "$ == 'aa'")

    def test_select_all_takes_only_the_values_on_show(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "['c', 'b']")

    def test_select_none_only_unchecks_what_is_on_show(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallySelectNone(col=col_at(model)))
        self.assertEqual(self.text(model), "'aa'")

    def box(self, tally):
        """The count input itself."""
        return re.search(r'<input[^>]*col-tally-count-filter[^>]*/>',
                         tally).group(0)

    def test_min_shows_the_least_common_values(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='min'))
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [html.escape(repr('aa'))])
        self.assertEqual(self.counts(tally), ['2'])

    def test_max_shows_the_most_common_values(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [html.escape(repr('c'))])
        self.assertEqual(self.counts(tally), ['5'])

    def test_values_that_tie_for_extreme_all_show(self):
        lst = ['a', 'a', 'b', 'b', 'c']
        _, model = tally_model(lst)
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr(v)) for v in ('a', 'b')])

    def test_min_and_max_disable_the_count_box(self):
        # They compare against the list rather than against a number, so the
        # box has nothing left to hold.
        lst, model = tally_model()
        self.assertNotIn('disabled', self.box(self.tally(model, lst)))
        for op in TALLY_COUNT_EXTREME_OPS:
            with self.subTest(op=op):
                picked = self.click(model, lst,
                                    TallyCountOpSelect(col=col_at(model), op=op))
                self.assertIn('disabled', self.box(self.tally(picked, lst)))

    def test_the_disabled_box_shows_nothing_but_remembers(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        self.assertIn('value=""', self.box(self.tally(model, lst)))
        self.assertEqual(model['tally_count_filter'], '3')
        # And the number comes back with the next comparison.
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='>='))
        self.assertIn('value="3"', self.box(self.tally(model, lst)))

    def test_the_chip_reads_min_and_max_as_words(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='min'))
        self.assertIn('Min', self.chip(self.tally(model, lst)))
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        self.assertIn('Max', self.chip(self.tally(model, lst)))

    def test_the_find_box_narrows_before_min_and_max(self):
        lst, model = tally_model()
        model = self.type_value(model, lst, 'a')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('aa'))])

    def test_the_order_in_force_does_not_change_which_values_are_extreme(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySortSelect(col=col_at(model), sort='rare'))
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        self.assertEqual(self.items(self.tally(model, lst)),
                         [html.escape(repr('c'))])

    def test_a_value_with_no_literal_can_be_the_extreme_one(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', 'c', Thing()]
        _, model = tally_model(lst)
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='min'))
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), ['&lt;thing&gt;'])
        self.assertIn('unselectable', tally)
        # And what All acts on can't come apart from what the menu lists: the
        # one row on show has nothing to select.
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), '')

    def test_select_all_takes_only_the_extreme_values(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        self.assertEqual(self.text(model), "'c'")

    def test_select_none_only_unchecks_the_extreme_values(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallySelectAll(col=col_at(model)))
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        model = self.click(model, lst, TallySelectNone(col=col_at(model)))
        self.assertEqual(self.text(model), "['aa', 'b']")

    def test_narrowing_to_the_extreme_is_not_a_filter_on_the_table(self):
        lst, model = tally_model()
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='min'))
        self.assertIsNone(model['column_searches'])
        self.assertIsNone(model['search'])

    def test_nothing_left_to_be_extreme_says_so(self):
        lst, model = tally_model()
        model = self.type_value(model, lst, 'zz')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='max'))
        tally = self.tally(model, lst)
        self.assertEqual(self.items(tally), [])
        self.assertIn('col-tally-note', tally)

    def test_closing_the_menu_forgets_the_count_filter(self):
        # Like the boxes around it: a way of reaching a value, not a setting.
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, TallyCountOpSelect(col=col_at(model), op='<='))
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-0'))
        self.assertEqual(model['tally_count_filter'], '')
        self.assertEqual(model['tally_count_op'], TALLY_COUNT_OP_DEFAULT)

    def test_another_column_starts_with_an_empty_box(self):
        lst, model = tally_model()
        model['columns'] = ['$', 'len($)']
        model = self.type(model, lst, '3')
        model['openDropdown'] = {'id': menu_id(model)}
        model = self.click(model, lst, DropdownToggle(dropdown_id='col-menu-1'))
        self.assertEqual(model['tally_count_filter'], '')

    def test_escape_forgets_the_count_filter(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model['openDropdown'] = {'id': menu_id(model)}
        model, _ = update(make_column_key_event('Escape'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(model['tally_count_filter'], '')

    def test_a_menu_the_columns_moved_out_from_under_forgets_it_too(self):
        lst, model = tally_model()
        model = self.type(model, lst, '3')
        model = self.click(model, lst, AddColumnClick())
        self.assertEqual(model['tally_count_filter'], '')


class TestColumnValuesExpr(unittest.TestCase):
    """The expression for a whole column, which is what the tally counts and
    what the header hands to a drag."""

    def test_the_item_column_is_the_list_itself(self):
        self.assertEqual(_column_values_expr('$', 'data'), 'data')

    def test_a_computed_column_is_one_comprehension(self):
        self.assertEqual(_column_values_expr("$['name']", 'data'),
                         "[item['name'] for item in data]")

    def test_a_bare_expression_source_is_used_as_written(self):
        self.assertEqual(_column_values_expr('$ * 2', 'get_items()'),
                         '[item * 2 for item in get_items()]')

    def test_the_item_column_is_recognised_however_it_is_spaced(self):
        self.assertEqual(_column_values_expr(' $ ', 'data'), 'data')


class TestDictColumnBinding(unittest.TestCase):
    """How a comprehension over a dict's rows binds them: the tightest header
    the column actually asks for, so the code it writes reads the way a person
    would have written it."""

    @staticmethod
    def binds():
        return _binds_for({'a': 1})

    def test_only_the_value_iterates_the_values(self):
        self.assertEqual(_column_binding('$v', 'd', self.binds()),
                         'v in d.values()')

    def test_only_the_key_iterates_the_dict(self):
        self.assertEqual(_column_binding('$k', 'd', self.binds()), 'k in d')

    def test_both_halves_iterate_the_items(self):
        self.assertEqual(_column_binding('($k, $v)', 'd', self.binds()),
                         'k, v in d.items()')

    def test_the_bare_row_iterates_the_items(self):
        self.assertEqual(_column_binding('$', 'd', self.binds()),
                         'k, v in d.items()')

    def test_a_column_that_reads_the_row_itself_needs_both_halves(self):
        # The trap in narrowing: `$v + len($)` names the value AND the row, so
        # the header cannot be the values alone -- $ would have nothing to be.
        self.assertEqual(_column_binding('len($) + $v', 'd', self.binds()),
                         'k, v in d.items()')

    def test_the_index_wraps_whatever_the_header_was(self):
        self.assertEqual(_column_binding('($k, $v, $i)', 'd', self.binds()),
                         'i, (k, v) in enumerate(d.items())')
        self.assertEqual(_column_binding('$v * $i', 'd', self.binds()),
                         'i, v in enumerate(d.values())')

    def test_a_list_binding_is_untouched(self):
        self.assertEqual(_column_binding("$['n']", 'data'), 'item in data')
        self.assertEqual(_column_binding('$ * $i', 'data'),
                         'i, item in enumerate(data)')


class TestDictWholeColumnExpr(unittest.TestCase):
    """A whole-column read gets the short spelling rather than a degenerate
    comprehension -- what the header hands to a drag."""

    @staticmethod
    def binds():
        return _binds_for({'a': 1})

    def test_the_three_short_forms(self):
        for col, want in (('$', 'list(d.items())'),
                          ('$k', 'list(d)'),
                          ('$v', 'list(d.values())')):
            with self.subTest(col=col):
                self.assertEqual(_column_values_expr(col, 'd', self.binds()), want)

    def test_anything_else_falls_through_to_a_comprehension(self):
        self.assertEqual(_column_values_expr("$v['age']", 'd', self.binds()),
                         "[v['age'] for v in d.values()]")

    def test_a_dict_column_is_never_the_source_itself(self):
        # The None protocol: for a list, `$` means the source already IS the
        # values. For a dict that is false -- list(d) is the keys -- so `$`
        # must come back as a real expression.
        self.assertNotEqual(_column_values_expr('$', 'd', self.binds()), 'd')


class TestDictCellExpr(unittest.TestCase):
    """One cell, named concretely. Key-subscript addressing is what a user
    would write and what is pleasant to drag into the editor."""

    def test_it_addresses_by_key(self):
        d = {'alice': 30, 'bob': 25}
        for col, want in (('$k', "'alice'"),
                          ('$v', "d['alice']"),
                          ('$', "('alice', d['alice'])"),
                          ('$i', '0')):
            with self.subTest(col=col):
                self.assertEqual(_column_cell_expr(col, 'd', 0, d), want)

    def test_it_addresses_the_right_row(self):
        d = {'alice': 30, 'bob': 25}
        self.assertEqual(_column_cell_expr('$v', 'd', 1, d), "d['bob']")

    def test_a_key_with_no_source_form_falls_back_to_position(self):
        # repr(nan) is 'nan', which isn't a literal -- literal_eval raises
        # rather than returning False, so the guard has to be inside a try.
        d = {float('nan'): 'no source form'}
        for col, want in (('$k', 'list(d)[0]'),
                          ('$v', 'list(d.values())[0]'),
                          ('$', 'list(d.items())[0]')):
            with self.subTest(col=col):
                self.assertEqual(_column_cell_expr(col, 'd', 0, d), want)

    def test_a_tuple_key_still_has_a_source_form(self):
        d = {(1, 2): 'pair'}
        self.assertEqual(_column_cell_expr('$v', 'd', 0, d), "d[(1, 2)]")

    def test_a_list_cell_expr_is_untouched(self):
        self.assertEqual(_column_cell_expr('$ * $i', 'data', 2), 'data[2] * 2')
        self.assertEqual(_column_cell_expr("$['n']", 'data', 1), "data[1]['n']")


class TestDictMainSearch(unittest.TestCase):
    """The main search box speaks row scope, so for a dict it can name the key
    and the value as well as the pair."""

    @staticmethod
    def d():
        return {'alice': 30, 'bob': 25, 'carol': 41}

    def test_it_matches_on_the_value(self):
        self.assertEqual(_get_matching_indices('$v > 28', self.d()), [0, 2])

    def test_it_matches_on_the_key(self):
        self.assertEqual(_get_matching_indices("$k == 'bob'", self.d()), [1])

    def test_a_bare_int_still_means_a_row_position(self):
        # list(my_dict) gives positions to the kv pairs, so 1 is the second
        # pair -- unchanged from the list behaviour.
        self.assertEqual(_get_matching_indices('1', self.d()), [1])

    def test_a_slice_still_means_a_run_of_rows(self):
        self.assertEqual(_get_matching_indices('0:2', self.d()), [0, 1])

    def test_a_list_search_is_untouched(self):
        self.assertEqual(_get_matching_indices('$ > 2', [1, 2, 3, 4]), [2, 3])


class TestDictTally(unittest.TestCase):
    """Tally is written against column expressions and _column_values, so it
    follows the column work -- verified rather than assumed."""

    def test_it_counts_the_values(self):
        d = {'a': 1, 'b': 2, 'c': 1}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_tally(_column_values('$v', d, model)), {1: 2, 2: 1})

    def test_it_counts_the_keys(self):
        d = {'a': 1, 'b': 2}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_tally(_column_values('$k', d, model)),
                         {'a': 1, 'b': 1})

    def test_the_counter_expression_reads_the_values(self):
        self.assertEqual(
            _tally_counter_expr('$v', 'd', _binds_for({'a': 1})),
            'Counter(v for v in d.values())')

    def test_unhashable_values_are_unhashable_not_a_crash(self):
        d = {'x': [1], 'y': [2]}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_tally(_column_values('$v', d, model)),
                         TALLY_UNHASHABLE)


class TestDictActionsAreDimmed(unittest.TestCase):
    """The table UI is fully exposed for dicts while generate_action and
    ROW_AGGS are still list-shaped. Left alone, clicking Filter on a dict
    writes `[item for item in d if p]` into the user's file -- which runs
    cleanly and silently yields KEYS. So this dims what is not yet written.

    Sort is deliberately NOT in the dimming set: it writes dict(sorted(...))
    and is correct."""

    @staticmethod
    def dict_model():
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = '$v > 28'
        return d, model

    @staticmethod
    def positional_model(search):
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = search
        return d, model

    def test_every_positional_search_now_writes_through_the_items(self):
        # All four families: index, slice, multi-index, broadcast slice.
        for search in ('1', '0:2', '[0, 1]', '[0,1]:[1,2]'):
            with self.subTest(search=search):
                d, model = self.positional_model(search)
                ctx = _get_search_context(model, ('d', 'd'), source_expr='d')
                for action in ('filter', 'delete', 'find_indices'):
                    self.assertIsNotNone(generate_action(action, ctx))

    def test_the_first_match_forms_all_write_for_a_dict(self):
        # All three: the pair, the key, and the dict without its first match.
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = '$v > 28'
        model['first_match'] = True
        ctx = _get_search_context(model, ('d', 'd'), source_expr='d')
        for action in ('filter', 'find_indices', 'delete'):
            with self.subTest(action=action):
                self.assertIsNotNone(generate_action(action, ctx))

    def test_the_predicate_actions_now_write_and_their_buttons_are_live(self):
        d, model = self.dict_model()
        html_out = _render_action_buttons(model, d)
        self.assertIn('data-action-expr', html_out)

    def test_every_positional_search_lights_the_buttons_up(self):
        for search in ('1', '0:2', '[0, 1]', '[0,1]:[1,2]'):
            with self.subTest(search=search):
                d, model = self.positional_model(search)
                html_out = _render_action_buttons(model, d)
                self.assertIn('data-action-expr', html_out)

    def test_a_list_still_generates_its_actions(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '$ > 1'
        ctx = _get_search_context(model, ('data', 'data'), source_expr='data')
        self.assertIsNotNone(generate_action('filter', ctx))

    def test_pick_is_dimmed_for_a_dict(self):
        d, model = self.dict_model()
        self.assertIn('dimmed', _render_tool_toolbar(model))

    def test_row_aggregations_answer_with_the_right_pair(self):
        # min($$.items(), key=...) rather than min($$, ...), which would have
        # ordered the KEYS.
        d = {'alice': 30, 'bob': 25}
        self.assertEqual(_agg_value(ROW_AGGS[0], [30, 25], None, d, '$v'),
                         ('bob', 25))
        self.assertEqual(_agg_value(ROW_AGGS[1], [30, 25], None, d, '$v'),
                         ('alice', 30))

    def test_a_list_row_aggregation_still_answers(self):
        lst = [{'a': 3}, {'a': 1}]
        self.assertIsNot(_agg_value(ROW_AGGS[0], [3, 1], None, lst, "$['a']"),
                         NO_ANSWER)

    def test_the_row_aggregation_code_reads_the_items(self):
        self.assertEqual(_agg_col_code(ROW_AGGS[0], '$v', 'd',
                                       _binds_for({'a': 1})),
                         'min(d.items(), key=lambda item: item[1])')

    def test_the_row_index_code_indexes_the_items(self):
        # dicts have no .index at all.
        code = _agg_row_index_code('X', 'd', ROW_AGGS[0], '$v',
                                   _binds_for({'a': 1}))
        self.assertEqual(code, 'list(d.items()).index(X)')

    def test_the_search_still_highlights_the_right_rows(self):
        # The rows highlight; only the buttons dim.
        d, _model = self.dict_model()
        self.assertEqual(_get_matching_indices('$v > 28', d), [0])


class TestDictGenerateAction(unittest.TestCase):
    """What a dict writes into the user's file: dict comprehensions, so the
    result is still a dict rather than the list of keys the list-shaped
    templates would silently have produced."""

    @staticmethod
    def ctx(search='$v > 28'):
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = search
        return _get_search_context(model, ('d', 'd'), source_expr='d')

    @staticmethod
    def whole_ctx():
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        return _get_whole_list_context(model, ('d', 'd'), source_expr='d')

    def test_filter_writes_a_dict_comprehension(self):
        self.assertEqual(generate_action('filter', self.ctx())[1],
                         '{k: v for k, v in d.items() if v > 28}')

    def test_delete_negates_the_same_comprehension(self):
        self.assertEqual(generate_action('delete', self.ctx())[1],
                         '{k: v for k, v in d.items() if not (v > 28)}')

    def test_a_dicts_indices_are_its_keys(self):
        self.assertEqual(generate_action('find_indices', self.ctx())[1],
                         '[k for k, v in d.items() if v > 28]')

    def test_count_any_and_all(self):
        self.assertEqual(generate_action('count', self.ctx())[1],
                         'sum(1 for k, v in d.items() if v > 28)')
        self.assertEqual(generate_action('any', self.ctx())[1],
                         'any(v > 28 for k, v in d.items())')
        self.assertEqual(generate_action('all', self.ctx())[1],
                         'all(v > 28 for k, v in d.items())')

    def test_the_if_forms_open_a_block(self):
        self.assertEqual(generate_action('if_any', self.ctx())[1],
                         'if any(v > 28 for k, v in d.items()):')

    def test_a_search_naming_the_key_reads_it(self):
        self.assertEqual(generate_action('filter', self.ctx("$k == 'bob'"))[1],
                         "{k: v for k, v in d.items() if k == 'bob'}")

    def test_a_search_naming_the_index_gets_the_enumerate_twin(self):
        # $i is the ROOT ROW index, so enumerate(d.items()) binds exactly what
        # $i means.
        self.assertEqual(generate_action('filter', self.ctx('$i > 0'))[1],
                         '{k: v for i, (k, v) in enumerate(d.items()) if i > 0}')

    def test_the_whole_dict_loops_over_its_items(self):
        self.assertEqual(generate_action('loop_no_idx', self.whole_ctx())[1],
                         'for k, v in d.items():')

    def test_the_whole_dict_joins_its_values(self):
        self.assertEqual(generate_action('join', self.whole_ctx())[1],
                         "''.join(str(v) for v in d.values())")

    def test_the_generated_filter_actually_runs_and_stays_a_dict(self):
        d = {'alice': 30, 'bob': 25}
        code = generate_action('filter', self.ctx())[1]
        self.assertEqual(eval(code, {'d': d}), {'alice': 30})

    def test_the_generated_find_indices_runs(self):
        d = {'alice': 30, 'bob': 25}
        code = generate_action('find_indices', self.ctx())[1]
        self.assertEqual(eval(code, {'d': d}), ['alice'])

    def test_a_list_action_is_byte_identical_to_before(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '$ > 1'
        ctx = _get_search_context(model, ('data', 'data'), source_expr='data')
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[item for item in data if item > 1]')


class TestDictGrammarRoundtrip(unittest.TestCase):
    """Each generated dict line parses back, so auto-linking keeps working --
    and the grammar generator agrees with the live one, which is the whole
    reason both exist."""

    ACTIONS = ('filter', 'delete', 'find_indices', 'count', 'any', 'all',
               'if_any', 'if_all', 'loop_no_idx', 'loop_orig_idx',
               'loop_new_idx')

    def setUp(self):
        from table_visualizer_grammar import (generate_action as grammar_gen,
                                              parse_generated_code)
        self.grammar_gen = grammar_gen
        self.parse_generated_code = parse_generated_code

    def ctx(self, search='$v > 28'):
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = search
        return _get_search_context(model, ('d', 'd'), source_expr='d')

    def test_both_generators_agree(self):
        for search in ('$v > 28', '$i > 0'):
            ctx = self.ctx(search)
            for action in self.ACTIONS:
                with self.subTest(action=action, search=search):
                    live = generate_action(action, ctx)
                    gram = self.grammar_gen(action, ctx)
                    self.assertIsNotNone(gram)
                    self.assertEqual(live[1], gram[1])

    def test_every_generated_line_parses_back(self):
        for search in ('$v > 28', '$i > 0'):
            ctx = self.ctx(search)
            for action in self.ACTIONS:
                with self.subTest(action=action, search=search):
                    code = generate_action(action, ctx)[1]
                    parsed = self.parse_generated_code(code)
                    self.assertIsNotNone(parsed, code)
                    self.assertTrue(parsed.get('is_dict'))
                    self.assertEqual(parsed.get('source_expr'), 'd')

    def test_a_dict_line_is_not_misread_as_a_list_one(self):
        # The failure that would matter: a dict comprehension parsed as a list
        # action would relink the table to code that means something else.
        for code in ('{k: v for k, v in d.items() if v > 28}',
                     '[k for k, v in d.items() if v > 28]'):
            with self.subTest(code=code):
                parsed = self.parse_generated_code(code)
                self.assertTrue(parsed.get('is_dict'))

    def test_list_lines_still_parse_as_lists(self):
        parsed = self.parse_generated_code('[item for item in data if item > 1]')
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.get('is_dict'))


class TestDictFirstMatch(unittest.TestCase):
    """Find One on a dict. The pair is what a row IS, so that is what the
    first match hands back -- and a dict's "index" is its key, so Find Indices
    hands back the key."""

    @staticmethod
    def ctx(search='$v > 28'):
        d = {'alice': 30, 'bob': 25, 'carol': 41}
        model = init_model(d, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = search
        model['first_match'] = True
        return _get_search_context(model, ('d', 'd'), source_expr='d')

    def test_filter_first_hands_back_the_pair(self):
        self.assertEqual(generate_action('filter', self.ctx())[1],
                         'next(((k, v) for k, v in d.items() if v > 28), None)')

    def test_find_indices_first_hands_back_the_key(self):
        self.assertEqual(generate_action('find_indices', self.ctx())[1],
                         'next((k for k, v in d.items() if v > 28), None)')

    def test_the_indexed_twins(self):
        self.assertEqual(
            generate_action('filter', self.ctx('$i > 0'))[1],
            'next(((k, v) for i, (k, v) in enumerate(d.items()) if i > 0), None)')

    def test_the_generated_code_runs(self):
        d = {'alice': 30, 'bob': 25, 'carol': 41}
        self.assertEqual(eval(generate_action('filter', self.ctx())[1],
                              {'d': d}), ('alice', 30))
        self.assertEqual(eval(generate_action('find_indices', self.ctx())[1],
                              {'d': d}), 'alice')

    def test_no_match_is_none_rather_than_an_error(self):
        d = {'alice': 30}
        code = generate_action('filter', self.ctx('$v > 999'))[1]
        self.assertIsNone(eval(code, {'d': d}))

    def test_delete_one_removes_the_first_match(self):
        self.assertEqual(
            generate_action('delete', self.ctx())[1],
            'next(({k2: v2 for k2, v2 in d.items() if k2 != k}'
            ' for k, v in d.items() if v > 28), d)')

    def test_delete_one_runs_and_removes_only_the_first(self):
        d = {'alice': 30, 'bob': 25, 'carol': 41}
        code = generate_action('delete', self.ctx())[1]
        self.assertEqual(eval(code, {'d': d}), {'bob': 25, 'carol': 41})

    def test_delete_one_evaluates_the_predicate_only_to_the_first_match(self):
        # The whole point of the next(...) idiom, and the same property the
        # list form has: it stops.
        seen = []
        def p(v):
            seen.append(v)
            return v > 28
        d = {'alice': 30, 'bob': 25, 'carol': 41}
        code = generate_action('delete', self.ctx('p($v)'))[1]
        eval(code, {'d': d, 'p': p})
        self.assertEqual(seen, [30])

    def test_delete_one_with_no_match_hands_back_the_dict(self):
        d = {'alice': 30}
        code = generate_action('delete', self.ctx('$v > 999'))[1]
        self.assertEqual(eval(code, {'d': d}), d)

    def test_delete_one_survives_a_none_key(self):
        # The reason this is written by KEY rather than against a
        # next(..., None) sentinel: None is a perfectly good dict key.
        d = {None: 99, 'bob': 25}
        code = generate_action('delete', self.ctx('$v > 28'))[1]
        self.assertEqual(eval(code, {'d': d}), {'bob': 25})

    def test_both_generators_agree_and_it_parses_back(self):
        from table_visualizer_grammar import (generate_action as ggen,
                                              parse_generated_code)
        for action in ('filter', 'find_indices', 'delete'):
            for search in ('$v > 28', '$i > 0'):
                with self.subTest(action=action, search=search):
                    ctx = self.ctx(search)
                    live = generate_action(action, ctx)
                    gram = ggen(action, ctx)
                    self.assertIsNotNone(gram)
                    self.assertEqual(live[1], gram[1])
                    parsed = parse_generated_code(gram[1])
                    self.assertIsNotNone(parsed, gram[1])
                    self.assertTrue(parsed.get('is_dict'))
                    self.assertTrue(parsed.get('is_first'))

    def test_a_list_first_match_is_unchanged(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '$ > 1'
        model['first_match'] = True
        ctx = _get_search_context(model, ('data', 'data'), source_expr='data')
        self.assertEqual(generate_action('filter', ctx)[1],
                         'next((item for item in data if item > 1), None)')


class TestDictPositionalActions(unittest.TestCase):
    """`3` and `1:3` in the search box mean ROW POSITIONS for a dict, since
    list(my_dict) gives positions to the kv pairs. The rows already highlighted;
    now the buttons write too, through list(d.items()) and back into a dict."""

    D = {'alice': 30, 'bob': 25, 'carol': 41}

    def ctx(self, search):
        model = init_model(self.D, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['search'] = search
        return _get_search_context(model, ('d', 'd'), source_expr='d')

    def gen(self, action, search):
        result = generate_action(action, self.ctx(search))
        return None if result is None else result[1]

    def list_ctx(self, search):
        model = init_model([10, 20, 30], mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['search'] = search
        return _get_search_context(model, ('data', 'data'), source_expr='data')

    def test_an_index_picks_the_pair_at_that_position(self):
        self.assertEqual(self.gen('filter', '1'), 'list(d.items())[1]')
        self.assertEqual(eval(self.gen('filter', '1'), {'d': self.D}),
                         ('bob', 25))

    def test_an_index_deletes_by_position_not_by_key(self):
        # d.pop(k) would need the key; the position is what was searched for.
        code = self.gen('delete', '1')
        self.assertEqual(code,
                         '{k: v for j, (k, v) in enumerate(d.items()) if j != 1}')
        self.assertEqual(eval(code, {'d': self.D}), {'alice': 30, 'carol': 41})

    def test_an_index_finds_the_key_at_that_position(self):
        self.assertEqual(self.gen('find_indices', '1'), 'list(d)[1]')
        self.assertEqual(eval(self.gen('find_indices', '1'), {'d': self.D}),
                         'bob')

    def test_a_slice_stays_a_dict(self):
        code = self.gen('filter', '0:2')
        self.assertEqual(code, 'dict(list(d.items())[0:2])')
        self.assertEqual(eval(code, {'d': self.D}), {'alice': 30, 'bob': 25})

    def test_a_slice_delete_keeps_both_ends(self):
        code = self.gen('delete', '1:2')
        self.assertEqual(eval(code, {'d': self.D}),
                         {'alice': 30, 'carol': 41})

    def test_an_open_ended_slice_works_at_both_ends(self):
        self.assertEqual(eval(self.gen('filter', ':2'), {'d': self.D}),
                         {'alice': 30, 'bob': 25})
        self.assertEqual(eval(self.gen('filter', '1:'), {'d': self.D}),
                         {'bob': 25, 'carol': 41})

    def test_a_slice_finds_the_keys_in_that_run(self):
        self.assertEqual(eval(self.gen('find_indices', '0:2'), {'d': self.D}),
                         ['alice', 'bob'])

    def test_a_broadcast_slice_yields_one_dict_per_band(self):
        code = self.gen('filter', '[0,2]:[1,3]')
        self.assertEqual(
            code,
            '[dict(list(d.items())[i:j]) for i, j in zip([0,2], [1,3])]')
        self.assertEqual(eval(code, {'d': self.D}),
                         [{'alice': 30}, {'carol': 41}])

    def test_a_broadcast_slice_anchored_at_one_end(self):
        self.assertEqual(eval(self.gen('filter', '[0,2]:'), {'d': self.D}),
                         [{'alice': 30, 'bob': 25, 'carol': 41}, {'carol': 41}])
        self.assertEqual(eval(self.gen('filter', ':[1,3]'), {'d': self.D}),
                         [{'alice': 30}, {'alice': 30, 'bob': 25, 'carol': 41}])

    def test_a_broadcast_slice_deletes_every_banded_row(self):
        code = self.gen('delete', '[0,2]:[1,3]')
        self.assertEqual(eval(code, {'d': self.D}), {'bob': 25})

    def test_a_broadcast_slice_counts_the_bands(self):
        self.assertEqual(self.gen('count', '[0,2]:[1,3]'), 'len([0,2])')
        self.assertEqual(self.gen('all', '[0,2]:[1,3]'), 'len([0,2]) == len(d)')

    def test_a_broadcast_slice_finds_the_key_each_band_starts_at(self):
        code = self.gen('find_indices', '[0,2]:[1,3]')
        self.assertEqual(code, '[list(d)[i] for i in [0,2]]')
        self.assertEqual(eval(code, {'d': self.D}), ['alice', 'carol'])

    def test_a_stop_anchored_band_starts_where_it_says(self):
        # A list answers `[0] * len([2,3])` here even though its bands start at
        # 1 -- it hardcodes the 0 rather than reading slice_start. That is a
        # pre-existing list bug, not a shape to copy, so the dict reads the
        # start it was actually given.
        code = self.gen('find_indices', '1:[2,3]')
        self.assertEqual(code, '[list(d)[1]] * len([2,3])')
        self.assertEqual(eval(code, {'d': self.D}), ['bob', 'bob'])
        self.assertEqual(eval(self.gen('filter', '1:[2,3]'), {'d': self.D}),
                         [{'bob': 25}, {'bob': 25, 'carol': 41}])

    def test_a_broadcast_slice_cuts_the_same_actions_a_list_does(self):
        # No list writes join over a band either, and loops stay unbuilt for
        # every dict positional family.
        for action in ('join', 'loop_no_idx', 'loop_orig_idx', 'loop_new_idx'):
            with self.subTest(action=action):
                self.assertIsNone(self.gen(action, '[0,2]:[1,3]'))

    def test_a_broadcast_slice_is_live_only_for_a_dict_as_it_is_for_a_list(self):
        # There are no broadcast BiTemplates for any container: the family is
        # generated live and never parsed back, so a dict having none is parity
        # rather than a gap. Adding dict-only ones would be the asymmetry.
        from table_visualizer_grammar import (generate_action as ggen,
                                              parse_generated_code)
        for action in ('filter', 'delete', 'find_indices', 'count'):
            with self.subTest(action=action):
                ctx = self.ctx('[0,2]:[1,3]')
                self.assertIsNotNone(generate_action(action, ctx))
                self.assertIsNone(ggen(action, ctx))
        lst_ctx = self.list_ctx('[0,2]:[1,3]')
        self.assertIsNone(ggen('filter', lst_ctx))
        self.assertIsNone(parse_generated_code(
            '[dict(list(d.items())[i:j]) for i, j in zip([0,2], [1,3])]'))

    def test_a_list_broadcast_slice_is_unchanged(self):
        ctx = self.list_ctx('[0,2]:[1,3]')
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[data[i:j] for i, j in zip([0,2], [1,3])]')
        self.assertEqual(generate_action('find_indices', ctx)[1], '[0,2]')
        self.assertEqual(generate_action('loop_no_idx', ctx)[1],
                         'for item in [data[i:j] for i, j in zip([0,2], [1,3])]:')

    def test_count_over_a_slice_stays_cut(self):
        # Not a dict gap: no list writes count over a slice either, so there is
        # nothing to reach parity with. Giving dicts one is a new feature for
        # both containers, and it lands as one.
        self.assertIsNone(self.gen('count', '0:2'))

    def test_a_slice_joins_the_values(self):
        # The same reading the predicate form uses -- `str(v)`, not the pair --
        # so Join means one thing on a dict however the rows were chosen.
        code = self.gen('join', '0:2')
        self.assertEqual(code, "''.join(str(v) for k, v in list(d.items())[0:2])")
        self.assertEqual(eval(code, {'d': self.D}), '3025')

    def test_a_slice_join_takes_the_separator(self):
        ctx = self.ctx('0:2')
        ctx['join_separator'] = "', '"
        code = generate_action('join', ctx)[1]
        self.assertEqual(eval(code, {'d': self.D}), '30, 25')

    def test_an_open_ended_slice_join_works_at_both_ends(self):
        self.assertEqual(eval(self.gen('join', ':2'), {'d': self.D}), '3025')
        self.assertEqual(eval(self.gen('join', '1:'), {'d': self.D}), '2541')

    def test_a_slice_join_reads_back_as_a_dict_slice(self):
        from table_visualizer_grammar import parse_generated_code
        ctx = parse_generated_code(self.gen('join', '0:2'))
        self.assertEqual(ctx['action'], 'join')
        self.assertEqual(ctx['source_expr'], 'd')
        self.assertTrue(ctx['is_dict'])
        self.assertTrue(ctx['is_slice'])
        self.assertEqual((ctx['slice_start'], ctx['slice_stop']), ('0', '2'))

    def test_a_slice_join_relinks_to_the_dict_it_came_from(self):
        # The source_expr guard is what made this fail before: reading the line
        # as a list over `list(d.items())` never matched the visualizer's `d`.
        from table_visualizer import _LINK_CONFIG
        from visualizer_utils import parse_owned_line
        owned = parse_owned_line(_LINK_CONFIG, self.gen('join', '0:2'), ('d', 'd'))
        self.assertIsNotNone(owned)
        self.assertEqual(owned[0]['source_expr'], 'd')

    def test_a_list_slice_join_still_reads_as_a_list(self):
        # A tuple target is what marks the dict form, so the list's `for item`
        # shape cannot be caught by it.
        from table_visualizer_grammar import parse_generated_code
        ctx = parse_generated_code("''.join(str(item) for item in data[0:2])")
        self.assertEqual(ctx['source_expr'], 'data')
        self.assertTrue(ctx['is_slice'])
        self.assertFalse(ctx.get('is_dict'))

    def test_both_generators_agree_on_every_positional_action(self):
        # Join is exempt: it lives outside the grammar for every container (no
        # Join templates exist at all), and is read back by the hand-written
        # AST reader instead. Its contract is tested above, by round-trip.
        from table_visualizer_grammar import (generate_action as ggen,
                                              parse_generated_code)
        for search in ('1', '0:2', ':2', '1:'):
            for action in ('filter', 'delete', 'find_indices', 'count'):
                with self.subTest(search=search, action=action):
                    ctx = self.ctx(search)
                    live = generate_action(action, ctx)
                    gram = ggen(action, ctx)
                    self.assertEqual(live and live[1], gram and gram[1])
                    if live:
                        self.assertIsNotNone(parse_generated_code(live[1]))

    def test_a_multi_index_picks_those_rows_into_a_dict(self):
        code = self.gen('filter', '[0, 2]')
        self.assertEqual(code, 'dict(list(d.items())[i] for i in [0, 2])')
        self.assertEqual(eval(code, {'d': self.D}), {'alice': 30, 'carol': 41})

    def test_a_multi_index_deletes_by_position(self):
        # The same reading the single index uses, widened to a set.
        code = self.gen('delete', '[0, 2]')
        self.assertEqual(
            code,
            '{k: v for j, (k, v) in enumerate(d.items()) if j not in set([0, 2])}')
        self.assertEqual(eval(code, {'d': self.D}), {'bob': 25})

    def test_a_multi_index_finds_those_keys(self):
        code = self.gen('find_indices', '[0, 2]')
        self.assertEqual(code, '[list(d)[i] for i in [0, 2]]')
        self.assertEqual(eval(code, {'d': self.D}), ['alice', 'carol'])

    def test_a_multi_index_counts_and_quantifies_like_a_list(self):
        # These three never touch the container: they are about how many
        # positions were named, so the list templates are already right.
        self.assertEqual(self.gen('count', '[0, 2]'), 'len([0, 2])')
        self.assertEqual(self.gen('any', '[0, 2]'), 'len([0, 2]) > 0')
        self.assertEqual(self.gen('all', '[0, 2]'), 'len([0, 2]) == len(d)')
        self.assertFalse(eval(self.gen('all', '[0, 2]'), {'d': self.D}))
        self.assertTrue(eval(self.gen('all', '[0, 1, 2]'), {'d': self.D}))

    def test_a_multi_index_joins_the_values(self):
        code = self.gen('join', '[0, 2]')
        self.assertEqual(
            code, "''.join(str(v) for k, v in [list(d.items())[i] for i in [0, 2]])")
        self.assertEqual(eval(code, {'d': self.D}), '3041')

    def test_the_loop_actions_stay_unbuilt_for_every_positional_family(self):
        # Uniformly: no dict positional search writes a loop. A list's
        # multi-index does, but its "original index" is a position, and a dict's
        # is a key -- so `for i in [0, 2]:` has no honest dict reading. Rather
        # than build two of the three, none are built, matching index and slice.
        for search in ('1', '0:2', '[0, 2]'):
            for action in ('loop_no_idx', 'loop_orig_idx', 'loop_new_idx'):
                with self.subTest(search=search, action=action):
                    self.assertIsNone(self.gen(action, search))

    def test_a_multi_index_reads_back_as_a_dict(self):
        from table_visualizer_grammar import parse_generated_code
        for action in ('filter', 'delete', 'find_indices'):
            with self.subTest(action=action):
                ctx = parse_generated_code(self.gen(action, '[0, 2]'))
                self.assertIsNotNone(ctx)
                self.assertEqual(ctx['action'], action)
                self.assertEqual(ctx['source_expr'], 'd')
                self.assertTrue(ctx['is_dict'])
                self.assertTrue(ctx['is_multi_index'])
                self.assertEqual(ctx['indices_expr'], '[0, 2]')

    def test_a_multi_index_join_reads_back_as_a_dict(self):
        from table_visualizer_grammar import parse_generated_code
        ctx = parse_generated_code(self.gen('join', '[0, 2]'))
        self.assertEqual(ctx['action'], 'join')
        self.assertEqual(ctx['source_expr'], 'd')
        self.assertTrue(ctx['is_dict'])
        self.assertTrue(ctx['is_multi_index'])
        self.assertEqual(ctx['indices_expr'], '[0, 2]')

    def test_a_multi_index_relinks_to_the_dict_it_came_from(self):
        from table_visualizer import _LINK_CONFIG
        from visualizer_utils import parse_owned_line
        for action in ('filter', 'delete', 'find_indices', 'join'):
            with self.subTest(action=action):
                owned = parse_owned_line(_LINK_CONFIG, self.gen(action, '[0, 2]'),
                                         ('d', 'd'))
                self.assertIsNotNone(owned)
                self.assertEqual(owned[0]['source_expr'], 'd')

    def test_a_list_multi_index_is_unchanged(self):
        from table_visualizer_grammar import parse_generated_code
        lst = [10, 20, 30]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '[0, 2]'
        ctx = _get_search_context(model, ('data', 'data'), source_expr='data')
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[data[i] for i in [0, 2]]')
        self.assertEqual(generate_action('find_indices', ctx)[1], '[0, 2]')
        self.assertEqual(generate_action('loop_orig_idx', ctx)[1],
                         'for i in [0, 2]:')
        back = parse_generated_code('[data[i] for i in [0, 2]]')
        self.assertFalse(back.get('is_dict'))

    def test_both_generators_agree_on_the_multi_index_family(self):
        from table_visualizer_grammar import generate_action as ggen
        for action in ('filter', 'delete', 'find_indices', 'count', 'any', 'all',
                       'loop_no_idx', 'loop_orig_idx', 'loop_new_idx'):
            with self.subTest(action=action):
                ctx = self.ctx('[0, 2]')
                live = generate_action(action, ctx)
                gram = ggen(action, ctx)
                self.assertEqual(live and live[1], gram and gram[1])

    def test_every_slice_join_shape_round_trips(self):
        from table_visualizer_grammar import parse_generated_code
        for search in ('0:2', ':2', '1:'):
            with self.subTest(search=search):
                code = self.gen('join', search)
                ctx = parse_generated_code(code)
                self.assertIsNotNone(ctx)
                self.assertEqual(ctx['source_expr'], 'd')
                self.assertTrue(ctx['is_dict'])

    def test_a_list_positional_action_is_unchanged(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['search'] = '1'
        ctx = _get_search_context(model, ('data', 'data'), source_expr='data')
        self.assertEqual(generate_action('filter', ctx)[1], 'data[1]')
        self.assertEqual(generate_action('delete', ctx)[1],
                         'data[:1] + data[1+1:]')


# The dict twin of the worked example: a match in the middle, two columns.
DICT_PICK_D = {'alice': 30, 'bob': 25, 'carol': 41}
DICT_PICK_COLUMNS = {'$': {}, '$v': {}}
DICT_PICK_SEARCH = '$v < 28'


def dict_pick_eval(code):
    return eval(code, {'d': dict(DICT_PICK_D)})


def make_dict_pick_model(picked=None, columns=None, search=DICT_PICK_SEARCH,
                         tool='pick'):
    """A table model parked in pick mode over DICT_PICK_D."""
    model = init_model(DICT_PICK_D, mock_get_visualizer_dict_tables,
                       eval_in_scope=dict_pick_eval, var_and_exp=('d', 'd'))
    model['columns'] = dict(DICT_PICK_COLUMNS if columns is None else columns)
    model['search'] = search
    model['tool'] = tool
    model['first_match'] = True
    model['picked'] = list(picked) if picked else None
    model['pick_expr'] = _build_pick_expr(model, 'd')
    return model


from table_visualizer import (
    _group_agg_column, _group_agg_template, _leaf_splat_target,
    _leaf_values, _leaf_columns, _agg_layout, _agg_value,
    _column_computes, _set_column_computes, _column_groups, _header_depth,
    _rows, _row_by_key, _slots_from_columns, _columns_from_slots,
    MAX_SPLAT_DEPTH, SUBCOL_SEP, _compose_sub, _move_target, _column_values,
    _column_row_expr, _col_add, _col_subs, _menu_id, ROW_AGGS, HISTOGRAM_AGG,
)
from visualizer_utils import parse_slot_cols


class TestNestedLeafColumns(unittest.TestCase):
    """A splat's sub-column may itself splat. The leaves are what everything
    that draws or computes goes through, so they are the first thing that has
    to know a chain of splats from a single one."""

    FLAT = {'$k': {}, '*$v': {'cols': {"$['who']": {}, "$['age']": {}}}}
    NESTED = {'$.name': {},
              '*$.teams': {'cols': {'$.title': {},
                                    '*$.members': {'cols': {'$.who': {},
                                                            '$.age': {}}}}}}

    def test_a_flat_table_is_what_it_always_was(self):
        leaves = _leaf_columns(self.FLAT)
        self.assertEqual([l.depth for l in leaves], [0, 1, 1])
        self.assertEqual([l.splat for l in leaves], [None, '*$v', '*$v'])
        self.assertEqual([l.header for l in leaves],
                         [('$k',), ('*$v', "$['who']"), ('*$v', "$['age']")])

    def test_a_nested_splat_gives_its_leaves_the_deeper_depth(self):
        leaves = _leaf_columns(self.NESTED)
        self.assertEqual([l.depth for l in leaves], [0, 1, 2, 2])

    def test_a_leaf_reads_off_its_innermost_splat(self):
        leaves = _leaf_columns(self.NESTED)
        self.assertEqual([l.splat for l in leaves],
                         [None, '*$.teams', '*$.members', '*$.members'])

    def test_the_chain_is_the_splats_from_the_outside_in(self):
        leaves = _leaf_columns(self.NESTED)
        self.assertEqual([l.chain for l in leaves],
                         [(), ('*$.teams',), ('*$.teams', '*$.members'),
                          ('*$.teams', '*$.members')])

    def test_the_header_path_grows_with_the_nesting(self):
        leaves = _leaf_columns(self.NESTED)
        self.assertEqual(leaves[2].header,
                         ('*$.teams', '*$.members', '$.who'))
        self.assertEqual(leaves[1].header, ('*$.teams', '$.title'))

    def test_identities_cannot_collide_across_ancestors(self):
        # The same sub-column name under two different splats is two columns.
        cols = {'*$.a': {'cols': {'$.n': {}}}, '*$.b': {'cols': {'$.n': {}}}}
        exprs = [l.expr for l in _leaf_columns(cols)]
        self.assertEqual(len(set(exprs)), 2)

    def test_a_nested_splat_with_no_subs_shows_the_element(self):
        cols = {'*$.teams': {'cols': {'*$.members': {}}}}
        leaves = _leaf_columns(cols)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0].depth, 2)
        self.assertEqual(leaves[0].sub, '$')

    def test_a_group_is_as_wide_as_the_leaves_under_it(self):
        # Not len(cols): a sub-splat expands further than its own count.
        groups = _column_groups(self.NESTED)
        self.assertEqual([g.col for g in groups], ['$.name', '*$.teams'])
        self.assertEqual([g.width for g in groups], [1, 3])

    def test_the_header_is_one_row_per_level(self):
        self.assertEqual(_header_depth(self.NESTED), 3)
        self.assertEqual(_header_depth(self.FLAT), 2)
        self.assertEqual(_header_depth({'$k': {}, '$v': {}}), 1)


class TestNestedRows(unittest.TestCase):
    """A row belongs to one group per depth. The spans are what a leaf reads to
    know how far down its cell reaches and which row draws it."""

    ORGS = [
        {'name': 'acme',
         'teams': [{'title': 'red', 'members': [{'who': 'ann'}, {'who': 'bo'}]},
                   {'title': 'blue', 'members': [{'who': 'cy'}]}]},
        {'name': 'globex',
         'teams': [{'title': 'green', 'members': [{'who': 'di'}]}]},
    ]
    COLS = {'$["name"]': {},
            '*$["teams"]': {'cols': {'$["title"]': {},
                                     '*$["members"]': {'cols': {'$["who"]': {}}}}}}

    def rows(self):
        return _rows(self.ORGS, self.COLS)

    def test_one_rendered_row_per_innermost_element(self):
        # acme: red has 2, blue has 1; globex: green has 1. Four rows.
        self.assertEqual(len(self.rows()), 4)

    def test_the_key_names_the_whole_path(self):
        self.assertEqual([r.key for r in self.rows()],
                         ['0.0.0', '0.0.1', '0.1.0', '1.0.0'])

    def test_the_root_index_stays_the_root_row(self):
        self.assertEqual([r.index for r in self.rows()], [0, 0, 0, 1])

    def test_each_depth_knows_its_own_group(self):
        rows = self.rows()
        # depth 0 is the whole root row: acme covers 3, globex 1.
        self.assertEqual([r.span_at(0) for r in rows], [3, 3, 3, 1])
        # depth 1 is the team: red covers 2, blue 1, green 1.
        self.assertEqual([r.span_at(1) for r in rows], [2, 2, 1, 1])
        # depth 2 is the member, which is one row by definition.
        self.assertEqual([r.span_at(2) for r in rows], [1, 1, 1, 1])

    def test_only_the_first_row_of_each_group_draws_it(self):
        rows = self.rows()
        self.assertEqual([r.starts_at(0) for r in rows],
                         [True, False, False, True])
        self.assertEqual([r.starts_at(1) for r in rows],
                         [True, False, True, True])
        self.assertEqual([r.starts_at(2) for r in rows], [True] * 4)

    def test_every_splat_in_the_chain_is_reachable_from_the_row(self):
        row = self.rows()[1]
        self.assertEqual(row.splats['*$["teams"]']['title'], 'red')
        self.assertEqual(row.splats['*$["members"]'], {'who': 'bo'})

    def test_j_binds_the_innermost_position(self):
        # Decided: outer group positions get no sigil at all.
        self.assertEqual([r.bindings['j'] for r in self.rows()], [0, 1, 0, 0])

    def test_an_empty_inner_list_still_leaves_one_row(self):
        orgs = [{'name': 'a', 'teams': [{'title': 't', 'members': []}]}]
        rows = _rows(orgs, self.COLS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].splats['*$["teams"]']['title'], 't')

    def test_an_empty_outer_list_still_leaves_one_row(self):
        rows = _rows([{'name': 'a', 'teams': []}], self.COLS)
        self.assertEqual(len(rows), 1)

    def test_a_row_is_found_by_its_nested_key(self):
        row = _row_by_key(self.ORGS, self.COLS, '0.1.0')
        self.assertEqual(row.splats['*$["members"]'], {'who': 'cy'})

    def test_one_level_is_exactly_what_it_was(self):
        d = {'a': [1, 2, 3], 'b': [10]}
        rows = _rows(d, {'$k': {}, '*$v': {}})
        self.assertEqual([r.key for r in rows], ['0.0', '0.1', '0.2', '1.0'])
        self.assertEqual([r.span for r in rows], [3, 3, 3, 1])
        self.assertEqual([r.span_start for r in rows],
                         [True, False, False, True])
        self.assertEqual([r.span_at(1) for r in rows], [1, 1, 1, 1])

    def test_a_flat_table_has_one_row_per_row(self):
        rows = _rows([1, 2, 3], {'$': {}})
        self.assertEqual([r.span for r in rows], [1, 1, 1])
        self.assertTrue(all(r.span_start for r in rows))


class TestNestedColumnsRoundTrip(unittest.TestCase):
    """Nested `cols` used to be dropped at load, because the row model
    described exactly one grouping level and honouring them would have rendered
    wrong. It doesn't any more, so they load."""

    NESTED = {'$.name': {},
              '*$.teams': {'cols': {'$.title': {},
                                    '*$.members': {'cols': {'$.who': {}}}}}}

    def test_the_slot_list_nests(self):
        self.assertEqual(_slots_from_columns(self.NESTED),
                         ['$.name',
                          {'expr': '*$.teams',
                           'cols': ['$.title',
                                    {'expr': '*$.members', 'cols': ['$.who']}]}])

    def test_it_comes_back_the_way_it_went_out(self):
        slots = _slots_from_columns(self.NESTED)
        exprs = [s if isinstance(s, str) else s['expr'] for s in slots]
        self.assertEqual(_columns_from_slots(exprs, parse_slot_cols(
            [s for s in slots if isinstance(s, dict)])), self.NESTED)

    def test_a_flat_table_writes_exactly_what_it_always_did(self):
        flat = {'$k': {}, '*$v': {'cols': {"$['who']": {}}}}
        self.assertEqual(_slots_from_columns(flat),
                         ['$k', {'expr': '*$v', 'cols': ["$['who']"]}])

    def test_nesting_is_capped(self):
        # Bounded by the config rather than the data, but a hand-edited
        # dotfile is a real input.
        entry = {'expr': '*$.x', 'cols': ['$.leaf']}
        for _ in range(MAX_SPLAT_DEPTH + 3):
            entry = {'expr': '*$.x', 'cols': [entry]}
        cols = _columns_from_slots(['*$.x'], parse_slot_cols([entry]))
        self.assertLessEqual(_header_depth(cols), MAX_SPLAT_DEPTH + 1)


class TestNestedRendering(unittest.TestCase):
    """The whole table, three levels deep."""

    ORGS = [
        {'name': 'acme',
         'teams': [{'title': 'red', 'members': [{'who': 'ann'}, {'who': 'bo'}]},
                   {'title': 'blue', 'members': [{'who': 'cy'}]}]},
    ]
    COLS = {'$["name"]': {},
            '*$["teams"]': {'cols': {'$["title"]': {},
                                     '*$["members"]': {'cols': {'$["who"]': {}}}}}}

    def html(self):
        m = init_model(self.ORGS, mock_get_visualizer, var_and_exp=('o', 'o'))
        m['columns'] = self.COLS
        return visualize(self.ORGS, m, mock_get_visualizer, None)

    def test_the_header_has_a_row_per_level(self):
        out = self.html()
        header = out[:out.index('</tr>', out.index('</tr>') + 1)]
        self.assertEqual(_header_depth(self.COLS), 3)
        self.assertEqual(out.count('col-subheader'), 3)

    def test_the_outer_splat_spans_every_leaf_under_it(self):
        # *teams covers title, *members and who -- two leaves, not two cols.
        self.assertIn('colspan="2"', self.html())

    def test_the_root_column_spans_every_rendered_row(self):
        # acme has three members across two teams.
        self.assertIn('rowspan="3"', self.html())

    def test_a_middle_column_spans_its_own_group(self):
        # 'red' has two members, so the title cell covers two rows.
        self.assertIn('rowspan="2"', self.html())

    def test_every_innermost_value_is_drawn(self):
        out = self.html()
        for who in ('ann', 'bo', 'cy'):
            self.assertIn(who, out)

    def test_the_middle_values_are_drawn_once_each(self):
        out = self.html()
        self.assertEqual(out.count('red'), 1)
        self.assertEqual(out.count('blue'), 1)


class TestPlainSubColumns(unittest.TestCase):
    """Splatting and sub-columns are different axes: a splat spreads a value
    DOWN into rows, sub-columns spread one ACROSS into columns. A column that
    doesn't splat carries them too -- which is how a CSV line, split into a
    list, draws as a row of fields instead of a list sitting in one cell."""

    LINES = ['id,name,age', '1,Alice,29', '2,Bob,34']
    SPLIT = "$.split(',')"
    COLS = {'$': {}, SPLIT: {'cols': {'$[0]': {}, '$[1]': {}}}}

    def leaves(self):
        return _leaf_columns(self.COLS)

    def html(self):
        model = init_model(self.LINES, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = self.COLS
        model['_source_expr'] = 'data'
        return visualize(self.LINES, model, mock_get_visualizer,
                         lambda code: eval(code, {}, {'data': self.LINES}))

    def test_the_parent_is_not_a_drawn_column(self):
        # Its sub-columns are what's drawn, the way a splat's are.
        self.assertEqual([leaf.expr for leaf in self.leaves()],
                         ['$', f'{self.SPLIT}{SUBCOL_SEP}$[0]',
                          f'{self.SPLIT}{SUBCOL_SEP}$[1]'])

    def test_a_plain_parent_adds_no_grouping_level(self):
        # It spread nothing into rows, so every leaf still draws once per row.
        self.assertEqual([leaf.splat for leaf in self.leaves()], [None] * 3)
        self.assertEqual([leaf.depth for leaf in self.leaves()], [0, 0, 0])

    def test_a_leaf_reads_by_the_composition(self):
        self.assertEqual([leaf.sub for leaf in self.leaves()],
                         [None, "$.split(',')[0]", "$.split(',')[1]"])

    def test_the_header_spans_what_it_carries(self):
        self.assertEqual([(g.col, g.width) for g in _column_groups(self.COLS)],
                         [('$', 1), (self.SPLIT, 2)])
        self.assertEqual(_header_depth(self.COLS), 2)

    def test_the_rows_stay_one_per_item(self):
        self.assertEqual(len(_rows(self.LINES, self.COLS)), 3)

    def test_every_field_draws_in_its_own_column(self):
        out = self.html()
        self.assertIn('colspan="2"', out)
        for text in ('id', 'name', 'Alice', 'Bob'):
            self.assertIn(text, out)

    def test_the_column_has_the_values_the_composition_reads(self):
        model = init_model(self.LINES, mock_get_visualizer)
        model['columns'] = self.COLS
        self.assertEqual(
            _column_values(f'{self.SPLIT}{SUBCOL_SEP}$[0]', self.LINES, model),
            ['id', '1', '2'])

    def test_the_whole_column_is_the_composed_one(self):
        # What the header hands to a drag, and what the tally and the
        # aggregations read: an ordinary column, because that is what it is.
        self.assertEqual(_leaf_values_expr(self.leaves()[1], 'data'),
                         "[item.split(',')[0] for item in data]")

    def test_it_round_trips_through_the_dotfile(self):
        slots = _slots_from_columns(self.COLS)
        self.assertEqual(slots,
                         ['$', {'expr': self.SPLIT, 'cols': ['$[0]', '$[1]']}])
        exprs = [s if isinstance(s, str) else s['expr'] for s in slots]
        self.assertEqual(
            _columns_from_slots(exprs, parse_slot_cols(
                [s for s in slots if isinstance(s, dict)])),
            self.COLS)


class TestSubColumnComposition(unittest.TestCase):
    """What `$` means inside a sub-column: its parent's value for that row.
    Under a splat that is the element the row stands for; under a plain column
    it is the cell's own value, which makes the sub-column a composition. `$$`
    is the row under either, so the two scopes read the same way."""

    def test_it_reads_the_parents_value(self):
        self.assertEqual(_compose_sub('$[0]', "$.split(',')"),
                         "$.split(',')[0]")

    def test_the_row_is_still_reachable(self):
        self.assertEqual(_compose_sub('$$[1]', "$.split(',')"), '$[1]')

    def test_a_parent_that_needs_parens_gets_them(self):
        self.assertEqual(_compose_sub('$[0]', '$ + $'), '($ + $)[0]')

    def test_a_dollar_in_a_string_stays_string_content(self):
        self.assertEqual(_compose_sub("$['a$b']", "$.split(',')"),
                         "$.split(',')['a$b']")

    def test_plain_parents_nest(self):
        cols = {'$.a': {'cols': {'$.b': {'cols': {'$.c': {}}}}}}
        self.assertEqual([leaf.sub for leaf in _leaf_columns(cols)], ['$.a.b.c'])

    def test_a_splat_still_reads_its_element(self):
        cols = {'*$v': {'cols': {"$['who']": {}}}}
        leaf = _leaf_columns(cols)[0]
        self.assertEqual((leaf.splat, leaf.sub), ('*$v', "$['who']"))


class TestSubColumnDrags(unittest.TestCase):
    """Which rewrite a drag needs is the parent's business. Going IN always
    deepens -- under either kind of parent `$` is the parent's value and `$$`
    the row, so a column written against the row is one dollar further out.
    Coming OUT differs: a splat spread its value over rows and has to collect
    it back into a list, where a plain column's was never spread."""

    SPLIT = "$.split(',')"

    def test_going_in_deepens_under_a_plain_parent(self):
        cols = {"$['b']": {}, self.SPLIT: {'cols': {'$[0]': {}}}}
        self.assertTrue(_move_target(cols, "$['b']",
                                     f'{self.SPLIT}{SUBCOL_SEP}$[0]'))
        self.assertEqual(list(_col_subs(cols, self.SPLIT)),
                         ["$$['b']", '$[0]'])

    def test_a_suffixed_dollar_cannot_go_in(self):
        # `$k` would deepen to `$$k`, which binds nothing by design.
        cols = {'$k': {}, self.SPLIT: {'cols': {'$[0]': {}}}}
        self.assertFalse(_move_target(cols, '$k',
                                      f'{self.SPLIT}{SUBCOL_SEP}$[0]'))

    def test_coming_out_of_a_plain_column_composes(self):
        cols = {self.SPLIT: {'cols': {'$[0]': {}}}, '$x': {}}
        self.assertTrue(_move_target(cols, f'{self.SPLIT}{SUBCOL_SEP}$[0]',
                                     '$x'))
        self.assertIn("$.split(',')[0]", cols)

    def test_coming_out_of_a_splat_still_collects(self):
        cols = {'*$v': {'cols': {'$[0]': {}}}, '$x': {}}
        self.assertTrue(_move_target(cols, f'*$v{SUBCOL_SEP}$[0]', '$x'))
        self.assertIn('[item2[0] for item2 in $v]', cols)


class TestGroupAggregationColumns(unittest.TestCase):
    """A per-group aggregation as the COLUMN it is: the same question the whole
    column is asked, asked of one group as if the group were the list.

    Nothing stores it. The column is the only record, so ticking the box writes
    one and unticking takes it away -- and a reading is accepted only when it
    composes back character for character, the way a search is read back out of
    the box that wrote it."""

    def leaf(self, columns, index=-1):
        return _leaf_columns(columns)[index]

    SUBBED = {'$k': {}, '*$v': {'cols': {"$['n']": {}}}}
    BARE = {'$k': {}, '*$v': {}}

    def test_the_column_is_the_aggregation_over_one_group(self):
        leaf = self.leaf(self.SUBBED)
        self.assertEqual(_group_agg_column(leaf, 'sum($)'),
                         "sum([item2['n'] for item2 in $v])")

    def test_a_splat_with_no_subs_asks_after_the_group_itself(self):
        # `[item for item in $v]` is the same list spelled the long way.
        self.assertEqual(_group_agg_column(self.leaf(self.BARE), 'sum($)'),
                         'sum($v)')

    def test_a_hole_goes_in_filled(self):
        self.assertEqual(
            _group_agg_column(self.leaf(self.SUBBED), 'np.percentile($, {{90}})'),
            "np.percentile([item2['n'] for item2 in $v], 90)")

    def test_a_row_aggregation_keys_over_the_groups_rows(self):
        # `$$` is the group, `$` the column read off one of its rows -- which is
        # what min/max with a key is handed. These answer nothing at all today.
        self.assertEqual(_group_agg_column(self.leaf(self.SUBBED), ROW_AGGS[0]),
                         "min($v, key=lambda item: item['n'])")

    def test_a_histogram_contributes_its_question_not_its_line(self):
        # It carries the whole line it writes; a column is the right of the `=`.
        self.assertEqual(
            _group_agg_column(self.leaf(self.SUBBED), HISTOGRAM_AGG),
            "np.histogram([item2['n'] for item2 in $v], bins=10)")

    def test_a_leaf_two_splats_deep_asks_after_its_innermost_group(self):
        cols = {'*$v': {'cols': {"*$['pets']": {'cols': {"$['n']": {}}}}}}
        self.assertEqual(_group_agg_column(self.leaf(cols), 'sum($)'),
                         "sum([item3['n'] for item3 in $['pets']])")

    def test_the_element_is_named_by_its_level_so_a_sort_can_wrap_it(self):
        # This column is read once per ROW, so whatever wraps it binds the row
        # -- and `key=lambda item: sum([item['n'] for item in item[1]])`, which
        # is what Sort writes over one, is correct Python that reads like a bug.
        leaf = self.leaf(self.SUBBED)
        col = _group_agg_column(leaf, 'sum($)')
        self.assertNotIn('for item in', col)
        key = _sort_key_expr(col, 'd', _DICT_BINDS)
        self.assertEqual(key, "sum([item2['n'] for item2 in item[1]])")
        d = {'ann': [{'n': 3}, {'n': 5}], 'bob': [{'n': 4}]}
        self.assertEqual([k for k, _v in sorted(
            d.items(), key=eval(f'lambda item: {key}'), reverse=True)],
            ['ann', 'bob'])

    def test_nothing_groups_a_column_that_did_not_splat(self):
        self.assertIsNone(_group_agg_column(self.leaf({'$k': {}, '$v': {}}),
                                            'sum($)'))

    def test_a_column_that_names_where_its_row_sits_cannot_be_grouped(self):
        # `$i` is the ROOT row's number and `$j` the position in the group;
        # neither is a number the group counts in, so there is no honest column
        # to write and the box is not offered.
        for sub in ("$['n'] * $i", "$['n'] * $j"):
            cols = {'*$v': {'cols': {sub: {}}}}
            self.assertIsNone(_group_agg_column(self.leaf(cols), 'sum($)'), sub)

    def test_the_column_reads_back_as_the_row_that_wrote_it(self):
        leaf = self.leaf(self.SUBBED)
        for template in ('sum($)', 'len(set($))', ROW_AGGS[0], HISTOGRAM_AGG):
            written = _group_agg_column(leaf, template)
            self.assertEqual(_group_agg_template(written, leaf, template),
                             template, template)

    def test_a_level_is_read_back_out_of_the_column(self):
        # So the row shows the percentile the column actually computes rather
        # than the one the catalog opens with.
        leaf = self.leaf(self.SUBBED)
        written = _group_agg_column(leaf, 'np.percentile($, {{25}})')
        self.assertEqual(
            _group_agg_template(written, leaf, 'np.percentile($, {{10}})'),
            'np.percentile($, {{25}})')

    def test_a_column_that_is_not_this_row_is_not_read_as_it(self):
        leaf = self.leaf(self.SUBBED)
        self.assertIsNone(_group_agg_template(
            _group_agg_column(leaf, 'min($)'), leaf, 'sum($)'))

    def test_a_column_the_user_wrote_is_not_read_as_an_aggregation(self):
        leaf = self.leaf(self.SUBBED)
        for expr in ('len($v)', '$k', "sum([item2['n'] for item2 in $v]) / 2"):
            self.assertIsNone(_group_agg_template(expr, leaf, 'sum($)'), expr)


class TestGroupAggregationRendering(unittest.TestCase):
    """A per-group answer is a column of the table, at the level its group is a
    row of -- so it rowspans that group because that is what a column at that
    depth already does, and needs no drawing code of its own."""

    D = {'a': [{'n': 1}, {'n': 2}, {'n': 3}], 'b': [{'n': 10}, {'n': 20}]}
    COLS = {'$k': {}, '*$v': {'cols': {"$['n']": {}}}}

    def render(self, columns=None):
        m = init_model(self.D, mock_get_visualizer_dict_tables,
                       var_and_exp=('d', 'd'))
        m['columns'] = copy.deepcopy(columns or self.COLS)
        return visualize(self.D, m, mock_get_visualizer_dict_tables, None)

    def rows(self, html_out):
        body = html_out.split('<tfoot')[0]
        return re.findall(r'<tr[^>]*>.*?</tr>', body, re.S)

    def with_agg(self, template='sum($)'):
        cols = copy.deepcopy(self.COLS)
        leaf = _leaf_columns(cols)[-1]
        cols[_group_agg_column(leaf, template)] = {}
        return cols

    def test_the_table_grows_a_column_rather_than_rows(self):
        plain = self.rows(self.render())
        with_agg = self.rows(self.render(self.with_agg()))
        self.assertEqual(len(with_agg), len(plain))

    def test_the_answers_are_one_per_group(self):
        out = self.render(self.with_agg())
        self.assertIn('>6<', out)   # group 'a'
        self.assertIn('>30<', out)  # group 'b'

    def test_the_answer_spans_its_group(self):
        out = self.render(self.with_agg())
        # `$k` and the answer both span their group: 3 rows and 2 rows.
        self.assertIn('rowspan="3"', out)
        self.assertIn('rowspan="2"', out)

    def test_no_row_of_answers_is_drawn_at_all(self):
        out = self.render(self.with_agg())
        self.assertNotIn('group-agg', out)

    def test_the_whole_column_answer_still_goes_under_the_table(self):
        m = init_model(self.D, mock_get_visualizer_dict_tables,
                       var_and_exp=('d', 'd'))
        m['columns'] = copy.deepcopy(self.COLS)
        _set_column_computes(m, f'*$v{SUBCOL_SEP}$[\'n\']', ['sum($)'])
        out = visualize(self.D, m, mock_get_visualizer_dict_tables, None)
        self.assertIn('<tfoot', out)
        self.assertIn('36', out)  # 1+2+3+10+20, the flattened column
        self.assertNotIn('group-agg', out)

    def test_the_answer_column_can_be_sorted_on(self):
        # The whole point: a group's answer is a value of a row of this table,
        # so the groups can be ordered by it.
        cols = self.with_agg()
        expr = list(cols)[-1]
        self.assertEqual(_column_row_expr(cols, expr), expr)

    def test_a_leaf_two_splats_deep_lands_among_its_splats_siblings(self):
        cols = {'*$v': {'cols': {"*$['pets']": {'cols': {"$['n']": {}}}}}}
        leaf = _leaf_columns(cols)[-1]
        self.assertEqual(_leaf_splat_target(leaf),
                         f"*$v{SUBCOL_SEP}*$['pets']")
        # Which is a sub-column of the outer splat, drawn at depth 1.
        _col_add(_col_subs(cols, '*$v'), _group_agg_column(leaf, 'sum($)'))
        added = next(lf for lf in _leaf_columns(cols)
                     if lf.expr.endswith(_group_agg_column(leaf, 'sum($)')))
        self.assertEqual(added.depth, 1)


class TestGroupAggregationMenu(unittest.TestCase):
    """The second checkbox: a splatted column can be asked the same question of
    the whole column or of each group, and the second writes a column."""

    D = {'a': [{'n': 1}, {'n': 2}], 'b': [{'n': 5}]}
    COLS = {'$k': {}, '*$v': {'cols': {"$['n']": {}}}}

    def model(self, columns=None):
        m = init_model(self.D, mock_get_visualizer_dict_tables,
                       var_and_exp=('d', 'd'))
        m['columns'] = copy.deepcopy(columns or self.COLS)
        return m

    def leaf_expr(self, model):
        """The splatted column, which is the one with two boxes -- asked for by
        what it is, since the answers it writes are drawn columns too."""
        return next(lf.expr for lf in _leaf_columns(model['columns'])
                    if lf.splat is not None)

    def panel(self, model, col=None):
        col = col or self.leaf_expr(model)
        model = dict(model, openDropdown={'id': _menu_id('col-menu', col)},
                     col_search_dropdown=_menu_id('compute', col))
        out = visualize(self.D, model, mock_get_visualizer_dict_tables, None)
        self.assertIn('col-compute-panel', out)
        return out[out.index('col-compute-panel'):]

    def toggle_cmds(self, model, expr='sum($)', col=None, per_group=False):
        """The same click, keeping what it asked the editor for."""
        event = ComputeToggle(col=col or self.leaf_expr(model), expr=expr,
                              per_group=per_group)
        return update(make_column_mouse_event(repr(event)), None, model,
                      self.D, mock_get_visualizer_dict_tables)

    def toggle(self, model, expr='sum($)', col=None, per_group=False):
        """Click a Compute box the way the markup offers it."""
        return self.toggle_cmds(model, expr, col, per_group)[0]

    def test_a_splatted_column_offers_the_second_box(self):
        out = self.panel(self.model())
        self.assertIn('col-compute-group-toggle', out)
        self.assertIn('per_group=True', out)

    def test_a_column_that_did_not_splat_offers_one_box(self):
        m = self.model({'$k': {}, '$v': {}})
        out = self.panel(m, col='$v')
        self.assertNotIn('col-compute-group-toggle', out)
        self.assertNotIn('per_group=True', out)

    def test_ticking_the_second_box_adds_a_column(self):
        m = self.toggle(self.model(), per_group=True)
        self.assertIn("sum([item2['n'] for item2 in $v])", m['columns'])
        # And keeps nothing of its own: the column IS the record.
        self.assertIsNone(m.get('column_computes'))

    def test_the_new_column_sits_beside_the_splat_it_summarises(self):
        m = self.toggle(self.model(), per_group=True)
        self.assertEqual(list(m['columns']),
                         ['$k', '*$v', "sum([item2['n'] for item2 in $v])"])

    def test_unticking_takes_the_column_away_again(self):
        before = self.model()
        after = self.toggle(self.toggle(before, per_group=True),
                            per_group=True)
        self.assertEqual(list(after['columns']), list(before['columns']))

    def test_two_asks_read_in_the_order_the_submenu_lists_them(self):
        m = self.model()
        m = self.toggle(m, expr='max($)', per_group=True)
        m = self.toggle(m, expr='min($)', per_group=True)
        # Min is above Max in the catalog, so it goes above it here too.
        self.assertEqual(list(m['columns'])[2:],
                         ["min([item2['n'] for item2 in $v])",
                          "max([item2['n'] for item2 in $v])"])

    def test_the_two_boxes_are_independent(self):
        m = self.model()
        m = self.toggle(m, per_group=True)
        m = self.toggle(m)
        self.assertEqual(_column_computes(m, self.leaf_expr(m)), ['sum($)'])
        self.assertIn("sum([item2['n'] for item2 in $v])", m['columns'])
        # Unticking the whole-column one leaves the column alone.
        m = self.toggle(m)
        self.assertEqual(_column_computes(m, self.leaf_expr(m)), [])
        self.assertIn("sum([item2['n'] for item2 in $v])", m['columns'])

    def test_the_second_box_reads_back_as_checked(self):
        m = self.model()
        leaf = _leaf_columns(m['columns'])[-1]
        m['columns'][_group_agg_column(leaf, 'sum($)')] = {}
        out = self.panel(m, col=leaf.expr)
        group_boxes = re.findall(
            r'<span class="col-compute-group-toggle".*?</span>', out, re.S)
        self.assertTrue(any('checked' in b for b in group_boxes))

    def test_an_old_event_without_the_flag_still_means_the_whole_column(self):
        m = self.toggle(self.model())
        self.assertEqual(_column_computes(m, self.leaf_expr(m)), ['sum($)'])
        self.assertEqual(len(m['columns']), 2)

    def test_editing_the_level_rewrites_the_column_in_place(self):
        m = self.model()
        m = self.toggle(m, expr='np.percentile($, {{10}})', per_group=True)
        col = self.leaf_expr(m)
        event = ComputeHoleInput(col=col, expr='np.percentile($, {{10}})',
                                 hole=0, value='25')
        m, _ = update(make_column_mouse_event(repr(event)), None, m,
                      self.D, mock_get_visualizer_dict_tables)
        self.assertEqual(list(m['columns'])[2:],
                         ["np.percentile([item2['n'] for item2 in $v], 25)"])

    def test_the_answer_survives_the_splat_being_removed(self):
        # It names the group's own list rather than the column that spread it.
        m = self.toggle(self.model(), per_group=True)
        expr = list(m['columns'])[-1]
        del m['columns']['*$v']
        out = visualize(self.D, m, mock_get_visualizer_dict_tables, None)
        self.assertIn(expr, html.unescape(out))
        self.assertIn('>3<', out)  # group 'a'

    def imports_asked_for(self, commands):
        return [c for c in commands if isinstance(c, AddImports)]

    def test_a_column_that_reaches_for_numpy_asks_for_the_import(self):
        """The first box writes a line and declares its imports alongside it.
        The second writes a column instead -- code with no line of its own, run
        in the user's scope on every run -- so a percentile lands in a file with
        no numpy in it and has nothing to show. It asks on the column's behalf.
        """
        _m, commands = self.toggle_cmds(self.model(),
                                        expr='np.percentile($, {{10}})',
                                        per_group=True)
        self.assertEqual(self.imports_asked_for(commands),
                         [AddImports(imports=('import numpy as np',))])

    def test_an_answer_in_plain_python_asks_for_nothing(self):
        _m, commands = self.toggle_cmds(self.model(), per_group=True)
        self.assertEqual(self.imports_asked_for(commands), [])

    def test_the_column_is_read_rather_than_the_row_that_asked_for_it(self):
        """What the answer needs is read off the answer, because the column it
        sums may be code a nested visualizer wrote: `sum($)` reaches for nothing
        on its own, but the group's answer holds the `re.sub` too."""
        m = self.model({'$k': {}, '*$v': {'cols': {"re.sub(r'x', '', $['n'])": {}}}})
        _m, commands = self.toggle_cmds(m, per_group=True)
        self.assertEqual(self.imports_asked_for(commands),
                         [AddImports(imports=('import re',))])

    def test_unticking_asks_for_nothing(self):
        """Taking the column away leaves no code behind to need anything."""
        m = self.toggle(self.model(), expr='np.percentile($, {{10}})',
                        per_group=True)
        _m, commands = self.toggle_cmds(m, expr='np.percentile($, {{10}})',
                                        per_group=True)
        self.assertEqual(self.imports_asked_for(commands), [])

    def test_the_whole_column_box_asks_for_nothing_of_its_own(self):
        """It writes no code until Compute's code row is clicked, and the answer
        it shows is worked out in here, with numpy handed in."""
        _m, commands = self.toggle_cmds(self.model(),
                                        expr='np.percentile($, {{10}})')
        self.assertEqual(self.imports_asked_for(commands), [])


class TestDictPickExpression(unittest.TestCase):
    """Assembling picked regions of a dict table into one expression.

    A band of rows is a run of PAIRS, so it is read out of list(d.items()) --
    the same route every positional dict action takes. The inner comprehension
    binds `k2, v2` rather than `k, v` so it cannot shadow the next(...) that
    will wrap it."""

    def _expr(self, picked):
        return make_dict_pick_model(picked=picked)['pick_expr']

    def test_a_matched_cell_is_the_column_itself(self):
        self.assertEqual(self._expr(['match_col_1']), '$v')
        self.assertEqual(self._expr(['match_col_0']), '$')
        self.assertEqual(self._expr(['match_idx']), 'i')

    def test_a_band_reads_through_the_items(self):
        self.assertEqual(self._expr(['pre_col_1']),
                         '[v2 for k2, v2 in list(d.items())[:i]]')
        self.assertEqual(self._expr(['post_col_1']),
                         '[v2 for k2, v2 in list(d.items())[i + 1:]]')

    def test_a_whole_column_is_what_the_header_hands_over(self):
        # Not a comprehension: the short spelling a person would recognise, and
        # the same one the column header drags.
        self.assertEqual(self._expr(['pre_col_1', 'match_col_1', 'post_col_1']),
                         'list(d.values())')
        self.assertEqual(self._expr(['pre_col_0', 'match_col_0', 'post_col_0']),
                         'list(d.items())')

    def test_the_identity_column_needs_no_comprehension(self):
        # `$` IS the pair, so a band of it is already the answer.
        self.assertEqual(self._expr(['pre_col_0']), 'list(d.items())[:i]')
        self.assertEqual(self._expr(['match_col_0', 'post_col_0']),
                         'list(d.items())[i:]')

    def test_the_index_column_is_positions_for_a_dict_too(self):
        self.assertEqual(self._expr(['pre_idx', 'match_idx', 'post_idx']),
                         'list(range(len(d)))')
        self.assertEqual(self._expr(['pre_idx']), 'list(range(i))')

    def test_a_column_naming_the_row_number_counts_from_the_band(self):
        model = make_dict_pick_model(picked=['post_col_1'],
                                     columns={'$': {}, '($i, $v)': {}})
        self.assertEqual(
            model['pick_expr'],
            '[(i, v2) for i, (k2, v2) in enumerate(list(d.items())[i + 1:], i + 1)]')

    def test_multiple_regions_become_a_tuple(self):
        self.assertEqual(self._expr(['match_idx', 'match_col_1']), '(i, $v)')


class TestDictPickGeneratedCode(unittest.TestCase):
    """The line a dict pick produces, and what it evaluates to."""

    def _generate(self, picked, action='filter', columns=None):
        model = make_dict_pick_model(picked=picked, columns=columns)
        ctx = _get_search_context(model, ('d', 'd'),
                                  eval_in_scope=dict_pick_eval)
        result = generate_action(action, ctx)
        return None if result is None else result[1]

    def test_a_scalar_pick_binds_the_pair(self):
        code = self._generate(['match_col_1'])
        self.assertEqual(
            code, 'next((v for k, v in d.items() if v < 28), None)')
        self.assertEqual(dict_pick_eval(code), 25)

    def test_an_index_pick_enumerates_the_items(self):
        code = self._generate(['match_idx'])
        self.assertEqual(
            code,
            'next((i for i, (k, v) in enumerate(d.items()) if v < 28), None)')
        self.assertEqual(dict_pick_eval(code), 1)

    def test_a_band_pick_runs_over_the_items(self):
        code = self._generate(['pre_col_1'])
        self.assertEqual(
            code,
            'next(([v2 for k2, v2 in list(d.items())[:i]] '
            'for i, (k, v) in enumerate(d.items()) if v < 28), None)')
        self.assertEqual(dict_pick_eval(code), [30])

    def test_the_band_names_do_not_shadow_the_binding(self):
        # k2/v2 inside, k/v outside: the predicate still reads the matched row.
        code = self._generate(['post_col_0'])
        self.assertEqual(dict_pick_eval(code), [('carol', 41)])

    def test_picking_the_whole_row_degenerates_to_the_plain_filter(self):
        # `$` IS the pair, so this is the ordinary dict first-match filter.
        self.assertEqual(self._generate(['match_col_0']),
                         'next(((k, v) for k, v in d.items() if v < 28), None)')

    def test_a_tuple_pick(self):
        self.assertEqual(dict_pick_eval(self._generate(['match_idx',
                                                        'match_col_1'])),
                         (1, 25))

    def test_loop_and_join_run_over_an_array_pick(self):
        # A band is a list whichever container it came from, so these need no
        # dict form of their own -- only the binding around them does.
        self.assertEqual(
            self._generate(['pre_col_1'], action='loop_no_idx'),
            'for item in next(([v2 for k2, v2 in list(d.items())[:i]] '
            'for i, (k, v) in enumerate(d.items()) if v < 28), None):')
        join = self._generate(['pre_col_1'], action='join')
        self.assertEqual(dict_pick_eval(join), '30')

    def test_no_pick_generates_the_plain_dict_filter(self):
        self.assertEqual(self._generate([]),
                         'next(((k, v) for k, v in d.items() if v < 28), None)')

    def test_both_generators_agree(self):
        from table_visualizer_grammar import generate_action as ggen
        for picked in ([], ['match_col_1'], ['match_idx'], ['pre_col_1'],
                       ['match_idx', 'match_col_1'], ['pre_col_0'],
                       ['pre_col_1', 'match_col_1', 'post_col_1']):
            with self.subTest(picked=picked):
                model = make_dict_pick_model(picked=picked)
                ctx = _get_search_context(model, ('d', 'd'),
                                          eval_in_scope=dict_pick_eval)
                live = generate_action('filter', ctx)
                self.assertEqual(ggen('filter', ctx)[1], live[1])

    def test_a_dict_pick_relinks_to_the_dict_it_came_from(self):
        from table_visualizer import _LINK_CONFIG, _ctx_to_model
        from visualizer_utils import parse_owned_line
        code = self._generate(['match_col_1'])
        owned = parse_owned_line(_LINK_CONFIG, code, ('d', 'd'))
        self.assertIsNotNone(owned)
        self.assertEqual(owned[0]['source_expr'], 'd')
        model = make_dict_pick_model(picked=[])
        _ctx_to_model(owned[0], model)
        self.assertEqual(model['search'], '$v < 28')
        self.assertEqual(model['pick_expr'], '$v')

    def test_a_list_pick_is_unchanged(self):
        model = make_pick_model(picked=['pre_col_1'])
        ctx = _get_search_context(model, ('strs', 'strs'),
                                  eval_in_scope=pick_eval)
        self.assertEqual(model['pick_expr'], '[len(x) for x in strs[:i]]')
        self.assertEqual(
            generate_action('filter', ctx)[1],
            'next(([len(x) for x in strs[:i]] for i, item in enumerate(strs) '
            'if len(item) > 4), None)')


class TestDictRelinkDollarizesItsOwnNames(unittest.TestCase):
    """A dict predicate read back off a line has to return to the search box as
    dollars. It was coming back as the bare comprehension names -- `v > 26`,
    which the box then evaluates against a `v` the user's program does not have
    -- because the dollarizer only knew a list's `item` and `i`."""

    D = {'alice': 30, 'bob': 25}

    def model_for(self, line):
        from table_visualizer import _ctx_to_model
        from table_visualizer_grammar import parse_generated_code
        model = init_model(self.D, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        _ctx_to_model(parse_generated_code(line), model)
        return model

    def test_a_value_predicate_comes_back_as_a_dollar(self):
        m = self.model_for('{k: v for k, v in d.items() if v > 26}')
        self.assertEqual(m['search'], '$v > 26')

    def test_a_key_predicate_comes_back_as_a_dollar(self):
        m = self.model_for("{k: v for k, v in d.items() if k != 'bob'}")
        self.assertEqual(m['search'], "$k != 'bob'")

    def test_the_index_comes_back_only_when_the_line_bound_it(self):
        m = self.model_for(
            '{k: v for i, (k, v) in enumerate(d.items()) if i > 0}')
        self.assertEqual(m['search'], '$i > 0')

    def test_a_users_own_name_is_not_mistaken_for_a_binding(self):
        # The unindexed form does not bind `i`, so an `i` in it is the user's.
        m = self.model_for('{k: v for k, v in d.items() if v > i}')
        self.assertEqual(m['search'], '$v > i')

    def test_names_inside_strings_are_left_alone(self):
        m = self.model_for("{k: v for k, v in d.items() if k == 'v is k'}")
        self.assertEqual(m['search'], "$k == 'v is k'")

    def test_a_list_predicate_is_unchanged(self):
        from table_visualizer import _ctx_to_model
        from table_visualizer_grammar import parse_generated_code
        model = init_model([1, 2, 3], mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        _ctx_to_model(parse_generated_code('[item for item in data if item > 1]'),
                      model)
        self.assertEqual(model['search'], '$ > 1')

    def test_the_search_it_restores_generates_the_line_it_came_from(self):
        for line in ('{k: v for k, v in d.items() if v > 26}',
                     "{k: v for k, v in d.items() if k != 'bob'}",
                     '{k: v for i, (k, v) in enumerate(d.items()) if i > 0}'):
            with self.subTest(line=line):
                model = self.model_for(line)
                ctx = _get_search_context(model, ('d', 'd'), source_expr='d')
                self.assertEqual(generate_action('filter', ctx)[1], line)


class TestDictColumnValues(unittest.TestCase):
    """_column_values' fast path lies for dicts: `$` short-circuits to
    list(lst), which for a dict is the KEYS -- silently wrong for tally, sort
    and every aggregation."""

    def test_the_bare_column_gives_pairs_not_keys(self):
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_column_values('$', d, model),
                         [('alice', 30), ('bob', 25)])

    def test_the_key_and_value_columns_read_their_halves(self):
        d = {'alice': 30, 'bob': 25}
        model = init_model(d, mock_get_visualizer_dict_tables)
        self.assertEqual(_column_values('$k', d, model), ['alice', 'bob'])
        self.assertEqual(_column_values('$v', d, model), [30, 25])

    def test_a_list_still_takes_the_fast_path(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(_column_values('$', lst, model), [1, 2, 3])


class TestTallyExprs(unittest.TestCase):
    """The Python behind the Tally / Items / Counts headers: what the section is
    showing, so what the user drags out is the list they were reading."""

    def exprs(self, model, lst, eval_in_scope=None):
        model = dict(model, _source_expr='data')
        return _tally_exprs('$', model, _tally(_column_values('$', lst, model)),
                            'data', eval_in_scope)

    def tally_expr(self, model, lst, eval_in_scope=None):
        return self.exprs(model, lst, eval_in_scope)[0]

    def test_an_untouched_tally_is_just_the_count(self):
        lst, model = tally_model()
        self.assertEqual(self.exprs(model, lst),
                         ('Counter(data)',
                          'list(Counter(data))',
                          'list(Counter(data).values())'))

    def test_a_computed_column_counts_the_column(self):
        # Counter takes any iterable, so there is no list to build on the way in.
        lst = [{'name': 'Alice'}, {'name': 'Bo'}]
        model = dict(init_model(lst, mock_get_visualizer), _source_expr='data')
        model['columns'] = ["$['name']"]
        tally = _tally(_column_values("$['name']", lst, model))
        self.assertEqual(
            _tally_exprs("$['name']", model, tally, 'data')[0],
            "Counter(item['name'] for item in data)")

    def test_a_column_that_is_the_item_is_counted_as_it_stands(self):
        lst, model = tally_model()
        self.assertEqual(self.tally_expr(model, lst), 'Counter(data)')

    def test_no_source_to_read_from_means_no_expression(self):
        lst, model = tally_model()
        model['_source_expr'] = None
        self.assertIsNone(
            _tally_exprs('$', model, _tally(lst), None))

    # --- the Sort by chip ---

    def test_most_common_first(self):
        lst, model = tally_model()
        model['tally_sort'] = 'common'
        self.assertEqual(
            self.exprs(model, lst),
            ('{v: c for v, c in Counter(data).most_common()}',
             '[v for v, c in Counter(data).most_common()]',
             '[c for v, c in Counter(data).most_common()]'))

    def test_rarest_first(self):
        lst, model = tally_model()
        model['tally_sort'] = 'rare'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for v, c in reversed(Counter(data).most_common())}')

    def test_by_value(self):
        lst, model = tally_model()
        model['tally_sort'] = 'item asc'
        self.assertEqual(self.tally_expr(model, lst),
                         '{v: c for v, c in sorted(Counter(data).items())}')
        model['tally_sort'] = 'item desc'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for v, c in sorted(Counter(data).items(), reverse=True)}')

    def test_a_column_of_mixed_types_sorts_on_how_it_reads(self):
        # The same fallback the display takes: values with no order of their own
        # still read in some order.
        lst = ['b', 1, 'b']
        _, model = tally_model(lst)
        model['tally_sort'] = 'item asc'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for v, c in sorted(Counter(data).items(), '
            'key=lambda vc: repr(vc[0]))}')

    # --- the display filters ---

    def test_the_filter_box_narrows_the_expression_too(self):
        lst, model = tally_model()
        model['tally_filter'] = ' A '
        self.assertEqual(
            self.exprs(model, lst),
            ("{v: c for v, c in Counter(data).items() if 'a' in repr(v).lower()}",
             "[v for v, c in Counter(data).items() if 'a' in repr(v).lower()]",
             "[c for v, c in Counter(data).items() if 'a' in repr(v).lower()]"))

    def test_the_count_box_narrows_the_expression_too(self):
        lst, model = tally_model()
        model['tally_count_filter'] = '3'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for v, c in Counter(data).items() if c >= 3}')
        model['tally_count_op'] = '=='
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for v, c in Counter(data).items() if c == 3}')

    def test_a_count_box_naming_the_programs_own_value_says_so(self):
        lst, model = tally_model()
        model['tally_count_filter'] = 'floor'
        self.assertEqual(
            self.tally_expr(model, lst, lambda code: eval(code, {'floor': 3})),
            '{v: c for v, c in Counter(data).items() if c >= floor}')

    def test_a_count_box_holding_an_operator_of_its_own_is_parenthesized(self):
        lst, model = tally_model()
        model['tally_count_filter'] = 'floor - 1'
        self.assertEqual(
            self.tally_expr(model, lst, lambda code: eval(code, {'floor': 4})),
            '{v: c for v, c in Counter(data).items() if c >= (floor - 1)}')

    def test_a_count_box_with_nothing_to_compare_against_narrows_nothing(self):
        lst, model = tally_model()
        model['tally_count_filter'] = 'half'  # a name that never arrives
        self.assertEqual(self.tally_expr(model, lst), 'Counter(data)')

    def test_the_two_boxes_narrow_together(self):
        lst, model = tally_model()
        model['tally_filter'] = 'a'
        model['tally_count_filter'] = '2'
        self.assertEqual(
            self.tally_expr(model, lst),
            "{v: c for v, c in Counter(data).items() "
            "if 'a' in repr(v).lower() and c >= 2}")

    def test_min_and_max_ask_the_list_rather_than_the_box(self):
        # Counting twice to answer one question would be a strange way to write
        # it, so the count and the extreme are each named once and used after.
        lst, model = tally_model()
        model['tally_count_op'] = 'max'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for _cnts in [Counter(data)] '
            'for _max in [max(_cnts.values())] '
            'for v, c in _cnts.items() if c == _max}')
        model['tally_count_op'] = 'min'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for _cnts in [Counter(data)] '
            'for _min in [min(_cnts.values())] '
            'for v, c in _cnts.items() if c == _min}')

    def test_min_and_max_answer_about_the_list_the_filter_box_left(self):
        lst, model = tally_model()
        model['tally_filter'] = 'a'
        model['tally_count_op'] = 'max'
        self.assertEqual(
            self.tally_expr(model, lst),
            "{v: c for _cnts in [Counter(data)] "
            "for _max in [max(c2 for v2, c2 in _cnts.items() "
            "if 'a' in repr(v2).lower())] "
            "for v, c in _cnts.items() "
            "if 'a' in repr(v).lower() and c == _max}")

    def test_the_extreme_reads_the_order_the_menu_is_listing_in(self):
        lst, model = tally_model()
        model['tally_sort'] = 'common'
        model['tally_count_op'] = 'min'
        self.assertEqual(
            self.tally_expr(model, lst),
            '{v: c for _cnts in [Counter(data)] '
            'for _min in [min(_cnts.values())] '
            'for v, c in _cnts.most_common() if c == _min}')

    def test_a_count_that_is_asked_for_once_is_not_named(self):
        # Naming it would be a line about nothing: the comparison the box makes
        # reads the counter no more often than the values do.
        lst, model = tally_model()
        model['tally_count_filter'] = '3'
        self.assertNotIn('_cnts', self.tally_expr(model, lst))

    def test_a_menu_showing_nothing_has_nothing_to_hand_over(self):
        lst, model = tally_model()
        model['tally_filter'] = 'zzz'
        self.assertIsNone(self.exprs(model, lst))

    def test_the_expressions_produce_what_the_menu_lists(self):
        # The point of all of it: run the code and get the rows on screen.
        lst, model = tally_model()
        model['tally_sort'] = 'common'
        model['tally_filter'] = 'a'
        scope = {'data': lst, 'Counter': Counter}
        tally_expr, items_expr, counts_expr = self.exprs(model, lst)
        self.assertEqual(eval(tally_expr, scope), {'aa': 2})
        self.assertEqual(eval(items_expr, scope), ['aa'])
        self.assertEqual(eval(counts_expr, scope), [2])

    def test_every_sort_and_filter_combination_still_runs(self):
        lst = ['c', 'aa', 'b', 'c', 'b', 'c', 'aa']
        _, model = tally_model(lst)
        scope = {'data': lst, 'Counter': Counter}
        for sort in TALLY_SORTS:
            for filter_text in ('', 'a'):
                for op, count in [('>=', '2'), ('<=', '2'), ('==', '2'),
                                  ('min', ''), ('max', '')]:
                    with self.subTest(sort=sort, filter=filter_text, op=op):
                        model = dict(model, tally_sort=sort,
                                     tally_filter=filter_text,
                                     tally_count_op=op,
                                     tally_count_filter=count)
                        exprs = self.exprs(model, lst)
                        if exprs is None:
                            continue
                        tally_expr, items_expr, counts_expr = exprs
                        counted = eval(tally_expr, scope)
                        self.assertEqual(list(counted), eval(items_expr, scope))
                        self.assertEqual(list(counted.values()),
                                         eval(counts_expr, scope))
                        rendered = _column_tally_rows('$', model, lst)
                        extreme = _tally_extreme(model, rendered)
                        shown = [(text, c) for text, c, _lit in rendered
                                 if _tally_lists(model, text, c, extreme)]
                        produced = [(repr(v), c) for v, c in counted.items()]
                        if sort == 'rare':
                            # See test_rare_reverses_ties: same rows, and only
                            # equally rare ones can be in a different order.
                            produced, shown = sorted(produced), sorted(shown)
                        self.assertEqual(produced, shown)

    def test_rare_reverses_ties(self):
        # `reversed(most_common())` is the readable way to ask for it, and the
        # one place it parts company with the list on screen: the display sorts
        # by count and so leaves equally rare values in first-seen order, while
        # reversing hands them back last-seen first. Same values, same counts.
        lst = ['c', 'c', 'a', 'b']
        _, model = tally_model(lst)
        model['tally_sort'] = 'rare'
        self.assertEqual(
            [v for v, _c in _sorted_tally(_tally(lst), 'rare')], ['a', 'b', 'c'])
        self.assertEqual(
            list(eval(self.tally_expr(model, lst),
                      {'data': lst, 'Counter': Counter})),
            ['b', 'a', 'c'])


class TestTallyRowCounts(unittest.TestCase):
    """A row's count is a question about one value, so it hands over the code
    that asks it -- without counting the other values to get there."""

    def counts(self, model, lst, col='$'):
        model = dict(model, _source_expr='data', columns=[col])
        model['openDropdown'] = {'id': menu_id(model)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        return re.findall(r'<span class="col-tally-count"([^>]*)>', th)

    def test_the_item_column_asks_the_list_itself(self):
        lst, model = tally_model()
        self.assertEqual(exps_in(self.counts(model, lst)[0]),
                         [["data.count('c')"]])

    def test_a_computed_column_counts_what_matches(self):
        lst = [{'species': s} for s in ('cat', 'dog', 'cat')]
        _, model = tally_model(lst)
        self.assertEqual(
            exps_in(self.counts(model, lst, "$['species']")[0]),
            [["sum(1 for item in data if item['species'] == 'cat')"]])

    def test_the_count_reads_leftwards_from_the_rows_edge(self):
        lst, model = tally_model()
        self.assertIn('snc-py-exp-align="right"', self.counts(model, lst)[0])

    def test_the_counts_are_what_the_rows_show(self):
        lst = [{'species': s} for s in ('cat', 'dog', 'cat', 'bird', 'cat')]
        _, model = tally_model(lst)
        exprs = [exps_in(attrs)[0][0]
                 for attrs in self.counts(model, lst, "$['species']")]
        self.assertEqual([eval(e, {'data': lst}) for e in exprs], [3, 1, 1])

    def test_a_value_with_no_literal_has_nothing_to_ask_with(self):
        class Thing:
            def __repr__(self):
                return '<thing>'
        lst = ['c', Thing()]
        _, model = tally_model(lst)
        counts = self.counts(model, lst)
        self.assertIn('snc-py-exps', counts[0])
        self.assertNotIn('snc-py-exps', counts[1])

    def test_a_column_with_no_source_hands_over_nothing(self):
        lst, model = tally_model()
        model = dict(model, openDropdown={'id': 'col-menu-0'})
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertNotIn('snc-py-exps', th)

    def test_only_a_sequence_is_asked_to_count_its_own(self):
        # `.count` is the list's way of answering this, so it needs a value
        # that has one. Today that is every value here; it may not always be.
        self.assertEqual(_tally_row_count_expr('$', 'data', "'c'", ['c', 'a']),
                         "data.count('c')")
        self.assertEqual(_tally_row_count_expr('$', 'data', "'c'", ('c', 'a')),
                         "data.count('c')")
        self.assertEqual(_tally_row_count_expr('$', 'data', "'c'", {'c', 'a'}),
                         "sum(1 for item in data if item == 'c')")

    def test_a_string_is_not_asked_to_count_its_own(self):
        # str.count answers a different question -- how many times one string
        # occurs inside another -- so it is no substitute here.
        self.assertEqual(_tally_row_count_expr('$', 'data', "'a'", 'aa'),
                         "sum(1 for item in data if item == 'a')")


class TestTallyHeadersHandOverTheirExpressions(unittest.TestCase):
    """The three headers are the grab handles for what the section computed."""

    def tally(self, model, lst, column=0):
        model = dict(model, _source_expr='data',
                     openDropdown={'id': menu_id(model, index=column)})
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertIn('<div class="col-tally">', th)
        return th[th.index('<div class="col-tally">'):]

    def exp_of(self, markup, klass):
        match = re.search(r'<span class="' + klass + r'"([^>]*)>', markup)
        self.assertIsNotNone(match, f'no {klass} span in {markup}')
        return match.group(1)

    def test_the_title_hands_over_the_tally(self):
        lst, model = tally_model()
        title = self.exp_of(self.tally(model, lst), 'col-tally-title-text')
        self.assertEqual(exps_in(title), [['Counter(data)']])
        self.assertIn('draggable="true"', title)

    def test_the_headers_hand_over_the_values_and_the_counts(self):
        lst, model = tally_model()
        tally = self.tally(model, lst)
        self.assertEqual(exps_in(self.exp_of(tally, 'col-tally-item-header')),
                         [['list(Counter(data))']])
        self.assertEqual(exps_in(self.exp_of(tally, 'col-tally-count-header')),
                         [['list(Counter(data).values())']])

    def test_the_counts_tooltip_stays_inside_the_menu(self):
        # It sits at the panel's right edge, so it reads leftwards.
        lst, model = tally_model()
        self.assertIn('snc-py-exp-align="right"',
                      self.exp_of(self.tally(model, lst),
                                  'col-tally-count-header'))

    def test_the_expressions_say_which_import_they_need(self):
        lst, model = tally_model()
        attrs = self.exp_of(self.tally(model, lst), 'col-tally-title-text')
        self.assertEqual(handles_in(attrs)[0][0]['imports'],
                         ['from collections import Counter'])

    def test_a_column_with_no_source_hands_over_nothing(self):
        lst, model = tally_model()
        model['openDropdown'] = {'id': menu_id(model)}
        th = _first_column_header(visualize(lst, model, mock_get_visualizer,
                                            None))
        self.assertNotIn('snc-py-exps', th[th.index('<div class="col-tally">'):])

    def test_a_tally_too_long_to_list_still_hands_over_its_count(self):
        lst = [str(i) for i in range(TALLY_MAX_CARDINALITY + 1)]
        _, model = tally_model(lst)
        tally = self.tally(model, lst)
        self.assertIn('col-tally-note', tally)
        self.assertEqual(exps_in(self.exp_of(tally, 'col-tally-title-text')),
                         [['Counter(data)']])

    def test_values_that_cannot_be_counted_hand_over_nothing(self):
        lst = [{'a': 1}, {'a': 2}]
        _, model = tally_model(lst)
        tally = self.tally(model, lst)
        self.assertIn('col-tally-note', tally)
        self.assertNotIn('snc-py-exps', tally)

    def test_a_menu_showing_nothing_hands_over_nothing(self):
        lst, model = tally_model()
        model['tally_filter'] = 'zzz'
        tally = self.tally(model, lst)
        self.assertIn('col-tally-note', tally)
        self.assertNotIn('snc-py-exps', tally)


# === Column compute tests ===

from table_visualizer import (
    COMPUTE_AGGS, HISTOGRAM_AGG, HISTOGRAM_BINS_TOOLTIP, NO_ANSWER,
    _agg_holes, _agg_fill, _agg_shape, _agg_set_hole, _agg_imports, _agg_expr,
    _agg_value, _agg_code, _agg_name, _format_agg_value,
    _agg_row_index_code, _agg_is_row, _agg_is_histogram, _agg_hist_svg,
    _table_child_value_getter, _agg_child_expr, _agg_layout,
)


# A column with a repeat in it, so #Unique has something to say, and no order
# to it, so Min Idx and Max Idx aren't both the last row.
COMPUTE_LIST = [3, 1, 4, 1, 5]


def agg_answers(html_str):
    """The text each answer's own visualizer drew, in order.

    An answer is a child now, so it isn't the .col-agg-value div's own text:
    this walks to the </div> that closes each one and takes the markup back
    out of what was inside it.

    Divs are what it counts because a div is the one tag here that always comes
    in a pair -- the answer's own visualizer is free to draw an <input>, an
    <svg> or a table of its own inside, and none of those can throw the count.
    """
    out = []
    for m in re.finditer(r'class="col-agg-value">', html_str):
        depth, end = 1, m.end()
        for tag in re.finditer(r'</?div\b', html_str[m.end():]):
            depth += 1 if tag.group() == '<div' else -1
            if depth == 0:
                end = m.end() + tag.start()
                break
        out.append(re.sub(r'<[^>]*>', '', html_str[m.end():end]))
    return out


def agg_named(label):
    """The catalog's expression for the row reading *label*, e.g. 'Mean'.

    Percentile names two rows, so it takes the first; the tests that care about
    which one say so by writing the expression out.
    """
    for row_label, template in COMPUTE_AGGS:
        if row_label == label:
            return template
    raise AssertionError(f'no aggregation named {label}')


def agg_row(label):
    """Which row of the menu an aggregation is, counting from the top.

    Named rather than counted to, so adding a row to the catalog doesn't move
    every test that was looking at one below it. Percentile names two rows and
    takes the first, the way agg_named does.
    """
    for i, (row_label, _) in enumerate(COMPUTE_AGGS):
        if row_label == label:
            return i
    raise AssertionError(f'no aggregation named {label}')


class TestAggHoles(unittest.TestCase):
    """A {{...}} in an aggregation is a text box, and what's typed in it is
    part of the expression rather than a setting stored beside it."""

    def test_reading_the_holes_out_of_a_template(self):
        self.assertEqual(_agg_holes('np.percentile($, {{10}})'), ['10'])
        self.assertEqual(_agg_holes('min($)'), [])

    def test_filling_a_template_drops_the_braces(self):
        self.assertEqual(_agg_fill('np.percentile($, {{10}})'),
                         'np.percentile($, 10)')
        self.assertEqual(_agg_fill('min($)'), 'min($)')

    def test_the_shape_is_the_template_with_its_holes_emptied(self):
        # What tells a percentile from a mean, without saying which percentile.
        self.assertEqual(_agg_shape('np.percentile($, {{10}})'),
                         _agg_shape('np.percentile($, {{90}})'))
        self.assertNotEqual(_agg_shape('np.percentile($, {{10}})'),
                            _agg_shape('np.median($)'))

    def test_writing_a_hole_leaves_the_rest_of_the_template_alone(self):
        self.assertEqual(_agg_set_hole('np.percentile($, {{10}})', 0, '25'),
                         'np.percentile($, {{25}})')

    def test_a_hole_that_is_not_there_changes_nothing(self):
        self.assertEqual(_agg_set_hole('min($)', 0, '25'), 'min($)')

    def test_braces_typed_into_a_box_cannot_close_it(self):
        # Otherwise the template stops being one hole and starts being two.
        self.assertEqual(_agg_holes(_agg_set_hole('np.percentile($, {{10}})',
                                                  0, '2}}5')),
                         ['25'])


class TestAggExpr(unittest.TestCase):
    """An aggregation that carries the line it writes is asking the question on
    the right of the `=`; the names on the left are where the line puts the
    answer, not part of it."""

    def test_the_names_a_line_answers_into_are_not_the_question(self):
        self.assertEqual(_agg_expr('counts, edges = np.histogram($, bins=10)'),
                         'np.histogram($, bins=10)')

    def test_one_name_reads_the_same_way(self):
        self.assertEqual(_agg_expr('total = sum($)'), 'sum($)')

    def test_an_expression_with_no_names_is_left_alone(self):
        self.assertEqual(_agg_expr('np.mean($)'), 'np.mean($)')

    def test_a_comparison_is_not_an_assignment(self):
        # `==` and `<=` open no left-hand side, and neither does `+=`, which
        # answers into a name that has to already hold something.
        for expr in ('min($) == 1', 'x <= 2', 'x != 2', 'x += 1'):
            with self.subTest(expr):
                self.assertEqual(_agg_expr(expr), expr)


class TestAggRowIndex(unittest.TestCase):
    """Min Item and Max Item answer with a row of the list rather than a value
    of its own. They ask row by row -- `min(lst, key=...)` -- so `$` in them is
    the column read off the row the key is handed."""

    def test_the_catalog_offers_min_item_and_max_item(self):
        self.assertEqual([label for label, template in COMPUTE_AGGS
                          if _agg_is_row(template)],
                         ['Min Item', 'Max Item'])

    def test_they_order_the_list_by_the_column_rather_than_index_into_it(self):
        self.assertEqual([template for _, template in COMPUTE_AGGS
                          if _agg_is_row(template)],
                         ['min($$, key=lambda item: $)',
                          'max($$, key=lambda item: $)'])

    def test_an_aggregation_that_answers_with_a_value_is_not_one(self):
        self.assertFalse(_agg_is_row('min($)'))
        # The index by itself is a number, not the row it names.
        self.assertFalse(_agg_is_row('np.argmin($)'))

    def test_an_aggregation_the_user_wrote_keeps_the_column_it_was_promised(self):
        # The free-form box says `$` is the whole column and `$$` the list, so
        # naming the list is not what makes an aggregation a row aggregation --
        # being one of these two is.
        self.assertFalse(_agg_is_row('$$[np.argmin($)]'))
        self.assertFalse(_agg_is_row('len($$) - len($)'))

    def test_the_index_is_the_list_own_index_of_the_row_it_picked(self):
        self.assertEqual(
            _agg_row_index_code("min(data, key=lambda item: item['b'])",
                                'data'),
            "data.index(min(data, key=lambda item: item['b']))")

    def test_a_row_aggregation_reads_as_its_name(self):
        self.assertEqual(_agg_name('min($$, key=lambda item: $)'), 'Min Item')
        self.assertEqual(_agg_name('max($$, key=lambda item: $)'), 'Max Item')

    def test_they_need_nothing_imported(self):
        # min and max are builtins; the row costs no numpy at all.
        self.assertEqual(_agg_imports('min($$, key=lambda item: $)'), ())


class TestAggImports(unittest.TestCase):
    """An expression says which import it needs, so the front end can decide
    whether the file already has it -- the way the tally's do."""

    def test_numpy_is_declared_by_the_expressions_that_use_it(self):
        self.assertEqual(_agg_imports('np.mean($)'), ('import numpy as np',))

    def test_math_is_declared_by_the_expressions_that_use_it(self):
        self.assertEqual(_agg_imports('sum(math.isnan(x) for x in $)'),
                         ('import math',))

    def test_a_builtin_needs_nothing(self):
        self.assertEqual(_agg_imports('min($)'), ())
        self.assertEqual(_agg_imports('len(set($))'), ())


class TestAggValues(unittest.TestCase):
    """Every aggregation in the catalog, over one small column."""

    def value(self, label_or_expr, values=None):
        expr = (label_or_expr if '$' in label_or_expr
                else agg_named(label_or_expr))
        return _agg_value(expr, COMPUTE_LIST if values is None else values)

    def test_the_catalog_reads_the_way_the_menu_lists_it(self):
        # Counts first, then the column read from its least to its greatest,
        # with each row's own idea of the middle in between; Histogram last,
        # since it is the whole column at once rather than one number out of it.
        self.assertEqual([label for label, _ in COMPUTE_AGGS],
                         ['#Unique', '#Present', '#Missing', '#NaN',
                          'Sum', 'Min', 'Min Idx', 'Min Item',
                          'Mean', 'Stddev (Pop)', 'Stddev (Sample)', 'Median',
                          'Percentile', 'Percentile', 'Max', 'Max Idx',
                          'Max Item', 'Histogram'])

    def test_each_aggregation_answers(self):
        for label, expected in [('#Unique', 4), ('#Present', 5), ('#Missing', 0),
                                ('#NaN', 0), ('Sum', 14),
                                ('Min', 1), ('Min Idx', 1), ('Mean', 2.8),
                                ('Median', 3), ('Max', 5), ('Max Idx', 4)]:
            with self.subTest(label):
                self.assertEqual(self.value(label), expected)

    def test_the_two_stddevs_divide_by_different_counts(self):
        # The same 12.8 of squared deviation, over the 5 values themselves and
        # over the 4 degrees of freedom a sample of them has.
        self.assertAlmostEqual(self.value('Stddev (Pop)'), math.sqrt(12.8 / 5))
        self.assertAlmostEqual(self.value('Stddev (Sample)'),
                               math.sqrt(12.8 / 4))

    def test_the_two_percentiles_ask_for_different_levels(self):
        self.assertEqual(self.value('np.percentile($, {{10}})'), 1.0)
        self.assertEqual(self.value('np.percentile($, {{90}})'), 4.6)

    def test_a_percentile_of_0_or_100_is_the_min_and_the_max(self):
        self.assertEqual(self.value('np.percentile($, {{0}})'), 1)
        self.assertEqual(self.value('np.percentile($, {{100}})'), 5)

    def test_present_and_missing_count_the_nones(self):
        values = [1, None, 3, None]
        self.assertEqual(self.value('#Present', values), 2)
        self.assertEqual(self.value('#Missing', values), 2)

    def test_a_column_of_strings_still_has_a_min_and_a_count(self):
        values = ['pear', 'apple', 'pear']
        self.assertEqual(self.value('Min', values), 'apple')
        self.assertEqual(self.value('#Unique', values), 2)

    def test_numpy_resolves_without_the_file_importing_it(self):
        # The user's own program has no numpy in it; the preview still answers.
        self.assertEqual(_agg_value('np.mean($)', [1, 2, 3],
                                    lambda code: eval(code, {}, {})), 3 - 1)

    def test_math_resolves_without_the_file_importing_it(self):
        # Nor any math, and #NaN is written with math.isnan.
        self.assertEqual(_agg_value('sum(math.isnan(x) for x in $)',
                                    [1.0, float('nan'), 3.0],
                                    lambda code: eval(code, {}, {})), 1)

    def test_nan_counts_the_nans(self):
        self.assertEqual(self.value('#NaN', [1.0, float('nan'), 3.0]), 1)
        self.assertEqual(self.value('#NaN', [1.0, 2.0]), 0)

    def test_a_row_aggregation_answers_with_the_row_the_column_picked(self):
        # The column is not the list here: the answer is the row the least of
        # those values belongs to, not the least value. `$` is bound to the
        # column read off one row, since that is what the key is handed.
        lst = [{'v': 30}, {'v': 10}, {'v': 20}]
        self.assertEqual(_agg_value(agg_named('Min Item'), None, None, lst,
                                    "item['v']"), {'v': 10})
        self.assertEqual(_agg_value(agg_named('Max Item'), None, None, lst,
                                    "item['v']"), {'v': 30})

    def test_the_item_column_orders_the_list_by_the_rows_themselves(self):
        self.assertEqual(_agg_value(agg_named('Min Item'), None, None,
                                    COMPUTE_LIST), 1)

    def test_a_row_aggregation_with_no_list_to_read_has_no_answer(self):
        self.assertIs(_agg_value(agg_named('Min Item'), [30, 10, 20]),
                      NO_ANSWER)

    def test_rows_that_cannot_be_compared_pick_none(self):
        # min raises rather than coercing, which np.argmin would not have.
        self.assertIs(_agg_value(agg_named('Min Item'), None, None, [1, 'a']),
                      NO_ANSWER)

    def test_a_histogram_answers_past_the_names_it_writes_into(self):
        # The aggregation carries the line everyone types by hand, so what it
        # computes is the right of the `=` and what it hands over is all of it.
        counts, edges = _agg_value(HISTOGRAM_AGG, COMPUTE_LIST)
        self.assertEqual(sum(counts), len(COMPUTE_LIST))
        self.assertEqual(len(counts), 10)
        self.assertEqual(len(edges), 11)

    def test_the_bins_box_says_how_many_bars(self):
        counts, _edges = _agg_value(
            'counts, edges = np.histogram($, bins={{4}})', COMPUTE_LIST)
        self.assertEqual(len(counts), 4)


class TestAggNonAnswers(unittest.TestCase):
    """A question this column can't answer is a row with nothing to show, never
    an exception out of a render."""

    def no_answer(self, label, values):
        self.assertIs(_agg_value(agg_named(label), values), NO_ANSWER)

    def test_an_empty_column_has_no_min(self):
        self.no_answer('Min', [])
        self.no_answer('Mean', [])

    def test_values_of_mixed_types_have_no_order(self):
        self.no_answer('Min', [1, 'a'])

    def test_strings_have_no_mean(self):
        self.no_answer('Mean', ['a', 'b'])

    def test_unhashable_values_cannot_be_counted_distinctly(self):
        self.no_answer('#Unique', [{'a': 1}, {'a': 2}])

    def test_a_column_of_nothing_but_none_has_no_min(self):
        self.no_answer('Min', [None, None])

    def test_a_hole_holding_something_other_than_a_number(self):
        # Half-typed, or never finished. Nothing to compute, and nothing said
        # about it either.
        self.assertIs(_agg_value('np.percentile($, {{}})', COMPUTE_LIST),
                      NO_ANSWER)
        self.assertIs(_agg_value('np.percentile($, {{abc}})', COMPUTE_LIST),
                      NO_ANSWER)

    def test_an_expression_that_does_not_parse(self):
        self.assertIs(_agg_value('min($', COMPUTE_LIST), NO_ANSWER)

    def test_a_bins_box_holding_something_other_than_a_count(self):
        for template in ('counts, edges = np.histogram($, bins={{}})',
                         'counts, edges = np.histogram($, bins={{abc}})',
                         'counts, edges = np.histogram($, bins={{0}})'):
            with self.subTest(template):
                self.assertIs(_agg_value(template, COMPUTE_LIST), NO_ANSWER)

    def test_a_column_of_strings_has_no_histogram(self):
        self.assertIs(_agg_value(HISTOGRAM_AGG, ['pear', 'apple']), NO_ANSWER)


class TestAggCode(unittest.TestCase):
    """What an aggregation hands over is itself, with $ bound to the same
    column expression the header already drags out."""

    def test_the_column_is_bound_where_the_dollar_was(self):
        self.assertEqual(_agg_code('np.mean($)', '[item["p"] for item in data]'),
                         'np.mean([item["p"] for item in data])')

    def test_the_item_column_hands_over_the_list_itself(self):
        self.assertEqual(_agg_code('min($)', 'data'), 'min(data)')

    def test_a_hole_is_filled_in_before_it_is_handed_over(self):
        self.assertEqual(_agg_code('np.percentile($, {{25}})', 'data'),
                         'np.percentile(data, 25)')

    def test_the_list_is_bound_where_the_second_dollar_was(self):
        self.assertEqual(_agg_code('len($$) - len($)',
                                   "[item['p'] for item in data]", 'data'),
                         "len(data) - len([item['p'] for item in data])")

    def test_a_row_aggregation_orders_the_list_by_one_rows_column(self):
        # `$` is bound to the column read off a row, which is what the caller
        # hands it, because that is the question a row aggregation asks.
        self.assertEqual(_agg_code(agg_named('Min Item'), "item['p']", 'data'),
                         "min(data, key=lambda item: item['p'])")

    def test_the_item_column_orders_the_list_by_its_own_rows(self):
        self.assertEqual(_agg_code(agg_named('Min Item'), 'item', 'data'),
                         'min(data, key=lambda item: item)')

    def test_a_histogram_hands_over_the_line_it_writes(self):
        # Not the question alone: `np.histogram` answers with a pair, and the
        # line everyone types by hand is the one that gives the pair names.
        self.assertEqual(_agg_code(HISTOGRAM_AGG, 'data'),
                         'counts, edges = np.histogram(data, bins=10)')

    def test_what_it_hands_over_is_what_it_computed(self):
        # The preview and the code have to be the same question, or the number
        # on screen isn't the one the user drags into the file.
        np = __import__('numpy')
        # The file the code is dragged into has the imports the row declares.
        math = __import__('math')
        data = COMPUTE_LIST
        for _, template in COMPUTE_AGGS:
            with self.subTest(template):
                # What `$` stands for: every value the column has, or -- for a
                # row aggregation -- the column read off one row.
                column = 'item' if _agg_is_row(template) else 'data'
                code = _agg_code(template, column, 'data')
                answer = _agg_value(template, data, None, data, column)
                if _agg_is_histogram(template):
                    # A line rather than an expression, so it is run rather than
                    # evaluated -- and it answers with arrays, which compare
                    # element by element rather than to a yes or a no.
                    scope = {'np': np, 'data': data}
                    exec(code, scope)
                    self.assertEqual(len(answer), 2)
                    for written, computed in zip(('counts', 'edges'), answer):
                        self.assertTrue(np.array_equal(scope[written], computed))
                else:
                    self.assertEqual(
                        eval(code, {'np': np, 'math': math}, {'data': data}),
                        answer)


class TestAggName(unittest.TestCase):
    """What a row and its cell read an aggregation as: the catalog's word for
    it, with what is in its boxes left to the boxes."""

    def test_a_plain_aggregation_reads_as_its_name(self):
        self.assertEqual(_agg_name('np.mean($)'), 'Mean')

    def test_a_percentile_of_any_level_is_named_percentile(self):
        # The number is what the box beside the name reads, not part of it.
        self.assertEqual(_agg_name('np.percentile($, {{25}})'), 'Percentile')
        self.assertEqual(_agg_name('np.percentile($, {{}})'), 'Percentile')

    def test_an_aggregation_the_catalog_does_not_know_has_no_name(self):
        self.assertIsNone(_agg_name('sum($) / 2'))

    def test_a_histogram_is_named_however_many_bins_it_asked_for(self):
        self.assertEqual(
            _agg_name('counts, edges = np.histogram($, bins={{20}})'),
            'Histogram')


class TestAggHistogramSvg(unittest.TestCase):
    """A histogram answers with a pair of arrays, which no cell can read as
    text, so the cell draws the bars instead."""

    def bars(self, svg):
        """Each bar's height, in the order they read."""
        return [float(h) for h in re.findall(r'<rect [^>]*height="([^"]*)"', svg)]

    def svg(self, values, bins=4):
        answer = _agg_value(
            f'counts, edges = np.histogram($, bins={{{{{bins}}}}})', values)
        return _agg_hist_svg(answer)

    def test_the_catalog_row_is_a_histogram_at_any_bin_count(self):
        self.assertTrue(_agg_is_histogram(HISTOGRAM_AGG))
        self.assertTrue(_agg_is_histogram(
            'counts, edges = np.histogram($, bins={{20}})'))
        self.assertFalse(_agg_is_histogram('np.mean($)'))

    def test_one_bar_per_bin(self):
        self.assertEqual(len(self.bars(self.svg([1, 2, 3, 4], bins=4))), 4)

    def test_the_bars_stand_in_proportion_to_the_fullest_bin(self):
        # Two in the first bin and one in the last: half the height.
        bars = self.bars(self.svg([0, 0, 10], bins=2))
        self.assertEqual(bars[0], 2 * bars[1])

    def test_a_bin_with_something_in_it_is_never_too_short_to_see(self):
        # One beside a hundred rounds to nothing, and a bar that isn't drawn
        # reads as an empty bin rather than a rare one.
        bars = self.bars(self.svg([0] * 100 + [10], bins=2))
        self.assertGreaterEqual(bars[1], bars[0] / 10)

    def test_an_empty_bin_draws_nothing(self):
        bars = self.bars(self.svg([0, 0, 10, 10], bins=3))
        self.assertEqual(bars[1], 0)

    def test_the_drawing_fills_whatever_box_it_is_given(self):
        svg = self.svg(COMPUTE_LIST)
        self.assertIn('preserveAspectRatio="none"', svg)
        self.assertIn('class="col-agg-hist"', svg)

    def test_an_answer_that_is_not_a_pair_of_arrays_draws_nothing(self):
        # A cell that can't draw its answer reads it, rather than raising out
        # of a render.
        for answer in (2.8, None, NO_ANSWER, ('a', 'b'), (1, 2, 3)):
            with self.subTest(repr(answer)):
                self.assertEqual(_agg_hist_svg(answer), '')


class TestFormatAggValue(unittest.TestCase):
    """A number in a cell is read, not computed against, so it is rounded --
    the expression the cell hands over stays exact."""

    def test_a_long_float_is_cut_down_to_something_readable(self):
        self.assertEqual(_format_agg_value(1 / 3), '0.333333')

    def test_a_whole_number_keeps_no_decimal_point(self):
        self.assertEqual(_format_agg_value(3.0), '3')
        self.assertEqual(_format_agg_value(3), '3')

    def test_a_numpy_scalar_reads_as_the_number_it_is(self):
        import numpy as np
        self.assertEqual(_format_agg_value(np.int64(2)), '2')
        self.assertEqual(_format_agg_value(np.float64(2.5)), '2.5')

    def test_other_values_read_as_python(self):
        self.assertEqual(_format_agg_value('ab'), "&#x27;ab&#x27;")

    def test_a_value_too_long_for_a_cell_is_elided(self):
        self.assertIn('…', _format_agg_value('x' * 200))


from table_visualizer import (
    ComputeToggle, ComputeHoleInput,
    _column_computes, _set_column_computes, _compute_rows,
)

P10 = 'np.percentile($, {{10}})'
P90 = 'np.percentile($, {{90}})'


def agg_x_events(html_str):
    """The event behind each aggregation cell's ✕, in the order they are drawn.

    Read back out of the markup, so a click in a test is the click the cell
    really offers.
    """
    return [eval(html.unescape(m)) for m in re.findall(
        r'<span class="col-agg-x[^>]*snc-mouse-down="([^"]*)"', html_str)]


def make_compute_hole_event(col, expr, hole, value):
    """Create a ComputeHoleInput event for one of a row's boxes."""
    return {
        'pythonEventStr': (f"lambda e: ComputeHoleInput(col={col!r}, "
                           f"expr={expr!r}, hole={hole}, "
                           f"value=e.get('value', ''))"),
        'eventJSON': {'type': 'input', 'value': value},
    }


class TestComputeEvents(unittest.TestCase):
    """Checking a row writes its expression into the column's list, which is
    the only record of what is checked."""

    def click(self, model, lst, event):
        return update(make_column_mouse_event(repr(event)), None, model, lst,
                      mock_get_visualizer, eval_in_scope=eval)

    def toggle(self, model, lst, expr, index=0, col=None):
        model, _ = self.click(
            model, lst,
            ComputeToggle(col=col_at(model, index) if col is None else col,
                          expr=expr))
        return model

    def test_checking_a_row_stores_its_expression(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, 'min($)')
        self.assertEqual(_column_computes(model, '$'), ['min($)'])

    def test_checking_it_again_takes_it_away(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, 'min($)')
        model = self.toggle(model, lst, 'min($)')
        self.assertEqual(_column_computes(model, '$'), [])

    def test_a_column_with_nothing_checked_is_not_stored_at_all(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, 'min($)')
        model = self.toggle(model, lst, 'min($)')
        self.assertIsNone(model['column_computes'])

    def test_they_are_kept_in_the_order_the_menu_lists_them(self):
        # However the user clicked their way to them.
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, 'max($)')
        model = self.toggle(model, lst, 'np.mean($)')
        model = self.toggle(model, lst, 'min($)')
        self.assertEqual(_column_computes(model, '$'),
                         ['min($)', 'np.mean($)', 'max($)'])

    def test_the_two_percentiles_keep_the_order_they_were_asked_for(self):
        # They are the same shape, so nothing else distinguishes them.
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, P90)
        model = self.toggle(model, lst, P10)
        self.assertEqual(_column_computes(model, '$'), [P90, P10])

    def test_each_column_is_asked_separately(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        model = self.toggle(model, lst, 'min($)', index=0)
        model = self.toggle(model, lst, 'max($)', index=1)
        self.assertEqual(_column_computes(model, "$['a']"), ['min($)'])
        self.assertEqual(_column_computes(model, "$['b']"), ['max($)'])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, 'min($)', col='$.gone')
        self.assertIsNone(model['column_computes'])

    def test_the_menu_stays_open_across_a_click(self):
        # The whole point is checking several in a row.
        lst, model = tally_model(COMPUTE_LIST)
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'compute')
        model = self.toggle(model, lst, 'min($)')
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'compute'))

    def test_the_x_on_a_cell_takes_that_aggregation_away(self):
        # Clicked as the cell wrote it, so the ✕ is tested against the event it
        # really carries rather than one the test made up.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        model, _ = self.click(model, lst,
                              agg_x_events(visualize(lst, model,
                                                     mock_get_visualizer,
                                                     None))[0])
        self.assertIsNone(model['column_computes'])

    def test_the_x_takes_away_only_the_cell_it_is_on(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'np.mean($)', 'max($)'])
        xs = agg_x_events(visualize(lst, model, mock_get_visualizer, None))
        model, _ = self.click(model, lst, xs[1])
        self.assertEqual(_column_computes(model, '$'), ['min($)', 'max($)'])

    def test_the_x_names_the_column_it_is_under(self):
        lst = [{'a': 1, 'b': 2}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        _set_column_computes(model, "$['a']", ['min($)'])
        _set_column_computes(model, "$['b']", ['max($)'])
        xs = agg_x_events(visualize(lst, model, mock_get_visualizer, None))
        model, _ = self.click(model, lst, xs[1])
        self.assertEqual(_column_computes(model, "$['a']"), ['min($)'])
        self.assertEqual(_column_computes(model, "$['b']"), [])

    def test_the_aggregations_follow_a_renamed_column(self):
        lst = [{'a': 1}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']"]
        model = self.toggle(model, lst, 'min($)')
        model, _ = update(
            make_column_mouse_event(repr(ColumnClick(col=col_at(model))), detail=2),
            None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        model['column_input_value'] = "$['b']"
        model, _ = update(make_column_key_event('Enter'), None, model, lst,
                          mock_get_visualizer, eval_in_scope=eval)
        self.assertEqual(list(model['columns']), ["$['b']"])
        self.assertEqual(_column_computes(model, "$['b']"), ['min($)'])

    def test_a_removed_column_takes_its_aggregations_with_it(self):
        lst = [{'a': 1}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']"]
        model = self.toggle(model, lst, 'min($)')
        model, _ = update(
            make_column_mouse_event(repr(RemoveColumnClick(col=col_at(model)))),
            None, model, lst, mock_get_visualizer, eval_in_scope=eval)
        self.assertIsNone(model['column_computes'])


class TestComputeHoleEvents(unittest.TestCase):
    """Typing in a box edits the expression, because the box is part of it."""

    def input(self, model, lst, expr, value, hole=0, col=None):
        col = col_at(model) if col is None else col
        model, _ = update(make_compute_hole_event(col, expr, hole, value),
                          None, model, lst, mock_get_visualizer,
                          eval_in_scope=eval)
        return model

    def test_typing_in_a_checked_row_rewrites_its_expression_in_place(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', P10, 'max($)'])
        model = self.input(model, lst, P10, '25')
        self.assertEqual(_column_computes(model, '$'),
                         ['min($)', 'np.percentile($, {{25}})', 'max($)'])

    def test_typing_in_an_unchecked_row_asks_for_that_percentile(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, P10, '25')
        self.assertEqual(_column_computes(model, '$'),
                         ['np.percentile($, {{25}})'])

    def test_a_half_typed_number_is_kept_so_the_box_keeps_its_place(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [P10])
        model = self.input(model, lst, P10, '')
        self.assertEqual(_column_computes(model, '$'),
                         ['np.percentile($, {{}})'])

    def test_asking_twice_for_the_same_percentile_asks_once(self):
        # Editing 10 up to 90 with 90 already checked is one aggregation, not
        # two cells reading the same number.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [P10, P90])
        model = self.input(model, lst, P10, '90')
        self.assertEqual(_column_computes(model, '$'), [P90])

    def test_typing_at_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, P10, '25', col='$.gone')
        self.assertIsNone(model['column_computes'])


class TestComputeRows(unittest.TestCase):
    """What the submenu shows, all of it read back out of the column's list."""

    def rows(self, model, col='$'):
        return _compute_rows(model, col)

    def checked(self, model, col='$'):
        return [template for _, template, checked in self.rows(model, col)
                if checked]

    def test_nothing_checked_shows_the_catalog_as_written(self):
        _, model = tally_model(COMPUTE_LIST)
        self.assertEqual([(label, template) for label, template, _
                          in self.rows(model)], list(COMPUTE_AGGS))
        self.assertEqual(self.checked(model), [])

    def test_a_stored_expression_checks_its_row(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        self.assertEqual(self.checked(model), ['np.mean($)'])

    def test_a_percentile_claims_the_row_it_matches_exactly(self):
        # Not the first percentile row: 90 is written on the second one.
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [P90])
        rows = [(template, checked) for _, template, checked in self.rows(model)]
        self.assertIn((P10, False), rows)
        self.assertIn((P90, True), rows)

    def test_an_edited_percentile_claims_a_row_of_the_same_shape(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{25}})'])
        rows = [(template, checked) for _, template, checked in self.rows(model)]
        self.assertIn(('np.percentile($, {{25}})', True), rows)
        # The other percentile row is still there, reading as it always did.
        self.assertIn((P90, False), rows)

    def test_two_edited_percentiles_claim_both_rows(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{25}})',
                                          'np.percentile($, {{75}})'])
        self.assertEqual(self.checked(model), ['np.percentile($, {{25}})',
                                               'np.percentile($, {{75}})'])

    def test_unchecking_an_edited_row_leaves_the_row_reading_its_default(self):
        # The row doesn't vanish just because the number in it was the user's.
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{25}})'])
        _set_column_computes(model, '$', [])
        rows = [(template, checked) for _, template, checked in self.rows(model)]
        self.assertIn((P10, False), rows)
        self.assertIn((P90, False), rows)

    def test_the_rows_are_always_the_catalog_in_its_own_order(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['max($)', 'min($)'])
        self.assertEqual([label for label, _, _ in self.rows(model)],
                         [label for label, _ in COMPUTE_AGGS])


class TestComputeMenuRendering(unittest.TestCase):
    """The Compute submenu: a row per aggregation, each previewing its answer
    so reading one costs no more than opening the menu."""

    def header(self, model, lst, column=0, open_submenu=True, source=None):
        model = dict(model, openDropdown={'id': menu_id(model, index=column)})
        if open_submenu:
            model['col_search_dropdown'] = menu_id(model, 'compute', column)
        if source:
            model['_source_expr'] = source
        return _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      (lambda code: eval(code, {}, {'data': lst}))
                      if source else None))

    def panel(self, model, lst, **kwargs):
        th = self.header(model, lst, **kwargs)
        self.assertIn('col-compute-panel', th)
        return th[th.index('col-compute-panel'):]

    def rows(self, panel):
        return re.findall(r'<div class="col-compute-row[^"]*".*?(?=<div '
                          r'class="col-compute-row|$)', panel, re.DOTALL)

    def previews(self, panel):
        return re.findall(r'col-compute-preview"[^>]*>([^<]*)<', panel)

    def test_the_menu_offers_compute_without_being_asked_twice(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertIn('col-compute-trigger',
                      self.header(model, lst, open_submenu=False))

    def test_the_rows_are_only_there_when_the_submenu_is_open(self):
        # Nothing is computed for a menu the user hasn't opened.
        lst, model = tally_model(COMPUTE_LIST)
        self.assertNotIn('col-compute-panel',
                         self.header(model, lst, open_submenu=False))

    def test_a_closed_column_menu_computes_nothing(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertNotIn('col-compute',
                         visualize(lst, model, mock_get_visualizer, None))

    def test_every_aggregation_is_listed_in_the_catalog_order(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst)
        self.assertEqual(re.findall(r'col-compute-name">([^<]*)<', panel),
                         [label for label, _ in COMPUTE_AGGS]
                         + [label for label, _, _ in COMPUTE_CODES])

    def test_each_row_previews_its_answer(self):
        # Histogram draws its answer rather than reading it, so it previews as
        # no text at all; the last is the empty box at the foot of the menu,
        # which has no expression in it yet to answer with.
        lst, model = tally_model(COMPUTE_LIST)
        previews = self.previews(self.panel(model, lst))
        self.assertEqual(previews,
                         ['4', '5', '0', '0', '14', '1', '1', '1',
                          '2.8', '1.6', '1.78885', '3', '1', '4.6',
                          '5', '4', '5', '', ''])

    def test_a_row_aggregation_previews_the_row_it_picked(self):
        lst = [{'a': 1}, {'a': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']"]
        previews = self.previews(self.panel(model, lst))
        self.assertEqual([previews[agg_row('Min Item')],
                          previews[agg_row('Max Item')]],
                         [html.escape("{'a': 1}"), html.escape("{'a': 3}")])

    def test_the_histogram_row_previews_its_bars_rather_than_its_pair(self):
        lst, model = tally_model(COMPUTE_LIST)
        row = self.rows(self.panel(model, lst))[len(COMPUTE_AGGS) - 1]
        self.assertIn('>Histogram<', row)
        self.assertIn('col-agg-hist', row)
        self.assertNotIn('array(', row)

    def test_the_histogram_row_is_checkable_and_asks_for_its_bins(self):
        lst, model = tally_model(COMPUTE_LIST)
        row = self.rows(self.panel(model, lst))[len(COMPUTE_AGGS) - 1]
        self.assertIn('col-tally-check', row)
        self.assertIn('col-compute-hole', row)
        self.assertIn('value="10"', row)

    def test_the_bins_box_says_what_the_number_in_it_counts(self):
        # "Histogram 10" doesn't say what the 10 is; a percentile's box reads
        # off the name beside it, so only this one has anything to add.
        lst, model = tally_model(COMPUTE_LIST)
        rows = self.rows(self.panel(model, lst))
        self.assertIn(f'data-tooltip="{HISTOGRAM_BINS_TOOLTIP}"',
                      rows[len(COMPUTE_AGGS) - 1])
        percentile = rows[[label for label, _ in COMPUTE_AGGS]
                          .index('Percentile')]
        self.assertIn('col-compute-hole', percentile)
        self.assertNotIn('data-tooltip', percentile)

    def test_the_histogram_row_hands_over_the_line_it_writes(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst, source='data')
        self.assertIn(['counts, edges = np.histogram(data, bins=10)'],
                      exps_in(panel))

    def test_a_checked_row_says_so(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        rows = self.rows(self.panel(model, lst))
        mean = agg_row('Mean')
        checked = [i for i, row in enumerate(rows) if 'checked' in row]
        self.assertEqual(checked, [mean])
        self.assertIn('checked',
                      rows[mean][:rows[mean].index('col-compute-name')])

    def test_a_question_this_column_cannot_answer_cannot_be_checked(self):
        lst = ['pear', 'apple']
        _, model = tally_model(lst)
        rows = self.rows(self.panel(model, lst))
        mean = rows[agg_row('Mean')]
        self.assertIn('unselectable', mean)
        self.assertIn('disabled', mean)
        self.assertNotIn('snc-mouse-down', mean)
        # Min still answers for strings, so it stays clickable.
        self.assertIn('snc-mouse-down', rows[agg_row('Min')])

    def test_a_checked_row_stays_clickable_once_it_stops_answering(self):
        # Otherwise there is no way to uncheck it.
        lst = ['pear', 'apple']
        _, model = tally_model(lst)
        _set_column_computes(model, '$', ['np.mean($)'])
        self.assertIn('snc-mouse-down',
                      self.rows(self.panel(model, lst))[agg_row('Mean')])

    def test_a_hole_is_a_box_holding_what_the_expression_says(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst)
        self.assertEqual(re.findall(r'col-compute-hole[^>]*value="([^"]*)"',
                                    panel), ['10', '90', '10'])

    def test_an_edited_level_is_what_its_box_reads(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{50}})'])
        panel = self.panel(model, lst)
        self.assertEqual(re.findall(r'col-compute-hole[^>]*value="([^"]*)"',
                                    panel), ['50', '90', '10'])
        self.assertEqual(self.previews(panel)[agg_row('Percentile')], '3')

    def test_a_row_hands_over_the_code_behind_its_preview(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst, source='data')
        offered = exps_in(panel)
        for expr in ('np.mean(data)', 'min(data)', 'np.percentile(data, 90)',
                     'min(data, key=lambda item: item)'):
            self.assertIn([expr], offered)

    def test_the_expressions_say_which_import_they_need(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst, source='data')
        declared = {handle[0]['expr']: handle[0].get('imports')
                    for handle in handles_in(panel)}
        self.assertEqual(declared['np.mean(data)'], ['import numpy as np'])
        # min is a builtin and needs nothing said about it.
        self.assertIsNone(declared['min(data)'])

    def test_a_column_with_no_source_hands_over_nothing(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertNotIn('snc-py-exps', self.panel(model, lst))

    def test_a_preview_tooltip_stays_inside_the_menu(self):
        # It sits at the panel's right edge, so it reads leftwards.
        lst, model = tally_model(COMPUTE_LIST)
        self.assertIn('snc-py-exp-align="right"',
                      self.panel(model, lst, source='data'))


class TestComputeCellRendering(unittest.TestCase):
    """A checked aggregation is a cell under its column, labelled with what it
    asked."""

    def table(self, model, lst, source=None):
        if source:
            model = dict(model, _source_expr=source)
        return visualize(lst, model, mock_get_visualizer,
                         (lambda code: eval(code, {}, {'data': lst}))
                         if source else None)

    def rows(self, model, lst, **kwargs):
        out = self.table(model, lst, **kwargs)
        self.assertIn('col-agg-row', out)
        return re.findall(r'<tr class="col-agg-row">(.*?)</tr>',
                          out[out.index('<tr class="col-agg-row">'):],
                          re.DOTALL)

    def cells(self, row):
        # The cell carries classes past the first one (it is the hover parent
        # its ✕ hides behind), so the class list is read open-endedly.
        return re.findall(r'<td class="col-agg-cell[^"]*"[^>]*>(.*?)</td>', row,
                          re.DOTALL)

    def child_keys(self, model, lst, **kwargs):
        out = self.table(model, lst, **kwargs)
        return [eval(html.unescape(m)) for m in
                re.findall(r'snc-child-key="([^"]*)"', out[out.index('<tfoot'):])]

    def test_nothing_checked_is_no_row_at_all(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertNotIn('col-agg-row', self.table(model, lst))

    def test_a_checked_aggregation_reads_under_its_column(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        rows = self.rows(model, lst)
        self.assertEqual(len(rows), 1)
        cell = self.cells(rows[0])[0]
        self.assertIn('>Mean<', cell)
        self.assertIn('>2.8<', cell)

    def test_each_one_is_a_cell_of_its_own_under_the_last(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['max($)', 'min($)'])
        rows = self.rows(model, lst)
        self.assertEqual(len(rows), 2)
        self.assertEqual([re.search(r'col-agg-label">([^<]*)<', row).group(1)
                          for row in rows], ['Min', 'Max'])
        self.assertEqual([agg_answers(row)[0] for row in rows], ['1', '5'])

    def test_a_column_with_none_of_its_own_gets_a_blank_that_stays_put(self):
        # The cell has to be there to keep the columns lined up, but a column
        # with no answer has nothing to pin over the rows it would cover.
        lst = [{'a': 1, 'b': 2}, {'a': 3, 'b': 4}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        _set_column_computes(model, "$['b']", ['max($)'])
        row = self.rows(model, lst)[0]
        self.assertEqual(row.count('<td'), 3)  # row index, blank, answer
        self.assertIn('<td class="col-agg-blank"></td>', row)
        self.assertIn('>Max<', self.cells(row)[0])

    def test_a_column_that_runs_out_first_blanks_the_rows_above_it(self):
        # The stacks sit on the same floor, so a short one is padded at the top
        # and its last answer still reads beside every other column's last.
        lst = [{'a': 1, 'b': 2}, {'a': 3, 'b': 4}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        _set_column_computes(model, "$['a']", ['min($)'])
        _set_column_computes(model, "$['b']", ['min($)', 'max($)'])
        rows = self.rows(model, lst)
        self.assertEqual(len(rows), 2)
        # The index cell is blank in every row, so it is the blank *column*
        # cells that are counted here.
        self.assertEqual(rows[0].count('<td class="col-agg-blank">'), 1)
        self.assertEqual(rows[1].count('<td class="col-agg-blank">'), 0)
        # a's only answer is Min; it sits on the bottom row, beside b's Max.
        self.assertIn('>Min<', self.cells(rows[1])[0])
        self.assertIn('>Max<', self.cells(rows[1])[1])
        self.assertIn('>Min<', self.cells(rows[0])[0])

    def test_the_stacks_are_bottom_aligned(self):
        lst = [{'a': 1, 'b': 2, 'c': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']", "$['c']"]
        _set_column_computes(model, "$['a']", ['min($)', 'np.mean($)', 'max($)'])
        _set_column_computes(model, "$['b']", ['max($)'])
        _set_column_computes(model, "$['c']", ['np.mean($)', 'max($)'])
        self.assertEqual(_agg_layout(model['columns'], model), [
            ('cells', ['min($)', None, None]),
            ('cells', ['np.mean($)', None, 'np.mean($)']),
            ('cells', ['max($)', 'max($)', 'max($)']),
        ])

    def test_the_rows_go_in_a_foot_that_pins_itself(self):
        # The foot sticks as one block, so no row has to be told where to stop
        # -- and no row has to be the height every other row is.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'np.mean($)', 'max($)'])
        out = self.table(model, lst)
        self.assertIn('<tfoot class="col-agg-rows">', out)
        self.assertNotIn('--snc-agg-row-height', out)
        for row in self.rows(model, lst):
            self.assertNotIn('style=', row)

    def test_the_foot_holds_every_row_and_nothing_else(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'max($)'])
        foot = re.search(r'<tfoot class="col-agg-rows">(.*?)</tfoot>',
                         self.table(model, lst), re.DOTALL).group(1)
        self.assertEqual(foot.count('<tr class="col-agg-row"'), 2)
        self.assertTrue(foot.startswith('<tr class="col-agg-row"'))
        self.assertTrue(foot.endswith('</tr>'))

    def test_nothing_checked_is_no_foot_at_all(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertNotIn('<tfoot', self.table(model, lst))

    def test_a_cell_reads_what_is_in_its_boxes(self):
        # In boxes here too -- see TestAggregationCellHoles -- so the name is
        # the label's own text and the number is what the box beside it reads.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{25}})'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('>Percentile <', cell)
        self.assertIn('col-agg-hole', cell)
        self.assertIn('value="25"', cell)

    def test_an_aggregation_this_column_can_no_longer_answer_reads_empty(self):
        # The column's values changed under it; the cell says nothing rather
        # than disappearing and taking the row's layout with it.
        lst = ['pear', 'apple']
        _, model = tally_model(lst)
        _set_column_computes(model, '$', ['np.mean($)'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('>Mean<', cell)
        self.assertEqual(agg_answers(cell), [''])

    def test_a_cell_hands_over_the_code_behind_it(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        cell = self.cells(self.rows(model, lst, source='data')[0])[0]
        self.assertIn(['np.mean(data)'], exps_in(cell))
        self.assertIn('draggable="true"', cell)

    # --- The ✕ that takes an aggregation away ---

    def test_every_cell_carries_an_x_for_its_own_aggregation(self):
        # It is the submenu's own checkbox event: an aggregation is checked by
        # being in the column's list, so there is nothing else to unchecking it.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'max($)'])
        self.assertEqual(agg_x_events(self.table(model, lst)),
                         [ComputeToggle(col=col_at(model), expr='min($)'),
                          ComputeToggle(col=col_at(model), expr='max($)')])

    def test_the_x_asks_for_the_expression_the_cell_is_showing(self):
        # Boxes and all, since that is what the column has stored.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.percentile($, {{25}})'])
        self.assertEqual(agg_x_events(self.table(model, lst)),
                         [ComputeToggle(col=col_at(model), expr='np.percentile($, {{25}})')])

    def test_a_drag_off_the_x_hands_over_nothing(self):
        # The cell around it is a drag handle, and a drag begun on the ✕ is a
        # click the user slipped on rather than an ask for the code.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        x = re.search(r'<span class="col-agg-x[^>]*>',
                      self.table(model, lst, source='data')).group()
        self.assertIn('draggable="false"', x)

    # --- The answer is drawn by whichever visualizer reads its type ---

    def test_the_answer_is_drawn_by_the_visualizer_for_its_type(self):
        # A number is the number visualizer's business, the same as it is in
        # any other cell of the table -- not text this table formatted.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['max($)'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('child-expr', cell)  # only MockIntVisualizer writes this
        self.assertIn('>5<', cell)

    def test_an_answer_that_is_a_list_reads_as_a_list(self):
        # The point of handing it over: an answer no line of text can show.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)'])
        # A nested table has cells of its own, so read the row: self.cells
        # would stop at the first </td> inside it.
        self.assertIn('list-visualizer', self.rows(model, lst)[0])

    def test_each_answer_is_a_child_under_a_key_of_its_own(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'max($)'])
        keys = self.child_keys(model, lst)
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)

    def test_an_answer_with_nothing_in_it_is_no_child_at_all(self):
        # Nothing to hand to a visualizer, so nothing is handed over.
        lst = ['pear', 'apple']
        _, model = tally_model(lst)
        _set_column_computes(model, '$', ['np.mean($)'])
        self.assertEqual(self.child_keys(model, lst), [])

    def test_the_answer_is_handed_the_expression_behind_it(self):
        # Like a table cell, the child is handed its access path and decides
        # for itself what to do with it.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['max($)'])
        cell = self.cells(self.rows(model, lst, source='data')[0])[0]
        self.assertIn('child-expr=max(data)', cell)

    def test_a_number_still_reads_the_way_a_cell_reads_it(self):
        # numpy writes a scalar down as np.float64(2.8000000000000003); the
        # cell is read rather than computed against, so it gets the number.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('>2.8<', cell)
        self.assertNotIn('np.float64', cell)

    def test_the_answer_is_small_until_it_is_picked(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)'])
        self.assertIn('list-visualizer small', self.table(model, lst))
        model['focused_child'] = self.child_keys(model, lst)[0]
        self.assertNotIn('list-visualizer small', self.table(model, lst))

    def test_a_histogram_is_still_drawn_rather_than_handed_over(self):
        # A pair of arrays reads as bars or as nothing; no visualizer of its
        # own would draw it better than the cell does.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [HISTOGRAM_AGG])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('col-agg-hist', cell)
        self.assertNotIn('snc-child-key', cell)


    def test_a_histogram_cell_draws_its_answer_and_names_its_bins(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [HISTOGRAM_AGG])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('>Histogram <', cell)
        self.assertIn('col-agg-hole', cell)
        self.assertIn('value="10"', cell)
        self.assertIn('col-agg-hist', cell)
        self.assertNotIn('array(', cell)

    def test_a_histogram_cell_hands_over_the_line_it_writes(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', [HISTOGRAM_AGG])
        cell = self.cells(self.rows(model, lst, source='data')[0])[0]
        self.assertIn(['counts, edges = np.histogram(data, bins=10)'],
                      exps_in(cell))
        self.assertIn('import numpy as np', handles_in(cell)[0][0]['imports'])

    def test_a_histogram_is_a_cell_rather_than_a_row_of_the_list(self):
        # It reads `$` and never `$$`, so it answers about the column rather
        # than picking a row out of the list the way Min Item does.
        self.assertFalse(_agg_is_row(HISTOGRAM_AGG))
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)', HISTOGRAM_AGG])
        rows = self.rows(model, lst)
        self.assertEqual(len(rows), 2)
        self.assertEqual([re.search(r'col-agg-label">([^<]*)<',
                                    row).group(1).strip()
                          for row in rows], ['Mean', 'Histogram'])

    def test_a_computed_column_hands_over_the_column_too(self):
        lst = [{'a': 1}, {'a': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']"]
        _set_column_computes(model, "$['a']", ['max($)'])
        cell = self.cells(self.rows(model, lst, source='data')[0])[0]
        self.assertIn(html.escape("max([item['a'] for item in data])"), cell)

    def test_the_cells_are_not_a_row_of_the_list(self):
        # No row index, and nothing to pick out of it in pick mode.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['max($)'])
        row = self.rows(model, lst)[0]
        self.assertNotIn('pick-region', row)
        self.assertIn('<td class="row-index col-agg-blank"></td>', row)


class TestAggCellHandsTheAnswerOverOnce(unittest.TestCase):
    """The cell is what carries the expression, not the answer inside it.

    An answer whose visualizer wraps itself in a handle -- the generic ones,
    which have no content of their own to hover -- would be given the same
    expression the cell around it already offers. Two handles, one inside the
    other, both saying the same thing: the inner one's tooltip is drawn above
    the answer, which is where the cell's label is, so hovering the answer
    covers up the name of the aggregation being read.

    The answer stays a handle to look at and to drag, though. It keeps the
    grab wrapper and the cell's own handle answers for it, which is what
    hovering it and dragging it find on the way up.
    """

    def cell(self, lst, expr, get_vis=None, source='data'):
        get_vis = get_vis or mock_get_visualizer
        _, model = tally_model(lst)
        _set_column_computes(model, '$', [expr])
        model['_source_expr'] = source
        out = visualize(lst, model, get_vis,
                        lambda code: eval(code, {}, {'data': lst}))
        row = re.search(r'<tr class="col-agg-row">(.*?)</tr>',
                        out[out.index('<tfoot'):], re.DOTALL).group(1)
        return re.search(r'<td class="col-agg-cell[^"]*"[^>]*>(.*?)</td>',
                         row, re.DOTALL).group(1)

    def test_the_answer_does_not_repeat_the_cells_expression(self):
        # MockStringVisualizer self-wraps when it is small, the way the generic
        # visualizer does.
        cell = self.cell(['b', 'a', 'c'], 'min($)')
        self.assertEqual(cell.count(exp_attr('min(data)')), 1)

    def test_the_answer_is_still_a_handle_to_look_at_and_to_drag(self):
        # No expression of its own to say, but the wrapper is what draws the
        # grab cursor and the border, and a drag on it finds the cell's.
        cell = self.cell(['b', 'a', 'c'], 'min($)')
        self.assertIn('<span class="py-exp-grab">', cell)
        self.assertNotIn('draggable="false"', cell.split('col-agg-value')[1])

    def test_the_cell_is_the_one_that_keeps_it(self):
        cell = self.cell(['b', 'a', 'c'], 'min($)')
        self.assertIn(f'<div class="col-agg" {exp_attr("min(data)")} '
                      'draggable="true">', cell)

    def test_the_answer_itself_is_still_drawn(self):
        cell = self.cell(['b', 'a', 'c'], 'min($)')
        self.assertEqual(agg_answers(cell), ['a'])

    def test_the_answer_is_still_handed_its_expression(self):
        # Taking the wrapper off is not the same as keeping the expression from
        # the child: one with handles of its own builds them out of it.
        # MockIntVisualizer echoes what it was given.
        cell = self.cell(COMPUTE_LIST, 'min($)', get_vis=lambda v: _mock_int_vis)
        self.assertIn('child-expr=min(data)', cell)

    def test_a_cell_with_nothing_to_hand_over_still_draws_its_answer(self):
        cell = self.cell(['b', 'a', 'c'], 'min($)', source=None)
        self.assertNotIn('snc-py-exps', cell)
        self.assertEqual(agg_answers(cell), ['a'])


class TestComputeCellChildEvents(unittest.TestCase):
    """An answer is a child like any other, so it takes focus and events -- but
    it is not a row of the list, so its key has to say enough to work the value
    out again when one comes back for it."""

    def setup(self, expr='sorted($)', source=None, get_vis=None):
        get_vis = get_vis or mock_get_visualizer
        lst = list(COMPUTE_LIST)
        _, model = tally_model(lst)
        _set_column_computes(model, '$', [expr])
        if source:
            model['_source_expr'] = source
        out = visualize(lst, model, get_vis,
                        (lambda code: eval(code, {}, {'data': lst}))
                        if source else None)
        keys = [eval(html.unescape(m)) for m in
                re.findall(r'snc-child-key="([^"]*)"',
                           out[out.index('<tfoot'):])]
        return lst, model, keys[0]

    def test_the_first_click_pins_the_answer(self):
        lst, model, key = self.setup()
        new_model, _ = update(make_child_mouse_event(key, 'None'), None,
                              model, lst, mock_get_visualizer)
        self.assertEqual(new_model.get('focused_child'), key)

    def test_the_key_is_enough_to_work_the_answer_out_again(self):
        lst, model, key = self.setup()
        self.assertEqual(
            _table_child_value_getter(key, lst, model), sorted(COMPUTE_LIST))

    def test_the_key_survives_a_column_being_renamed(self):
        # The column part of the key is what the rename walks, the same as a
        # cell's -- so a pinned answer stays pinned.
        lst = [{'a': 1}, {'a': 3}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']"]
        _set_column_computes(model, "$['a']", ['max($)'])
        out = visualize(lst, model, mock_get_visualizer, None)
        key = eval(html.unescape(re.findall(
            r'snc-child-key="([^"]*)"', out[out.index('<tfoot'):])[0]))
        self.assertTrue(key.endswith(f"{CELL_KEY_SEP}$['a']"))

    def test_an_answer_of_a_row_aggregation_is_worked_out_too(self):
        lst = [{'a': 10, 'b': 2}, {'a': 30, 'b': 1}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        _set_column_computes(model, "$['b']", [MIN_ITEM])
        out = visualize(lst, model, mock_get_visualizer, None)
        keys = [eval(html.unescape(m)) for m in re.findall(
            r'snc-child-key="([^"]*)"', out[out.index('<tfoot'):])]
        # One per column of the picked row: its 'a' and its 'b'.
        self.assertEqual([_table_child_value_getter(k, lst, model)
                          for k in keys], [30, 1])

    def test_code_out_of_an_answer_goes_up_rather_than_into_a_column(self):
        # Code out of a cell becomes a column, since a cell's expression is one
        # every row answers. An answer's is one value the aggregation worked
        # out, so a column of it would be the same number n times.
        get_vis = lambda v: _mock_code_vis
        lst, model, key = self.setup(source='data', get_vis=get_vis)
        model['focused_child'] = key
        new_model, commands = update(
            make_child_mouse_event(key, 'None'), None, model, lst, get_vis,
            eval_in_scope=lambda c: eval(c, {}, {'data': lst}))
        self.assertEqual(list(new_model['columns']), ['$'])
        self.assertEqual(commands, [('x', '(sorted(data))')])

    def test_an_answer_binds_the_code_the_same_way_wherever_it_goes(self):
        # There is no row-generic form of an answer to keep a column in, so the
        # expression bound for the editor is the one bound for the code.
        lst, model, key = self.setup(source='data')
        self.assertEqual(_agg_child_expr(key, 'data'), 'sorted(data)')
        self.assertIsNone(_agg_child_expr(key, None))


MIN_ITEM = 'min($$, key=lambda item: $)'
MAX_ITEM = 'max($$, key=lambda item: $)'


class TestComputeItemRowRendering(unittest.TestCase):
    """Min Item and Max Item answer with a row of the list, so they are drawn as
    a whole row of the table -- index cell included -- rather than one cell."""

    # Least by 'b' is the middle row, which is neither least nor greatest by
    # 'a': a cell that read the wrong row would show it.
    LST = [{'a': 10, 'b': 2}, {'a': 30, 'b': 1}, {'a': 20, 'b': 3}]
    LEAST_BY_B = "min(data, key=lambda item: item['b'])"

    def model(self, computes, lst=None, columns=None):
        lst = self.LST if lst is None else lst
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"] if columns is None else columns
        for col, exprs in computes.items():
            _set_column_computes(model, col, exprs)
        return lst, model

    def table(self, model, lst, source=None):
        if source:
            model = dict(model, _source_expr=source)
        return visualize(lst, model, mock_get_visualizer,
                         (lambda code: eval(code, {}, {'data': lst}))
                         if source else None)

    def rows(self, model, lst, **kwargs):
        return re.findall(r'<tr class="col-agg-row[^"]*">(.*?)</tr>',
                          self.table(model, lst, **kwargs), re.DOTALL)

    def item_rows(self, model, lst, **kwargs):
        found = re.findall(
            r'<tr class="col-agg-row col-agg-item-row">(.*?)</tr>',
            self.table(model, lst, **kwargs), re.DOTALL)
        self.assertTrue(found, 'no item row rendered')
        return found

    def values(self, row):
        return agg_answers(row)

    def test_a_row_aggregation_draws_the_whole_row(self):
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst)[0]
        # Index cell plus one cell per column, all of them that row's.
        self.assertIn('<td class="row-index col-agg-cell"', row)
        self.assertEqual(self.values(row), ['30', '1'])

    def test_the_index_cell_reads_the_index(self):
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst)[0]
        index_cell = row[:row.index('</td>')]
        self.assertIn('>1<', index_cell)

    def test_the_index_cell_hands_over_the_index_itself(self):
        # The point of the row: pick the index out of it and use the number.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst, source='data')[0]
        index_cell = row[:row.index('</td>')]
        self.assertIn(html.escape(f'data.index({self.LEAST_BY_B})'), index_cell)
        self.assertIn('draggable="true"', index_cell)

    def test_each_cell_hands_over_its_own_column_of_that_row(self):
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst, source='data')[0]
        self.assertIn(html.escape(f"{self.LEAST_BY_B}['a']"), row)
        self.assertIn(html.escape(f"{self.LEAST_BY_B}['b']"), row)

    def test_no_cell_repeats_the_expression_its_answer_was_handed(self):
        # Same as any other answer: the cell is the handle, so a child that
        # would wrap itself in one has it taken back off. Strings here because
        # the mock string visualizer self-wraps when small.
        lst, model = self.model({"$['b']": [MIN_ITEM]},
                                lst=[{'a': 'x', 'b': 2}, {'a': 'y', 'b': 1}])
        row = self.item_rows(model, lst, source='data')[0]
        self.assertIn('<span class="py-exp-grab">', row)
        self.assertEqual(row.count(exp_attr(f"{self.LEAST_BY_B}['a']")), 1)

    def test_the_row_costs_no_imports(self):
        # min and max are builtins, so nothing has to be added to the file.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst, source='data')[0]
        self.assertEqual([handle[0].get('imports') for handle in handles_in(row)],
                         [None] * len(handles_in(row)))

    def test_only_the_column_that_asked_is_labelled(self):
        # The other cells are that row's values, not minima of their own.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst)[0]
        # The index cell and the column that didn't ask keep an empty label for
        # spacing, so the one with anything in it is the one that asked.
        self.assertEqual(re.findall(r'col-agg-label">([^<]*)<', row),
                         ['', '', 'Min Item'])
        labelled = row[row.index('Min Item'):]
        self.assertIn('>1<', labelled)

    def test_only_the_labelled_cell_offers_the_x(self):
        # The other cells are that row's values, so there is no aggregation of
        # theirs for an ✕ to take away.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        self.assertEqual(agg_x_events(self.item_rows(model, lst)[0]),
                         [ComputeToggle(col=col_at(model, 1), expr=MIN_ITEM)])

    def test_min_item_and_max_item_are_a_row_each(self):
        lst, model = self.model({"$['b']": [MIN_ITEM, MAX_ITEM]})
        rows = self.item_rows(model, lst)
        self.assertEqual(len(rows), 2)
        self.assertEqual([self.values(row) for row in rows],
                         [['30', '1'], ['20', '3']])

    def test_a_row_aggregation_sits_under_the_cells(self):
        lst, model = self.model({"$['a']": ['min($)'], "$['b']": [MIN_ITEM]})
        rows = self.rows(model, lst)
        self.assertEqual(len(rows), 2)
        self.assertIn('>Min<', rows[0])
        self.assertIn('>Min Item<', rows[1])

    def test_it_goes_in_the_same_foot_the_cells_do(self):
        # One block that pins itself, so a row of the list is free to be
        # whatever height it is.
        lst, model = self.model({"$['a']": ['min($)'], "$['b']": [MIN_ITEM]})
        foot = re.search(r'<tfoot class="col-agg-rows">(.*?)</tfoot>',
                         self.table(model, lst), re.DOTALL).group(1)
        self.assertEqual(foot.count('<tr class="col-agg-row'), 2)
        self.assertIn('col-agg-item-row', foot)
        for row in self.rows(model, lst):
            self.assertNotIn('style=', row)

    def test_a_column_that_cannot_pick_a_row_still_keeps_its_row(self):
        # There is no least row of no rows; the row says nothing rather than
        # disappearing and taking the table's layout with it.
        lst, model = self.model({'$': [MIN_ITEM]}, lst=[], columns=['$'])
        row = self.item_rows(model, lst)[0]
        self.assertEqual(self.values(row), [''])
        self.assertIn('>Min Item<', row)
        self.assertNotIn('snc-py-exps', row)

    def test_a_list_with_no_source_hands_over_nothing(self):
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        self.assertNotIn('snc-py-exps', self.item_rows(model, lst)[0])

    def test_the_item_column_hands_over_the_row_itself(self):
        lst, model = self.model({'$': [MIN_ITEM]}, lst=[3, 1, 4],
                                columns=['$'])
        row = self.item_rows(model, lst, source='data')[0]
        self.assertIn(html.escape('min(data, key=lambda item: item)'), row)
        self.assertEqual(self.values(row), ['1'])

    def test_a_row_aggregation_is_not_a_row_of_the_list(self):
        # It reads like one, but there is nothing in it to pick.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        self.assertNotIn('pick-region', self.item_rows(model, lst)[0])

    def test_the_label_hands_over_the_row_itself(self):
        # The row's own name is the one place the whole row is offered: the
        # cells under it each hand over a column of it, and the index cell the
        # number beside it. Only a `$` column would otherwise hand over the row.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst, source='data')[0]
        label = re.search(r'<div class="col-agg-label col-agg-item-label"([^>]*)>',
                          row).group(1)
        self.assertIn(exp_attr(self.LEAST_BY_B), label)
        self.assertIn('draggable="true"', label)

    def test_the_label_hands_over_nothing_with_no_row_to_point_at(self):
        lst, model = self.model({'$': [MIN_ITEM]}, lst=[], columns=['$'])
        row = self.item_rows(model, lst, source='data')[0]
        self.assertNotIn('snc-py-exps', row)

    def test_every_cell_of_the_row_is_a_child_like_any_other(self):
        # The values are the row's, so each is drawn by whichever visualizer
        # reads it -- but the index beside them is the table's own, and reads
        # like the index cells above it.
        lst, model = self.model({"$['b']": [MIN_ITEM]})
        row = self.item_rows(model, lst)[0]
        keys = re.findall(r'snc-child-key="([^"]*)"', row)
        self.assertEqual(len(set(keys)), 2)  # one per column, not the index
        index_cell = row[:row.index('</td>')]
        self.assertNotIn('snc-child-key', index_cell)


from table_visualizer import (
    COMPUTE_CODES, TALLY_IMPORTS,
    ComputeCodeClick, ComputeExprInput, ComputeExprKeyDown,
    _agg_is_free, _compute_free_rows, _compute_scope,
)


class TestComputeCodeCatalog(unittest.TestCase):
    """Unique and Tally answer with a whole list rather than a number, so they
    go in the file instead of into a cell under the column."""

    def test_the_catalog_reads_the_way_the_todo_lists_it(self):
        self.assertEqual([label for label, _, _ in COMPUTE_CODES],
                         ['Unique', 'Tally'])

    def test_they_are_written_with_the_same_dollar_every_aggregation_is(self):
        self.assertEqual([template for _, template, _ in COMPUTE_CODES],
                         ['set($)', 'Counter($)'])

    def test_the_column_goes_in_where_the_dollar_is(self):
        self.assertEqual(_agg_code('set($)', 'data'), 'set(data)')
        self.assertEqual(_agg_code('Counter($)', "[item['a'] for item in data]"),
                         "Counter([item['a'] for item in data])")

    def test_counter_says_which_import_it_needs(self):
        self.assertEqual(_agg_imports('Counter($)'), TALLY_IMPORTS)

    def test_a_builtin_needs_nothing(self):
        self.assertEqual(_agg_imports('set($)'), ())


class ComputePanelCase(unittest.TestCase):
    """The Compute submenu, opened over a one-column table."""

    def panel(self, model, lst, column=0, source=None):
        model = dict(model, openDropdown={'id': menu_id(model, index=column)},
                     col_search_dropdown=menu_id(model, 'compute', column))
        if source:
            model['_source_expr'] = source
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      (lambda code: eval(code, {}, {'data': lst}))
                      if source else None))
        self.assertIn('col-compute-panel', th)
        return th[th.index('col-compute-panel'):]

    def previews(self, panel):
        return re.findall(r'col-compute-preview"[^>]*>([^<]*)<', panel)


class TestComputeCodeRendering(ComputePanelCase):
    """The code rows sit under the aggregations: a name and nothing else, since
    there is no cell for them to preview."""

    def code_rows(self, panel):
        return re.findall(r'<div class="col-compute-row col-compute-code[^"]*".'
                          r'*?(?=<div class="col-compute-row|$)', panel,
                          re.DOTALL)

    def test_both_are_listed_after_the_aggregations(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst)
        names = re.findall(r'col-compute-name">([^<]*)<', panel)
        self.assertEqual(names[-2:], ['Unique', 'Tally'])

    def test_a_code_row_has_neither_a_checkbox_nor_a_preview(self):
        # Nothing to check -- it writes a line rather than keeping an answer on
        # screen -- and nothing to preview, since a whole list wouldn't fit.
        lst, model = tally_model(COMPUTE_LIST)
        for row in self.code_rows(self.panel(model, lst)):
            self.assertNotIn('col-tally-check', row)
            self.assertNotIn('col-compute-preview', row)

    def test_a_code_row_hands_over_the_line_it_would_write(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst, source='data')
        self.assertIn(['set(data)'], exps_in(panel))
        self.assertIn(['Counter(data)'], exps_in(panel))

    def test_the_tally_row_says_it_needs_counter(self):
        lst, model = tally_model(COMPUTE_LIST)
        panel = self.panel(model, lst, source='data')
        declared = {handle[0]['expr']: handle[0].get('imports')
                    for handle in handles_in(panel)}
        self.assertEqual(declared['Counter(data)'], list(TALLY_IMPORTS))

    def test_with_no_source_there_is_no_line_to_write(self):
        lst, model = tally_model(COMPUTE_LIST)
        for row in self.code_rows(self.panel(model, lst)):
            self.assertIn('unselectable', row)
            self.assertNotIn('snc-mouse-down', row)


class TestComputeCodeEvents(unittest.TestCase):
    """Clicking a code row writes the line, the way an action button does."""

    def click(self, lst, expr, index=0, source='data', columns=None, col=None):
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['$'] if columns is None else columns
        model['_source_expr'] = source
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'compute')
        return update(make_column_mouse_event(
            repr(ComputeCodeClick(col=col_at(model, index) if col is None else col,
                                  expr=expr))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=(lambda code: eval(code, {}, {'data': lst})))

    def test_unique_writes_the_set_of_the_column(self):
        _, commands = self.click(COMPUTE_LIST, 'set($)')
        self.assertEqual(commands[0][:2], ('data_unique', 'set(data)'))

    def test_tally_writes_the_counter_and_says_it_needs_the_import(self):
        _, commands = self.click(COMPUTE_LIST, 'Counter($)')
        self.assertEqual(commands[0],
                         ('data_tally', 'Counter(data)', TALLY_IMPORTS))

    def test_a_computed_column_goes_in_as_the_column(self):
        lst = [{'a': 1}, {'a': 3}]
        _, commands = self.click(lst, 'set($)', columns=["$['a']"])
        self.assertEqual(commands[0][1], "set([item['a'] for item in data])")

    def test_the_name_falls_back_when_the_list_has_no_name(self):
        _, commands = self.click(COMPUTE_LIST, 'set($)', source='data[0]')
        self.assertEqual(commands[0][0], 'result_unique')

    def test_the_menu_closes_behind_it(self):
        # One line written, unlike checking a box, which invites the next.
        model, _ = self.click(COMPUTE_LIST, 'set($)')
        self.assertIsNone(model['openDropdown'])
        self.assertIsNone(model['col_search_dropdown'])

    def test_a_list_with_no_source_writes_nothing(self):
        _, commands = self.click(COMPUTE_LIST, 'set($)', source=None)
        self.assertEqual(commands, [])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        _, commands = self.click(COMPUTE_LIST, 'set($)', col='$.gone')
        self.assertEqual(commands, [])


class TestFreeAggregations(unittest.TestCase):
    """An aggregation the user writes themselves is simply an expression the
    catalog has no row for, so nothing marks it as theirs."""

    def test_an_expression_the_catalog_does_not_know_is_the_users_own(self):
        self.assertTrue(_agg_is_free('sorted($)[2]'))

    def test_a_catalog_expression_is_not(self):
        self.assertFalse(_agg_is_free('min($)'))
        self.assertFalse(_agg_is_free('np.percentile($, {{25}})'))

    def test_an_empty_box_is_nobodys_expression_yet(self):
        self.assertTrue(_agg_is_free(''))

    def test_it_has_no_name_but_the_code_it_is(self):
        self.assertIsNone(_agg_name('sorted($)[2]'))

    def test_it_answers_like_any_other_aggregation(self):
        self.assertEqual(_agg_value('sorted($)[2]', COMPUTE_LIST), 3)

    def test_it_hands_over_the_same_code_it_computed(self):
        self.assertEqual(_agg_code('sorted($)[2]', 'data'), 'sorted(data)[2]')

    def test_the_rows_are_the_users_own_and_an_empty_one_after_them(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'sorted($)[2]'])
        self.assertEqual(_compute_free_rows(model, '$'), ['sorted($)[2]', ''])

    def test_a_column_with_none_still_offers_a_box_to_write_one_in(self):
        _, model = tally_model(COMPUTE_LIST)
        self.assertEqual(_compute_free_rows(model, '$'), [''])

    def test_they_stack_under_the_catalogs_own(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]', 'min($)'])
        self.assertEqual(_column_computes(model, '$'),
                         ['min($)', 'sorted($)[2]'])

    def test_an_empty_one_is_not_an_aggregation(self):
        _, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['   '])
        self.assertIsNone(model['column_computes'])


def make_compute_expr_event(col, expr, value):
    """Create a ComputeExprInput event for a free-form aggregation's box."""
    return {
        'pythonEventStr': (f"lambda e: ComputeExprInput(col={col!r}, "
                           f"expr={expr!r}, value=e.get('value', ''))"),
        'eventJSON': {'type': 'input', 'value': value},
    }


class TestFreeAggregationEvents(unittest.TestCase):
    """The box is the aggregation: what is typed in it is the expression."""

    def input(self, model, lst, expr, value, col=None):
        col = col_at(model) if col is None else col
        model, _ = update(make_compute_expr_event(col, expr, value), None,
                          model, lst, mock_get_visualizer, eval_in_scope=eval)
        return model

    def test_typing_in_the_empty_box_adds_the_aggregation(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, '', 'sorted($)[2]')
        self.assertEqual(_column_computes(model, '$'), ['sorted($)[2]'])

    def test_typing_in_one_already_there_rewrites_it_in_place(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        model = self.input(model, lst, 'sorted($)[2]', 'sorted($)[1]')
        self.assertEqual(_column_computes(model, '$'), ['sorted($)[1]'])

    def test_emptying_the_box_takes_the_aggregation_away(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        model = self.input(model, lst, 'sorted($)[2]', '')
        self.assertIsNone(model['column_computes'])

    def test_an_empty_box_left_empty_adds_nothing(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, '', '  ')
        self.assertIsNone(model['column_computes'])

    def test_a_half_typed_expression_is_kept_so_the_box_keeps_its_place(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, '', 'sorted(')
        self.assertEqual(_column_computes(model, '$'), ['sorted('])

    def test_the_menu_stays_open_while_it_is_typed(self):
        lst, model = tally_model(COMPUTE_LIST)
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'compute')
        model = self.input(model, lst, '', 'sorted($)[2]')
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'compute'))

    def test_typing_at_a_column_that_is_gone_is_a_noop(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, '', 'sorted($)[2]', col='$.gone')
        self.assertIsNone(model['column_computes'])

    def test_writing_the_catalogs_own_expression_checks_its_row(self):
        # It is Min, whoever typed it.
        lst, model = tally_model(COMPUTE_LIST)
        model = self.input(model, lst, '', 'min($)')
        self.assertEqual(_column_computes(model, '$'), ['min($)'])
        self.assertEqual(_compute_free_rows(model, '$'), [''])


class TestFreeAggregationRendering(ComputePanelCase):
    """A free-form row is a box holding the expression, previewing its answer
    the way every other row does."""

    def boxes(self, panel):
        return re.findall(r'col-compute-expr[^>]*value="([^"]*)"', panel)

    def test_the_menu_ends_with_an_empty_box(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertEqual(self.boxes(self.panel(model, lst)), [''])

    def test_each_of_the_users_own_gets_a_box_and_an_empty_one_follows(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]', 'sum($) / 2'])
        self.assertEqual(self.boxes(self.panel(model, lst)),
                         [html.escape('sorted($)[2]'), html.escape('sum($) / 2'),
                          ''])

    def test_a_free_row_previews_its_answer(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        # The last preview belongs to the empty box that follows it.
        self.assertEqual(self.previews(self.panel(model, lst))[-2:], ['3', ''])

    def test_a_free_row_hands_over_its_code(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        self.assertIn(exp_attr('sorted(data)[2]'),
                      self.panel(model, lst, source='data'))

    def test_the_empty_row_says_what_it_is_for(self):
        lst, model = tally_model(COMPUTE_LIST)
        self.assertIn('placeholder="Add aggregation"', self.panel(model, lst))

    def test_the_box_says_what_the_dollars_mean(self):
        # The same thing the column search box says of its own.
        lst, model = tally_model(COMPUTE_LIST)
        self.assertIn(f'data-tooltip="{html.escape(_compute_scope().legend)}"',
                      self.panel(model, lst))

    def free_rows(self, panel):
        return re.findall(r'<div class="col-compute-row col-compute-free[^"]*">'
                          r'.*?col-compute-preview.*?</span></div>', panel,
                          re.DOTALL)

    def test_an_aggregation_of_theirs_is_checked_and_can_be_unchecked(self):
        # Unchecking is how one is taken away: the expression is the only record
        # that it is there at all.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        row = self.free_rows(self.panel(model, lst))[0]
        self.assertIn('checked', row)
        self.assertIn(
            html.escape(f"ComputeToggle(col={col_at(model)!r}, "
                        f"expr='sorted($)[2]', per_group=False)"),
            row)

    def test_the_empty_row_has_nothing_to_uncheck(self):
        lst, model = tally_model(COMPUTE_LIST)
        row = self.free_rows(self.panel(model, lst))[-1]
        self.assertIn('disabled', row)
        self.assertNotIn('snc-mouse-down', row)

    def test_the_box_takes_its_own_enter_and_escape(self):
        lst, model = tally_model(COMPUTE_LIST)
        row = self.free_rows(self.panel(model, lst))[-1]
        self.assertIn(f'snc-key-down="{html.escape(repr(ComputeExprKeyDown()))}"',
                      row)


class TestFreeAggregationCell(unittest.TestCase):
    """The cell a free-form aggregation makes is labelled with a box holding the
    expression -- there is no name for it but itself, so the place it reads is
    the place to edit it."""

    def rows(self, model, lst, source=None):
        if source:
            model = dict(model, _source_expr=source)
        out = visualize(lst, model, mock_get_visualizer,
                        (lambda code: eval(code, {}, {'data': lst}))
                        if source else None)
        self.assertIn('col-agg-row', out)
        return re.findall(r'<tr class="col-agg-row">(.*?)</tr>',
                          out[out.index('<tr class="col-agg-row">'):],
                          re.DOTALL)

    def cells(self, row):
        # The cell carries classes past the first one (it is the hover parent
        # its ✕ hides behind), so the class list is read open-endedly.
        return re.findall(r'<td class="col-agg-cell[^"]*"[^>]*>(.*?)</td>', row,
                          re.DOTALL)

    def test_the_label_is_a_box_holding_the_expression(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('class="col-agg-label col-agg-expr"', cell)
        self.assertIn(f'value="{html.escape("sorted($)[2]")}"', cell)

    def test_the_box_edits_the_aggregation_it_labels(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn(html.escape("ComputeExprInput(col='$'"), cell)
        self.assertIn(html.escape("expr='sorted($)[2]'"), cell)

    def test_a_named_aggregation_keeps_its_name(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['np.mean($)'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn('<div class="col-agg-label">Mean</div>', cell)
        self.assertNotIn('col-agg-expr', cell)

    def test_the_cell_still_shows_and_hands_over_its_answer(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        cell = self.cells(self.rows(model, lst, source='data')[0])[0]
        self.assertEqual(agg_answers(cell), ['3'])
        self.assertIn(exp_attr('sorted(data)[2]'), cell)

    def test_the_box_says_what_the_dollars_mean_here_too(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        cell = self.cells(self.rows(model, lst)[0])[0]
        self.assertIn(f'data-tooltip="{html.escape(_compute_scope().legend)}"',
                      cell)


class TestAggregationCellHoles(unittest.TestCase):
    """A cell whose aggregation has a box in it -- a percentile's level, a
    histogram's bin count -- carries that box in its own label, the way a
    free-form one carries the whole expression: the place the number reads is
    the place to edit it."""

    def rows(self, model, lst, source=None):
        if source:
            model = dict(model, _source_expr=source)
        out = visualize(lst, model, mock_get_visualizer,
                        (lambda code: eval(code, {}, {'data': lst}))
                        if source else None)
        self.assertIn('col-agg-row', out)
        return re.findall(r'<tr class="col-agg-row">(.*?)</tr>',
                          out[out.index('<tr class="col-agg-row">'):],
                          re.DOTALL)

    def cells(self, row):
        return re.findall(r'<td class="col-agg-cell[^"]*"[^>]*>(.*?)</td>', row,
                          re.DOTALL)

    def cell(self, computes, lst=None, col='$', **kwargs):
        lst, model = tally_model(COMPUTE_LIST if lst is None else lst)
        _set_column_computes(model, col, computes)
        return self.cells(self.rows(model, lst, **kwargs)[0])[0]

    def boxes(self, cell):
        """What each of the cell's boxes reads, in the order they are drawn."""
        return re.findall(r'col-agg-hole[^>]*value="([^"]*)"', cell)

    def test_the_level_is_a_box_the_cell_carries(self):
        cell = self.cell([P10])
        self.assertIn('class="col-agg-label"', cell)
        self.assertIn('Percentile', cell)
        self.assertEqual(self.boxes(cell), ['10'])

    def test_an_edited_level_is_what_the_box_reads(self):
        self.assertEqual(self.boxes(self.cell(['np.percentile($, {{25}})'])),
                         ['25'])

    def test_the_box_edits_the_aggregation_it_labels(self):
        cell = self.cell([P10])
        self.assertIn(html.escape("ComputeHoleInput(col='$'"), cell)
        self.assertIn(html.escape(f'expr={P10!r}'), cell)
        self.assertIn(html.escape('hole=0'), cell)

    def test_typing_in_it_rewrites_the_cell_in_place(self):
        # Through the event the cell really offers, so a number typed at the
        # table asks what a number typed in the submenu asks.
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', P10, 'max($)'])
        cell = self.cells(self.rows(model, lst)[1])[0]
        event = html.unescape(
            re.search(r'col-agg-hole[^>]*snc-input="([^"]*)"', cell).group(1))
        model, _ = update({'pythonEventStr': event,
                           'eventJSON': {'type': 'input', 'value': '25'}},
                          None, model, lst, mock_get_visualizer,
                          eval_in_scope=eval)
        self.assertEqual(_column_computes(model, '$'),
                         ['min($)', 'np.percentile($, {{25}})', 'max($)'])

    def test_the_cell_still_shows_and_hands_over_its_answer(self):
        cell = self.cell([P10], source='data')
        self.assertEqual(agg_answers(cell), ['1.0'])
        self.assertIn(html.escape('np.percentile(data, 10)'), cell)

    def test_an_aggregation_with_no_box_is_the_name_alone(self):
        cell = self.cell(['np.mean($)'])
        self.assertIn('<div class="col-agg-label">Mean</div>', cell)
        self.assertNotIn('col-agg-hole', cell)

    def test_the_histogram_cell_carries_its_bin_count_too(self):
        # A histogram's box is the percentile's under another name.
        cell = self.cell([HISTOGRAM_AGG])
        self.assertIn('Histogram', cell)
        self.assertEqual(self.boxes(cell), ['10'])

    def box_html(self, cell):
        return re.search(r'<input[^>]*col-agg-hole[^>]*>', cell).group(0)

    def test_the_bins_box_says_what_the_number_in_it_counts(self):
        # The same thing it says in the submenu; a percentile's box reads off
        # the name beside it, so only this one has anything to add.
        self.assertIn(f'data-tooltip="{HISTOGRAM_BINS_TOOLTIP}"',
                      self.box_html(self.cell([HISTOGRAM_AGG])))
        self.assertNotIn('data-tooltip', self.box_html(self.cell([P10])))

    def test_the_box_names_itself_by_where_it_sits(self):
        # Typing in it rewrites what it says, so a box found again by what it
        # says would lose the typing to it -- and no two boxes may share a name.
        lst = [{'a': 1, 'b': 2}, {'a': 3, 'b': 4}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['a']", "$['b']"]
        _set_column_computes(model, "$['a']", [P10, P90])
        _set_column_computes(model, "$['b']", [P10])
        keys = re.findall(r'col-agg-hole[^>]*snc-focus-key="([^"]*)"',
                          ''.join(self.rows(model, lst)))
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)

    def test_the_box_is_not_a_drag_handle(self):
        # The cell around it is one, and a drag begun inside the box would take
        # the selection the user was making with it.
        self.assertIn('draggable="false"', self.box_html(self.cell([P10])))

    def test_the_cell_can_still_be_taken_away(self):
        self.assertEqual(agg_x_events(self.cell([P10])),
                         [ComputeToggle(col='$', expr=P10)])


def make_compute_expr_key_event(key):
    """Create a ComputeExprKeyDown event for a free-form aggregation's box."""
    return {
        'pythonEventStr': repr(ComputeExprKeyDown()),
        'eventJSON': {
            'type': 'keydown',
            'key': key,
            'metaKey': False,
            'shiftKey': False,
            'ctrlKey': False,
            'altKey': False,
        },
    }


class TestFreeAggregationKeys(unittest.TestCase):
    """Enter in the box says the aggregation is written: the cell is already
    there, and the menu has nothing more to say about it."""

    def open_menu(self, lst=None):
        lst, model = tally_model(COMPUTE_LIST if lst is None else lst)
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = menu_id(model, 'compute')
        _set_column_computes(model, '$', ['sorted($)[2]'])
        return lst, model

    def press(self, model, lst, key):
        return update(make_compute_expr_key_event(key), ('data', 'data'), model,
                      lst, mock_get_visualizer, eval_in_scope=eval)

    def test_enter_closes_the_column_menu(self):
        lst, model = self.open_menu()
        model, _ = self.press(model, lst, 'Enter')
        self.assertIsNone(model['openDropdown'])
        self.assertIsNone(model['col_search_dropdown'])

    def test_enter_leaves_the_aggregation_alone(self):
        lst, model = self.open_menu()
        model, commands = self.press(model, lst, 'Enter')
        self.assertEqual(_column_computes(model, '$'), ['sorted($)[2]'])
        # And writes no line: Enter over a search is what does that.
        self.assertEqual(commands, [])

    def test_escape_closes_only_the_submenu(self):
        # Innermost first, the way Escape reads everywhere else in the menu.
        lst, model = self.open_menu()
        model, _ = self.press(model, lst, 'Escape')
        self.assertIsNone(model['col_search_dropdown'])
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})

    def test_any_other_key_is_just_typing(self):
        lst, model = self.open_menu()
        model, _ = self.press(model, lst, 'a')
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'compute'))


class TestFreeAggregationRemoval(unittest.TestCase):
    """Unchecking a free-form row takes the aggregation away -- the expression
    is the only record that it was there, so there is nothing left to keep."""

    def toggle(self, model, lst, expr, index=0):
        col = col_at(model, index)
        model, _ = update(make_column_mouse_event(
            repr(ComputeToggle(col=col, expr=expr))), None, model, lst,
            mock_get_visualizer, eval_in_scope=eval)
        return model

    def test_unchecking_one_removes_it(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['sorted($)[2]'])
        model = self.toggle(model, lst, 'sorted($)[2]')
        self.assertIsNone(model['column_computes'])

    def test_the_others_stay_where_they_were(self):
        lst, model = tally_model(COMPUTE_LIST)
        _set_column_computes(model, '$', ['min($)', 'sorted($)[2]',
                                          'sum($) / 2'])
        model = self.toggle(model, lst, 'sorted($)[2]')
        self.assertEqual(_column_computes(model, '$'), ['min($)', 'sum($) / 2'])

    def test_the_empty_row_has_nothing_to_toggle(self):
        lst, model = tally_model(COMPUTE_LIST)
        model = self.toggle(model, lst, '')
        self.assertIsNone(model['column_computes'])


from table_visualizer import (
    _parse_sorted, _sort_expr, _sort_checked, canonical_source_expr,
)


class TestParseSorted(unittest.TestCase):
    """A sort is read back out of the line rather than remembered, so reading
    one has to answer for every shape the menu can write."""

    def test_a_bare_sort_has_no_key_and_no_reverse(self):
        self.assertEqual(_parse_sorted('sorted(data)'), ('data', None, False))

    def test_reverse_is_the_descending_one(self):
        self.assertEqual(_parse_sorted('sorted(data, reverse=True)'),
                         ('data', None, True))

    def test_a_key_comes_back_as_the_body_of_its_lambda(self):
        self.assertEqual(
            _parse_sorted("sorted(data, key=lambda item: item['b'])"),
            ('data', "item['b']", False))

    def test_a_key_and_reverse_together(self):
        self.assertEqual(
            _parse_sorted(
                "sorted(data, key=lambda item: item['b'], reverse=True)"),
            ('data', "item['b']", True))

    def test_the_inner_expression_comes_back_as_it_was_written(self):
        # Written back verbatim on an unsort, so it has to be the user's own
        # text rather than an unparse of it.
        self.assertEqual(_parse_sorted('sorted(json.load( f ))')[0],
                         'json.load( f )')

    def test_something_that_is_not_a_sort_is_not_one(self):
        self.assertIsNone(_parse_sorted('data'))
        self.assertIsNone(_parse_sorted('[item for item in data]'))
        self.assertIsNone(_parse_sorted('sorted'))

    def test_a_sort_of_nothing_in_particular_is_not_one(self):
        self.assertIsNone(_parse_sorted('sorted()'))
        self.assertIsNone(_parse_sorted('sorted(a, b)'))

    def test_a_keyword_it_does_not_speak_is_not_one(self):
        self.assertIsNone(_parse_sorted('sorted(data, key=len, x=1)'))
        self.assertIsNone(_parse_sorted('sorted(data, **kw)'))

    def test_a_hand_written_key_still_reads_as_a_sort(self):
        # So clicking a direction replaces it rather than nesting inside it.
        # It comes back as written rather than as no key at all, so it can't be
        # mistaken for the sort that orders on the row itself.
        self.assertEqual(_parse_sorted('sorted(data, key=len)'),
                         ('data', 'len', False))

    def test_a_key_that_is_not_a_lambda_of_item_comes_back_as_written(self):
        self.assertEqual(_parse_sorted('sorted(data, key=lambda x: x.n)')[1],
                         'lambda x: x.n')

    def test_syntax_that_is_not_python_is_not_a_sort(self):
        self.assertIsNone(_parse_sorted('sorted(data'))
        self.assertIsNone(_parse_sorted(''))


class TestDictSort(unittest.TestCase):
    """A shape change, not a key= fix: sorted(d, key=...) returns a list of
    KEYS whatever the key function is, so appending a correct key= would turn
    the user's dict table into a list of keys the moment they click Sort."""

    @staticmethod
    def binds():
        return _binds_for({'a': 1})

    def test_the_row_itself_sorts_the_items_and_stays_a_dict(self):
        self.assertEqual(_sort_expr('d', '$', 'asc', self.binds()),
                         'dict(sorted(d.items(), key=lambda item: item))')

    def test_a_column_keys_through_the_pair(self):
        # The lambda parameter stays named `item` -- that is the name
        # _parse_sorted recognises -- and tuple-unpacking parameters are
        # illegal in Python 3, so item[1] is the only spelling available.
        self.assertEqual(_sort_expr('d', "$v['age']", 'desc', self.binds()),
                         "dict(sorted(d.items(), key=lambda item: item[1]['age'],"
                         " reverse=True))")

    def test_sorting_by_the_key(self):
        self.assertEqual(_sort_expr('d', '$k', 'asc', self.binds()),
                         'dict(sorted(d.items(), key=lambda item: item[0]))')

    def test_an_existing_dict_sort_is_replaced_rather_than_nested(self):
        was = 'dict(sorted(d.items(), key=lambda item: item[0]))'
        self.assertEqual(_sort_expr(was, '$v', 'asc', self.binds()),
                         'dict(sorted(d.items(), key=lambda item: item[1]))')

    def test_unsorting_hands_back_the_container_the_line_names(self):
        was = 'dict(sorted(d.items(), key=lambda item: item[0]))'
        self.assertEqual(_sort_expr(was, '$k', None, self.binds()), 'd')

    def test_parse_sorted_unwraps_the_dict_transparently(self):
        # Same (inner, key, reverse) triple as a list sort, with the trailing
        # .items() taken off the inner too -- so `inner` is the container the
        # line names, and no caller grows a fourth element.
        self.assertEqual(
            _parse_sorted('dict(sorted(d.items(), key=lambda item: item[1]))'),
            ('d', 'item[1]', False))

    def test_the_direction_checkmark_round_trips(self):
        for direction in ('asc', 'desc'):
            with self.subTest(direction=direction):
                line = _sort_expr('d', "$v['age']", direction, self.binds())
                self.assertTrue(
                    _sort_checked(line, "$v['age']", direction, self.binds()))
                other = 'desc' if direction == 'asc' else 'asc'
                self.assertFalse(
                    _sort_checked(line, "$v['age']", other, self.binds()))

    def test_canonical_source_expr_sees_through_a_dict_sort(self):
        # If it didn't, every sort of a dict would read as a NEW source
        # expression and throw away the user's searches, aggregations and child
        # models -- exactly what this function exists to prevent.
        self.assertEqual(
            canonical_source_expr(
                'dict(sorted(d.items(), key=lambda item: item[1]))'),
            'd')


class TestSortExpr(unittest.TestCase):
    """What the menu writes. sorted() returns a new list in both directions,
    so there is nothing to wrap it in."""

    def test_the_row_itself_sorts_without_a_key(self):
        self.assertEqual(_sort_expr('data', '$', 'asc'), 'sorted(data)')

    def test_descending_the_row_itself(self):
        self.assertEqual(_sort_expr('data', '$', 'desc'),
                         'sorted(data, reverse=True)')

    def test_a_column_becomes_the_key(self):
        self.assertEqual(_sort_expr('data', "$['b']", 'asc'),
                         "sorted(data, key=lambda item: item['b'])")

    def test_a_column_descending(self):
        self.assertEqual(_sort_expr('data', "$['b']", 'desc'),
                         "sorted(data, key=lambda item: item['b'], reverse=True)")

    def test_an_existing_sort_is_replaced_rather_than_nested(self):
        was = "sorted(data, key=lambda item: item['b'])"
        self.assertEqual(_sort_expr(was, "$['c']", 'desc'),
                         "sorted(data, key=lambda item: item['c'], reverse=True)")

    def test_unsorting_hands_back_the_expression_that_was_wrapped(self):
        was = "sorted(json.load(f), key=lambda item: item['b'])"
        self.assertEqual(_sort_expr(was, "$['b']", None), 'json.load(f)')

    def test_a_computed_column_reads_the_row_through_its_expression(self):
        self.assertEqual(_sort_expr('data', 'len($)', 'asc'),
                         'sorted(data, key=lambda item: len(item))')


class TestSortChecked(unittest.TestCase):
    """Which box is ticked is the line's answer, not the model's."""

    def test_the_direction_the_line_sorts_in_is_the_checked_one(self):
        was = "sorted(data, key=lambda item: item['b'])"
        self.assertTrue(_sort_checked(was, "$['b']", 'asc'))
        self.assertFalse(_sort_checked(was, "$['b']", 'desc'))

    def test_descending(self):
        was = "sorted(data, key=lambda item: item['b'], reverse=True)"
        self.assertTrue(_sort_checked(was, "$['b']", 'desc'))
        self.assertFalse(_sort_checked(was, "$['b']", 'asc'))

    def test_another_column_is_not_this_columns_sort(self):
        was = "sorted(data, key=lambda item: item['b'])"
        self.assertFalse(_sort_checked(was, "$['c']", 'asc'))

    def test_the_row_itself_is_the_sort_with_no_key(self):
        self.assertTrue(_sort_checked('sorted(data)', '$', 'asc'))
        self.assertFalse(_sort_checked('sorted(data)', "$['b']", 'asc'))

    def test_a_keyed_sort_is_not_the_row_itselfs(self):
        was = "sorted(data, key=lambda item: item['b'])"
        self.assertFalse(_sort_checked(was, '$', 'asc'))

    def test_an_unsorted_line_checks_nothing(self):
        self.assertFalse(_sort_checked('data', '$', 'asc'))
        self.assertFalse(_sort_checked('data', '$', 'desc'))

    def test_a_hand_written_key_checks_nothing(self):
        self.assertFalse(_sort_checked('sorted(data, key=len)', '$', 'asc'))

    def test_nothing_to_read_checks_nothing(self):
        self.assertFalse(_sort_checked(None, '$', 'asc'))


class TestCanonicalSourceExpr(unittest.TestCase):
    """A sort wrapper is the one part of the expression that is not a change of
    source, so a model survives one being put on or taken off."""

    def test_a_sort_signs_as_the_thing_it_sorts(self):
        self.assertEqual(canonical_source_expr('sorted([3, 1, 2])'), '[3, 1, 2]')
        self.assertEqual(
            canonical_source_expr(
                "sorted([3, 1, 2], key=lambda item: item['b'], reverse=True)"),
            '[3, 1, 2]')

    def test_an_unsorted_expression_signs_as_itself(self):
        self.assertEqual(canonical_source_expr('[3, 1, 2]'), '[3, 1, 2]')

    def test_a_rename_is_still_a_different_source(self):
        self.assertNotEqual(canonical_source_expr('sorted(x)'),
                            canonical_source_expr('sorted(y)'))

    def test_nothing_signs_as_nothing(self):
        self.assertIsNone(canonical_source_expr(None))


from table_visualizer import ChangeSourceExpr, SortClick, SortCodeClick

SORT_LIST = [{'b': 3}, {'b': 1}, {'b': 2}]

# (text, start_line, start_col, end_line, end_col) -- what the runner hands the
# visualizer for the expression its own line is showing.
SPAN = ('json.load(f)', 4, 7, 4, 19)


def sort_model(lst=None, columns=None, span=SPAN, source='data'):
    """A table model with a column menu and its Sort submenu open."""
    lst = SORT_LIST if lst is None else lst
    model = init_model(lst, mock_get_visualizer)
    model['columns'] = ["$['b']"] if columns is None else columns
    model['_source_expr'] = source
    model['_source_span'] = span
    model['openDropdown'] = {'id': menu_id(model)}
    model['col_search_dropdown'] = menu_id(model, 'sort')
    return lst, model


class SortPanelCase(unittest.TestCase):
    """The Sort submenu, opened over a one-column table."""

    def panel(self, model, lst):
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertIn('col-sort-panel', th)
        panel = th[th.index('col-sort-panel'):]
        # Sort's own trigger comes before its panel, so the next one along is
        # Compute's -- i.e. where this panel has finished. Without cutting
        # there the last row would run on into the rest of the column menu.
        return panel[:panel.index('col-compute-trigger')]

    def rows(self, panel):
        return re.findall(r'<div class="col-compute-row[^"]*".*?'
                          r'(?=<div class="col-compute-row|$)', panel,
                          re.DOTALL)

    def names(self, panel):
        return re.findall(r'col-compute-name">([^<]*)<', panel)


class TestSortPanelRendering(SortPanelCase):
    """Four rows: two that rewrite the line, two that write a new one."""

    def test_it_lists_the_four_rows_in_order(self):
        lst, model = sort_model()
        self.assertEqual(self.names(self.panel(model, lst)),
                         ['Asc', 'Desc', 'Asc (new code)', 'Desc (new code)'])

    def test_only_the_rewriting_rows_have_a_checkbox(self):
        lst, model = sort_model()
        rows = self.rows(self.panel(model, lst))
        self.assertEqual([('col-tally-check' in row) for row in rows],
                         [True, True, False, False])

    def test_the_new_code_rows_hand_over_the_line_they_write(self):
        lst, model = sort_model()
        rows = self.rows(self.panel(model, lst))
        self.assertIn("sorted(data, key=lambda item: item[&#x27;b&#x27;])",
                      rows[2])
        self.assertIn('reverse=True', rows[3])

    def test_every_row_hands_its_expression_out_to_the_right(self):
        # A tooltip over a menu row would otherwise cover the rows around it.
        lst, model = sort_model()
        for row in self.rows(self.panel(model, lst)):
            self.assertIn('snc-py-exp-align="right"', row)

    def test_the_rewriting_rows_hand_over_what_they_would_make_the_line(self):
        lst, model = sort_model()
        rows = self.rows(self.panel(model, lst))
        self.assertIn(
            exp_attr("sorted(json.load(f), key=lambda item: item['b'])"),
            rows[0])
        self.assertIn('reverse=True', rows[1])

    def test_a_checked_row_still_names_its_own_sort(self):
        # The row names an order, not the click; dragging Asc off a line that
        # already sorts that way hands over the line as it reads.
        lst, model = sort_model(
            span=("sorted(json.load(f), key=lambda item: item['b'])",
                  4, 7, 4, 56))
        rows = self.rows(self.panel(model, lst))
        self.assertIn(
            exp_attr("sorted(json.load(f), key=lambda item: item['b'])"),
            rows[0])

    def test_with_no_span_they_have_no_expression_to_hand_over(self):
        lst, model = sort_model(span=None)
        rows = self.rows(self.panel(model, lst))
        self.assertNotIn('snc-py-exps', rows[0])
        self.assertNotIn('snc-py-exps', rows[1])

    def test_the_direction_the_line_sorts_in_is_the_checked_row(self):
        lst, model = sort_model(
            span=("sorted(json.load(f), key=lambda item: item['b'])",
                  4, 7, 4, 56))
        rows = self.rows(self.panel(model, lst))
        self.assertIn('checked', rows[0])
        self.assertNotIn('checked', rows[1])

    def test_an_unsorted_line_checks_neither(self):
        lst, model = sort_model()
        rows = self.rows(self.panel(model, lst))
        self.assertNotIn('checked', rows[0])
        self.assertNotIn('checked', rows[1])

    def test_with_no_span_the_rewriting_rows_are_inert(self):
        # A loop variable is bound by its statement, not written on it, so
        # there is no expression to wrap.
        lst, model = sort_model(span=None)
        rows = self.rows(self.panel(model, lst))
        self.assertIn('unselectable', rows[0])
        self.assertIn('unselectable', rows[1])
        self.assertNotIn('SortClick', rows[0])

    def test_the_new_code_rows_still_work_without_a_span(self):
        lst, model = sort_model(span=None)
        rows = self.rows(self.panel(model, lst))
        self.assertIn('SortCodeClick', rows[2])
        self.assertNotIn('unselectable', rows[2])

    def test_a_list_with_no_source_has_no_line_to_write(self):
        lst, model = sort_model(span=None, source=None)
        rows = self.rows(self.panel(model, lst))
        self.assertIn('unselectable', rows[2])
        self.assertNotIn('SortCodeClick', rows[2])

    def test_the_trigger_reads_as_a_flyout_like_compute(self):
        lst, model = sort_model()
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertIn('>Sort<', th)
        self.assertIn('col-sort-trigger', th)

    def test_only_the_open_submenu_draws_its_panel(self):
        lst, model = sort_model()
        model['col_search_dropdown'] = menu_id(model, 'compute')
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertNotIn('col-sort-panel', th)


class TestHeaderTracksTheMouseOnlyWhileDragging(unittest.TestCase):
    """A header asks to hear about mouse movement only while a column is
    actually being dragged.

    Every one of those events is a full re-run of the user's program -- one per
    16ms of movement -- and the handler that receives them does nothing at all
    unless a drag is in progress. So outside a drag they are asked for, paid
    for, and thrown away.
    """

    def header(self, **model_fields):
        lst = [{'b': 3}, {'b': 1}]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['b']"]
        model['_source_expr'] = 'data'
        model.update(model_fields)
        return _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))

    def test_hovering_a_header_asks_for_nothing(self):
        self.assertNotIn('snc-mouse-move', self.header())

    def test_a_drag_in_progress_tracks_every_move(self):
        self.assertIn('snc-mouse-move', self.header(column_drag_from=0))

    def test_the_drag_can_always_be_finished(self):
        # mouseup isn't continuous, so it costs nothing to keep listening --
        # and a release that lands anywhere has to end the drag.
        self.assertIn('snc-mouse-up', self.header())
        self.assertIn('snc-mouse-up', self.header(column_drag_from=0))


class TestTheDropLineGoesOnTheEdgeTheColumnIsComingFrom(unittest.TestCase):
    """The line drawn while a column is dragged over another sits on the edge
    the dragged column would land against: its left when it is coming from the
    right, its right when it is coming from the left.

    Which edge that is, is the one thing in a drag that is about position
    rather than identity -- so it has to be read off where the columns are
    DRAWN. `_menu_targets` orders by kind, every leaf and then the parents
    that span them, so a column carrying sub-columns is last in that order
    however far left it is drawn; asking it which side it is on would put the
    line on the same edge every time.
    """

    def header(self, over, frm):
        lst = [{'a': 1, 'b': [10, 20], 'c': 3},
               {'a': 2, 'b': [30, 40], 'c': 4}]
        model = init_model(lst, mock_get_visualizer)
        # Drawn a | b[0] b[1] | c, with b a spanning header over two.
        model['columns'] = {"$['a']": {},
                            "$['b']": {'cols': {'$[0]': {}, '$[1]': {}}},
                            "$['c']": {}}
        model['_source_expr'] = 'data'
        model['column_drag_from'] = frm
        model['column_drag_over'] = over
        out = visualize(lst, model, mock_get_visualizer,
                        lambda code: eval(code, {}, {'data': lst}))
        for m in re.finditer(r'<th class="[^"]*col-header[^"]*".*?</th>',
                             out, re.DOTALL):
            if f'class="col-name">{html.escape(over)}</span>' in m.group(0):
                return m.group(0)
        raise AssertionError(f'no header drawn for {over!r}')

    def test_a_column_from_the_left_marks_the_right_edge(self):
        th = self.header(over="$['c']", frm="$['a']")
        self.assertIn('col-drag-after', th)
        self.assertNotIn('col-drag-before', th)

    def test_a_column_from_the_right_marks_the_left_edge(self):
        th = self.header(over="$['a']", frm="$['c']")
        self.assertIn('col-drag-before', th)
        self.assertNotIn('col-drag-after', th)

    def test_a_spanning_header_takes_the_line_on_its_left_too(self):
        # The reported bug: `$['c']` is drawn to the right of `$['b']`, but is
        # earlier than it in menu-target order, so the drop line landed on the
        # right edge -- the side the column was coming from.
        th = self.header(over="$['b']", frm="$['c']")
        self.assertIn('col-drag-before', th)
        self.assertNotIn('col-drag-after', th)

    def test_and_on_its_right_when_the_column_comes_from_the_left(self):
        th = self.header(over="$['b']", frm="$['a']")
        self.assertIn('col-drag-after', th)
        self.assertNotIn('col-drag-before', th)

    def test_a_spanning_header_sits_where_its_first_sub_column_sits(self):
        # A sub-column dragged out to a column on the parent's right is coming
        # from the left, even though the leaf it left is drawn inside a header
        # whose own order-of-kind index is last.
        th = self.header(over="$['c']", frm=f"$['b']{SUBCOL_SEP}$[0]")
        self.assertIn('col-drag-after', th)
        self.assertNotIn('col-drag-before', th)


from table_visualizer import _is_pure_ref


class TestPureRef(unittest.TestCase):
    """Whether the table may read a cell by evaluating `<source>[i]` again, or
    has to read it off the value it was handed."""

    def test_a_name_is_free_to_evaluate_again(self):
        self.assertTrue(_is_pure_ref('data'))

    def test_so_is_a_path_of_subscripts_and_attributes(self):
        self.assertTrue(_is_pure_ref('data[0]'))
        self.assertTrue(_is_pure_ref("obj.rows['a'][2]"))

    def test_a_call_is_not(self):
        # Evaluating it again RUNS the user's function again -- once per cell,
        # on top of the once their program meant.
        self.assertFalse(_is_pure_ref('f()'))
        self.assertFalse(_is_pure_ref('json.load(open(p))'))
        self.assertFalse(_is_pure_ref('rows[compute()]'))

    def test_nor_is_anything_that_will_not_parse(self):
        self.assertFalse(_is_pure_ref('data['))
        self.assertFalse(_is_pure_ref(''))


class TestImpureSourceIsNotReEvaluated(unittest.TestCase):
    """A list that came from a call is read off the value in hand.

    Otherwise every cell re-runs the call: the user's side effects happen
    again, and every value their function logged on the way gets another
    visualizer stacked on the one before it.
    """

    def calls_to_build(self, source_expr, build):
        calls = []

        def counting():
            calls.append(1)
            return [{'b': 3}, {'b': 1}]

        lst = counting()
        del calls[:]
        scope = lambda code: eval(code, {}, {'f': counting, 'data': lst})
        build(lst, source_expr, scope)
        return len(calls)

    def render(self, lst, source_expr, scope):
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=(None, source_expr))
        model['columns'] = ["$['b']"]
        visualize(lst, model, mock_get_visualizer, scope)

    def test_a_call_source_is_never_run_again(self):
        self.assertEqual(self.calls_to_build('f()', self.render), 0)

    def test_a_named_source_still_reads_through_its_name(self):
        # Unchanged for the ordinary case: a name costs nothing to evaluate.
        lst = [{'b': 3}, {'b': 1}]
        seen = []
        scope = lambda code: (seen.append(code), eval(code, {}, {'data': lst}))[1]
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=('data', 'data'))
        model['columns'] = ["$['b']"]
        visualize(lst, model, mock_get_visualizer, scope)
        self.assertTrue(any('data[0]' in code for code in seen))

    def test_the_cells_still_show_the_right_values(self):
        lst = [{'b': 3}, {'b': 1}]
        scope = lambda code: eval(code, {}, {'f': lambda: lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=(None, 'f()'))
        model['columns'] = ["$['b']"]
        html_out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('>3<', html_out)
        self.assertIn('>1<', html_out)

    def test_the_column_still_hands_over_code_that_names_the_call(self):
        # Only evaluation changes: what a drag offers still says where the
        # values came from.
        lst = [{'b': 3}, {'b': 1}]
        scope = lambda code: eval(code, {}, {'f': lambda: lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=(None, 'f()'))
        model['columns'] = ["$['b']"]
        html_out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('for item in f()', html_out)


from table_visualizer import (SubcolToggle, SubcolShowAll, SubcolHideAll,
                              SubcolExprInput, SubcolExprKeyDown,
                              _subcol_candidates, _subs_at)


class SubcolPanelCase(unittest.TestCase):
    """The Subcolumns submenu, opened over a column whose values are lists."""

    LINES = ['id,name', '1,Alice']
    SPLIT = "$.split(',')"

    def model(self, columns=None, lst=None, open_submenu=True, index=0):
        lst = self.LINES if lst is None else lst
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = {self.SPLIT: {}} if columns is None else columns
        model['openDropdown'] = {'id': menu_id(model, index=index)}
        model['col_search_dropdown'] = (menu_id(model, 'subcols', index)
                                        if open_submenu else None)
        return model

    def header(self, model, lst=None):
        return _first_column_header(
            visualize(self.LINES if lst is None else lst, model,
                      mock_get_visualizer, None))

    def panel(self, model, lst=None):
        th = self.header(model, lst)
        self.assertIn('col-subcol-panel', th)
        # The Sort row is the next thing in the menu, so that is where this
        # panel has finished.
        panel = th[th.index('col-subcol-panel'):]
        return panel[:panel.index('col-sort')]

    def rows(self, panel):
        return re.findall(r'<div class="[^"]*col-subcol-row[^"]*".*?'
                          r'(?=<div class="[^"]*col-subcol-row|$)', panel,
                          re.DOTALL)

    def names(self, panel):
        return re.findall(r'col-compute-name">([^<]*)<', panel)


class TestSubcolMenuRendering(SubcolPanelCase):
    """Sub-columns are made here rather than from a button on the header: a
    checkbox for every field the column's values have, a box for whatever the
    user writes themselves, and Show all / Hide all over the top."""

    def test_the_row_sits_under_remove_column(self):
        menu = self.header(self.model(open_submenu=False))
        self.assertEqual(
            re.findall(r'>(Remove Column|Subcolumns|Sort|Group By This Column|Compute)<',
                       menu),
            ['Remove Column', 'Subcolumns', 'Sort', 'Group By This Column',
             'Compute'])

    def test_the_panel_is_only_there_when_the_submenu_is_open(self):
        self.assertNotIn('col-subcol-panel',
                         self.header(self.model(open_submenu=False)))

    def test_it_offers_the_fields_the_values_have(self):
        # A row here is a CSV line; what a sub-column reads is one field of the
        # list the column splits it into.
        self.assertEqual(self.names(self.panel(self.model())),
                         ['Show all', 'Hide all', '$[0]', '$[1]'])

    def test_a_field_already_shown_is_checked(self):
        model = self.model({self.SPLIT: {'cols': {'$[0]': {}}}}, index=1)
        rows = self.rows(self.panel(model))
        self.assertIn('checked', rows[2])
        self.assertNotIn('checked', rows[3])

    def test_clicking_a_row_toggles_that_field(self):
        model = self.model()
        panel = self.panel(model)
        self.assertIn(
            html.escape(repr(SubcolToggle(col=self.SPLIT, expr='$[0]'))), panel)

    def test_show_all_and_hide_all_are_the_first_two_rows(self):
        panel = self.panel(self.model())
        self.assertIn(html.escape(repr(SubcolShowAll(col=self.SPLIT))), panel)
        self.assertIn(html.escape(repr(SubcolHideAll(col=self.SPLIT))), panel)

    def test_a_written_sub_column_gets_a_box_of_its_own(self):
        # No candidate row covers it, so it is listed as what it is.
        model = self.model({self.SPLIT: {'cols': {'len($)': {}}}}, index=1)
        panel = self.panel(model)
        self.assertIn('value="len($)"', panel)

    def test_the_empty_box_at_the_foot_checks_nothing(self):
        panel = self.panel(self.model())
        free = [r for r in self.rows(panel) if 'col-subcol-free' in r]
        self.assertEqual(len(free), 1)
        self.assertIn('placeholder="Add subcolumn"', free[0])
        self.assertIn('disabled', free[0])
        self.assertNotIn('SubcolToggle', free[0])

    def test_each_box_names_itself_for_the_focus(self):
        # The first character typed adds a column, and a box found again by its
        # place among everything focusable would lose the rest of the word.
        self.assertIn(f'snc-focus-key="subcol-free-{self.SPLIT}-0"',
                      self.panel(self.model()))

    def test_the_box_keeps_its_name_when_the_first_character_lands(self):
        # That first character makes the column it was typed at stop being a
        # leaf, which moves it. A name that moved with it would lose the focus
        # to the very edit that caused the move.
        model = self.model()
        key = lambda m: re.search(r'snc-focus-key="([^"]*)"',
                                  self.panel(m)).group(1)
        before = key(model)
        event = {'pythonEventStr': repr(SubcolExprInput(col=col_at(model), expr='',
                                                        value='l')),
                 'eventJSON': {'type': 'input', 'value': 'l'}}
        with patch('table_visualizer.save_columns_to_dotfile'):
            after, _ = update(event, None, model, self.LINES,
                              mock_get_visualizer)
        self.assertEqual(key(after), before)

    def test_a_column_with_no_fields_still_offers_the_box(self):
        # Always enabled: there is nothing to detect on a column of numbers,
        # but an expression can still be written against it.
        model = self.model({'$': {}}, lst=[1, 2, 3])
        panel = self.panel(model, lst=[1, 2, 3])
        self.assertEqual(self.names(panel), ['Show all', 'Hide all'])
        self.assertIn('placeholder="Add subcolumn"', panel)


class TestSubcolCandidates(unittest.TestCase):
    """What the menu offers to show: the fields of whatever a sub-column would
    read -- the cell's value for a plain column, and the ELEMENT for a splat,
    since that is what a splat's sub-column is written against."""

    def test_a_plain_column_offers_its_values_fields(self):
        lst = ['id,name', '1,Alice']
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = {"$.split(',')": {}}
        self.assertEqual(
            _subcol_candidates("$.split(',')", lst, model, mock_get_visualizer),
            ['$[0]', '$[1]'])

    def test_a_splat_offers_its_elements_fields(self):
        groups = {'eng': [['1', 'Alice']], 'mkt': [['2', 'Bob']]}
        model = init_model(groups, mock_get_visualizer)
        model['columns'] = {'$k': {}, '*$v': {}}
        self.assertEqual(
            _subcol_candidates('*$v', groups, model, mock_get_visualizer),
            ['$[0]', '$[1]'])


class TestSubcolEvents(unittest.TestCase):
    """Checking a box is the whole edit: what is checked is read back out of
    the column's own sub-columns, so there is nothing else to keep in step."""

    LINES = ['id,name', '1,Alice']
    SPLIT = "$.split(',')"

    def model(self, columns=None, index=0):
        model = init_model(self.LINES, mock_get_visualizer)
        model['columns'] = {self.SPLIT: {}} if columns is None else columns
        model['openDropdown'] = {'id': menu_id(model, index=index)}
        model['col_search_dropdown'] = menu_id(model, 'subcols', index)
        return model

    def click(self, model, event):
        with patch('table_visualizer.save_columns_to_dotfile') as saved:
            out, _cmds = update(make_column_mouse_event(repr(event)), None,
                                model, self.LINES, mock_get_visualizer)
        return out, saved

    def subs(self, model):
        return list(_subs_at(model['columns'], self.SPLIT) or {})

    def test_checking_a_field_makes_it_a_sub_column(self):
        model, saved = self.click(self.model(), SubcolToggle(col=self.SPLIT, expr='$[0]'))
        self.assertEqual(self.subs(model), ['$[0]'])
        saved.assert_called()

    def test_unchecking_takes_it_away(self):
        model, _ = self.click(self.model({self.SPLIT: {'cols': {'$[0]': {}}}},
                                         index=1),
                              SubcolToggle(col=self.SPLIT, expr='$[0]'))
        self.assertEqual(self.subs(model), [])

    def test_show_all_takes_every_field(self):
        model, _ = self.click(self.model(), SubcolShowAll(col=self.SPLIT))
        self.assertEqual(self.subs(model), ['$[0]', '$[1]'])

    def test_hide_all_takes_the_written_ones_too(self):
        # Everything the menu lists is what it reaches. The parent is target 2
        # here: its two leaves come first, and it is not one of them.
        model, _ = self.click(
            self.model({self.SPLIT: {'cols': {'$[0]': {}, 'len($)': {}}}},
                       index=2),
            SubcolHideAll(col=self.SPLIT))
        self.assertEqual(self.subs(model), [])

    def test_hiding_them_all_gives_the_column_back_its_own_cell(self):
        model, _ = self.click(
            self.model({self.SPLIT: {'cols': {'$[0]': {}}}}, index=1),
            SubcolHideAll(col=self.SPLIT))
        self.assertEqual([leaf.expr for leaf in _leaf_columns(model['columns'])],
                         [self.SPLIT])

    def test_the_menu_stays_on_the_column_it_was_opened_on(self):
        # A column that gains sub-columns stops being a leaf and moves in the
        # target space. The ids name the column rather than where it sits, so
        # there is nothing to move and nothing to re-point.
        before = self.model()
        model, _ = self.click(before, SubcolToggle(col=self.SPLIT, expr='$[0]'))
        self.assertEqual(model['openDropdown'], before['openDropdown'])
        self.assertEqual(model['col_search_dropdown'],
                         before['col_search_dropdown'])

    def test_a_written_box_adds_a_sub_column(self):
        model = self.model()
        event = {'pythonEventStr': repr(SubcolExprInput(col=self.SPLIT, expr='',
                                                        value='len($)')),
                 'eventJSON': {'type': 'input', 'value': 'len($)'}}
        with patch('table_visualizer.save_columns_to_dotfile'):
            out, _ = update(event, None, model, self.LINES, mock_get_visualizer)
        self.assertEqual(list(_subs_at(out['columns'], self.SPLIT) or {}),
                         ['len($)'])

    def test_editing_a_box_keeps_the_columns_place(self):
        model = self.model(
            {self.SPLIT: {'cols': {'len($)': {}, '$[1]': {}}}}, index=2)
        event = {'pythonEventStr': repr(SubcolExprInput(col=self.SPLIT, expr='len($)',
                                                        value='len($) * 2')),
                 'eventJSON': {'type': 'input', 'value': 'len($) * 2'}}
        with patch('table_visualizer.save_columns_to_dotfile'):
            out, _ = update(event, None, model, self.LINES, mock_get_visualizer)
        self.assertEqual(list(_subs_at(out['columns'], self.SPLIT) or {}),
                         ['len($) * 2', '$[1]'])

    def test_a_search_goes_away_with_the_column_it_was_set_on(self):
        # A leaf is a column: it can have been searched on, under an identity
        # nothing will answer to once the sub-column is gone.
        model = self.model({self.SPLIT: {'cols': {'$[0]': {}}}}, index=1)
        target = f'{self.SPLIT}{SUBCOL_SEP}$[0]'
        model['column_searches'] = {target: {'op': '==', 'text': "'id'",
                                             'compose': 'and'}}
        out, _ = self.click(model, SubcolToggle(col=self.SPLIT, expr='$[0]'))
        self.assertIsNone(out['column_searches'])

    def test_emptying_a_box_drops_it(self):
        model = self.model({self.SPLIT: {'cols': {'len($)': {}}}}, index=1)
        event = {'pythonEventStr': repr(SubcolExprInput(col=self.SPLIT, expr='len($)',
                                                        value='')),
                 'eventJSON': {'type': 'input', 'value': ''}}
        with patch('table_visualizer.save_columns_to_dotfile'):
            out, _ = update(event, None, model, self.LINES, mock_get_visualizer)
        self.assertEqual(list(_subs_at(out['columns'], self.SPLIT) or {}), [])

    def test_the_menu_stays_open_across_a_toggle(self):
        # Checking several boxes in a row is the point of a list of them.
        model, _ = self.click(self.model(), SubcolToggle(col=self.SPLIT, expr='$[0]'))
        self.assertIsNotNone(model['openDropdown'])

    def test_enter_says_the_column_is_written(self):
        model = self.model()
        model['col_search_dropdown'] = menu_id(model, 'subcols')
        event = {'pythonEventStr': repr(SubcolExprKeyDown()),
                 'eventJSON': {'type': 'keydown', 'key': 'Enter'}}
        out, _ = update(event, None, model, self.LINES, mock_get_visualizer)
        self.assertIsNone(out['openDropdown'])

    def test_escape_leaves_the_column_menu_open(self):
        # Innermost first, like the aggregation box.
        model = self.model()
        event = {'pythonEventStr': repr(SubcolExprKeyDown()),
                 'eventJSON': {'type': 'keydown', 'key': 'Escape'}}
        out, _ = update(event, None, model, self.LINES, mock_get_visualizer)
        self.assertIsNone(out['col_search_dropdown'])
        self.assertIsNotNone(out['openDropdown'])

    def test_a_stale_index_is_a_noop(self):
        model, _ = self.click(self.model(), SubcolToggle(col='$.gone', expr='$[0]'))
        self.assertEqual(self.subs(model), [])


from table_visualizer import ColumnSubmenuDwell


class TestColumnMenuDwell(unittest.TestCase):
    """Resting the pointer on a row of the column ▾ menu opens the submenu it
    names, and resting it on a row that names none puts the open one away.

    A row renders the attribute only when dwelling there would change
    something, so a pointer left lying still can never cost a re-run for a menu
    that is already as the user wants it.
    """

    def menu(self, open_dropdown=None):
        lst = SORT_LIST
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ["$['b']"]
        model['_source_expr'] = 'data'
        model['openDropdown'] = {'id': menu_id(model)}
        model['col_search_dropdown'] = open_dropdown
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        return th[th.index('col-menu-panel'):]

    def dwells(self, menu):
        return re.findall(r'snc-dwell="([^"]*)"', menu)

    def opens(self, dropdown_id):
        return html.escape(repr(ColumnSubmenuDwell(dropdown_id=dropdown_id)))

    def test_sort_and_compute_offer_to_open_themselves(self):
        dwells = self.dwells(self.menu())
        self.assertIn(self.opens("sort-$['b']"), dwells)
        self.assertIn(self.opens("compute-$['b']"), dwells)

    def test_a_submenu_already_open_offers_nothing(self):
        dwells = self.dwells(self.menu(open_dropdown="sort-$['b']"))
        self.assertNotIn(self.opens("sort-$['b']"), dwells)
        self.assertIn(self.opens("compute-$['b']"), dwells)

    def test_the_other_rows_offer_to_close_what_is_open(self):
        self.assertIn(self.opens(None), self.dwells(self.menu(open_dropdown="sort-$['b']")))

    def test_with_nothing_open_there_is_nothing_to_close(self):
        self.assertNotIn(self.opens(None), self.dwells(self.menu()))

    def search_row(self, menu):
        return menu[menu.index('col-search-area'):][:200]

    def test_a_row_does_not_offer_to_close_its_own_chip_menu(self):
        # The operator chip lives in the search row; resting the pointer on the
        # row it opened from is not a way of leaving it.
        menu = self.menu(open_dropdown="op-$['b']")
        self.assertEqual(self.dwells(self.search_row(menu)), [])

    def test_but_it_does_close_a_submenu_that_is_not_its_own(self):
        menu = self.menu(open_dropdown="sort-$['b']")
        self.assertEqual(self.dwells(self.search_row(menu)), [self.opens(None)])

    def test_and_another_row_still_closes_its_chip_menu(self):
        menu = self.menu(open_dropdown="op-$['b']")
        remove_row = menu[:menu.index('col-sort')]
        self.assertIn(self.opens(None), self.dwells(remove_row))


from table_visualizer import ColumnMenuDismiss


class TestColumnMenuDismiss(unittest.TestCase):
    """A click outside the menu closes it, the way a menu anywhere else does."""

    def test_the_panel_says_what_clicking_away_means(self):
        lst, model = sort_model()
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        menu = th[th.index('col-menu-panel'):]
        self.assertIn(f'snc-dismiss="{html.escape(repr(ColumnMenuDismiss()))}"',
                      menu[:200])

    def dismiss(self, **model_fields):
        lst, model = sort_model()
        model.update(model_fields)
        return update(make_column_mouse_event(repr(ColumnMenuDismiss())),
                      ('data', 'data'), model, lst, mock_get_visualizer,
                      eval_in_scope=lambda code: eval(code, {}, {'data': lst}))

    def test_it_closes_the_menu(self):
        model, _ = self.dismiss()
        self.assertIsNone(model['openDropdown'])

    def test_it_takes_the_open_submenu_with_it(self):
        model, _ = self.dismiss(col_search_dropdown='sort-0')
        self.assertIsNone(model['col_search_dropdown'])

    def test_it_forgets_the_tally_view_like_every_other_way_out(self):
        model, _ = self.dismiss(tally_filter='ab', tally_sort='common')
        self.assertEqual(model['tally_filter'], '')

    def test_it_writes_no_code(self):
        _, commands = self.dismiss()
        self.assertEqual(commands, [])

    def test_it_leaves_the_column_search_alone(self):
        # Closing the menu is not clearing what was set in it.
        lst, model = sort_model()
        _set_column_search(model, "$['b']", op='>=', text='2')
        model, _ = update(
            make_column_mouse_event(repr(ColumnMenuDismiss())),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda code: eval(code, {}, {'data': lst}))
        self.assertEqual(_column_search_row(model, "$['b']")['text'], '2')


class TestColumnSubmenuDwellEvent(unittest.TestCase):
    """Setting, not toggling: dwelling says which submenu should be open."""

    def dwell(self, dropdown_id, open_dropdown=None):
        lst, model = sort_model()
        model['col_search_dropdown'] = open_dropdown
        model, commands = update(
            make_column_mouse_event(repr(ColumnSubmenuDwell(dropdown_id=dropdown_id))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda code: eval(code, {}, {'data': lst}))
        return model, commands

    def test_it_opens_the_submenu_it_names(self):
        model, _ = self.dwell("sort-$['b']")
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'sort'))

    def test_it_replaces_whatever_was_open(self):
        model, _ = self.dwell("compute-$['b']", open_dropdown="sort-$['b']")
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'compute'))

    def test_naming_none_closes(self):
        model, _ = self.dwell(None, open_dropdown="sort-$['b']")
        self.assertIsNone(model['col_search_dropdown'])

    def test_it_leaves_the_column_menu_itself_open(self):
        model, _ = self.dwell("sort-$['b']")
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})

    def test_it_writes_no_code(self):
        _, commands = self.dwell("sort-$['b']")
        self.assertEqual(commands, [])


class SortEventCase(unittest.TestCase):
    def click(self, event, lst=None, **kwargs):
        lst, model = sort_model(lst, **kwargs)
        return update(make_column_mouse_event(repr(event)),
                      ('data', 'data'), model, lst, mock_get_visualizer,
                      eval_in_scope=lambda code: eval(code, {}, {'data': lst}))


class TestSortClick(SortEventCase):
    """Clicking a direction rewrites the line the table is showing."""

    def test_it_wraps_the_lines_own_expression(self):
        _, commands = self.click(SortClick(col="$['b']", direction='asc'))
        self.assertEqual(
            commands,
            [ChangeSourceExpr(
                expression="sorted(json.load(f), key=lambda item: item['b'])",
                start_line=4, start_col=7, end_line=4, end_col=19)])

    def test_descending_asks_for_the_reverse(self):
        _, commands = self.click(SortClick(col="$['b']", direction='desc'))
        self.assertIn('reverse=True', commands[0].expression)

    def test_the_row_itself_sorts_without_a_key(self):
        _, commands = self.click(SortClick(col='$', direction='asc'),
                                 lst=[3, 1, 2], columns=['$'])
        self.assertEqual(commands[0].expression, 'sorted(json.load(f))')

    def test_clicking_the_checked_direction_takes_the_sort_off(self):
        span = ("sorted(json.load(f), key=lambda item: item['b'])", 4, 7, 4, 56)
        _, commands = self.click(SortClick(col="$['b']", direction='asc'), span=span)
        self.assertEqual(commands[0].expression, 'json.load(f)')

    def test_the_other_direction_replaces_rather_than_nests(self):
        span = ("sorted(json.load(f), key=lambda item: item['b'])", 4, 7, 4, 56)
        _, commands = self.click(SortClick(col="$['b']", direction='desc'), span=span)
        self.assertEqual(commands[0].expression.count('sorted('), 1)
        self.assertIn('reverse=True', commands[0].expression)

    def test_the_menu_stays_open(self):
        # A checkbox, and flipping the direction is the common next act.
        model, _ = self.click(SortClick(col="$['b']", direction='asc'))
        self.assertEqual(model['openDropdown'], {'id': menu_id(model)})
        self.assertEqual(model['col_search_dropdown'], menu_id(model, 'sort'))

    def test_with_no_span_there_is_nothing_to_rewrite(self):
        _, commands = self.click(SortClick(col="$['b']", direction='asc'), span=None)
        self.assertEqual(commands, [])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        _, commands = self.click(SortClick(col='$.gone', direction='asc'))
        self.assertEqual(commands, [])


class TestSortCodeClick(SortEventCase):
    """The other two rows write a line instead, the way Unique and Tally do."""

    def test_it_writes_the_sorted_list_as_a_new_line(self):
        _, commands = self.click(SortCodeClick(col="$['b']", direction='asc'))
        self.assertEqual(
            commands[0][:2],
            ('data_sorted', "sorted(data, key=lambda item: item['b'])"))

    def test_descending(self):
        _, commands = self.click(SortCodeClick(col="$['b']", direction='desc'))
        self.assertIn('reverse=True', commands[0][1])

    def test_sorted_is_a_builtin_so_it_needs_no_import(self):
        _, commands = self.click(SortCodeClick(col="$['b']", direction='asc'))
        self.assertEqual(len(commands[0]), 2)

    def test_it_sorts_the_whole_list_rather_than_the_lines_expression(self):
        # The new line names the list, the way every Compute row does; only the
        # rewriting rows care what the line itself says.
        span = ("sorted(json.load(f), key=lambda item: item['b'])", 4, 7, 4, 56)
        _, commands = self.click(SortCodeClick(col="$['b']", direction='asc'),
                                 span=span)
        self.assertEqual(commands[0][1],
                         "sorted(data, key=lambda item: item['b'])")

    def test_the_name_falls_back_when_the_list_has_no_name(self):
        _, commands = self.click(SortCodeClick(col="$['b']", direction='asc'),
                                 source='data[0]')
        self.assertEqual(commands[0][0], 'result_sorted')

    def test_the_menu_closes_behind_it(self):
        model, _ = self.click(SortCodeClick(col="$['b']", direction='asc'))
        self.assertIsNone(model['openDropdown'])
        self.assertIsNone(model['col_search_dropdown'])

    def test_a_list_with_no_source_writes_nothing(self):
        _, commands = self.click(SortCodeClick(col="$['b']", direction='asc'),
                                 source=None)
        self.assertEqual(commands, [])


# === Group By ===

from table_visualizer import (GroupByClick, _group_by_expr, _column_binding,
                              _LIST_BINDS, _DICT_BINDS)


class TestGroupByExpr(unittest.TestCase):
    """The list as a dict of lists, keyed by the column.

    A dict of lists rather than itertools.groupby, which only groups runs and
    so would answer wrongly for any list the user hasn't already sorted.
    """

    def test_a_column_becomes_the_key(self):
        self.assertEqual(
            _group_by_expr("$['b']", 'data'),
            "(_d := {}, [_d.setdefault(item['b'], []).append(item) "
            "for item in data])[0]")

    def test_the_row_itself_can_be_the_key(self):
        self.assertEqual(
            _group_by_expr('$', 'nums'),
            '(_d := {}, [_d.setdefault(item, []).append(item) '
            'for item in nums])[0]')

    def test_a_computed_column_reads_the_row_through_its_expression(self):
        self.assertEqual(
            _group_by_expr('len($)', 'data'),
            '(_d := {}, [_d.setdefault(len(item), []).append(item) '
            'for item in data])[0]')

    def test_a_column_naming_the_row_number_enumerates(self):
        # The one thing Sort can't do: sorted() takes a key over rows and a row
        # handed to one doesn't know its number, but a comprehension can count.
        self.assertEqual(
            _group_by_expr('$i % 2', 'data'),
            '(_d := {}, [_d.setdefault(i % 2, []).append(item) '
            'for i, item in enumerate(data)])[0]')

    def test_a_dict_groups_the_pairs_its_rows_are(self):
        self.assertEqual(
            _group_by_expr('$v', 'd', _DICT_BINDS),
            '(_d := {}, [_d.setdefault(v, []).append((k, v)) '
            'for k, v in d.items()])[0]')

    def test_a_dict_keyed_on_its_keys_still_groups_the_pairs(self):
        self.assertEqual(
            _group_by_expr('$k[0]', 'd', _DICT_BINDS),
            '(_d := {}, [_d.setdefault(k[0], []).append((k, v)) '
            'for k, v in d.items()])[0]')

    def test_the_code_it_writes_actually_groups_a_list(self):
        # Unusual enough an expression to be run rather than only matched.
        data = [{'b': 1, 'n': 'a'}, {'b': 2, 'n': 'x'}, {'b': 1, 'n': 'c'}]
        self.assertEqual(
            eval(_group_by_expr("$['b']", 'data'), {'data': data}),
            {1: [{'b': 1, 'n': 'a'}, {'b': 1, 'n': 'c'}],
             2: [{'b': 2, 'n': 'x'}]})

    def test_and_a_dict(self):
        d = {'a': 1, 'b': 2, 'c': 1}
        self.assertEqual(
            eval(_group_by_expr('$v', 'd', _DICT_BINDS), {'d': d}),
            {1: [('a', 1), ('c', 1)], 2: [('b', 2)]})

    def test_and_one_keyed_on_the_row_number(self):
        nums = [3, 1, 4, 1, 5]
        self.assertEqual(
            eval(_group_by_expr('$i % 2', 'nums'), {'nums': nums}),
            {0: [3, 4, 5], 1: [1, 1]})


class TestColumnBindingWholeRow(unittest.TestCase):
    """A group holds whole rows, so the binding keeps the pair even where the
    key alone would have needed only half of it."""

    def test_a_dict_column_narrows_by_default(self):
        self.assertEqual(_column_binding('$v', 'd', _DICT_BINDS),
                         'v in d.values()')
        self.assertEqual(_column_binding('$k', 'd', _DICT_BINDS), 'k in d')

    def test_asking_for_the_whole_row_stops_it_narrowing(self):
        self.assertEqual(
            _column_binding('$v', 'd', _DICT_BINDS, whole_row=True),
            'k, v in d.items()')
        self.assertEqual(
            _column_binding('$k', 'd', _DICT_BINDS, whole_row=True),
            'k, v in d.items()')

    def test_the_index_still_wraps_it(self):
        self.assertEqual(
            _column_binding('$v * $i', 'd', _DICT_BINDS, whole_row=True),
            'i, (k, v) in enumerate(d.items())')

    def test_a_list_has_only_the_one_row_to_bind(self):
        self.assertEqual(_column_binding("$['b']", 'data', _LIST_BINDS,
                                         whole_row=True),
                         'item in data')


def group_by_model(lst=None, columns=None, span=SPAN, source='data'):
    """A table model with a column menu open, and no submenu -- Group By is a
    row of the menu itself rather than a flyout out of it."""
    lst, model = sort_model(lst, columns, span, source)
    model['col_search_dropdown'] = None
    return lst, model


class TestGroupByRow(unittest.TestCase):
    """One plain row of the column ▾ menu, which writes a line of its own."""

    def row(self, model, lst):
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        start = th.index('col-group-by')
        return th[th.rindex('<div', 0, start):th.index('</div>', start)]

    def test_it_sits_between_sort_and_compute(self):
        # Sort's own trigger carries Compute's classes as well as its own, so
        # the rows are told apart by what they say rather than by class.
        lst, model = group_by_model()
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        menu = th[th.index('col-menu-panel'):]
        self.assertEqual(re.findall(r'>(Remove Column|Sort|Group By This Column|Compute)<',
                                    menu),
                         ['Remove Column', 'Sort', 'Group By This Column',
                          'Compute'])

    def test_it_hands_over_the_line_it_writes(self):
        lst, model = group_by_model()
        self.assertIn(
            exp_attr("(_d := {}, [_d.setdefault(item['b'], [])"
                     ".append(item) for item in data])[0]"),
            self.row(model, lst))

    def test_it_hands_it_out_to_the_right(self):
        # A tooltip over a menu row would otherwise cover the rows around it.
        lst, model = group_by_model()
        self.assertIn('snc-py-exp-align="right"', self.row(model, lst))

    def test_clicking_it_asks_to_group(self):
        lst, model = group_by_model()
        self.assertIn(html.escape(repr(GroupByClick(col="$['b']"))),
                      self.row(model, lst))

    def test_it_names_the_list_rather_than_the_lines_own_expression(self):
        # Like every Compute row, and like Sort's two `(new code)` rows.
        lst, model = group_by_model()
        self.assertIn('for item in data', self.row(model, lst))

    def test_a_column_naming_the_row_number_still_works(self):
        # Where Sort goes inert, this enumerates.
        lst, model = group_by_model(lst=[1, 2, 3], columns=['$i % 2'])
        row = self.row(model, lst)
        self.assertNotIn('unselectable', row)
        self.assertIn('enumerate(data)', row)

    def test_without_a_source_there_is_no_list_to_name(self):
        lst, model = group_by_model(source=None)
        row = self.row(model, lst)
        self.assertIn('unselectable', row)
        self.assertNotIn('snc-py-exps', row)
        self.assertNotIn('GroupByClick', row)


class TestGroupByClick(unittest.TestCase):
    """Clicking it writes the grouped dict as a line of its own."""

    def click(self, event, lst=None, **kwargs):
        lst, model = group_by_model(lst, **kwargs)
        return update(make_column_mouse_event(repr(event)),
                      ('data', 'data'), model, lst, mock_get_visualizer,
                      eval_in_scope=lambda code: eval(code, {}, {'data': lst}))

    def test_it_writes_the_grouped_list_as_a_new_line(self):
        _, commands = self.click(GroupByClick(col="$['b']"))
        self.assertEqual(
            commands[0][:2],
            ('data_grouped',
             "(_d := {}, [_d.setdefault(item['b'], []).append(item) "
             "for item in data])[0]"))

    def test_setdefault_is_a_builtin_so_it_needs_no_import(self):
        _, commands = self.click(GroupByClick(col="$['b']"))
        self.assertEqual(len(commands[0]), 2)

    def test_it_groups_the_whole_list_rather_than_the_lines_expression(self):
        span = ("sorted(json.load(f), key=lambda item: item['b'])", 4, 7, 4, 56)
        _, commands = self.click(GroupByClick(col="$['b']"), span=span)
        self.assertIn('for item in data', commands[0][1])

    def test_the_name_falls_back_when_the_list_has_no_name(self):
        _, commands = self.click(GroupByClick(col="$['b']"), source='data[0]')
        self.assertEqual(commands[0][0], 'result_grouped')

    def test_the_menu_closes_behind_it(self):
        # One line written, unlike checking a box, which invites the next.
        model, _ = self.click(GroupByClick(col="$['b']"))
        self.assertIsNone(model['openDropdown'])
        self.assertIsNone(model['col_search_dropdown'])

    def test_a_list_with_no_source_writes_nothing(self):
        _, commands = self.click(GroupByClick(col="$['b']"), source=None)
        self.assertEqual(commands, [])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        _, commands = self.click(GroupByClick(col='$.gone'))
        self.assertEqual(commands, [])


class TestGroupBySeedsTheGroupedTable(unittest.TestCase):
    """The grouped dict lands on a line of its own, as a type nothing has ever
    configured -- and what it wants is not what detection would say, which
    reads a group's own length as its fields.

    So the click leaves the columns behind it. A group holds whole ROWS of the
    table being grouped, so inside `*$v` the element is a row and the columns
    that read one read the other: they come along as they are written."""

    ROWS = [['1', 'Alice', 'eng'], ['2', 'Bob', 'mkt'], ['5', 'Eva', 'eng']]

    def seed(self, columns, index, lst=None, loaded=None, source='data'):
        lst = self.ROWS if lst is None else lst
        lst, model = group_by_model(lst, columns=columns, source=source)
        with patch('table_visualizer.load_columns_from_dotfile',
                   return_value=loaded), \
             patch('table_visualizer.save_columns_to_dotfile') as saved:
            update(make_column_mouse_event(repr(GroupByClick(col=col_at(model, index)))),
                   ('data', 'data'), model, lst, mock_get_visualizer,
                   eval_in_scope=lambda code: eval(code, {}, {'data': lst}))
        return saved

    def test_it_seeds_the_key_the_size_and_the_group_spread(self):
        saved = self.seed(['$[0]', '$[1]', '$[2]'], index=2)
        self.assertEqual(
            saved.call_args[0][:3],
            ('builtins.str->builtins.list', [],
             ['$k', 'len($v)', {'expr': '*$v', 'cols': ['$[0]', '$[1]']}]))

    def test_the_column_grouped_on_is_the_key_rather_than_a_column_again(self):
        # It has one value per group by construction, and $k already says it.
        saved = self.seed(['$[0]', '$[2]'], index=1)
        self.assertEqual(saved.call_args[0][2][2]['cols'], ['$[0]'])

    def test_the_key_type_is_the_columns_own_rather_than_the_rows(self):
        # The keys are what the column answers, and the value is always a list.
        saved = self.seed(['int($[0])'], index=0)
        self.assertEqual(saved.call_args[0][0], 'builtins.int->builtins.list')

    def test_a_type_someone_has_already_configured_is_left_alone(self):
        # A seed is a default for a type nobody has said anything about.
        saved = self.seed(['$[0]', '$[2]'], index=1, loaded=['$k'])
        saved.assert_not_called()

    def test_a_column_that_names_the_row_number_stays_behind(self):
        # `$i` is the row's number in the list it was read from, and an element
        # of a group has no such number; `$$` named that list itself.
        saved = self.seed(['$i', 'len($$)', '$[0]', '$[2]'], index=3)
        self.assertEqual(saved.call_args[0][2][2]['cols'], ['$[0]'])

    def test_a_splat_brings_its_own_sub_columns_along(self):
        # The leaves come first in the menu-target space, so `$[2]` is 1 here:
        # the splat carrying a sub-column is not itself a leaf.
        saved = self.seed({'*$[1]': {'cols': {'$[0]': {}}}, '$[2]': {}},
                          index=1)
        self.assertEqual(saved.call_args[0][2][2]['cols'],
                         [{'expr': '*$[1]', 'cols': ['$[0]']}])

    def test_a_dicts_rows_are_pairs_so_its_columns_stay_behind(self):
        # Grouping a dict answers with lists of the pairs `.items()` gives, and
        # a sigil binds to the row it was written for rather than to a pair.
        saved = self.seed(['$k', '$v'], index=1, lst={'a': 1, 'b': 2})
        self.assertEqual(saved.call_args[0][2],
                         ['$k', 'len($v)', '*$v'])

    def test_a_click_that_writes_no_line_seeds_nothing(self):
        self.seed(['$[0]'], index=0, source=None).assert_not_called()


# === Convert Type ===

from table_visualizer import (ConvertTypeToggle, ConvertTypeColumnClick,
                              CONVERT_TYPES, _convert_expr, _converted_type,
                              _column_computes)


class TestConvertExpr(unittest.TestCase):
    """What the menu writes into the column's own expression."""

    def test_it_wraps_the_column(self):
        self.assertEqual(_convert_expr("$['n']", 'int'), "int($['n'])")

    def test_it_offers_the_four_types_the_menu_lists(self):
        self.assertEqual([_convert_expr('$', to) for to in CONVERT_TYPES],
                         ['int($)', 'float($)', 'str($)', 'bool($)'])

    def test_another_type_replaces_rather_than_nests(self):
        self.assertEqual(_convert_expr("int($['n'])", 'float'), "float($['n'])")

    def test_no_type_takes_the_conversion_off(self):
        self.assertEqual(_convert_expr("int($['n'])", None), "$['n']")

    def test_an_expression_that_converts_nothing_is_left_as_written(self):
        self.assertEqual(_convert_expr("len($['n'])", None), "len($['n'])")

    def test_a_splat_converts_the_elements_it_spread(self):
        self.assertEqual(_convert_expr("*$['ns']", 'int'),
                         "*[int(item2) for item2 in $['ns']]")

    def test_and_takes_that_back_off_again(self):
        self.assertEqual(
            _convert_expr("*[int(item2) for item2 in $['ns']]", None),
            "*$['ns']")

    def test_a_splats_type_is_replaced_rather_than_nested_too(self):
        self.assertEqual(
            _convert_expr("*[int(item2) for item2 in $['ns']]", 'str'),
            "*[str(item2) for item2 in $['ns']]")

    def test_a_splat_of_a_comprehension_does_not_shadow_its_own_element(self):
        # _promote_expr's rule: `for item2 in [f(item2) for item2 in v]` is
        # correct Python that reads like a bug.
        self.assertEqual(
            _convert_expr('*[item2 for item2 in $]', 'int'),
            '*[int(item3) for item3 in [item2 for item2 in $]]')


class TestConvertedType(unittest.TestCase):
    """Which box is ticked is the column expression's answer, not the model's --
    so a conversion the user typed by hand ticks the box that describes it."""

    def test_a_wrapped_column_reads_as_its_type(self):
        self.assertEqual(_converted_type("int($['n'])"), 'int')
        self.assertEqual(_converted_type("bool($['n'])"), 'bool')

    def test_a_plain_column_converts_nothing(self):
        self.assertIsNone(_converted_type("$['n']"))

    def test_a_call_that_is_not_a_conversion_is_not_one(self):
        self.assertIsNone(_converted_type("len($['n'])"))

    def test_a_two_argument_int_is_not_the_conversion_this_menu_writes(self):
        # The second argument is a base, and taking the wrapper off would
        # change what the column says rather than what type it reads as.
        self.assertIsNone(_converted_type("int($['n'], 16)"))

    def test_one_written_by_hand_ticks_its_box(self):
        self.assertEqual(_converted_type("float( $['n'] )"), 'float')

    def test_something_that_does_not_parse_converts_nothing(self):
        self.assertIsNone(_converted_type("int($['n']"))

    def test_a_splat_reads_through_the_elements_it_spread(self):
        self.assertEqual(_converted_type("*[int(x) for x in $['ns']]"), 'int')

    def test_a_comprehension_that_converts_something_else_is_not_one(self):
        self.assertIsNone(_converted_type("*[int(x['a']) for x in $['ns']]"))

    def test_a_filtered_comprehension_is_not_a_plain_conversion(self):
        self.assertIsNone(_converted_type("*[int(x) for x in $['ns'] if x]"))

    def test_a_conversion_is_not_read_through_a_star_that_is_not_there(self):
        # `[int(x) for x in ns]` as a plain column is a list per row, not a
        # column that converts -- taking the comprehension off would change
        # what the column is.
        self.assertIsNone(_converted_type('[int(x) for x in $]'))


CONVERT_LIST = [{'n': '3'}, {'n': '1'}, {'n': '2'}]


def convert_model(lst=None, columns=None, source='data', index=0):
    """A table model with a column menu and its Convert Type submenu open."""
    lst = CONVERT_LIST if lst is None else lst
    model = init_model(lst, mock_get_visualizer)
    model['columns'] = ["$['n']"] if columns is None else columns
    model['_source_expr'] = source
    model['openDropdown'] = {'id': menu_id(model, index=index)}
    model['col_search_dropdown'] = menu_id(model, 'convert', index)
    return lst, model


class ConvertPanelCase(unittest.TestCase):
    """The Convert Type submenu, opened over a one-column table."""

    def panel(self, model, lst):
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertIn('col-convert-panel', th)
        panel = th[th.index('col-convert-panel'):]
        # Convert Type's own trigger comes before its panel, so the next one
        # along is Compute's -- i.e. where this panel has finished.
        return panel[:panel.index('col-compute-trigger')]

    def rows(self, panel):
        return re.findall(r'<div class="col-compute-row[^"]*".*?'
                          r'(?=<div class="col-compute-row|$)', panel,
                          re.DOTALL)

    def names(self, panel):
        return re.findall(r'col-compute-name">([^<]*)<', panel)


class TestConvertPanelRendering(ConvertPanelCase):
    """Eight rows: four that rewrite the column, four that write another one
    beside it."""

    def test_it_lists_the_eight_rows_in_order(self):
        lst, model = convert_model()
        self.assertEqual(self.names(self.panel(model, lst)),
                         ['int', 'float', 'str', 'bool',
                          'int (new column)', 'float (new column)',
                          'str (new column)', 'bool (new column)'])

    def test_only_the_rewriting_rows_have_a_checkbox(self):
        lst, model = convert_model()
        rows = self.rows(self.panel(model, lst))
        self.assertEqual([('col-tally-check' in row) for row in rows],
                         [True] * 4 + [False] * 4)

    def test_an_unconverted_column_checks_nothing(self):
        lst, model = convert_model()
        for row in self.rows(self.panel(model, lst))[:4]:
            self.assertNotIn('checked', row)

    def test_the_type_the_column_already_reads_as_is_the_checked_row(self):
        lst, model = convert_model(columns=["int($['n'])"])
        rows = self.rows(self.panel(model, lst))
        self.assertIn('checked', rows[0])
        for row in rows[1:4]:
            self.assertNotIn('checked', row)

    def test_every_row_hands_over_the_converted_column(self):
        lst, model = convert_model()
        rows = self.rows(self.panel(model, lst))
        self.assertIn(exp_attr("[int(item['n']) for item in data]"), rows[0])
        self.assertIn(exp_attr("[str(item['n']) for item in data]"), rows[2])

    def test_the_new_column_rows_hand_over_the_same_expression(self):
        lst, model = convert_model()
        rows = self.rows(self.panel(model, lst))
        self.assertIn(exp_attr("[int(item['n']) for item in data]"), rows[4])

    def test_a_checked_row_still_names_the_column_it_describes(self):
        # The row names a type, not the click; dragging int off a column that
        # already reads as one hands over the column as it stands.
        lst, model = convert_model(columns=["int($['n'])"])
        rows = self.rows(self.panel(model, lst))
        self.assertIn(exp_attr("[int(item['n']) for item in data]"), rows[0])

    def test_a_splat_hands_over_the_elements_it_spread(self):
        # The converted column read the ordinary way -- the star's own list
        # converted, then flattened -- rather than a comprehension fused by
        # hand: what the drag hands over is what the column would BE.
        lst, model = convert_model(lst=[{'ns': ['1', '2']}],
                                   columns=["*$['ns']"])
        rows = self.rows(self.panel(model, lst))
        self.assertIn(
            exp_attr('[item3 for item in data '
                     "for item3 in [int(item2) for item2 in item['ns']]]"),
            rows[0])

    def test_every_row_hands_its_expression_out_to_the_right(self):
        # A tooltip over a menu row would otherwise cover the rows around it.
        lst, model = convert_model()
        for row in self.rows(self.panel(model, lst)):
            self.assertIn('snc-py-exp-align="right"', row)

    def test_a_list_with_no_source_has_no_expression_to_hand_over(self):
        lst, model = convert_model(source=None)
        for row in self.rows(self.panel(model, lst)):
            self.assertNotIn('snc-py-exps', row)

    def test_but_it_can_still_be_converted(self):
        # Unlike Sort, this rewrites the COLUMN rather than the line, so a list
        # with no name of its own has nothing to stop it.
        lst, model = convert_model(source=None)
        rows = self.rows(self.panel(model, lst))
        self.assertIn('ConvertTypeToggle', rows[0])
        self.assertNotIn('unselectable', rows[0])

    def test_a_column_that_is_already_there_is_not_offered_again(self):
        # Two columns would share one identity, and the second would be a cell
        # nothing could tell from the first.
        lst, model = convert_model(columns=["$['n']", "int($['n'])"])
        rows = self.rows(self.panel(model, lst))
        self.assertIn('unselectable', rows[0])
        self.assertNotIn('ConvertTypeToggle', rows[0])
        self.assertIn('unselectable', rows[4])
        self.assertNotIn('ConvertTypeColumnClick', rows[4])
        self.assertNotIn('unselectable', rows[1])

    def test_the_trigger_reads_as_a_flyout_like_sort(self):
        lst, model = convert_model()
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertIn('>Convert Type<', th)
        self.assertIn('col-convert-trigger', th)

    def test_it_sits_between_group_by_and_compute(self):
        lst, model = convert_model()
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertLess(th.index('col-group-by'), th.index('col-convert'))
        self.assertLess(th.index('col-convert'), th.index('>Compute<'))

    def test_only_the_open_submenu_draws_its_panel(self):
        lst, model = convert_model()
        model['col_search_dropdown'] = menu_id(model, 'compute')
        th = _first_column_header(
            visualize(lst, model, mock_get_visualizer,
                      lambda code: eval(code, {}, {'data': lst})))
        self.assertNotIn('col-convert-panel', th)


class ConvertEventCase(unittest.TestCase):
    def click(self, event, lst=None, **kwargs):
        lst, model = convert_model(lst, **kwargs)
        return update(make_column_mouse_event(repr(event)),
                      ('data', 'data'), model, lst, mock_get_visualizer,
                      eval_in_scope=lambda code: eval(code, {}, {'data': lst}))


class TestConvertTypeToggle(ConvertEventCase):
    """Clicking a type rewrites the column's own expression, so the cells, the
    search and everything computed off the column all read the new type."""

    def test_it_wraps_the_columns_expression(self):
        model, _ = self.click(ConvertTypeToggle(col="$['n']", to='int'))
        self.assertEqual(list(model['columns']), ["int($['n'])"])

    def test_it_writes_no_code(self):
        # A conversion is about how a column reads, not about the line.
        _, commands = self.click(ConvertTypeToggle(col="$['n']", to='int'))
        self.assertEqual(commands, [])

    def test_it_keeps_the_columns_place(self):
        model, _ = self.click(ConvertTypeToggle(col="$['b']", to='float'),
                              lst=[{'a': 1, 'b': '2', 'c': 3}],
                              columns=["$['a']", "$['b']", "$['c']"], index=1)
        self.assertEqual(list(model['columns']),
                         ["$['a']", "float($['b'])", "$['c']"])

    def test_clicking_the_checked_type_takes_the_conversion_off(self):
        model, _ = self.click(ConvertTypeToggle(col="int($['n'])", to='int'),
                              columns=["int($['n'])"])
        self.assertEqual(list(model['columns']), ["$['n']"])

    def test_another_type_replaces_rather_than_nests(self):
        model, _ = self.click(ConvertTypeToggle(col="int($['n'])", to='str'),
                              columns=["int($['n'])"])
        self.assertEqual(list(model['columns']), ["str($['n'])"])

    def test_the_menu_stays_open_on_the_column_it_renamed(self):
        # A checkbox, and picking another type is the common next act -- but the
        # column it is open on is called something else now.
        model, _ = self.click(ConvertTypeToggle(col="$['n']", to='int'))
        self.assertEqual(model['openDropdown'],
                         {'id': "col-menu-int($['n'])"})
        self.assertEqual(model['col_search_dropdown'], "convert-int($['n'])")

    def test_what_the_column_computes_follows_it_over(self):
        # The aggregations describe the column rather than filtering it.
        lst, model = convert_model()
        model['column_computes'] = {"$['n']": ['len($)']}
        model, _ = update(
            make_column_mouse_event(repr(ConvertTypeToggle(col="$['n']",
                                                           to='int'))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda code: eval(code, {}, {'data': lst}))
        self.assertEqual(_column_computes(model, "int($['n'])"), ['len($)'])

    def test_a_sub_column_converts_its_own_expression(self):
        model, _ = self.click(ConvertTypeToggle(col=f"$['p']\x01$['n']",
                                                to='int'),
                              lst=[{'p': {'n': '1'}}],
                              columns={"$['p']": {'cols': {"$['n']": {}}}})
        self.assertEqual(list(model['columns']["$['p']"]['cols']),
                         ["int($['n'])"])

    def test_a_splat_converts_the_elements_it_spread(self):
        model, _ = self.click(ConvertTypeToggle(col="*$['ns']", to='int'),
                              lst=[{'ns': ['1', '2']}], columns=["*$['ns']"])
        self.assertEqual(list(model['columns']),
                         ["*[int(item2) for item2 in $['ns']]"])

    def test_a_name_a_sibling_already_has_is_refused(self):
        model, _ = self.click(ConvertTypeToggle(col="$['n']", to='int'),
                              columns=["$['n']", "int($['n'])"])
        self.assertEqual(list(model['columns']), ["$['n']", "int($['n'])"])

    def test_a_type_it_does_not_offer_is_a_noop(self):
        model, _ = self.click(ConvertTypeToggle(col="$['n']", to='eval'))
        self.assertEqual(list(model['columns']), ["$['n']"])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        model, _ = self.click(ConvertTypeToggle(col='$.gone', to='int'))
        self.assertEqual(list(model['columns']), ["$['n']"])


class TestConvertTypeColumnClick(ConvertEventCase):
    """The other four rows add the converted column beside the original, which
    is the one thing the checkbox can't do: keep both readings on screen."""

    def test_it_adds_the_converted_column_to_the_right(self):
        model, _ = self.click(ConvertTypeColumnClick(col="$['n']", to='int'))
        self.assertEqual(list(model['columns']), ["$['n']", "int($['n'])"])

    def test_it_lands_beside_the_column_rather_than_at_the_far_right(self):
        model, _ = self.click(ConvertTypeColumnClick(col="$['a']", to='str'),
                              lst=[{'a': 1, 'b': 2}],
                              columns=["$['a']", "$['b']"], index=0)
        self.assertEqual(list(model['columns']),
                         ["$['a']", "str($['a'])", "$['b']"])

    def test_a_converted_column_converts_from_the_same_place(self):
        # Replacing rather than nesting, the way the checkboxes do.
        model, _ = self.click(ConvertTypeColumnClick(col="int($['n'])",
                                                    to='str'),
                              columns=["int($['n'])"])
        self.assertEqual(list(model['columns']),
                         ["int($['n'])", "str($['n'])"])

    def test_a_sub_columns_new_column_is_a_sub_column_beside_it(self):
        # It is written in the scope its parent hands out, so a column of the
        # table would read it against something else entirely.
        model, _ = self.click(ConvertTypeColumnClick(col=f"$['p']\x01$['n']",
                                                     to='int'),
                              lst=[{'p': {'n': '1'}}],
                              columns={"$['p']": {'cols': {"$['n']": {}}}})
        self.assertEqual(list(model['columns']["$['p']"]['cols']),
                         ["$['n']", "int($['n'])"])

    def test_the_menu_closes_behind_it(self):
        # One column written, unlike checking a box, which invites the next.
        model, _ = self.click(ConvertTypeColumnClick(col="$['n']", to='int'))
        self.assertIsNone(model['openDropdown'])
        self.assertIsNone(model['col_search_dropdown'])

    def test_a_column_that_is_already_there_is_not_added_twice(self):
        model, _ = self.click(ConvertTypeColumnClick(col="$['n']", to='int'),
                              columns=["$['n']", "int($['n'])"])
        self.assertEqual(list(model['columns']), ["$['n']", "int($['n'])"])

    def test_a_click_on_a_column_that_is_gone_is_a_noop(self):
        model, _ = self.click(ConvertTypeColumnClick(col='$.gone', to='int'))
        self.assertEqual(list(model['columns']), ["$['n']"])


class TestSourceSpanAndExprRefresh(unittest.TestCase):
    """The line can be rewritten under a model that outlives the rewrite, so
    what the model knows about it is refreshed rather than remembered."""

    def test_visualize_records_the_span_it_is_handed(self):
        lst, model = sort_model(span=None)
        visualize(lst, model, mock_get_visualizer,
                  lambda code: eval(code, {}, {'data': lst}),
                  var_and_exp=('data', 'data'), source_span=SPAN)
        self.assertEqual(model['_source_span'], SPAN)

    def test_update_records_it_too(self):
        lst, model = sort_model(span=None)
        model, _ = update(make_column_mouse_event(
            repr(SortClick(col=col_at(model), direction='asc'))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda code: eval(code, {}, {'data': lst}),
            source_span=SPAN)
        self.assertEqual(model['_source_span'], SPAN)

    def test_a_model_that_outlives_a_rewrite_reads_the_new_expression(self):
        # A bare expression statement carries its text, so sorting it changes
        # what the line says. The cells must follow, or the table would show
        # the old order against the new value.
        lst, model = sort_model(span=None, source='[3, 1, 2]')
        visualize(lst, model, mock_get_visualizer,
                  lambda code: eval(code, {}, {'data': lst}),
                  var_and_exp=(None, 'sorted([3, 1, 2])'))
        self.assertEqual(model['_source_expr'], 'sorted([3, 1, 2])')

    def test_a_named_line_keeps_its_name(self):
        lst, model = sort_model()
        visualize(lst, model, mock_get_visualizer,
                  lambda code: eval(code, {}, {'data': lst}),
                  var_and_exp=('data', 'data'))
        self.assertEqual(model['_source_expr'], 'data')

    def test_nothing_to_go_on_leaves_what_the_model_had(self):
        lst, model = sort_model()
        visualize(lst, model, mock_get_visualizer,
                  lambda code: eval(code, {}, {'data': lst}))
        self.assertEqual(model['_source_expr'], 'data')


from table_visualizer import _column_item_expr, _column_key_expr


class TestColumnDollarDollarIsTheList(unittest.TestCase):
    """A column is written in row scope, but the box says `$$` is the whole
    list -- so `$ / max($$)` is a column, and every place that reads a column or
    writes code for one has to bind it."""

    def named_source(self, lst):
        """A table over `data`, whose cells are read through the name."""
        scope = lambda code: eval(code, {}, {'data': lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=('data', 'data'))
        return model, scope

    def test_a_cell_read_through_the_source_reads_the_list_too(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        model['columns'] = ['$ * len($$)']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('>3<', out)
        self.assertIn('>6<', out)
        self.assertIn('>9<', out)

    def test_a_cell_read_off_the_row_in_hand_reads_it_as_well(self):
        # An impure source is never re-evaluated (see _is_pure_ref), so the
        # list has to come in as a value rather than as an expression.
        lst = [1, 2, 3]
        scope = lambda code: eval(code, {}, {'f': lambda: lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=(None, 'f()'))
        model['columns'] = ['$ * len($$)']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('>3<', out)
        self.assertIn('>9<', out)

    def test_with_no_scope_at_all_the_list_is_still_in_reach(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['$ * len($$)']
        out = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('>9<', out)

    def test_the_columns_values_are_gathered_over_the_list(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        self.assertEqual(_column_values('$ * len($$)', lst, model, scope),
                         [3, 6, 9])

    def test_gathered_without_a_scope_too(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(_column_values('$ * len($$)', lst, model), [3, 6, 9])

    def test_the_column_hands_over_code_that_names_the_list(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        model['columns'] = ['$ * len($$)']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('[item * len(data) for item in data]', html.unescape(out))

    def test_a_cell_hands_over_code_that_names_the_list(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        model['columns'] = ['$ * len($$)']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('child-expr=data[0] * len(data)', html.unescape(out))

    def test_the_row_expression_names_the_list_the_row_came_from(self):
        self.assertEqual(_column_item_expr('$ * len($$)', 'data'),
                         'item * len(data)')
        self.assertEqual(_column_key_expr('$ * len($$)', 'data'),
                         'item * len(data)')

    def test_a_source_that_is_not_a_name_is_parenthesized(self):
        # It is substituted into the user's own expression, so it has to bind
        # as tightly as the `$$` it stands for.
        self.assertEqual(_column_item_expr('len($$)', 'a + b'), 'len((a + b))')

    def test_sorting_by_such_a_column_names_the_list_in_the_key(self):
        self.assertEqual(_sort_expr('data', '$ / max($$)', 'asc'),
                         'sorted(data, key=lambda item: item / max(data))')

    def test_a_column_search_lifts_the_list_into_the_search_box(self):
        # In column scope $ is the value, $$ the row and $$$ the list; lifted
        # into the search box's scope the column's own $$ is already what that
        # scope calls the list.
        self.assertEqual(lift_column_predicate('$ > 2', '$ / max($$)'),
                         '($ / max($$)) > 2')


from table_visualizer import (_column_cell_expr, _column_values_clause,
                             _pick_range_expr, _render_sort_panel,
                             _agg_column_expr, _agg_col_code, _agg_row_index,
                             _pick_standalone_exprs, _ctx_to_model, unlift_term)
from table_visualizer_grammar import parse_generated_code_or_assignment


class TestColumnDollarIIsTheRowIndex(unittest.TestCase):
    """The column box says `$i` is the row's index, so `$ * $i` is a column --
    and every place that reads a column or writes code for one has to bind it.

    Unlike a dollar run, `$i` names no scope: a list has one index to give, so
    it means the same row number wherever it is written.
    """

    def named_source(self, lst):
        """A table over `data`, whose cells are read through the name."""
        scope = lambda code: eval(code, {}, {'data': lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=('data', 'data'))
        return model, scope

    # --- the four ways a cell gets read ---

    def test_a_cell_read_through_the_source_knows_its_row(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        model['columns'] = ['$ * $i']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('>0<', out)
        self.assertIn('>2<', out)
        self.assertIn('>6<', out)

    def test_a_cell_read_off_the_row_in_hand_knows_it_too(self):
        # An impure source is never re-evaluated (see _is_pure_ref), so this
        # goes through eval_dollar_expr rather than through the source name.
        lst = [1, 2, 3]
        scope = lambda code: eval(code, {}, {'f': lambda: lst})
        model = init_model(lst, mock_get_visualizer, eval_in_scope=scope,
                           var_and_exp=(None, 'f()'))
        model['columns'] = ['$ * $i']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('>2<', out)
        self.assertIn('>6<', out)

    def test_with_no_scope_at_all_the_row_number_is_still_in_reach(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        model['columns'] = ['$ * $i']
        out = visualize(lst, model, mock_get_visualizer, None)
        self.assertIn('>6<', out)

    def test_the_columns_values_are_gathered_over_the_list(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        self.assertEqual(_column_values('$ * $i', lst, model, scope), [0, 2, 6])

    def test_gathered_without_a_scope_too(self):
        lst = [1, 2, 3]
        model = init_model(lst, mock_get_visualizer)
        self.assertEqual(_column_values('$ * $i', lst, model), [0, 2, 6])

    def test_a_column_that_is_only_the_index_reads_as_the_row_numbers(self):
        lst = ['a', 'b', 'c']
        model, scope = self.named_source(lst)
        self.assertEqual(_column_values('$i', lst, model, scope), [0, 1, 2])

    # --- what it hands over ---

    def test_the_column_hands_over_code_that_counts_the_rows(self):
        self.assertEqual(_column_values_clause('$ * $i', 'data'),
                         'item * i for i, item in enumerate(data)')
        self.assertEqual(_column_values_expr('$ * $i', 'data'),
                         '[item * i for i, item in enumerate(data)]')

    def test_a_column_that_never_asks_hands_over_what_it_always_did(self):
        # The enumerate is only ever there because the column asked for it.
        self.assertEqual(_column_values_expr("$['p']", 'data'),
                         "[item['p'] for item in data]")

    def test_a_cell_names_its_own_row_number(self):
        # A cell is one row, so the index is that row's number rather than a
        # variable -- which is what makes the expression stand on its own.
        self.assertEqual(_column_cell_expr('$ * $i', 'data', 2), 'data[2] * 2')
        self.assertEqual(_column_cell_expr('$ * $i', 'data', 0), 'data[0] * 0')

    def test_a_cell_hands_over_the_code_it_was_read_through(self):
        lst = [1, 2, 3]
        model, scope = self.named_source(lst)
        model['columns'] = ['$ * $i']
        out = visualize(lst, model, mock_get_visualizer, scope)
        self.assertIn('child-expr=data[1] * 1', html.unescape(out))

    def test_the_row_expression_counts_the_rows_off(self):
        self.assertEqual(_column_item_expr('$ * $i', 'data'), 'item * i')

    # --- the search ---

    def test_a_search_on_the_index_matches_by_row_number(self):
        self.assertEqual(_get_matching_indices('$ > $i', [5, 0, 9], eval),
                         [0, 2])

    def test_a_search_without_one_is_unchanged(self):
        self.assertEqual(_get_matching_indices('$ > 1', [5, 0, 9], eval),
                         [0, 2])

    def test_a_column_search_lifts_the_index_across_untouched(self):
        # In column scope $ is the value and $$ the row, and lifting shifts
        # those out by one. The index is at neither level: it is the row number,
        # which is the same number on both sides of the lift.
        self.assertEqual(lift_column_predicate('$ > $i', "$['p']"),
                         "$['p'] > $i")

    def test_and_unlifts_back_to_exactly_what_was_written(self):
        # unlift_term only accepts a reading that lifts back verbatim, so a
        # term coming back at all is the round-trip holding.
        self.assertEqual(unlift_term("$['p'] > $i", "$['p']"), '$ > $i')

    # --- generated code ---

    def test_filtering_on_the_index_counts_the_rows_off(self):
        model = {'search': '$ > $i', 'columns': ['$']}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'),
                                  eval_in_scope=eval)
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[item for i, item in enumerate(data) if item > i]')

    def test_counting_on_the_index_does_too(self):
        model = {'search': '$ > $i', 'columns': ['$']}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'),
                                  eval_in_scope=eval)
        self.assertEqual(generate_action('count', ctx)[1],
                         'sum(1 for i, item in enumerate(data) if item > i)')

    def test_a_search_that_never_asks_generates_what_it_always_did(self):
        model = {'search': '$ > 1', 'columns': ['$']}
        ctx = _get_search_context(model, var_and_exp=('data', 'data'),
                                  eval_in_scope=eval)
        self.assertEqual(generate_action('filter', ctx)[1],
                         '[item for item in data if item > 1]')

    def picked_match(self, columns, search):
        """What one picked cell of the match row hands over, standalone."""
        data = [5, 0, 9]
        model = {'columns': columns, 'search': search, 'first_match': True,
                 'tool': 'pick', 'picked': ['match_col_0']}
        exprs = _pick_standalone_exprs(model, 'data', lambda c: eval(c, {'data': data}),
                                       ['match_col_0'])
        return exprs['match_col_0'], data

    def test_a_picked_region_binds_the_index_its_column_asked_for(self):
        # A region expression is written against the names the next(...) around
        # it binds, and the row's number is one of them.
        code, data = self.picked_match(['$ * $i'], '$ > 1')
        self.assertEqual(
            code, 'next((item * i for i, item in enumerate(data) if item > 1), None)')
        self.assertEqual(eval(code, {'data': data}), 0)

    def test_a_picked_region_counts_the_rows_off_when_the_search_asked(self):
        # The region says nothing about the index, but the predicate beside it
        # does -- and one binding serves both sides of the next(...).
        code, data = self.picked_match(['$'], '$ > $i')
        self.assertEqual(
            code, 'next((item for i, item in enumerate(data) if item > i), None)')
        self.assertEqual(eval(code, {'data': data}), 5)

    def test_a_pick_that_asks_for_neither_is_unchanged(self):
        code, _data = self.picked_match(['$'], '$ > 1')
        self.assertEqual(code, 'next((item for item in data if item > 1), None)')

    def test_a_pick_band_keeps_counting_from_where_the_band_starts(self):
        # `$i` is the row's number in the list, not its place in the band, so
        # the count starts at the band's first row.
        self.assertEqual(_pick_range_expr('col_0', ['$ * $i'], 'data', '3', None),
                         '[x * i for i, x in enumerate(data[3:], 3)]')
        self.assertEqual(_pick_range_expr('col_0', ['$ * $i'], 'data', None, '2'),
                         '[x * i for i, x in enumerate(data[:2])]')

    # --- reading the line back ---

    def read_back(self, code):
        """The search a generated line comes back as."""
        ctx, _prefix = parse_generated_code_or_assignment(code)
        self.assertIsNotNone(ctx, f'did not parse: {code}')
        model = {'columns': ['$'], 'search': None, 'pick_expr': None}
        _ctx_to_model(ctx, model)
        return model['search']

    ACTIONS = ('filter', 'count', 'any', 'all', 'if_any', 'if_all', 'delete',
               'find_indices', 'loop_no_idx', 'loop_orig_idx', 'loop_new_idx')

    def test_every_action_writes_a_line_that_reads_back_as_its_search(self):
        # The whole round trip, for a search that names the row's number and one
        # that doesn't: the second is what every line looked like before `$i`
        # existed, and has to still.
        data = [5, 0, 9]
        for search in ('$ > $i', '$ > 1'):
            for action in self.ACTIONS:
                for first in (False, True):
                    with self.subTest(search=search, action=action, first=first):
                        model = {'columns': ['$'], 'search': search,
                                 'first_match': first}
                        ctx = _get_search_context(
                            model, var_and_exp=('data', 'data'),
                            eval_in_scope=lambda c: eval(c, {'data': data}))
                        result = generate_action(action, ctx)
                        self.assertIsNotNone(result)
                        self.assertEqual(self.read_back(result[1]), search)

    def test_and_that_line_runs(self):
        data = [5, 0, 9]
        for action, want in [('filter', [5, 9]), ('count', 2),
                             ('find_indices', [0, 2]), ('any', True),
                             ('all', False), ('delete', [0])]:
            with self.subTest(action=action):
                model = {'columns': ['$'], 'search': '$ > $i',
                         'first_match': False}
                ctx = _get_search_context(
                    model, var_and_exp=('data', 'data'),
                    eval_in_scope=lambda c: eval(c, {'data': data}))
                code = generate_action(action, ctx)[1]
                self.assertEqual(eval(code, {'data': data}), want)

    def test_a_line_that_never_bound_a_row_number_keeps_its_own_i(self):
        # `i` here is a name from the user's program -- the comprehension binds
        # only the row -- so reading it as the row's number would quietly change
        # what the search asks.
        self.assertEqual(self.read_back('[item for item in data if item > i]'),
                         '$ > i')

    def test_a_line_that_does_bind_one_reads_it_as_the_row_number(self):
        self.assertEqual(
            self.read_back('[i for i, item in enumerate(data) if item > i]'),
            '$ > $i')

    # --- aggregations ---

    def test_a_column_aggregation_reads_the_column_it_always_did(self):
        self.assertEqual(_agg_column_expr('sum($)', '$ * $i', 'data'),
                         '[item * i for i, item in enumerate(data)]')

    def test_a_row_aggregation_orders_by_index_when_the_column_asks(self):
        # `lambda item:` has no row number in it, so the key runs over the row
        # numbers instead -- and the row is read back out, because an
        # aggregation answers with a row whichever way it found one.
        self.assertEqual(
            _agg_col_code(agg_named('Min Item'), '$ * $i', 'data'),
            'data[min(range(len(data)), key=lambda i: data[i] * i)]')
        self.assertEqual(_agg_column_expr(agg_named('Min Item'), '$ * $i',
                                          'data'),
                         'data[i] * i')

    def test_a_row_aggregation_over_a_plain_column_is_unchanged(self):
        self.assertEqual(_agg_column_expr(agg_named('Min Item'), "$['p']",
                                          'data'),
                         "item['p']")
        self.assertEqual(_agg_col_code(agg_named('Min Item'), "$['p']", 'data'),
                         "min(data, key=lambda item: item['p'])")

    def test_a_row_aggregation_finds_the_row_the_index_picked_out(self):
        # 3*0, 1*1, 4*2, 1*3, 5*4 -- least is row 0, greatest is row 4.
        lst = [3, 1, 4, 1, 5]
        self.assertEqual(_agg_value(agg_named('Min Item'), None, None, lst,
                                    '$ * $i'), 3)
        self.assertEqual(_agg_value(agg_named('Max Item'), None, None, lst,
                                    '$ * $i'), 5)

    def test_and_says_which_row_that_was_rather_than_the_first_equal_one(self):
        # `.index` of the row would answer with the first row equal to it, which
        # is a different row as soon as the number is part of what was compared:
        # here 1, 5, 1 keyed by $ - $i is 1, 4, -1, so the row picked is the last
        # of them and `data.index(1)` would say 0.
        lst = [1, 5, 1]
        template = agg_named('Min Item')
        self.assertEqual(_agg_row_index(lst, 1, template, '$ - $i'), 2)
        code = _agg_row_index_code(_agg_col_code(template, '$ - $i', 'data'),
                                   'data', template, '$ - $i')
        self.assertEqual(code,
                         'min(range(len(data)), key=lambda i: data[i] - i)')
        self.assertEqual(eval(code, {'data': lst}), 2)

    def test_a_plain_column_still_looks_its_row_up_the_way_it_did(self):
        lst = [{'v': 30}, {'v': 10}]
        template = agg_named('Min Item')
        self.assertEqual(_agg_row_index(lst, {'v': 10}, template, "$['v']"), 1)
        self.assertEqual(
            _agg_row_index_code("min(data, key=lambda item: item['v'])", 'data',
                                template, "$['v']"),
            "data.index(min(data, key=lambda item: item['v']))")

    # --- the one thing it can't do ---

    def test_sorting_by_such_a_column_is_not_offered(self):
        # sorted() takes a key over rows, and there is no row number inside one.
        # Rather than hand over code that won't run, the rows go inert.
        lst = [1, 2, 3]
        model, _scope = self.named_source(lst)
        model['_source_span'] = ('data', 0, 4)
        panel = _render_sort_panel('$ * $i', model)
        self.assertNotIn('snc-mouse-down', panel)
        self.assertEqual(panel.count('unselectable'), 4)

    def test_sorting_by_a_plain_column_still_is(self):
        lst = [1, 2, 3]
        model, _scope = self.named_source(lst)
        model['_source_span'] = ('data', 0, 4)
        panel = _render_sort_panel('$', model)
        self.assertIn('snc-mouse-down', panel)


# === Expand/collapse bar ===

def make_expand_toggle_event() -> dict:
    """Create an ExpandToggle event dict (a click on the expand/collapse bar)."""
    return {'pythonEventStr': repr(ExpandToggle()), 'eventJSON': {}}


def _pane_max_height(output: str) -> int:
    """How tall the table's scroll pane was allowed to get, in px."""
    style = re.search(r'<div class="list-table-scroll" style="([^"]*)"', output)[1]
    return int(re.search(r'max-height: (\d+)px', style)[1])


def _pane_min_height(output: str) -> int:
    """How tall the table's scroll pane actually asks to be, in px."""
    style = re.search(r'<div class="list-table-scroll" style="([^"]*)"', output)[1]
    return int(re.search(r'min-height: (\d+)px', style)[1])


def _expand_bar(output: str) -> str:
    """Just the expand/collapse bar, tag and all -- the readout beside it on
    the same row is its own control and carries its own attributes."""
    match = re.search(r'<div class="expand-toggle.*?</div>', output)
    return match[0] if match else ''


class TestExpandToggle(unittest.TestCase):
    """The bar under a table, which opens the pane past its collapsed ceiling."""

    # 30 rows at 18px each want more than the 368px a top-level table gets.
    TALL = list(range(30))
    SHORT = [1, 2, 3]

    def table(self, lst, model=None, **kwargs):
        if model is None:
            model = init_model(lst, mock_get_visualizer)
        return visualize(lst, model, mock_get_visualizer, None, **kwargs)

    def test_bar_is_offered_when_the_pane_clips_the_table(self):
        output = self.table(self.TALL)
        self.assertIn('expand-toggle', output)
        self.assertIn('ExpandToggle()', output)

    def test_a_table_that_the_row_count_says_fits_gets_one_anyway(self):
        # Whether it fits is worked out at 18px a row, which is a row of plain
        # cells; one holding a nested visualizer is taller. So a table this
        # arithmetic calls short can be clipping rows all the same, and
        # withholding the bar would leave nothing to open it with.
        output = self.table(self.SHORT)
        self.assertIn('expand-toggle', output)
        self.assertIn('ExpandToggle()', output)

    def test_the_bar_reports_a_click_that_flips_the_state(self):
        model = init_model(self.TALL, mock_get_visualizer)
        model, _ = update(make_expand_toggle_event(), None, model, self.TALL,
                          mock_get_visualizer)
        self.assertTrue(model['expanded'])
        model, _ = update(make_expand_toggle_event(), None, model, self.TALL,
                          mock_get_visualizer)
        self.assertFalse(model['expanded'])

    def test_expanding_lifts_the_panes_ceiling(self):
        model = init_model(self.TALL, mock_get_visualizer)
        collapsed = _pane_max_height(self.table(self.TALL, model))
        model['expanded'] = True
        self.assertGreater(_pane_max_height(self.table(self.TALL, model)), collapsed)

    def test_the_bar_says_which_way_it_goes(self):
        model = init_model(self.TALL, mock_get_visualizer)
        self.assertIn('data-tooltip="Expand"', self.table(self.TALL, model))
        model['expanded'] = True
        self.assertIn('data-tooltip="Collapse"', self.table(self.TALL, model))

    def test_an_open_bar_carries_the_class_that_turns_its_chevron(self):
        model = init_model(self.TALL, mock_get_visualizer)
        model['expanded'] = True
        self.assertIn('class="expand-toggle expanded"', self.table(self.TALL, model))

    def test_a_short_table_honours_the_flag_because_it_has_a_bar_too(self):
        # Every table carries the bar, so an expanded state on a short one is
        # one the user can always close again -- it opens rather than being
        # ignored.
        model = init_model(self.SHORT, mock_get_visualizer)
        model['expanded'] = True
        output = self.table(self.SHORT, model)
        self.assertIn('class="expand-toggle expanded"', output)
        self.assertGreater(_pane_max_height(output),
                           _pane_max_height(self.table(self.SHORT)))

    def test_opening_a_short_table_doesnt_stretch_it_to_the_new_ceiling(self):
        # The ceiling is a limit, not a height: three rows still ask for three
        # rows' worth of pane, so opening one leaves the table where it was.
        model = init_model(self.SHORT, mock_get_visualizer)
        model['expanded'] = True
        self.assertEqual(_pane_min_height(self.table(self.SHORT, model)),
                         _pane_min_height(self.table(self.SHORT)))

    def test_the_bar_is_offered_in_the_unfocused_preview_too(self):
        # Marked so the frontend toggles in place instead of pinning focus to
        # the line, and so a slipped drag isn't read as a drag of the cell.
        bar = _expand_bar(self.table(self.TALL, small=True))
        self.assertIn('snc-unfocused-clickable', bar)
        self.assertIn('draggable="false"', bar)

    def test_the_focused_bar_is_a_plain_control(self):
        # The focused visualizer dispatches its own clicks already; opting out
        # of click-to-focus there would only take a click away from the line.
        # Asked of the bar alone -- the count beside it is click-through in
        # either mode, that being all it does.
        self.assertNotIn('snc-unfocused-clickable',
                         _expand_bar(self.table(self.TALL)))

    def test_the_bar_sits_between_the_table_and_the_search_area(self):
        output = self.table(self.TALL)
        self.assertLess(output.index('</table>'), output.index('expand-toggle'))
        self.assertLess(output.index('expand-toggle'), output.index('search-div'))

    def test_a_nested_table_gets_its_own_bar_against_its_own_ceiling(self):
        # A cell is handed 80px, so a list far shorter than a top-level one is
        # already clipped there.
        lst = [{'xs': [1, 2, 3]}]
        model = init_model(lst, mock_get_visualizer)
        self.assertIn('expand-toggle', self.table(lst, model))


def _tiny_len(output: str) -> str:
    """The length readout on the expand bar, tag and all."""
    match = re.search(r'<div class="tiny-len".*?</div>', output)
    return match[0] if match else ''


class TestTinyLen(unittest.TestCase):
    """How many items the list has, at the right end of the expand bar."""

    TALL = list(range(30))
    SHORT = [1, 2, 3]

    def table(self, lst, model=None, **kwargs):
        if model is None:
            model = init_model(lst, mock_get_visualizer)
        return visualize(lst, model, mock_get_visualizer, None, **kwargs)

    def test_the_bar_says_how_many_items_there_are(self):
        self.assertIn('30 items', _tiny_len(self.table(self.TALL)))

    def test_a_short_table_counts_itself_too(self):
        # It rides the bar, and the bar is offered on every table.
        self.assertIn('3 items', _tiny_len(self.table(self.SHORT)))

    def test_the_count_hands_over_the_len_of_the_source(self):
        output = self.table(self.TALL, var_and_exp=('xs', 'xs'))
        self.assertEqual(exps_in(_tiny_len(output)), [['len(xs)']])

    def test_the_count_is_draggable_like_any_other_handle(self):
        output = self.table(self.TALL, var_and_exp=('xs', 'xs'))
        self.assertIn('draggable="true"', _tiny_len(output))

    def test_the_count_offers_nothing_without_a_source_expression(self):
        # Still shown -- the number is worth having even where there is no
        # access path to hand the editor.
        output = self.table(self.TALL)
        self.assertIn('30 items', _tiny_len(output))
        self.assertNotIn('snc-py-exps', _tiny_len(output))

    def test_a_dict_counts_its_pairs_off_the_dict(self):
        d = {str(i): i for i in range(30)}
        output = self.table(d, var_and_exp=('d', 'd'))
        self.assertIn('30 entries', _tiny_len(output))
        self.assertEqual(exps_in(_tiny_len(output)), [['len(d)']])

    def test_the_count_sits_after_the_toggle_it_shares_the_bar_with(self):
        output = self.table(self.TALL)
        self.assertIn('class="expand-and-len"', output)
        self.assertLess(output.index('expand-toggle'), output.index('tiny-len'))

    def test_the_preview_counts_too(self):
        output = self.table(self.TALL, var_and_exp=('xs', 'xs'), small=True)
        self.assertIn('30 items', _tiny_len(output))
        self.assertEqual(exps_in(_tiny_len(output)), [['len(xs)']])


# === snc-py-exps under dicts, sub-columns, splats and grouping ================

from table_visualizer import (
    _as_columns, _column_row_expr, _column_whole_expr, _column_header_exps,
    _leaf_for, _leaf_cell_expr, _leaf_cell_value, SUBCOL_SEP,
)


def leaf_at(columns, n):
    """The *n*th drawn column of a columns map written as a literal."""
    return _leaf_columns(_as_columns(columns))[n]


class TestColumnRowExpr(unittest.TestCase):
    """A column as one row reads it -- what Sort and Group By are written
    against -- or None when the target has 0..n values per row rather than
    one."""

    def test_a_plain_column_is_itself(self):
        self.assertEqual(_column_row_expr(_as_columns(['$k', '$v']), '$v'), '$v')

    def test_a_plain_column_carrying_sub_columns_is_still_itself(self):
        cols = _as_columns({"$['name']": {'cols': {'$[0]': {}}}})
        self.assertEqual(_column_row_expr(cols, "$['name']"), "$['name']")

    def test_a_sub_column_of_a_plain_column_is_the_composition(self):
        cols = _as_columns({"$['name']": {'cols': {'$[0]': {}}}})
        self.assertEqual(_column_row_expr(cols, leaf_at(cols, 0).expr),
                         "$['name'][0]")

    def test_a_splat_has_no_row_expression(self):
        self.assertIsNone(_column_row_expr(_as_columns(['*$v']), '*$v'))

    def test_a_split_splat_has_none_either(self):
        cols = _as_columns({'*$v': {'cols': {"$['who']": {}}}})
        self.assertIsNone(_column_row_expr(cols, '*$v'))

    def test_a_sub_column_of_a_splat_has_none(self):
        cols = _as_columns({'*$v': {'cols': {"$['who']": {}}}})
        self.assertIsNone(_column_row_expr(cols, leaf_at(cols, 0).expr))

    def test_a_splat_nested_under_a_plain_column_has_none(self):
        # A leading star is not enough to recognise one by: this leaf's
        # identity is "$['a']\x01*$['b']\x01$['c']", which hasn't got one.
        cols = _as_columns(
            {"$['a']": {'cols': {"*$['b']": {'cols': {"$['c']": {}}}}}})
        leaf = leaf_at(cols, 0)
        self.assertIn(SUBCOL_SEP, leaf.expr)
        self.assertFalse(leaf.expr.startswith('*'))
        self.assertIsNone(_column_row_expr(cols, leaf.expr))


class TestColumnWholeExpr(unittest.TestCase):
    """Every value a column has, for any column -- keyed on the columns rather
    than on the model, so the callers holding no model can ask it too."""

    def test_a_plain_column_is_the_ordinary_whole_column_expression(self):
        self.assertEqual(
            _column_whole_expr(_as_columns(['$v']), '$v', 'd', _binds_for({'a': 1})),
            'list(d.values())')

    def test_a_leaf_under_a_splat_is_flattened(self):
        cols = _as_columns({'*$v': {'cols': {"$['who']": {}}}})
        self.assertEqual(
            _column_whole_expr(cols, leaf_at(cols, 0).expr, 'd',
                               _binds_for({'a': 1})),
            "[item2['who'] for v in d.values() for item2 in v]")

    def test_a_sub_column_of_a_plain_column_is_its_composition(self):
        cols = _as_columns({"$['name']": {'cols': {'$[0]': {}}}})
        self.assertEqual(
            _column_whole_expr(cols, leaf_at(cols, 0).expr, 'data'),
            "[item['name'][0] for item in data]")

    def test_a_split_splat_flattens_one_level(self):
        # A split splat isn't a leaf -- its sub-columns are the drawn columns
        # -- but its header spans them, and what it spans is the elements.
        cols = _as_columns({"*$['pets']": {'cols': {"$['kind']": {}}}})
        self.assertEqual(_column_whole_expr(cols, "*$['pets']", 'data'),
                         "[item2 for item in data for item2 in item['pets']]")

    def test_a_split_splat_hands_over_what_an_unsplit_one_does(self):
        split = _as_columns({"*$['pets']": {'cols': {"$['kind']": {}}}})
        unsplit = _as_columns(["*$['pets']"])
        self.assertEqual(_column_whole_expr(split, "*$['pets']", 'data'),
                         _column_whole_expr(unsplit, "*$['pets']", 'data'))


class TestSplatHeadersOfferBothReadings(unittest.TestCase):
    """A splat spread a list into rows, so its column and every sub-column
    under it read two ways: flattened, which is what is drawn, and as lists,
    which is what each root row actually holds."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'pets': [{'kind': 'rat'}]}]

    def exps(self, columns, col):
        return _column_header_exps(_as_columns(columns), col, 'data')

    def header_handle(self, columns, label):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(columns)
        out = visualize(self.DATA, model, mock_get_visualizer, None,
                        var_and_exp=('data', 'data'))
        for handle in handles_in(out):
            if handle[0]['expr'].startswith(label):
                return handle
        self.fail(f'no handle offering {label}')

    def test_a_split_splat_is_flattened_then_as_lists(self):
        exps = self.exps({"*$['pets']": {'cols': {"$['kind']": {}}}},
                         "*$['pets']")
        self.assertEqual(
            [(e.expr, e.label) for e in exps],
            [("[item2 for item in data for item2 in item['pets']]", 'Flattened'),
             ("[item['pets'] for item in data]", 'As lists')])

    def test_a_splat_drawing_its_own_column_reads_both_ways_too(self):
        # The cells are the elements, but the list each row holds is no less
        # real for not being drawn -- and it is the shape the column came from.
        self.assertEqual(
            [(e.expr, e.label) for e in self.exps({"*$['pets']": {}},
                                                  "*$['pets']")],
            [("[item2 for item in data for item2 in item['pets']]", 'Flattened'),
             ("[item['pets'] for item in data]", 'As lists')])

    def test_a_splat_reads_the_same_way_split_or_not(self):
        split = self.exps({"*$['pets']": {'cols': {"$['kind']": {}}}},
                          "*$['pets']")
        unsplit = self.exps({"*$['pets']": {}}, "*$['pets']")
        self.assertEqual([(e.expr, e.label) for e in split],
                         [(e.expr, e.label) for e in unsplit])

    def test_a_sub_column_as_lists_is_one_list_per_ROOT_row(self):
        columns = {"*$['pets']": {'cols': {"$['kind']": {}}}}
        leaf = leaf_at(columns, 0)
        self.assertEqual(
            [(e.expr, e.label) for e in self.exps(columns, leaf.expr)],
            [("[item2['kind'] for item in data for item2 in item['pets']]",
              'Flattened'),
             ("[[item2['kind'] for item2 in item['pets']] for item in data]",
              'As lists')])

    def test_both_readings_run_and_agree(self):
        columns = {"*$['pets']": {'cols': {"$['kind']": {}}}}
        for col in ("*$['pets']", leaf_at(columns, 0).expr):
            with self.subTest(col=col):
                flat, lists = self.exps(columns, col)
                scope = {'data': self.DATA}
                self.assertEqual(
                    eval(flat.expr, scope),
                    [v for group in eval(lists.expr, scope) for v in group])

    def test_a_nested_splat_reads_as_the_lists_one_level_out(self):
        columns = {"*$['members']": {'cols': {"*$['scores']": {}}}}
        self.assertEqual(
            [(e.expr, e.label) for e in
             self.exps(columns, SUBCOL_SEP.join(["*$['members']",
                                                 "*$['scores']"]))],
            [("[item3 for item in data for item2 in item['members'] "
              "for item3 in item2['scores']]", 'Flattened'),
             ("[item2['scores'] for item in data for item2 in item['members']]",
              'As lists')])

    def test_a_plain_column_reads_one_way_and_says_nothing(self):
        exps = self.exps({"$['pets']": {}}, "$['pets']")
        self.assertEqual([(e.expr, e.label) for e in exps],
                         [("[item['pets'] for item in data]", None)])

    def test_a_sub_column_of_a_plain_column_reads_one_way(self):
        columns = {"$['name']": {'cols': {'$[0]': {}}}}
        exps = self.exps(columns, leaf_at(columns, 0).expr)
        self.assertEqual(len(exps), 1)
        self.assertIsNone(exps[0].label)

    def test_the_rendered_header_carries_both(self):
        handle = self.header_handle({"*$['pets']": {}}, '[item2 for')
        self.assertEqual([entry.get('label') for entry in handle],
                         ['Flattened', 'As lists'])


class TestDictOfListsReading(unittest.TestCase):
    """A splat over a DICT spread lists that had keys, and the keys are on the
    screen -- so the column reads a third way, as the dict it came from."""

    DATA = {'ann': [{'n': 1}, {'n': 2}], 'bob': [{'n': 3}]}
    COLS = {'*$v': {'cols': {"$['n']": {}}}}

    def exps(self, col, columns=None, source='d', data=None):
        columns = self.COLS if columns is None else columns
        return _column_header_exps(_as_columns(columns), col, source,
                                   _binds_for(self.DATA if data is None else data))

    def test_the_splat_header_reads_three_ways(self):
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps('*$v')],
            [('Flattened', '[item2 for v in d.values() for item2 in v]'),
             ('As lists', 'list(d.values())'),
             ('Dict of lists', '{k: v for k, v in d.items()}')])

    def test_a_sub_column_reads_three_ways(self):
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps(leaf_at(self.COLS, 0).expr)],
            [('Flattened', "[item2['n'] for v in d.values() for item2 in v]"),
             ('As lists', "[[item2['n'] for item2 in v] for v in d.values()]"),
             ('Dict of lists',
              "{k: [item2['n'] for item2 in v] for k, v in d.items()}")])

    def test_the_dict_reading_keeps_the_keys_and_the_values(self):
        for col in ('*$v', leaf_at(self.COLS, 0).expr):
            with self.subTest(col=col):
                flat, lists, as_dict = self.exps(col)
                scope = {'d': self.DATA}
                self.assertEqual(list(eval(as_dict.expr, scope)),
                                 list(self.DATA))
                self.assertEqual(list(eval(as_dict.expr, scope).values()),
                                 eval(lists.expr, scope))
                self.assertEqual(
                    [v for group in eval(as_dict.expr, scope).values()
                     for v in group],
                    eval(flat.expr, scope))

    def test_a_list_root_has_no_keys_to_read_by(self):
        columns = {"*$['pets']": {'cols': {"$['kind']": {}}}}
        data = [{'pets': [{'kind': 'cat'}]}]
        for col in ("*$['pets']", leaf_at(columns, 0).expr):
            with self.subTest(col=col):
                exps = self.exps(col, columns, 'data', data)
                self.assertEqual([e.label for e in exps],
                                 ['Flattened', 'As lists'])

    def test_a_column_nothing_spread_reads_as_a_list_or_a_dict(self):
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps('$v', {'$v': {}})],
            [('List', 'list(d.values())'),
             ('Dict', '{k: v for k, v in d.items()}')])

    def test_a_column_the_user_wrote_reads_both_ways_too(self):
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps('sorted($v)',
                                                  {'sorted($v)': {}})],
            [('List', '[sorted(v) for v in d.values()]'),
             ('Dict', '{k: sorted(v) for k, v in d.items()}')])

    def test_a_sub_column_of_a_plain_column_reads_both_ways(self):
        columns = {'$v': {'cols': {'$[0]': {}}}}
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps(leaf_at(columns, 0).expr,
                                                  columns)],
            [('List', '[v[0] for v in d.values()]'),
             ('Dict', '{k: v[0] for k, v in d.items()}')])

    def test_the_keys_alone_have_nothing_to_key_by(self):
        # `{k: k for k, v in d.items()}` is the keys twice -- a reading that
        # says nothing the list of them doesn't. Anything READ off the key is
        # another matter, and keeps both.
        self.assertEqual([e.label for e in self.exps('$k', {'$k': {}})], [None])
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps('$k.upper()',
                                                  {'$k.upper()': {}})],
            [('List', '[k.upper() for k in d]'),
             ('Dict', '{k: k.upper() for k, v in d.items()}')])

    def test_a_nested_splat_keys_by_the_ROOT_key(self):
        # The dict's keys are the only keys there are: the inner level has
        # none, so it stays a list inside the value.
        columns = {'*$v': {'cols': {"*$['scores']": {}}}}
        col = SUBCOL_SEP.join(['*$v', "*$['scores']"])
        self.assertEqual(
            [(e.label, e.expr) for e in self.exps(col, columns)][2],
            ('Dict of lists',
             "{k: [item2['scores'] for item2 in v] for k, v in d.items()}"))


class TestSplatElementNamesDontShadow(unittest.TestCase):
    """A column expression can be a comprehension of its own -- a sub-column
    moved out of a splat is exactly that -- so the element name steps down a
    level rather than binding a name the same line already binds."""

    # `*[float(item2[5]) for item2 in $v]`: a splat of a promoted sub-column.
    COL = "*[float(item2[5]) for item2 in $v]"
    DATA = {'a': [[0, 1, 2, 3, 4, '8.0'], [0, 1, 2, 3, 4, '1.5']],
            'b': [[0, 1, 2, 3, 4, '7.0']]}

    def test_the_flattened_form_binds_a_free_name(self):
        code = _leaf_values_expr(leaf_at({self.COL: {}}, 0), 'd',
                                 _binds_for(self.DATA))
        self.assertEqual(
            code,
            "[item3 for v in d.values() for item3 in "
            "[float(item2[5]) for item2 in v]]")
        self.assertEqual(eval(code, {'d': self.DATA}), [8.0, 1.5, 7.0])

    def test_one_group_of_it_binds_no_name_at_all(self):
        # A splat showing its own elements IS its group, so the per-group answer
        # asks after the list itself rather than spreading it into a name that
        # could clash with the one the column already binds.
        code = _group_agg_column(leaf_at({self.COL: {}}, 0), 'sum($)')
        self.assertEqual(code, 'sum([float(item2[5]) for item2 in $v])')
        self.assertEqual(
            eval(_column_values_expr(code, 'd', _binds_for(self.DATA)),
                 {'d': self.DATA}),
            [9.5, 7.0])

    def test_promoting_out_of_a_splat_does_not_reuse_the_subs_own_name(self):
        # The sub is a comprehension already binding `item2`, so the list it is
        # applied across cannot bind that name as well.
        self.assertEqual(
            _promote_expr('[float(item2[5]) for item2 in $]', '*$v'),
            '[[float(item2[5]) for item2 in item3] for item3 in $v]')


class TestNestedSplatFlattening(unittest.TestCase):
    """A leaf two splats deep flattens BOTH of them: one `for` clause per
    splat in the chain, each written against the element above it."""

    def test_a_splat_inside_a_splat_flattens_both(self):
        cols = _as_columns({'*$v': {'cols': {"*$['scores']": {}}}})
        self.assertEqual(
            _leaf_values_expr(leaf_at(cols, 0), 'd', _binds_for({'a': 1})),
            "[item3 for v in d.values() for item2 in v for item3 in item2['scores']]")

    def test_a_sub_column_of_the_inner_splat_reads_off_its_element(self):
        cols = _as_columns({"*$['members']":
                            {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}})
        self.assertEqual(
            _leaf_values_expr(leaf_at(cols, 0), 'data'),
            "[item3['n'] for item in data for item2 in item['members'] "
            "for item3 in item2['scores']]")

    def test_the_depth_one_expression_is_the_one_it_always_was(self):
        cols = _as_columns({'*$v': {'cols': {"$['who']": {}}}})
        self.assertEqual(
            _leaf_values_expr(leaf_at(cols, 0), 'd', _binds_for({'a': 1})),
            "[item2['who'] for v in d.values() for item2 in v]")

    def test_it_runs_and_answers_the_leaves(self):
        data = [{'members': [{'scores': [{'n': 1}, {'n': 2}]}]},
                {'members': [{'scores': [{'n': 3}]}]}]
        cols = _as_columns({"*$['members']":
                            {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}})
        code = _leaf_values_expr(leaf_at(cols, 0), 'data')
        self.assertEqual(eval(code, {'data': data}), [1, 2, 3])

    def test_a_bare_splat_inside_a_bare_splat_is_not_silently_short(self):
        # The one that was wrong in VALUES rather than only in code: this
        # expression ran, and answered the inner lists instead of what is on
        # the screen, so the tally and every aggregation showed wrong numbers.
        data = [[[1, 2], [3]], [[4]]]
        cols = _as_columns({'*$': {'cols': {'*$': {}}}})
        code = _leaf_values_expr(leaf_at(cols, 0), 'data')
        self.assertEqual(eval(code, {'data': data}), [1, 2, 3, 4])

    def test_the_code_and_the_cells_agree(self):
        data = [{'members': [{'scores': [{'n': 1}, {'n': 2}]}]},
                {'members': [{'scores': [{'n': 3}]}]}]
        model = init_model(data, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(
            {"*$['members']": {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}})
        leaf = _leaf_columns(model['columns'])[0]
        self.assertEqual(_leaf_values(leaf, data, model, lambda c: eval(c, {'data': data})),
                         [1, 2, 3])


class TestSplatSubColumnCellExpressions(unittest.TestCase):
    """A cell under a splat names the ELEMENT it is showing -- and, when the
    splat carries sub-columns, the sub-column read off that element."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'pets': [{'kind': 'rat'}]}]
    COLS = {"*$['pets']": {'cols': {"$['kind']": {}}}}

    def model(self, columns=None, data=None):
        data = self.DATA if data is None else data
        model = init_model(data, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS if columns is None else columns)
        return model

    def row(self, key, columns=None, data=None):
        data = self.DATA if data is None else data
        cols = _as_columns(self.COLS if columns is None else columns)
        return next(r for r in _rows(data, cols) if r.key == key)

    def test_a_sub_column_cell_names_its_element(self):
        cols = _as_columns(self.COLS)
        self.assertEqual(
            _leaf_cell_expr(_leaf_columns(cols)[0], 'data',
                            self.row('0.1'), self.DATA),
            "data[0]['pets'][1]['kind']")

    def test_a_splat_with_no_sub_columns_names_the_element_itself(self):
        cols = _as_columns(["*$['pets']"])
        self.assertEqual(
            _leaf_cell_expr(_leaf_columns(cols)[0], 'data',
                            self.row('1.0', cols), self.DATA),
            "data[1]['pets'][0]")

    def test_a_leaf_two_splats_deep_is_subscripted_twice(self):
        data = [{'members': [{'scores': [{'n': 1}, {'n': 2}]}]}]
        cols = _as_columns({"*$['members']":
                            {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}})
        self.assertEqual(
            _leaf_cell_expr(_leaf_columns(cols)[0], 'data',
                            self.row('0.0.1', cols, data), data),
            "data[0]['members'][0]['scores'][1]['n']")

    def test_the_expression_evaluates_to_what_the_cell_shows(self):
        cols = _as_columns(self.COLS)
        leaf = _leaf_columns(cols)[0]
        for key, shown in (('0.0', 'cat'), ('0.1', 'dog'), ('1.0', 'rat')):
            with self.subTest(key=key):
                row = self.row(key)
                code = _leaf_cell_expr(leaf, 'data', row, self.DATA)
                self.assertEqual(eval(code, {'data': self.DATA}), shown)
                self.assertEqual(
                    _leaf_cell_value(leaf, row, self.DATA), shown)

    def test_a_dict_row_is_addressed_by_key(self):
        d = {'ann': [{'kind': 'cat'}]}
        cols = _as_columns({'*$v': {'cols': {"$['kind']": {}}}})
        code = _leaf_cell_expr(_leaf_columns(cols)[0], 'd',
                               self.row('0.0', cols, d), d)
        self.assertEqual(code, "d['ann'][0]['kind']")
        self.assertEqual(eval(code, {'d': d}), 'cat')

    def test_no_composed_identity_reaches_the_editor(self):
        out = visualize(self.DATA, self.model(), mock_get_visualizer, None,
                        var_and_exp=('data', 'data'))
        self.assertNotIn(SUBCOL_SEP, out)
        self.assertNotIn('\\u0001', out)

    def test_every_cell_hands_over_something_that_runs(self):
        out = visualize(self.DATA, self.model(), mock_get_visualizer,
                        lambda c: eval(c, {'data': self.DATA}),
                        var_and_exp=('data', 'data'))
        offered = {e['expr'] for handle in handles_in(out) for e in handle}
        self.assertIn("data[0]['pets'][1]['kind']", offered)
        for code in offered:
            with self.subTest(code=code):
                # Some handles offer a template to insert rather than a value
                # to evaluate; every one of them is still Python.
                ast.parse(code)
                try:
                    tree = ast.parse(code, mode='eval')
                except SyntaxError:
                    continue
                eval(compile(tree, '<test>', 'eval'), {'data': self.DATA})


class TestSplatSubColumnChildEvents(unittest.TestCase):
    """A child visualizer inside a splat's sub-column is fed the value it is
    actually showing -- the composed identity is a key, not an expression."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]}]
    COLS = {"*$['pets']": {'cols': {"$['kind']": {}}}}

    def model(self):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS)
        return model

    def leaf_key(self, row_key):
        cols = _as_columns(self.COLS)
        return f'{row_key}{CELL_KEY_SEP}{_leaf_columns(cols)[0].expr}'

    def test_the_getter_answers_with_the_element_read(self):
        model = self.model()
        for row_key, shown in (('0.0', 'cat'), ('0.1', 'dog')):
            with self.subTest(row_key=row_key):
                self.assertEqual(
                    _table_child_value_getter(self.leaf_key(row_key),
                                              self.DATA, model),
                    shown)

    def test_a_sub_column_of_a_plain_column_is_read_through_its_parent(self):
        data = [{'name': 'ann'}]
        model = init_model(data, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['columns'] = _as_columns({"$['name']": {'cols': {'$[0]': {}}}})
        key = f'0{CELL_KEY_SEP}{_leaf_columns(model["columns"])[0].expr}'
        self.assertEqual(_table_child_value_getter(key, data, model), 'a')


class CellCodeVisualizer:
    """A child that answers every event with both a line of generated code and
    a clipboard copy, so a test can watch both forms the parent rebinds."""
    def can_visualize(self, value):
        return True
    def get_fields(self, value):
        return None
    def init_model(self, value, get_visualizer=None, eval_in_scope=None,
                   var_and_exp=None, **kwargs):
        return {'handledKeys': []}
    def visualize(self, value, model, get_visualizer, eval_in_scope=None,
                  max_width=None, max_height=None, small=False, var_and_exp=None):
        return f'<span>{html.escape(repr(value))}</span>'
    def update(self, event, var_and_exp, model, value, get_visualizer=None,
               eval_in_scope=None):
        return (model, [('x', f'{CHILD_SOURCE_BINDER}.upper()'),
                        CopyToClipboard(text=f'{CHILD_SOURCE_BINDER}.upper()')])


_cell_code_vis = CellCodeVisualizer()


def get_visualizer_cell_code(value):
    """Tables for containers, the code-emitting child for everything else."""
    if isinstance(value, (list, dict)):
        return _mock_table_vis
    return _cell_code_vis


class TestCodeOutOfASplatCell(unittest.TestCase):
    """Code made in a cell under a splat is written against the ELEMENT, so it
    goes back in as a sub-column of that splat -- and the clipboard form of it
    names the element concretely."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]}]
    COLS = {"*$['pets']": {'cols': {"$['kind']": {}}}}

    def fire(self, columns, row_key, leaf_n=0, data=None):
        data = self.DATA if data is None else data
        cols = _as_columns(columns)
        model = init_model(data, get_visualizer_cell_code,
                           var_and_exp=('data', 'data'))
        model['columns'] = cols
        key = f'{row_key}{CELL_KEY_SEP}{_leaf_columns(cols)[leaf_n].expr}'
        ev = make_child_mouse_event(key, 'lambda ev: None')
        # The first mousedown on an unfocused cell only pins focus to it.
        model, _ = update(ev, ('data', 'data'), model, data,
                          get_visualizer_cell_code)
        return update(ev, ('data', 'data'), model, data,
                      get_visualizer_cell_code)

    def test_the_clipboard_form_names_the_element(self):
        _model, commands = self.fire(self.COLS, '0.1')
        texts = [c.text for c in commands if isinstance(c, CopyToClipboard)]
        self.assertEqual(texts, ["(data[0]['pets'][1]['kind']).upper()"])
        self.assertEqual(eval(texts[0], {'data': self.DATA}), 'DOG')

    def test_the_new_column_lands_under_the_splat_it_was_made_in(self):
        model, _commands = self.fire(self.COLS, '0.1')
        subs = _col_subs(model['columns'], "*$['pets']")
        self.assertIn("($['kind']).upper()", subs)
        self.assertNotIn("($['kind']).upper()", model['columns'])

    def test_a_splat_drawing_its_own_column_grows_a_sub_column(self):
        # The cell is one element, so what the code is generic over is the
        # elements -- which is a sub-column, not a column of the table.
        model, _commands = self.fire({"*$['pets']": {}}, '0.1',
                                     data=[{'pets': ['cat', 'dog']}])
        self.assertIn('($).upper()', _col_subs(model['columns'], "*$['pets']"))

    def test_no_composed_identity_becomes_a_column(self):
        model, _commands = self.fire(self.COLS, '0.1')
        self.assertFalse([c for c in model['columns'] if SUBCOL_SEP in c])

    def test_a_plain_column_still_gets_a_row_generic_column_of_the_table(self):
        data = [{'name': 'ann'}, {'name': 'bo'}]
        model, _commands = self.fire({"$['name']": {}}, '0', data=data)
        self.assertIn("($['name']).upper()", model['columns'])

    def test_a_sub_column_of_a_plain_column_composes_through_its_parent(self):
        data = [{'name': 'ann'}]
        model, _commands = self.fire({"$['name']": {'cols': {'$[0]': {}}}}, '0',
                                     data=data)
        self.assertIn("($['name'][0]).upper()", model['columns'])


from table_visualizer import _render_sort_panel, _render_column_group_by


class TestRowScopedOpsGoInert(unittest.TestCase):
    """Sort and Group By order and cut up ROWS, and a splat column has no one
    value per row to do either by -- so every row of them goes inert there,
    rather than handing over code that cannot run."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}], 'name': 'ann'}]
    SPLAT = {"*$['pets']": {'cols': {"$['kind']": {}}}}

    def model(self, columns):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(columns)
        model['_source_expr'] = 'data'
        model['_source_span'] = ('data', 1, 0, 1, 4)
        return model

    def targets(self, columns):
        return _menu_targets(_as_columns(columns))

    def test_group_by_is_inert_on_a_splat_and_on_its_sub_columns(self):
        model = self.model(self.SPLAT)
        for target in self.targets(self.SPLAT):
            with self.subTest(target=target):
                row = _render_column_group_by(target, model)
                self.assertIn('unselectable', row)
                self.assertNotIn('snc-py-exps', row)
                self.assertNotIn('GroupByClick', row)

    def test_group_by_still_writes_a_line_for_a_plain_column(self):
        row = _render_column_group_by("$['name']", self.model({"$['name']": {}}))
        self.assertNotIn('unselectable', row)
        self.assertIn('GroupByClick', row)

    def test_group_by_on_a_sub_column_names_the_composition(self):
        cols = {"$['pets']": {'cols': {'len($)': {}}}}
        model = self.model(cols)
        row = _render_column_group_by(leaf_at(cols, 0).expr, model)
        self.assertEqual(exps_in(row), [
            ["(_d := {}, [_d.setdefault(len(item['pets']), [])"
             ".append(item) for item in data])[0]"]])

    def test_every_sort_row_is_inert_on_a_splat(self):
        model = self.model(self.SPLAT)
        for target in self.targets(self.SPLAT):
            with self.subTest(target=target):
                panel = _render_sort_panel(target, model)
                self.assertEqual(panel.count('unselectable'), 4)
                self.assertNotIn('snc-py-exps', panel)
                self.assertNotIn('SortClick', panel)
                self.assertNotIn('SortCodeClick', panel)

    def test_sort_by_a_sub_column_orders_by_the_composition(self):
        cols = {"$['pets']": {'cols': {'len($)': {}}}}
        panel = _render_sort_panel(leaf_at(cols, 0).expr, self.model(cols))
        self.assertEqual(
            exps_in(panel)[0],
            ["sorted(data, key=lambda item: len(item['pets']))"])

    def test_a_click_on_a_splat_writes_nothing(self):
        model = self.model(self.SPLAT)
        for event in (GroupByClick(col="*$['pets']"),
                      SortClick(col="*$['pets']", direction='asc'),
                      SortCodeClick(col="*$['pets']", direction='asc')):
            with self.subTest(event=event):
                _model, commands = update(
                    make_column_mouse_event(repr(event)), ('data', 'data'),
                    self.model(self.SPLAT), self.DATA, mock_get_visualizer,
                    eval_in_scope=lambda c: eval(c, {}, {'data': self.DATA}))
                self.assertEqual(commands, [])

    def test_a_click_on_a_sub_column_writes_the_composition(self):
        cols = {"$['pets']": {'cols': {'len($)': {}}}}
        _model, commands = update(
            make_column_mouse_event(repr(GroupByClick(col=leaf_at(cols, 0).expr))),
            ('data', 'data'), self.model(cols), self.DATA, mock_get_visualizer,
            eval_in_scope=lambda c: eval(c, {}, {'data': self.DATA}))
        self.assertEqual(
            commands[0][1],
            "(_d := {}, [_d.setdefault(len(item['pets']), [])"
            ".append(item) for item in data])[0]")


from table_visualizer import (
    _render_column_tally, _recompose_search, _apply_search_to_columns,
    _set_column_search, _tally_counter_expr, _tally_row_count_expr,
)


class TestTallyOnLeafColumns(unittest.TestCase):
    """A tally summarises what the column SHOWS, so its code has to read the
    same values -- through the leaf for a sub-column, flat for a splat."""

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'pets': [{'kind': 'cat'}]}]
    COLS = {"*$['pets']": {'cols': {"$['kind']": {}}}}

    def model(self, columns=None, data=None):
        data = self.DATA if data is None else data
        model = init_model(data, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS if columns is None else columns)
        model['_source_expr'] = 'data'
        return model

    def panel(self, col, columns=None, data=None):
        data = self.DATA if data is None else data
        return _render_column_tally(col, self.model(columns, data), data,
                                    lambda c: eval(c, {'data': data}))

    def test_the_counter_reads_a_sub_column_flat(self):
        cols = _as_columns(self.COLS)
        self.assertEqual(
            _tally_counter_expr(leaf_at(cols, 0).expr, 'data', columns=cols),
            "Counter([item2['kind'] for item in data for item2 in item['pets']])")

    def test_a_dict_column_binds_its_key(self):
        # The binds were dropped on the way in, so this said `$k for item in d`
        # -- a column expression left half-substituted, which is not Python.
        self.assertEqual(
            _tally_counter_expr('$k', 'd', _binds_for({'a': 1}),
                                _as_columns(['$k'])),
            'Counter(k for k in d)')

    def test_the_headers_hand_over_code_that_runs(self):
        panel = self.panel(leaf_at(_as_columns(self.COLS), 0).expr)
        offered = [e for handle in handles_in(panel) for e in handle]
        self.assertTrue(offered)
        for entry in offered:
            with self.subTest(expr=entry['expr']):
                scope = {'data': self.DATA}
                for line in entry.get('imports', ()):
                    exec(line, scope)
                eval(entry['expr'], scope)

    def test_a_row_count_on_a_splat_counts_what_the_row_shows(self):
        # The tally of a splat column counts ELEMENTS -- the rows it spread
        # into -- so the number's own code counts the same things.
        cols = _as_columns(self.COLS)
        code = _tally_row_count_expr(leaf_at(cols, 0).expr, 'data', "'cat'",
                                     self.DATA, columns=cols)
        self.assertEqual(eval(code, {'data': self.DATA}), 2)

    def test_a_splat_column_cannot_be_filtered_by_its_tally(self):
        # Checking one would compose `*$['pets'] == 'cat'`, which matches no
        # rows and quietly empties the table.
        panel = self.panel("*$['pets']", {"*$['pets']": {}},
                           [{'pets': ['cat', 'dog']}, {'pets': ['cat']}])
        self.assertNotIn('TallyItemToggle', panel)
        self.assertNotIn('TallySelectAll', panel)
        self.assertIn('unselectable', panel)

    def test_a_plain_column_still_filters(self):
        panel = self.panel("$['b']", {"$['b']": {}},
                           [{'b': 1}, {'b': 2}])
        self.assertIn('TallyItemToggle', panel)
        self.assertIn('TallySelectAll', panel)


class TestColumnSearchInLeafSpace(unittest.TestCase):
    """A search is stored under the target it was typed on, and lifted through
    the expression that target reads by -- so a sub-column's box filters."""

    DATA = [{'name': 'ann', 'pets': [{'kind': 'cat'}]},
            {'name': 'bo', 'pets': [{'kind': 'dog'}]}]
    COLS = {"$['name']": {'cols': {'$[0]': {}}},
            "*$['pets']": {'cols': {"$['kind']": {}}}}

    def model(self):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS)
        model['_source_expr'] = 'data'
        return model

    def test_a_sub_columns_search_composes_through_its_parent(self):
        model = self.model()
        _set_column_search(model, leaf_at(self.COLS, 0).expr,
                           op='==', text="'a'", compose='and')
        _recompose_search(model)
        self.assertEqual(model['search'], "$['name'][0] == 'a'")

    def test_it_reads_back_onto_the_sub_column(self):
        model = self.model()
        model['search'] = "$['name'][0] == 'a'"
        _apply_search_to_columns(model)
        self.assertEqual(list(model['column_searches'] or {}),
                         [leaf_at(self.COLS, 0).expr])

    def test_it_filters_the_table(self):
        model = self.model()
        _set_column_search(model, leaf_at(self.COLS, 0).expr,
                           op='==', text="'a'", compose='and')
        _recompose_search(model)
        self.assertEqual(
            _get_matching_indices(model['search'], self.DATA,
                                  lambda c: eval(c, {'data': self.DATA})),
            [0])

    def test_a_splat_column_writes_no_search(self):
        model = self.model()
        _set_column_search(model, "*$['pets']", op='==', text="'cat'",
                           compose='and')
        _recompose_search(model)
        self.assertIsNone(model['search'])


from table_visualizer import (
    _render_compute_panel, _render_agg_rows, _agg_col_code, _leaf_row_expr,
    _agg_row_index,
)


def agg_foot(html_str):
    """The <tfoot> of answers under a table, or ''."""
    m = re.search(r'<tfoot.*?</tfoot>', html_str, re.DOTALL)
    return m.group(0) if m else ''


class TestDictAggregationExpressions(unittest.TestCase):
    """A dict's aggregations show the right number, so the code beside them has
    to name the same values -- with the dict's own bindings substituted."""

    D = {'a': 1, 'b': 2, 'c': 3}

    def model(self, columns=('$k', '$v'), computes=None, value=None):
        value = self.D if value is None else value
        model = init_model(value, mock_get_visualizer_dict_tables,
                           var_and_exp=('d', 'd'))
        model['columns'] = _as_columns(list(columns))
        model['_source_expr'] = 'd'
        for col, exprs in (computes or {}).items():
            _set_column_computes(model, col, exprs)
        return model

    def render(self, model, value=None):
        value = self.D if value is None else value
        return visualize(value, model, mock_get_visualizer_dict_tables,
                         lambda c: eval(c, {'d': value}),
                         var_and_exp=('d', 'd'))

    def test_a_sum_cell_names_the_dicts_values(self):
        out = self.render(self.model(computes={'$v': ['sum($)']}))
        self.assertIn(['sum(list(d.values()))'], exps_in(agg_foot(out)))

    def test_the_compute_menu_row_says_the_same(self):
        panel = _render_compute_panel('$v', self.model(), self.D,
                                      lambda c: eval(c, {'d': self.D}))
        self.assertIn(['sum(list(d.values()))'], exps_in(panel))

    def test_unique_writes_a_line_that_names_the_values(self):
        panel = _render_compute_panel('$v', self.model(), self.D,
                                      lambda c: eval(c, {'d': self.D}))
        self.assertIn(['set(list(d.values()))'], exps_in(panel))

    def test_every_expression_the_panel_offers_runs(self):
        panel = _render_compute_panel('$v', self.model(), self.D,
                                      lambda c: eval(c, {'d': self.D}))
        for entry in [e for h in handles_in(panel) for e in h]:
            with self.subTest(expr=entry['expr']):
                scope = {'d': self.D}
                for line in entry.get('imports', ()):
                    exec(line, scope)
                if 'counts, edges' in entry['expr']:
                    exec(entry['expr'], scope)   # the histogram writes a line
                else:
                    eval(entry['expr'], scope)

    def test_min_item_draws_a_row_with_its_index_and_its_values(self):
        out = self.render(self.model(computes={'$v': [ROW_AGGS[0]]}))
        foot = agg_foot(out)
        self.assertIn('col-agg-item-row', foot)
        # 'a' is the smallest value's key, and it is row 0.
        self.assertIn('>a<', foot)
        offered = exps_in(foot)
        # The index beside the row, then the row itself, then each column of
        # it -- read off the pair the aggregation picked rather than off `$k`
        # and `$v`, which name nothing outside a comprehension over the dict.
        self.assertEqual(offered, [
            ['list(d.items()).index(min(d.items(), key=lambda item: item[1]))'],
            ['min(d.items(), key=lambda item: item[1])'],
            ['min(d.items(), key=lambda item: item[1])[0]'],
            ['min(d.items(), key=lambda item: item[1])[1]']])
        for entry in offered:
            self.assertEqual(eval(entry[0], {'d': self.D}),
                             {0: 0, 1: ('a', 1), 2: 'a', 3: 1}[offered.index(entry)])

    def test_min_item_finds_the_row_number_of_a_dict(self):
        # dicts have no `.index`, so this answered NO_ANSWER and the row drew
        # with no index at all.
        self.assertEqual(_agg_row_index(self.D, ('b', 2)), 1)


class TestSplatAggregationExpressions(unittest.TestCase):
    """An aggregation over a splat column summarises the flattened values, so
    the code beside it says so too."""

    DATA = [{'pets': [{'n': 1}, {'n': 2}]}, {'pets': [{'n': 3}]}]
    COLS = {"*$['pets']": {'cols': {"$['n']": {}}}}

    def model(self, computes=None):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS)
        model['_source_expr'] = 'data'
        for col, exprs in (computes or {}).items():
            _set_column_computes(model, col, exprs)
        return model

    def leaf(self):
        return leaf_at(self.COLS, 0).expr

    def test_a_sum_over_a_sub_column_is_flattened(self):
        self.assertEqual(
            _agg_col_code('sum($)', self.leaf(), 'data',
                          columns=_as_columns(self.COLS)),
            "sum([item2['n'] for item in data for item2 in item['pets']])")

    def test_the_cell_under_the_column_says_the_same(self):
        out = visualize(self.DATA, self.model(computes={self.leaf(): ['sum($)']}),
                        mock_get_visualizer, lambda c: eval(c, {'data': self.DATA}),
                        var_and_exp=('data', 'data'))
        foot = agg_foot(out)
        self.assertIn(["sum([item2['n'] for item in data for item2 in item['pets']])"],
                      exps_in(foot))
        self.assertIn('>6<', foot)

    def test_a_row_aggregation_is_not_offered_on_a_splat(self):
        # Min Item picks a ROW; a splat column's rows are its own elements.
        self.assertIsNone(_agg_col_code(ROW_AGGS[0], self.leaf(), 'data',
                                        columns=_as_columns(self.COLS)))

    def test_a_splat_column_reads_as_a_list_per_root_row(self):
        cols = _as_columns(self.COLS)
        self.assertEqual(_leaf_row_expr(_leaf_columns(cols)[0]),
                         "[item2['n'] for item2 in $['pets']]")


class TestLeafSpaceLayout(unittest.TestCase):
    """The body draws one cell per LEAF, so the rows of answers under it have
    to as well -- otherwise an answer lands under the wrong column, or never
    renders at all."""

    DATA = [{'name': 'ann', 'pets': [{'n': 1}, {'n': 2}]},
            {'name': 'bo', 'pets': [{'n': 3}]}]
    COLS = {"$['name']": {}, "*$['pets']": {'cols': {"$['n']": {}}}}

    def model(self, computes=None):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS)
        model['_source_expr'] = 'data'
        for col, exprs in (computes or {}).items():
            _set_column_computes(model, col, exprs)
        return model

    def render(self, model):
        return visualize(self.DATA, model, mock_get_visualizer,
                         lambda c: eval(c, {'data': self.DATA}),
                         var_and_exp=('data', 'data'))

    def leaf(self, n):
        return leaf_at(self.COLS, n).expr

    def test_an_aggregation_on_a_sub_column_renders_at_all(self):
        out = self.render(self.model(computes={self.leaf(1): ['sum($)']}))
        self.assertIn('col-agg-cell', agg_foot(out))

    def test_the_answer_row_is_as_wide_as_a_body_row(self):
        out = self.render(self.model(computes={self.leaf(1): ['sum($)']}))
        foot = agg_foot(out)
        # The index CELL, not the `$i` header over it -- a header row has no
        # <td> in it to count.
        body_row = re.search(r'<tr>(?:(?!</tr>).)*<td class="row-index"'
                             r'(?:(?!</tr>).)*</tr>', out, re.DOTALL).group(0)
        self.assertEqual(len(re.findall(r'<td', foot)),
                         len(re.findall(r'<td', body_row)))

    def test_the_answer_sits_under_the_column_that_asked(self):
        out = self.render(self.model(computes={self.leaf(1): ['sum($)']}))
        cells = re.findall(r'<td[^>]*>.*?(?=<td|</tr>)', agg_foot(out), re.DOTALL)
        # index cell, the name column's blank, then the sub-column's answer.
        self.assertEqual(len(cells), 3)
        self.assertIn('col-agg-blank', cells[1])
        self.assertIn('>6<', cells[2])

    def test_a_row_aggregation_draws_one_cell_per_leaf(self):
        out = self.render(self.model(computes={self.leaf(0): [ROW_AGGS[0]]}))
        row = re.search(r'<tr class="col-agg-row col-agg-item-row">.*?</tr>',
                        agg_foot(out), re.DOTALL).group(0)
        self.assertEqual(len(re.findall(r'<td', row)), 3)

    def test_a_splat_leaf_in_a_row_aggregation_shows_that_rows_values(self):
        out = self.render(self.model(computes={self.leaf(0): [ROW_AGGS[0]]}))
        row = re.search(r'<tr class="col-agg-row col-agg-item-row">.*?</tr>',
                        agg_foot(out), re.DOTALL).group(0)
        offered = {e['expr'] for h in handles_in(row) for e in h}
        self.assertIn(
            "[item2['n'] for item2 in min(data, key=lambda item: item['name'])['pets']]",
            offered)


from table_visualizer import _pick_column_ids, _pick_column_expr


class TestPickRegionsInLeafSpace(unittest.TestCase):
    """The overlays are drawn over the DRAWN columns, so the ids that name them
    are counted the same way."""

    COLS = {"$['name']": {'cols': {'$[0]': {}}},
            "*$['pets']": {'cols': {"$['n']": {}}}}

    def test_ids_are_counted_off_the_drawn_columns(self):
        # Two top-level columns, two leaves -- and only the first is pickable.
        self.assertEqual(_pick_column_ids(_as_columns(self.COLS)),
                         ['idx', 'col_0'])

    def test_a_flat_table_is_unchanged(self):
        self.assertEqual(_pick_column_ids(_as_columns(['$k', '$v'])),
                         ['idx', 'col_0', 'col_1'])

    def test_an_id_reads_as_the_column_it_is_drawn_over(self):
        self.assertEqual(_pick_column_expr('col_0', _as_columns(self.COLS)),
                         "$['name'][0]")

    def test_a_splat_column_offers_no_expression(self):
        # A band is a run of ROWS; a splat column's rows are its own elements.
        self.assertIsNone(_pick_column_expr('col_1', _as_columns(self.COLS)))

    def test_an_id_past_the_end_is_no_column(self):
        self.assertIsNone(_pick_column_expr('col_9', _as_columns(self.COLS)))

    def test_no_overlay_is_drawn_for_an_id_that_is_not_offered(self):
        data = [{'name': 'ann', 'pets': [{'n': 1}]},
                {'name': 'bo', 'pets': [{'n': 2}]}]
        model = init_model(data, mock_get_visualizer, var_and_exp=('data', 'data'))
        model['columns'] = _as_columns(self.COLS)
        model['_source_expr'] = 'data'
        model['search'] = "$['name'] == 'bo'"
        model['tool'] = 'pick'
        out = visualize(data, model, mock_get_visualizer,
                        lambda c: eval(c, {'data': data}),
                        var_and_exp=('data', 'data'))
        drawn = set(re.findall(r'PickToggle\(region_id=&#x27;'
                               r'(?:pre|match|post)_(col_\d+)&#x27;\)', out))
        self.assertEqual(drawn, {'col_0'})


from table_visualizer import (
    _group_agg_column, _group_agg_columns, _group_agg_template,
    _leaf_splat_target, _parse_agg_child_key, _column_header_exps,
    _column_cell_expr, _column_values_expr, code_imports,
    _add_group_agg_column, _leaf_for,
)
from table_visualizer import _sort_key_expr, _DICT_BINDS


class TestGroupAggregationExpressions(unittest.TestCase):
    """A per-group answer is one value per group, and a group is a row of this
    table -- so the expression is an ordinary column expression, written in the
    scope that row is read in."""

    DATA = [{'pets': [{'n': 1}, {'n': 2}]}, {'pets': [{'n': 3}]}]
    COLS = {"*$['pets']": {'cols': {"$['n']": {}}}}
    NESTED = {"*$['members']": {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}}
    NESTED_DATA = [{'members': [{'scores': [{'n': 1}, {'n': 2}]},
                                {'scores': [{'n': 3}]}]}]

    def test_the_group_is_the_list_the_splat_spread(self):
        leaf = leaf_at(self.COLS, 0)
        self.assertEqual(_group_agg_column(leaf, 'sum($)'),
                         "sum([item2['n'] for item2 in $['pets']])")

    def test_it_answers_once_per_group(self):
        leaf = leaf_at(self.COLS, 0)
        expr = _group_agg_column(leaf, 'sum($)')
        self.assertEqual(
            eval(_column_values_expr(expr, 'data'), {'data': self.DATA}),
            [3, 3])

    def test_a_dict_roots_groups_are_its_values(self):
        d = {'ann': [{'n': 1}], 'bob': [{'n': 2}, {'n': 3}]}
        cols = _as_columns({'*$v': {'cols': {"$['n']": {}}}})
        expr = _group_agg_column(_leaf_columns(cols)[0], 'sum($)')
        self.assertEqual(expr, "sum([item2['n'] for item2 in $v])")
        self.assertEqual(
            eval(_column_values_expr(expr, 'd', _binds_for(d)), {'d': d}),
            [1, 5])

    def test_a_leaf_two_splats_deep_asks_after_its_innermost_group(self):
        # The innermost group is one member's scores, so the answer is written
        # against the member -- which is the row it will be a column of.
        leaf = leaf_at(self.NESTED, 0)
        self.assertEqual(_group_agg_column(leaf, 'sum($)'),
                         "sum([item3['n'] for item3 in $['scores']])")

    def test_it_goes_in_beside_the_splat_it_is_about(self):
        self.assertEqual(_leaf_splat_target(leaf_at(self.COLS, 0)),
                         "*$['pets']")
        self.assertEqual(_leaf_splat_target(leaf_at(self.NESTED, 0)),
                         f"*$['members']{SUBCOL_SEP}*$['scores']")

    def test_a_leaf_no_splat_spread_has_no_group_to_ask_after(self):
        cols = _as_columns({"$['n']": {}})
        self.assertIsNone(_group_agg_column(_leaf_columns(cols)[0], 'sum($)'))
        self.assertIsNone(_leaf_splat_target(_leaf_columns(cols)[0]))

    def test_the_columns_beside_a_splat_say_which_rows_wrote_them(self):
        cols = _as_columns(self.COLS)
        leaf = _leaf_columns(cols)[0]
        cols[_group_agg_column(leaf, 'min($)')] = {}
        cols['len($)'] = {}
        self.assertEqual(_group_agg_columns(cols, leaf),
                         {"min([item2['n'] for item2 in $['pets']])": 'min($)'})


class TestGroupAggregationHandles(unittest.TestCase):
    """What a per-group answer hands to the editor: nothing of its own. It is a
    column, so its header and its cells hand over what every column's do."""

    DATA = [{'pets': [{'n': 1}, {'n': 2}]}, {'pets': [{'n': 3}]}]
    COLS = {"*$['pets']": {'cols': {"$['n']": {}}}}

    def cols_with(self, template='sum($)', columns=None, data=None):
        cols = _as_columns(copy.deepcopy(columns or self.COLS))
        leaf = _leaf_columns(cols)[0]
        cols[_group_agg_column(leaf, template)] = {}
        return cols

    def render(self, columns, data, var='data'):
        model = init_model(data, mock_get_visualizer, var_and_exp=(var, var))
        model['columns'] = columns
        model['_source_expr'] = var
        return visualize(data, model, mock_get_visualizer,
                         lambda c: eval(c, {var: data}),
                         var_and_exp=(var, var))

    def test_the_header_hands_over_every_groups_answer(self):
        cols = self.cols_with()
        expr = list(cols)[-1]
        [exp] = _column_header_exps(cols, expr, 'data')
        self.assertEqual(exp.expr,
                         "[sum([item2['n'] for item2 in item['pets']]) "
                         "for item in data]")
        self.assertEqual(eval(exp.expr, {'data': self.DATA}), [3, 3])

    def test_a_dict_root_hands_over_the_keyed_reading_too(self):
        d = {'ann': [{'n': 1}, {'n': 2}], 'bob': [{'n': 3}]}
        cols = self.cols_with(columns={'*$v': {'cols': {"$['n']": {}}}})
        expr = list(cols)[-1]
        exps = _column_header_exps(cols, expr, 'd', _binds_for(d))
        self.assertEqual([e.label for e in exps], ['List', 'Dict'])
        self.assertEqual(eval(exps[1].expr, {'d': d}), {'ann': 3, 'bob': 3})

    def test_a_cell_names_its_own_group(self):
        cols = self.cols_with()
        code = _column_cell_expr(list(cols)[-1], 'data', 0)
        self.assertEqual(code, "sum([item2['n'] for item2 in data[0]['pets']])")
        self.assertEqual(eval(code, {'data': self.DATA}), 3)

    def test_the_row_handle_carries_it_beside_the_rest(self):
        out = self.render(self.cols_with(), self.DATA)
        handed = [e for handle in exps_in(out) for e in handle]
        self.assertTrue(
            any("sum([item2['n'] for item2 in data[0]['pets']])" in e
                for e in handed), handed)

    def test_the_aggregations_imports_come_along(self):
        # Off the text, the way every composed expression's are: a column is
        # code the table hands out rather than a line it declares.
        cols = self.cols_with('np.mean($)')
        [exp] = _column_header_exps(cols, list(cols)[-1], 'data')
        self.assertEqual(code_imports(exp.expr), ('import numpy as np',))

    def test_no_answer_is_a_child_of_the_column_that_asked(self):
        # Only the whole-column answers under the table are; a per-group one is
        # an ordinary cell, and its child key is an ordinary cell key.
        out = self.render(self.cols_with(), self.DATA)
        self.assertNotIn('group-agg', out)
        self.assertIsNone(_parse_agg_child_key(
            f"0{CELL_KEY_SEP}sum([item2['n'] for item2 in $['pets']])"))


class TestInnermostGroupAggregations(unittest.TestCase):
    """A leaf nested two splats deep answers about its INNERMOST group, so its
    answer is a sub-column of the outer splat rather than a column of the
    table."""

    COLS = {"$['who']": {},
            "*$['members']": {'cols': {"$['name']": {},
                                       "*$['scores']": {'cols': {"$['n']": {}}}}}}
    DATA = [{'who': 'ann',
             'members': [{'name': 'x', 'scores': [{'n': 1}, {'n': 2}]},
                         {'name': 'y', 'scores': [{'n': 3}]}]}]

    def columns(self):
        cols = _as_columns(copy.deepcopy(self.COLS))
        leaf = _leaf_columns(cols)[2]
        subs = _col_subs(cols, "*$['members']")
        _col_add(subs, _group_agg_column(leaf, 'sum($)'))
        return cols

    def render(self):
        model = init_model(self.DATA, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = self.columns()
        model['_source_expr'] = 'data'
        return visualize(self.DATA, model, mock_get_visualizer,
                         lambda c: eval(c, {'data': self.DATA}),
                         var_and_exp=('data', 'data'))

    def test_the_answer_is_drawn_at_the_outer_splats_depth(self):
        added = _leaf_columns(self.columns())[-1]
        self.assertEqual(added.depth, 1)
        self.assertEqual(added.splat, "*$['members']")

    def test_one_answer_per_inner_group(self):
        out = self.render()
        # x's scores are 1 + 2, y's is 3 -- one cell each, not one per score.
        self.assertEqual(len(re.findall(r'>3<', out)), 3)  # y's n, and both 3s

    def test_a_column_spans_only_its_own_group_now(self):
        # No rows of answers are hung inside the groups, so nothing has to reach
        # across them: the row covers its 3 rendered rows and the member its 2.
        out = self.render()
        body = out[out.index('</tr>', out.index('col-subheader')):]
        self.assertIn('rowspan="3"', body)
        self.assertIn('rowspan="2"', body)
        self.assertNotIn('rowspan="5"', body)

    def test_no_rows_of_answers_are_drawn_at_all(self):
        self.assertNotIn('group-agg', self.render())


# === Everything the table hands to the editor, evaluated =====================

from table_visualizer import _menu_id, AGG_KEY_SEP


# What a column that can't answer the question raises, as opposed to what code
# built wrong raises. The line this test draws is between the two: a NameError
# or a SyntaxError means the expression itself is broken.
_UNANSWERABLE = (TypeError, ValueError, KeyError, IndexError, AttributeError,
                 ZeroDivisionError, ArithmeticError)


def _handle_tree(code):
    """The handle's code as an expression to evaluate, or None when it is a
    template to INSERT -- a loop to write the body of, an `if any(...)`, the
    line numpy's histogram is always written as.

    Either way it has to be Python: a `*` sigil or a composed identity that
    leaked into generated code parses as neither, which is the point.
    """
    try:
        return ast.parse(code, mode='eval')
    except SyntaxError:
        ast.parse(code)   # a statement, then -- but still Python
        return None


class TestEveryExpressionTheTableHandsOver(unittest.TestCase):
    """The audit this whole change came out of, as a test.

    Render each shape the table can be in, read back every expression it offers
    the editor -- cells, headers, menu rows, answers, action buttons -- and run
    each one against the very scope it names. A `*` or a composed identity that
    leaks into generated code stops being a thing to notice and becomes a
    failure here.
    """

    # (name, value, columns) -- a shape per row of the audit.
    SHAPES = (
        ('list of dicts', [{'b': 3, 'c': 'x'}, {'b': 1, 'c': 'y'}],
         ["$['b']", "$['c']"]),
        ('dict root', {'a': 1, 'b': 2}, ['$k', '$v']),
        ('dict of lists', {'a': [1, 2], 'b': [3]}, ['$k', 'len($v)']),
        ('splat, no sub-columns', [{'pets': ['cat', 'dog']}, {'pets': ['rat']}],
         {"*$['pets']": {}}),
        ('splat with sub-columns',
         [{'pets': [{'kind': 'cat', 'n': 1}]}, {'pets': [{'kind': 'rat', 'n': 2}]}],
         {"$['pets']": {}, "*$['pets']": {'cols': {"$['kind']": {}, "$['n']": {}}}}),
        ('dict of lists, splatted',
         {'a': [{'n': 1}, {'n': 2}], 'b': [{'n': 3}]},
         {'$k': {}, '*$v': {'cols': {"$['n']": {}}}}),
        ('plain column with sub-columns', [{'name': 'ann'}, {'name': 'bo'}],
         {"$['name']": {'cols': {'$[0]': {}, 'len($)': {}}}}),
        ('nested splat',
         [{'members': [{'scores': [{'n': 1}, {'n': 2}]}, {'scores': [{'n': 3}]}]}],
         {"*$['members']": {'cols': {"*$['scores']": {'cols': {"$['n']": {}}}}}}),
    )

    def model_for(self, value, columns, name):
        gv = mock_get_visualizer_dict_tables
        model = init_model(value, gv, var_and_exp=(name, name))
        model['columns'] = _as_columns(columns)
        model['_source_expr'] = name
        model['_source_span'] = (name, 1, 0, 1, len(name))
        return model

    def check(self, out, scope, label):
        """Every entry of every handle in *out*, run against *scope*."""
        entries = [e for handle in handles_in(out) for e in handle]
        self.assertTrue(entries, f'{label}: nothing offered')
        for entry in entries:
            with self.subTest(shape=label, expr=entry['expr']):
                code = entry['expr']
                self.assertNotIn(SUBCOL_SEP, code)
                self.assertNotIn(AGG_KEY_SEP, code)
                run = dict(scope)
                # Each entry declares what it needs, so a missing declaration
                # is a failure here rather than something an allowlist hides.
                for line in entry.get('imports', ()):
                    exec(line, run)
                tree = _handle_tree(code)
                if tree is None:
                    continue
                try:
                    eval(compile(tree, '<handle>', 'eval'), run)
                except _UNANSWERABLE:
                    # A question this data can't answer -- summing strings, a
                    # set of dicts. The menu offers those rows whatever is in
                    # the column, and what they write is still the right code
                    # for what was asked. A NameError or a SyntaxError is not
                    # in that class, and is what this test is looking for.
                    pass

    def render(self, value, columns, name, **model_fields):
        gv = mock_get_visualizer_dict_tables
        model = self.model_for(value, columns, name)
        model.update(model_fields)
        return visualize(value, model, gv, lambda c: eval(c, {name: value}),
                         var_and_exp=(name, name)), model

    def test_every_shape_hands_over_code_that_runs(self):
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            out, _model = self.render(value, columns, name)
            self.check(out, {name: value}, label)

    def test_with_a_search_a_tally_and_the_menus_open(self):
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            model = self.model_for(value, columns, name)
            targets = _menu_targets(model['columns'])
            for target in targets:
                for kind in (None, 'sort', 'compute', 'subcols'):
                    fields = {'openDropdown': {'id': _menu_id('col-menu', target)}}
                    if kind:
                        fields['col_search_dropdown'] = _menu_id(kind, target)
                    out, _m = self.render(value, columns, name, **fields)
                    self.check(out, {name: value}, f'{label} / {target!r} / {kind}')

    def test_with_the_row_menu_open_on_every_row(self):
        # The row handles are drawn whatever else is; the menu's own rows are
        # only there while it is open, so every row gets opened in turn.
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            for i in range(len(value)):
                out, _m = self.render(
                    value, columns, name,
                    openDropdown={'id': _menu_id('row-menu', str(i))})
                self.check(out, {name: value}, f'{label} / row {i}')

    def test_with_an_aggregation_on_every_column(self):
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            model = self.model_for(value, columns, name)
            for target in _menu_targets(model['columns']):
                for template in ('sum($)', 'len(set($))', ROW_AGGS[0]):
                    model = self.model_for(value, columns, name)
                    _set_column_computes(model, target, [template])
                    out = visualize(value, model, mock_get_visualizer_dict_tables,
                                    lambda c: eval(c, {name: value}),
                                    var_and_exp=(name, name))
                    self.check(out, {name: value},
                               f'{label} / {target!r} / {template}')

    def test_with_a_per_group_aggregation_on_every_splat_column(self):
        # Written the way the box writes it, so what this runs is what a click
        # would have put there -- and a column, so every handle in the table
        # sees it, not just the cells it made.
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            base = self.model_for(value, columns, name)
            for expr in [lf.expr for lf in _leaf_columns(base['columns'])]:
                for template in ('sum($)', ROW_AGGS[0],
                                 'np.percentile($, {{50}})'):
                    model = self.model_for(value, columns, name)
                    leaf = _leaf_for(model['columns'], expr)
                    if leaf is None or _group_agg_column(leaf, template) is None:
                        continue
                    self.assertTrue(
                        _add_group_agg_column(model, leaf, template))
                    out = visualize(value, model,
                                    mock_get_visualizer_dict_tables,
                                    lambda c: eval(c, {name: value}),
                                    var_and_exp=(name, name))
                    self.check(out, {name: value},
                               f'{label} / {expr!r} / {template} / group')

    def test_with_a_column_search_written_on_every_column(self):
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            base = self.model_for(value, columns, name)
            for target in _menu_targets(base['columns']):
                model = self.model_for(value, columns, name)
                _set_column_search(model, target, op='==', text='1',
                                   compose='and')
                _recompose_search(model, lambda c: eval(c, {name: value}))
                out = visualize(value, model, mock_get_visualizer_dict_tables,
                                lambda c: eval(c, {name: value}),
                                var_and_exp=(name, name))
                self.check(out, {name: value}, f'{label} / {target!r} / search')

    def test_the_separators_never_reach_the_output_at_all(self):
        # Not just inside a handle: an identity anywhere in the markup would
        # come back on the next event as a column nothing can read.
        for label, value, columns in self.SHAPES:
            name = 'd' if isinstance(value, dict) else 'data'
            out, _model = self.render(value, columns, name)
            with self.subTest(shape=label):
                self.assertNotIn(SUBCOL_SEP, out)
                self.assertNotIn(AGG_KEY_SEP, out)


# === What each box says its dollars mean =====================================
#
# Every box the user writes Python into binds the dollars to a scope of its own,
# and the legend on it is the only place that scope is written down. So the
# legend is asked of the same thing the box is: what a dict binds is not what a
# list binds, and what a sub-column of a splat binds is not what a sub-column of
# a plain column binds.

from table_visualizer import (
    JOIN_SEP_TOOLTIP, _leaf_cell_expr, _leaf_cell_value, _leaf_values,
    _column_search_scope, _row_scope, _sigil_dollars, _subcol_binds,
    _subcol_scope, _SIGIL_LABELS, _DICT_BINDS, _LIST_BINDS,
    _binds_for, _column_dollars, _is_dict_binds, _agg_code,
)


def box_tooltip(html_str, needle):
    """The data-tooltip on the box whose tag holds *needle*."""
    for tag in re.findall(r'<input[^>]*>', html_str):
        if needle in tag:
            tip = re.search(r'data-tooltip="([^"]*)"', tag)
            return html.unescape(tip.group(1)) if tip else None
    raise AssertionError(f'no box holding {needle!r}')


class DollarLegendCase(unittest.TestCase):
    """A table over a list and the same table over a dict, rendered far enough
    for the boxes to be on screen."""

    LIST = [{'n': 1}, {'n': 2}]
    DICT = {'a': 1, 'b': 2}

    def render(self, value, *, menu=False, submenu=None, adding=False):
        name = 'd' if isinstance(value, dict) else 'data'
        model = init_model(value, mock_get_visualizer, var_and_exp=(name, name))
        model['_source_expr'] = name
        if menu or submenu:
            model['openDropdown'] = {'id': menu_id(model)}
        if submenu:
            model['col_search_dropdown'] = menu_id(model, submenu)
        if adding:
            model['adding_column'] = True
        return visualize(value, model, mock_get_visualizer,
                         lambda c: eval(c, {name: value}),
                         var_and_exp=(name, name))


class TestRowScopeLegend(DollarLegendCase):
    """The main search box and the Column code box are asked the same thing of
    the same scope -- one row, and which row it is -- so they say it the same
    way. A dict's row is the pair its .items() gives, and the halves have names
    of their own."""

    def test_a_list_says_what_it_always_said(self):
        self.assertEqual(box_tooltip(self.render(self.LIST), 'placeholder="Search"'),
                         _row_scope(_LIST_BINDS, 'data').legend)

    def test_a_dict_says_the_row_is_a_pair(self):
        self.assertEqual(box_tooltip(self.render(self.DICT), 'placeholder="Search"'),
                         _row_scope(_DICT_BINDS, 'd').legend)

    def test_a_dict_names_the_key_and_the_value(self):
        # The two tokens a user reaching into a dict actually wants, and the two
        # the list wording has no room for.
        legend = box_tooltip(self.render(self.DICT), 'placeholder="Search"')
        self.assertIn('$k', legend)
        self.assertIn('$v', legend)

    def test_the_column_code_box_speaks_the_same_scope(self):
        for value, expected in ((self.LIST, _row_scope(_LIST_BINDS, 'data').legend),
                                (self.DICT, _row_scope(_DICT_BINDS, 'd').legend)):
            with self.subTest(dict=isinstance(value, dict)):
                out = self.render(value, adding=True)
                self.assertEqual(box_tooltip(out, 'placeholder="Column code"'),
                                 expected)

    def test_a_dict_counts_entries_rather_than_rows(self):
        # One entry occupies as many rendered rows as its splat spreads it
        # into, so "row number" would name something `$i` isn't.
        for legend in (_row_scope(_DICT_BINDS).legend, _column_search_scope(_DICT_BINDS).legend):
            with self.subTest(legend=legend):
                self.assertIn('$i the entry number', legend)
                self.assertNotIn('row number', legend)


class TestEditingAColumnLegend(unittest.TestCase):
    """Double-clicking a header opens the Column code box on that column. A
    top-level column is written in row scope; a SUB-column is written in the
    scope its parent hands out, which is what its own Subcolumns box promises.
    """

    DATA = [{'pets': [{'kind': 'cat'}, {'kind': 'dog'}]}]
    COLS = {'*$["pets"]': {'cols': {'$["kind"]': {}}}}
    SPLAT = '*$["pets"]'
    SUB = '*$["pets"]' + SUBCOL_SEP + '$["kind"]'

    def editing(self, target, value=None, columns=None):
        value = self.DATA if value is None else value
        name = 'd' if isinstance(value, dict) else 'data'
        ev = lambda c: eval(c, {name: value})
        model = init_model(value, mock_get_visualizer, var_and_exp=(name, name))
        model['columns'] = self.COLS if columns is None else columns
        model['_source_expr'] = name
        model['editing_column'] = target
        model['column_input_value'] = (
            target.split(SUBCOL_SEP, 1)[1] if SUBCOL_SEP in target else target)
        out = visualize(value, model, mock_get_visualizer, ev,
                        var_and_exp=(name, name))
        return box_tooltip(out, 'col-input')

    def test_a_top_level_column_keeps_the_row_legend(self):
        self.assertEqual(self.editing(self.SPLAT),
                         _row_scope(_LIST_BINDS, 'data').legend)

    def test_a_sub_column_speaks_its_parents_scope(self):
        # `$["kind"]` is written against one element of the splat, which is
        # exactly what the splat's own Subcolumns box promises.
        self.assertEqual(self.editing(self.SUB),
                         _subcol_scope(self.SPLAT, _LIST_BINDS).legend)

    def test_editing_a_sub_column_names_the_group_position(self):
        # The box the sub-column was WRITTEN in lists `$j`; the box it is EDITED
        # in has to list it too, or the same text reads as two different scopes.
        self.assertIn('$j', self.editing(self.SUB))

    def test_a_nested_plain_sub_column_speaks_its_parents_scope_too(self):
        columns = {'$["a"]': {'cols': {'$[0]': {}}}}
        legend = self.editing('$["a"]' + SUBCOL_SEP + '$[0]',
                              value=[{'a': 'xy'}], columns=columns)
        self.assertEqual(legend, _subcol_scope('$["a"]', _LIST_BINDS).legend)
        self.assertNotIn('$j', legend)


class TestColumnSearchLegend(DollarLegendCase):
    """A column search is written one level in from the row: $ is the column's
    value, so every other run is one deeper than the main box's."""

    def test_a_list_says_what_it_always_said(self):
        out = self.render(self.LIST, menu=True)
        self.assertEqual(box_tooltip(out, 'col-search-input'),
                         _column_search_scope(_LIST_BINDS).legend)

    def test_a_dict_names_the_key_and_the_value_here_too(self):
        out = self.render(self.DICT, menu=True)
        self.assertEqual(box_tooltip(out, 'col-search-input'),
                         _column_search_scope(_DICT_BINDS).legend)
        self.assertIn('$k', _column_search_scope(_DICT_BINDS).legend)
        self.assertIn('$v', _column_search_scope(_DICT_BINDS).legend)

    def test_the_dict_legend_does_not_call_the_row_a_list_item(self):
        # $$ is the pair for a dict, not "the original list item".
        self.assertNotIn('list item', _column_search_scope(_DICT_BINDS).legend)


class TestAggregationLegend(DollarLegendCase):
    """An aggregation is asked of the whole column at once, so there is no one
    item to name -- only what the column came out of."""

    def test_a_list_says_what_it_always_said(self):
        out = self.render(self.LIST, submenu='compute')
        self.assertEqual(box_tooltip(out, 'placeholder="Add aggregation"'),
                         _compute_scope(_LIST_BINDS).legend)

    def test_a_dict_names_a_dict(self):
        out = self.render(self.DICT, submenu='compute')
        self.assertEqual(box_tooltip(out, 'placeholder="Add aggregation"'),
                         _compute_scope(_DICT_BINDS).legend)

    def test_the_cell_label_says_the_same_thing_the_menu_did(self):
        # The box that labels a free-form aggregation's cell is the same box
        # under another name, so it cannot say a different scope.
        name = 'd'
        model = init_model(self.DICT, mock_get_visualizer, var_and_exp=(name, name))
        model['_source_expr'] = name
        _set_column_computes(model, col_at(model), ['sorted($)[0]'])
        out = visualize(self.DICT, model, mock_get_visualizer,
                        lambda c: eval(c, {name: self.DICT}),
                        var_and_exp=(name, name))
        self.assertEqual(box_tooltip(out, 'col-agg-expr'),
                         _compute_scope(_DICT_BINDS).legend)


class TestSubcolLegend(SubcolPanelCase):
    """A sub-column's scope is a fact about where its box sits, and the box sits
    in four places. Each is checked against what the leaf under it actually
    resolves to -- see TestSubcolLegendMatchesTheCells below."""

    ORGS = [{'name': 'acme', 'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'name': 'globex', 'pets': [{'kind': 'fish'}]}]
    SPLAT = '*$["pets"]'
    UNDER_SPLAT = '*$["pets"]' + SUBCOL_SEP + '$["kind"]'

    def test_the_box_carries_the_legend_for_where_it_sits(self):
        panel = self.panel(self.model())
        self.assertEqual(box_tooltip(panel, 'placeholder="Add subcolumn"'),
                         _subcol_scope(self.SPLIT, _LIST_BINDS).legend)

    def test_a_top_level_plain_column_calls_the_outer_run_the_row(self):
        legend = _subcol_scope(self.SPLIT, _LIST_BINDS).legend
        self.assertEqual(legend,
                         "$ is this column's value, $i the row number, "
                         '$$ the row')

    def test_a_splat_calls_the_outer_run_the_whole_list(self):
        # It resolves to the source expression, not to the row -- the defect
        # this legend had.
        legend = _subcol_scope(self.SPLAT, _LIST_BINDS).legend
        self.assertEqual(legend,
                         '$ is one item of the column, $j its position in the '
                         'group, $i the row number, $$ the whole list')
        self.assertNotIn('$$ the row', legend)

    def test_a_sub_of_a_sub_names_what_it_was_read_off(self):
        # Neither the row nor the whole list: `_compose_sub` binds the outer run
        # to whatever the parent column reads.
        legend = _subcol_scope("$['a']" + SUBCOL_SEP + '$[0]', _LIST_BINDS).legend
        self.assertEqual(legend,
                         "$ is this column's value, $i the row number, "
                         '$$ the value it was read off')

    def test_a_plain_sub_under_a_splat_still_names_the_group_position(self):
        # $j is bound wherever a splat is above, not only where the box sits on
        # the splat itself.
        legend = _subcol_scope(self.UNDER_SPLAT, _LIST_BINDS).legend
        self.assertEqual(legend,
                         "$ is this column's value, $j its position in the "
                         'group, $i the row number, $$ the value it was read '
                         'off')

    def test_nothing_without_a_splat_above_it_names_a_group_position(self):
        for col in (self.SPLIT, "$['a']" + SUBCOL_SEP + '$[0]'):
            with self.subTest(col=col):
                self.assertNotIn('$j', _subcol_scope(col, _LIST_BINDS).legend)

    def test_a_splat_nested_under_a_plain_column_reads_as_a_splat(self):
        # Its composed key leads with the plain parent, so there is no star at
        # the front to recognise it by.
        legend = _subcol_scope("$['pets']" + SUBCOL_SEP + '*$', _LIST_BINDS).legend
        self.assertIn('$ is one item of the column', legend)
        self.assertIn('$$ the whole list', legend)

    def test_nothing_promises_the_run_no_box_here_binds(self):
        for col in (self.SPLIT, self.SPLAT, self.UNDER_SPLAT,
                    "$['a']" + SUBCOL_SEP + '$[0]'):
            with self.subTest(col=col):
                self.assertNotIn('$$$', _subcol_scope(col, _LIST_BINDS).legend)

    def test_a_dicts_sub_column_names_the_key_and_the_value(self):
        # A row's bindings reach a sub-column, so a dict's halves are as
        # available here as they are in the main box.
        legend = _subcol_scope('*$v', _DICT_BINDS).legend
        self.assertIn('$k the key', legend)
        self.assertIn('$v the value', legend)

    def test_a_dicts_sub_column_counts_entries_rather_than_rows(self):
        legend = _subcol_scope('*$v', _DICT_BINDS).legend
        self.assertIn('$i the entry number', legend)
        self.assertNotIn('row number', legend)

    def test_a_dicts_outer_run_is_named_as_a_dict(self):
        self.assertIn('$$ the whole dict', _subcol_scope('*$v', _DICT_BINDS).legend)
        self.assertIn('$$ the (key, value) pair',
                      _subcol_scope('$v', _DICT_BINDS).legend)

    def test_a_list_says_none_of_that(self):
        for col in (self.SPLAT, self.SPLIT):
            with self.subTest(col=col):
                legend = _subcol_scope(col, _LIST_BINDS).legend
                self.assertNotIn('$k', legend)
                self.assertNotIn('$v', legend)
                self.assertIn('$i the row number', legend)


class TestSubcolLegendMatchesTheCells(unittest.TestCase):
    """The legend against the leaves themselves: what a box promises has to be
    what a sub-column written into it resolves to."""

    DATA = [{'name': 'ab', 'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'name': 'c', 'pets': [{'kind': 'fish'}]}]

    def scope(self, code):
        return eval(code, {'data': self.DATA})

    def outer_run(self, columns, target):
        """What `$$` written into the box under *target* comes back as."""
        cols = copy.deepcopy(columns)
        _subs_at(cols, target, create=True)['$$'] = {}
        leaf = [l for l in _leaf_columns(cols) if l.expr.endswith('$$')][0]
        row = _rows(self.DATA, cols)[-1]
        return _leaf_cell_value(leaf, row, self.DATA, 'data', self.scope)

    def test_the_row_it_promises_is_the_row(self):
        target = '$["name"]'
        self.assertIn('$$ the row', _subcol_scope(target, _LIST_BINDS).legend)
        self.assertEqual(self.outer_run({target: {}}, target), self.DATA[-1])

    def test_the_whole_list_it_promises_is_the_whole_list(self):
        target = '*$["pets"]'
        self.assertIn('$$ the whole list', _subcol_scope(target, _LIST_BINDS).legend)
        self.assertEqual(self.outer_run({target: {}}, target), self.DATA)

    def test_what_it_was_read_off_is_what_it_was_read_off(self):
        columns = {'*$["pets"]': {'cols': {'$["kind"]': {}}}}
        target = '*$["pets"]' + SUBCOL_SEP + '$["kind"]'
        self.assertIn('$$ the value it was read off',
                      _subcol_scope(target, _LIST_BINDS).legend)
        # The last rendered row is globex's only pet.
        self.assertEqual(self.outer_run(columns, target), {'kind': 'fish'})


class TestDictSubcolLegendMatchesTheCells(unittest.TestCase):
    """The same, for the shape Group By produces: a dict of lists, splatted.
    Every token the legend names has to come back with a value."""

    GROUPS = {'eng': [{'who': 'ann'}, {'who': 'bo'}], 'mkt': [{'who': 'cy'}]}
    COLS = {'$k': {}, '*$v': {'cols': {'$["who"]': {}}}}

    def cell(self, sub):
        cols = copy.deepcopy(self.COLS)
        _subs_at(cols, '*$v', create=True)[sub] = {}
        leaf = [l for l in _leaf_columns(cols) if l.expr.endswith(sub)][0]
        row = _rows(self.GROUPS, cols)[-1]
        return _leaf_cell_value(leaf, row, self.GROUPS, 'd',
                                lambda c: eval(c, {'d': self.GROUPS}))

    def test_every_token_the_legend_names_binds(self):
        legend = _subcol_scope('*$v', _DICT_BINDS).legend
        # The last rendered row is 'mkt', entry 1, position 0 in its group.
        for token, expected in (('$k', 'mkt'), ('$v', [{'who': 'cy'}]),
                                ('$i', 1), ('$j', 0),
                                ('$$', self.GROUPS)):
            with self.subTest(token=token):
                self.assertIn(token, legend)
                self.assertEqual(self.cell(token), expected)

    def test_the_entry_number_is_not_the_rendered_row_number(self):
        # 'eng' spreads into two rendered rows and both report entry 0, which
        # is why the dict legend says entry rather than row.
        rows = _rows(self.GROUPS, self.COLS)
        self.assertEqual([r.key for r in rows], ['0.0', '0.1', '1.0'])
        self.assertEqual([r.bindings['i'] for r in rows], [0, 0, 1])


class TestJoinSeparatorLegend(DollarLegendCase):
    """The one box in the action bar, sitting beside a search box that does take
    dollars -- so it says that it doesn't."""

    def test_the_box_says_it_is_an_ordinary_expression(self):
        self.assertEqual(box_tooltip(self.render(self.LIST), 'join-sep-input'),
                         JOIN_SEP_TOOLTIP)


class TestSplatSubcolBindings(unittest.TestCase):
    """What a splat's sub-column binds, asked of the cell and of the code the
    same cell hands over. They have to agree: a legend that advertises $i is
    advertising both."""

    ORGS = [{'name': 'acme', 'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'name': 'globex', 'pets': [{'kind': 'fish'}]}]

    def leaf_and_rows(self, sub):
        cols = {'*$["pets"]': {'cols': {sub: {}}}}
        return _leaf_columns(cols)[0], _rows(self.ORGS, cols), cols

    def scope(self, code):
        return eval(code, {'data': self.ORGS})

    def test_the_row_number_reaches_the_cell(self):
        leaf, rows, _ = self.leaf_and_rows('$i')
        got = [_leaf_cell_value(leaf, row, self.ORGS, 'data', self.scope)
               for row in rows]
        self.assertEqual(got, [0, 0, 1])

    def test_the_cell_and_the_code_it_drags_agree_about_the_row_number(self):
        leaf, rows, _ = self.leaf_and_rows('$i')
        for row in rows:
            with self.subTest(row=row.key):
                self.assertEqual(
                    _leaf_cell_value(leaf, row, self.ORGS, 'data', self.scope),
                    self.scope(_leaf_cell_expr(leaf, 'data', row, self.ORGS)))

    def test_the_position_in_the_group_reaches_the_cell(self):
        leaf, rows, _ = self.leaf_and_rows('$j')
        got = [_leaf_cell_value(leaf, row, self.ORGS, 'data', self.scope)
               for row in rows]
        self.assertEqual(got, [0, 1, 0])

    def test_a_whole_column_of_positions_keeps_every_row(self):
        # _leaf_values is what an aggregation over the column is asked of, so a
        # binding it drops is a column that silently loses rows.
        leaf, _rws, cols = self.leaf_and_rows('$j')
        model = init_model(self.ORGS, mock_get_visualizer,
                           var_and_exp=('data', 'data'))
        model['columns'] = cols
        self.assertEqual(_leaf_values(leaf, self.ORGS, model, self.scope),
                         [0, 1, 0])


class TestLegendsFollowTheBinds(unittest.TestCase):
    """The sync itself. A box's legend is generated from the binds dict its
    scope was handed, so the two cannot describe different sets of tokens --
    these are the tests that would fail if someone went back to writing the
    prose out by hand."""

    def test_the_sigils_named_are_exactly_the_sigils_bound(self):
        for binds in (_LIST_BINDS, _DICT_BINDS):
            with self.subTest(dict=_is_dict_binds(binds)):
                self.assertEqual({d.token for d in _sigil_dollars(binds)},
                                 {f'${s}' for s in binds})

    def test_a_sigil_added_to_a_container_reaches_every_legend(self):
        # The property that matters: declaring a sigil in the binds seam is all
        # it takes for the boxes to start teaching it.
        binds = {**_LIST_BINDS, 'j': 'j'}
        for scope in (_row_scope(binds), _column_search_scope(binds),
                      _subcol_scope('$', binds), _subcol_scope('*$', binds)):
            with self.subTest(scope=scope.legend):
                self.assertIn('$j', scope.legend)

    def test_a_sigil_with_no_words_for_it_refuses_to_go_undocumented(self):
        # Better a crash here than a box quietly promising less than it binds.
        with self.assertRaises(KeyError):
            _sigil_dollars({**_LIST_BINDS, 'q': 'q'})

    def test_a_sigil_taken_away_leaves_every_legend(self):
        for scope in (_row_scope({}), _column_search_scope({}),
                      _subcol_scope('$', {})):
            with self.subTest(scope=scope.legend):
                self.assertNotIn('$i', scope.legend)

    def test_the_levels_a_column_substitutes_are_the_levels_the_box_names(self):
        # _column_dollars IS _row_scope's levels, so the expression a column
        # compiles to and the tooltip over the box it was typed into come off
        # one declaration.
        scope = _row_scope(_LIST_BINDS, source_expr='data')
        self.assertEqual(scope.replace_exps, _column_dollars('data'))
        self.assertEqual(scope.tokens, ('$', '$i', '$$'))

    def test_the_levels_an_aggregation_substitutes_are_the_ones_it_names(self):
        # _agg_code and _agg_eval both take their levels off _compute_scope, so
        # the Compute box's tooltip and the code its rows write agree by
        # construction.
        scope = _compute_scope(_LIST_BINDS, 'COLVALS', 'data')
        self.assertEqual(scope.replace_exps, ['COLVALS', 'data'])
        self.assertEqual(_agg_code('sum($) / len($$)', 'COLVALS', 'data'),
                         'sum(COLVALS) / len(data)')

    def test_an_aggregation_with_no_source_promises_no_outer_run(self):
        scope = _compute_scope(_LIST_BINDS, 'COLVALS', None)
        self.assertEqual(scope.replace_exps, ['COLVALS'])
        self.assertNotIn('$$', scope.legend)
        # And the substitution leaves it as written, which is what the box
        # declining to mention it means.
        self.assertEqual(_agg_code('len($$)', 'COLVALS', None), 'len($$)')

    def test_a_list_with_no_source_promises_no_outer_run(self):
        # `$$` is left as written when there is nothing to name the list by, so
        # the box stops offering it -- both halves at once.
        scope = _row_scope(_LIST_BINDS, source_expr=None)
        self.assertEqual(scope.replace_exps, _column_dollars(None))
        self.assertNotIn('$$', scope.legend)

    def test_a_sub_column_binds_the_group_position_exactly_where_a_splat_is(self):
        # _subcol_binds is what _leaf_cell_value threads, and the legend is
        # built from it -- one answer, not two.
        for col, wants_j in (('$', False), ('*$', True),
                             ('*$v' + SUBCOL_SEP + '$.x', True),
                             ('$a' + SUBCOL_SEP + '$.x', False)):
            with self.subTest(col=col):
                self.assertEqual('j' in _subcol_binds(col, _LIST_BINDS), wants_j)
                self.assertEqual('$j' in _subcol_scope(col, _LIST_BINDS).legend,
                                 wants_j)

    def test_every_sigil_has_a_word_for_every_container_that_binds_it(self):
        for binds in (_LIST_BINDS, _DICT_BINDS, {**_DICT_BINDS, 'j': 'j'},
                      {**_LIST_BINDS, 'j': 'j'}):
            for sigil in binds:
                with self.subTest(sigil=sigil, dict=_is_dict_binds(binds)):
                    self.assertIn(_is_dict_binds(binds), _SIGIL_LABELS[sigil])


class TestEveryLegendTokenActuallyBinds(unittest.TestCase):
    """The other direction, asked of the running code rather than of the
    declaration: evaluate each token the box names and check something comes
    back. A legend that names a token the substitution leaves as written
    produces a SyntaxError here."""

    LIST = [{'n': 1, 'pets': [{'kind': 'cat'}, {'kind': 'dog'}]},
            {'n': 2, 'pets': [{'kind': 'koi'}]}]
    DICT = {'eng': [{'who': 'ann'}, {'who': 'bo'}], 'mkt': [{'who': 'cy'}]}

    def cells(self, value, columns, name):
        """Every drawn column's value for the last rendered row."""
        row = _rows(value, columns)[-1]
        scope = lambda c: eval(c, {name: value})
        out = {}
        for leaf in _leaf_columns(columns):
            token = leaf.expr.split(SUBCOL_SEP)[-1]
            out[token] = _leaf_cell_value(leaf, row, value, name, scope)
        return out

    def check(self, value, name, parent, columns_for):
        binds = _binds_for(value)
        legend = _subcol_scope(parent, binds).legend
        tokens = [d.token for d in _subcol_scope(parent, binds).dollars]
        got = self.cells(value, columns_for(tokens), name)
        for token in tokens:
            with self.subTest(parent=parent, token=token, legend=legend):
                # NO_ANSWER never appears here: an unbound run raises inside
                # eval_dollar_expr, which is what this is looking for.
                self.assertIn(token, got)

    def test_a_lists_sub_column_binds_everything_its_box_names(self):
        for parent, columns_for in (
                ('$["n"]', lambda ts: {'$["n"]': {'cols': {t: {} for t in ts}}}),
                ('*$["pets"]',
                 lambda ts: {'*$["pets"]': {'cols': {t: {} for t in ts}}})):
            self.check(self.LIST, 'data', parent, columns_for)

    def test_a_dicts_sub_column_binds_everything_its_box_names(self):
        for parent, columns_for in (
                ('$v', lambda ts: {'$v': {'cols': {t: {} for t in ts}}}),
                ('*$v', lambda ts: {'*$v': {'cols': {t: {} for t in ts}}})):
            self.check(self.DICT, 'd', parent, columns_for)


from html.parser import HTMLParser

from table_visualizer import (AddColumnAtClick, _add_anchor, _col_insert,
                              _subcol_scope, _model_binds)


def _header_html(output):
    """The table's header rows: everything before its first body cell."""
    return output[:output.index('<td')]


def _header_row(output, level=0):
    """One header row's cells, in the order they are drawn."""
    row = _header_html(output).split('<tr>')[level + 1]
    return re.findall(r'<th.*?</th>', row, re.DOTALL)


def _cell_names(cells):
    """What each header cell shows: its column, or what kind of cell it is
    where it shows no column -- the row-index corner, the box, the (+)."""
    names = []
    for cell in cells:
        if 'col-input' in cell:
            names.append('BOX')
        elif 'col-add' in cell:
            names.append('+')
        else:
            m = re.search(r'class="col-name">([^<]*)<', cell)
            names.append(html.unescape(m.group(1)) if m else '')
    return names


def _body_row(output, n=0):
    """One body row's cells, in the order they are drawn."""
    rows = re.findall(r'<tr[^>]*>(?:(?!<tr).)*?<td.*?</tr>', output, re.DOTALL)
    return re.findall(r'<td.*?</td>', rows[n], re.DOTALL)


class AddColumnBesideCase(unittest.TestCase):
    """A table of three columns, with one column's ▾ menu open."""

    LST = [{'a': 1, 'b': 2, 'c': 3}]

    def model(self, lst=None, columns=None, index=0):
        model = init_model(self.LST if lst is None else lst,
                           mock_get_visualizer)
        if columns is not None:
            model['columns'] = columns
        model['openDropdown'] = {'id': menu_id(model, index=index)}
        return model

    def click(self, model, event, lst=None):
        with patch('table_visualizer.save_columns_to_dotfile'):
            out, _ = update(make_column_mouse_event(repr(event)), None, model,
                            self.LST if lst is None else lst,
                            mock_get_visualizer)
        return out

    def commit(self, model, text, lst=None):
        """Type an expression into the open box and press Enter."""
        model['column_input_value'] = text
        with patch('table_visualizer.save_columns_to_dotfile'):
            out, _ = update(make_column_key_event('Enter'), None, model,
                            self.LST if lst is None else lst,
                            mock_get_visualizer)
        return out

    def render(self, model, lst=None):
        return visualize(self.LST if lst is None else lst, model,
                         mock_get_visualizer, None)


class TestAddColumnBesideMenu(AddColumnBesideCase):
    """The two rows that make a column where the user is looking, rather than
    at the far right the table's own (+) adds to."""

    def test_the_menu_offers_both_sides(self):
        col = col_at(self.model(), 1)
        menu = self.render(self.model(index=1))
        for after in (False, True):
            self.assertIn(html.escape(repr(AddColumnAtClick(col=col,
                                                            after=after))),
                          menu)

    def test_the_rows_sit_below_remove_column(self):
        # Beside Remove Column, ahead of everything that asks after the rows:
        # the three rows that decide which columns exist, together.
        menu = _first_column_header(self.render(self.model()))
        self.assertEqual(
            re.findall(r'>(Add Column Before|Add Column After|Remove Column'
                       r'|Subcolumns|Sort)<', menu),
            ['Remove Column', 'Add Column Before', 'Add Column After',
             'Subcolumns', 'Sort'])

    def test_a_sub_column_offers_them_too(self):
        split = "$.split(',')"
        lines = ['id,name', '1,Alice']
        model = self.model(lst=lines,
                           columns={split: {'cols': {'$[0]': {}, '$[1]': {}}}},
                           index=0)
        sub = col_at(model, 0)
        self.assertIn(SUBCOL_SEP, sub)
        menu = self.render(model, lst=lines)
        self.assertIn(html.escape(repr(AddColumnAtClick(col=sub, after=True))),
                      menu)

    def test_opening_the_box_closes_the_menu(self):
        model = self.click(self.model(), AddColumnAtClick(col=col_at(self.model()),
                                                          after=False))
        self.assertIsNone(model['openDropdown'])
        self.assertEqual(model['column_input_value'], '')
        self.assertIsNone(model['editing_column'])


class TestAddColumnBesideBox(AddColumnBesideCase):
    """Where the box is drawn: beside the column the menu was opened on, so
    the new column is written where it will end up."""

    def open_at(self, index, after, model=None):
        model = model or self.model(index=index)
        return self.click(model, AddColumnAtClick(col=col_at(model, index),
                                                  after=after))

    def test_before_draws_the_box_to_the_left_of_that_column(self):
        model = self.open_at(1, after=False)
        names = _cell_names(_header_row(self.render(model)))
        self.assertEqual(names, ['', "$['a']", 'BOX', "$['b']", "$['c']", '+'])

    def test_after_draws_it_to_the_right(self):
        model = self.open_at(1, after=True)
        names = _cell_names(_header_row(self.render(model)))
        self.assertEqual(names, ['', "$['a']", "$['b']", 'BOX', "$['c']", '+'])

    def test_the_plus_still_draws_its_box_at_the_far_right(self):
        model = self.click(self.model(), AddColumnClick())
        names = _cell_names(_header_row(self.render(model)))
        self.assertEqual(names, ['', "$['a']", "$['b']", "$['c']", 'BOX', '+'])

    def test_the_body_keeps_its_columns_lined_up(self):
        # A header cell with no cell under it would slide every column right of
        # it off the values it names, so the column being written gets an empty
        # cell in each row until it exists.
        model = self.open_at(1, after=False)
        cells = _body_row(self.render(model))
        self.assertEqual(len(cells), 5)
        self.assertIn('col-add-blank', cells[2])

    def test_the_empty_table_still_spans_the_whole_width(self):
        model = self.model(lst=[], columns={'$': {}}, index=0)
        model = self.open_at(0, after=False, model=model)
        html_out = self.render(model, lst=[])
        self.assertIn('colspan="3"', html_out)

    def test_the_box_says_what_a_sub_columns_dollars_mean(self):
        # The box holds a sub-column's own expression, written in the scope its
        # parent hands out -- the same thing the Subcolumns box would say.
        split = "$.split(',')"
        lines = ['id,name', '1,Alice']
        model = self.model(lst=lines, columns={split: {'cols': {'$[0]': {}}}})
        model = self.open_at(0, after=True, model=model)
        legend = _subcol_scope(split, _model_binds(model)).legend
        self.assertIn(f'data-tooltip="{html.escape(legend)}"',
                      self.render(model, lst=lines))


class TestAddColumnBesideSubcolumns(AddColumnBesideCase):
    """A sub-column's menu adds a sub-column: the box sits in its own header
    row, and what it writes goes in beside it rather than at the top level."""

    SPLIT = "$.split(',')"
    LINES = ['id,name', '1,Alice']

    def subcol_model(self, index=0):
        return self.model(lst=self.LINES,
                          columns={self.SPLIT: {'cols': {'$[0]': {}, '$[1]': {}}}},
                          index=index)

    def open_at(self, index, after):
        model = self.subcol_model(index)
        return self.click(model, AddColumnAtClick(col=col_at(model, index),
                                                  after=after), lst=self.LINES)

    def test_the_box_sits_in_the_sub_columns_own_row(self):
        model = self.open_at(1, after=True)
        out = self.render(model, lst=self.LINES)
        self.assertEqual(_cell_names(_header_row(out, 1)),
                         ['$[0]', '$[1]', 'BOX'])

    def test_the_parent_spans_the_box_too(self):
        # Otherwise the header cell stops short and the columns under it shift.
        model = self.open_at(0, after=False)
        out = self.render(model, lst=self.LINES)
        self.assertIn('colspan="3"', _header_row(out)[1])

    def test_what_it_writes_is_a_sub_column(self):
        model = self.commit(self.open_at(0, after=False), 'len($)',
                            lst=self.LINES)
        self.assertEqual(list(_subs_at(model['columns'], self.SPLIT)),
                         ['len($)', '$[0]', '$[1]'])
        self.assertEqual(list(model['columns']), [self.SPLIT])

    def test_after_puts_it_on_the_other_side(self):
        model = self.commit(self.open_at(0, after=True), 'len($)',
                            lst=self.LINES)
        self.assertEqual(list(_subs_at(model['columns'], self.SPLIT)),
                         ['$[0]', 'len($)', '$[1]'])


class TestAddColumnBesideCommit(AddColumnBesideCase):
    """What the box writes goes in where the box was drawn."""

    def open_at(self, index, after):
        model = self.model(index=index)
        return self.click(model, AddColumnAtClick(col=col_at(model, index),
                                                  after=after))

    def test_before_inserts_at_that_position(self):
        model = self.commit(self.open_at(1, after=False), 'len($)')
        self.assertEqual(list(model['columns']),
                         ["$['a']", 'len($)', "$['b']", "$['c']"])
        self.assertFalse(model['adding_column'])
        self.assertEqual(model['column_input_value'], '')

    def test_after_inserts_at_the_next_position(self):
        model = self.commit(self.open_at(1, after=True), 'len($)')
        self.assertEqual(list(model['columns']),
                         ["$['a']", "$['b']", 'len($)', "$['c']"])

    def test_a_suggestion_goes_in_the_same_place(self):
        model = self.open_at(0, after=True)
        model = self.click(model, ColumnSelect(name="$['z']"))
        self.assertEqual(list(model['columns']),
                         ["$['a']", "$['z']", "$['b']", "$['c']"])

    def test_the_plus_still_adds_at_the_far_right(self):
        model = self.click(self.model(), AddColumnClick())
        self.assertIs(model['adding_column'], True)
        self.assertIsNone(_add_anchor(model))
        model = self.commit(model, 'len($)')
        self.assertEqual(list(model['columns'])[-1], 'len($)')

    def test_a_column_that_went_away_falls_back_to_the_far_right(self):
        # The anchor names its column, like every other column event; one that
        # no longer exists says nothing about where the new column goes, and a
        # column the user wrote is not worth throwing away over it.
        model = self.open_at(1, after=False)
        del model['columns'][col_at(model, 1)]
        model = self.commit(model, 'len($)')
        self.assertEqual(list(model['columns'])[-1], 'len($)')

    def test_escape_takes_the_box_away(self):
        model = self.open_at(1, after=False)
        model, _ = update(make_column_key_event('Escape'), None, model,
                          self.LST, mock_get_visualizer)
        self.assertFalse(model['adding_column'])
        self.assertIsNone(_add_anchor(model))

    def test_a_column_already_drawn_is_not_added_twice(self):
        model = self.commit(self.open_at(1, after=False), "$['c']")
        self.assertEqual(list(model['columns']), ["$['a']", "$['b']", "$['c']"])


class _TableGrid(HTMLParser):
    """The outermost table as a grid of occupied slots, spans and all.

    Only the outer table: a cell's own visualizer may draw one of its own, and
    that one's shape is its business.
    """

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.widths = []      # one per row: how many columns it fills
        self._carried = {}    # row offset -> columns a rowspan above holds
        self._row = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.depth += 1
        elif tag == 'tr' and self.depth == 1:
            self._start_row()
        elif tag in ('td', 'th') and self.depth == 1:
            colspan = int(attrs.get('colspan', 1))
            rowspan = int(attrs.get('rowspan', 1))
            self._row += colspan
            for r in range(1, rowspan):
                self._carried[r] = self._carried.get(r, 0) + colspan

    def handle_endtag(self, tag):
        if tag == 'table':
            self.depth -= 1
        elif tag == 'tr' and self.depth == 1:
            self._end_row()

    def _start_row(self):
        if self._row is not None:
            self._end_row()
        self._row = self._carried.pop(0, 0)

    def _end_row(self):
        self.widths.append(self._row)
        self._carried = {r - 1: n for r, n in self._carried.items()}
        self._row = None

    def close(self):
        super().close()
        if self._row is not None:
            self._end_row()


def _row_widths(output):
    """How many columns each row of the table fills."""
    grid = _TableGrid()
    grid.feed(output)
    grid.close()
    return grid.widths


class TestAddColumnBesideKeepsTheTableRectangular(AddColumnBesideCase):
    """The box takes a column of the table everywhere, not just in the header:
    every row grows by exactly the one column it is taking, so nothing to the
    right of it comes away from its own values.

    Past the last column there is nothing to hold in place, and the box sits
    where the (+)'s does -- over the space beside the table rather than over a
    column of it, which is where the (+)'s box has always sat."""

    SPLAT = {'$k': {}, '*$v': {'cols': {'$[0]': {}, '$[1]': {}}}}
    GROUPS = {'eng': [['1', 'Alice'], ['2', 'Bo']], 'mkt': [['3', 'Cy']]}

    def check(self, model_for, lst):
        """The table with the box open beside every column, on either side."""
        base = _row_widths(visualize(lst, model_for(), mock_get_visualizer,
                                     None))
        columns = model_for()['columns']
        n_header = _header_depth(columns)
        leaves = [leaf.expr for leaf in _leaf_columns(columns)]
        for index, target in enumerate(_menu_targets(columns)):
            covered = [i for i, expr in enumerate(leaves)
                       if expr == target or expr.startswith(target + SUBCOL_SEP)]
            for after in (False, True):
                with self.subTest(column=target, after=after):
                    model = self.click(
                        model_for(),
                        AddColumnAtClick(col=target, after=after), lst=lst)
                    widths = _row_widths(
                        visualize(lst, model, mock_get_visualizer, None))
                    past_end = after and covered[-1] == len(leaves) - 1
                    self.assertEqual(
                        widths,
                        [w + 1 for w in base[:n_header]]
                        + [w + (0 if past_end else 1) for w in base[n_header:]])

    def test_a_plain_table(self):
        self.check(lambda: self.model(), self.LST)

    def test_a_table_with_sub_columns(self):
        lines = ['id,name', '1,Alice']
        columns = {"$.split(',')": {'cols': {'$[0]': {}, '$[1]': {}}},
                   'len($)': {}}
        self.check(lambda: self.model(lst=lines, columns=copy.deepcopy(columns)),
                   lines)

    def test_a_splat_and_its_per_group_answers(self):
        def model_for():
            model = self.model(lst=self.GROUPS, columns=copy.deepcopy(self.SPLAT))
            model['column_computes'] = {f'*$v{SUBCOL_SEP}$[0]': ['len($)']}
            return model
        self.check(model_for, self.GROUPS)

    def test_a_table_with_answers_under_it(self):
        def model_for():
            model = self.model()
            model['column_computes'] = {
                "$['b']": ['min($)', 'min($$, key=lambda item: $)']}
            return model
        self.check(model_for, self.LST)


class TestColInsert(unittest.TestCase):
    """The map keeps its order, so a column can go in anywhere in it."""

    def test_it_inserts_at_the_index(self):
        cols = {}
        for name in ('a', 'b', 'c'):
            _col_add(cols, name)
        self.assertTrue(_col_insert(cols, 'x', 1))
        self.assertEqual(list(cols), ['a', 'x', 'b', 'c'])

    def test_it_keeps_every_columns_config(self):
        cols = {'a': {'cols': {'$[0]': {}}}, 'b': {}}
        _col_insert(cols, 'x', 0)
        self.assertEqual(cols['a'], {'cols': {'$[0]': {}}})

    def test_a_duplicate_is_refused(self):
        cols = {'a': {}, 'b': {}}
        self.assertFalse(_col_insert(cols, 'b', 0))
        self.assertEqual(list(cols), ['a', 'b'])

    def test_past_the_end_is_the_end(self):
        cols = {'a': {}}
        _col_insert(cols, 'x', 99)
        self.assertEqual(list(cols), ['a', 'x'])


# === The row's drag handle and ▾ menu ========================================
#
# What a column header carries, for a row: a handle that hands over the row's
# values and a menu of the lines a row can be written into. The index column is
# the only cell a row has that isn't already showing something, and it has no
# room to spare -- so both sit outside the number and only appear on hover.

from table_visualizer import (
    RowActionClick, ROW_ACTIONS, LAST_ROW_ACTIONS,
    _row_actions, _row_tuple_expr, _row_without_expr, _row_headers_expr,
    _row_item_expr, _row_column_exprs, _row_handle_exprs, _names_from_end,
    _render_row_index_cell, _row_delete_matching_expr, _row_match_literal,
)


ROW_LIST = [{'b': 3, 'c': 'x'}, {'b': 1, 'c': 'y'}, {'b': 2, 'c': 'z'}]


def row_model(lst=None, columns=None, source='data', open_row=None):
    """A table with a source to write code from, and optionally a row menu
    open on one of its rows."""
    lst = ROW_LIST if lst is None else lst
    model = init_model(lst, mock_get_visualizer)
    if columns is not None:
        model['columns'] = _as_columns(columns)
    model['_source_expr'] = source
    if open_row is not None:
        model['openDropdown'] = {'id': _menu_id('row-menu', str(open_row))}
    return lst, model


def row_codes(model, lst, i):
    """The row menu's rows as {action: code}."""
    return {action: code for action, _label, code in _row_actions(model, lst, i)}


def row_labels(model, lst, i):
    return [label for _action, label, _code in _row_actions(model, lst, i)]


class TestRowTupleExpr(unittest.TestCase):
    """What the drag handle hands over: the row, as the columns on screen read
    it. The index column is not one of them -- it heads no column the user
    added, and the number is already the row's name in every other expression
    the row offers."""

    def test_it_is_the_visible_columns_of_that_row(self):
        lst, model = row_model()
        self.assertEqual(_row_tuple_expr(model, lst, 1),
                         "(data[1]['b'], data[1]['c'])")

    def test_a_column_the_user_took_away_is_not_in_it(self):
        lst, model = row_model(columns=["$['c']"])
        self.assertEqual(_row_tuple_expr(model, lst, 2), "data[2]['c']")

    def test_one_column_is_not_written_as_a_one_tuple(self):
        # `(data[0]['b'],)` is the tuple the label promises and not the thing
        # anyone dragging one column out of one row wants.
        lst, model = row_model(columns=["$['b']"])
        self.assertEqual(_row_tuple_expr(model, lst, 0), "data[0]['b']")

    def test_a_computed_column_reads_as_it_is_written(self):
        lst, model = row_model(columns=["$['b']", "$['b'] * 2"])
        self.assertEqual(_row_tuple_expr(model, lst, 0),
                         "(data[0]['b'], data[0]['b'] * 2)")

    def test_the_row_number_column_is_the_number(self):
        # A cell names one row concretely, so `$i` in it is that number.
        lst, model = row_model(columns=['$i', "$['b']"])
        self.assertEqual(_row_tuple_expr(model, lst, 2), "(2, data[2]['b'])")

    def test_a_splat_column_is_the_whole_list_the_row_spread(self):
        # The row is one row however many rendered rows it takes, so a column
        # that spread it hands over every value it spread.
        lst = [{'pets': ['cat', 'dog']}, {'pets': ['rat']}]
        lst, model = row_model(lst, {"*$['pets']": {}})
        self.assertEqual(_row_tuple_expr(model, lst, 0),
                         "[item2 for item2 in data[0]['pets']]")

    def test_a_dict_row_is_addressed_by_its_key(self):
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertEqual(_row_tuple_expr(model, d, 1), "('b', d['b'])")

    def test_no_source_means_nothing_to_hand_over(self):
        lst, model = row_model(source=None)
        self.assertIsNone(_row_tuple_expr(model, lst, 0))


class TestRowWithoutExpr(unittest.TestCase):
    """The list with one row left out -- what Delete Row writes."""

    def test_the_first_row_is_a_slice_past_it(self):
        lst, model = row_model()
        self.assertEqual(_row_without_expr(model, lst, 0), 'data[1:]')

    def test_the_last_row_is_a_slice_up_to_it(self):
        lst, model = row_model()
        self.assertEqual(_row_without_expr(model, lst, 2), 'data[:2]')

    def test_a_row_in_the_middle_is_the_two_halves(self):
        lst, model = row_model()
        self.assertEqual(_row_without_expr(model, lst, 1),
                         'data[:1] + data[2:]')

    def test_the_only_row_leaves_an_empty_list(self):
        lst, model = row_model([{'b': 1}])
        self.assertEqual(_row_without_expr(model, lst, 0), 'data[1:]')

    def test_a_loose_source_is_parenthesized_before_it_is_sliced(self):
        lst, model = row_model(source='xs + ys')
        self.assertEqual(_row_without_expr(model, lst, 1),
                         '(xs + ys)[:1] + (xs + ys)[2:]')

    def test_a_dict_drops_the_entry_by_key(self):
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertEqual(_row_without_expr(model, d, 1),
                         "{k: v for k, v in d.items() if k != 'b'}")

    def test_a_key_with_no_source_form_is_addressed_by_position(self):
        d = {(1, 2): 'a', float('nan'): 'b'}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertEqual(_row_without_expr(model, d, 1),
                         '{k: v for k, v in d.items() if k != list(d)[1]}')

    def test_no_source_means_no_line(self):
        lst, model = row_model(source=None)
        self.assertIsNone(_row_without_expr(model, lst, 0))


class TestRowDeleteMatchingExpr(unittest.TestCase):
    """The list with every row that READS like this one taken out, where Delete
    takes out the one row at that position."""

    def test_it_compares_against_the_rows_own_value(self):
        lst, model = row_model()
        self.assertEqual(
            _row_delete_matching_expr(model, lst, 1),
            "[item for item in data if item != {'b': 1, 'c': 'y'}]")

    def test_a_loose_source_is_parenthesized_before_it_is_walked(self):
        lst, model = row_model([1, 2, 1], ['$'], source='xs + ys')
        self.assertEqual(_row_delete_matching_expr(model, lst, 0),
                         '[item for item in (xs + ys) if item != 1]')

    def test_a_value_with_no_literal_has_no_line(self):
        # Its repr describes the object rather than spelling it out, so there
        # is nothing a comparison could be written against.
        lst, model = row_model([object(), object()], ['$'])
        self.assertIsNone(_row_delete_matching_expr(model, lst, 0))

    def test_a_value_that_is_not_equal_to_itself_has_no_line(self):
        lst, model = row_model([float('nan'), 1.0], ['$'])
        self.assertIsNone(_row_delete_matching_expr(model, lst, 0))

    def test_a_dicts_entry_is_not_matched_this_way(self):
        # A dict's entries are unique by key, so every entry equal to this one
        # IS this one -- Delete Entry under a second name.
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertIsNone(_row_delete_matching_expr(model, d, 0))

    def test_no_source_means_no_line(self):
        lst, model = row_model(source=None)
        self.assertIsNone(_row_delete_matching_expr(model, lst, 0))

    def test_the_literal_is_the_one_the_label_reads(self):
        lst, model = row_model()
        self.assertIn(_row_match_literal(model, lst, 2),
                      _row_delete_matching_expr(model, lst, 2))


class TestRowHeadersExpr(unittest.TestCase):
    """A row of headers over the rows under it: the list of lists a CSV reader
    hands back, read as the list of dicts it wants to be."""

    ROWS = [['name', 'dept'], ['Alice', 'eng'], ['Bob', 'mkt']]

    def test_the_first_row_names_the_rest(self):
        lst, model = row_model(self.ROWS, ['$[0]', '$[1]'])
        self.assertEqual(_row_headers_expr(model, lst, 0),
                         '[dict(zip(data[0], item)) for item in data[1:]]')

    def test_any_row_can_be_the_headers(self):
        # The rows it names are every OTHER row, which is the same list Delete
        # Row writes -- so the two can't come to disagree about what is left.
        lst, model = row_model(self.ROWS, ['$[0]', '$[1]'])
        self.assertEqual(
            _row_headers_expr(model, lst, 1),
            '[dict(zip(data[1], item)) for item in data[:1] + data[2:]]')

    def test_a_row_that_is_not_a_sequence_has_no_headers_in_it(self):
        # zip of a number is a line that cannot run, so the row goes inert
        # rather than writing one.
        lst, model = row_model([1, 2, 3], ['$'])
        self.assertIsNone(_row_headers_expr(model, lst, 0))

    def test_a_string_row_is_not_a_row_of_headers(self):
        lst, model = row_model(['ab', 'cd'], ['$'])
        self.assertIsNone(_row_headers_expr(model, lst, 0))

    def test_a_dict_has_no_row_to_read_as_headers(self):
        d = {'a': [1], 'b': [2]}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertIsNone(_row_headers_expr(model, d, 0))


class TestNamedFromTheEnd(unittest.TestCase):
    """Which rows are worth naming from the end of the list as well as by
    their number."""

    def test_the_last_row_of_a_list_of_several(self):
        lst, model = row_model()
        self.assertTrue(_names_from_end(model, lst, 2))

    def test_not_a_row_in_the_middle(self):
        lst, model = row_model()
        self.assertFalse(_names_from_end(model, lst, 1))

    def test_not_the_only_row(self):
        # Its last row is its first, and `data[-1]` is `data[0]` said twice.
        lst, model = row_model([{'b': 1}])
        self.assertFalse(_names_from_end(model, lst, 0))

    def test_not_a_dicts_last_entry(self):
        # A dict's rows are addressed by key, which is a name that doesn't
        # move when the dict grows -- there is nothing left to buy.
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertFalse(_names_from_end(model, d, 1))


class TestNamingTheLastRowFromTheEnd(unittest.TestCase):
    """The same questions asked of the last row, answered `[-1]`."""

    def test_the_item_is_the_last_one(self):
        lst, model = row_model()
        self.assertEqual(_row_item_expr(model, lst, 2, from_end=True),
                         'data[-1]')

    def test_the_list_without_it_is_everything_but_the_last(self):
        lst, model = row_model()
        self.assertEqual(_row_without_expr(model, lst, 2, from_end=True),
                         'data[:-1]')

    def test_its_cells_are_read_off_the_last_item(self):
        lst, model = row_model()
        self.assertEqual(_row_column_exprs(model, lst, 2, from_end=True),
                         ["data[-1]['b']", "data[-1]['c']"])

    def test_its_row_is_the_tuple_of_those(self):
        lst, model = row_model()
        self.assertEqual(_row_tuple_expr(model, lst, 2, from_end=True),
                         "(data[-1]['b'], data[-1]['c'])")

    def test_the_row_number_column_still_counts_from_the_front(self):
        # `$i` is where the row sits, and the last row of three sits at 2
        # however it is reached.
        lst, model = row_model(columns=['$i'])
        self.assertEqual(_row_column_exprs(model, lst, 2, from_end=True), ['2'])


class TestRowActions(unittest.TestCase):
    """The rows of the menu, in the order it offers them."""

    def test_a_middle_row_offers_the_numbered_ones(self):
        lst, model = row_model()
        self.assertEqual([a for a, _l, _c in _row_actions(model, lst, 1)],
                         ['delete', 'delete_matching', 'item', 'cells',
                          'headers'])

    def test_the_last_row_offers_the_end_relative_ones_first(self):
        lst, model = row_model()
        self.assertEqual([a for a, _l, _c in _row_actions(model, lst, 2)],
                         list(ROW_ACTIONS))
        self.assertEqual(list(ROW_ACTIONS)[:3], list(LAST_ROW_ACTIONS))

    def test_each_row_says_which_row_it_is_about(self):
        lst, model = row_model()
        self.assertEqual(row_labels(model, lst, 1),
                         ['Delete Item 1',
                          "Delete {'b': 1, 'c': 'y'} Items",
                          'Extract Item 1',
                          'Extract Row 1 Cells as Tuple',
                          'Use Item 1 as Headers'])

    def test_the_matching_row_names_the_value_rather_than_the_row(self):
        # It is not about a position: the same line comes out whichever of the
        # equal rows it was reached from.
        lst, model = row_model(['a', 'b', 'a'], ['$'])
        self.assertIn("Delete 'a' Items", row_labels(model, lst, 0))
        self.assertEqual(row_codes(model, lst, 0)['delete_matching'],
                         row_codes(model, lst, 2)['delete_matching'])

    def test_a_long_value_is_named_short_enough_to_read(self):
        lst, model = row_model([{'name': 'Alice', 'dept': 'engineering',
                                 'id': 1}, {'name': 'Bob'}], ['$'])
        label = [l for l in row_labels(model, lst, 0) if l.startswith('Delete ')
                 and l.endswith(' Items')][0]
        self.assertIn('…', label)
        self.assertLess(len(label), len(f"Delete {lst[0]!r} Items"))

    def test_a_row_with_no_literal_is_not_offered_it(self):
        lst, model = row_model([object(), object()], ['$'])
        self.assertNotIn('delete_matching', row_codes(model, lst, 0))

    def test_a_dict_is_not_offered_it(self):
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertNotIn('delete_matching', row_codes(model, d, 0))

    def test_the_last_rows_own_three_read_from_the_end(self):
        lst, model = row_model()
        self.assertEqual(row_labels(model, lst, 2)[:3],
                         ['Delete Last Item', 'Extract Last Item',
                          'Extract Last Row Cells as Tuple'])

    def test_the_item_and_the_cells_are_different_questions(self):
        # One is whatever `$` is, the other the columns on screen.
        lst, model = row_model()
        codes = row_codes(model, lst, 1)
        self.assertEqual(codes['item'], 'data[1]')
        self.assertEqual(codes['cells'], "(data[1]['b'], data[1]['c'])")

    def test_one_column_is_extracted_without_the_word_tuple(self):
        lst, model = row_model(columns=["$['b']"])
        self.assertIn('Extract Row 0 Cells', row_labels(model, lst, 0))
        self.assertNotIn('Extract Row 0 Cells as Tuple',
                         row_labels(model, lst, 0))

    def test_a_column_that_is_the_item_is_not_offered_twice(self):
        # The cells of a one-column table showing `$` ARE the item, and a menu
        # that says so twice has a row to spare.
        lst, model = row_model(columns=['$'])
        self.assertEqual(row_labels(model, lst, 1),
                         ['Delete Item 1',
                          "Delete {'b': 1, 'c': 'y'} Items",
                          'Extract Item 1',
                          'Use Item 1 as Headers'])

    def test_a_dicts_rows_are_called_entries(self):
        # The `$i` over this very column says "the entry number" for a dict, so
        # the menu hanging off it can't call the same thing an item.
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertEqual(row_labels(model, d, 0)[:2],
                         ['Delete Entry 0', 'Extract Entry 0'])

    def test_a_row_with_nothing_to_write_carries_no_code(self):
        lst, model = row_model([1, 2, 3], ['$'])
        self.assertIsNone(row_codes(model, lst, 0)['headers'])

    def test_without_a_source_no_row_carries_code(self):
        lst, model = row_model(source=None)
        self.assertEqual(set(row_codes(model, lst, 0).values()), {None})


class TestRowHandleExprs(unittest.TestCase):
    """What the drag handle on a row's number offers, in the order the tooltip
    stacks them. The first is what a drag hands over."""

    def labelled(self, model, lst, i):
        return [(e.label, e.expr) for e in _row_handle_exprs(model, lst, i)]

    def test_a_row_reads_two_ways(self):
        lst, model = row_model()
        self.assertEqual(self.labelled(model, lst, 1),
                         [("Row's cells", "(data[1]['b'], data[1]['c'])"),
                          ('Item', 'data[1]')])

    def test_the_last_row_offers_its_end_relative_readings_first(self):
        lst, model = row_model()
        self.assertEqual(self.labelled(model, lst, 2),
                         [("Last row's cells", "(data[-1]['b'], data[-1]['c'])"),
                          ('Last item', 'data[-1]'),
                          ("Row's cells", "(data[2]['b'], data[2]['c'])"),
                          ('Item', 'data[2]')])

    def test_a_column_that_is_the_item_is_not_offered_twice(self):
        lst, model = row_model(columns=['$'])
        self.assertEqual(self.labelled(model, lst, 1),
                         [("Row's cells", 'data[1]')])

    def test_a_dicts_entry_is_labelled_an_entry(self):
        # `$v` alone is not the whole entry, so the two readings differ and
        # both are offered -- the second by the name a dict's rows go by.
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$v'], source='d')
        self.assertEqual(self.labelled(model, d, 1),
                         [("Row's cells", "d['b']"),
                          ('Entry', "('b', d['b'])")])

    def test_a_dict_drawing_both_halves_says_the_entry_once(self):
        # `$k` and `$v` side by side ARE the entry, spelled the way the entry
        # itself is spelled.
        d = {'a': 1, 'b': 2}
        d, model = row_model(d, ['$k', '$v'], source='d')
        self.assertEqual(self.labelled(model, d, 1),
                         [("Row's cells", "('b', d['b'])")])


class TestRowWidgetRendering(unittest.TestCase):
    """Both widgets hang off the row's number and neither takes any of its
    room: they are drawn outside the cell, and only while it is hovered."""

    def render(self, lst=None, columns=None, source='data', open_row=None,
               small=False, **fields):
        lst, model = row_model(lst, columns, source, open_row)
        model.update(fields)
        # visualize re-reads the source off var_and_exp each run (see
        # _adopt_source), so a table meant to have none must be handed none.
        var_and_exp = None if source is None else ('data', source)
        return lst, model, visualize(lst, model, mock_get_visualizer,
                                     lambda c: eval(c, {'data': lst}),
                                     small=small, var_and_exp=var_and_exp)

    def index_cell(self, out, n=0):
        cells = re.findall(r'<td class="row-index[^"]*".*?</td>', out, re.DOTALL)
        return cells[n]

    def index_inner(self, out, n=0):
        """The wrapper inside the cell -- the number and the two controls."""
        cell = self.index_cell(out, n)
        m = re.search(r'<div class="row-index-inner".*(?=</div>)', cell,
                      re.DOTALL)
        assert m is not None, 'no row-index-inner'
        return m.group(0)

    def test_the_index_cell_carries_a_drag_handle(self):
        _lst, _model, out = self.render()
        self.assertIn('row-handle', self.index_cell(out, 1))

    def test_the_handle_hands_over_the_rows_visible_columns(self):
        _lst, _model, out = self.render()
        offered = [e for h in handles_in(self.index_cell(out, 1)) for e in h]
        self.assertEqual(offered[0],
                         {'expr': "(data[1]['b'], data[1]['c'])",
                          'label': "Row's cells"})

    def test_the_handle_offers_the_item_beside_the_cells(self):
        _lst, _model, out = self.render()
        offered = [e for h in handles_in(self.index_cell(out, 1)) for e in h]
        self.assertEqual(offered[1], {'expr': 'data[1]', 'label': 'Item'})

    def test_the_last_rows_handle_leads_with_the_end_relative_readings(self):
        _lst, _model, out = self.render()
        offered = [e['label']
                   for h in handles_in(self.index_cell(out, 2)) for e in h]
        self.assertEqual(offered, ["Last row's cells", 'Last item',
                                   "Row's cells", 'Item'])

    def test_the_handle_asks_to_be_lifted_out_of_the_scrollport(self):
        # It belongs outside the table's left edge, which is outside the
        # overflow that clips it, so the front end draws a copy of it there
        # for as long as the number is hovered.
        _lst, _model, out = self.render()
        self.assertIn('snc-hover-hoist', self.index_cell(out, 0))

    def test_the_number_and_the_controls_share_a_wrapper(self):
        # Flex on the <td> would drop the cell out of table layout, so what
        # lays the three of them out is a wrapper inside it.
        _lst, _model, out = self.render()
        inner = self.index_inner(out, 2)
        self.assertIn('row-handle', inner)
        self.assertIn('row-menu-trigger', inner)
        self.assertRegex(inner, r'</span>2<span')

    def test_the_wrapper_is_what_a_hoisted_control_is_placed_against(self):
        # Not the cell: the cell is as tall as whatever is drawn beside it in
        # the row, and the controls belong beside the number.
        _lst, _model, out = self.render()
        self.assertIn('snc-hoist-host', self.index_inner(out, 0))

    def test_a_cell_with_no_controls_hosts_nothing(self):
        _lst, _model, out = self.render(small=True)
        self.assertIn('row-index-inner', self.index_cell(out, 0))
        self.assertNotIn('snc-hoist-host', out)

    def test_the_pick_overlay_stays_a_child_of_the_cell(self):
        # It covers the whole cell and is positioned against it, so it is not
        # one of the things the wrapper lays out.
        _lst, _model, out = self.render(search="$['b'] == 1", tool='pick',
                                        first_match=True)
        self.assertIn('pick-region', self.index_cell(out, 0))
        self.assertNotIn('pick-region', self.index_inner(out, 0))

    def test_the_handle_is_draggable(self):
        _lst, _model, out = self.render()
        self.assertIn('draggable="true"', self.index_cell(out, 0))

    def test_the_number_is_still_the_cells_only_content(self):
        # Both widgets are position:absolute, so the column stays as wide as
        # the numbers in it.
        _lst, _model, out = self.render()
        self.assertRegex(self.index_cell(out, 2), r'>\s*2\s*<')

    def test_the_index_cell_carries_a_menu_trigger(self):
        _lst, _model, out = self.render()
        self.assertIn('row-menu-trigger', self.index_cell(out, 0))

    def test_the_menu_is_closed_until_the_trigger_is_clicked(self):
        _lst, _model, out = self.render()
        self.assertNotIn('row-menu-panel', out)

    def test_an_open_menu_draws_its_panel_under_its_own_row(self):
        _lst, _model, out = self.render(open_row=1)
        self.assertNotIn('row-menu-panel', self.index_cell(out, 0))
        self.assertIn('row-menu-panel', self.index_cell(out, 1))

    def test_the_open_panel_is_one_the_front_end_hoists(self):
        _lst, _model, out = self.render(open_row=0)
        panel = out[out.index('row-menu-panel'):]
        self.assertIn('snc-dropdown-panel', self.index_cell(out, 0))
        self.assertIn('snc-dropdown-align="flyout"', self.index_cell(out, 0))
        self.assertIn('snc-dismiss', panel[:200])

    def test_the_open_trigger_stays_visible_behind_the_hoisted_panel(self):
        _lst, _model, out = self.render(open_row=0)
        self.assertIn('row-menu-trigger open', self.index_cell(out, 0))

    def test_every_menu_row_is_a_handle_on_the_code_it_writes(self):
        _lst, lst_model, out = self.render(open_row=1)
        panel = self.index_cell(out, 1)
        offered = {e['expr'] for h in handles_in(panel) for e in h}
        self.assertIn('data[:1] + data[2:]', offered)
        self.assertIn("(data[1]['b'], data[1]['c'])", offered)

    def test_a_row_with_nothing_to_write_is_drawn_unselectable(self):
        # A list of numbers: `$` is the whole column, so the cells reading is
        # the item and drops out, and nothing zips into headers.
        _lst, _model, out = self.render([1, 2, 3], ['$'], open_row=0)
        rows = re.findall(r'<div class="snc-dropdown-option row-action[^"]*"',
                          self.index_cell(out, 0))
        self.assertEqual(len(rows), 4)
        self.assertIn('unselectable', rows[3])

    def test_the_last_rows_menu_leads_with_its_end_relative_rows(self):
        _lst, _model, out = self.render(open_row=2)
        panel = self.index_cell(out, 2)
        self.assertIn('Delete Last Item', panel)
        self.assertLess(panel.index('Delete Last Item'),
                        panel.index('Delete Item 2'))

    def test_an_ordinary_row_is_offered_none_of_them(self):
        _lst, _model, out = self.render(open_row=1)
        self.assertNotIn('Last Item', self.index_cell(out, 1))

    def test_a_small_table_draws_neither(self):
        # No room, and an unfocused preview is not where a line gets written.
        _lst, _model, out = self.render(small=True)
        self.assertNotIn('row-handle', out)
        self.assertNotIn('row-menu-trigger', out)

    def test_a_table_with_no_source_draws_neither(self):
        _lst, _model, out = self.render(source=None)
        self.assertNotIn('row-handle', out)
        self.assertNotIn('row-menu-trigger', out)

    def test_the_pick_tool_keeps_the_index_cell_to_itself(self):
        # The pick region overlay sits on top of the cell and takes the click;
        # a handle under it is one the user could never reach.
        _lst, _model, out = self.render(search="$['b'] == 1", tool='pick',
                                        first_match=True)
        self.assertIn('pick-region', out)
        self.assertNotIn('row-handle', out)

    def test_a_splat_draws_the_widgets_once_per_root_row(self):
        lst = [{'pets': ['cat', 'dog']}, {'pets': ['rat']}]
        _lst, _model, out = self.render(lst, {"*$['pets']": {}})
        self.assertEqual(out.count('row-handle'), 2)


class TestRowActionClick(unittest.TestCase):
    """Clicking one writes its line and closes the menu behind it."""

    def click(self, action, row=1, lst=None, columns=None, source='data',
              **fields):
        lst, model = row_model(lst, columns, source, open_row=row)
        model.update(fields)
        return update(make_column_mouse_event(
            repr(RowActionClick(row=row, action=action))),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda c: eval(c, {}, {'data': lst}))

    def test_delete_writes_the_list_without_that_row(self):
        _model, commands = self.click('delete')
        self.assertEqual(commands[0][:2],
                         ('data_without_item_1', 'data[:1] + data[2:]'))

    def test_delete_matching_writes_the_list_without_that_value(self):
        _model, commands = self.click('delete_matching')
        self.assertEqual(
            commands[0][:2],
            ('data_without_matching_items',
             "[item for item in data if item != {'b': 1, 'c': 'y'}]"))

    def test_a_matching_click_on_a_row_with_no_literal_writes_nothing(self):
        # The menu never offered it there, so a stale click can't take it up.
        _model, commands = self.click('delete_matching', row=0,
                                      lst=[object(), object()], columns=['$'])
        self.assertEqual(commands, [])

    def test_item_writes_the_item_itself(self):
        _model, commands = self.click('item')
        self.assertEqual(commands[0][:2], ('data_item_1', 'data[1]'))

    def test_cells_writes_the_rows_columns_as_a_tuple(self):
        _model, commands = self.click('cells')
        self.assertEqual(commands[0][:2],
                         ('data_row_1', "(data[1]['b'], data[1]['c'])"))

    def test_the_last_rows_three_are_written_from_the_end(self):
        self.assertEqual(self.click('last_delete', row=2)[1][0][:2],
                         ('data_without_last', 'data[:-1]'))
        self.assertEqual(self.click('last_item', row=2)[1][0][:2],
                         ('data_last_item', 'data[-1]'))
        self.assertEqual(self.click('last_cells', row=2)[1][0][:2],
                         ('data_last_row', "(data[-1]['b'], data[-1]['c'])"))

    def test_an_end_relative_click_on_a_row_that_is_not_last_writes_nothing(self):
        # The menu never offered it there, so a stale click can't take it up.
        _model, commands = self.click('last_delete', row=1)
        self.assertEqual(commands, [])

    def test_headers_writes_the_list_of_dicts(self):
        rows = [['name'], ['Alice'], ['Bob']]
        _model, commands = self.click('headers', row=0, lst=rows,
                                      columns=['$[0]'])
        self.assertEqual(
            commands[0][:2],
            ('data_dicts', '[dict(zip(data[0], item)) for item in data[1:]]'))

    def test_the_lines_need_nothing_imported(self):
        _model, commands = self.click('delete')
        self.assertEqual(len(commands[0]), 2)

    def test_the_menu_closes_behind_it(self):
        model, _commands = self.click('cells')
        self.assertIsNone(model['openDropdown'])

    def test_the_name_falls_back_when_the_list_has_no_name(self):
        _model, commands = self.click('delete', source='data[0]')
        self.assertEqual(commands[0][0], 'result_without_item_1')

    def test_a_dicts_entry_is_named_an_entry(self):
        d = {'a': 1, 'b': 2}
        _model, commands = self.click('delete', lst=d, columns=['$k', '$v'],
                                      source='d')
        self.assertEqual(commands[0][0], 'd_without_entry_1')

    def test_a_row_that_is_gone_writes_nothing(self):
        _model, commands = self.click('delete', row=9)
        self.assertEqual(commands, [])

    def test_an_action_with_no_code_writes_nothing(self):
        _model, commands = self.click('headers', row=0, lst=[1, 2, 3],
                                      columns=['$'])
        self.assertEqual(commands, [])

    def test_a_dict_is_offered_none_of_the_end_relative_rows(self):
        d = {'a': 1, 'b': 2}
        _model, commands = self.click('last_item', row=1, lst=d,
                                      columns=['$k', '$v'], source='d')
        self.assertEqual(commands, [])

    def test_an_action_nobody_offers_writes_nothing(self):
        _model, commands = self.click('sort')
        self.assertEqual(commands, [])

    def test_without_a_source_it_writes_nothing(self):
        _model, commands = self.click('delete', source=None)
        self.assertEqual(commands, [])


class TestTheLastRowsCellsNameItFromTheEnd(unittest.TestCase):
    """The row handle is not the only thing on the last row that can say
    `[-1]`: the cells are handed that expression too, so a child's own handles
    are built out of it and the code a cell makes comes back bound to it.

    One expression per cell rather than two: `var_and_exp` is the one slot a
    child is given, so which naming the last row hands down is a choice, and
    the one that survives the list growing is the one worth having.
    """

    LST = [{'b': 3, 'c': 'x'}, {'b': 1, 'c': 'y'}, {'b': 2, 'c': 'z'}]

    def render(self, lst=None, columns=None):
        lst = self.LST if lst is None else lst
        model = init_model(lst, mock_get_visualizer, var_and_exp=('data', 'data'))
        if columns is not None:
            model['columns'] = _as_columns(columns)
        return lst, model, visualize(lst, model, mock_get_visualizer,
                                     lambda c: eval(c, {'data': lst}),
                                     var_and_exp=('data', 'data'))

    def body_row(self, out, n):
        rows = [r for r in re.findall(r'<tr[^>]*>.*?</tr>', out, re.DOTALL)
                if 'col-header' not in r]
        return rows[n]

    def cell_exprs(self, out, n):
        """The expression each cell of body row *n* was handed, index cell
        (which has its own labelled readings) aside.

        Read off what the child did with it rather than off the table: the int
        mock echoes the expression it was given, and the string mock wraps
        itself in a handle built out of it. Between them that is every way a
        cell's expression reaches the editor.
        """
        row = self.body_row(out, n)
        row = row[row.index('</td>'):]
        echoed = re.findall(r'child-expr=([^>]*)>', html.unescape(row))
        return echoed + [e['expr'] for h in handles_in(row) for e in h]

    def test_the_last_rows_cells_are_read_off_the_last_item(self):
        _lst, _model, out = self.render()
        self.assertCountEqual(self.cell_exprs(out, 2),
                              ["data[-1]['b']", "data[-1]['c']"])

    def test_every_other_row_is_still_read_by_its_number(self):
        _lst, _model, out = self.render()
        self.assertCountEqual(self.cell_exprs(out, 1),
                              ["data[1]['b']", "data[1]['c']"])

    def test_the_only_row_of_a_list_is_read_by_its_number(self):
        _lst, _model, out = self.render([{'b': 3, 'c': 'x'}])
        self.assertCountEqual(self.cell_exprs(out, 0),
                              ["data[0]['b']", "data[0]['c']"])

    def test_a_splat_cell_in_the_last_row_too(self):
        # Asked of the whole table: a splat's later rendered rows have no
        # index cell of their own for cell_exprs to read past.
        lst = [{'pets': ['cat']}, {'pets': ['rat', 'bat']}]
        _lst, _model, out = self.render(lst, {"*$['pets']": {}})
        offered = {e['expr'] for h in handles_in(out) for e in h}
        self.assertIn("data[-1]['pets'][0]", offered)
        self.assertIn("data[-1]['pets'][1]", offered)
        self.assertIn("data[0]['pets'][0]", offered)

    def test_a_dicts_last_entry_is_still_read_by_its_key(self):
        d = {'a': 1, 'b': 2}
        model = init_model(d, mock_get_visualizer, var_and_exp=('d', 'd'))
        model['columns'] = _as_columns(['$v'])
        out = visualize(d, model, mock_get_visualizer,
                        lambda c: eval(c, {'d': d}), var_and_exp=('d', 'd'))
        self.assertCountEqual(self.cell_exprs(out, 1), ["d['b']"])


class TestCodeOutOfTheLastRowsCell(unittest.TestCase):
    """The way back up agrees with the way down: a cell handed `data[-1][...]`
    has whatever it makes rebound through the same expression, or the value on
    screen and the text on the clipboard would name different rows."""

    DATA = [{'name': 'ann'}, {'name': 'bo'}, {'name': 'cy'}]

    def fire(self, row_key):
        cols = _as_columns({"$['name']": {}})
        model = init_model(self.DATA, get_visualizer_cell_code,
                           var_and_exp=('data', 'data'))
        model['columns'] = cols
        key = f'{row_key}{CELL_KEY_SEP}{_leaf_columns(cols)[0].expr}'
        ev = make_child_mouse_event(key, 'lambda ev: None')
        # The first mousedown on an unfocused cell only pins focus to it.
        model, _ = update(ev, ('data', 'data'), model, self.DATA,
                          get_visualizer_cell_code)
        return update(ev, ('data', 'data'), model, self.DATA,
                      get_visualizer_cell_code)

    def test_the_clipboard_form_names_the_last_item(self):
        _model, commands = self.fire('2')
        texts = [c.text for c in commands if isinstance(c, CopyToClipboard)]
        self.assertEqual(texts, ["(data[-1]['name']).upper()"])
        self.assertEqual(eval(texts[0], {'data': self.DATA}), 'CY')

    def test_another_row_still_names_its_number(self):
        _model, commands = self.fire('1')
        texts = [c.text for c in commands if isinstance(c, CopyToClipboard)]
        self.assertEqual(texts, ["(data[1]['name']).upper()"])

    def test_the_column_it_writes_is_row_generic_either_way(self):
        # What the code is generic over is the rows, which the row it was made
        # in has no say in.
        model, _commands = self.fire('2')
        self.assertIn("($['name']).upper()", model['columns'])


class TestRowMenuToggle(unittest.TestCase):
    """The trigger is the same state-driven dropdown the column ▾ is, so it
    goes through the one slot that holds a menu open."""

    def test_clicking_the_trigger_opens_that_rows_menu(self):
        lst, model = row_model()
        model, _commands = update(
            make_dropdown_toggle_event(_menu_id('row-menu', '2')),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda c: eval(c, {}, {'data': lst}))
        self.assertEqual(model['openDropdown'], {'id': 'row-menu-2'})

    def test_a_click_away_closes_it(self):
        lst, model = row_model(open_row=1)
        model, _commands = update(
            make_column_mouse_event(repr(table_visualizer.ColumnMenuDismiss())),
            ('data', 'data'), model, lst, mock_get_visualizer,
            eval_in_scope=lambda c: eval(c, {}, {'data': lst}))
        self.assertIsNone(model['openDropdown'])


if __name__ == '__main__':
    unittest.main()
