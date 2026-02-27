## Read Project Description First

The description of the project is in `Sculpt-n-Code README.md`. Read this first.

### TDD the Visualizers

When working on a *_visualizer.py file, first write failing tests in *_visulizer_tests.py. Do not TDD the typescript front-end.

### After Finishing a Feature, Have the User Check Interactions

The user should already be running `npm run watch` so any changes you make are already instantly built. Ask the user to verify that changes are working as expected and run `./scripts/code.sh $(pwd) $(pwd)/snc_test.py`, not in the background. That will boot the app in the current folder and open `./snc_test.py` automatically (you can change that file's contents as necessary to test, or open a different file). The user will test the feature and then quit the app and then report to you if the feature worked.

## Static Visual Testing (only if the user tells you to check by screenshotting)

If the change is visual and does not require mouse clicks or keyboard input to test, the user is not necessary. There is a MCP server for visual inspection called **sculpt-n-code-viewer**. Its **build_and_screenshot_app** tool will rebuild the app, launch it, and take a screenshot. You can give it a **file_path** parameter to open a particular test file to screenshot. Inspect the returned screenshot to see if changes worked.

## Cursor Cloud specific instructions

### Prerequisites

- **Node.js 20.19.0** (specified in `.nvmrc`). Use `nvm use` in the workspace root.
- **Python 3** must be on `PATH` for the Sculpt-n-Code visualizers. The SNC backend spawns `python` (not `python3`), so `python` must resolve to Python 3 (e.g. `sudo ln -s /usr/bin/python3 /usr/bin/python`).
- **System package `libkrb5-dev`** is required for native `kerberos` module compilation during `npm install`.

### Key commands

| Task | Command |
|---|---|
| Install deps | `npm install` |
| Compile (one-shot) | `npm run compile` |
| Watch (dev) | `npm run watch` (or `npm run watch-client` for client only) |
| Lint | `npm run eslint` |
| Node unit tests | `npm run test-node` |
| Python visualizer tests | `python3 src/vs/platform/snc/node/visualizers/<name>_tests.py` (run each file individually) |
| Launch app | `./scripts/code.sh $(pwd) $(pwd)/snc_test.py` |

### Launching Code-OSS in the Cloud VM

The Electron app requires a real X11 display with GPU/DRI3 support. **Xvfb alone is insufficient** — the GPU process crashes with `"GPU process isn't usable. Goodbye."` because Xvfb lacks DRI3.

Use **display `:1`** (the XFCE desktop provided by the VM) instead of Xvfb:

```bash
export DISPLAY=:1
eval $(dbus-launch --sh-syntax)
./scripts/code.sh $(pwd) $(pwd)/snc_test.py
```

The app detects `/.dockerenv` and automatically adds `--disable-dev-shm-usage`.

### Pre-existing lint warnings

`npm run eslint` exits non-zero due to 22 pre-existing warnings in `src/vs/editor/contrib/snc/browser/snc.ts` (missing semicolons, `==` vs `===`). These are not regressions.
