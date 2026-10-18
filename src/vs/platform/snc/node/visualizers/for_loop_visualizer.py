"""For loop visualizer for Sculpt-n-Code.

When a `for` loop finishes, the runner logs a ForLoopTable on its last line:
a row per iteration, a column per value the loop computed. The editor shows it
in place of the loop's body while the cursor is outside the loop, so a loop
reads as what it did rather than as one iteration of it.

    iteration | element | count += 1
    1         | 1       | 1
    2         | 2       | 2
    [Count] [Sum element] [Product element]

**The buttons add a step to the loop.** Each writes one statement at the end
of the body -- `count += 1`, `total += element` -- and, when the accumulator
isn't bound yet, its initializer above the header. That code lands away from
the line this visualizer sits on, so it goes out as InsertLines rather than a
NewCode tuple, and nothing is linked: the next press adds another step.

**Never focused.** The table only shows while the cursor is elsewhere, so every
button is snc-unfocused-clickable; a press on the table itself expands it like
any other small visualizer, which moves the cursor into the loop.

Sorts before `z_object_visualizer` (which claims everything) so that the table
reaches it rather than being shown as a dataclass's fields.
"""

import html
from dataclasses import dataclass
from typing import Any, List, Tuple

from visualizer_utils import EXPANDED_PANE_MAX_HEIGHT, ForLoopTable, InsertLines, is_live_only


@dataclass(frozen=True)
class AddStep:
    """A press on a button: update `accumulator` by `value` every iteration."""
    accumulator: str
    value: str


# accumulator -> (augmented operator, initial value)
_STEPS = {
    'count': ('+=', '0'),
    'total': ('+=', '0'),
    'product': ('*=', '1'),
}


def can_visualize(value):
    return isinstance(value, ForLoopTable)


def init_model(value, get_visualizer=None):
    return {}


def _statement(step: AddStep) -> str:
    return f'{step.accumulator} {_STEPS[step.accumulator][0]} {step.value}'


def _steps(value: ForLoopTable) -> List[Tuple[str, AddStep]]:
    """Every button, as (label, step), in the order drawn."""
    steps = [('Count', AddStep('count', '1'))]
    steps += [(f'Sum {name}', AddStep('total', name)) for name in value.targets]
    steps += [(f'Product {name}', AddStep('product', name)) for name in value.targets]
    return steps


def _render_button(label: str, step: AddStep) -> str:
    return (f'<span class="action-button" snc-unfocused-clickable draggable="false" '
            f'snc-mouse-down="{html.escape(repr(step))}" '
            f'data-tooltip="{html.escape(_statement(step))}">'
            f'<span class="text">{html.escape(label)}</span></span>')


def _render_cell(text) -> str:
    if text is None:
        return '<td class="list-table-cell">—</td>'
    return f'<td class="list-table-cell"><span class="snc-code">{html.escape(text)}</span></td>'


def visualize(value: ForLoopTable, model=None, get_visualizer=None, small=False):
    # Capped like a table nested in a cell: the loop's own code is right
    # above, and a long loop shouldn't push the rest of the file away.
    strs = ['<div class="list-visualizer small for-loop-visualizer">',
            f'<div class="list-table-scroll snc-base-visualizer" style="max-height: {EXPANDED_PANE_MAX_HEIGHT // 2}px;">',
            '<table><thead class="col-header-rows"><tr>',
            '<th class="row-index-header">iteration</th>']
    strs += [f'<th>{html.escape(label)}</th>' for label in value.columns]
    strs.append('</tr></thead><tbody>')
    for i, row in enumerate(value.rows):
        strs.append(f'<tr><td class="row-index">{i + 1}</td>')
        strs += [_render_cell(text) for text in row]
        strs.append('</tr>')
    strs.append('</tbody></table></div>')
    if value.hidden_rows:
        noun = 'iteration' if value.hidden_rows == 1 else 'iterations'
        strs.append(f'<div class="for-loop-note">{value.hidden_rows} more {noun}</div>')
    # Every button writes code, so live-only leaves the bar out entirely.
    if not is_live_only():
        strs.append('<div class="search-div"><div class="action-buttons">')
        strs += [_render_button(label, step) for label, step in _steps(value)]
        strs.append('</div></div>')
    strs.append('</div>')
    return ''.join(strs)


def update(event, var_and_exp, model, value: ForLoopTable, get_visualizer=None) -> Tuple[Any, List[Any]]:
    if not isinstance(event, dict) or not event.get('pythonEventStr'):
        return (model, [])
    try:
        step = eval(event['pythonEventStr'])
    except Exception:
        return (model, [])
    # Only a step one of the buttons offers: the event string comes back from
    # the editor, and whatever it says is written into the user's file.
    if not isinstance(step, AddStep) or step not in [s for _, s in _steps(value)]:
        return (model, [])
    lines = []
    if step.accumulator not in value.defined:
        lines.append((value.line - 1, f'{value.indent}{step.accumulator} = {_STEPS[step.accumulator][1]}'))
    lines.append((value.end_line, f'{value.body_indent}{_statement(step)}'))
    return (model, [InsertLines(tuple(lines))])
