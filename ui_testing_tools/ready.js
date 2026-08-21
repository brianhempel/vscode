// Usage: node ready.js
//    or: node ready.js '.my-selector'
//
// Polls CDP until the app is reachable, then -- if a selector is given -- until
// Python has finished its first run and that selector is actually showing, and
// prints target info. The port opens well before the window has anything in it,
// so waiting on something you expect to see is the difference between "the app
// is up" and "the app is ready".

import { sleep, POLL_MS, measure, waitForPythonReconnecting } from './cdp.js';

const CDP_PORT = process.env.CDP_PORT || 9222;
const selector = process.argv[2];
const timeout = 20000;

async function targets() {
	try {
		return await fetch(`http://localhost:${CDP_PORT}/json`).then(r => r.json());
	} catch {
		return null;
	}
}

async function main() {
	const deadline = Date.now() + timeout;

	while (Date.now() < deadline) {
		const found = await targets();
		if (found?.some(t => t.type === 'page')) {
			// Its own budget, not the rest of this one: a slow start should not
			// leave the window less time to draw in.
			if (selector) {
				await waitForPythonReconnecting(timeout, async (page) => {
					const rect = await measure(page, selector);
					return rect && rect.visible ? rect : null;
				});
			}
			// Re-fetched: waiting for the window to draw can outlast the target
			// list we first saw, and a stale webSocketDebuggerUrl is useless.
			console.log(JSON.stringify(await targets() ?? found, null, 2));
			process.exit(0);
		}
		await sleep(POLL_MS);
	}

	console.error(`CDP not ready after ${timeout}ms on port ${CDP_PORT}`);
	process.exit(1);
}

main().catch(e => { console.error(e.message); process.exit(1); });
