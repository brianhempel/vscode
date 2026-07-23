# Sculpt-n-Code

Setup:

```
git clone https://github.com/brianhempel/vscode.git
cd vscode
git checkout snc

# Node version: use the version in .nvmrc (currently 24.18.0). e.g. with fnm:
fnm install && fnm use   # or: nvm install && nvm use
npm install # On Windows you have to run this in Visual Studio

# Use your ordinary VS Code extensions
mkdir ~/.vscode-oss-dev
ln -s ~/.vscode/extensions ~/.vscode-oss-dev/extensions
# Windows PowerShell equivalent:
New-Item -ItemType Directory -Path "$HOME\.vscode-oss-dev"
New-Item -ItemType SymbolicLink -Path "$HOME\.vscode-oss-dev\extensions" -Target "$HOME\.vscode\extensions"

# Python stuff
pip install pytest

# Build (first build takes 66sec)
npm run watch # first build, and if you are working on extensions
npm run watch-client # faster

# Launch app. Run in separate terminal from watch-client
./scripts/code.sh
.\scripts\code.bat # Windows
```

After building once, you can edit `~/.vscode-oss-dev/argv.json` to disable crash reporting.

**On Windows:** you must run `npm install` above in Visual Studio.

**More details if you have trouble:** https://github.com/microsoft/vscode/wiki/How-to-Contribute#build-and-run

Front-end code is at: `src/vs/editor/contrib/snc`

If you change the Typescript or the CSS, need to hit Cmd-R in the running application to reload the front-end.

Back-end runner is at: `src/vs/platform/snc`

The Python visualizers are at: `src/vs/platform/snc/common/node/visualizers`

Visualizers use the Elm architecture (albeit a custom implementation in Python). They take in a Python value and a visualizer-specific model state and render HTML which is delivered to the VS Code front-end for display. They may specify events on that HTML which are routed to a visualizer-specific Python update function which updates the model (and thereby the displayed HTML).

User events trigger a full re-run to get back to the appropriate visualizer to run the event through its Elm-like update and visualize functions. To speed this up, Python is preloaded at two checkpoints to avoid paying startup costs. Checkpoint 1 is after the python_runner.py is started up; checkpoint 2 is after just the `import`s on the open file (to avoid re-paying import and source-to-source translation cost). Checkpoint 2 is used if the code didn't change, checkpoint 1 otherwise.

### Python interpreter selection

The pool workers are spawned with whichever interpreter the user has selected via the official Python extension (`ms-python.python`). Re-resolution happens on:

- Controller construction (initial load).
- `onDidChangeModel` (tab switch — interpreter may differ across workspace folders).
- `onDidChangeConfiguration` for `python.defaultInterpreterPath` / `python.pythonPath`.

Status-bar interpreter picks aren't surfaced as a config event, so they're picked up on the next tab switch rather than instantly. If the Python extension isn't installed or the command fails for any reason, SNC falls back to `python3` on PATH.

See `Scuplt-n-Code README 2.md` for more architecture details.

## Committing

Need to use `--no-verify` to avoid automated checks.

```
git add .
git commit --no-verify -m 'message'
git push -f
```

After that, to update on latest VS Code see below. Currently rebased on `1.130.0`.

Note: don't use the old `git reset --hard TAG` + `git cherry-pick origin/snc` recipe. The
snc branch and the current VS Code release branch diverge from a common ancestor that is
*older* than the tag snc is based on, so a plain merge/cherry-pick drags in thousands of
unrelated upstream-vs-upstream conflicts. Instead, apply only the net SNC diff onto the new
tag. SNC touches ~14 upstream files (all tiny edits) plus a bunch of purely additive files.

```
git fetch ms --tags
# OLD_TAG = the tag snc is currently based on (e.g. 1.130.0); NEW_TAG = target tag.
git checkout -B snc-on-NEW_TAG NEW_TAG

# Restore all SNC-added files verbatim (pure additions, no conflicts):
git diff --diff-filter=A --name-only -z OLD_TAG snc | xargs -0 git checkout snc --

# Re-apply the handful of upstream file edits by hand. See:
git diff --diff-filter=M OLD_TAG snc
# Watch for upstream file moves/renames (past moves: gulpfile.vscode*.js -> .ts,
# workbench{,-dev}.html -> src/vs/code/electron-browser/, desktop.main.ts ->
# src/vs/workbench/electron-browser/, editor font defaults editorOptions.ts -> fontInfo.ts).
# If AGENTS.md conflicts with an upstream AGENTS.md, merge both.

git add -A   # (make sure not to stage local scratch files)
git commit --no-verify
```

### Preferred: preserve the individual commits with `rebase --onto`

The net-diff recipe above collapses all of SNC into one commit. To keep the full commit
history, use `git rebase --onto` instead. The merge-base gotcha above does *not* apply here:
`rebase --onto NEW_TAG OLD_TAG` replays only the `OLD_TAG..snc` commits (each as a small patch
relative to `OLD_TAG`), so it never touches the ancient common ancestor and never drags in the
upstream-vs-upstream conflicts.

```
git fetch ms --tags
# OLD_TAG = the tag snc is currently based on; NEW_TAG = target tag.
git worktree add -b snc-on-NEW_TAG ../snc-rebase-wt NEW_TAG   # optional: keep your built tree intact
cd ../snc-rebase-wt
git reset --hard snc
git rebase --onto NEW_TAG OLD_TAG
```

Only the ~14 upstream-file commits conflict; the additive-file commits apply cleanly. Resolve
each conflict keeping the upstream (NEW_TAG) side and re-applying the small SNC edit, minding
the file moves/renames listed above (git rename-detection follows most of them automatically,
but not gulpfile.vscode.js -> .ts, and it can mis-route workbench-dev.html onto a copilot test
fixture — redirect that edit to `src/vs/code/electron-browser/workbench/workbench-dev.html`).
`git config rerere.enabled true` helps with the repeated AGENTS.md conflict.

Then build (`npm i` with the .nvmrc node version, `npm run watch-client`) and fix any
compile errors from API drift in `snc.ts` / `sncProcessService.ts` / `pythonDropProvider.ts`.

If everything still works, fast-forward the `snc` branch and push:

```
git branch -f snc snc-on-NEW_TAG
git push -f
```

## Scratch Notes (ignore)

Process spawning/killing: debugpy-main/src/debugpy/launcher/handlers.py debugpy-main/src/debugpy/launcher/debuggee.py

Can overwrite the import handling pretty easily, if we need to hook into that process: https://docs.python.org/3/reference/import.html https://github.com/rohitsanj/import-hook-python/blob/main/import_hook.py https://docs.python.org/3/library/importlib.htm
