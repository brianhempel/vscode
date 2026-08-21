// Usage: node dwell.js '.my-selector' [ms]
//    or: node dwell.js 500,300 [ms]
//
// Hovers without clicking, and stays there. For the menus that open on dwell,
// and for revealing `.snc-hover-hidden` furniture so a screenshot shows it.
//
// A selector is waited for the usual way, Python first (see hoverTarget in
// pointer.js). What happens after the hover is the point here, so that is left
// to the dwell: it is timed rather than waited out, because a hover that opens
// nothing has no render to wait for and would sit there until the timeout.

import { connect, sleep } from './cdp.js';
import { parseTarget, hoverTarget } from './pointer.js';

const arg = process.argv[2];
const ms = process.argv[3] === undefined ? 500 : Number(process.argv[3]);

if (!arg || Number.isNaN(ms)) {
	console.error('Usage: node dwell.js <css-selector> [ms]');
	console.error('       node dwell.js <x>,<y> [ms]');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const target = parseTarget(arg);
	const at = await hoverTarget(ws, target);
	await sleep(ms);
	console.log(`Dwelt ${ms}ms ${target.selector === undefined ? 'at' : target.label + ' at'} ${at.where}`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
