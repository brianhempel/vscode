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

from visualizer_utils import (ChildEvent, wrap_child_html, route_child_event,
                              aggregate_handled_keys, eval_dollar_expr,
                              replace_dollars_in_py_exp, dollar_expr_parses,
                              dollar_expr_names_index, dollar_expr_sigils,
                              py_exp_attrs, PyExp, nest_child_command,
                              wrap_drag_grab, defer_drag_grab,
                              imports_for_code, CHILD_SOURCE_BINDER,
                              new_code_command, is_new_code)
from visualizer_utils import (
    parse_slots, parse_slot_cols, save_slots_at_path,
    set_line_config, take_line_config, peek_line_config, config_sig,
    config_comment_index, parse_config_comment, format_config_comment,
    CONFIG_COMMENT_PREFIX,
    child_nesting_kwargs, too_deep, MAX_NEST_DEPTH,
    opens_block, with_pass_body, without_pass_body,
    supported_kwargs, call_with_supported_kwargs, keyword_params, wants_kwarg,
    render_expand_toggle, truncate_str, truncate_repr,
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

    def test_an_enclosing_scope_is_what_the_longer_run_names(self):
        # A list column is written against a row, but the box it is typed into
        # says $$ is the whole list.
        lst = [3, 1, 5]
        self.assertEqual(eval_dollar_expr('$ / max($$)', 5, outer=(lst,)), 1.0)

    def test_scopes_are_bound_outwards_one_run_at_a_time(self):
        self.assertEqual(eval_dollar_expr('($, $$, $$$)', 1, outer=(2, 3)),
                         (1, 2, 3))

    def test_a_run_with_no_scope_to_bind_it_is_an_error(self):
        # Left as written, which is not Python -- the same answer as naming a
        # variable the program doesn't have.
        with self.assertRaises(Exception):
            eval_dollar_expr('len($$)', 5)


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


class TestDollarIIsOneTokenOfItsOwn(unittest.TestCase):
    """`$i` names the index of the value, not a scope. A run of dollars says how
    far out to look; `$i` says which one of them we are at, so it is bound on its
    own rather than by run length."""

    def test_it_binds_to_the_index_it_is_given(self):
        self.assertEqual(
            replace_dollars_in_py_exp('$ * $i', ['item'], index_exp='i'),
            'item * i')

    def test_a_caller_with_no_index_leaves_it_as_written(self):
        # Which is not Python, so it lands in the caller's except as "no value"
        # -- the same answer as a dollar run with no scope behind it.
        self.assertEqual(replace_dollars_in_py_exp('$ * $i', ['item']),
                         'item * $i')

    def test_the_i_has_to_be_the_whole_of_the_name(self):
        # $item is a dollar beside a variable the program might have, not an
        # index. Only a bare i is the index.
        self.assertEqual(
            replace_dollars_in_py_exp('$item', ['_v'], index_exp='_i'), '_vitem')
        self.assertEqual(
            replace_dollars_in_py_exp('$i2', ['_v'], index_exp='_i'), '_vi2')

    def test_only_the_innermost_scope_has_an_index(self):
        # A list has one index to give, so $$i names nothing and is left alone.
        self.assertEqual(
            replace_dollars_in_py_exp('$$i', ['item', 'lst'], index_exp='i'),
            '$$i')

    def test_an_i_in_a_string_literal_is_string_content(self):
        self.assertEqual(
            replace_dollars_in_py_exp('"$i" + str($i)', ['item'], index_exp='i'),
            '"$i" + str(i)')

    def test_dollar_expr_parses_reads_it_as_a_value(self):
        self.assertEqual([dollar_expr_parses(s) for s in ('$i', '$ * $i', '$i(')],
                         [True, True, False])

    def test_eval_binds_the_index_beside_the_value(self):
        self.assertEqual(eval_dollar_expr('$ * $i', 5, index=3), 15)

    def test_eval_binds_it_beside_the_enclosing_scopes_too(self):
        lst = [3, 1, 5]
        self.assertEqual(
            eval_dollar_expr('($, $i, len($$))', 1, outer=(lst,), index=0),
            (1, 0, 3))

    def test_eval_without_an_index_is_an_error(self):
        with self.assertRaises(Exception):
            eval_dollar_expr('$ * $i', 5)

    def test_an_index_of_zero_still_counts_as_one(self):
        # Falsy, and bound all the same -- row 0 is a row like any other.
        self.assertEqual(eval_dollar_expr('$i', 'a', index=0), 0)


class TestDollarExprNamesIndex(unittest.TestCase):
    """Whether an expression asks for the index, which is what every caller
    choosing between `for item in lst` and `for i, item in enumerate(lst)` has to
    know. Asked through the substitution itself, so it tells code from string
    content the same way binding does."""

    def test_it_sees_the_index(self):
        self.assertTrue(dollar_expr_names_index('$ * $i'))
        self.assertTrue(dollar_expr_names_index('$i'))

    def test_a_column_that_doesnt_ask_for_it_says_so(self):
        self.assertFalse(dollar_expr_names_index('$'))
        self.assertFalse(dollar_expr_names_index("$['name'] + $item"))

    def test_a_literal_dollar_i_is_not_asking_for_it(self):
        self.assertFalse(dollar_expr_names_index('"$i"'))

    def test_a_literal_one_beside_a_real_dollar_is_still_string_content(self):
        # The scopes are bound to a stand-in before the question is asked, so a
        # run left as written can't make the text after it look like code.
        self.assertFalse(dollar_expr_names_index('$ + "$i"'))

    def test_half_typed_text_is_read_as_code_like_anywhere_else(self):
        # Not an expression yet, but the $i in it is one the user is writing
        # rather than one they quoted -- and asking must not crash on the way.
        self.assertTrue(dollar_expr_names_index('$i('))


class TestSuffixedDollarSigils(unittest.TestCase):
    """`$k`, `$v` and `$j` join `$i` as suffixes on a dollar run: the key, the
    value, and the position within a splat. Like `$i` they bind at depth 1 only
    and carry their own boundary, so `$key` is still a dollar beside a name."""

    def test_each_sigil_binds_what_it_is_given(self):
        for sigil, want in (('i', 'IDX'), ('k', 'KEY'), ('v', 'VAL'), ('j', 'POS')):
            with self.subTest(sigil=sigil):
                self.assertEqual(
                    replace_dollars_in_py_exp(f'${sigil}', ['_v'],
                                              bindings={sigil: want}),
                    want)

    def test_sigils_bind_alongside_each_other_and_the_bare_dollar(self):
        self.assertEqual(
            replace_dollars_in_py_exp('($, $k, $v, $i)', ['pair'],
                                      bindings={'i': 'n', 'k': 'k', 'v': 'v'}),
            '(pair, k, v, n)')

    def test_a_sigil_has_to_be_the_whole_of_the_name(self):
        # The trap the character class must not fall into: $key, $value and $ki
        # are all a bare dollar beside a variable the program might have.
        binds = {'i': '_i', 'k': '_k', 'v': '_vv', 'j': '_j'}
        for text, want in (('$key', '_vkey'), ('$value', '_vvalue'),
                           ('$ki', '_vki'), ('$k2', '_vk2'),
                           ('$vi', '_vvi'), ('$jk', '_vjk')):
            with self.subTest(text=text):
                self.assertEqual(
                    replace_dollars_in_py_exp(text, ['_v'], bindings=binds), want)

    def test_only_the_innermost_scope_has_them(self):
        # Same rule as $$i: suffixes bind at depth 1, so $$k names nothing and
        # is left as written. This is the known gap that keeps a column search
        # from reaching the key.
        self.assertEqual(
            replace_dollars_in_py_exp('$$k', ['item', 'lst'],
                                      bindings={'k': 'k'}),
            '$$k')

    def test_a_sigil_in_a_string_literal_is_string_content(self):
        self.assertEqual(
            replace_dollars_in_py_exp('"$k" + str($k)', ['_v'],
                                      bindings={'k': '_k'}),
            '"$k" + str(_k)')

    def test_an_unbound_sigil_is_left_as_written(self):
        # Which isn't Python, so it lands in the caller's except as "no value" --
        # the same answer $i already gives a caller with no index.
        self.assertEqual(replace_dollars_in_py_exp('$k', ['_v']), '$k')

    def test_index_exp_still_works_as_the_old_spelling(self):
        # string_visualizer and z_object_visualizer call it this way and are
        # deliberately untouched.
        self.assertEqual(
            replace_dollars_in_py_exp('$ * $i', ['item'], index_exp='i'),
            'item * i')

    def test_eval_binds_the_sigils_beside_the_value(self):
        self.assertEqual(
            eval_dollar_expr('($k, $v)', ('a', 1),
                             bindings={'k': 'a', 'v': 1}),
            ('a', 1))

    def test_eval_sigil_bindings_do_not_collide_with_the_value(self):
        # eval_dollar_expr binds the value to the internal name _v; a $v
        # binding must not land on top of it.
        self.assertEqual(
            eval_dollar_expr('($, $v)', ('a', 1), bindings={'v': 99}),
            (('a', 1), 99))

    def test_eval_binds_sigils_beside_index_and_outer_scopes(self):
        d = {'a': 1}
        self.assertEqual(
            eval_dollar_expr('($k, $v, $i, len($$))', ('a', 1), outer=(d,),
                             index=0, bindings={'k': 'a', 'v': 1}),
            ('a', 1, 0, 1))


class TestDollarExprSigils(unittest.TestCase):
    """Which suffixed dollars an expression actually binds -- the generalisation
    of dollar_expr_names_index, asked through the substitution so a sigil that is
    string content correctly answers no."""

    def test_it_reports_each_sigil_it_sees(self):
        self.assertEqual(dollar_expr_sigils('$k'), frozenset({'k'}))
        self.assertEqual(dollar_expr_sigils('$v > 3'), frozenset({'v'}))
        self.assertEqual(dollar_expr_sigils('($k, $v)'), frozenset({'k', 'v'}))
        self.assertEqual(dollar_expr_sigils('$ * $i'), frozenset({'i'}))

    def test_an_expression_with_no_sigils_is_empty(self):
        self.assertEqual(dollar_expr_sigils('$'), frozenset())
        self.assertEqual(dollar_expr_sigils("$['name'] + $item"), frozenset())

    def test_a_sigil_in_a_string_literal_is_not_named(self):
        self.assertEqual(dollar_expr_sigils('"$k"'), frozenset())
        self.assertEqual(dollar_expr_sigils('$ + "$k"'), frozenset())

    def test_deeper_runs_name_nothing(self):
        self.assertEqual(dollar_expr_sigils('$$k'), frozenset())

    def test_it_agrees_with_names_index_on_the_index(self):
        for expr in ('$ * $i', '$i', '$', "$['name'] + $item", '"$i"',
                     '$ + "$i"', '$i(' , '$$i'):
            with self.subTest(expr=expr):
                self.assertEqual('i' in dollar_expr_sigils(expr),
                                 dollar_expr_names_index(expr))


class TestParseSlotCols(unittest.TestCase):
    """A splat slot may carry `cols`: the sub-columns written against ONE
    splatted element. `children` (nested-visualizer config, keyed by type) and
    `cols` (sub-columns) are different axes and must not be conflated."""

    def test_it_reads_a_slots_sub_columns(self):
        config = ['$.name', {'expr': '*$.members', 'cols': ['$.who', '$.age']}]
        self.assertEqual(parse_slot_cols(config),
                         {'*$.members': ['$.who', '$.age']})

    def test_a_slot_without_cols_is_absent_rather_than_empty(self):
        self.assertEqual(parse_slot_cols(['$.name', {'expr': '$.x'}]), {})

    def test_children_are_not_read_as_cols(self):
        config = [{'expr': '$.x', 'children': {'builtins.dict': ['$.y']}}]
        self.assertEqual(parse_slot_cols(config), {})

    def test_a_slot_can_carry_both_without_either_leaking(self):
        config = [{'expr': '*$.m', 'cols': ['$.a'], 'children': ['$.b']}]
        self.assertEqual(parse_slot_cols(config), {'*$.m': ['$.a']})
        self.assertEqual(parse_slots(config)[1], {'*$.m': ['$.b']})

    def test_bare_strings_are_tolerated(self):
        self.assertEqual(parse_slot_cols(['$.a', '$.b']), {})

    def test_cols_survive_a_save_that_does_not_mention_them(self):
        # save_slots_at_path rewrites the expr list and keeps each surviving
        # slot's other keys, so an ancestor never clobbers a descendant's
        # sub-columns.
        set_line_config([{'expr': '$.name'}, {'expr': '*$.m', 'cols': ['$.who']}])
        save_slots_at_path([], ['$.name', '*$.m'])
        stored, _ = take_line_config()
        self.assertEqual(stored[1], {'expr': '*$.m', 'cols': ['$.who']})


class TestNewCodeCommand(unittest.TestCase):
    """The NewCode tuple: (name, code[, imports[, config]])."""

    def test_nothing_extra_is_the_pair(self):
        self.assertEqual(new_code_command(('g', 'f(x)')), ('g', 'f(x)'))

    def test_imports_are_the_third_slot(self):
        cmd = new_code_command(('g', 're.findall(p, s)'), lambda code: ['import re'])
        self.assertEqual(cmd, ('g', 're.findall(p, s)', ('import re',)))

    def test_config_is_the_fourth_slot_even_with_nothing_to_import(self):
        cmd = new_code_command(('g', 'f(x)'), config=['$k'])
        self.assertEqual(cmd, ('g', 'f(x)', (), ['$k']))

    def test_all_shapes_are_new_code(self):
        for cmd in [('g', 'f'), ('g', 'f', ()), ('g', 'f', (), ['$'])]:
            self.assertTrue(is_new_code(cmd))
        self.assertFalse(is_new_code(('g',)))
        self.assertFalse(is_new_code(['g', 'f']))


class TestLineConfigStore(unittest.TestCase):
    """The per-line slots the runner installs before a visualizer runs and
    collects after: what the line's `#%click` comment holds, in memory."""

    def setUp(self):
        set_line_config(None)

    def test_starts_empty_and_clean(self):
        self.assertEqual(take_line_config(), (None, False))

    def test_save_marks_dirty_and_is_read_back(self):
        save_slots_at_path([], ['$.x', '$.y'])
        self.assertEqual(take_line_config(),
                         ([{'expr': '$.x'}, {'expr': '$.y'}], True))

    def test_saving_no_columns_is_still_a_config(self):
        save_slots_at_path([], [])
        self.assertEqual(take_line_config(), ([], True))

    def test_nested_save_lands_under_the_slot(self):
        set_line_config(['$.a', '$.b'])
        save_slots_at_path(['$.b'], ['$.q'])
        self.assertEqual(take_line_config(), ([
            {'expr': '$.a'},
            {'expr': '$.b', 'children': [{'expr': '$.q'}]}], True))

    def test_take_hands_over_the_slots_and_resets(self):
        save_slots_at_path([], ['$.x'])
        slots, _ = take_line_config()
        slots.append('junk')
        self.assertEqual(take_line_config(), (None, False))

    def test_set_does_not_alias_the_caller_list(self):
        given = ['$.x']
        set_line_config(given)
        save_slots_at_path([], ['$.y'])
        self.assertEqual(given, ['$.x'])

    def test_set_ignores_a_non_list(self):
        set_line_config({'not': 'slots'})
        self.assertEqual(take_line_config(), (None, False))

    def test_sig_is_canonical(self):
        self.assertEqual(config_sig([{'b': 1, 'a': 2}]), config_sig([{'a': 2, 'b': 1}]))
        self.assertNotEqual(config_sig(['a']), config_sig(['b']))
        self.assertNotEqual(config_sig([]), config_sig(None))


class TestPeekLineConfig(unittest.TestCase):
    """Reading the store without emptying it: what a visualizer handing its
    own view state to a line it is writing needs, where take_line_config is
    the runner's and resets."""

    def setUp(self):
        set_line_config(None)

    def tearDown(self):
        set_line_config(None)

    def test_no_store_is_none(self):
        self.assertIsNone(peek_line_config())

    def test_the_root_slots_come_back_and_stay(self):
        set_line_config(['$.a', {'expr': '*$.m', 'cols': ['$.b']}])
        self.assertEqual(peek_line_config(),
                         ['$.a', {'expr': '*$.m', 'cols': ['$.b']}])
        self.assertEqual(take_line_config()[0],
                         ['$.a', {'expr': '*$.m', 'cols': ['$.b']}])

    def test_a_path_descends_into_a_slots_children(self):
        set_line_config(['$.a', {'expr': '$.b', 'children': ['$.q']}])
        self.assertEqual(peek_line_config(['$.b']), ['$.q'])

    def test_a_path_that_is_not_there_is_none(self):
        set_line_config(['$.a'])
        self.assertIsNone(peek_line_config(['$.b']))
        self.assertIsNone(peek_line_config(['$.a']))

    def test_the_answer_does_not_alias_the_store(self):
        set_line_config([{'expr': '$.a'}])
        peeked = peek_line_config()
        peeked[0]['expr'] = 'junk'
        self.assertEqual(peek_line_config(), [{'expr': '$.a'}])


class TestConfigComment(unittest.TestCase):
    """A `#%click` comment trails the line it configures."""

    def test_trailing_comment_binds_to_its_own_line(self):
        src = 'x = 1  #%click ["$.a"]\ny = 2\n'
        self.assertEqual(config_comment_index('x = 1  #%click ["$.a"]'), 7)
        self.assertEqual(parse_config_comment(src, 1), ['$.a'])

    def test_it_does_not_bind_to_any_other_line(self):
        src = 'x = 1  #%click ["$.a"]\ny = 2\n'
        self.assertIsNone(parse_config_comment(src, 2))

    def test_a_comment_on_its_own_line_binds_to_nothing_below(self):
        src = '#%click ["$.a"]\nx = 1\n'
        self.assertIsNone(parse_config_comment(src, 2))

    def test_the_marker_must_stand_alone(self):
        self.assertIsNone(config_comment_index('x = "#%click"'))
        self.assertIsNone(config_comment_index('x = 1  #%clicker [1]'))
        self.assertEqual(config_comment_index('x = 1\t#%click [1]'), 6)

    def test_line_out_of_range(self):
        src = 'x = 1  #%click ["$.a"]\n'
        self.assertIsNone(parse_config_comment(src, 0))
        self.assertIsNone(parse_config_comment(src, 99))

    def test_malformed_json_is_no_config(self):
        src = 'x = 1  #%click [not json\n'
        self.assertEqual(config_comment_index(src.split('\n')[0]), 7)
        self.assertIsNone(parse_config_comment(src, 1))

    def test_non_list_json_is_no_config(self):
        src = 'x = 1  #%click {"a": 1}\n'
        self.assertIsNone(parse_config_comment(src, 1))

    def test_no_columns_is_a_config(self):
        src = 'x = 1  #%click []\n'
        self.assertEqual(parse_config_comment(src, 1), [])

    def test_format_round_trips(self):
        slots = [{'expr': "$['name']", 'children': ['$.x']}]
        text = format_config_comment(slots)
        self.assertTrue(text.startswith(CONFIG_COMMENT_PREFIX + ' '))
        self.assertNotIn('\n', text)
        self.assertEqual(parse_config_comment('x = 1  ' + text + '\n', 1), slots)

    def test_format_keeps_unicode(self):
        self.assertIn('é', format_config_comment(['é']))


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
        spec = [{'expr': 'f', 'children': [{'expr': '$'}]}]
        exprs, children = parse_slots(spec)
        self.assertEqual(exprs, ['f'])
        self.assertEqual(children, {'f': [{'expr': '$'}]})

    def test_none_config(self):
        exprs, children = parse_slots(None)
        self.assertEqual(exprs, [])
        self.assertEqual(children, {})

    def test_expr_transform_applied(self):
        exprs, _ = parse_slots(['x', '$.y'],
                               expr_transform=lambda e: e if '$' in e else '$' + e)
        self.assertEqual(exprs, ['$x', '$.y'])

    def test_empty_children_not_stored(self):
        _, children = parse_slots([{'expr': 'f', 'children': []}])
        self.assertEqual(children, {})

    def test_invalid_entries_skipped(self):
        exprs, _ = parse_slots([123, {'no_expr': 1}, '$'])
        self.assertEqual(exprs, ['$'])


class TestSaveSlotsAtPath(unittest.TestCase):
    """save_slots_at_path persists a level's exprs at its path, preserving
    siblings and descendants' nested children."""

    def setUp(self):
        set_line_config(None)

    def slots(self):
        return take_line_config()[0]

    def test_save_root(self):
        save_slots_at_path([], ['$', 'f'])
        self.assertEqual(self.slots(), [{'expr': '$'}, {'expr': 'f'}])

    def test_nested_path_creates_structure(self):
        save_slots_at_path(['f'], ['$', '$.x'])
        self.assertEqual(self.slots(), [
            {'expr': 'f', 'children': [{'expr': '$'}, {'expr': '$.x'}]}])

    def test_root_resave_preserves_children_by_expr(self):
        save_slots_at_path([], ['$', 'f'])
        save_slots_at_path(['f'], ['$'])
        # Re-save the root with the columns reordered; the nested children
        # under 'f' must survive (an ancestor never clobbers a descendant).
        save_slots_at_path([], ['f', '$'])
        self.assertEqual(self.slots(), [
            {'expr': 'f', 'children': [{'expr': '$'}]}, {'expr': '$'}])

    def test_remove_expr_drops_its_subtree(self):
        save_slots_at_path([], ['a', 'b'])
        save_slots_at_path(['b'], ['$'])
        save_slots_at_path([], ['a'])
        self.assertEqual(self.slots(), [{'expr': 'a'}])

    def test_bare_string_entries_normalized(self):
        set_line_config(['a', 'b'])
        save_slots_at_path([], ['a', 'b', 'c'])
        self.assertEqual(self.slots(), [{'expr': 'a'}, {'expr': 'b'}, {'expr': 'c'}])

    def test_deep_path(self):
        save_slots_at_path(['a', 'b', 'c'], ['$'])
        self.assertEqual(self.slots(), [{'expr': 'a', 'children': [
            {'expr': 'b', 'children': [
                {'expr': 'c', 'children': [{'expr': '$'}]}]}]}])


class TestChildNestingKwargs(unittest.TestCase):
    """child_nesting_kwargs computes the kwargs handed to a child visualizer."""

    def test_returns_the_slots_nested_config(self):
        model = {
            '_slot_children': {'f': [{'expr': '$'}]},
            '_config_path': [],
        }
        kw = child_nesting_kwargs(model, 'f')
        self.assertEqual(kw, {'slots_config': [{'expr': '$'}],
                              'config_path': ['f'],
                              'persist': True})

    def test_no_children_returns_none_slots(self):
        model = {'_slot_children': {}, '_config_path': []}
        kw = child_nesting_kwargs(model, 'f')
        self.assertIsNone(kw['slots_config'])
        self.assertEqual(kw['config_path'], ['f'])

    def test_path_appends_step(self):
        model = {'_slot_children': {}, '_config_path': ['g']}
        kw = child_nesting_kwargs(model, 'f')
        self.assertEqual(kw['config_path'], ['g', 'f'])

    def test_an_unsaved_parent_has_unsaved_children(self):
        model = {'_slot_children': {}, '_config_path': ['g'], '_config_persist': False}
        self.assertFalse(child_nesting_kwargs(model, 'f')['persist'])

    def test_child_that_names_the_params_gets_them_all(self):
        def init_model(value, get_visualizer=None, slots_config=None,
                       config_path=None, persist=True):
            pass
        model = {'_slot_children': {'f': [{'expr': '$'}]}, '_config_path': []}
        kw = child_nesting_kwargs(model, 'f', init_model)
        self.assertEqual(kw, {'slots_config': [{'expr': '$'}],
                              'config_path': ['f'], 'persist': True})

    def test_child_that_ignores_nesting_is_handed_nothing(self):
        # And the config isn't even computed for it -- this is the hot path,
        # once per cell of a table.
        def init_model(value, get_visualizer=None, eval_in_scope=None):
            pass
        model = {'_slot_children': {'f': [{'expr': '$'}]}, '_config_path': []}
        self.assertEqual(child_nesting_kwargs(model, 'f', init_model), {})

    def test_child_naming_only_some_params_gets_only_those(self):
        def init_model(value, get_visualizer=None, slots_config=None):
            pass
        model = {'_slot_children': {'f': [{'expr': '$'}]}, '_config_path': []}
        self.assertEqual(child_nesting_kwargs(model, 'f', init_model),
                         {'slots_config': [{'expr': '$'}]})

    def test_child_taking_var_keyword_gets_them_all(self):
        def init_model(value, **kwargs):
            pass
        model = {'_slot_children': {}, '_config_path': []}
        self.assertEqual(set(child_nesting_kwargs(model, 'f', init_model)),
                         {'slots_config', 'config_path', 'persist'})


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


class TestImportsForCode(unittest.TestCase):
    """What an expression can't run without, read off the expression."""

    def test_a_regex_call_needs_re(self):
        self.assertEqual(imports_for_code("re.sub(r'a', '', s)"),
                         ('import re',))

    def test_the_others_this_code_reaches_for(self):
        self.assertEqual(imports_for_code('np.mean(xs)'),
                         ('import numpy as np',))
        self.assertEqual(imports_for_code('sum(math.isnan(x) for x in xs)'),
                         ('import math',))
        self.assertEqual(imports_for_code('Counter(xs)'),
                         ('from collections import Counter',))

    def test_the_reads_the_fetch_menu_writes(self):
        # The string visualizer's Fetch menu reads a URL or a file, and each
        # way of reading one names its module.
        self.assertEqual(imports_for_code('json.load(open(path1))'),
                         ('import json',))
        self.assertEqual(imports_for_code("list(csv.reader(open(p, newline='')))"),
                         ('import csv',))
        self.assertEqual(
            imports_for_code('urllib.request.urlopen(url1).read().decode()'),
            ('import urllib.request',))
        self.assertEqual(imports_for_code("pd.read_excel(p, sheet_name='a')"),
                         ('import pandas as pd',))
        self.assertEqual(
            imports_for_code('json.load(urllib.request.urlopen(url1))'),
            ('import json', 'import urllib.request'))

    def test_another_corner_of_urllib_is_not_the_request_one(self):
        # `import urllib.request` is what the reads here need; a file reaching
        # for another corner of the package says so itself.
        self.assertEqual(imports_for_code('urllib.parse.quote(s)'), ())

    def test_builtins_and_slices_need_nothing(self):
        self.assertEqual(imports_for_code('[x[1:] for x in data]'), ())
        self.assertEqual(imports_for_code('min(data)'), ())
        self.assertEqual(imports_for_code(''), ())

    def test_a_name_that_ends_in_the_module_is_not_the_module(self):
        for code in ('_re.match(p, s)', 'score.mean()', 'row.math.pi',
                     'self.np.array(xs)'):
            with self.subTest(code=code):
                self.assertEqual(imports_for_code(code), ())

    def test_what_the_user_searched_for_is_text_rather_than_code(self):
        # The pattern a string visualizer writes into its call is the user's
        # own text: `import numpy as np` on a file that hasn't got numpy is a
        # crash where the code it was added for ran fine.
        self.assertEqual(imports_for_code("re.split(r'np\\.', s)"),
                         ('import re',))
        self.assertEqual(imports_for_code('s.replace("Counter(", "")'), ())

    def test_an_f_string_is_code_and_is_read(self):
        self.assertEqual(imports_for_code("f'{math.pi:.2f}'"),
                         ('import math',))

    def test_several_needs_come_back_in_one_order(self):
        self.assertEqual(imports_for_code('Counter(np.round(xs))'),
                         ('import numpy as np', 'from collections import Counter'))


class TestPyExpAttrs(unittest.TestCase):
    """The attributes that hand expressions to the editor: the tooltip that
    lists them, the drag that carries the first, and the imports each one can't
    run without."""

    def exps(self, attrs, attr='snc-py-exps'):
        """What the editor reads back off the handle."""
        match = re.search(rf'{attr}="([^"]*)"', attrs)
        return json.loads(html.unescape(match.group(1))) if match else None

    def test_one_expression_is_a_list_of_one(self):
        # One shape for one expression and for five, so nothing downstream has
        # a second form to know about.
        self.assertEqual(py_exp_attrs('xs[0]', draggable=False),
                         ' snc-py-exps="[{&quot;expr&quot;: &quot;xs[0]&quot;}]"')

    def test_the_expression_comes_out_escaped(self):
        self.assertEqual(self.exps(py_exp_attrs('d["<k>"]')),
                         [{'expr': 'd["<k>"]'}])

    def test_a_handle_that_is_only_hovered_is_not_draggable(self):
        self.assertNotIn('draggable', py_exp_attrs('xs[0]', draggable=False))

    def test_a_handle_at_the_right_edge_reads_leftwards(self):
        self.assertIn(' snc-py-exp-align="right"',
                      py_exp_attrs('xs[0]', draggable=False, align='right'))

    def test_several_expressions_keep_the_order_they_were_given(self):
        # The first is the one the handle itself drags, so a caller puts the
        # one most likely wanted first and the rest are the tooltip's to offer.
        attrs = py_exp_attrs(['data.count("c")', 'set(data)'])
        self.assertEqual(self.exps(attrs),
                         [{'expr': 'data.count("c")'}, {'expr': 'set(data)'}])

    def test_each_expression_says_which_imports_it_needs(self):
        # Declared by whatever produced the code. Per expression, because the
        # editor adds the imports of the one that was actually taken -- a union
        # would import Counter for a dragged `min(data)`.
        attrs = py_exp_attrs([PyExp('Counter(data)',
                                    ('from collections import Counter',)),
                              'min(data)'])
        self.assertEqual(self.exps(attrs),
                         [{'expr': 'Counter(data)',
                           'imports': ['from collections import Counter']},
                          {'expr': 'min(data)'}])

    def test_an_expression_can_say_what_it_reads_as(self):
        # Two expressions on one handle are often two different values rather
        # than two spellings of one, and the tooltip has room to say which.
        attrs = py_exp_attrs([PyExp('data.count("c")', label='count'),
                              PyExp('[i for i in data if i == "c"]',
                                    label='matching items')])
        self.assertEqual([e.get('label') for e in self.exps(attrs)],
                         ['count', 'matching items'])

    def test_an_action_buttons_expressions_ride_on_their_own_attribute(self):
        # A different tooltip system picks them up; same list underneath.
        attrs = py_exp_attrs(PyExp('re.findall(p, s)', ('import re',)),
                             draggable=False, attr='data-action-expr')
        self.assertEqual(self.exps(attrs, 'data-action-expr'),
                         [{'expr': 're.findall(p, s)',
                           'imports': ['import re']}])
        self.assertNotIn('snc-py-exps', attrs)

    def test_an_expression_needing_nothing_says_nothing(self):
        self.assertEqual(self.exps(py_exp_attrs('xs[0]')), [{'expr': 'xs[0]'}])

    def test_an_expression_nobody_declared_for_still_says_what_it_needs(self):
        # An expression composed across visualizers -- a table's handle on a
        # column a string cell wrote -- has no producer left to declare for it:
        # only the text crosses the boundary, so the text is read.
        self.assertEqual(self.exps(py_exp_attrs("re.sub(r'a', '', item)")),
                         [{'expr': "re.sub(r'a', '', item)",
                           'imports': ['import re']}])

    def test_a_declaration_is_not_repeated_by_what_is_read(self):
        attrs = py_exp_attrs(PyExp('Counter(data)',
                                   ('from collections import Counter',)))
        self.assertEqual(self.exps(attrs)[0]['imports'],
                         ['from collections import Counter'])

    def test_a_declaration_and_what_is_read_both_travel(self):
        # A producer declaring one thing doesn't mean the expression needs
        # nothing else: a Counter over a column a string cell wrote needs both.
        attrs = py_exp_attrs(PyExp("Counter(re.sub(r'a', '', i) for i in xs)",
                                   ('from collections import Counter',)))
        self.assertEqual(self.exps(attrs)[0]['imports'],
                         ['from collections import Counter', 'import re'])

    def test_no_expression_means_no_attributes_at_all(self):
        for nothing in ('', None, [], (), [None, ''], [PyExp(None)]):
            self.assertEqual(py_exp_attrs(nothing), '')

    def test_an_expression_the_caller_has_none_of_drops_out(self):
        # A caller with nothing to offer for one of them passes None for it,
        # the way a caller with nothing at all passes None for the lot.
        self.assertEqual(self.exps(py_exp_attrs(['xs[0]', None])),
                         [{'expr': 'xs[0]'}])


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
        html_str = (f'<div><span{py_exp_attrs("min(data)")} '
                    f'class="py-exp-grab">5</span></div>')
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
                                       persist=True),
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
                                       config_path=[], persist=True),
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


class TestTruncateRepr(unittest.TestCase):
    """How a value is named where it is only being mentioned in passing -- a
    menu row, a preview chip -- rather than shown."""

    def test_a_short_value_reads_as_its_repr(self):
        self.assertEqual(truncate_repr('ab', 30), "'ab'")

    def test_a_long_one_is_shortened_from_the_middle(self):
        text = truncate_repr('x' * 100, 20)
        self.assertEqual(text, truncate_str(repr('x' * 100), 20))
        self.assertIn('…', text)
        self.assertLessEqual(len(text), 20)

    def test_a_repr_that_raises_names_nothing_rather_than_blowing_up(self):
        class Awkward:
            def __repr__(self):
                raise ValueError('no')
        self.assertEqual(truncate_repr(Awkward(), 30), '…')


class TestRenderExpandToggle(unittest.TestCase):
    """The expand/collapse bar the string and list visualizers share."""

    def test_it_reports_the_event_the_caller_named(self):
        bar = render_expand_toggle(False, 'ExpandToggle()')
        self.assertIn('snc-mouse-down="ExpandToggle()"', bar)

    def test_an_event_with_markup_in_it_is_escaped(self):
        bar = render_expand_toggle(False, "ExpandToggle(tag='<b>')")
        self.assertNotIn('<b>', bar)
        self.assertIn('&lt;b&gt;', bar)

    def test_a_closed_bar_offers_to_open(self):
        bar = render_expand_toggle(False, 'ExpandToggle()')
        self.assertIn('data-tooltip="Expand"', bar)
        self.assertIn('class="expand-toggle"', bar)

    def test_an_open_bar_offers_to_close_and_says_so_in_its_class(self):
        # The class is what turns the chevron over, and it sits on the bar
        # rather than on the container: the container of a table holds the
        # cells too, and their own panes are not what this opened.
        bar = render_expand_toggle(True, 'ExpandToggle()')
        self.assertIn('data-tooltip="Collapse"', bar)
        self.assertIn('class="expand-toggle expanded"', bar)

    def test_a_focused_bar_is_a_plain_control(self):
        bar = render_expand_toggle(False, 'ExpandToggle()')
        self.assertNotIn('snc-unfocused-clickable', bar)
        self.assertNotIn('draggable', bar)

    def test_a_bar_in_the_unfocused_preview_acts_without_taking_focus(self):
        bar = render_expand_toggle(False, 'ExpandToggle()', small=True)
        self.assertIn('snc-unfocused-clickable', bar)
        self.assertIn('draggable="false"', bar)


# === A scope, read as expressions and as prose ===============================
#
# The point of declaring one is that both halves come off it: a token the scope
# doesn't have can't be substituted and can't be described, so the two can't
# drift apart.

from visualizer_utils import Dollar, DollarScope


class TestDollarScope(unittest.TestCase):

    SCOPE = DollarScope(
        Dollar('$', 'the item', 'item'),
        Dollar('$i', 'the row number', 'i'),
        Dollar('$$', 'the whole list', 'data'),
    )

    def test_the_levels_come_out_in_depth_order(self):
        # What replace_dollars_in_py_exp wants, whatever order they were
        # declared in -- the declaration order is the PROSE's.
        self.assertEqual(self.SCOPE.replace_exps, ['item', 'data'])

    def test_the_sigils_come_out_as_bindings(self):
        self.assertEqual(self.SCOPE.bindings, {'i': 'i'})

    def test_the_legend_leads_with_a_sentence(self):
        self.assertEqual(self.SCOPE.legend,
                         '$ is the item, $i the row number, $$ the whole list')

    def test_the_two_halves_describe_the_same_tokens(self):
        named = set(self.SCOPE.tokens)
        bound = {'$'} | {f'${s}' for s in self.SCOPE.bindings}
        bound |= {'$' * n for n in range(1, len(self.SCOPE.replace_exps) + 1)}
        self.assertEqual(named, bound)

    def test_a_level_with_nothing_to_stand_for_is_bound_by_neither(self):
        # A source expression that can't be named drops $$ from the
        # substitution and from the prose together, which is the whole point.
        scope = DollarScope(Dollar('$', 'the item', 'item'),
                            Dollar('$$', 'the whole list', None))
        self.assertEqual(scope.replace_exps, ['item'])
        self.assertNotIn('$$', scope.legend)

    def test_a_run_past_the_end_is_not_invented(self):
        # $$$ named but $$ not: the substitution stops at the gap rather than
        # sliding the deeper expression into the shallower run.
        scope = DollarScope(Dollar('$', 'a', 'A'), Dollar('$$$', 'c', 'C'))
        self.assertEqual(scope.replace_exps, ['A'])

    def test_a_reading_of_a_token_is_not_a_scope_of_its_own(self):
        # `$[0]` teaches how to use `$`; it binds nothing and must not be
        # mistaken for a level.
        scope = DollarScope(Dollar('$', 'the match', 'mtch'),
                            Dollar('$[0]', 'its text'),
                            Dollar('$$', 'the whole string', 's'))
        self.assertEqual(scope.replace_exps, ['mtch', 's'])
        self.assertEqual(scope.bindings, {})
        self.assertIn('$[0] its text', scope.legend)

    def test_an_empty_slot_is_dropped_rather_than_punctuated(self):
        # Scopes are built with conditional entries; a falsy one must not leave
        # a stray comma behind.
        scope = DollarScope(Dollar('$', 'the item', 'item'), None,
                            Dollar('$$', 'the list', 'data'))
        self.assertEqual(scope.legend, '$ is the item, $$ the list')

    def test_a_scope_is_hashable_so_it_can_be_a_constant(self):
        self.assertEqual(self.SCOPE, DollarScope(*self.SCOPE.dollars))



class TestLiveOnly(unittest.TestCase):
    """The live-only switch (clickacode.liveOnlyVisualizers): nothing a visualizer
    renders may hand code to the editor. The shared helpers that write drag
    handles and action-button expressions are where most of them come from, so
    they go quiet under the flag and every visualizer built on them follows."""

    def setUp(self):
        from visualizer_utils import set_live_only
        set_live_only(True)

    def tearDown(self):
        from visualizer_utils import set_live_only
        set_live_only(False)

    def test_flag_is_off_by_default_and_toggles(self):
        from visualizer_utils import set_live_only, is_live_only
        self.assertTrue(is_live_only())
        set_live_only(False)
        self.assertFalse(is_live_only())

    def test_py_exp_attrs_writes_nothing(self):
        self.assertEqual(py_exp_attrs('x[0]'), '')
        self.assertEqual(py_exp_attrs([PyExp('x', ('import re',))], attr='data-action-expr'), '')

    def test_wrap_drag_grab_leaves_the_html_bare(self):
        self.assertEqual(wrap_drag_grab('<b>1</b>', ('x', 'x')), '<b>1</b>')

    def test_readings_are_not_added_to_a_bare_child(self):
        from visualizer_utils import add_drag_readings
        child = wrap_drag_grab('<b>1</b>', (None, 'x[0]'))
        self.assertEqual(add_drag_readings(child, 'x[0]', ['[item for item in x]']), '<b>1</b>')
        self.assertEqual(defer_drag_grab(child, 'x[0]'), '<b>1</b>')

if __name__ == '__main__':
    unittest.main()
