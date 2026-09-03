# Study Logging

Sculpt-n-Code records how a participant uses the system to JSON-lines files so the study can be analyzed afterward. Logging is **on by default** (`clickacode.studyLogging.enabled`); nothing is uploaded — files only ever land on the participant's disk.

## Where the logs are

One file per app launch, shared by every window of that launch:

```
<user data dir>/snc-study-logs/<sessionId>.jsonl
```

`<user data dir>` is the Electron user-data path (dev builds: `~/.vscode-oss-dev/`, or `~/Library/Application Support/<product>/` on macOS for packaged builds). `sessionId` looks like `20260826T153012-1a2b3c4d` (launch time in UTC + random tail). Command Palette: **Clickacode: Reveal Study Log Folder** opens the current file in Finder/Explorer.

Settings (all application-scoped):

| Setting | Default | Meaning |
|---|---|---|
| `clickacode.studyLogging.enabled` | `true` | Master switch. Turning it off writes one last `settings.loggingDisabled` record. |
| `clickacode.studyLogging.directory` | `""` | Absolute folder to write to instead of the default. |
| `clickacode.studyLogging.logFullHtml` | `false` | Put the full HTML + model of every rendered visualizer into each `run.end` (very large). Off records type and length only. |
| `clickacode.studyLogging.snapshotIntervalSeconds` | `60` | How often a changed file's full text is snapshotted. |

## How it works

- `src/vs/platform/snc/common/sncStudyLog.ts` — the `studyLog.log(type, payload, file?)` sink product code calls (never throws; buffers until the service exists), `StudyLogCoalescer`, and the IPC interface.
- `src/vs/workbench/contrib/snc/browser/sncStudyLog.contribution.ts` — renderer service: buffers events, flushes to the main process every 1 s (or at 500 buffered events) and on shutdown via `onWillShutdown.join`; also all editor/model/workbench instrumentation, settings, and the reveal command.
- `src/vs/platform/snc/electron-main/sncStudyLogWriter.ts` — main-process writer (channel `sncStudyLog`): mints the session id, `mkdir -p`, serialized `appendFile`.
- `src/vs/editor/contrib/snc/browser/snc.ts` — visualizer widget and Python-run instrumentation.

Events are buffered in memory for up to ~1 s, so a hard crash can lose the last second.

## Record shape

Every line is one JSON object:

```json
{"t":"2026-08-26T15:30:12.345Z","ms":1234.56,"seq":42,"session":"20260826T153012-1a2b3c4d","window":1,"type":"widget.mouse","file":"file:///Users/p1/task.py","payload":{...}}
```

| Field | Meaning |
|---|---|
| `t` | Wall clock, ISO 8601 UTC. |
| `ms` | `performance.now()` of the window — monotonic; use for durations. Restarts at 0 per window (and per Cmd-R reload). |
| `seq` | Per-window counter. Gaps mean dropped records (also counted in `app.shutdown.dropped`). |
| `session` | App-launch id (= file basename). |
| `window` | VS Code window id; distinguishes windows sharing a session. |
| `type` | Event type, below. |
| `file` | URI the event concerns, when there is one. |
| `payload` | Type-specific. |

## Event catalog

### App / session
| type | payload |
|---|---|
| `session.start` | `version`, `commit` (from `product.json`; unset in a from-source build), `repo` (what git says about the checkout the app runs from: `root`, `head`, `branch`, `describe`, `dirty`, `dirtyFiles`, `dirtyPaths` (first 40), `diffSha1` (sha1 of `git diff HEAD`, so two sessions on the same uncommitted edits hash alike; absent when clean), or `error` when git could not answer), `quality`, `os`, `osFamily`, `userAgent`, `screen`, `timezoneOffsetMinutes`, `settings` (all `snc.*` values), `startedAt` (main process start). |
| `settings.changed` | `snc` (new values of all `snc.*`), `source`. |
| `settings.loggingEnabled` / `settings.loggingDisabled` | — |
| `app.focus` / `app.blur` | Window focus. |
| `app.shutdown` | `reason`, `counts` (records per type this window), `dropped`. |
| `command.revealStudyLogFolder` | — |
| `log.internalError` | `where`, `error` — the logger's own failures. |

### Editor / files
Only Python files, untitled buffers and SNC stdin documents (`*.snc*`) get file events; settings/output panes do not.

| type | payload |
|---|---|
| `file.open` / `file.close` | `language`, `lineCount`, `length`. |
| `file.snapshot` | `reason` (`open`/`close`/`save`/`periodic`/`changes`), `versionId`, `lineCount`, `text` (full file). Periodic = every `snapshotIntervalSeconds` if changed; `changes` = after 200 content changes. |
| `file.userEdit` | `versionId`, `isUndoing`, `isRedoing`, `isFlush`, `changes: [{range:[sl,sc,el,ec], rangeLength, text:{text,length,truncated}}]` — the `IModelContentChangedEvent` deltas; `text` truncated at 4000 chars (snapshots recover the rest). |
| `file.sncEdit` | Same, plus `origin`: `NewCode`, `InsertNewVar`, `ChangeSelectedText`, `ChangeSourceExpr`, `SetConfigComment`. Any edit made through `pushEditOperations` inside SNC is bracketed with `studyLog.withEditOrigin`; everything else is `userEdit` (including edits by other extensions/format-on-save). |
| `editor.undo` / `editor.redo` | `versionId` (emitted alongside the edit record). |
| `file.save` | `reason`, `source`; followed by a `file.snapshot` (`save`). |
| `file.languageChanged` | `from`, `to`. |
| `editor.created` / `editor.disposed` / `editor.modelChanged` | `editorId`, `file`, `language`, `from`/`to`. |
| `editor.activeChanged` | Active editor name/type, `visible` URIs. |
| `editor.closed` | Tab closed. |
| `editor.focus` / `editor.blur` | Text focus; `blur` includes `activeElement` (e.g. `div.snc-visualization-widget...` when focus went into a visualizer). |
| `editor.cursor` | **Coalesced**: `selection`, `position`, `empty`, `source`, `reason`, `coalesced` (records suppressed since last). Logged when the cursor line or selection-emptiness changes, else at most every 300 ms, plus a trailing record 300 ms after the last move. |
| `editor.scroll` | **Coalesced** (500 ms, same rule): `scrollTop`, `scrollLeft`, `visibleRanges`. |
| `editor.fileDrop` | A file or URL was shift-dropped into the editor as a read: `sources` (`{type, path}` for files with `type` one of `text`/`csv`/`json`/`excel`, or `{type: 'url', url}`), `lines` (the assignments inserted), `imports`, `position`. (The edit follows as `file.userEdit`, like `editor.pyExpDrop`.) |
| `editor.pyExpDrop` | A py-exp dragged from a visualizer was dropped into the editor: `expr`, `imports`, `position`. (The edit itself follows as `file.userEdit` — the drop provider's edit is applied by the editor, not SNC.) |

### Visualizer widgets
`line`/`visIndex` identify the widget; `visType` (e.g. `string-visualizer`, `list-visualizer`) is read from the rendered HTML's container class; `focused` says whether that line was the focused (full-size) one. `target` describes the DOM element hit: `tag`, `classes`, `text`, `depth`, `attrs` (`data-action-expr`, `snc-py-exps`, `snc-mouse*`, `snc-idx*`, ...), plus the nearest ancestor `actionExpr`/`pyExps`.

| type | payload |
|---|---|
| `widget.mousedown` | Raw DOM mousedown on any widget, before any routing: `button`, `detail`, `x`,`y`, modifiers, `target`. Action-button clicks show up here via `target.attrs['data-action-expr']`/`actionExpr`; the code they produce follows as `snc.command` + `file.sncEdit`. |
| `widget.mouse` | A mousedown/mouseup actually sent to Python: `pythonEventStr` (e.g. `MouseDown(5)`, wrapped with child keys), `event` (the JSON Python gets: `offsetY`, `elementHeight`, modifiers, ...). |
| `widget.mouseMove` | **Coalesced** mousemove/mouseout sent to Python: new record whenever `(line, visIndex, pythonEventStr)` changes, otherwise at most every 250 ms; `coalesced` = suppressed count; trailing record after 250 ms of stillness. Flushed before any `widget.mouse`. Moves over non-focused (small) widgets never reach Python and are not logged. A mouseout/mouseleave also carries `to` (the element the pointer went to): its `offsetY` is measured against the element being left, so it reads as nonsense without that. |
| `widget.emptyEventStr` | A pointer event resolved to an empty Python event string. Should never occur (the dispatchers skip these); if it does, it is a bug -- the event was dropped rather than sent as a no-op run. `event`, `target`. |
| `widget.key` | `pythonEventStr`, `keyString` (normalized, e.g. `cmd shift z`), `handled` (widget intercepted it), `event`. |
| `widget.input` | `pythonEventStr`, `value` (full input text). |
| `widget.drop` | py-exp dropped into a widget input: `text`, `insertAt`, `previousValue`. |
| `widget.dragStart` | Drag of a py-exp began: `expr`, `imports`, `alternatives`. |
| `widget.copyExpr` | Copy button in a tooltip: `expr`. |
| `widget.insertNewVar` | `+` button: `line`, `expression`, `imports` (edit follows as `file.sncEdit` origin `InsertNewVar`). |
| `widget.tooltip` | `kind` (`pyExp`/`action`), `exprs`. |
| `widget.hoverMenu` | Dropdown hover menu shown: `trigger`, `items` text. |
| `widget.chainClick` | Chain icon clicked: `state` before the click. |
| `snc.chainClick` | Controller side of the same click: `wasLinked`, `linkedRange`. |
| `widget.expand` | Click on a small (unfocused) widget pinned focus to `line`. |
| `widget.loopSlider` | `line`, `iteration`, `max`, `dragging`. One record per `input` event (sliders are already stepwise; not coalesced). |

### Python runs
| type | payload |
|---|---|
| `run.start` | `runId`, `trigger`, `cancelledPrevious` (runId superseded), `contentLength`/`contentLines`, `focusedLine`, `loopSelections`, `event` (the UI event this run carries, if any), `queuedEvents`, `modelsSent`. |
| `run.end` | `runId`, `trigger`, `durationMs` (wall, start→end message), `toFirstItemMs`, `toFirstRenderMs`, `exitCode`, `syntaxError`, `awaitingInput`, `stderr`, `backendTiming` (spawn timing from the pool), `loopCounts`, `itemCount`, `items: [{line, visIndex, executionStep, path, visType, htmlLength, hasModel, html?, model?}]` (html/model only with `logFullHtml`). |
| `run.error` | `runId`, `trigger`, `durationMs`, `error`. |
| `run.warning` | `runId`, `warning`. |
| `run.cancelled` | `runId`, `by` (`superseded:<trigger of the new run>`, `overtaken:<trigger>`, or `cancelCurrentRun`), `elapsedMs`. |
| `run.item` | A widget's item arrived and did something worth noting: `line`, `visIndex`, `step`, `handledEventIds` (queued events this item applied, now retired), `commands` (types of the commands it carried), `stillQueued` (events it declined, to be retried), `dropped` (`declined-twice` when this was already the retry and they were thrown away). Plain items -- neither events nor commands -- are not logged one by one; `run.end`'s `itemCount`/`items` has them. |
| `vis.update` | One call of a visualizer's `update`, as the runner reports it on the item: `runId`, `line`, `visIndex`, `step`, `event` (`id`, `type`, `pythonEventStr`), `modelBefore`, `modelAfter` (JSON snapshots, so an in-place mutation still shows both), `commands` (type names returned), `notes` (what the handling code said about itself, below), `error` (`ExcName: message` when `update` raised; `modelAfter` and `commands` are then absent, and the item's html is the runner's error box). Logged before that item's `run.item`; several per item when a run replayed several queued events. A nested visualizer's update is inside its parent's, not a record of its own. A model JSON can't encode shows as `{_unserializable}`. |
| `run.eventsDropped` | The end-of-run sweep threw queued events away: `reason` (`widget-not-reached`: the run ended without ever reaching the widget, so it is not part of this execution), `widgets: [{line, visIndex, events}]`. |
| `run.startFailed` | IPC call to start failed: `error`. |
| `snc.command` | A command Python sent back: `runId`, `trigger`, `command` (full `SNCCommand`: `NewCode` edits + imports, `ChangeSelectedText`, `ChangeSourceExpr`, `SetConfigComment`, `CopyToClipboard`). The model edit it causes is the next `file.sncEdit`. |

`trigger` values: `initial`, `edit`, `cursor-line`, `expand`, `stdin`, `loop-slider`, `editor-visible`, `widget:mousedown` / `widget:mouseup` / `widget:mousemove` / `widget:mouseout` / `widget:keydown` / `widget:input`, `queued-events` (a retry for events a run declined), `scheduled`.

#### `vis.update` notes

Every branch of every visualizer's `update` calls `study_note(**info)` (from `visualizer_utils`) to say what it did; the runner attaches the merged dict to that update's record as `notes`. The event alone says `MouseMove`; the notes say `select.drag` of a `fuzzy` segment.

Fixed keys:

| key | meaning |
|---|---|
| `vis` | Which visualizer handled it: `string`, `table`, `object`, `tuple`. A nested visualizer overwrites its parent's. |
| `action` | `area.verb`, lowercase, hyphenated: `select.start`, `column.remove`, `code.sort`, `tally.toggle`, `key.ignored`, ... The most specific branch reached wins (a `ColumnKeyDown` starts as `key.ignored` and becomes `column.add` if Enter commits a name). |
| `childPath` | Child keys the event was routed through, outermost first, when it went to a nested visualizer. The parent notes `child.route` (or `child.focus` / `child.dropped` for an unfocused child) and the child's own update overwrites `action`. |

Areas: `select`, `handle`, `hover`, `mouse` (string selections); `dropdown`, `segment`, `flag`, `search`, `replace`, `expand`, `tool`, `pick`, `history` (string chrome); `column`, `subcol`, `compute`, `sort`, `tally`, `menu`, `rows` (table); `field` (object); `link` (`set-action`, `unlink`, `relink`), `code` (a line written: `action`, `fetch`, `sort`, `group-by`, `row-action`, `compute`, `join`), `copy`, `key`, `child`.

The rest is per-action metadata, named after what it is: `column`, `segment`, `field`, `type` (selection type), `at` (string index), `to`/`from`, `on` (a toggle's new state), `wrote` (whether code was actually produced), `codeAction` (the action name a `code.*` / `link.set-action` used), `key`. Two keys are set by the shared helpers rather than by a branch: `linkedUpdate` (the linked line was rewritten, value = the linked action) and `autoLink` (a first interaction inserted and linked a line), plus `outcome`/`linked` on `link.relink` and `derivedColumn` when a cell's code became a table column.

## Analysis

```python
import json, pandas as pd, glob

rows = []
for path in glob.glob("~/.vscode-oss-dev/snc-study-logs/*.jsonl".replace("~", __import__("os").path.expanduser("~"))):
    with open(path) as f:
        rows += [json.loads(line) for line in f if line.strip()]
df = pd.json_normalize(rows)          # payload.* become columns
df["t"] = pd.to_datetime(df["t"])
df = df.sort_values(["session", "window", "seq"])

print(df["type"].value_counts())
runs = df[df.type == "run.end"]
print(runs["payload.trigger"].value_counts(), runs["payload.durationMs"].describe())

# Reconstruct a file at any point: take the last file.snapshot before it and
# replay file.userEdit / file.sncEdit changes (ranges are 1-based [sl, sc, el, ec]).
```

Reconstructing text from deltas: apply each change's `range` → `text` in the order given within one record (VS Code guarantees they don't overlap and are ordered by position; apply from last to first). Truncated `text` (`truncated: true`) can be recovered from the next snapshot.

## Privacy / volume notes

- The log contains the full text of every Python file the participant opens in SNC, everything they type into visualizer inputs, and clipboard copies from visualizers. Nothing else from the clipboard.
- Typical volume: a few hundred KB per hour without `logFullHtml`; mouse moves are the largest stream and are capped by the coalescing above.
- Mouse moves that stay on one target for a long time produce one record per 250 ms; each carries `coalesced` so the true count is recoverable.
