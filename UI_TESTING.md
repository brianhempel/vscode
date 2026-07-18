# Agent-driven UI Testing

If asked, try to test the UI yourself with the tool in `ui_testing_tools/`. (They use Chrome Devtools Protocol (CDP)).

The user should already be running `npm run watch-client` so any changes you make are already instantly built (but check the terminals to ensure they are running watch-client).

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

`node buffer.js` - print the current editor's text buffer to stdout (including unsaved content)

`node cdp_send.js Domain.method '{"param":"value"}'` - send arbitrary CDP command (e.g. for mouse move/press/release sequences that click.js can't do, like `node cdp_send.js Input.dispatchMouseEvent '{"type":"mouseMoved","x":100,"y":200}'`)

Visualizers appear below the relevant line of code, so you sometimes have to scroll down to see their buttons. Any buttons above are from a prior line of code.

When finished, quit the app with `pkill -f "snc_test.*--remote-debugging-port=9222"`.
