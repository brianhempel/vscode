# Sculpt-n-Code

Sculpt-n-Code (SNC) is a modified version of VS Code that provides **live, inline visualizations of Python runtime values** as you type. When you open a Python file, SNC automatically executes it, captures the values produced by each statement, and renders interactive HTML visualizations directly in the editor next to the line that produced them. Visualizations are interactive and can produce more code. For example, users can select portions of a string by dragging to build regex patterns by demonstration.

## Setup

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

**More details if you have trouble:** [https://github.com/microsoft/vscode/wiki/How-to-Contribute#build-and-run](https://github.com/microsoft/vscode/wiki/How-to-Contribute#build-and-run)

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

## Updating to latest VS Code

Currently rebased on tag `1.130.0`. See `Rebasing Scuplt-n-Code.md` for how to rebase on a newer VS Code.

## Scratch Notes (ignore)

Process spawning/killing: debugpy-main/src/debugpy/launcher/handlers.py debugpy-main/src/debugpy/launcher/debuggee.py

Can overwrite the import handling pretty easily, if we need to hook into that process: [https://docs.python.org/3/reference/import.html](https://docs.python.org/3/reference/import.html) [https://github.com/rohitsanj/import-hook-python/blob/main/import_hook.py](https://github.com/rohitsanj/import-hook-python/blob/main/import_hook.py) [https://docs.python.org/3/library/importlib.htm](https://docs.python.org/3/library/importlib.htm)
