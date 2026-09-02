"""Tuple visualizer for Sculpt-n-Code.

A tuple is a fixed handful of values that mean different things -- a pair from
`enumerate`, a `divmod` result, the row a database handed back. So it draws as
what it is, with each element handed to whichever visualizer reads its type:

    ([subvis], [subvis], [subvis])

and a named tuple as `Point(x=[subvis], y=[subvis])`.

**No search and no actions.** Those are questions about a collection of like
things -- which rows match, what the total is -- and a tuple is a collection of
unlike things. There is no row to filter and nothing to sum. What it does have
is a way to name each element (`t[0]`, `p.x`), so every element is a handle the
user can drag out into code, and so is the whole tuple, hung on its parens.

**Its elements are the value's, not the user's**, which is the whole of the
difference from the list and object visualizers. There is no column to add and
no field to remove, so there is nothing for a tuple to persist in the line's
`#%click` comment. It still passes the nesting parameters down (see
`child_nesting_kwargs`), because a table inside one of its elements does have
columns to save, and `save_slots_at_path` writes the slot leading down to it on
the way.

**Children know they are children.** Each is drawn `small` unless it is the one
the user has clicked (`focused_child`), and each is given a `config_path` that
says how deep it sits -- which is what makes a nested list draw its
`truncate_repr` instead of a table. The tuple itself never collapses that way: a
tuple drawn properly costs about what its repr costs, so there is nothing to be
saved by hiding it, and a pair inside a table cell is exactly where a tuple
visualizer earns its keep.

Sorts before `z_object_visualizer` (which claims everything) so that a tuple
reaches it rather than being shown as `dir()` minus `object()` -- which for a
named tuple leads with `count` and `index`.
"""

import functools
import html

from typing import Any, List, Tuple

from visualizer_utils import (
    ChildEvent,
    add_drag_readings, aggregate_handled_keys, child_nesting_kwargs,
    compose_dollar_expr, eval_dollar_expr, is_nested, nest_child_command,
    parse_slots, replace_dollars_in_py_exp, route_child_event, too_deep,
    truncate_str, wants_kwarg, wrap_child_html, wrap_drag_grab,
    CHILD_SOURCE_BINDER,
)


# The room an element is given when the tuple was given none: enough for a
# preview, the same order as the object visualizer's fields.
_DEFAULT_CHILD_WIDTH = 500

# Narrower than this and a child has room for nothing at all, so a wide tuple
# stops dividing and lets the row scroll instead.
_MIN_CHILD_WIDTH = 80

# How many elements are drawn before the rest become a count.
#
# Every element is a visualizer of its own, built and rendered on every rerun --
# every ~100ms while the user types -- so `tuple(range(10_000))` has to not be
# ten thousand of them, nor ten thousand columns in a table that sampled one.
# Well above any tuple written by hand, which is the size this is for.
MAX_ELEMENTS = 32


def can_visualize(value):
    return isinstance(value, tuple)


def _field_names(value):
    """The names a named tuple gives its positions, or None for a plain one.

    `_fields` is the whole of the duck type -- `collections.namedtuple` and
    `typing.NamedTuple` both write it -- and it is checked for shape rather
    than trusted, since any tuple subclass may have an attribute by that name.
    """
    fields = getattr(value, '_fields', None)
    if not isinstance(fields, tuple) or len(fields) != len(value):
        return None
    if not all(isinstance(name, str) and name.isidentifier() for name in fields):
        return None
    return fields


def element_slots(value) -> list:
    """`(label, expr)` per element: what names it on screen, and what reads it.

    A named tuple is read by name, because `p.x` is what the user would have
    written and `p[0]` is what they were avoiding by naming it.

    Cut off at MAX_ELEMENTS, so that everything downstream -- the children built,
    the elements drawn, the columns an enclosing table detects -- is capped by
    agreeing on this one list. `len(value)` is what says how much was left out.
    """
    fields = _field_names(value)
    if fields is None:
        return [(None, f'$[{i}]') for i in range(min(len(value), MAX_ELEMENTS))]
    return [(name, f'$.{name}') for name in fields[:MAX_ELEMENTS]]


def get_fields(value):
    """How a tuple is addressed from *outside* -- the expressions an enclosing
    table uses to pull cells out of it, which is what turns a list of pairs
    into a two-column table."""
    return [expr for _, expr in element_slots(value)]


def _elements(value) -> list:
    """`(label, expr, element)` per element.

    The element is read straight off the tuple rather than through its
    expression: both spellings are positional and `p.x` IS `p[0]`, and this runs
    once per element per render, where `eval_dollar_expr` would compile a lambda
    each time. Going through the expression is how something OUTSIDE this
    visualizer reaches an element, and `_element_at` is that way in.
    """
    return [(label, expr, value[i])
            for i, (label, expr) in enumerate(element_slots(value))]


def _element_at(value, expr: str, eval_in_scope=None):
    """The element some expression names -- for an event arriving with a key
    rather than a position, which may name one the value no longer has."""
    return eval_dollar_expr(expr, value, eval_in_scope)


def _adopt_source(model: dict, var_and_exp=None) -> None:
    """Take in what this run says about the line the value came from.

    Refreshed rather than remembered: a model outlives an edit to its line, and
    one still holding the old name would hand every element a handle naming a
    variable that no longer exists.
    """
    if var_and_exp:
        var_name, expr = var_and_exp
        model['_source_expr'] = var_name if var_name else expr


def init_model(value, get_visualizer=None, eval_in_scope=None, var_and_exp=None,
               slots_config=None, config_path=None, persist=True):
    """`slots_config`, `config_path` and `persist` are the nesting parameters --
    see child_nesting_kwargs.

    The saved config is read for its *children* only. A tuple's own slots are
    the value's positions, so a comment that says otherwise says nothing this
    visualizer can act on -- but the branch under a slot is a nested
    visualizer's config, and it has to reach the child that wrote it.
    """
    _, slot_children = parse_slots(slots_config)
    model = {
        'children': {},
        'focused_child': None,
        'handledKeys': [],
        '_source_expr': None,
        '_config_path': list(config_path or []),
        '_config_persist': persist,
        '_slot_children': slot_children,
    }
    _adopt_source(model, var_and_exp)

    # Depth backstop: beyond the cap, stop building nested children entirely
    # (renders as a truncated repr) so a tuple that reaches itself through some
    # container can't RecursionError.
    if too_deep(model['_config_path']):
        model['_too_deep'] = True
        return model

    if get_visualizer is None:
        return model

    for _, expr, element in _elements(value):
        child_vis = get_visualizer(element)
        # A child visualizer that doesn't name the nesting params in its
        # init_model gets {} back and isn't handed them.
        extra = child_nesting_kwargs(model, expr, child_vis.init_model)
        model['children'][expr] = child_vis.init_model(
            element, get_visualizer, eval_in_scope=eval_in_scope, **extra)

    model['handledKeys'] = aggregate_handled_keys(model['children'])
    return model


def update(event, var_and_exp, model: dict, value, get_visualizer=None,
           eval_in_scope=None) -> Tuple[dict, List[Any]]:
    """Route an event to the element it landed on. A tuple has no events of its
    own -- nothing on it is a control."""
    if not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])
    if model is None:
        model = init_model(value, get_visualizer, eval_in_scope=eval_in_scope,
                           var_and_exp=var_and_exp)

    try:
        make_python_event = eval(event['pythonEventStr'])
    except Exception:
        return (model, [])
    event_json = event.get('eventJSON')
    msg = make_python_event(event_json) if callable(make_python_event) else make_python_event

    if not isinstance(msg, ChildEvent) or get_visualizer is None:
        return (model, [])

    new_model, child_cmds = route_child_event(
        event, model, value,
        lambda expr: _element_at(value, expr, eval_in_scope),
        get_visualizer,
        # The element is bound to a name for the child, so the code it writes is
        # dollar-free and about the ELEMENT rather than about the tuple.
        var_and_exp=(None, CHILD_SOURCE_BINDER),
        eval_in_scope=eval_in_scope,
    )
    element_expr = _command_expr(new_model, msg.child_key, var_and_exp)
    if element_expr:
        # One expression for both destinations. A tuple is the one visualizer
        # with nothing to say about the difference: at the root both spellings
        # are the concrete path, and when nested both are the binder, which the
        # parent then resolves two ways with the two expressions it has.
        child_cmds = [nest_child_command(cmd, element_expr, element_expr)
                      for cmd in child_cmds]
    new_model['handledKeys'] = aggregate_handled_keys(new_model.get('children', {}))
    return (new_model, child_cmds)


def _element_expr(model: dict, expr: str) -> 'str | None':
    """The element's slot expression written against the line's own value --
    `$[0]` against `t` is `t[0]`. None when the line named nothing to hang it
    on, and then the element simply isn't a handle."""
    source_expr = model.get('_source_expr')
    if not source_expr:
        return None
    return replace_dollars_in_py_exp(expr, [source_expr])


def _command_expr(model: dict, expr: str, var_and_exp) -> 'str | None':
    """How an element is named in code travelling back up out of it.

    A tuple has no scope of its own -- it is a way THROUGH to an element -- so
    when it is itself nested it does not resolve the child's binder, it
    *extends* it: `_snc_cell_` becomes `_snc_cell_[0]`, and the parent finishes
    the job. That parent is the one that knows the two spellings of where the
    value came from, and it needs both: a table's derived column has to stay
    row-generic (`($)[0]`) while its clipboard text names this row (`(x[0])[0]`).
    Resolving here to the concrete path -- which is all `_source_expr` holds,
    rendering having handed the tuple the cell it was drawn in -- is what made a
    column read `x[0][0]` and answer only for the row it was made in.

    At the root there is nobody above to finish it, and the concrete path is
    both the code and the clipboard text.
    """
    if is_nested(var_and_exp):
        return replace_dollars_in_py_exp(expr, [CHILD_SOURCE_BINDER])
    return _element_expr(model, expr)


def _punct(text: str) -> str:
    return f'<span class="punct">{html.escape(text)}</span>'


def visualize(value, model: dict, get_visualizer=None, eval_in_scope=None,
              max_width=None, max_height=None, small=False, var_and_exp=None,
              every_row_exps=None):
    """`([subvis], [subvis], [subvis])`, or `Point(x=[subvis], y=[subvis])`.

    *small* is deliberately unused for the tuple's own layout: it says the
    line isn't the focused one, and a tuple drawn properly is already about
    the size of its repr, so there is nothing smaller to fall back to. It
    reaches the elements, though: an element opened by the user closes when
    its line loses focus, the way a table's cell does, and opens again when
    the line gets it back (see `_render_element`).

    *every_row_exps* is how a table above says what a value in one of its cells
    also reads as, taken down every row -- see `_render_element`. Absent when
    there is no table above, and then there are no rows to read down.
    """
    if model is None:
        model = init_model(value, get_visualizer, eval_in_scope=eval_in_scope,
                           var_and_exp=var_and_exp)
    _adopt_source(model, var_and_exp)

    # Depth-capped leaf: a plain truncated repr instead of more nesting.
    if model.get('_too_deep'):
        return f'<span class="small">{html.escape(truncate_str(repr(value), 200))}</span>'

    elements = _elements(value)
    whole = (None, model.get('_source_expr'))
    named = _field_names(value) is not None
    open_html = _punct('(')
    if named:
        # The class name reads as a name rather than as punctuation -- it is
        # the one word here that came from the user's program.
        open_html = (f'<span class="name">{html.escape(type(value).__name__)}</span>'
                     + open_html)

    parts = [wrap_drag_grab(open_html, whole)]
    for i, (label, expr, element) in enumerate(elements):
        if i:
            parts.append(_punct(', '))
        if label is not None:
            parts.append(f'<span class="field">{html.escape(label)}</span>'
                         f'<span class="punct">=</span>')
        parts.append(_render_element(element, expr, model, get_visualizer,
                                     eval_in_scope, max_width, max_height,
                                     len(elements), every_row_exps, small=small))
    hidden = len(value) - len(elements)
    if hidden > 0:
        parts.append(_punct(f', +{hidden}'))
    # `(1)` is a parenthesised 1; `(1,)` is the pair of the two that is a tuple.
    # A named tuple says which it is with its own name, so it needs no comma.
    elif len(elements) == 1 and not named:
        parts.append(_punct(','))
    parts.append(wrap_drag_grab(_punct(')'), whole))

    return f'<span class="snc-tuple-visualizer">{"".join(parts)}</span>'


def _render_element(element, expr: str, model: dict, get_visualizer, eval_in_scope,
                    max_width, max_height, count: int, every_row_exps=None,
                    small: bool = False) -> str:
    """One element, drawn by whichever visualizer reads its type.

    Handed its own access-path expression rather than wrapped in one, so a child
    with handles of its own keeps them instead of being covered by a handle that
    would answer for every hover inside it.

    When there is a table above, the element is also a value every row has --
    the `2` of `x = [('asdf', 2), ...]` is `x[0][1]` and it is `[item[1] for
    item in x]` -- so the question is asked of this element's slot and the
    answer added to the handle. `every_row_exps` is composed on the way down
    too, so a tuple inside this one asks about `$[0][1]` rather than starting
    over.
    """
    if get_visualizer is None:
        return html.escape(repr(element))

    child_vis = get_visualizer(element)
    child_model = model.get('children', {}).get(expr)
    if child_model is None:
        extra = child_nesting_kwargs(model, expr, child_vis.init_model)
        child_model = child_vis.init_model(element, get_visualizer,
                                           eval_in_scope=eval_in_scope, **extra)
        # Kept, so a later event runs against this model -- with the nesting
        # this one asked for -- rather than the bare fallback route_child_event
        # builds for a child its parent has none for.
        if child_model is not None:
            model.setdefault('children', {})[expr] = child_model

    child_expr = _element_expr(model, expr)
    inner = {}
    if every_row_exps is not None and wants_kwarg(child_vis.visualize, 'every_row_exps'):
        inner['every_row_exps'] = functools.partial(_nested_every_row_exps,
                                                    every_row_exps, expr)
    child_html = child_vis.visualize(
        element, child_model, get_visualizer, eval_in_scope,
        max_width=_child_width(max_width, count), max_height=max_height,
        small=small or (expr != model.get('focused_child')),
        var_and_exp=(None, child_expr) if child_expr else None, **inner)
    if every_row_exps is not None and child_expr:
        child_html = add_drag_readings(child_html, child_expr,
                                       every_row_exps(expr))
    return wrap_child_html(child_html, expr)


def _nested_every_row_exps(every_row_exps, expr: str, sub_expr: str) -> list:
    """The same question, asked from one element further in: a child's `$[1]`
    inside this tuple's `$[0]` is the table's `$[0][1]`."""
    return every_row_exps(compose_dollar_expr(sub_expr, expr))


def _child_width(max_width, count: int):
    """The room one element gets: an equal share of the row, since a tuple has
    no idea which of its elements is the interesting one."""
    if max_width is None:
        return _DEFAULT_CHILD_WIDTH
    return max(_MIN_CHILD_WIDTH, int(max_width / max(count, 1)))
