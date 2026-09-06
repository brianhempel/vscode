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
(uv supplies fonttools for the font subsetting; each scene is built by the
python3 on PATH, the interpreter the editor uses, so numpy and pandas are the
user's own.)
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


def click(python_event: str, detail: int = 1, top_half: bool = True) -> dict:
    """A mousedown on an element whose snc-mouse-down is *python_event*.
    *detail* 2 is a double-click; the string visualizer reads the top or
    bottom half of a character off offsetY (bottom = fuzzy = alt)."""
    return {'pythonEventStr': python_event,
            'eventJSON': {'type': 'mousedown', 'button': 0, 'buttons': 1,
                          'detail': detail, 'offsetY': 5 if top_half else 15,
                          'elementHeight': 20, 'altKey': not top_half,
                          'shiftKey': False, 'ctrlKey': False,
                          'timeStamp': 1000.0}}


def move(python_event: str, top_half: bool = True) -> dict:
    """A mousemove with the button held, over an element whose snc-mouse-move
    (or snc-idx shorthand) is *python_event*."""
    return {'pythonEventStr': python_event,
            'eventJSON': {'type': 'mousemove', 'buttons': 1,
                          'offsetY': 5 if top_half else 15, 'elementHeight': 20,
                          'altKey': not top_half, 'shiftKey': False, 'ctrlKey': False}}


def release(python_event: str, top_half: bool = True) -> dict:
    """A mouseup over an element whose snc-mouse-up is *python_event*. The
    string visualizer reads the selection type off the modifiers on every
    event, so a fuzzy drag keeps alt held through the release."""
    return {'pythonEventStr': python_event,
            'eventJSON': {'type': 'mouseup', 'buttons': 0, 'altKey': not top_half,
                          'shiftKey': False, 'ctrlKey': False}}


def hover_move(python_event: str) -> dict:
    """A mousemove with no button held: resting the pointer somewhere."""
    return {'pythonEventStr': python_event,
            'eventJSON': {'type': 'mousemove', 'buttons': 0, 'altKey': False,
                          'shiftKey': False, 'ctrlKey': False}}


def typed(event_class: str, value: str) -> dict:
    """Typing *value* into a box whose snc-input builds *event_class*."""
    return typed_into(f"lambda e: {event_class}(value=e.get('value', ''))", value)


def typed_into(snc_input: str, value: str) -> dict:
    """Typing *value* into a box whose snc-input attribute is *snc_input*."""
    return {'pythonEventStr': snc_input,
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


def _set_config_comment(lines: list, cmd: dict, moved: int = 0) -> None:
    """SetConfigComment: replace or add the line's trailing #%click comment.
    *moved* is how far an import landing above has pushed the line down since
    the command named it (the editor keeps the same map, reportedLineNow)."""
    n = cmd['triggerLine'] - 1 + moved
    code = re.sub(r'\s*#%click\b.*$', '', lines[n])
    lines[n] = code if cmd['comment'] is None else f"{code}  {cmd['comment']}"


def _char_index(text: str, byte_offset: int) -> int:
    """A column the runner gave as a byte offset, as a character index (snc.ts
    byteOffsetToColumn)."""
    return len(text.encode('utf-8')[:byte_offset].decode('utf-8', 'ignore'))


def _change_source_expr(lines: list, cmd: dict) -> None:
    """ChangeSourceExpr: replace the exact span of the user's own source that
    the widget's line is showing -- what Sort in place writes (snc.ts
    handleChangeSourceExpr)."""
    first, last = cmd['start_line'] - 1, cmd['end_line'] - 1
    head = lines[first][:_char_index(lines[first], cmd['start_col'])]
    tail = lines[last][_char_index(lines[last], cmd['end_col']):]
    indent = re.match(r'[ \t]*', lines[first])[0]
    body = cmd['expression'].split('\n')
    body = [body[0]] + [indent + l for l in body[1:]]
    lines[first:last + 1] = (head + '\n'.join(body) + tail).split('\n')


def apply_commands(source: str, commands: list, linked: 'int | None',
                   trigger: int) -> tuple:
    """Carry out the editor's side of *commands*. Returns (new_source, the line
    to focus, the line now linked to the widget, where the trigger line is now
    -- an import landing above it moves it down)."""
    lines = source.split('\n')
    focus = None
    trigger0 = trigger
    for cmd in commands:
        if cmd['type'] == 'NewCode':
            before_len = len(lines)
            main = _insert_new_code(lines, cmd)
            # An import landing above pushes everything down -- with or without
            # a line of the command's own (a nested child's imports come alone).
            grown = len(lines) - before_len
            above = grown - sum(len(e['text'].split('\n')) for e in cmd['edits']
                                if e['afterLine'] >= trigger)
            trigger += above
            if linked is not None:
                linked += above
            if main is not None:
                linked = focus = main
        elif cmd['type'] == 'ChangeSelectedText':
            assert linked, 'ChangeSelectedText with no linked line'
            _rewrite_linked(lines, cmd, linked)
            focus = linked
        elif cmd['type'] == 'SetConfigComment':
            _set_config_comment(lines, cmd, trigger - trigger0)
            focus = cmd['triggerLine'] + trigger - trigger0
        elif cmd['type'] == 'ChangeSourceExpr':
            _change_source_expr(lines, cmd)
            focus = cmd['start_line']
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
    keep_menu: bool = False         # leave a menu the click left open in the After
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
ADDR = ("people = [{'name': 'Ann', 'addr': {'city': 'Oslo', 'zip': '0150'}}, "
        "{'name': 'Bo', 'addr': {'city': 'Lima', 'zip': '15001'}}]\n")
NUMS = "nums = list(range(120))\n"
HEADED = "rows = [['name', 'age'], ['Ann', '34'], ['Bo', '28']]\n"
ORDERS = "rows = ['order 66', 'order 67']\n"
PETS_SPLAT = PETS.rstrip('\n') + '  #%click [{"expr": "$"}, {"expr": "$[\'name\']"}, {"expr": "*$[\'pets\']"}]\n'
PETS_COL = "*$['pets']"
PATH = "path = 'tasks/apache-log-parse.input.log'\n"
JSON_PATH = "path = 'tasks/besdui-product-search.input.json'\n"
CSV_PATH = "path = 'tasks/blinkfill-examples.input.csv'\n"
CASE_LOG = "log = 'Order 66 shipped, order 67 pending'\n"
LOG_TEXT = 'order 66 shipped 2024-05-01, order 67 shipped 2024-06-12, order 68 pending'
DATE_RE = "r'\\d{4}-\\d\\d-\\d\\d'"
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
        id='add-column', title='Add a column',
        blurb='A new column from any expression over the row.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=ADD_MENU_ID)))],
        hover='[snc-mouse-down^="AddColumnClick"]',
        click=[click('AddColumnClick()'), typed('ColumnInput', "$['age'] > 30"),
               key('ColumnKeyDown', 'Enter')],
        action=('Open the <b>(+)</b> menu, click <b>Add Column</b>, type '
                '<code>$[\'age\'] > 30</code>, and press Enter.'),
    ),
    Scene(
        id='column-search', title='Search a column',
        blurb='A search written in one column\'s scope.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT)],
        hover='.col-search-input',
        click=typed_into(f"lambda e: ColumnSearchInput(col={DEPT!r}, value=e.get('value', ''))", "'eng'"),
        action=('Open the <b>dept</b> column\'s ▾ menu and type <code>\'eng\'</code> in its search box. '
                'The search is lifted into the main box and the Filter line written.'),
    ),
    Scene(
        id='tally-filter', title='Tally',
        blurb='Keep the rows holding a value ticked in the column\'s tally.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT)],
        hover="[snc-mouse-down^=\"TallyItemToggle\"]|'eng'",
        click=click(f"TallyItemToggle(col={DEPT!r}, literal=\"'eng'\")"),
        action='Open the <b>dept</b> column\'s ▾ menu and tick <b>\'eng\'</b> in its tally.',
    ),
    Scene(
        id='subcolumns', title='Subcolumns',
        blurb='Spread a column of records across several sub-columns.',
        source=ADDR, line=1,
        setup=[column_menu("$['addr']"), submenu('subcols', "$['addr']")],
        hover='[snc-mouse-down^="SubcolToggle"]|city',
        click=click('SubcolToggle(col="$[\'addr\']", expr="$[\'city\']")'),
        action='Open the <b>addr</b> column\'s ▾ menu, rest on <b>Subcolumns</b>, and tick <b>city</b>.',
    ),
    Scene(
        id='compute-custom', title='A custom aggregation',
        blurb='Any expression over the column, kept under it like the built-in ones.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), submenu('compute', AGE)],
        hover='.col-compute-expr',
        click=[typed_into(f"lambda e: ComputeExprInput(col={AGE!r}, expr='', value=e.get('value', ''), previous=e.get('previous'))",
                          'max($) - min($)'),
               key('ComputeExprKeyDown', 'Enter')],
        action=('Open the <b>age</b> column\'s ▾ menu, rest on <b>Compute</b>, type '
                '<code>max($) - min($)</code> in the empty box at the foot, and press Enter.'),
    ),
    Scene(
        id='table-any-all', title='Any / All',
        blurb='Whether any row (or every row) matches the search.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover=action_button('any'),
        click=click("ActionButtonClick(action='any', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click <b>Any/All</b>. '
                'The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='first-match', title='First match only',
        blurb='Just the first row the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover='[snc-mouse-down="FirstMatchToggle()"]',
        click=click('FirstMatchToggle()'),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click the <b>1st</b> toggle. '
                'The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='edit-column', title='Edit a column expression',
        blurb='Rewrite what a column shows.',
        source=PEOPLE, line=1,
        setup=[],
        hover="[snc-mouse-down^=\"ColumnClick\"]|$['age']",
        click=[click(f'ColumnClick(col={AGE!r})', detail=2),
               typed('ColumnInput', "$['age'] + 1"), key('ColumnKeyDown', 'Enter')],
        action=('Double-click the <b>age</b> header, type <code>$[\'age\'] + 1</code>, '
                'and press Enter.'),
    ),
    Scene(
        id='reorder-columns', title='Reorder columns by dragging',
        blurb='Drag a column by its handle to another position.',
        source=PEOPLE, line=1,
        setup=[],
        hover="th|$['age']|.col-drag-handle",
        click=[click(f'ColumnDragStart(col={AGE!r})'),
               move('ColumnDragOver(col="$[\'name\']")'),
               release('ColumnDragEnd(col="$[\'name\']")')],
        action='Drag the <b>age</b> column\'s handle onto the <b>name</b> column.',
    ),
    Scene(
        id='load-more', title='Load more rows',
        blurb='The table shows 50 rows and the last three; the rest come a page at a time.',
        source=NUMS, line=1,
        setup=[],
        hover='.load-more',
        click=click('LoadMoreRows()'),
        action='Click <b>Load more</b>.',
    ),
    Scene(
        id='row-menu-more', title='Delete Item',
        blurb='The list without one row.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '1'))))],
        hover='.row-action|Delete Item 1',
        click=click("RowActionClick(row=1, action='delete')"),
        action='Open the ▾ menu on row <b>1</b>\'s number and click <b>Delete Item 1</b>.',
    ),
    Scene(
        id='literal-drag', title='Literal drag',
        blurb='Drag across the top half of characters to match them literally.',
        source=LOG, line=1,
        setup=[],
        hover='.string-visualizer',
        click=[click(f'MouseDown(index={LOG_TEXT.index("2024") + 1})'),
               move(f'MouseMove(index={LOG_TEXT.index("2024") + 10})'),
               release(f'MouseUp(index={LOG_TEXT.index("2024") + 10})')],
        action='Drag across the top half of <b>2024-05-01</b>.',
    ),
    Scene(
        id='fuzzy-drag', title='Fuzzy drag',
        blurb='Drag across the bottom half to match a character class instead.',
        source=LOG, line=1,
        setup=[],
        hover='.string-visualizer',
        click=[click(f'MouseDown(index={LOG_TEXT.index("66") + 1})', top_half=False),
               move(f'MouseMove(index={LOG_TEXT.index("66") + 2})', top_half=False),
               release(f'MouseUp(index={LOG_TEXT.index("66") + 2})', top_half=False)],
        action='Drag across the bottom half of <b>66</b>.',
    ),
    Scene(
        id='string-match-objects', title='Match Objects',
        blurb='The matches as match objects rather than strings.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover=action_button('find_or_map'),
        click=click("ActionButtonClick(action='find_or_map', copy=False)"),
        action='With a search typed, click <b>Match Objects</b>. The linked line is rewritten in place.',
    ),
    Scene(
        id='string-replace', title='Replace',
        blurb='Every match replaced by what you type.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover='.disclosure-button',
        click=[click('ReplaceToggle()'), typed('ReplaceBoxInput', "'<date>'"),
               click("ActionButtonClick(action='replace', copy=False)")],
        action=('With a search typed, open the replace box, type <code>\'&lt;date&gt;\'</code>, '
                'and click <b>Replace</b>. The linked line is rewritten in place.'),
    ),
    Scene(
        id='string-any-all', title='Any / All',
        blurb='Whether the string has a match at all.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover=action_button('any'),
        click=click("ActionButtonClick(action='any', copy=False)"),
        action='With a search typed, click <b>Any/All</b>. The linked line is rewritten in place.',
    ),
    Scene(
        id='string-loop', title='Loop',
        blurb='A for loop over the matches.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover='.action-button|Loop',
        click=click("ActionButtonClick(action='loop', copy=False)"),
        action=('With a search typed, click <b>Loop › Over match objects</b>. '
                'The linked line is rewritten as a loop.'),
    ),
    Scene(
        id='fetch', title='Read Filepath',
        blurb='A string that names a file is one read away from its contents.',
        source=PATH, line=1,
        setup=[],
        hover='.action-button|Fetch',
        click=click("FetchClick(source='file', fmt='text')"),
        action='Rest on <b>Fetch</b> and click <b>Read Filepath › as string</b>.',
    ),
    Scene(
        id='sort-in-place', title='Sort in place',
        blurb='Order the rows by a column, rewriting the line the table is showing.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), submenu('sort', AGE)],
        hover='[snc-mouse-down^="SortClick"]|Asc',
        click=click(f"SortClick(col={AGE!r}, direction='asc')"),
        action='Open the <b>age</b> column\'s ▾ menu, rest on <b>Sort</b>, and tick <b>Asc</b>.',
    ),
    Scene(
        id='change-type-in-place', title='Change Type in place',
        blurb='Read the column itself as another type.',
        source=AGES, line=1,
        setup=[column_menu(AGE), submenu('convert', AGE)],
        hover='[snc-mouse-down^="ConvertTypeToggle"]|int',
        click=click(f"ConvertTypeToggle(col={AGE!r}, to='int')"),
        action='Open the <b>age</b> column\'s ▾ menu, rest on <b>Change Type</b>, and tick <b>int</b>.',
    ),
    Scene(
        id='unsplat', title='Collapse lists to single cells',
        blurb='Undo an expansion: each list comes home to one cell.',
        source=PETS_SPLAT, line=1,
        setup=[column_menu(PETS_COL)],
        hover='.col-expand-rows',
        click=click(f'UnsplatColumnClick(col={PETS_COL!r})'),
        action='Open the expanded <b>pets</b> column\'s ▾ menu and click <b>Collapse lists to single cells</b>.',
    ),
    Scene(
        id='compute-per-group', title='Per-group answers',
        blurb='On an expanded column, one answer per group becomes a column.',
        source=PETS_SPLAT, line=1,
        setup=[column_menu(PETS_COL), submenu('compute', PETS_COL),
               click('SelectGroupedComputeTab(grouped=True)')],
        hover='[snc-mouse-down*="per_group=True"]|# Unique',
        click=click(f"ComputeToggle(col={PETS_COL!r}, expr='len(set($))', per_group=True)"),
        action=('Open the expanded <b>pets</b> column\'s ▾ menu, rest on <b>Compute</b>, switch to the '
                '<b>Per Group</b> tab, and tick <b># Unique</b>.'),
    ),
    Scene(
        id='tally-exclude', title='Tally: Exclude',
        blurb='Keep every row except the ones holding the ticked values.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT), click(f"TallyItemToggle(col={DEPT!r}, literal=\"'eng'\")")],
        hover='.col-tally-exclude',
        click=click(f'TallyExcludeToggle(col={DEPT!r})'),
        action='With <b>\'eng\'</b> ticked in the <b>dept</b> tally, click <b>Exclude</b>.',
    ),
    Scene(
        id='tally-select', title='Tally: All / None',
        blurb='Tick or untick every value shown at once.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT), click(f"TallyItemToggle(col={DEPT!r}, literal=\"'eng'\")")],
        hover='[snc-mouse-down^="TallySelectAll"]',
        click=click(f'TallySelectAll(col={DEPT!r})'),
        action='With <b>\'eng\'</b> ticked in the <b>dept</b> tally, click <b>All</b>.',
    ),
    Scene(
        id='tally-sort-count', title='Tally: narrow by count',
        blurb='Show only the values that occur at least so many times.',
        source=PEOPLE, line=1,
        setup=[column_menu(DEPT)],
        hover='.col-tally-count-filter',
        click=typed_into(f"lambda e: TallyCountFilterInput(col={DEPT!r}, value=e.get('value', ''))", '2'),
        action='Open the <b>dept</b> column\'s ▾ menu and type <code>2</code> in the tally\'s count box.',
        keep_menu=True,
    ),
    Scene(
        id='column-search-op', title='Search a column: operator',
        blurb='Pick how a column\'s search compares.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), click(f"ColumnSearchDropdownToggle(dropdown_id={_menu_id('op', AGE)!r})")],
        hover='.col-search-chip-panel .snc-dropdown-option|>=',
        click=[click(f"ColumnSearchOpSelect(col={AGE!r}, op='>=')"),
               typed_into(f"lambda e: ColumnSearchInput(col={AGE!r}, value=e.get('value', ''))", '30')],
        action=('Open the <b>age</b> column\'s ▾ menu, pick <b>>=</b> from the operator chip, '
                'and type <code>30</code> in its search box.'),
    ),
    Scene(
        id='table-if-any', title='If Any / If All',
        blurb='An if statement on whether any row (or every row) matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover='.action-button|Any/All',
        click=click("ActionButtonClick(action='if_any', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click '
                '<b>Any/All › If Any</b>. The linked Filter line is rewritten in place.'),
    ),
    Scene(
        id='table-filter-button', title='Filter',
        blurb='Bring the linked line back to the rows the search matches.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG), click("ActionButtonClick(action='count', copy=False)")],
        hover=action_button('filter'),
        click=click("ActionButtonClick(action='filter', copy=False)"),
        action=('With a search typed and the linked line showing a count, click <b>Filter</b>. '
                'The line is rewritten back to a filter.'),
    ),
    Scene(
        id='resize-column', title='Resize a column',
        blurb='Drag a header\'s edge; the width is saved with the line.',
        source=PEOPLE, line=1,
        setup=[],
        hover="th|$['age']|.col-resize-right",
        click=release(f'ColumnResize(col={AGE!r}, width=160)'),
        action='Drag the right edge of the <b>age</b> header.',
    ),
    Scene(
        id='match-case', title='Match case',
        blurb='Whether the search minds the difference between upper and lower case.',
        source=CASE_LOG, line=1,
        setup=[typed('SearchBoxInput', "r'order'")],
        hover='[snc-mouse-down="CaseSensitiveToggle()"]',
        click=click('CaseSensitiveToggle()'),
        action='With <code>r\'order\'</code> typed, click the <b>Aa</b> toggle. The linked line is rewritten in place.',
    ),
    Scene(
        id='capture-groups', title='Capture groups',
        blurb='Hand back the groups of each match instead of the whole of it.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', "r'(\\d{4})-(\\d\\d)'")],
        hover='[snc-mouse-down="CaptureGroupsToggle()"]',
        click=click('CaptureGroupsToggle()'),
        action=('With <code>r\'(\\d{4})-(\\d\\d)\'</code> typed, click the <b>( )</b> toggle. '
                'The linked line is rewritten in place.'),
    ),
    Scene(
        id='string-indexes', title='Indexes',
        blurb='Where each match starts and ends.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover=action_button('find_indices'),
        click=click("ActionButtonClick(action='find_indices', copy=False)"),
        action='With a search typed, click <b>Indexes</b>. The linked line is rewritten in place.',
    ),
    Scene(
        id='string-loop-strings', title='Loop over matched strings',
        blurb='A for loop over the matches as strings.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover='.action-button|Loop',
        click=click("ActionButtonClick(action='loop_match_strings', copy=False)"),
        action=('With a search typed, click <b>Loop › Over matched strings</b>. '
                'The linked line is rewritten as a loop.'),
    ),
    Scene(
        id='fetch-json', title='Read Filepath as JSON',
        blurb='A path to a JSON file, parsed.',
        source=JSON_PATH, line=1,
        setup=[],
        hover='.action-button|Fetch',
        click=click("FetchClick(source='file', fmt='json')"),
        action='Rest on <b>Fetch</b> and click <b>Read Filepath › as JSON</b>.',
    ),
    Scene(
        id='fetch-csv', title='Read Filepath as CSV',
        blurb='A path to a CSV file, read as rows.',
        source=CSV_PATH, line=1,
        setup=[],
        hover='.action-button|Fetch',
        click=click("FetchClick(source='file', fmt='csv')"),
        action='Rest on <b>Fetch</b> and click <b>Read Filepath › as CSV</b>.',
    ),
    Scene(
        id='string-map', title='Map',
        blurb='An expression over each match, in the replace box.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE)],
        hover='.disclosure-button',
        click=[click('ReplaceToggle()'), typed('ReplaceBoxInput', '$[0].replace(\'-\', \'/\')')],
        action=('With a search typed, open the replace box and type '
                '<code>$[0].replace(\'-\', \'/\')</code>. The linked line becomes a map over the matches.'),
    ),
    Scene(
        id='index-drag', title='Index drag',
        blurb='Drag with the index tool to make a slice.',
        source=LOG, line=1,
        setup=[click("ToolSelect(tool='index')")],
        hover='.string-visualizer',
        click=[click(f'MouseDown(index={LOG_TEXT.index("2024") + 1})'),
               move(f'MouseMove(index={LOG_TEXT.index("2024") + 10})'),
               release(f'MouseUp(index={LOG_TEXT.index("2024") + 10})'),
               click("ActionButtonClick(action='find_or_map', copy=False)")],
        action=('Pick the <b>index</b> tool (or hold ctrl), drag across <b>2024-05-01</b>, '
                'and click <b>Slice</b>.'),
    ),
    Scene(
        id='chain-segments', title='Chain segments',
        blurb='Start a new drag where the last selection ends to add a segment.',
        source=LOG, line=1,
        setup=[click(f'MouseDown(index={LOG_TEXT.index("shipped ") + 1})'),
               move(f'MouseMove(index={LOG_TEXT.index("shipped ") + 8})'),
               release(f'MouseUp(index={LOG_TEXT.index("shipped ") + 8})')],
        hover='.string-visualizer',
        click=[click(f'MouseDown(index={LOG_TEXT.index("2024") + 1})', top_half=False),
               move(f'MouseMove(index={LOG_TEXT.index("2024") + 10})', top_half=False),
               release(f'MouseUp(index={LOG_TEXT.index("2024") + 10})', top_half=False)],
        action=('With <b>shipped </b> selected literally, drag across the bottom half of '
                '<b>2024-05-01</b> starting right where that selection ends.'),
    ),
    Scene(
        id='resize-segment', title='Resize a segment',
        blurb='Drag a segment\'s handle to take in more (or fewer) characters.',
        source=LOG, line=1,
        setup=[click(f'MouseDown(index={LOG_TEXT.index("shipped") + 1})'),
               move(f'MouseMove(index={LOG_TEXT.index("shipped") + 7})'),
               release(f'MouseUp(index={LOG_TEXT.index("shipped") + 7})'),
               # Resting the pointer on the segment is what draws its handles.
               hover_move(f'MouseMove(index={LOG_TEXT.index("shipped") + 4})')],
        hover='.chr-resize-handle.right',
        click=[click("HandleMouseDown(segment_index=0, side='right', match_index=0)"),
               move(f'MouseMove(index={LOG_TEXT.index("shipped") + 12})'),
               release(f'MouseUp(index={LOG_TEXT.index("shipped") + 12})')],
        action='With <b>shipped</b> selected, drag its right handle five characters further.',
    ),
    Scene(
        id='segment-menu', title='Segment menu',
        blurb='Change how often a segment repeats, or its character class.',
        source=LOG, line=1,
        setup=[click(f'MouseDown(index={LOG_TEXT.index("66") + 1})', top_half=False),
               move(f'MouseMove(index={LOG_TEXT.index("66") + 2})', top_half=False),
               release(f'MouseUp(index={LOG_TEXT.index("66") + 2})', top_half=False),
               click("DropdownToggle(dropdown_id='repetition-0-0')")],
        hover='[snc-mouse-down*="RepetitionInput"]',
        click=[typed_into("lambda e: RepetitionInput(dropdown_id='repetition-0-0', field='exact', value=e.get('value', ''))", '2'),
               click("DropdownToggle(dropdown_id='repetition-0-0')")],
        action=('With <b>66</b> selected fuzzily, open the segment\'s repetition menu, '
                'type <code>2</code> in the exact box, and close the menu.'),
    ),
    Scene(
        id='string-pick', title='Pick',
        blurb='Click the pieces of the first match to build an expression.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE), click("ToolSelect(tool='pick')")],
        hover='[snc-mouse-down*="SegmentToggle(segment_id=\'prefix\')"]',
        click=click("SegmentToggle(segment_id='prefix')"),
        action='With a search typed, pick the <b>pick</b> tool and click the <b>prefix</b> chip.',
    ),
    Scene(
        id='string-filter', title='Filter',
        blurb='Keep the matches for which an expression holds.',
        source=LOG, line=1,
        setup=[typed('SearchBoxInput', DATE_RE), click('ReplaceToggle()'),
               typed('ReplaceBoxInput', "$[0] > '2024-06'")],
        hover=action_button('filter'),
        click=click("ActionButtonClick(action='filter', copy=False)"),
        action=('With a search typed and <code>$[0] &gt; \'2024-06\'</code> in the replace box, '
                'click <b>Filter</b>.'),
    ),
    Scene(
        id='row-pop', title='Pop Item',
        blurb='Take one row out, keeping both the row and the list without it.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '1'))))],
        hover='.row-action|Pop Item 1',
        click=click("RowActionClick(row=1, action='pop')"),
        action='Open the ▾ menu on row <b>1</b>\'s number and click <b>Pop Item 1</b>.',
    ),
    Scene(
        id='row-cells', title='Extract Row Cells',
        blurb='One row\'s cells, as the columns show them.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '1'))))],
        hover='.row-action|Extract Row 1 Cells as Tuple',
        click=click("RowActionClick(row=1, action='cells')"),
        action='Open the ▾ menu on row <b>1</b>\'s number and click <b>Extract Row 1 Cells as Tuple</b>.',
    ),
    Scene(
        id='row-headers', title='Use Item as Headers',
        blurb='Turn a list of rows whose first row names the columns into a list of dicts.',
        source=HEADED, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '0'))))],
        hover='.row-action|Use Item 0 as Headers',
        click=click("RowActionClick(row=0, action='headers')"),
        action='Open the ▾ menu on row <b>0</b>\'s number and click <b>Use Item 0 as Headers</b>.',
    ),
    Scene(
        id='row-delete-matching', title='Delete matching items',
        blurb='The list without every row equal to this one.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '1'))))],
        hover='.row-action|Delete {',
        click=click("RowActionClick(row=1, action='delete_matching')"),
        action='Open the ▾ menu on row <b>1</b>\'s number and click <b>Delete {…} Items</b>.',
    ),
    Scene(
        id='row-last', title='The last row',
        blurb='The last row named as the last one, so the line still means it when the list grows.',
        source=PEOPLE, line=1,
        setup=[click(repr(DropdownToggle(dropdown_id=_menu_id('row-menu', '2'))))],
        hover='.row-action|Extract Last Item',
        click=click("RowActionClick(row=2, action='last_item')"),
        action='Open the ▾ menu on the last row\'s number and click <b>Extract Last Item</b>.',
    ),
    Scene(
        id='table-loop-index', title='Loop with the index',
        blurb='A for loop over the matched rows that also counts them.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG)],
        hover='.action-button|Loop',
        click=click("ActionButtonClick(action='loop_orig_idx', copy=False)"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, click '
                '<b>Loop › Original indices</b>. The linked Filter line is rewritten as a loop.'),
    ),
    Scene(
        id='table-join-sep', title='Join with a separator',
        blurb='The cells joined with a separator picked from the Join menu.',
        source=NAMES, line=1,
        setup=[],
        hover='.action-button|Join',
        click=click("ActionButtonClick(action=\"join:', '\", copy=False)"),
        action='Rest on <b>Join</b> and click <b>\', \'</b>.',
    ),
    Scene(
        id='compute-percentile', title='Percentile',
        blurb='A percentile of the column, with its level typed into the box.',
        source=PEOPLE, line=1,
        setup=[column_menu(AGE), submenu('compute', AGE),
               click(f"ComputeToggle(col={AGE!r}, expr='np.percentile($, {{{{10}}}})')")],
        hover='.col-agg-label input',
        click=typed_into(f"lambda e: ComputeHoleInput(col={AGE!r}, expr='np.percentile($, {{{{10}}}})', hole=0, value=e.get('value', ''), previous=e.get('previous'))", '50'),
        action=('Tick <b>Percentile</b> in the <b>age</b> column\'s Compute submenu, then type '
                '<code>50</code> into the level box of the cell it made.'),
    ),
    Scene(
        id='compute-histogram', title='Histogram',
        blurb='The column\'s values binned and drawn as bars.',
        source=NUMS, line=1,
        setup=[column_menu('$'), submenu('compute', '$')],
        hover='.col-compute-row|Histogram|.col-compute-toggle',
        click=click("ComputeToggle(col='$', expr='counts, edges = np.histogram($, bins={{10}})')"),
        action='Open the column\'s ▾ menu, rest on <b>Compute</b>, and tick <b>Histogram</b>.',
    ),
    Scene(
        id='object-edit-field', title='Edit a field',
        blurb='Rewrite what a field reads.',
        source=MATCH, line=2,
        setup=[],
        hover='[snc-mouse-down="FieldClick(index=1)"]',
        click=[click('FieldClick(index=1)', detail=2), typed('FieldInput', '$.start(0) + 1'),
               key('KeyDown', 'Enter')],
        action='Double-click <b>$.start(0)</b>, type <code>$.start(0) + 1</code>, and press Enter.',
    ),
    Scene(
        id='object-remove-field', title='Remove a field',
        blurb='Take a field off the object\'s table.',
        source=MATCH, line=2,
        setup=[],
        hover='[snc-mouse-down="RemoveFieldClick(index=2)"]',
        click=click('RemoveFieldClick(index=2)'),
        action='Click the <b>×</b> beside <b>$.end(0)</b>.',
    ),
    Scene(
        id='object-reorder-fields', title='Reorder fields by dragging',
        blurb='Drag a field by its handle to another position.',
        source=MATCH, line=2,
        setup=[],
        hover='[snc-mouse-down="DragStart(index=2)"]',
        click=[click('DragStart(index=2)'), move('DragOver(index=0)'), release('DragEnd(index=0)')],
        action='Drag <b>$.end(0)</b>\'s handle to the top.',
    ),
    Scene(
        id='table-pick', title='Pick',
        blurb='Click cells of the first matched row to assemble an expression over it.',
        source=PEOPLE, line=1,
        setup=[typed('SearchBoxInput', SEARCH_ENG), click("ToolSelect(tool='pick')")],
        hover='[data-pick-region="match_col_1"]',
        click=click("PickToggle(region_id='match_col_1')"),
        action=(f'With <code>{html.escape(SEARCH_ENG)}</code> in the search box, pick the '
                '<b>Pick</b> tool and click the <b>name</b> cell of the first matching row. '
                'The linked Filter line is rewritten to that cell.'),
    ),
    Scene(
        id='nested', title='Nested visualizers',
        blurb=('A string in a table cell gets the string visualizer; what it writes '
               'reads through the parent, here as a new column.'),
        source=ORDERS, line=1,
        setup=[click("ChildEvent('0\\x00$', \"PinFocus()\")"),
               typed_into("ChildEvent('0\\x00$', \"lambda e: SearchBoxInput(value=e.get('value', ''))\")",
                          "r'\\d+'")],
        hover="[snc-child-key=\"'0\\x00$'\"] .visualizer-container",
        click=click("ChildEvent('0\\x00$', \"ActionButtonClick(action='match_strings', copy=False)\")"),
        action=('Click the first cell to focus its string, type <code>r\'\\d+\'</code> in its '
                'search box, and click <b>Substrs</b>.'),
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
            ('column-search', 'Search a column', 'A search written in the column\'s scope.'),
            ('column-search-op', 'Search a column: operator', 'The chips pick the comparison and how it composes with other columns.'),
            ('tally-filter', 'Tally', 'Tick values to keep the rows holding them.'),
            ('tally-exclude', 'Tally: Exclude', 'Keep every row except the ticked values.'),
            ('tally-select', 'Tally: All / None', ''),
            ('tally-sort-count', 'Tally: narrow by count', 'The sort chip and count box narrow which values the tally lists.'),
            ('sort', 'Sort', 'The insert rows write a sorted copy of the list.'),
            ('sort-in-place', 'Sort in place', 'Ticking Asc / Desc rewrites the line the table shows.'),
            ('group-by', 'Group By', ''),
            ('change-type', 'Change Type', 'Read the column as int / float / str / bool as a new column.'),
            ('change-type-in-place', 'Change Type in place', 'Ticking a type converts the column itself.'),
            ('subcolumns', 'Subcolumns', 'Spread a column of records across several sub-columns.'),
            ('splat', 'Expand list items into rows', 'A column of lists becomes one row per element.'),
            ('unsplat', 'Collapse lists to single cells', 'Each list comes home to one cell.'),
            ('compute', 'Compute', 'Sum, min, max, mean, median, counts and the rest, kept under the column.'),
            ('compute-percentile', 'Percentile', 'Its level typed into the box.'),
            ('compute-histogram', 'Histogram', 'Drawn as bars.'),
            ('compute-custom', 'A custom aggregation', 'Type any expression over the column.'),
            ('compute-per-group', 'Per-group answers', 'On a splatted column, one answer per group becomes a column.'),
            ('unique-tally', 'Unique / Tally', 'Write set($) or Counter($) as a line.'),
            ('insert-column-beside', 'Insert Left / Insert Right', ''),
            ('remove-column', 'Remove', ''),
        ]),
        ('A row\'s ▾ menu', [
            ('row-menu', 'Extract Item', 'Take one row out as a line of its own.'),
            ('row-menu-more', 'Delete Item', ''),
            ('row-pop', 'Pop Item', ''),
            ('row-cells', 'Extract Row Cells', ''),
            ('row-headers', 'Use Item as Headers', 'A list of rows whose first row names the columns becomes a list of dicts.'),
            ('row-delete-matching', 'Delete matching items', ''),
            ('row-last', 'The last row', 'Delete, Pop, Extract and Cells, named as the last one.'),
        ]),
        ('The search box and action bar', [
            ('search', 'Search', 'A predicate with $, $i, $$ and $$$; the Filter line is written as you type.'),
            ('first-match', 'First match only', ''),
            ('table-filter-button', 'Filter', 'Bring a linked line back to the rows the search matches.'),
            ('table-count', 'Count', ''),
            ('table-delete', 'Delete All', 'The list without the matched rows.'),
            ('table-indexes', 'Find Indices', 'The positions of the matched rows.'),
            ('table-extract', 'Extract', 'The columns on show, as a list.'),
            ('table-join', 'Join', ''),
            ('table-join-sep', 'Join with a separator', ''),
            ('table-any-all', 'Any / All', ''),
            ('table-if-any', 'If Any / If All', ''),
            ('table-loop', 'Loop', 'A for loop over the matched rows.'),
            ('table-loop-index', 'Loop with the index', 'Original or new indices.'),
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
            ('string-toggles', 'First match', ''),
            ('match-case', 'Match case', 'Ignore case, with re.I.'),
            ('capture-groups', 'Capture groups', 'Hand back the groups of each match.'),
            ('string-replace', 'Replace', 'Open the replace box and write re.sub.'),
            ('string-map', 'Map', 'The replace box as a mapping over the matches.'),
        ]),
        ('The action bar', [
            ('string-match-objects', 'Match Objects', 'The matches as match objects.'),
            ('string-indexes', 'Indexes', 'Where each match starts.'),
            ('string-count', 'Count', ''),
            ('string-split', 'Split', ''),
            ('string-delete', 'Delete', ''),
            ('string-filter', 'Filter', 'Keep the matches for which the replace-box expression holds.'),
            ('string-any-all', 'Any / All / If any / If all', ''),
            ('string-loop', 'Loop', 'Loop over the match objects.'),
            ('string-loop-strings', 'Loop over matched strings', ''),
            ('fetch', 'Read Filepath', 'Read a string that names a file, as text; Fetch URL does the same over the network.'),
            ('fetch-json', 'Read Filepath as JSON', ''),
            ('fetch-csv', 'Read Filepath as CSV', 'Excel is read the same way.'),
        ]),
    ]),
    ('Objects and tuples', [
        ('', [
            ('object-add-field', 'Add a field', 'Type an accessor, with autocomplete over the object\'s attributes.'),
            ('object-edit-field', 'Edit a field', ''),
            ('object-remove-field', 'Remove a field', ''),
            ('object-reorder-fields', 'Reorder fields by dragging', ''),
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
    after_model = clicked[(line, 0)]['model']

    # The editor keeps the caret on the trigger line after a click, so the
    # widget that was clicked stays focused and the line it wrote draws small.
    # Its model (the search typed, the menu closed) carries over to the rerun,
    # as it does in the editor.
    after_source, _, linked, line = apply_commands(before_source, commands, linked, line)

    # Ticking a box leaves the menu open for the next tick, which in the
    # After picture would cover the result. Click away from it, as a user
    # would, unless the scene is about what the menu itself shows. Against the
    # source as the click left it: a rewritten #%click comment changes the
    # line's signature, and the runner drops events on a model it rebuilt.
    if not scene.keep_menu and (after_model.get('openDropdown')
                                or after_model.get('col_search_dropdown')):
        dismissed = run(after_source, line,
                        queued(line, after_model, [click('ColumnMenuDismiss()')]))
        if dismissed[(line, 0)]['handledEventIds']:
            after_model = dismissed[(line, 0)]['model']
            after_source, _, _, line = apply_commands(
                after_source, dismissed[(line, 0)].get('commands') or [], linked, line)

    after = run(after_source, line, queued(line, after_model, []))
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
    # The drawn cursor hovers nothing, but many controls (a column's ▾, a
    # field's ×, drag handles, segment handles) only show under the pointer.
    # Every :hover rule also matches the marker the page puts on the cursor's
    # target and its ancestors, so what the user would see is what is drawn.
    return (strings + '\n' + main).replace(':hover', ':is(:hover, .doc-hover-path)')


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

/* The scene's hover: the cursor itself. What it rests on is marked with
   .doc-hover-path, which the widget CSS treats as :hover. */
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
			// The pointer is over the target and everything around it.
			for (let node = el; node && node !== pane.parentElement; node = node.parentElement) {
				node.classList.add('doc-hover-path');
			}
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
    from fontTools import subset
    from fontTools.ttLib import TTFont
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


def build_in_subprocess(scene_id: str) -> tuple:
    """Build one scene in a fresh interpreter. The editor gives every run a
    fresh Python process, and building all the scenes in one process lets
    state leak between them (a custom aggregation came out blank that way)."""
    import shutil
    import subprocess
    # The interpreter the editor itself falls back to, with the user's numpy
    # and pandas -- not uv's isolated script environment, which has neither
    # and so answers every aggregation with nothing.
    # uv puts its own environment first on PATH, so look past it.
    outside = os.pathsep.join(p for p in os.environ.get('PATH', '').split(os.pathsep)
                              if not p.startswith(sys.prefix))
    python = shutil.which('python3', path=outside) or sys.executable
    env = {k: v for k, v in os.environ.items() if k != 'VIRTUAL_ENV'}
    env['PATH'] = outside
    proc = subprocess.run([python, __file__, '--scene', scene_id],
                          capture_output=True, text=True, cwd=REPO, env=env)
    if proc.returncode != 0:
        return scene_id, None, proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'failed'
    before_html, after_html = json.loads(proc.stdout.splitlines()[-1])
    return scene_id, (before_html, after_html), None


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == '--scene':
        scene = next(sc for sc in SCENES if sc.id == sys.argv[2])
        build(scene)
        print(json.dumps([scene.before_html, scene.after_html]))
        return

    from concurrent.futures import ThreadPoolExecutor
    jobs = int(os.environ.get('SNC_DOCS_JOBS') or (os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(build_in_subprocess, [sc.id for sc in SCENES]))
    built = []
    by_id = {sc.id: sc for sc in SCENES}
    for scene_id, htmls, error in results:
        if htmls is None:
            print(f'FAILED {scene_id}: {error}')
            continue
        by_id[scene_id].before_html, by_id[scene_id].after_html = htmls
        built.append(by_id[scene_id])
    out = os.path.join(HERE, 'index.html')
    with open(out, 'w') as f:
        f.write(render_page(built))
    print(f'wrote {out} ({len(built)} of {len(SCENES)} scene(s))')


if __name__ == '__main__':
    main()
