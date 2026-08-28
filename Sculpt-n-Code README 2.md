# Sculpt-n-Code  Implementation Details

## How It Works

When a Python file is open in the editor, SNC:

1. **Parses** the user's code into a Python AST.
2. **Transforms** the AST by injecting `_log_value()` calls after every assignment, expression, conditional, loop iteration, and return statement, and loop/call context hooks around loops and function bodies.
3. **Executes** the transformed code in a pooled Python worker subprocess.
4. **Streams** JSON-encoded visualization items (one per logged value) back to the editor over stdout.
5. **Renders** each item as an HTML overlay widget positioned at the end of the corresponding source line.

The user's original line numbers are preserved through AST compilation (it's not string-based code generation), so error tracebacks still point to the correct lines. User program `stdout`/`stderr` are captured separately from the visualization stream.

## Architecture

The system is split across three layers:

```
┌──────────────────────────────────────────────────────────┐
│  VS Code Renderer (TypeScript)                           │
│  src/vs/editor/contrib/snc/browser/snc.ts                │
│  - SNCController: editor contribution, manages lifecycle │
│  - VisualizationWidget: overlay widget per value per line│
│  - Debounced re-execution on every edit                  │
│  - Routes mouse/keyboard events from HTML back to Python │
│  - Elm-style command handling (e.g. NewCode inserts line │
│    edits; CopyToClipboard writes text to clipboard)      │
└────────────────────┬─────────────────────────────────────┘
                     │ IPC channel "sncProcess"
                     │ (VS Code's mainProcessService)
┌────────────────────▼─────────────────────────────────────┐
│  Main Process Service (TypeScript, Node.js)              │
│  src/vs/platform/snc/node/sncProcessService.ts           │
│  - SNCProcessService: spawns & manages Python processes  │
│  - Checkpointed process pools (CP1/CP2 workers)          │
│  - Streams NDJSON from Python stdout → onStream event    │
│  - Timing instrumentation (spawn → stdout → render)      │
└────────────────────┬─────────────────────────────────────┘
                     │ stdin/stdout (NDJSON)
┌────────────────────▼─────────────────────────────────────┐
│  Python Runner + Visualizers                             │
│  src/vs/platform/snc/node/python_runner.py               │
│  - AST parsing → CodeTransformer → compile → exec        │
│  - Pool-worker mode: workers emit checkpoint_ready(1),   │
│    optionally warm to checkpoint_ready(2) by pre-running │
│    leading imports for the current code                  │
│  - Per-run visualizer reload by file mtime; pluggable    │
│    visualizer system loaded from disk                    │
│                                                          │
│  src/vs/platform/snc/node/visualizers/                   │
│  - the type-specific visualizers                         │
└──────────────────────────────────────────────────────────┘
```

### Communication Protocol

Node.js and Python communicate over stdio using **newline-delimited JSON (NDJSON)**. Message types:

| Message Type | Direction | Purpose |
|---|---|---|
| `init_imports` | Node → Python | Warm this worker to checkpoint 2 by pre-running the code's leading imports |
| `run` | Node → Python | Execute this code; carries `models_and_events`, `stdin`, `loop_selections`, the focused line |
| `events` | Node → Python | Events for a run already under way, for a widget it hasn't reached yet |
| `checkpoint_ready` | Python → Node | Worker reached checkpoint 1 or 2 and is ready |
| `item` | Python → Node → Renderer | A single visualization item (line, visIndex, html, model, handledEventIds) |
| `command` | Python → Node → Renderer | An Elm-style command for VS Code (e.g. `NewCode`) |
| `loop` | Python → Node → Renderer | A loop/function finished: `{line, path, count}`; sizes its slider (see Loops below) |
| `output` | Python → Node → Renderer | A chunk of the program's stdout/stderr, tagged with how much stdin had been consumed |
| `end` | Python → Node → Renderer | Run completed; includes exitCode and, when the program is waiting on input, `awaitingInput` |
| `warning` | Python → Node → Renderer | Visualizer load/runtime warning |
| `error` | Node → Renderer | Process error or timeout |
| `spawn` | Node → Renderer | Timing data when process was spawned |

One invariant on the Python side: **a single reader owns the protocol fd**, via `read_stdin_line` / `drain_stdin_lines`, which share one byte buffer. `sys.stdin.readline()` must not be used alongside them — it is a `TextIOWrapper` over a `BufferedReader` that reads ahead by whole chunks, so bytes sitting in its buffer are invisible to a raw read, and an `events` message arriving hard behind a `run` message would simply vanish. (The fd is switched to non-blocking once the handshake is read, so the mid-run drain never stalls the user's program. `sys.stdin` itself is the program's stand-in stream — see the console section — and is unrelated to this fd.)

### Interactive Visualizer Protocol (Elm Architecture)

Visualizers that support interaction implement the Elm architecture:

- **`init_model(value)`** — returns initial state for this visualization instance.
- **`visualize(value, model)`** — renders HTML from the value and current model. HTML elements can carry `snc-mouse-down`, `snc-mouse-move`, `snc-mouse-up`, `snc-key-down`, and `snc-input` attributes whose values are Python expression strings. Nested visualizers can route events with `snc-child-key`.
- **`update(event, source_code, source_line, model, value)`** — processes a UI event and returns `(new_model, commands)`. Commands include `NewCode` (line-based insert edits), `CopyToClipboard`, and `SetConfigComment` (rewrite the line's saved-config comment; see below).

Models are serialized to JSON and round-tripped through the TypeScript frontend so they survive across re-executions. The value itself is **not** stored in the model; it is always passed as a parameter.

#### How an event reaches its visualizer

An event is queued on its widget (`unhandledEvents`, keyed by `(line, visIndex)`) and ships with the next run in `models_and_events`. A run reaches a widget long before the program ends, so an event does **not** need a run of its own:

- If a run is in flight that hasn't yet produced the item for that widget, the event is sent to it (`sendEvents` → an `events` message on the worker's stdin) and **no new run starts**. `log_value` drains stdin just before it looks up a widget's events, so the run applies everything queued up to the instant it arrives there. A hover at 60Hz then costs one run per trip through the program instead of sixty.
- Otherwise the event starts a run as before.

**The runner reports which events it applied**, as `handledEventIds` on the item, and the editor requeues everything else. It can't be inferred from what was sent: the runner declines to replay onto a model it had to rebuild (a changed type invalidates the `_type_fingerprint`), and events can arrive just behind the widget. Ids are stamped in `sendEventToPython` because object identity doesn't survive the trip through Python. Leftovers get exactly one `queued-events` retry, after which they're dropped rather than spinning runs forever; events for a widget a completed run never reached are dropped too, since that widget isn't part of this execution.

Static (non-interactive) visualizers only need `can_visualize(value)` and `visualize(value)`.

### Per-line visualizer config: the `#%click` comment

What a visualizer persists across sessions -- a table's columns, an object's
fields -- is saved with the line of code that produced the value, in a comment
directly above it:

```python
#%click [{"expr": "$['name']"}, {"expr": "$['orders']", "children": [{"expr": "$.total"}]}]
people = [{'name': 'Alice', 'orders': [...]}, ...]
```

The comment binds to the **next non-comment, non-empty line**, so blank lines
and ordinary comments may come between, and inserting either never re-binds
it. Each line has its own; nothing is shared across lines or files (the old
type-keyed `.snc_table_columns.json` / `.snc_object_fields.json` dotfiles are
gone).

The JSON is a **slot list**: a slot is a column (of a table) or a field (of an
object), written as a bare expression or `{"expr": ..., "children": [slot,
...]}`. Columns are assumed homogeneous, so a slot's `children` is the one
config of whatever visualizer its cells get, and a nested config's location is
just the exprs leading down to it (`config_path`). There are no type keys: a
config written for one shape of value applies to whatever the line holds now,
and an expr that no longer fits shows an error cell rather than the config
being silently dropped.

Visualizers never see the source. `python_runner.log_value` parses the
comment for the line, hands the slots to the root visualizer's `init_model`
as `slots_config` (nested visualizers get their slot's `children` the same
way, via `child_nesting_kwargs`), and installs them in
`visualizer_utils.set_line_config`. A save (`save_slots_at_path`) rewrites
that store; afterwards `take_line_config` says whether anything changed, and
if so a `SetConfigComment` command goes out. The editor finds the existing
comment by the same binding rule and replaces it in place, or inserts one
above the line. Replacing rather than inserting keeps a replayed event
harmless. A visualizer that must not save -- an aggregation answer the table
worked out, which is nowhere in the value's shape -- is initialised with
`persist=False`.

The model round-trip is what carries state within a session; the comment is
the cross-session store. A model is stamped with `_config_sig`, a canonical
hash of the slots it reflects, so a comment edited by hand (or swapped in by
a checkout) rebuilds the model from the comment, while the visualizer's own
save -- whose model already reflects the new comment -- does not.

The editor folds each comment's JSON to a `…` token after the `#%click` prefix
(`SNCController.updateConfigCommentFolding`, a decoration); the line the
cursor is on is shown in full so it can be edited.

### Execution Optimization: Checkpointed Worker Pools (No `os.fork()`)

To minimize latency between a keystroke and seeing updated visualizations, SNC uses pre-spawned worker pools:

- **Checkpoint 1 (CP1)**: Pool workers start with visualizers loaded and emit `checkpoint_ready(1)`. CP1 workers run full transform+compile+exec and then exit.
- **Checkpoint 2 (CP2)**: Workers can be warmed with `init_imports`, pre-running the leading imports and emitting `checkpoint_ready(2)`. A CP2 worker compiles the body of whatever run it is handed and executes it against those warmed globals.

Every worker handles exactly one run and exits.

**A warmed worker is matched on the leading imports, not the whole file.** That is all it has executed, so a warmed worker serves any program with the same imports -- which is nearly every keystroke, since editing the body doesn't touch them. `importPrefixOf` (Node) and `_leading_import_stmts` (Python) compute that key on their respective sides; the Node one is a line scanner rather than a parser, so it can disagree on exotic input. That only ever costs a warmed worker: the run message carries the current code, and the worker re-checks with a real AST (`imports_match`). If the imports turn out to differ it executes them itself, degrading to the checkpoint 1 path in place, so a worker can always serve the run it is handed.

The service prefers a ready CP2 worker, falls back to CP1, and otherwise waits for the next worker to become ready. Some consequences worth knowing, each of which was a real source of lag:

- **A run waiting for a worker outranks warming one.** A worker that reaches checkpoint 1 while a run has nothing to run on is handed over immediately rather than being sent off to import; queueing a keystroke behind someone else's `import pandas` is how a run ends up waiting seconds for a worker that was ready.
- **Queued runs are dropped, not served.** A new run supersedes the one in flight (its worker is killed), and equally supersedes any run still waiting for a worker -- their output would be discarded on arrival. Without this a burst of N events costs N worker acquisitions, and the queue itself becomes the latency.
- **CP2 refills as workers are taken**, not only when a run completes. A burst of runs never reaches `end` (each kills the one before it), so waiting for completion lets the pool drain to empty and dumps the whole burst onto CP1. The one exception is the run that invalidated the pool: respawning ten workers about to be killed again is what makes typing out an `import` expensive.

### Visualizer Discovery

Visualizers are loaded from three directories, checked in priority order:

1. `.snc_visualizers/` in the current workspace (project-specific)
2. `~/.snc_visualizers/` in the user's home directory (user-global)
3. `src/vs/platform/snc/node/visualizers/` (built-in)

Any Python file matching `*_visualizer.py` that exports `can_visualize()` and `visualize()` is loaded. The first visualizer whose `can_visualize(value)` returns `True` wins.

## Loops: which iteration a line shows

A line inside a loop runs once per iteration, so "the value of this line" is
really "the value of this line *in some iteration*". Every item carries the
iteration it came from, and a slider on the loop's header line picks which one
the body shows.

**Identity.** An item is identified by `(line, visIndex)`, where `visIndex` is
the *static* index of the log site on that line, assigned by the
`CodeTransformer` (`for a, b in ...` has sites 0 and 1). It does not change
with how many times the line runs, so a visualizer's model and pending events
stay attached to it across iterations and across runs.

**Dynamic context.** The transformer wraps each `for`/`while` as
`_snc_loop_enter(L); try: <loop, with _snc_loop_iter(L) first in its body>
finally: _snc_ctx_exit(L)`, where `L` is the header line, and each function
body (except generators/async, which suspend) as `_snc_call_enter(D); try:
<body> finally: _snc_ctx_exit(D)` -- a function is a loop over its calls, and
its parameters are logged on the `def` line at the top of each call the way a
`for` target is logged on its line, one site per parameter. The
runner keeps a stack of `[id_line, iteration]` frames, and every item carries
its **`path`**: that stack at the moment it was logged, outermost first, e.g.
`[[1, 2], [2, 0]]` for the first inner iteration of the third outer one.
Counts are kept per enclosing path (minus the frames of the thing being
counted), so an inner loop's count is "under this outer iteration", a
function called from a loop is call 0 in each iteration, and a recursive
function's activations are numbered in entry order -- `fact(4)` is
activation 0 and `fact(0)` is 4 -- with a pin matching the *innermost*
activation a value was logged in.

**Selection happens in Python, and a slider move is a rerun.** The editor
sends `loop_selections` (`{header_line: iteration}`) with every run, exactly
as it sends the focused line. `log_value` drops any value whose path
disagrees with a pinned loop before choosing a visualizer, so only the pinned
iteration is rendered or transmitted, and a branch the pinned iteration didn't
take simply has no item. Rendering at the moment of logging is also what makes
this correct for values that are mutated across iterations; recording every
iteration and scrubbing locally would need deep copies. A loop with no pin
renders every iteration, each item replacing the last on the front end, so
the last iteration is what stays on screen. When a loop ends, `_snc_ctx_exit`
emits a **`loop` message** (`{line, path, count}`, only under a selected path)
which sizes the slider; on it, the editor also drops items of an unpinned loop
that came from an iteration other than the last (a branch the last iteration
didn't take), and moves a pin that now points past the end of a shortened
loop. A site logged repeatedly in one run replays its pending events on the
first logging and carries the resulting model through the rest
(`_run_models`), so a command a visualizer emits in response goes out once.

**Front end.** `SNCController.loopSelections` keys each pin by a decoration on
the header line, so edits above the loop don't re-key it. `LoopSliderWidget`
(one per loop/def line that ran at least twice) sits at the end of the header
line ahead of the line's own visualizer, which moves over by its width.

## Network read cache

Because a rerun happens every ~100ms and each one is a fresh process, network I/O could slow things down. `url_cache.py` patches `urllib.request.urlopen` so user code that fetches URLs are served from a `.snc_url_cache` directory next to the file being edited. Editing the line is what forces a refetch.

## The console: program stdin/stdout/stderr

A program that reads stdin can't be handed a live pipe here. The worker's real
stdin is the runner's command channel, and every rerun is a brand-new process
that would have nobody at the other end. So the console works the way
`models_and_events` already works for visualizer state: **the renderer owns the
state, ships it in on every run, and Python replays it.**

The user's typed input is a *document* — `.snc_stdin/<name>.txt` beside the
source file. It is sent as `stdin` on the run message, and `std_streams.py`
replays it through a `sys.stdin` stand-in, so `input()`, `sys.stdin.read()` and
`for line in sys.stdin:` behave as if the session had been typed live, and
behave identically on every rerun. Unlike `.snc_url_cache`, `.snc_stdin` is the
user's own input and is meant to be committed, so it is not gitignored.

That document is opened as an **ordinary editor tab**, and the console
(`vs/workbench/contrib/snc/browser/`) is an editor *contribution* on it rather
than a view of its own — `sourceFileForStdinUri` is what tells a stdin document
apart from any other file. So it is structurally a second Sculpt-n-Code editor:
editable stdin lines, with the program's stdout/stderr in view zones *between*
them, placed by the `stdin_offset` each output chunk carries. Editing any line
reruns the program on the same ~100ms debounce that a source edit uses.

Being a real editor is the point: line numbers, find, undo, multi-cursor and
paste all come for free, and the tab can be split, dragged or moved anywhere the
user would move any other tab — the workbench remembers it. It first opens in
the group beside the source, which is where a console wants to be. The service
holds a model reference so the document stays loaded and keeps driving reruns
whether or not a tab is showing it, and saves it on a short debounce so typing
input never leaves a dirty tab behind.

Two things are worth knowing:

- **A read past the end of the document is not an error.** It raises
  `NeedsInput` (a `BaseException`, so a user's `except Exception:` can't swallow
  it), which unwinds the run cleanly and reports `awaitingInput`. Statements
  after the read simply don't run — exactly what a terminal session that hasn't
  got there yet would show.
- **End of stream is a line in the document,** literally `<EOF>` (Ctrl-D inserts
  it). Only the renderer interprets it: it sends the text above the marker plus
  `stdin_eof: true`. Python's contract stays "here is the text, here is whether
  it ends", and every offset it reports maps 1:1 onto a document position. The
  cost is that a program can't be fed the literal line `<EOF>`.

`print()` keeps its inline visualizer as well as reaching the console: the
widget shows the interactive *value*, the console shows the *text*.
