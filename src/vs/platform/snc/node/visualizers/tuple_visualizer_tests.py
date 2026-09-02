"""Tests for tuple_visualizer.py -- the `([subvis], [subvis], [subvis])` renderer.

Run this test file directly:
    python3 src/vs/platform/snc/node/visualizers/tuple_visualizer_tests.py

Or use pytest with verbose output:
    python3 -m pytest src/vs/platform/snc/node/visualizers/tuple_visualizer_tests.py -v
"""

import html as html_module
import re as _re
import unittest
from collections import namedtuple
from dataclasses import dataclass

from tuple_visualizer import (
    can_visualize, get_fields, init_model, update, visualize, element_slots,
)
import tuple_visualizer
import table_visualizer

from visualizer_utils import (
    CHILD_SOURCE_BINDER, ChildEvent, MAX_NEST_DEPTH, py_exp_attrs,
    set_line_config, take_line_config, truncate_repr, wrap_drag_grab,
    label_readings,
)


Point = namedtuple('Point', ['x', 'y'])


def exp_attr(*exprs):
    """The `snc-py-exps` attribute a handle offering these expressions carries,
    as it reads inside the tag it was written into."""
    return py_exp_attrs(list(exprs), draggable=False).strip()


def reads_attr(primary, *extras):
    """The `snc-py-exps` attribute of a handle offering several readings, named
    the way the tooltip names them (One / List / Dict)."""
    return py_exp_attrs(label_readings(primary, extras), draggable=False).strip()


def child_keys(out: str) -> list:
    """The child keys the rendering wrapped its subvisualizers in, in order."""
    return [eval(html_module.unescape(k))
            for k in _re.findall(r'snc-child-key="([^"]*)"', out)]


def text_of(out: str) -> str:
    """What the rendering reads as with the tags taken off."""
    return html_module.unescape(_re.sub(r'<[^>]*>', '', out))


# =============================================================================
# Visualizer adapters (mirroring how python_runner presents modules)
# =============================================================================

class _GenericVis:
    """Fallback visualizer for tests (matches GenericVisualizer in python_runner)."""
    def can_visualize(self, value):
        return True

    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return None

    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None,
                  max_height=None, small=False, var_and_exp=None):
        return wrap_drag_grab(html_module.escape(repr(value)), var_and_exp)

    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return (model, [])


class _TupleVisAdapter:
    def can_visualize(self, value):
        return tuple_visualizer.can_visualize(value)

    def get_fields(self, value):
        return tuple_visualizer.get_fields(value)

    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None, **kwargs):
        return tuple_visualizer.init_model(value, get_visualizer, eval_in_scope=eval_in_scope,
                                           var_and_exp=var_and_exp, **kwargs)

    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None,
                  max_height=None, small=False, var_and_exp=None, every_row_exps=None):
        return tuple_visualizer.visualize(value, model, get_visualizer, eval_in_scope,
                                          max_width=max_width, max_height=max_height,
                                          small=small, var_and_exp=var_and_exp,
                                          every_row_exps=every_row_exps)

    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return tuple_visualizer.update(event, var_and_exp, model, value, get_visualizer,
                                       eval_in_scope=eval_in_scope)


class _ListVisAdapter:
    """Adapter wrapping the table_visualizer module (for cross-type nesting tests)."""
    def can_visualize(self, value):
        return table_visualizer.can_visualize(value)

    def get_fields(self, value):
        return table_visualizer.get_fields(value)

    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None, **kwargs):
        return table_visualizer.init_model(value, get_visualizer, eval_in_scope=eval_in_scope,
                                           var_and_exp=var_and_exp, **kwargs)

    def visualize(self, value, model, get_visualizer, eval_in_scope=None, max_width=None,
                  max_height=None, small=False, var_and_exp=None):
        return table_visualizer.visualize(value, model, get_visualizer, eval_in_scope,
                                          max_width=max_width, max_height=max_height,
                                          small=small, var_and_exp=var_and_exp)

    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        return table_visualizer.update(event, var_and_exp, model, value, get_visualizer,
                                       eval_in_scope=eval_in_scope)


_generic_vis = _GenericVis()
_tuple_vis = _TupleVisAdapter()
_list_vis = _ListVisAdapter()


def _get_visualizer(value):
    """The runtime priority, as far as these tests need it."""
    if isinstance(value, tuple):
        return _tuple_vis
    if isinstance(value, (list, dict)):
        return _list_vis
    return _generic_vis


def _generic_only(value):
    return _generic_vis


def make_mouse_down_event(python_event_str: str, detail: int = 1) -> dict:
    return {
        'pythonEventStr': python_event_str,
        'eventJSON': {
            'type': 'mousedown', 'button': 0, 'buttons': 1, 'detail': detail,
        },
    }


def setUpModule():
    set_line_config(None)


# =============================================================================
# can_visualize
# =============================================================================

class TestCanVisualize(unittest.TestCase):
    def test_it_claims_tuples(self):
        self.assertTrue(can_visualize((1, 2)))
        self.assertTrue(can_visualize(()))
        self.assertTrue(can_visualize((1,)))

    def test_it_claims_named_tuples(self):
        # A named tuple IS a tuple; leaving it to the object visualizer would
        # show it as dir() minus object(), which is `count` and `index` before
        # anything the user named.
        self.assertTrue(can_visualize(Point(1, 2)))

    def test_it_leaves_other_containers_alone(self):
        self.assertFalse(can_visualize([1, 2]))
        self.assertFalse(can_visualize({'a': 1}))
        self.assertFalse(can_visualize({1, 2}))
        self.assertFalse(can_visualize('ab'))
        self.assertFalse(can_visualize(1))
        self.assertFalse(can_visualize(None))

    def test_it_sorts_ahead_of_the_object_visualizer(self):
        # Visualizers are globbed in filename order, first match wins, and
        # z_object_visualizer claims everything -- so the file has to sort
        # before it.
        self.assertLess('tuple_visualizer.py', 'z_object_visualizer.py')


# =============================================================================
# get_fields / element_slots -- how a tuple is addressed from outside and in
# =============================================================================

class TestFields(unittest.TestCase):
    def test_a_tuple_is_addressed_by_position(self):
        self.assertEqual(get_fields(('a', 1, None)), ['$[0]', '$[1]', '$[2]'])

    def test_an_empty_tuple_has_no_fields(self):
        self.assertEqual(get_fields(()), [])

    def test_a_named_tuple_is_addressed_by_name(self):
        self.assertEqual(get_fields(Point(1, 2)), ['$.x', '$.y'])

    def test_element_slots_carry_the_label_a_named_tuple_shows(self):
        self.assertEqual(element_slots(Point(1, 2)), [('x', '$.x'), ('y', '$.y')])
        self.assertEqual(element_slots((7, 8)), [(None, '$[0]'), (None, '$[1]')])

    def test_a_long_tuple_stops_at_the_cap(self):
        # A rerun happens every ~100ms and every element is a visualizer of its
        # own, so `tuple(range(10000))` must not become 10000 of them -- nor
        # 10000 columns in a table that sampled one.
        big = tuple(range(10_000))
        self.assertEqual(len(element_slots(big)), tuple_visualizer.MAX_ELEMENTS)
        self.assertEqual(len(get_fields(big)), tuple_visualizer.MAX_ELEMENTS)

    def test_a_table_of_tuples_gets_a_column_per_position(self):
        # What get_fields is for: an enclosing table asks each row what it has
        # to show.
        model = table_visualizer.init_model([(1, 'a'), (2, 'b')], _get_visualizer)
        out = table_visualizer.visualize([(1, 'a'), (2, 'b')], model,
                                         _get_visualizer, None)
        self.assertIn('$[0]', out)
        self.assertIn('$[1]', out)


# =============================================================================
# init_model
# =============================================================================

class TestInitModel(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def test_it_returns_the_expected_structure(self):
        model = init_model((1, 2), _get_visualizer)
        self.assertIn('children', model)
        self.assertIn('handledKeys', model)
        self.assertIsNone(model.get('focused_child'))
        self.assertEqual(model['_config_path'], [])
        self.assertTrue(model['_config_persist'])
        self.assertEqual(model['_slot_children'], {})

    def test_it_builds_a_child_model_per_element(self):
        model = init_model((1, [2, 3]), _get_visualizer)
        self.assertEqual(sorted(model['children']), ['$[0]', '$[1]'])

    def test_an_empty_tuple_has_no_children(self):
        self.assertEqual(init_model((), _get_visualizer)['children'], {})

    def test_it_remembers_the_expression_the_line_showed(self):
        model = init_model((1, 2), _get_visualizer, var_and_exp=('t', '(1, 2)'))
        self.assertEqual(model['_source_expr'], 't')

    def test_a_line_with_no_variable_is_named_by_its_expression(self):
        model = init_model((1, 2), _get_visualizer, var_and_exp=(None, 'f()'))
        self.assertEqual(model['_source_expr'], 'f()')

    def test_children_are_handed_their_slot_of_the_saved_config(self):
        slots = [{'expr': '$[1]', 'children': [{'expr': '$.name'}]}]
        model = init_model((1, [{'name': 'a'}]), _get_visualizer, slots_config=slots)
        self.assertEqual(model['_slot_children'], {'$[1]': [{'expr': '$.name'}]})
        child = model['children']['$[1]']
        self.assertEqual(child['_config_path'], ['$[1]'])
        self.assertIn('$.name', child['columns'])

    def test_a_child_saves_at_its_own_path_under_the_tuple(self):
        # The tuple never writes a slot list of its own -- its elements are the
        # value's, not the user's -- but a nested table saving its columns has
        # to land under the element it is showing.
        set_line_config(None)
        model = init_model((1, [{'a': 1}]), _get_visualizer)
        child = model['children']['$[1]']
        self.assertEqual(child['_config_path'], ['$[1]'])

    def test_a_child_not_naming_the_nesting_params_is_not_handed_them(self):
        # Would TypeError if the kwargs were passed regardless.
        model = init_model((1, 2), _generic_only)
        self.assertEqual(sorted(model['children']), ['$[0]', '$[1]'])

    def test_persist_false_travels_down_to_the_children(self):
        model = init_model((1, [2]), _get_visualizer, persist=False)
        self.assertFalse(model['_config_persist'])
        self.assertFalse(model['children']['$[1]']['_config_persist'])

    def test_the_depth_cap_stops_the_nesting(self):
        deep = ['$'] * MAX_NEST_DEPTH
        model = init_model((1, 2), _get_visualizer, config_path=deep)
        self.assertTrue(model['_too_deep'])
        self.assertEqual(model['children'], {})

    def test_it_survives_without_a_visualizer_resolver(self):
        model = init_model((1, 2))
        self.assertEqual(model['children'], {})

    def test_handled_keys_are_aggregated_from_the_children(self):
        class _KeyVis(_GenericVis):
            def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
                return {'handledKeys': ['Enter']}

        model = init_model((1, 2), lambda v: _KeyVis())
        self.assertIn('Enter', model['handledKeys'])


# =============================================================================
# visualize -- ([subvis1], [subvis2], [subvis3])
# =============================================================================

class TestVisualize(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def render(self, value, **kwargs):
        var_and_exp = kwargs.pop('var_and_exp', ('t', 't'))
        model = kwargs.pop('model', None)
        if model is None:
            model = init_model(value, _get_visualizer, var_and_exp=var_and_exp)
        return visualize(value, model, _get_visualizer, None,
                         var_and_exp=var_and_exp, **kwargs)

    def test_it_reads_as_a_tuple(self):
        self.assertEqual(text_of(self.render((1, 'a'))), "(1, 'a')")

    def test_an_empty_tuple_reads_as_a_pair_of_parens(self):
        self.assertEqual(text_of(self.render(())), '()')

    def test_a_one_element_tuple_keeps_its_trailing_comma(self):
        # Without it `(1,)` reads as a parenthesised 1, which is a different
        # value entirely.
        self.assertEqual(text_of(self.render((1,))), '(1,)')

    def test_each_element_is_a_child_in_order(self):
        out = self.render((1, 2, 3))
        self.assertEqual(child_keys(out), ['$[0]', '$[1]', '$[2]'])

    def test_each_child_is_handed_its_own_access_path(self):
        out = self.render(('a', 'b'), var_and_exp=('t', 't'))
        self.assertIn(exp_attr('t[0]'), out)
        self.assertIn(exp_attr('t[1]'), out)

    def test_the_access_path_is_built_from_the_expression_when_there_is_no_name(self):
        out = self.render((1, 2), var_and_exp=(None, 'f()'))
        self.assertIn(exp_attr('f()[0]'), out)

    def test_a_line_that_names_nothing_still_renders(self):
        out = self.render((1, 2), var_and_exp=None)
        self.assertEqual(text_of(out), '(1, 2)')
        self.assertNotIn('snc-py-exps', out)

    def test_the_parens_carry_the_whole_tuple(self):
        # The elements carry their own handles, so a handle around all of them
        # would claim every hover in between -- the parens are what is left to
        # hang the whole value on.
        out = self.render((1, 2), var_and_exp=('t', 't'))
        self.assertEqual(out.count(exp_attr('t')), 2)

    def test_it_renders_inline_rather_than_as_a_container(self):
        out = self.render((1, 2))
        self.assertIn('snc-tuple-visualizer', out)
        self.assertNotIn('visualizer-container', out)

    def test_it_offers_no_search_and_no_actions(self):
        out = self.render((1, 2, 3))
        self.assertNotIn('search-box', out)
        self.assertNotIn('search-div', out)
        self.assertNotIn('data-action-expr', out)
        self.assertNotIn('snc-key-down', out)
        self.assertNotIn('<input', out)

    def test_a_long_tuple_says_how_much_it_is_not_showing(self):
        big = tuple(range(100))
        out = self.render(big)
        cap = tuple_visualizer.MAX_ELEMENTS
        self.assertEqual(len(child_keys(out)), cap)
        self.assertIn(f'+{100 - cap}', text_of(out))

    def test_the_depth_cap_renders_a_plain_repr(self):
        deep = ['$'] * MAX_NEST_DEPTH
        model = init_model((1, 2), _get_visualizer, config_path=deep)
        out = visualize((1, 2), model, _get_visualizer, None, var_and_exp=('t', 't'))
        self.assertIn('(1, 2)', text_of(out))
        self.assertEqual(child_keys(out), [])

    def test_it_takes_in_a_renamed_variable(self):
        # The model outlives an edit to the line; cells evaluated against the
        # old name would blank out.
        model = init_model((1, 2), _get_visualizer, var_and_exp=('t', 't'))
        out = visualize((1, 2), model, _get_visualizer, None, var_and_exp=('u', 'u'))
        self.assertIn(exp_attr('u[0]'), out)


class TestNamedTupleVisualize(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def render(self, value, **kwargs):
        model = init_model(value, _get_visualizer, var_and_exp=('p', 'p'))
        return visualize(value, model, _get_visualizer, None,
                         var_and_exp=('p', 'p'), **kwargs)

    def test_it_reads_the_way_the_named_tuple_does(self):
        self.assertEqual(text_of(self.render(Point(1, 2))), 'Point(x=1, y=2)')

    def test_the_class_name_reads_as_a_name(self):
        # It is the one word on screen that came out of the user's program.
        self.assertIn('<span class="name">Point</span>', self.render(Point(1, 2)))

    def test_its_elements_are_grabbed_by_name(self):
        out = self.render(Point(1, 2))
        self.assertEqual(child_keys(out), ['$.x', '$.y'])
        self.assertIn(exp_attr('p.x'), out)
        self.assertIn(exp_attr('p.y'), out)

    def test_a_one_field_named_tuple_takes_no_trailing_comma(self):
        # `Single(x=1)` is already unambiguous -- the comma is a plain tuple's
        # way of saying it is one.
        Single = namedtuple('Single', ['x'])
        self.assertEqual(text_of(self.render(Single(1))), 'Single(x=1)')


# =============================================================================
# Children know they are children
# =============================================================================

class TestChildrenRenderAsChildren(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def render(self, value, model=None):
        if model is None:
            model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        return model, visualize(value, model, _get_visualizer, None,
                                var_and_exp=('t', 't'))

    def test_an_unfocused_list_collapses_to_its_repr(self):
        value = (1, [{'a': 1}, {'a': 2}])
        _, out = self.render(value)
        self.assertIn(html_module.escape(truncate_repr([{'a': 1}, {'a': 2}])), out)
        self.assertNotIn('list-table-scroll', out)

    def test_a_focused_list_child_gets_its_table(self):
        value = (1, [{'a': 1}, {'a': 2}])
        model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        _, out = self.render(value, model)
        self.assertIn('list-table-scroll', out)

    def test_a_focused_child_closes_when_the_tuple_itself_is_not_focused(self):
        # The line the tuple is on lost focus (the user clicked into another
        # line's visualizer): its opened element closes with it, the way a
        # table's cell does. The element stays the focused child, so clicking
        # back into the line finds it open again.
        value = (1, [{'a': 1}, {'a': 2}])
        model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        out = visualize(value, model, _get_visualizer, None,
                        var_and_exp=('t', 't'), small=True)
        self.assertNotIn('list-table-scroll', out)
        self.assertEqual(model['focused_child'], '$[1]')

    def test_a_nested_tuple_still_reads_as_a_tuple(self):
        # A tuple costs a repr's worth of room to draw properly, so unlike a
        # table it has no reason to collapse when nobody is looking at it.
        _, out = self.render((1, (2, 3)))
        self.assertEqual(text_of(out), '(1, (2, 3))')
        self.assertIn(exp_attr('t[1][0]'), out)

    def test_a_tuple_in_a_table_cell_keeps_its_elements(self):
        rows = [{'pair': (1, 2)}]
        model = table_visualizer.init_model(rows, _get_visualizer,
                                            var_and_exp=('rows', 'rows'))
        out = table_visualizer.visualize(rows, model, _get_visualizer, None,
                                         var_and_exp=('rows', 'rows'))
        self.assertIn('snc-tuple-visualizer', out)


# =============================================================================
# update -- routing to the children, and nothing else
# =============================================================================

@dataclass(frozen=True)
class _Copy:
    """A clipboard command, duck-typed the way each visualizer declares its
    own (see nest_child_command)."""
    text: str


class _RecordingVis(_GenericVis):
    """A child that records the events it was handed, and answers with code.

    It writes its code against `_snc_cell_`, the binder every nested visualizer
    is given for the value it is showing -- so what comes back out of the tuple
    is exactly the question these tests are asking.
    """

    def __init__(self):
        self.events = []

    def init_model(self, value, get_visualizer=None, eval_in_scope=None, var_and_exp=None):
        return {'handledKeys': ['Enter'], 'seen': 0}

    def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
        self.events.append((event, var_and_exp))
        model = dict(model, seen=model.get('seen', 0) + 1)
        return (model, [('n', 'len(_snc_cell_)'),
                        _Copy(text='len(_snc_cell_)')])


class TestUpdate(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def test_an_event_that_is_not_a_child_event_changes_nothing(self):
        model = init_model((1, 2), _get_visualizer)
        event = make_mouse_down_event('None')
        new_model, cmds = update(event, ('t', 't'), model, (1, 2), _get_visualizer)
        self.assertEqual(cmds, [])
        self.assertIsNone(new_model.get('focused_child'))

    def test_an_empty_event_changes_nothing(self):
        model = init_model((1, 2), _get_visualizer)
        new_model, cmds = update(None, ('t', 't'), model, (1, 2), _get_visualizer)
        self.assertIs(new_model, model)
        self.assertEqual(cmds, [])

    def test_the_first_mousedown_on_an_unfocused_child_pins_focus(self):
        value = (1, [2, 3])
        model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        new_model, cmds = update(event, ('t', 't'), model, value, _get_visualizer)
        self.assertEqual(new_model['focused_child'], '$[1]')
        self.assertEqual(cmds, [])

    def test_a_focused_child_receives_the_event(self):
        child = _RecordingVis()
        value = (1, 2)
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        model = init_model(value, get_vis, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        new_model, _ = update(event, ('t', 't'), model, value, get_vis)
        self.assertEqual(len(child.events), 1)
        self.assertEqual(new_model['children']['$[1]']['seen'], 1)

    def test_the_child_is_handed_the_value_at_its_own_key(self):
        child = _RecordingVis()
        seen = []

        class _Watch(_RecordingVis):
            def update(self, event, var_and_exp, model, value, get_visualizer=None, eval_in_scope=None):
                seen.append(value)
                return super().update(event, var_and_exp, model, value, get_visualizer, eval_in_scope)

        watcher = _Watch()
        value = ('a', 'b')
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else watcher
        model = init_model(value, get_vis, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        update(event, ('t', 't'), model, value, get_vis)
        self.assertEqual(seen, ['b'])

    def test_a_childs_generated_code_is_resolved_to_the_element(self):
        child = _RecordingVis()
        value = (1, [2, 3])
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        model = init_model(value, get_vis, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        _, cmds = update(event, ('t', 't'), model, value, get_vis)
        self.assertEqual(cmds, [('n', 'len((t[1]))'),
                                _Copy(text='len((t[1]))')])

    def test_a_named_tuples_child_code_is_resolved_by_name(self):
        child = _RecordingVis()
        value = Point(1, [2, 3])
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        model = init_model(value, get_vis, var_and_exp=('p', 'p'))
        model['focused_child'] = '$.y'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$.y', py_ev_str='None')))
        _, cmds = update(event, ('p', 'p'), model, value, get_vis)
        self.assertEqual(cmds, [('n', 'len((p.y))'),
                                _Copy(text='len((p.y))')])

    def test_a_nested_tuple_extends_the_binder_instead_of_resolving_it(self):
        # A tuple has no scope of its own -- it is a way THROUGH to an element.
        # Its parent is the one that knows both spellings of where the value
        # came from (a table's column stays row-generic, its clipboard names
        # the row), so a nested tuple hands the binder back on with its own
        # element access on the end and lets the parent finish the job. It must
        # not resolve it here: doing so is what made a table's derived column
        # read `x[0][0]` instead of `$[0]`.
        child = _RecordingVis()
        value = (1, [2, 3])
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        nested = (None, CHILD_SOURCE_BINDER)
        model = init_model(value, get_vis, var_and_exp=nested, config_path=['$'])
        # What rendering adopted: the concrete cell it was drawn in. Tempting,
        # and wrong, for code headed back up to the table.
        model['_source_expr'] = 'x[0]'
        model['focused_child'] = '$[1]'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        _, cmds = update(event, nested, model, value, get_vis)
        self.assertEqual(cmds, [('n', f'len(({CHILD_SOURCE_BINDER}[1]))'),
                                _Copy(text=f'len(({CHILD_SOURCE_BINDER}[1]))')])

    def test_a_nested_named_tuple_extends_the_binder_by_name(self):
        child = _RecordingVis()
        value = Point(1, [2, 3])
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        nested = (None, CHILD_SOURCE_BINDER)
        model = init_model(value, get_vis, var_and_exp=nested, config_path=['$'])
        model['focused_child'] = '$.y'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$.y', py_ev_str='None')))
        _, cmds = update(event, nested, model, value, get_vis)
        self.assertEqual(cmds[0], ('n', f'len(({CHILD_SOURCE_BINDER}.y))'))

    def test_handled_keys_are_reaggregated_after_a_child_event(self):
        child = _RecordingVis()
        value = (1, 2)
        get_vis = lambda v: _tuple_vis if isinstance(v, tuple) else child
        model = init_model(value, get_vis, var_and_exp=('t', 't'))
        model['focused_child'] = '$[1]'
        event = make_mouse_down_event(
            repr(ChildEvent(child_key='$[1]', py_ev_str='None')))
        new_model, _ = update(event, ('t', 't'), model, value, get_vis)
        self.assertIn('Enter', new_model['handledKeys'])


# =============================================================================
# Through a real table: `x = [('asdf', 2)]`
# =============================================================================

class TestGeneralizesToTheEnclosingTable(unittest.TestCase):
    """Code made inside a tuple that sits in a table CELL has to come out as a
    column of that table -- one expression every row answers -- and not as the
    one row it was made in."""

    # `x = [('asdf', 2)]`, one `$` column, so the cell holds the whole tuple --
    # the shape the screenshot shows, and what a saved config or a column the
    # user removed leaves behind.
    DOUBLE = ([('asdf', 2)], ['$[0]'])
    # `x = [(('asdf', 9), 2)]` -- a tuple inside the tuple inside the cell.
    TRIPLE = ([(('asdf', 9), 2)], ['$[0]', '$[0]'])

    def setUp(self):
        set_line_config(None)
        self.child = _RecordingVis()

    def get_vis(self, v):
        if isinstance(v, tuple):
            return _tuple_vis
        if isinstance(v, (list, dict)):
            return _list_vis
        return self.child

    def fire(self, case):
        """Open the cell, open each tuple down to the string, and let the child
        showing it answer with code. Returns (table_model, commands)."""
        value, inner_path = case
        scope = {'x': value}
        eis = lambda code: eval(code, scope)
        ve = ('x', 'x')
        model = table_visualizer.init_model(value, self.get_vis, eval_in_scope=eis,
                                            var_and_exp=ve, slots_config=['$'])
        draw = lambda: table_visualizer.visualize(value, model, self.get_vis, eis,
                                                  var_and_exp=ve)
        path = [child_keys(draw())[0]] + list(inner_path)
        # Focus a level at a time, redrawing between: a child only builds its
        # own children once it is drawn open.
        node = model
        for key in path[:-1]:
            node['focused_child'] = key
            draw()
            node = node['children'][key]
        node['focused_child'] = path[-1]
        draw()

        py_ev = 'None'
        for key in reversed(path):
            py_ev = repr(ChildEvent(child_key=key, py_ev_str=py_ev))
        return table_visualizer.update(make_mouse_down_event(py_ev), ve, model,
                                       value, self.get_vis, eval_in_scope=eis)

    def derived_column(self, model):
        cols = [c for c in (model.get('columns') or {}) if c != '$']
        self.assertEqual(len(cols), 1, f'expected one derived column, got {cols}')
        return cols[0]

    def _assert_generic(self, case, answer):
        model, _ = self.fire(case)
        col = self.derived_column(model)
        self.assertIn('$', col)
        self.assertNotIn('x[0]', col)
        self.assertNotIn(CHILD_SOURCE_BINDER, col)
        # `$` is the row -- the whole tuple -- so the column has to index its
        # way down to the element the code was made in, and answer for any row.
        self.assertEqual(eval_column(col, case[0]), [answer])

    def test_a_tuple_deep_the_column_is_row_generic(self):
        self._assert_generic(self.DOUBLE, len('asdf'))

    def test_two_tuples_deep_the_column_is_row_generic(self):
        self._assert_generic(self.TRIPLE, len('asdf'))

    def _assert_concrete_clipboard(self, case, answer):
        value, _ = case
        _, cmds = self.fire(case)
        copies = [c for c in cmds if isinstance(c, _Copy)]
        self.assertEqual(len(copies), 1, f'expected one copy, got {cmds}')
        # Pasted into the editor as-is, so it has to name a value that exists.
        self.assertNotIn('$', copies[0].text)
        self.assertNotIn(CHILD_SOURCE_BINDER, copies[0].text)
        self.assertEqual(eval(copies[0].text, {'x': value}), answer)

    def test_a_tuple_deep_the_clipboard_names_this_row(self):
        self._assert_concrete_clipboard(self.DOUBLE, len('asdf'))

    def test_two_tuples_deep_the_clipboard_names_this_row(self):
        self._assert_concrete_clipboard(self.TRIPLE, len('asdf'))


def eval_column(col: str, value):
    """A derived column read over every row, the way the table reads it."""
    from visualizer_utils import eval_dollar_expr
    return [eval_dollar_expr(col, row) for row in value]


# =============================================================================
# The other reading: the same element, down every row
# =============================================================================

class TestEveryRowReading(unittest.TestCase):
    """An element of a tuple in a table's CELL is two things at once: the value
    in this row, and the value every row has at that position.

    A column header says the second thing for a column, so a table whose
    columns are `$[0]`/`$[1]` needs nothing here. But under one `$` column the
    cell holds the whole tuple and the only header says `$` -- so the element's
    own handle is the one place left to offer it.
    """

    def setUp(self):
        set_line_config(None)

    def every_row(self, sub_expr):
        """Stands in for the table: `$[1]` -> `[item[1] for item in x]`."""
        return [f'[item{sub_expr[1:]} for item in x]']

    def render(self, value=('asdf', 2), cell='x[0]', every_row=True):
        model = init_model(value, _get_visualizer, var_and_exp=(None, cell))
        return visualize(value, model, _get_visualizer, None,
                         var_and_exp=(None, cell),
                         every_row_exps=self.every_row if every_row else None)

    def test_an_element_offers_the_column_reading_too(self):
        self.assertIn(reads_attr('x[0][1]',  '[item[1] for item in x]'),
                      self.render())

    def test_this_rows_value_is_what_the_handle_drags(self):
        # First is what the handle itself drags; the rest are the tooltip's.
        # The user grabbed THIS 2, so that is what a drag has to hand over.
        out = self.render()
        self.assertNotIn(exp_attr('[item[1] for item in x]', 'x[0][1]'), out)

    def test_with_no_table_above_there_is_only_the_one_reading(self):
        out = self.render(cell='t', every_row=False)
        self.assertIn(exp_attr('t[1]'), out)

    def test_a_named_tuples_field_reads_by_name(self):
        out = self.render(value=Point(1, 2))
        self.assertIn(reads_attr('x[0].y',  '[item.y for item in x]'), out)

    def test_a_tuple_inside_a_tuple_asks_from_where_it_sits(self):
        # Composed on the way down, so the inner element asks about `$[0][1]`
        # rather than starting over at `$[1]`.
        out = self.render(value=(('a', 'b'), 2))
        self.assertIn(reads_attr('x[0][0][1]',  '[item[0][1] for item in x]'), out)

    def test_the_whole_tuple_keeps_its_own_handle(self):
        # The parens name the cell, which the column header already answers for.
        out = self.render()
        self.assertIn(exp_attr('x[0]'), out)


# =============================================================================
# The line's config
# =============================================================================

class TestConfig(unittest.TestCase):
    def setUp(self):
        set_line_config(None)

    def test_a_tuple_saves_nothing_of_its_own(self):
        # Its slots are the value's positions, not a choice the user made, so
        # there is nothing to write above the line.
        value = (1, [2, 3])
        model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        visualize(value, model, _get_visualizer, None, var_and_exp=('t', 't'))
        _, dirty = take_line_config()
        self.assertFalse(dirty)

    def test_a_childs_save_lands_under_its_element(self):
        set_line_config(None)
        value = (1, [{'a': 1}])
        model = init_model(value, _get_visualizer, var_and_exp=('t', 't'))
        child_model = model['children']['$[1]']
        table_visualizer._save_columns(child_model)
        slots, dirty = take_line_config()
        self.assertTrue(dirty)
        self.assertEqual([s['expr'] for s in slots], ['$[1]'])
        self.assertTrue(slots[0].get('children'))



class TestLiveOnly(unittest.TestCase):
    """Under clickacode.liveOnlyVisualizers a tuple's parens and elements carry no
    drag handles."""

    def setUp(self):
        from visualizer_utils import set_live_only
        set_live_only(True)

    def tearDown(self):
        from visualizer_utils import set_live_only
        set_live_only(False)

    def test_no_handles(self):
        value = (1, 'a')
        model = init_model(value, var_and_exp=('t', 't'))
        out = visualize(value, model, lambda v: _GenericVis(), None,
                        var_and_exp=('t', 't'))
        self.assertIn('snc-tuple-visualizer', out)
        self.assertNotIn('snc-py-exps', out)
        self.assertNotIn('py-exp-grab', out)

if __name__ == '__main__':
    unittest.main()
