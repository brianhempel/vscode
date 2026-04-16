# VS Code Agents Instructions

This file provides instructions for AI coding agents working with the VS Code codebase.

For detailed project overview, architecture, coding guidelines, and validation steps, see the [Copilot Instructions](.github/copilot-instructions.md).

## Read Project Description First

The description of the project is in `Sculpt-n-Code README.md`. Read this first.

### TDD the Visualizers

When working on a *_visualizer.py file, first write failing tests in *_visulizer_tests.py. Do not TDD the typescript front-end.

### After Finishing a Feature, Have the User Check Interactions

The user should already be running `npm run watch` so any changes you make are already instantly built. Ask the user to verify that changes are working as expected and run `./scripts/code.sh $(pwd) $(pwd)/snc_test.py`, not in the background. That will boot the app in the current folder and open `./snc_test.py` automatically (you can change that file's contents as necessary to test, or open a different file). The user will test the feature and then quit the app and then report to you if the feature worked.

### UI Testing

If asked, try to test the UI yourself with the tool in `ui_testing_tools/`. (They use Chrome Devtools Protocol (CDP)).

Set up `snc_test.py` as desired, then start the app with:

`./scripts/code.sh $(pwd) $(pwd)/snc_test.py --remote-debugging-port=9222`

The tools are in `ui_testing_tools/*.js`:

`node ready.js` - poll until CDP is reachable (up to 10s), then print targets JSON

`node screenshot.js [OUT_PATH.png]` - takes a screenshot (default: `cdp_screenshot.png`)

`node reload.js` - reload the app window, required if typescript or css changes (use this script because naive mechanisms like location.reload do not work)

`node eval.js 'document.title'` - run JS in the renderer, print result as JSON

`node click.js '.my-selector'` - click an element by CSS selector
`node click.js 500 300` - click at x,y coordinates

`node type.js 'hello'` - type text into the focused element
`node type.js --key Enter` - press a special key (Enter, Escape, Tab, ArrowUp/Down/Left/Right, Backspace, Delete, Space)

`node wait_for.js '.my-selector' [timeout_ms]` - wait for a CSS selector to appear (default timeout: 10s)

`node cursor.js 5` - move editor cursor to line 5 (uses Ctrl+G)

`node visible.js '.my-selector'` - check if element is in viewport (exit 0=visible, 2=offscreen, 1=not found)

`node scroll.js '.my-selector'` - scroll element into view
`node scroll.js down [pixels]` - scroll editor down (default 300px)
`node scroll.js up [pixels]` - scroll editor up (default 300px)

`node buffer.js` - print the current editor's text buffer (unsaved content)

`node cdp_send.js Domain.method '{"param":"value"}'` - send arbitrary CDP command (e.g. for mouse move/press/release sequences that click.js can't do, like `node cdp_send.js Input.dispatchMouseEvent '{"type":"mouseMoved","x":100,"y":200}'`)

Visualizers appear below the relevant line of code, so you sometimes have to scroll down to see their buttons. Any buttons above are from a prior line of code.

## Static Visual Testing (only if the user tells you to check by screenshotting)

If the change is visual and does not require mouse clicks or keyboard input to test, the user is not necessary. There is a MCP server for visual inspection called **sculpt-n-code-viewer**. Its **build_and_screenshot_app** tool will rebuild the app, launch it, and take a screenshot. You can give it a **file_path** parameter to open a particular test file to screenshot. Inspect the returned screenshot to see if changes worked.
