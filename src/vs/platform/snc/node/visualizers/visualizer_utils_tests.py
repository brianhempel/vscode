"""
Tests for visualizer_utils.py - shared utilities for visualizer composition.

Run:
    python3 -m pytest visualizer_utils_tests.py -v
"""

import unittest
import html
import os
import shutil
import tempfile

from visualizer_utils import ChildEvent, wrap_child_html, route_child_event, aggregate_handled_keys, eval_caret_expr
from visualizer_utils import (
    config_key, parse_slots, load_root_slots, save_slots_at_path,
    child_nesting_kwargs, too_deep, MAX_NEST_DEPTH,
)


class TestChildEvent(unittest.TestCase):
    """Test ChildEvent dataclass basics."""

    def test_child_event_fields(self):
        ev = ChildEvent(child_key='0', py_ev_str='MouseDown(index=5)')
        self.assertEqual(ev.child_key, '0')
        self.assertEqual(ev.py_ev_str, 'MouseDown(index=5)')

    def test_child_event_is_frozen(self):
        ev = ChildEvent(child_key='0', py_ev_str='MouseDown(index=5)')
        with self.assertRaises(AttributeError):
            ev.child_key = '1'

    def test_child_event_repr_evals_back(self):
        ev = ChildEvent(child_key='abc', py_ev_str='KeyDown()')
        reconstructed = eval(repr(ev))
        self.assertEqual(reconstructed, ev)


class TestWrapChildHtml(unittest.TestCase):
    """Test wrap_child_html wraps child HTML in a span with snc-child-key."""

    def test_wraps_in_span_with_data_attribute(self):
        child_html = '<span snc-mouse-down="MouseDown(index=5)">X</span>'
        wrapped = wrap_child_html(child_html, '0')
        self.assertIn('snc-child-key=', wrapped)
        self.assertTrue(wrapped.startswith('<span '))
        self.assertTrue(wrapped.endswith('</span>'))

    def test_child_html_preserved_inside_wrapper(self):
        child_html = '<span snc-mouse-down="MouseDown(index=5)">X</span>'
        wrapped = wrap_child_html(child_html, '0')
        self.assertIn(child_html, wrapped)

    def test_child_key_repr_in_data_attribute(self):
        """The data attribute should contain the Python repr of the child key."""
        import re
        wrapped = wrap_child_html('<span>X</span>', 'mykey')
        match = re.search(r'snc-child-key="([^"]*)"', wrapped)
        self.assertIsNotNone(match)
        attr_value = html.unescape(match.group(1))
        self.assertEqual(attr_value, repr('mykey'))

    def test_child_key_with_special_chars_is_escaped(self):
        """Keys with HTML-special chars should be properly escaped in the attribute."""
        import re
        wrapped = wrap_child_html('<span>X</span>', '0::field<name>')
        match = re.search(r'snc-child-key="([^"]*)"', wrapped)
        self.assertIsNotNone(match)
        attr_value = html.unescape(match.group(1))
        self.assertEqual(eval(attr_value), '0::field<name>')

    def test_snc_attrs_not_modified(self):
        """snc-* attributes in child HTML should be left untouched."""
        child_html = '<span snc-mouse-down="MouseDown(index=5)">X</span>'
        wrapped = wrap_child_html(child_html, '0')
        self.assertIn('snc-mouse-down="MouseDown(index=5)"', wrapped)

    def test_preserves_all_child_content(self):
        child_html = '<span class="foo" style="color:red" snc-mouse-down="X">hello</span>'
        wrapped = wrap_child_html(child_html, '0')
        self.assertIn('class="foo"', wrapped)
        self.assertIn('style="color:red"', wrapped)
        self.assertIn('>hello</span>', wrapped)

    def test_multiple_elements_preserved(self):
        child_html = '<span snc-mouse-down="A">1</span><span snc-mouse-down="B">2</span>'
        wrapped = wrap_child_html(child_html, '0')
        self.assertIn('snc-mouse-down="A"', wrapped)
        self.assertIn('snc-mouse-down="B"', wrapped)


class TestRouteChildEvent(unittest.TestCase):
    """Test route_child_event dispatches to child visualizers correctly."""

    def _make_mock_visualizer(self, updated_model='updated', commands=None):
        """Create a mock visualizer module with init_model and update."""
        class MockVis:
            def can_visualize(self, value):
                return True
            def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'mock': True}
            def visualize(self, value, model, get_visualizer):
                return '<span>mock</span>'
            def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
                return (updated_model, commands or [])
        return MockVis()

    def _make_get_visualizer(self, vis):
        return lambda value: vis

    def test_routes_to_child_and_updates_model(self):
        mock_vis = self._make_mock_visualizer(updated_model='child_updated')
        get_vis = self._make_get_visualizer(mock_vis)

        # Pre-focus the child so the mousedown dispatches; the click-to-focus
        # case is covered separately in TestClickToFocusChild.
        model = {'children': {'0': 'old_child_model'}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'}
        }
        value = ['item0', 'item1']

        def child_value_getter(key):
            return value[int(key)]

        new_model, commands = route_child_event(
            event, model, value, child_value_getter, get_vis,
            var_and_exp=('x', 'x')
        )
        self.assertEqual(new_model['children']['0'], 'child_updated')

    def test_initializes_missing_child_model(self):
        mock_vis = self._make_mock_visualizer(updated_model='new_child')
        get_vis = self._make_get_visualizer(mock_vis)

        # Pre-focus so the dispatch (and lazy init_model) runs.
        model = {'children': {}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'}
        }
        value = ['item0']

        new_model, commands = route_child_event(
            event, model, value, lambda k: value[int(k)], get_vis,
        )
        self.assertEqual(new_model['children']['0'], 'new_child')

    def test_returns_child_commands(self):
        mock_vis = self._make_mock_visualizer(commands=['cmd1', 'cmd2'])
        get_vis = self._make_get_visualizer(mock_vis)

        # Pre-focus the child so the mousedown dispatches instead of just
        # pinning focus (see TestClickToFocusChild for the unfocused case).
        model = {'children': {'0': 'some_model'}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'}
        }
        value = ['item0']

        _, commands = route_child_event(
            event, model, value, lambda k: value[int(k)], get_vis,
        )
        self.assertEqual(commands, ['cmd1', 'cmd2'])


class TestClickToFocusChild(unittest.TestCase):
    """First mousedown on an unfocused child should only pin focus, not
    dispatch the event to the child. Mirrors the top-level click-to-expand
    behavior: clicking a small/unfocused widget expands it without firing a
    stray Python event whose target may not exist post-expand.
    """

    def _make_dispatch_tracker(self):
        """Visualizer that records every update() call so we can assert
        whether dispatch happened."""
        class TrackingVis:
            def __init__(self):
                self.update_calls = []
            def can_visualize(self, value):
                return True
            def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'mock': True}
            def visualize(self, value, model, get_visualizer):
                return ''
            def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
                self.update_calls.append(event)
                return ({'dispatched': True}, ['some_cmd'])
        return TrackingVis()

    def test_first_mousedown_on_unfocused_child_only_pins_focus(self):
        tracker = self._make_dispatch_tracker()
        get_vis = lambda v: tracker
        model = {'children': {'0': 'old'}, 'handledKeys': []}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'},
        }
        new_model, commands = route_child_event(
            event, model, ['item0'], lambda k: 'item0', get_vis,
        )
        self.assertEqual(new_model.get('focused_child'), '0')
        self.assertEqual(tracker.update_calls, [],
                         "Child's update() should NOT be called on first focus click")
        self.assertEqual(commands, [])
        self.assertEqual(new_model['children']['0'], 'old',
                         "Child model should not be replaced on first focus click")

    def test_mousedown_on_already_focused_child_dispatches(self):
        tracker = self._make_dispatch_tracker()
        get_vis = lambda v: tracker
        model = {'children': {'0': 'old'}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'},
        }
        new_model, commands = route_child_event(
            event, model, ['item0'], lambda k: 'item0', get_vis,
        )
        self.assertEqual(len(tracker.update_calls), 1)
        self.assertEqual(commands, ['some_cmd'])
        self.assertTrue(new_model['children']['0'].get('dispatched'))

    def test_non_mousedown_event_on_unfocused_child_is_ignored(self):
        """Hovering / finishing a drag over an unfocused child must NOT
        dispatch and must NOT pin focus. Only mousedown can change focus."""
        tracker = self._make_dispatch_tracker()
        get_vis = lambda v: tracker
        model = {'children': {'0': 'old'}, 'handledKeys': []}  # no focused_child
        for ev_type in ('mousemove', 'mouseup', 'mouseover', 'keydown'):
            event = {
                'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
                'eventJSON': {'type': ev_type},
            }
            new_model, commands = route_child_event(
                event, model, ['item0'], lambda k: 'item0', get_vis,
            )
            self.assertEqual(tracker.update_calls, [],
                             f"{ev_type} on unfocused child should be ignored")
            self.assertEqual(commands, [])
            self.assertNotIn('focused_child', new_model,
                             f"{ev_type} must not pin focus")

    def test_focused_child_receives_non_mousedown_events(self):
        """Once focused, the child receives mousemove/mouseup/etc as normal."""
        tracker = self._make_dispatch_tracker()
        get_vis = lambda v: tracker
        model = {'children': {'0': 'old'}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('0', 'SomeEvent()')",
            'eventJSON': {'type': 'mousemove'},
        }
        _, commands = route_child_event(
            event, model, ['item0'], lambda k: 'item0', get_vis,
        )
        self.assertEqual(len(tracker.update_calls), 1)
        self.assertEqual(commands, ['some_cmd'])

    def test_mousedown_switching_focus_between_children_only_pins(self):
        tracker = self._make_dispatch_tracker()
        get_vis = lambda v: tracker
        model = {'children': {'0': 'a', '1': 'b'}, 'handledKeys': [], 'focused_child': '0'}
        event = {
            'pythonEventStr': "ChildEvent('1', 'SomeEvent()')",
            'eventJSON': {'type': 'mousedown'},
        }
        new_model, commands = route_child_event(
            event, model, ['item0', 'item1'], lambda k: 'item' + k, get_vis,
        )
        self.assertEqual(new_model.get('focused_child'), '1')
        self.assertEqual(tracker.update_calls, [])
        self.assertEqual(commands, [])


class TestAggregateHandledKeys(unittest.TestCase):
    """Test aggregate_handled_keys merges child handledKeys."""

    def _make_vis_with_keys(self, keys):
        class Vis:
            def can_visualize(self, value):
                return True
            def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'handledKeys': keys}
            def visualize(self, value, model, get_visualizer):
                return ''
            def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
                return (model, [])
        return Vis()

    def test_aggregates_from_children_models(self):
        children_models = {
            '0': {'handledKeys': ['Enter', 'Escape']},
            '1': {'handledKeys': ['Escape', 'Tab']},
        }
        result = aggregate_handled_keys(children_models, own_keys=[])
        self.assertIn('Enter', result)
        self.assertIn('Escape', result)
        self.assertIn('Tab', result)

    def test_includes_own_keys(self):
        children_models = {
            '0': {'handledKeys': ['Enter']},
        }
        result = aggregate_handled_keys(children_models, own_keys=['Backspace'])
        self.assertIn('Enter', result)
        self.assertIn('Backspace', result)

    def test_empty_children(self):
        result = aggregate_handled_keys({}, own_keys=['Escape'])
        self.assertEqual(result, ['Escape'])

    def test_child_without_handled_keys(self):
        children_models = {
            '0': {'some_other_field': 'val'},
            '1': {'handledKeys': ['Enter']},
        }
        result = aggregate_handled_keys(children_models, own_keys=[])
        self.assertIn('Enter', result)

    def test_no_duplicates(self):
        children_models = {
            '0': {'handledKeys': ['Enter', 'Escape']},
            '1': {'handledKeys': ['Enter', 'Tab']},
        }
        result = aggregate_handled_keys(children_models, own_keys=['Enter'])
        self.assertEqual(result.count('Enter'), 1)


class TestEvalCaretExpr(unittest.TestCase):
    """Test eval_caret_expr: shared field evaluation using ^ expressions."""

    def test_simple_attribute_fallback(self):
        class Obj:
            x = 42
        self.assertEqual(eval_caret_expr('^.x', Obj()), 42)

    def test_index_access_fallback(self):
        self.assertEqual(eval_caret_expr('^[1]', [10, 20, 30]), 20)

    def test_dict_key_access_fallback(self):
        self.assertEqual(eval_caret_expr("^['name']", {'name': 'Alice'}), 'Alice')

    def test_method_call_fallback(self):
        self.assertEqual(eval_caret_expr('^.upper()', 'hello'), 'HELLO')

    def test_chained_access_fallback(self):
        class Inner:
            val = 99
        class Outer:
            child = Inner()
        self.assertEqual(eval_caret_expr('^.child.val', Outer()), 99)

    def test_uses_eval_in_scope_when_both_provided(self):
        _my_var = [10, 20, 30]
        eis = lambda expr: eval(expr)
        result = eval_caret_expr('^[2]', _my_var, eval_in_scope=eis)
        self.assertEqual(result, 30)

    def test_eval_in_scope_with_nested_source_expr(self):
        _my_var = [[1, 2], [3, 4]]
        eis = lambda expr: eval(expr)
        result = eval_caret_expr('^[0]', _my_var[1], eval_in_scope=eis)
        self.assertEqual(result, 3)

    def test_falls_back_when_eval_in_scope_none(self):
        self.assertEqual(eval_caret_expr('^[0]', [42], eval_in_scope=None), 42)

    def test_falls_back_when_source_expr_none(self):
        eis = lambda expr: eval(expr)
        self.assertEqual(eval_caret_expr('^[0]', [42], eval_in_scope=eis), 42)

    def test_error_propagates(self):
        with self.assertRaises(Exception):
            eval_caret_expr('^.nonexistent', 42)


class TestConfigKey(unittest.TestCase):
    """config_key selects the per-element type so a list-of-T and a single T
    share one config."""

    def test_list_of_str(self):
        self.assertEqual(config_key(['a', 'b']), 'builtins.str')

    def test_list_of_dict(self):
        self.assertEqual(config_key([{'a': 1}]), 'builtins.dict')

    def test_empty_list_is_none(self):
        self.assertIsNone(config_key([]))

    def test_single_string_matches_list_of_string(self):
        self.assertEqual(config_key('hi'), config_key(['hi']))

    def test_object_class_name(self):
        class Foo:
            pass
        self.assertIn('Foo', config_key(Foo()))

    def test_int(self):
        self.assertEqual(config_key(5), 'builtins.int')


class TestParseSlots(unittest.TestCase):
    """parse_slots splits a slot list into (exprs, slot_children)."""

    def test_bare_strings(self):
        exprs, children = parse_slots(['^', '^.x'])
        self.assertEqual(exprs, ['^', '^.x'])
        self.assertEqual(children, {})

    def test_dict_entries_without_children(self):
        exprs, children = parse_slots([{'expr': '^'}, {'expr': '^.x'}])
        self.assertEqual(exprs, ['^', '^.x'])
        self.assertEqual(children, {})

    def test_children_collected_by_expr(self):
        spec = [{'expr': 'f', 'children': {'builtins.str': [{'expr': '^'}]}}]
        exprs, children = parse_slots(spec)
        self.assertEqual(exprs, ['f'])
        self.assertEqual(children, {'f': {'builtins.str': [{'expr': '^'}]}})

    def test_none_config(self):
        exprs, children = parse_slots(None)
        self.assertEqual(exprs, [])
        self.assertEqual(children, {})

    def test_expr_transform_applied(self):
        exprs, _ = parse_slots(['x', '^.y'],
                               expr_transform=lambda e: e if '^' in e else '^' + e)
        self.assertEqual(exprs, ['^x', '^.y'])

    def test_empty_children_not_stored(self):
        _, children = parse_slots([{'expr': 'f', 'children': {}}])
        self.assertEqual(children, {})

    def test_invalid_entries_skipped(self):
        exprs, _ = parse_slots([123, {'no_expr': 1}, '^'])
        self.assertEqual(exprs, ['^'])


class TestSaveSlotsAtPath(unittest.TestCase):
    """save_slots_at_path persists a level's exprs at its path, preserving
    siblings, other types, and descendants' nested children."""

    def setUp(self):
        self.orig = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)
        self.dot = '.snc_test_slots.json'

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_root(self):
        save_slots_at_path(self.dot, 'builtins.str', [], ['^', 'f'])
        self.assertEqual(load_root_slots(self.dot, 'builtins.str'),
                         [{'expr': '^'}, {'expr': 'f'}])

    def test_preserves_other_types(self):
        save_slots_at_path(self.dot, 'A', [], ['^.x'])
        save_slots_at_path(self.dot, 'B', [], ['^.y'])
        self.assertEqual(load_root_slots(self.dot, 'A'), [{'expr': '^.x'}])
        self.assertEqual(load_root_slots(self.dot, 'B'), [{'expr': '^.y'}])

    def test_nested_path_creates_structure(self):
        save_slots_at_path(self.dot, 'builtins.str',
                           [('f', 'builtins.str')], ['^', '^.x'])
        slots = load_root_slots(self.dot, 'builtins.str')
        f_slot = next(s for s in slots if s['expr'] == 'f')
        self.assertEqual(f_slot['children']['builtins.str'],
                         [{'expr': '^'}, {'expr': '^.x'}])

    def test_root_resave_preserves_children_by_expr(self):
        save_slots_at_path(self.dot, 'builtins.str', [], ['^', 'f'])
        save_slots_at_path(self.dot, 'builtins.str',
                           [('f', 'builtins.str')], ['^'])
        # Re-save the root with the columns reordered; the nested children
        # under 'f' must survive (an ancestor never clobbers a descendant).
        save_slots_at_path(self.dot, 'builtins.str', [], ['f', '^'])
        slots = load_root_slots(self.dot, 'builtins.str')
        f_slot = next(s for s in slots if s['expr'] == 'f')
        self.assertEqual(f_slot.get('children'),
                         {'builtins.str': [{'expr': '^'}]})

    def test_remove_expr_drops_its_subtree(self):
        save_slots_at_path(self.dot, 'T', [], ['a', 'b'])
        save_slots_at_path(self.dot, 'T', [('b', 'X')], ['^'])
        save_slots_at_path(self.dot, 'T', [], ['a'])
        slots = load_root_slots(self.dot, 'T')
        self.assertEqual([s['expr'] for s in slots], ['a'])

    def test_legacy_string_entries_normalized(self):
        # A pre-existing flat (legacy) file with bare strings.
        import json
        with open(self.dot, 'w') as f:
            json.dump({'T': ['a', 'b']}, f)
        save_slots_at_path(self.dot, 'T', [], ['a', 'b', 'c'])
        self.assertEqual(load_root_slots(self.dot, 'T'),
                         [{'expr': 'a'}, {'expr': 'b'}, {'expr': 'c'}])

    def test_none_root_type_is_noop(self):
        save_slots_at_path(self.dot, None, [], ['^'])
        self.assertIsNone(load_root_slots(self.dot, None))


class TestChildNestingKwargs(unittest.TestCase):
    """child_nesting_kwargs computes the kwargs handed to a child visualizer."""

    def test_returns_nested_slots_for_cell_type(self):
        model = {
            '_slot_children': {'f': {'builtins.str': [{'expr': '^'}]}},
            '_config_root_type': 'builtins.str',
            '_config_root_dotfile': '.snc_list_columns.json',
            '_config_path': [],
        }
        kw = child_nesting_kwargs(model, 'f', ['a', 'b'])
        self.assertEqual(kw['slots_config'], [{'expr': '^'}])
        self.assertEqual(kw['config_root_type'], 'builtins.str')
        self.assertEqual(kw['config_root_dotfile'], '.snc_list_columns.json')
        self.assertEqual(kw['config_path'], [('f', 'builtins.str')])

    def test_no_children_returns_none_slots(self):
        model = {'_slot_children': {}, '_config_path': []}
        kw = child_nesting_kwargs(model, 'f', ['a'])
        self.assertIsNone(kw['slots_config'])
        self.assertEqual(kw['config_path'], [('f', 'builtins.str')])

    def test_path_appends_step(self):
        model = {'_slot_children': {}, '_config_path': [('g', 'X')]}
        kw = child_nesting_kwargs(model, 'f', 5)
        self.assertEqual(kw['config_path'], [('g', 'X'), ('f', 'builtins.int')])


class TestTooDeep(unittest.TestCase):
    """too_deep caps nesting depth so cyclic values can't RecursionError."""

    def test_shallow_not_too_deep(self):
        self.assertFalse(too_deep([]))
        self.assertFalse(too_deep(None))
        self.assertFalse(too_deep([('a', 'T')] * (MAX_NEST_DEPTH - 1)))

    def test_at_cap_too_deep(self):
        self.assertTrue(too_deep([('a', 'T')] * MAX_NEST_DEPTH))


if __name__ == '__main__':
    unittest.main()
