// Usage: node wait_for.js '.my-selector' [timeout_ms]

import { connect, evaluate } from './cdp.js';

const selector = process.argv[2];
const timeout = Number(process.argv[3]) || 10000;

if (!selector) {
	console.error('Usage: node wait_for.js <css-selector> [timeout_ms]');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const poll = 200;
	const deadline = Date.now() + timeout;

	while (Date.now() < deadline) {
		const found = await evaluate(ws, `!!document.querySelector(${JSON.stringify(selector)})`);
		if (found) {
			console.log(`Found: ${selector}`);
			process.exit(0);
		}
		await new Promise(r => setTimeout(r, poll));
	}

	console.error(`Timed out after ${timeout}ms waiting for: ${selector}`);
	process.exit(1);
}

main().catch(e => { console.error(e.message); process.exit(1); });
