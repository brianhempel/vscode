#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pygments", "fonttools"]
# ///
"""Generate `index.html` next to this file: a gallery of Clickacode widget
operations, each shown as a Before / After scene.

Every scene is produced by driving the real runner (`python_runner.py`) and
the real visualizers in-process, exactly the way the editor does:

  1. run the Before program and take the widget's model;
  2. queue the UI events that set the scene up (say, open a column's menu) and
     run again: that render is the "Before" picture;
  3. queue the click that performs the operation and run again: the NewCode
     command it answers with is applied to the source the way the editor
     applies it;
  4. run the edited program: that render is the "After" picture.

So the HTML in the page is what the editor would have shown, and the code in
the After pane is what the editor would have written. Only the chrome around
it (line numbers, syntax colouring, the cursor arrow) is drawn here.

Run from anywhere:  uv run docs/ops/generate_docs.py
"""
import html
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NODE = os.path.join(REPO, 'src', 'vs', 'platform', 'snc', 'node')
BROWSER = os.path.join(REPO, 'src', 'vs', 'editor', 'contrib', 'snc', 'browser')
FONT = os.path.join(REPO, 'src', 'vs', 'workbench', 'browser', 'media', 'fonts',
                    'pragmasevka', 'pragmasevka-nf-regular.ttf')

sys.path.insert(0, NODE)
sys.path.insert(0, os.path.join(NODE, 'visualizers'))

import python_runner as pr  # noqa: E402
from table_visualizer import DropdownToggle, GroupByClick, _menu_id, ADD_MENU_ID  # noqa: E402

from pygments import highlight  # noqa: E402
from pygments.lexers import PythonLexer  # noqa: E402
from pygments.formatters import HtmlFormatter  # noqa: E402
from fontTools import subset  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402


# =============================================================================
# Driving the runner
# =============================================================================

def run(source: str, focused_line: int, models_and_events=None) -> dict:
    """Run *source* through the runner and return {(line, visIndex): item}.

    The runner streams NDJSON to `_stream_out`; we point that at a buffer for
    the duration, the way the runner's own tests do."""
    buf = io.StringIO()
    saved = pr._stream_out
    pr._stream_out = buf
    try:
        pr._source_code = source
        import_code, body = pr.split_leading_imports(source)
        pr._execute_run(body, json.dumps(models_and_events or []), 'docs',
                        focused_line=focused_line, import_code=import_code,
                        stdin_eof=True)
    finally:
        pr._stream_out = saved
    items = {}
    for raw in buf.getvalue().splitlines():
        if not raw.strip():
            continue
        msg = json.loads(raw)
        if msg.get('type') == 'item':
            item = msg['item']
            items[(item['line'], item['visIndex'])] = item
        elif msg.get('type') == 'error':
            raise RuntimeError(f'runner error: {msg}')
    return items


def click(python_event: str) -> dict:
    """A mousedown on an element whose snc-mouse-down is *python_event*."""
    return {'pythonEventStr': python_event,
            'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1,
                          'detail': 1, 'offsetY': 5, 'elementHeight': 20,
                          'timeStamp': 1000.0}}


def typed(event_class: str, value: str) -> dict:
    """Typing *value* into a box whose snc-input builds *event_class*."""
    return {'pythonEventStr': f"lambda e: {event_class}(value=e.get('value', ''))",
            'eventJSON': {'type': 'input', 'value': value}}


def key(event_class: str, name: str) -> dict:
    """A keydown (Enter, Escape) on an element whose snc-key-down is *event_class*()."""
    return {'pythonEventStr': f'{event_class}()',
            'eventJSON': {'type': 'keydown', 'key': name, 'metaKey': False,
                          'shiftKey': False, 'ctrlKey': False, 'altKey': False}}


def queued(line: int, model: dict, events: list) -> list:
    """The models_and_events entry that queues *events* on the widget at *line*."""
    return [{'line': line, 'visIndex': 0, 'model': model,
             'events': [{'line': line, 'visIndex': 0, 'id': i + 1, **ev}
                        for i, ev in enumerate(events)]}]


def _insert_new_code(lines: list, cmd: dict) -> 'int | None':
    """Apply one NewCode command's edits to *lines* the way the editor does
    (bottom-to-top, `afterLine` 0 meaning before the first line). Returns the
    line number of the main insert, which is the line the editor links."""
    edits = list(cmd['edits'])
    # The editor works out where a missing import goes; the doc keeps it
    # simple and puts it above everything.
    for imp in cmd.get('imports') or []:
        if imp not in '\n'.join(lines):
            edits.append({'afterLine': 0, 'text': imp, 'type': 'insert'})
    main = next((e['afterLine'] + 1 for e in cmd['edits']
                 if e['afterLine'] == cmd['triggerLine']), None)
    for edit in sorted(edits, key=lambda e: e['afterLine'], reverse=True):
        lines[edit['afterLine']:edit['afterLine']] = edit['text'].split('\n')
        if main is not None and edit['afterLine'] < main - 1:
            main += len(edit['text'].split('\n'))
    return main


ASSIGNMENT_RE = re.compile(r'^(?P<indent>[ \t]*)(?P<name>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<expr>.*)$')


def _rewrite_linked(lines: list, cmd: dict, linked: int) -> None:
    """ChangeSelectedText: rewrite the expression of the linked line, keeping
    its variable name unless the visualizer suggests another and the current
    one is used nowhere else (snc.ts handleChangeSelectedText)."""
    m = ASSIGNMENT_RE.match(lines[linked - 1])
    indent = re.match(r'[ \t]*', lines[linked - 1])[0]
    if not m or cmd['expression'].rstrip().endswith(':'):
        # A statement rather than an assignment -- a loop, an if -- gets the
        # placeholder body that makes it runnable, as the editor gives it.
        lines[linked - 1:linked] = [indent + l for l in
                                    pr.with_pass_body(cmd['expression']).split('\n')]
        return
    name = m['name']
    suggested = cmd.get('suggested_var_name')
    elsewhere = '\n'.join(lines[:linked - 1] + lines[linked:])
    if suggested and suggested != name and not re.search(rf'\b{name}\b', elsewhere):
        name = pr._find_available_variable_name(elsewhere, suggested)
    lines[linked - 1] = f"{m['indent']}{name} = {cmd['expression']}"


def _set_config_comment(lines: list, cmd: dict) -> None:
    """SetConfigComment: replace or add the line's trailing #%click comment."""
    n = cmd['triggerLine'] - 1
    code = re.sub(r'\s*#%click\b.*$', '', lines[n])
    lines[n] = code if cmd['comment'] is None else f"{code}  {cmd['comment']}"


def apply_commands(source: str, commands: list, linked: 'int | None',
                   trigger: int) -> tuple:
    """Carry out the editor's side of *commands*. Returns (new_source, the line
    to focus, the line now linked to the widget, where the trigger line is now
    -- an import landing above it moves it down)."""
    lines = source.split('\n')
    focus = None
    for cmd in commands:
        if cmd['type'] == 'NewCode':
            before_len = len(lines)
            main = _insert_new_code(lines, cmd)
            if main is not None:
                grown = len(lines) - before_len
                above = grown - sum(len(e['text'].split('\n')) for e in cmd['edits']
                                    if e['afterLine'] >= trigger)
                trigger += above
                if linked is not None and linked > 0:
                    linked += above
                linked = focus = main
        elif cmd['type'] == 'ChangeSelectedText':
            assert linked, 'ChangeSelectedText with no linked line'
            _rewrite_linked(lines, cmd, linked)
            focus = linked
        elif cmd['type'] == 'SetConfigComment':
            _set_config_comment(lines, cmd)
            focus = cmd['triggerLine']
    return '\n'.join(lines), focus, linked, trigger


# =============================================================================
# Scenes
# =============================================================================

@dataclass
class Scene:
    id: str
    title: str
    blurb: str
    source: str
    line: int                       # the line whose widget is acted on
    setup: list                     # events queued before the picture (click / typed)
    hover: str                      # cursor target: 'selector', 'selector|text', or
                                    # 'selector|text|child selector' within that match
    click: object                   # the event (or list of events) that performs it
    action: str                     # what the user does, in a line
    before_html: str = ''
    after_html: str = ''


PEOPLE = ("people = [{'name': 'Ann', 'dept': 'eng', 'age': 34}, "
          "{'name': 'Bo', 'dept': 'ops', 'age': 28}, "
          "{'name': 'Cy', 'dept': 'eng', 'age': 41}]\n")
AGES = ("rows = [{'name': 'Ann', 'age': '34'}, {'name': 'Bo', 'age': '28'}, "
        "{'name': 'Cy', 'age': '41'}]\n")
LOG = ("log = 'order 66 shipped 2024-05-01, order 67 shipped 2024-06-12, "
       "order 68 pending'\n")

DEPT = "$['dept']"
AGE = "$['age']"


def column_menu(col: str) -> dict:
    return click(repr(DropdownToggle(dropdown_id=_menu_id('col-menu', col))))


def submenu(kind: str, col: str) -> dict:
    """Rest the pointer on a row of the column menu that opens a submenu."""
    return click(f"ColumnSubmenuDwell(dropdown_id={_menu_id(kind, col)!r})")


PETS = ("people = [{'name': 'Ann', 'pets': ['cat', 'dog']}, {'name': 'Bo', 'pets': []}, "
        "{'name': 'Cy', 'pets': ['emu']}]\n")
NAMES = "names = ['Ann', 'Bo', 'Cy']\n"
MATCH = "import re\nm = re.search(r'\\d+', 'order 66 shipped')\n"

SEARCH_ENG = "$['dept'] == 'eng'"


def action_button(action: str) -> str:
    """Hover target for an action-bar button, by the event it carries: some of
    them are icons with no text to match."""
    return f""".action-button[snc-mouse-down*="action='{action}'"]"""

SCENES = [
    Scene(
        id='group-by', title='Group By',
        blurb='Cut the list into a dict of lists keyed by a column.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT)],
        hover='.col-group-by',
        click=click(repr(GroupByClick(col=DEPT))),
        action='Open the <b>dept</b> column\'s ▾ menu and click <b>Group By</b>.',
    ),
    Scene(
        id='sort', title='Sort',
        blurb='Order the rows by a column.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), submenu('sort', AGE)],
        hover='.col-sort-code||.col-compute-toggle',
        click=click(f"SortCodeClick(col={AGE!r}, direction='asc')"),
        action=('Open the <b>age</b> column\'s ▾ menu, rest on <b>Sort</b>, and click '
                'the (+) beside <b>Asc</b>. Ticking Asc instead sorts the line in place.'),
    ),
    Scene(
        id='search', title='Search',
        blurb='Keep the rows the search matches.',
        source=PEOPLE, line=1,
        setup=[],
        hover='.search-box',
        click=typed('SearchBoxInput', SEARCH_ENG),
        action=(f'Type <code>{html.escape(SEARCH_ENG)}</code> in the search box. '
                'The Filter line is written as you type, and stays linked to the widget.'),
    ),
    Scene(
        id='table-count', title='Count',
        blurb='How many rows the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover=action_button('count'),
        click=click("ActionButtonClick(action='count', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click <b>Count</b>. '
                'The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='table-delete', title='Delete All',
        blurb='The list without the rows the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover=action_button('delete'),
        click=click("ActionButtonClick(action='delete', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click <b>Delete All</b>. '
                'The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='table-indexes', title='Find Indices',
        blurb='The positions of the rows the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover=action_button('find_indices'),
        click=click("ActionButtonClick(action='find_indices', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click <b>Find Indices</b>. '
                'The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='unique-tally', title='Unique / Tally',
        blurb='The distinct values of a column, or how often each occurs.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT), submenu('compute', DEPT)],
        hover='.col-compute-code|Unique',
        click=click(f"ComputeCodeClick(col={DEPT!r}, expr='set($)')"),
        action='Open the <b>dept</b> column\'s ▾ menu, rest on <b>Compute</b>, and click <b>Unique</b>.',
    ),
    Scene(
        id='change-type', title='Change Type',
        blurb='Read a column as another type.',
        source=AGES, line=1,
        setup=[column_menu(AGE), submenu('convert', AGE)],
        hover='.col-convert-wrapper|int|.col-compute-row-aside .col-compute-toggle',
        click=click(f"ConvertTypeColumnClick(col={AGE!r}, to='int')"),
        action=('Open the <b>age</b> column\'s ▾ menu, rest on <b>Change Type</b>, and click '
                'the insert-column arrow beside <b>int</b>. Ticking int instead converts '
                'the column in place.'),
    ),
    Scene(
        id='row-menu', title='Extract Item',
        blurb='Take one row out as a line of its own.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '1'))))],
        hover='.row-action|Extract Item 1',
        click=click("RowActionClick(row=1, action='item')"),
        action='Open the ▾ menu on row <b>1</b>\'s number and click <b>Extract Item 1</b>.',
    ),
    Scene(
        id='show-hide-fields', title='Show / hide fields',
        blurb='Tick a field off (or on) in the (+) menu.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=ADD_MENU_ID)))],
        hover=".col-add-row|$['age']|.col-compute-toggle",
        click=click('ColumnToggle(expr="$[\'age\']")'),
        action='Open the <b>(+)</b> menu and untick <b>age</b>.',
    ),
    Scene(
        id='remove-column', title='Remove',
        blurb='Take a column off the table.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE)],
        hover='.snc-dropdown-option|Remove',
        click=click(f'RemoveColumnClick(col={AGE!r})'),
        action='Open the <b>age</b> column\'s ▾ menu and click <b>Remove</b>.',
    ),
    Scene(
        id='insert-column-beside', title='Insert Left / Insert Right',
        blurb='Add a column beside this one.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE)],
        hover='.col-add-beside|Insert Right',
        click=[click(f'AddColumnAtClick(col={AGE!r}, after=True)'),
               typed('ColumnInput', "$['age'] * 2"), key('ColumnKeyDown', 'Enter')],
        action=('Open the <b>age</b> column\'s ▾ menu, click <b>Insert Right</b>, type '
                '<code>$[\'age\'] * 2</code> in the new header, and press Enter.'),
    ),
    Scene(
        id='compute', title='Compute',
        blurb='Ask a question of the whole column and keep the answer under it.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), submenu('compute', AGE)],
        hover='.col-compute-row|Sum|.col-compute-toggle',
        click=click(f"ComputeToggle(col={AGE!r}, expr='sum($)')"),
        action='Open the <b>age</b> column\'s ▾ menu, rest on <b>Compute</b>, and tick <b>Sum</b>.',
    ),
    Scene(
        id='splat', title='Expand list items into rows',
        blurb='A column of lists becomes one row per element.',
        source=PETS, line=1,
        setup=[column_menu("$['pets']")],
        hover='.col-expand-rows',
        click=click('SplatColumnClick(col="$[\'pets\']")'),
        action='Open the <b>pets</b> column\'s ▾ menu and click <b>Expand list items into rows</b>.',
    ),
    Scene(
        id='table-extract', title='Extract',
        blurb='The columns on show, as a list.',
        source=PEOPLE, line=1,
        setup=[],
        hover=action_button('extract'),
        click=click("ActionButtonClick(action='extract', copy=False)"),
        action='Click <b>Extract</b>.',
    ),
    Scene(
        id='table-join', title='Join',
        blurb='The cells joined into one string.',
        source=NAMES, line=1,
        setup=[],
        hover=action_button('join'),
        click=click("ActionButtonClick(action='join', copy=False)"),
        action='Click <b>Join</b>. Its menu offers other separators.',
    ),
    Scene(
        id='table-loop', title='Loop',
        blurb='A for loop over the rows the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover=action_button('loop_no_idx'),
        click=click("ActionButtonClick(action='loop_no_idx', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click <b>Loop</b>. '
                'The linked Filter line is rewritten as a loop.'),
    ),
    Scene(
        id='string-toggles', title='First match',
        blurb='Only the first match, instead of all of them.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', "r'\\d{4}-\\d\\d-\\d\\d'")],
        hover='[snc-mouse-down="FirstMatchToggle()"]',
        click=click('FirstMatchToggle()'),
        action='With a search typed, click the <b>1st</b> toggle. The linked line is rewritten in place.',
    ),
    Scene(
        id='string-count', title='Count',
        blurb='How many matches there are.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', "r'\\d{4}-\\d\\d-\\d\\d'")],
        hover=action_button('count'),
        click=click("ActionButtonClick(action='count', copy=False)"),
        action='With a search typed, click <b>Count</b>. The linked line is rewritten in place.',
    ),
    Scene(
        id='string-delete', title='Delete',
        blurb='The string with every match taken out.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', "r'order \\d+ '")],
        hover=action_button('delete'),
        click=click("ActionButtonClick(action='delete', copy=False)"),
        action='With a search typed, click <b>Delete</b>. The linked line is rewritten in place.',
    ),
    Scene(
        id='object-add-field', title='Add a field',
        blurb='Show another attribute of the object.',
        source=MATCH, line=2,
        setup=[click('AddFieldClick()')],
        hover='.obj-add-bar',
        click=[typed('FieldInput', '$.span()'), key('KeyDown', 'Enter')],
        action='Click <b>(+)</b>, type <code>$.span()</code>, and press Enter.',
    ),
    Scene(
        id='string-match', title='Type a search',
        blurb='Every match of a pattern, as strings.',
        source=LOG, line=1,
        setup=[],
        hover='.search-box',
        click=typed('SearchBoxInput', "r'\\d{4}-\\d\\d-\\d\\d'"),
        action=('Type <code>r\'\\d{4}-\\d\\d-\\d\\d\'</code> in the search box '
                '(or drag it out on the string). The Substrs line is written as you type.'),
    ),
    Scene(
        id='string-split', title='Split',
        blurb='Cut the string at every match.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', "', '")],
        hover=action_button('split'),
        click=click("ActionButtonClick(action='split', copy=False)"),
        action=('With <code>\', \'</code> in the search box, click <b>Split</b>. '
                'The linked line is rewritten in place.'),
    ),
]


# Every operation the page should eventually show, grouped the way the UI
# groups them. An id that matches a Scene above links to it; the rest are
# listed as still to do. (Ordered roughly from the most to the least used.)
CATALOG = [
    ('Tables', [
        ('The (+) menu', [
            ('add-column', 'Add a column', 'Type a $-expression for a new column, with autocomplete.'),
            ('show-hide-fields', 'Show / hide fields', 'Tick fields on and off; Show all, Hide all.'),
        ]),
        ('A column\'s ▾ menu', [
            ('column-search', 'Search a column', 'A search in the column\'s scope, with its operator and and / or composition.'),
            ('tally-filter', 'Tally', 'Tick values to keep or exclude them; sort and narrow the tally.'),
            ('sort', 'Sort', 'Asc / Desc rewrites the line in place; the insert rows write a sorted copy.'),
            ('group-by', 'Group By', ''),
            ('change-type', 'Change Type', 'Read the column as int / float / str / bool, in place or as a new column.'),
            ('subcolumns', 'Subcolumns', 'Spread a column of records across several sub-columns.'),
            ('splat', 'Expand list items into rows / collapse them back', 'A column of lists becomes one row per element.'),
            ('compute', 'Compute', 'Sum, min, max, mean, median, percentiles, counts, histogram and the rest, kept under the column.'),
            ('compute-custom', 'A custom aggregation', 'Type any expression over the column.'),
            ('compute-per-group', 'Per-group answers', 'On a splatted column, one answer per group becomes a column.'),
            ('unique-tally', 'Unique / Tally', 'Write set($) or Counter($) as a line.'),
            ('insert-column-beside', 'Insert Left / Insert Right', ''),
            ('remove-column', 'Remove', ''),
        ]),
        ('A row\'s ▾ menu', [
            ('row-menu', 'Extract Item', 'Take one row out as a line of its own.'),
            ('row-menu-more', 'Delete, Pop, Extract Cells, Use as Headers', 'The rest of the row menu, and the same for the last row.'),
        ]),
        ('The search box and action bar', [
            ('search', 'Search', 'A predicate with $, $i, $$ and $$$; the Filter line is written as you type.'),
            ('first-match', 'First match only', ''),
            ('table-filter', 'Filter', ''),
            ('table-count', 'Count', ''),
            ('table-delete', 'Delete All', 'The list without the matched rows.'),
            ('table-indexes', 'Find Indices', 'The positions of the matched rows.'),
            ('table-extract', 'Extract', 'The columns on show, as a list.'),
            ('table-join', 'Join', 'The cells joined with a separator.'),
            ('table-any-all', 'Any / All / If any / If all', ''),
            ('table-loop', 'Loop', 'A for loop over the matched rows, with or without the index.'),
            ('table-pick', 'Pick', 'Click cells to assemble an expression over a matched row.'),
        ]),
        ('Headers and cells', [
            ('edit-column', 'Edit a column expression', 'Double-click a header to rewrite it.'),
            ('reorder-columns', 'Reorder columns by dragging', ''),
            ('resize-column', 'Resize a column', ''),
            ('load-more', 'Load more rows', 'Paging past 50 rows.'),
            ('drag-out-table', 'Drag out', 'Drag a cell, a row, a column header, an aggregation or a tally row into the code.'),
        ]),
    ]),
    ('Strings', [
        ('The string itself', [
            ('literal-drag', 'Literal drag', 'Drag across the top half of characters to match them literally.'),
            ('fuzzy-drag', 'Fuzzy drag', 'Drag across the bottom half to match a character class.'),
            ('index-drag', 'Index drag', 'Drag with the index tool to make a slice.'),
            ('chain-segments', 'Chain segments', 'Start a new drag at the end of a selection.'),
            ('resize-segment', 'Resize a segment', 'Drag its handles.'),
            ('segment-menu', 'Segment menu', 'Change a segment\'s repetition (1, ?, *, +, exact, range) or character class; split or delete it.'),
            ('string-pick', 'Pick', 'Click chips of the first match (start, end, prefix, groups, suffix) to build an expression.'),
            ('drag-out-string', 'Drag out', 'Drag a match or a chip into the code.'),
        ]),
        ('The search box', [
            ('string-match', 'Type a search', 'A regex, a substring, a slice or an expression; the Substrs line is written as you type.'),
            ('string-toggles', 'First match / Match case / Capture groups', ''),
            ('string-replace', 'Replace', 'Open the replace box and write re.sub.'),
            ('string-map', 'Map', 'The replace box as a mapping over the matches.'),
        ]),
        ('The action bar', [
            ('string-match-objects', 'Match Objects / Substrs / Indexes', 'The matches as objects, strings or index pairs.'),
            ('string-count', 'Count', ''),
            ('string-split', 'Split', ''),
            ('string-delete', 'Delete', ''),
            ('string-filter', 'Filter', 'Keep the elements of a list of strings that match.'),
            ('string-any-all', 'Any / All / If any / If all', ''),
            ('string-loop', 'Loop', 'Loop over the matches.'),
            ('fetch', 'Fetch URL / Read Filepath', 'Read a string that names a place, as text, JSON, CSV or Excel.'),
        ]),
    ]),
    ('Objects and tuples', [
        ('', [
            ('object-add-field', 'Add a field', 'Type an accessor, with autocomplete over the object\'s attributes.'),
            ('object-edit-remove', 'Edit / remove / reorder fields', ''),
            ('drag-out-object', 'Drag out', 'Drag a field into the code; drag a tuple element or the whole tuple.'),
            ('nested', 'Nested visualizers', 'A string in a table cell, a table in a tuple: the child works as it would alone and the code it writes reads through the parent.'),
        ]),
    ]),
    ('The editor', [
        ('', [
            ('linked-line', 'The linked line', 'A generated line keeps rewriting as the gesture continues; the chain icon unlinks and relinks.'),
            ('config-comment', 'The #%click comment', 'A line\'s saved columns or fields, folded to a chip.'),
            ('focus', 'Focus', 'Widgets away from the cursor draw small; a click pins one.'),
            ('loop-slider', 'Loops', 'The slider picks which iteration a widget inside a loop shows; pin an iteration.'),
            ('drop-url', 'Drop a URL, a browser tab or a file into the code', 'Writes the line that reads it.'),
            ('console', 'The console', 'stdin and stdout for the program.'),
            ('live-only', 'Live-only mode', 'Visualizers without any affordance that writes code.'),
            ('errors', 'Errors', 'An uncaught exception drawn at the line that raised it.'),
            ('numpy-pandas', 'NumPy and pandas', 'Read-only summaries.'),
        ]),
    ]),
]


def build(scene: Scene) -> None:
    line = scene.line
    fresh = run(scene.source, line)
    model = fresh[(line, 0)]['model']

    # Set the scene up. Some setup writes code of its own -- typing a search
    # writes the Filter (or Substrs) line straight away and links it -- so the
    # Before picture is taken after that landed.
    staged = run(scene.source, line, queued(line, model, scene.setup))
    item = staged[(line, 0)]
    assert len(item['handledEventIds']) == len(scene.setup), scene.id
    before_source, _, linked, line = apply_commands(
        scene.source, item.get('commands') or [], None, line)
    before = (run(before_source, line, queued(line, item['model'], []))
              if before_source != scene.source else staged)
    scene.before_html = render_editor(before_source, before, line)

    # The operation may be a few events -- a header typed and Enter pressed.
    events = scene.click if isinstance(scene.click, list) else [scene.click]
    clicked = run(before_source, line,
                  queued(line, before[(line, 0)]['model'], events))
    assert len(clicked[(line, 0)]['handledEventIds']) == len(events), scene.id
    commands = clicked[(line, 0)].get('commands') or []

    # The editor keeps the caret on the trigger line after a click, so the
    # widget that was clicked stays focused and the line it wrote draws small.
    # Its model (the search typed, the menu closed) carries over to the rerun,
    # as it does in the editor.
    after_source, _, _, after_line = apply_commands(before_source, commands, linked, line)
    after = run(after_source, after_line,
                queued(after_line, clicked[(line, 0)]['model'], []))
    line = after_line
    scene.after_html = render_editor(after_source, after, line)


# =============================================================================
# Rendering a mini editor
# =============================================================================

_lexer = PythonLexer()
_formatter = HtmlFormatter(nowrap=True)
CONFIG_COMMENT_RE = re.compile(r'^(?P<code>.*?)(?P<gap>\s*)#%click (?P<payload>.*)$')


def highlight_line(text: str) -> str:
    """One line of Python, coloured, with a `#%click` comment folded to the
    chip the editor shows (see SNCController.updateConfigCommentFolding)."""
    m = CONFIG_COMMENT_RE.match(text)
    if not m:
        return highlight(text, _lexer, _formatter).rstrip('\n')
    code = highlight(m['code'], _lexer, _formatter).rstrip('\n')
    return (f'{code}{m["gap"]}<span class="c1">#%click </span>'
            f'<span class="snc-config-ellipsis" title="{html.escape(m["payload"])}">…</span>'
            f'<span class="snc-config-payload">{html.escape(m["payload"])}</span>')


def render_editor(source: str, items: dict, focused_line: int) -> str:
    """The code with each line's widget under it, as the editor lays it out:
    a widget of any size sits in block layout below its line, indented to the
    code."""
    out = ['<div class="doc-editor monaco-editor editor-instance">']
    lines = source.rstrip('\n').split('\n')
    for n, text in enumerate(lines, start=1):
        cls = ' focused' if n == focused_line else ''
        out.append(f'<div class="doc-line{cls}"><span class="doc-ln">{n}</span>'
                   f'<span class="doc-code">{highlight_line(text)}</span></div>')
        indent = len(text) - len(text.lstrip(' '))
        for (line, vis_index), item in sorted(items.items()):
            if line != n:
                continue
            out.append(f'<div class="doc-widget-row" style="padding-left:{indent}ch">'
                       f'<div class="snc-visualization-widget snc-visualization-widget-block-layout">'
                       f'{item["html"]}</div></div>')
    out.append('</div>')
    return '\n'.join(out)


# =============================================================================
# The page
# =============================================================================

def snc_css() -> str:
    with open(os.path.join(BROWSER, 'string-visualizer.css')) as f:
        strings = f.read()
    with open(os.path.join(BROWSER, 'snc.css')) as f:
        main = f.read().replace('@import "./string-visualizer.css";', '')
    return strings + '\n' + main


CURSOR_SVG = (
    '<svg class="doc-cursor" width="18" height="24" viewBox="0 0 18 24">'
    '<path d="M2 1.5 L2 18.5 L6.4 14.6 L9.4 21.2 L12.2 19.9 L9.3 13.4 L15.2 13.4 Z" '
    'fill="#000" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>')

DOC_CSS = """
:root {
	--vscode-focusBorder: #0090f1;
	--vscode-toolbar-hoverBackground: rgba(184, 184, 184, 0.31);
	--vscode-icon-foreground: #424242;
	--vscode-editor-foldPlaceholderForeground: #808080;
	--vscode-editorWidget-border: #c8c8c8;
	--vscode-editorWidget-background: #f3f3f3;
	--vscode-editor-foreground: #3b3b3b;
}
@font-face {
	font-family: "Pragmasevka";
	src: url("__FONT__") format("truetype");
	font-weight: 400;
	font-style: normal;
}
body {
	margin: 0;
	padding: 32px 40px 80px;
	background: #fff;
	color: #222;
	font: 15px/1.5 -apple-system, system-ui, sans-serif;
	max-width: 1400px;
}
h1 { font-weight: 600; font-size: 26px; margin: 0 0 6px; }
h2.doc-section {
	font-weight: 600;
	font-size: 22px;
	margin: 64px 0 4px;
	padding-bottom: 6px;
	border-bottom: 1px solid #e3e3e3;
}
h3.doc-subsection { font-weight: 600; font-size: 19px; margin: 40px 0 0; color: #333; }
h4 { font-weight: 600; font-size: 16px; margin: 28px 0 4px; }
.doc-intro, .doc-blurb { max-width: 760px; color: #444; }
.doc-blurb code { font-family: Pragmasevka, monospace; font-size: 0.95em; }
.doc-scene {
	display: grid;
	grid-template-columns: 1fr auto 1fr;
	gap: 16px;
	align-items: start;
	margin-top: 18px;
}
@media (max-width: 1100px) {
	.doc-scene { grid-template-columns: 1fr; }
	.doc-scene .doc-arrow { transform: rotate(90deg); justify-self: center; }
}
.doc-pane-label {
	font-size: 12px;
	font-weight: 600;
	letter-spacing: 0.06em;
	text-transform: uppercase;
	color: #888;
	margin-bottom: 6px;
}
.doc-toc { margin: 28px 0 8px; max-width: 1100px; }
.doc-toc-section { margin-bottom: 22px; }
.doc-toc h3 {
	font-size: 15px;
	font-weight: 600;
	margin: 0 0 8px;
	padding-bottom: 4px;
	border-bottom: 1px solid #e3e3e3;
	color: #222;
}
.doc-toc-columns {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
	gap: 4px 32px;
}
.doc-toc h4 {
	font-size: 11.5px;
	font-weight: 600;
	letter-spacing: 0.06em;
	text-transform: uppercase;
	color: #888;
	margin: 4px 0 4px;
}
.doc-toc ul { list-style: none; margin: 0; padding: 0; }
.doc-toc li { font-size: 13.5px; line-height: 1.35; margin: 0 0 5px; }
.doc-toc a { color: #1a5fb4; text-decoration: none; }
.doc-toc a:hover { text-decoration: underline; }
.doc-todo { color: #444; }
.doc-toc-note {
	color: #999;
	font-size: 12px;
	line-height: 1.35;
	padding-left: 12px;
	margin-top: 1px;
}
.doc-caption { font-size: 13.5px; color: #555; margin-top: 10px; max-width: 560px; }
.doc-arrow { align-self: center; color: #aaa; font-size: 28px; padding-top: 24px; }

/* The mini editor. Real VS Code positions widgets absolutely and reserves
   room with view zones; here each widget simply flows under its line. */
.doc-editor {
	position: relative;
	border: 1px solid #e3e3e3;
	border-radius: 6px;
	background: #fff;
	padding: 10px 14px 12px 0;
	font-family: Pragmasevka, monospace;
	font-size: 14px;
	line-height: 20px;
	overflow-x: auto;
}
.doc-line { display: flex; white-space: pre; }
.doc-line.focused { background: #f6f6f6; }
.doc-ln {
	flex: none;
	width: 44px;
	text-align: right;
	padding-right: 18px;
	color: #999;
	user-select: none;
}
.doc-line.focused .doc-ln { color: #333; }
.doc-code { color: #3b3b3b; }
.doc-widget-row { margin-left: 62px; }
.doc-editor .snc-visualization-widget { position: relative; }

/* VS Code "Default Light Modern" token colours, on Pygments classes. */
.doc-code .k, .doc-code .kn, .doc-code .ow { color: #0000ff; }
.doc-code .s, .doc-code .s1, .doc-code .s2, .doc-code .sa { color: #a31515; }
.doc-code .mi, .doc-code .mf { color: #098658; }
.doc-code .c1 { color: #008000; }
.doc-code .n { color: #001080; }
.doc-code .nb, .doc-code .nf { color: #795e26; }
.doc-code .p, .doc-code .o { color: #3b3b3b; }

/* The scene's hover: the row under the cursor, and the cursor itself. */
.doc-hovered { background: var(--snc-hover-bg); }
.doc-cursor {
	position: absolute;
	z-index: 200;
	pointer-events: none;
	filter: drop-shadow(0 1px 1.5px rgba(0, 0, 0, 0.35));
}
"""

DOC_JS = """
// A column menu is rendered inside its <th> and the editor hoists it out so
// the table's scroll box cannot clip it (VisualizationWidget.hoistDropdownPanel).
// Do the same here, then put the cursor on the row the scene hovers.
//
// Everything is measured only once the code font has loaded: the table is
// laid out again when Pragmasevka arrives, and a menu placed against the
// fallback font's column widths ends up beside the wrong column.
const hoisted = [];
const cursors = [];

function hoist() {
	for (const pane of document.querySelectorAll('.doc-editor')) {
		for (const panel of pane.querySelectorAll('.snc-dropdown-panel:not([data-hover-menu])')) {
			const trigger = panel.closest('.snc-dropdown-trigger');
			if (!trigger) { continue; }
			let measure = trigger;
			if (trigger.getBoundingClientRect().width === 0) {
				measure = Array.from(trigger.children).find(c => c.getBoundingClientRect().width > 0) || trigger;
			}
			panel.remove();
			pane.appendChild(panel);
			panel.style.position = 'absolute';
			panel.style.zIndex = '100';
			hoisted.push({ pane, panel, measure, align: panel.getAttribute('snc-dropdown-align') || 'left' });
		}
		const hover = pane.closest('[data-hover]')?.dataset.hover;
		let el = null;
		if (hover) {
			const [selector, text, child] = hover.split('|');
			const candidates = Array.from(pane.querySelectorAll(selector));
			// An exact label first: "Item 1" must not resolve to "Delete Item 1".
			el = (text && candidates.find(c => c.textContent.trim() === text))
				|| candidates.find(c => !text || c.textContent.includes(text))
				|| null;
			if (el && child) { el = el.querySelector(child); }
		}
		if (el) {
			el.classList.add('doc-hovered');
			const cursor = document.querySelector('#cursor-template').content.firstElementChild.cloneNode(true);
			pane.appendChild(cursor);
			cursors.push({ pane, el, cursor });
		}
	}
}

function position() {
	// Start from the grid's own widths; a pane grows below only as far as
	// the menus hoisted into it need.
	for (const { pane } of hoisted) {
		pane.style.minWidth = '';
		pane.style.minHeight = '';
	}
	for (const { pane, panel, measure, align } of hoisted) {
		const t = measure.getBoundingClientRect();
		const p = pane.getBoundingClientRect();
		if (align === 'flyout') {
			panel.style.top = `${t.top - p.top + pane.scrollTop}px`;
			panel.style.left = `${t.right - p.left + pane.scrollLeft}px`;
		} else if (align === 'right') {
			panel.style.top = `${t.bottom - p.top}px`;
			panel.style.right = `${p.right - t.right}px`;
		} else {
			panel.style.top = `${t.bottom - p.top}px`;
			panel.style.left = `${t.left - p.left}px`;
		}
		// The pane flows its content; a hoisted panel does not, so make room
		// for it in both directions.
		const r = panel.getBoundingClientRect();
		pane.style.minHeight = `${Math.max(pane.offsetHeight, r.bottom - p.top + 12)}px`;
		pane.style.minWidth = `${Math.max(parseFloat(pane.style.minWidth) || 0, r.right - p.left + 12)}px`;
	}
	for (const { pane, el, cursor } of cursors) {
		const p = pane.getBoundingClientRect();
		const r = el.getBoundingClientRect();
		cursor.style.left = `${r.left - p.left + Math.min(r.width * 0.45, 40)}px`;
		cursor.style.top = `${r.top - p.top + r.height * 0.55}px`;
	}
}

hoist();
position();
document.fonts.ready.then(position);
window.addEventListener('resize', position);
"""


def embedded_font(text: str) -> str:
    """Pragmasevka (the Nerd Font build the editor bundles, whose private-use
    glyphs the visualizers use for icons) cut down to the characters *text*
    uses, as a data URI.

    Embedded rather than linked because Chrome treats every `file://` page as
    its own origin and web fonts need CORS, so a linked font never loads when
    the page is opened from disk."""
    wanted = set(text) | {chr(c) for c in range(0x20, 0x7f)}
    font = TTFont(FONT)
    options = subset.Options()
    options.name_IDs = ['*']
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[ord(c) for c in wanted])
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    import base64
    return 'data:font/ttf;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def render_toc(scenes: list) -> str:
    """The catalog as a table of contents: a section per kind of value, its
    subsections side by side, a link for every operation that has a scene and
    a plain entry for every one still to do."""
    done = {s.id for s in scenes}
    out = ['<nav class="doc-toc">']
    for section, subsections in CATALOG:
        out.append(f'<section class="doc-toc-section"><h3>{section}</h3>'
                   f'<div class="doc-toc-columns">')
        for sub, ops in subsections:
            out.append('<div class="doc-toc-column">')
            if sub:
                out.append(f'<h4>{sub}</h4>')
            out.append('<ul>')
            for op_id, title, note in ops:
                label = (f'<a href="#{op_id}">{title}</a>' if op_id in done
                         else f'<span class="doc-todo">{title}</span>')
                note_html = f'<div class="doc-toc-note">{note}</div>' if note else ''
                out.append(f'<li>{label}{note_html}</li>')
            out.append('</ul></div>')
        out.append('</div></section>')
    out.append('</nav>')
    return '\n'.join(out)


def catalog_walk(scenes: list):
    """(section, subsection, scene) for every scene, in the order the table of
    contents lists them; a scene the catalog does not know comes last."""
    by_id = {sc.id: sc for sc in scenes}
    seen = set()
    for section, subsections in CATALOG:
        for sub, ops in subsections:
            for op_id, _, _ in ops:
                if op_id in by_id:
                    seen.add(op_id)
                    yield section, sub, by_id[op_id]
    for sc in scenes:
        if sc.id not in seen:
            yield 'Other', '', sc


def render_page(scenes: list) -> str:
    parts = [
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">',
        '<title>Clickacode Widget Operations</title>',
        f'<style>{snc_css()}</style>',
        '<style>__DOC_CSS__</style>',
        '</head><body>',
        f'<template id="cursor-template">{CURSOR_SVG}</template>',
        '<h1>Clickacode widget operations</h1>',
        render_toc(scenes),
    ]
    # The body carries the table of contents' headings, so the two read alike.
    section_shown = sub_shown = None
    for section, sub, s in catalog_walk(scenes):
        if section != section_shown:
            parts.append(f'<h2 class="doc-section">{section}</h2>')
            section_shown, sub_shown = section, None
        if sub and sub != sub_shown:
            parts.append(f'<h3 class="doc-subsection">{sub}</h3>')
            sub_shown = sub
        parts.append(f'<h4 id="{s.id}">{s.title}</h4>')
        parts.append(f'<p class="doc-blurb">{s.blurb}</p>')
        parts.append(f'<div class="doc-scene">')
        parts.append(f'<div class="doc-pane" data-hover="{html.escape(s.hover)}">'
                     f'<div class="doc-pane-label">Before</div>{s.before_html}'
                     f'<p class="doc-caption">{s.action}</p></div>')
        parts.append('<div class="doc-arrow">➜</div>')
        parts.append(f'<div class="doc-pane"><div class="doc-pane-label">After</div>'
                     f'{s.after_html}</div>')
        parts.append('</div>')
    parts.append(f'<script>{DOC_JS}</script>')
    parts.append('</body></html>')
    page = '\n'.join(parts)
    return page.replace('__DOC_CSS__', DOC_CSS.replace('__FONT__', embedded_font(page)))


def main() -> None:
    built = []
    for scene in SCENES:
        try:
            build(scene)
            built.append(scene)
        except Exception as e:  # noqa: BLE001 -- report and carry on
            print(f'FAILED {scene.id}: {type(e).__name__}: {e}')
    out = os.path.join(HERE, 'index.html')
    with open(out, 'w') as f:
        f.write(render_page(built))
    print(f'wrote {out} ({len(built)} of {len(SCENES)} scene(s))')


if __name__ == '__main__':
    main()
