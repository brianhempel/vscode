# Agent-driven UI Testing

If asked, try to test the UI yourself with the tool in `ui_testing_tools/`. (They use Chrome Devtools Protocol (CDP)).

The user should already be running `npm run watch-client` so any changes you make are already instantly built (but check the terminals to ensure they are running watch-client).

Set up `snc_test.py` as desired, then start the app with:

`./scripts/code.sh $(pwd) $(pwd)/snc_test.py --remote-debugging-port=9222`

**If you are an agent running inside VS Code**, that launch will die at startup
with `SyntaxError: The requested module 'electron' does not provide an export
named 'Menu'`. The build is fine; the environment is not. The extension host
exports `ELECTRON_RUN_AS_NODE=1`, which the child Electron inherits and which
makes it run `out/main.js` as plain Node. Strip that and its neighbours:

```
env -u ELECTRON_RUN_AS_NODE -u VSCODE_IPC_HOOK -u VSCODE_PID -u VSCODE_CWD \
    -u VSCODE_ESM_ENTRYPOINT -u VSCODE_CODE_CACHE_PATH -u VSCODE_NLS_CONFIG \
    -u VSCODE_CRASH_REPORTER_PROCESS_TYPE -u VSCODE_HANDLES_UNCAUGHT_ERRORS \
    -u VSCODE_L10N_BUNDLE_LOCATION -u VSCODE_CLI -u ELECTRON_NO_ATTACH_CONSOLE \
    ./scripts/code.sh $(pwd) $(pwd)/snc_test.py --remote-debugging-port=9222
```

The tools are in `ui_testing_tools/*.js`:

`node ready.js ['.my_selector']` - poll until CDP is reachable (up to 20s) and (if provided) wait for Python+render to finish and the CSS selector becomes visible, then print targets JSON

`node wait_for_python.js [timeout_ms]` - poll until the Python backend is done and render finishes, returns 1 if not a Python file (default timeout: 10000); most utils below incorporate this wait already, however

`node screenshot.js [OUT_PATH.png]` - wait for Python+render to finish and takes a screenshot (default: `cdp_screenshot.png`)

`node reload.js ['.my_selector']` - reload the app window and wait for Python+render to finish and CSS selector to be visible, required if typescript or css changes (use this script because naive mechanisms like location.reload do not work)

`node eval.js 'document.title'` - run JS in the renderer, print result as JSON

`node dwell.js '.my-selector' [ms]` - wait for Python+render to finish and CSS selector to appear, mouse over it, and wait (default milliseconds: 500)
`node dwell.js 500,300 [ms]` - mouse over x,y coordinates and wait (default milliseconds: 500)

`node click.js '.my-selector'` - wait for Python+render and for CSS selector to appear, then mouse over it, then click it and wait for Python+render to finish
`node click.js 500,300` - mouse over and click at x,y coordinates and wait for Python+render to finish

`node clicks.js '.my-selector' [ms] 500,300 [ms] ...` - perform a series of click and wait operations, default wait is 0 (milliseconds) and can be omitted, it just waits for Python+render to finish; same as running click.js multiple times with waits in between

`node type.js 'hello'` - type text into the focused element, and wait for Python+render to finish
`node type.js --key Enter` - press a key (Enter, Escape, Tab, ArrowUp/Down/Left/Right, Backspace, Delete, Space, Home, End, PageUp/PageDown, F1-F12, or a single character) and wait for Python+render to finish
`node type.js --key cmd+z` - press a chord (cmd/command, ctrl, alt/opt, shift), e.g. `cmd+shift+p` and wait for Python+render to finish

`node wait_for.js '.my-selector' [timeout_ms]` - wait for Python+render and for CSS selector to appear (default timeout: 10000)

`node cursor.js 5` - move editor cursor to line 5 (uses Ctrl+G) and wait for Python+render

`node visible.js '.my-selector'` - check if element is in viewport (exit 0=visible, 2=offscreen, 1=not found)

`node scroll.js '.my-selector'` - scroll element into view
`node scroll.js down [pixels]` - scroll editor down (default 300px)
`node scroll.js up [pixels]` - scroll editor up (default 300px)

`node buffer.js` - print the current editor's text buffer to stdout (including unsaved content)

`node cdp_send.js Domain.method '{"param":"value"}'` - send arbitrary CDP command

Visualizers appear below the relevant line of code, so you sometimes have to scroll down to see their buttons. Any buttons above are from a prior line of code.

Each visualizer carries a `.snc-line-N` class naming the line it belongs to (1-indexed),
so prefix a selector with it when more than one visualizer is on screen:
`.snc-line-7 .col-menu-trigger` is line 7's.

## Gotchas

**A table's columns are saved in a comment above its line.** Column and field
layouts persist in a `#%click {...}` comment that binds to the next non-comment,
non-empty line below it (blank lines and ordinary comments may sit between).
The editor folds the JSON to a `…` token (the whole line shows when the
cursor is on it), so read the buffer rather than the DOM when checking one.
Nothing is
shared across lines or files any more: a fresh `[{'who': 'a', 'n': 3}, ...]`
comes up with its own auto-detected columns unless a `#%click` comment sits
above it. To reset a line's layout, delete its comment and `reload.js`.

**Check which editor you are actually driving.** VS Code restores the previous
session's tabs, so a second `snc_test.py` — `working_examples/snc_test.py`, or
the untitled one described below — can be the focused one, and every reading you
take will be of the wrong file. `buffer.js` is the check. To switch, prefer
`type.js --key cmd+p`, then the name, then `type.js --key Enter`: it resolves by
path, so it can tell the real file from an untitled tab wearing the same name,
and it stays away from the tab-click hazard in the next gotcha.
`click.js '.tabs-container .tab:nth-child(N)'` still works when you know which N
you want.

**Verify the buffer after clicking anything that isn't in the visualizer.**
A synthesized click on a tab has been observed pasting the editor's own URI into
the document — tabs are `draggable`, so a press, a move and a release make a
drag and drop the URI wherever it lands. `click.js` and `clicks.js` never move
between press and release, so they cannot do this; a hand-rolled `cdp_send.js`
sequence can. `buffer.js` again.

**A buffer that disagrees with the file on disk survives restarting.** Unsaved
changes live in `~/Library/Application Support/code-oss-dev/Backups/<hash>/`,
and every launch restores them — so quitting and relaunching is what brings the
disagreement *back*, not what clears it. Revert File
(`type.js --key F1`, then "Revert File") for a tab with a file behind it;
close-and-discard for one without; or delete that Backups folder while the app
is closed, which throws away every unsaved change in the workspace at once.

Those backups are also where the phantom tabs come from. Files you deleted stay
in the tab bar, held open by a backup of their last unsaved state — and one
entry is an *untitled* buffer whose URI ends in `snc_test.py`, which is the
duplicate `snc_test.py` tab. It has no file behind it at all, so it can never
agree with disk and Revert File has nothing to revert to.

**Send shortcuts with `type.js --key`, not by hand.** Cmd+Z, Cmd+P and F1 all
work, but `cdp_send.js Input.dispatchKeyEvent` gets them wrong in three ways
that are all silent — the app simply ignores a chord it has no binding for, and
it reads as "synthetic keys don't work here":

- The modifier bitmask is Alt=1, Ctrl=2, **Meta/Cmd=4**, Shift=8. `modifiers: 2`
  for what you meant as Cmd sends Ctrl.
- A key only INSERTS something if the event carries `text`. Without it the
  editor hears Enter and is handed nothing to write.
- On macOS the editing shortcuts never reach the page as chords: the OS turns
  them into NSResponder commands and CDP goes in below that, so Cmd+Z needs
  `commands: ["undo"]` named explicitly.

`type.js --key` handles all three. It takes chords —
`--key cmd+z`, `--key cmd+shift+p`, `--key ctrl+g` — with `cmd`/`command`,
`ctrl`, `alt`/`opt` and `shift`, and any of the named keys, F1–F12, or a single
character.

**Interacting with a visualizer takes two clicks:** one to focus the visualizer,
then one on the thing you meant to hit. The same again one level down, for a
table cell's nested visualizer. A single click on an unfocused visualizer looks
exactly like a click that missed — nothing opens — so if something isn't
responding, try clicking it twice before you go hunting for a coordinate bug.

**The pointer stays where the last click or dwell left it.** That is deliberate
— a menu held open by hover is still open to read afterwards — but it means the
pointer is usually already on the thing you are about to aim at, and a mouse
that is already there has not *moved* there. Submenus open on `snc-dwell`, which
arms on `mouseover` and ignores the element it is already waiting on, so a
second hover on the same pixel opens nothing at all. `click.js`, `clicks.js` and
`dwell.js` handle it by entering every target from just outside its top edge;
raw `cdp_send.js Input.dispatchMouseEvent` does not, and will silently do
nothing. A dwell needs to rest for `DWELL_MS` (150ms in `snc.ts`) plus the
re-render, which is why `dwell.js` waits 500ms by default.

**Opening a menu is a full Python re-render, not a CSS toggle.** Every event
goes back to the visualizer's update function and the HTML comes back rebuilt,
so expect any DOM you mutated yourself (a marker class, say) to be gone, and
re-measure immediately before acting on a coordinate rather than reusing a rect
you took earlier. The tools wait that re-render out for you; it is only when you
drive the app another way (`eval.js`, `cdp_send.js`) that you have to say
`wait_for_python.js` yourself. Hover reveals (`.snc-hover-hidden`) are the
exception — those are a plain CSS `:hover` rule and apply immediately.

**Quiting the app.** When finished, quit the app with `pkill -f "snc_test.*--remote-debugging-port=9222"`. Do not use simply `pkill -f "remote-debugging-port=9222"` because that will not kill the full app and you will be subsequently confused.
