"""
Tests for visualizer_utils.py - shared utilities for visualizer composition.

Run:
    python3 -m pytest visualizer_utils_tests.py -v
"""

import ast
import json
import re
import unittest
import html
import os
import shutil
import tempfile

from visualizer_utils import (ChildEvent, wrap_child_html, route_child_event,
                              aggregate_handled_keys, eval_dollar_expr,
                              replace_dollars_in_py_exp, dollar_expr_parses,
                              py_exp_attrs, nest_child_command,
                              wrap_drag_grab, defer_drag_grab,
                              CHILD_SOURCE_BINDER)
from visualizer_utils import (
    config_key, parse_slots, load_root_slots, save_slots_at_path,
    child_nesting_kwargs, too_deep, MAX_NEST_DEPTH,
    opens_block, with_pass_body, without_pass_body,
    supported_kwargs, call_with_supported_kwargs, keyword_params, wants_kwarg,
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


class TestEvalDollarExpr(unittest.TestCase):
    """Test eval_dollar_expr: shared field evaluation using $ expressions."""

    def test_simple_attribute_fallback(self):
        class Obj:
            x = 42
        self.assertEqual(eval_dollar_expr('$.x', Obj()), 42)

    def test_index_access_fallback(self):
        self.assertEqual(eval_dollar_expr('$[1]', [10, 20, 30]), 20)

    def test_dict_key_access_fallback(self):
        self.assertEqual(eval_dollar_expr("$['name']", {'name': 'Alice'}), 'Alice')

    def test_method_call_fallback(self):
        self.assertEqual(eval_dollar_expr('$.upper()', 'hello'), 'HELLO')

    def test_chained_access_fallback(self):
        class Inner:
            val = 99
        class Outer:
            child = Inner()
        self.assertEqual(eval_dollar_expr('$.child.val', Outer()), 99)

    def test_uses_eval_in_scope_when_both_provided(self):
        _my_var = [10, 20, 30]
        eis = lambda expr: eval(expr)
        result = eval_dollar_expr('$[2]', _my_var, eval_in_scope=eis)
        self.assertEqual(result, 30)

    def test_eval_in_scope_with_nested_source_expr(self):
        _my_var = [[1, 2], [3, 4]]
        eis = lambda expr: eval(expr)
        result = eval_dollar_expr('$[0]', _my_var[1], eval_in_scope=eis)
        self.assertEqual(result, 3)

    def test_falls_back_when_eval_in_scope_none(self):
        self.assertEqual(eval_dollar_expr('$[0]', [42], eval_in_scope=None), 42)

    def test_falls_back_when_source_expr_none(self):
        eis = lambda expr: eval(expr)
        self.assertEqual(eval_dollar_expr('$[0]', [42], eval_in_scope=eis), 42)

    def test_the_expression_can_name_the_programs_variables(self):
        # A dollar expression is written where the user is looking, so the
        # names beside the dollar are their program's names. The scope stands
        # in for a user module that defined `factor`; passing the `eval`
        # builtin instead would resolve against this test module.
        eis = lambda expr: eval(expr, {'factor': 10})
        self.assertEqual(eval_dollar_expr('$ * factor', 3, eval_in_scope=eis),
                         30)

    def test_the_expression_can_call_the_programs_functions(self):
        eis = lambda expr: eval(expr, {'twice': lambda n: n * 2})
        self.assertEqual(eval_dollar_expr('twice($)', 5, eval_in_scope=eis), 10)

    def test_error_propagates(self):
        with self.assertRaises(Exception):
            eval_dollar_expr('$.nonexistent', 42)


class TestReplaceDollarsInPyExp(unittest.TestCase):
    """A dollar run names a scope: $ is the innermost value, $$ its parent, and
    replace_exps binds them innermost-first."""

    def test_binds_each_level_by_run_length(self):
        self.assertEqual(
            replace_dollars_in_py_exp('($$)[:$.start()]', ['mtch', '_snc_cell_']),
            '(_snc_cell_)[:mtch.start()]')

    def test_leaves_dollars_in_string_literals_alone(self):
        # A $ that parses where it stands is string content, not a scope
        # reference. $ is never legal Python outside a literal, so unlike the
        # old caret syntax there is no operator to confuse it with.
        cases = [
            ('"a $ b" + $[0]', ['mtch'], '"a $ b" + mtch[0]'),
            ("$.split('$')", ['mtch'], "mtch.split('$')"),
            ('a ^ b', ['mtch'], 'a ^ b'),
        ]
        self.assertEqual([replace_dollars_in_py_exp(e, b) for e, b, _ in cases],
                         [want for _, _, want in cases])

    def test_unbound_level_is_left_alone(self):
        # A caller that knows one scope shouldn't crash on text naming two, and
        # must not invent a binding it doesn't have.
        self.assertEqual(replace_dollars_in_py_exp('$$ + $[0]', ['mtch']),
                         '$$ + mtch[0]')

    def test_dollar_expr_parses_reads_every_level_as_a_value(self):
        self.assertEqual(
            [dollar_expr_parses(s) for s in
             ('$.start()', '$$.foo', '$$ + $', 'a ^ b', '$.(', 'def f(): pass')],
            [True, True, True, True, False, False])

    def test_binder_is_spliced_verbatim(self):
        # The replacement is not re-scanned, so a multi-token binder lands whole.
        self.assertEqual(
            replace_dollars_in_py_exp('$.upper()', ['rows[0].name']),
            'rows[0].name.upper()')


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
        exprs, children = parse_slots(['$', '$.x'])
        self.assertEqual(exprs, ['$', '$.x'])
        self.assertEqual(children, {})

    def test_dict_entries_without_children(self):
        exprs, children = parse_slots([{'expr': '$'}, {'expr': '$.x'}])
        self.assertEqual(exprs, ['$', '$.x'])
        self.assertEqual(children, {})

    def test_children_collected_by_expr(self):
        spec = [{'expr': 'f', 'children': {'builtins.str': [{'expr': '$'}]}}]
        exprs, children = parse_slots(spec)
        self.assertEqual(exprs, ['f'])
        self.assertEqual(children, {'f': {'builtins.str': [{'expr': '$'}]}})

    def test_none_config(self):
        exprs, children = parse_slots(None)
        self.assertEqual(exprs, [])
        self.assertEqual(children, {})

    def test_expr_transform_applied(self):
        exprs, _ = parse_slots(['x', '$.y'],
                               expr_transform=lambda e: e if '$' in e else '$' + e)
        self.assertEqual(exprs, ['$x', '$.y'])

    def test_empty_children_not_stored(self):
        _, children = parse_slots([{'expr': 'f', 'children': {}}])
        self.assertEqual(children, {})

    def test_invalid_entries_skipped(self):
        exprs, _ = parse_slots([123, {'no_expr': 1}, '$'])
        self.assertEqual(exprs, ['$'])


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
        save_slots_at_path(self.dot, 'builtins.str', [], ['$', 'f'])
        self.assertEqual(load_root_slots(self.dot, 'builtins.str'),
                         [{'expr': '$'}, {'expr': 'f'}])

    def test_preserves_other_types(self):
        save_slots_at_path(self.dot, 'A', [], ['$.x'])
        save_slots_at_path(self.dot, 'B', [], ['$.y'])
        self.assertEqual(load_root_slots(self.dot, 'A'), [{'expr': '$.x'}])
        self.assertEqual(load_root_slots(self.dot, 'B'), [{'expr': '$.y'}])

    def test_nested_path_creates_structure(self):
        save_slots_at_path(self.dot, 'builtins.str',
                           [('f', 'builtins.str')], ['$', '$.x'])
        slots = load_root_slots(self.dot, 'builtins.str')
        f_slot = next(s for s in slots if s['expr'] == 'f')
        self.assertEqual(f_slot['children']['builtins.str'],
                         [{'expr': '$'}, {'expr': '$.x'}])

    def test_root_resave_preserves_children_by_expr(self):
        save_slots_at_path(self.dot, 'builtins.str', [], ['$', 'f'])
        save_slots_at_path(self.dot, 'builtins.str',
                           [('f', 'builtins.str')], ['$'])
        # Re-save the root with the columns reordered; the nested children
        # under 'f' must survive (an ancestor never clobbers a descendant).
        save_slots_at_path(self.dot, 'builtins.str', [], ['f', '$'])
        slots = load_root_slots(self.dot, 'builtins.str')
        f_slot = next(s for s in slots if s['expr'] == 'f')
        self.assertEqual(f_slot.get('children'),
                         {'builtins.str': [{'expr': '$'}]})

    def test_remove_expr_drops_its_subtree(self):
        save_slots_at_path(self.dot, 'T', [], ['a', 'b'])
        save_slots_at_path(self.dot, 'T', [('b', 'X')], ['$'])
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
        save_slots_at_path(self.dot, None, [], ['$'])
        self.assertIsNone(load_root_slots(self.dot, None))


class TestChildNestingKwargs(unittest.TestCase):
    """child_nesting_kwargs computes the kwargs handed to a child visualizer."""

    def test_returns_nested_slots_for_cell_type(self):
        model = {
            '_slot_children': {'f': {'builtins.str': [{'expr': '$'}]}},
            '_config_root_type': 'builtins.str',
            '_config_root_dotfile': '.snc_list_columns.json',
            '_config_path': [],
        }
        kw = child_nesting_kwargs(model, 'f', ['a', 'b'])
        self.assertEqual(kw['slots_config'], [{'expr': '$'}])
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

    def test_child_that_names_the_params_gets_them_all(self):
        def init_model(value, get_visualizer=None, slots_config=None,
                       config_root_type=None, config_root_dotfile=None,
                       config_path=None):
            pass
        model = {'_slot_children': {'f': {'builtins.int': [{'expr': '$'}]}},
                 '_config_root_type': 'builtins.list', '_config_path': []}
        kw = child_nesting_kwargs(model, 'f', 5, init_model)
        self.assertEqual(kw['slots_config'], [{'expr': '$'}])
        self.assertEqual(kw['config_path'], [('f', 'builtins.int')])

    def test_child_that_ignores_nesting_is_handed_nothing(self):
        # And the config isn't even computed for it -- this is the hot path,
        # once per cell of a table.
        def init_model(value, get_visualizer=None, eval_in_scope=None):
            pass
        model = {'_slot_children': {'f': {'builtins.int': [{'expr': '$'}]}},
                 '_config_path': []}
        self.assertEqual(child_nesting_kwargs(model, 'f', 5, init_model), {})

    def test_child_naming_only_some_params_gets_only_those(self):
        def init_model(value, get_visualizer=None, slots_config=None):
            pass
        model = {'_slot_children': {'f': {'builtins.int': [{'expr': '$'}]}},
                 '_config_path': []}
        self.assertEqual(child_nesting_kwargs(model, 'f', 5, init_model),
                         {'slots_config': [{'expr': '$'}]})

    def test_child_taking_var_keyword_gets_them_all(self):
        def init_model(value, **kwargs):
            pass
        model = {'_slot_children': {}, '_config_path': []}
        self.assertEqual(set(child_nesting_kwargs(model, 'f', 5, init_model)),
                         {'slots_config', 'config_root_type',
                          'config_root_dotfile', 'config_path'})


class TestTooDeep(unittest.TestCase):
    """too_deep caps nesting depth so cyclic values can't RecursionError."""

    def test_shallow_not_too_deep(self):
        self.assertFalse(too_deep([]))
        self.assertFalse(too_deep(None))
        self.assertFalse(too_deep([('a', 'T')] * (MAX_NEST_DEPTH - 1)))

    def test_at_cap_too_deep(self):
        self.assertTrue(too_deep([('a', 'T')] * MAX_NEST_DEPTH))


class TestOpensBlock(unittest.TestCase):
    """opens_block detects generated code that needs a body to be runnable."""

    def test_single_line_header(self):
        self.assertTrue(opens_block('for item in xs:'))
        self.assertTrue(opens_block('if any(x > 1 for x in xs):'))

    def test_multi_line_header(self):
        self.assertTrue(opens_block('for i, item in enumerate(xs):\n    if item > 1:'))

    def test_trailing_whitespace_still_a_header(self):
        self.assertTrue(opens_block('for item in xs:   '))

    def test_expressions_are_not_headers(self):
        self.assertFalse(opens_block('xs[1:2]'))
        self.assertFalse(opens_block('[x for x in xs if x > 1]'))
        self.assertFalse(opens_block("','.join(str(item) for item in xs)"))
        self.assertFalse(opens_block('{1: 2}'))

    def test_empty_code_is_not_a_header(self):
        self.assertFalse(opens_block(''))
        self.assertFalse(opens_block('   '))


class TestWithPassBody(unittest.TestCase):
    """with_pass_body re-attaches the body that generation leaves off."""

    def test_appends_pass_under_single_line_header(self):
        self.assertEqual(with_pass_body('for item in xs:'),
                         'for item in xs:\n    pass')

    def test_indents_pass_under_deepest_header_line(self):
        self.assertEqual(
            with_pass_body('for i, item in enumerate(xs):\n    if item > 1:'),
            'for i, item in enumerate(xs):\n    if item > 1:\n        pass')

    def test_expression_returned_unchanged(self):
        self.assertEqual(with_pass_body('xs[1:2]'), 'xs[1:2]')

    def test_result_is_parseable(self):
        for code in ['for item in xs:',
                     'if all(x for x in xs):',
                     'for i, item in enumerate(xs):\n    if item > 1:']:
            with self.subTest(code=code):
                ast.parse(with_pass_body(code))

    def test_assignment_prefix_stays_parseable(self):
        """Headers never carry an assignment prefix, but expressions do."""
        ast.parse('_linked_result = ' + with_pass_body('xs[1:2]'))


class TestWithoutPassBody(unittest.TestCase):
    """without_pass_body normalizes editor text back to a bare header."""

    def test_strips_placeholder_body(self):
        self.assertEqual(without_pass_body('for item in xs:\n    pass'),
                         'for item in xs:')

    def test_strips_deeper_placeholder_body(self):
        self.assertEqual(
            without_pass_body('for i, item in enumerate(xs):\n    if item > 1:\n        pass'),
            'for i, item in enumerate(xs):\n    if item > 1:')

    def test_inverts_with_pass_body(self):
        for code in ['for item in xs:',
                     'if all(x for x in xs):',
                     'for i, item in enumerate(xs):\n    if item > 1:',
                     'xs[1:2]']:
            with self.subTest(code=code):
                self.assertEqual(without_pass_body(with_pass_body(code)), code)

    def test_keeps_real_body(self):
        """Only a placeholder body is scaffolding; user code must survive."""
        code = 'for item in xs:\n    print(item)'
        self.assertEqual(without_pass_body(code), code)

    def test_expression_returned_unchanged(self):
        self.assertEqual(without_pass_body('xs[1:2]'), 'xs[1:2]')
        self.assertEqual(without_pass_body('compass'), 'compass')


class TestNestChildCommandKeepsTheDeclaration(unittest.TestCase):
    """Code coming back from a child visualizer is rebound to the parent's
    scope. What it needs imported doesn't change on the way up."""

    def test_a_nested_command_keeps_its_imports(self):
        cmd = ('found', f"re.findall(r'a', {CHILD_SOURCE_BINDER})",
               ('import re',))
        nested = nest_child_command(cmd, 'item', 'xs[0]')
        self.assertEqual(nested[0], 'found')
        self.assertEqual(nested[1], "re.findall(r'a', (item))")
        self.assertEqual(nested[2], ('import re',))

    def test_a_command_that_declared_nothing_stays_a_pair(self):
        cmd = ('picked', f'{CHILD_SOURCE_BINDER}[1:]')
        self.assertEqual(nest_child_command(cmd, 'item', 'xs[0]'),
                         ('picked', '(item)[1:]'))


class TestPyExpAttrs(unittest.TestCase):
    """The attributes that hand an expression to the editor: the tooltip that
    shows it, the drag that carries it, and the imports it can't run without."""

    def test_the_expression_comes_out_escaped(self):
        self.assertEqual(py_exp_attrs('d["<k>"]'),
                         ' snc-py-exp="d[&quot;&lt;k&gt;&quot;]" draggable="true"')

    def test_a_handle_that_is_only_hovered_is_not_draggable(self):
        self.assertEqual(py_exp_attrs('xs[0]', draggable=False),
                         ' snc-py-exp="xs[0]"')

    def test_a_handle_at_the_right_edge_reads_leftwards(self):
        self.assertIn(' snc-py-exp-align="right"',
                      py_exp_attrs('xs[0]', draggable=False, align='right'))

    def test_an_expression_says_which_imports_it_needs(self):
        # Declared by whatever produced the code; nothing downstream re-derives
        # it from the text. JSON so one statement per entry survives intact.
        attrs = py_exp_attrs('re.findall(p, s)',
                             imports=('import re', 'import os'))
        match = re.search(r'snc-py-exp-imports="([^"]*)"', attrs)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(html.unescape(match.group(1))),
                         ['import re', 'import os'])

    def test_an_action_buttons_expression_rides_on_its_own_attribute(self):
        # A different tooltip system picks it up, but the imports keep one name.
        attrs = py_exp_attrs("re.findall(p, s)", imports=('import re',),
                             draggable=False, attr='data-action-expr')
        self.assertIn(' data-action-expr="re.findall(p, s)"', attrs)
        self.assertIn(' snc-py-exp-imports=', attrs)
        self.assertNotIn(' snc-py-exp=', attrs)

    def test_an_expression_needing_nothing_says_nothing(self):
        self.assertNotIn('snc-py-exp-imports', py_exp_attrs('xs[0]'))

    def test_no_expression_means_no_attributes_at_all(self):
        self.assertEqual(py_exp_attrs(''), '')
        self.assertEqual(py_exp_attrs(None), '')


class TestDeferDragGrab(unittest.TestCase):
    """Letting a parent's handle answer for a child's whole-value one, which
    stays a handle to look at and to drag."""

    GRAB = '<span class="py-exp-grab">'

    def test_a_handle_the_parent_repeats_stops_carrying_the_expression(self):
        wrapped = wrap_drag_grab('<span>5</span>', (None, 'min(data)'))
        self.assertEqual(defer_drag_grab(wrapped, 'min(data)'),
                         f'{self.GRAB}<span>5</span></span>')

    def test_an_expression_needing_escaping_is_still_recognised(self):
        wrapped = wrap_drag_grab('<span>5</span>', (None, 'd["<k>"]'))
        self.assertEqual(defer_drag_grab(wrapped, 'd["<k>"]'),
                         f'{self.GRAB}<span>5</span></span>')

    def test_a_handle_over_something_else_stays_as_it_is(self):
        # Not the parent's expression, so not the parent's to answer for.
        wrapped = wrap_drag_grab('<span>5</span>', (None, 'data[0]'))
        self.assertEqual(defer_drag_grab(wrapped, 'min(data)'), wrapped)

    def test_handles_inside_the_child_are_left_alone(self):
        # A child that draws its own handles keeps every one of them: only a
        # wrapper around the whole thing is what the parent duplicates.
        html_str = ('<div><span snc-py-exp="min(data)" draggable="true" '
                    'class="py-exp-grab">5</span></div>')
        self.assertEqual(defer_drag_grab(html_str, 'min(data)'), html_str)

    def test_two_wrapped_things_side_by_side_are_left_alone(self):
        # Starts with a handle and ends with a close, but the close isn't that
        # handle's -- rewriting the first tag would speak for the last too.
        both = (wrap_drag_grab('<span>5</span>', (None, 'min(data)'))
                + wrap_drag_grab('<span>6</span>', (None, 'min(data)')))
        self.assertEqual(defer_drag_grab(both, 'min(data)'), both)

    def test_nothing_to_repeat_means_nothing_to_defer(self):
        self.assertEqual(defer_drag_grab('<span>5</span>', None),
                         '<span>5</span>')
        self.assertEqual(defer_drag_grab('<span>5</span>', ''),
                         '<span>5</span>')


class TestSupportedKwargs(unittest.TestCase):
    """A visualizer asks for what it wants by naming it in its signature; the
    caller offers everything and the extras are dropped, so no visualizer has
    to also declare a top-level capability constant."""

    def test_drops_kwargs_the_function_does_not_declare(self):
        def init_model(value, get_visualizer=None, eval_in_scope=None):
            pass
        self.assertEqual(
            supported_kwargs(init_model, eval_in_scope=1, slots_config=[{'expr': '$'}]),
            {'eval_in_scope': 1})

    def test_keeps_kwargs_the_function_declares(self):
        def init_model(value, get_visualizer=None, eval_in_scope=None,
                       slots_config=None, config_path=None):
            pass
        offered = {'eval_in_scope': 1, 'slots_config': ['s'], 'config_path': [],
                   'nonesuch': 'x'}
        self.assertEqual(supported_kwargs(init_model, **offered),
                         {'eval_in_scope': 1, 'slots_config': ['s'], 'config_path': []})

    def test_keyword_only_params_count_as_declared(self):
        def init_model(value, *, slots_config=None):
            pass
        self.assertEqual(supported_kwargs(init_model, slots_config=['s'], other=2),
                         {'slots_config': ['s']})

    def test_var_keyword_takes_everything(self):
        def init_model(value, get_visualizer=None, **kwargs):
            pass
        offered = {'eval_in_scope': 1, 'slots_config': ['s'], 'whatever': 2}
        self.assertEqual(supported_kwargs(init_model, **offered), offered)

    def test_positional_only_params_are_not_passable_by_keyword(self):
        def init_model(value, /, slots_config=None):
            pass
        self.assertEqual(supported_kwargs(init_model, value=1, slots_config=['s']),
                         {'slots_config': ['s']})

    def test_bound_method_does_not_count_self(self):
        class Vis:
            def init_model(self, value, get_visualizer=None, slots_config=None):
                pass
        self.assertEqual(supported_kwargs(Vis().init_model, self='oops',
                                          slots_config=['s'], config_path=[]),
                         {'slots_config': ['s']})

    def test_uninspectable_callable_is_offered_everything(self):
        # Some builtins have no introspectable signature; don't silently drop
        # arguments on them -- let the call itself be the judge.
        self.assertEqual(supported_kwargs('abc'.find, whatever=1), {'whatever': 1})

    def test_call_passes_positional_args_through(self):
        def init_model(value, get_visualizer=None, slots_config=None):
            return (value, get_visualizer, slots_config)
        self.assertEqual(
            call_with_supported_kwargs(init_model, [1, 2], 'gv', slots_config=['s'],
                                       config_root_type='builtins.list'),
            ([1, 2], 'gv', ['s']))

    def test_wants_kwarg_reads_the_signature(self):
        def init_model(value, get_visualizer=None, slots_config=None):
            pass

        def plain_init_model(value, get_visualizer=None):
            pass

        def anything(value, **kwargs):
            pass
        self.assertTrue(wants_kwarg(init_model, 'slots_config'))
        self.assertFalse(wants_kwarg(plain_init_model, 'slots_config'))
        self.assertTrue(wants_kwarg(anything, 'slots_config'))

    def test_wants_kwarg_on_a_bound_method(self):
        class Vis:
            def init_model(self, value, slots_config=None):
                pass

        class PlainVis:
            def init_model(self, value):
                pass
        self.assertTrue(wants_kwarg(Vis().init_model, 'slots_config'))
        self.assertFalse(wants_kwarg(PlainVis().init_model, 'slots_config'))
        self.assertFalse(wants_kwarg(PlainVis().init_model, 'self'))

    def test_call_on_a_visualizer_that_wants_nothing_extra(self):
        def init_model(value, get_visualizer=None):
            return 'ok'
        self.assertEqual(
            call_with_supported_kwargs(init_model, [1], 'gv', slots_config=['s'],
                                       config_path=[], config_root_type='t',
                                       config_root_dotfile='.f'),
            'ok')

    def test_signatures_are_inspected_once_per_function(self):
        def init_model(value, slots_config=None):
            pass
        supported_kwargs(init_model, slots_config=1)
        before = keyword_params.cache_info()
        supported_kwargs(init_model, slots_config=2)
        self.assertEqual(keyword_params.cache_info().hits, before.hits + 1)

    def test_bound_methods_of_one_class_share_a_cache_entry(self):
        # A visualizer object hands back a fresh bound method every attribute
        # access; caching on the underlying function keeps that from thrashing.
        class Vis:
            def init_model(self, value, slots_config=None):
                pass
        supported_kwargs(Vis().init_model, slots_config=1)
        before = keyword_params.cache_info()
        supported_kwargs(Vis().init_model, slots_config=2)  # different instance
        self.assertEqual(keyword_params.cache_info().hits, before.hits + 1)

    def test_keyword_params_reports_var_keyword_as_take_everything(self):
        def takes_all(value, **kwargs):
            pass

        def takes_some(value, slots_config=None):
            pass
        self.assertIsNone(keyword_params(takes_all))
        self.assertEqual(keyword_params(takes_some), frozenset({'value', 'slots_config'}))


if __name__ == '__main__':
    unittest.main()
