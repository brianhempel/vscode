// Usage: node clicks.js '.my-selector' [ms] 500,300 [ms] ...
//
// The same as running click.js several times, in one connection. Every click
// already waits for its own Python re-render to finish and be on screen, so a
// target needs no wait after it; give one only to hold still longer than that,
// for something the status cannot speak for (an animation, a hover menu you
// want to see settle). Interacting with a visualizer takes two clicks, one to
// focus and one to hit, which is what makes this the normal way to drive it.
//
//   node clicks.js '.list-visualizer' '.col-menu-chevron' '.menu-item-sort'

import { connect, sleep } from './cdp.js';
import { parseTarget, clickTarget } from './pointer.js';

const DEFAULT_WAIT_MS = 0;

const args = process.argv.slice(2);

if (args.length === 0) {
	console.error('Usage: node clicks.js <target> [ms] <target> [ms] ...');
	console.error('       where a target is a css-selector or <x>,<y>');
	process.exit(1);
}

// A bare number is how long to wait after the click before it; `500,300` is a
// place to click. Nothing else can be read two ways -- no CSS selector is just
// a number.
const steps = [];
for (const arg of args) {
	if (/^\s*\d+\s*$/.test(arg)) {
		if (steps.length === 0) {
			console.error(`Wait with nothing to wait after: ${arg}`);
			process.exit(1);
		}
		steps[steps.length - 1].wait = Number(arg);
	} else {
		steps.push({ target: parseTarget(arg), wait: DEFAULT_WAIT_MS });
	}
}

async function main() {
	const ws = await connect();
	for (const [i, { target, wait }] of steps.entries()) {
		let at;
		try {
			at = await clickTarget(ws, target);
		} catch (e) {
			// Which one failed matters: the earlier clicks have already landed
			// and the app is not where it started.
			throw new Error(`Step ${i + 1} of ${steps.length}, ${target.label}: ${e.message}`);
		}
		const held = wait > 0 ? `, waited a further ${wait}ms` : '';
		console.log(`Clicked ${target.selector === undefined ? 'at' : target.label + ' at'} ${at.where}${held}`);
		await sleep(wait);
	}
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
