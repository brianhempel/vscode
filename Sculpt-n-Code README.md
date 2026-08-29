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
pip install "pandas<3" "numpy<2"

# If you want to write Python that downloads URLs, you'll need SSL certs
/Applications/Python\ 3.14/Install\ Certificates.command

# Build, may have to run `npm run watch` the first time to build extensions
npm run snc # runs `npm run watch-snc` in a restart loop. agent edits occasionally crash npm run watch-snc

# In a separate terminal, launch app.
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

User events trigger a re-run to get back to the appropriate visualizer to run the event through its Elm-like update and visualize functions. To speed this up, Python is preloaded at three checkpoints to avoid paying startup costs. Checkpoint 1 is after the python_runner.py is started up; checkpoint 2 is after just the `import`s on the open file (to avoid re-paying import cost). Checkpoint 2 is used when the open file's leading `import`s are unchanged -- which is nearly always, since editing the body doesn't touch them -- and checkpoint 1 otherwise.

Checkpoint 3 goes further: the worker runs the program up to the visualizer the user last interacted with and *stops there*, holding all its live state. An event then costs only that visualizer's update/visualize plus the tail of the program -- everything above it (reading the CSV, fitting the model) is already done. It is only usable while nothing that changes what the prefix does has changed: the code, the focused line, the loop pins, the console document. So dragging on a visualizer is fast, and the first edit after it falls back to checkpoint 2. Note that a warm worker holds the visualizer modules it loaded, so editing a `*_visualizer.py` needs a touch to the Python file (type and delete a space) to take effect.

An event doesn't always need a re-run of its own. A run that hasn't yet reached the widget the event is for is still able to answer it, so the event is handed to that run instead and it renders with everything the user has done up to the moment it gets there. This is what keeps a gesture (a drag, a hover) to roughly one run per trip through the program rather than one run per event.

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
