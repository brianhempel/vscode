// Usage: node reload.js
//    or: node reload.js '.my-selector'
//
// Reloads and waits for the window that comes back: for Python to have finished
// its first run and put the visualizers on screen, and -- if a selector is
// given -- for that selector to be showing.

import { connect, evaluate, measure, waitReconnecting, pythonStatus, pythonReady } from './cdp.js';

const selector = process.argv[2];

// What Cmd+R runs. Sending the `vscode:reloadWindow` IPC message directly --
// which this script used to do -- skips the workbench's shutdown sequence, and
// the editor comes back with the file's contents appended to what was already
// in the buffer. One more copy per reload, with the tab still reading as clean
// and the file on disk never changing, so it looks like the buffer was
// corrupted by something else entirely. Go through the command.
const RELOAD = `(globalThis._sncEditor._commandService`
	+ `.executeCommand('workbench.action.reloadWindow'), 'sent')`;

// The old page keeps answering for a moment after being told to go, and it has
// a finished run and a full DOM to report -- so every wait here would be over
// before the reload had begun. A global is the marker to use: unlike a class on
// an element, or the run counter, nothing but a navigation can clear it, and a
// navigation always does.
const STAMP = '__sncReloadStamp';

async function main() {
	const ws = await connect();
	if (await evaluate(ws, 'globalThis._sncEditor === undefined')) {
		throw new Error('No _sncEditor to reload through. Open a Python file, '
			+ 'or reload by hand with `node type.js --key cmd+r`.');
	}
	await evaluate(ws, `window.${STAMP} = true`);
	await evaluate(ws, RELOAD);

	await waitReconnecting(async (page) => {
		if (await evaluate(page, `window.${STAMP} === true`)) {
			return null;
		}
		if (!pythonReady(await pythonStatus(page))) {
			return null;
		}
		if (!selector) {
			return 'reloaded';
		}
		const rect = await measure(page, selector);
		return rect && rect.visible ? rect : null;
	}, selector ? `the reloaded window to show ${selector}` : 'the reloaded window');

	console.log(selector ? `Reloaded, ${selector} is showing` : 'Reloaded');
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
