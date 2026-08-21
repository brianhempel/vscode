// Usage: node click.js '.my-selector'
//    or: node click.js 500,300
//
// Waits for Python before looking for a selector and again after clicking, so
// what it hits is what is on screen and what it leaves behind is finished. See
// hoverTarget and clickTarget in pointer.js.

import { connect } from './cdp.js';
import { parseTarget, clickTarget } from './pointer.js';

const arg = process.argv[2];

if (!arg) {
	console.error('Usage: node click.js <css-selector>');
	console.error('       node click.js <x>,<y>');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const target = parseTarget(arg);
	const at = await clickTarget(ws, target);
	console.log(`Clicked ${target.selector === undefined ? 'at' : target.label + ' at'} ${at.where}`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
