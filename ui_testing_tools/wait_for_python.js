// Usage: node wait_for_python.js [timeout_ms]
//
// Waits until the Python backend has nothing left to do and what it produced is
// on screen. Most of the other tools do this for you -- see `waitForPython` in
// cdp.js and who calls it -- so reach for this one when you have driven the app
// some other way (eval.js, cdp_send.js) and want to read the result.
//
// Exits 1 when the focused file is not Python: no run will ever happen, so a
// wait would only burn the timeout. The shared helper treats that as nothing to
// wait for, which is what the other tools want; only here is it worth saying.

import { waitForPythonReconnecting } from './cdp.js';

const timeout = Number(process.argv[2]) || 10000;

async function main() {
	const status = await waitForPythonReconnecting(timeout);
	if (!status.python) {
		console.error('Not a Python file; nothing to wait for.');
		process.exit(1);
	}
	console.log(`Python done (${status.runsSettled} run${status.runsSettled === 1 ? '' : 's'})`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
