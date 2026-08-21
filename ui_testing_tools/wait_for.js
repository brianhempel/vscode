// Usage: node wait_for.js '.my-selector' [timeout_ms]
//
// Waits for Python to finish, then for the element to be in the DOM. Not the
// same as waiting for it to be showing -- see `measure` in cdp.js -- which is
// what ready.js and reload.js do.

import { connect, waitFor, waitForPython } from './cdp.js';

const selector = process.argv[2];
const timeout = Number(process.argv[3]) || 10000;

if (!selector) {
	console.error('Usage: node wait_for.js <css-selector> [timeout_ms]');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	// Its own budget, not a share of one: a slow run should not leave the
	// element less time to appear in.
	await waitForPython(ws, timeout);
	await waitFor(ws, selector, { timeout });
	console.log(`Found: ${selector}`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
