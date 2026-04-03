// Usage: node click.js '.my-selector'
//    or: node click.js 500 300

import { connect, send, evaluate } from './cdp.js';

const arg1 = process.argv[2];
const arg2 = process.argv[3];

if (!arg1) {
	console.error('Usage: node click.js <css-selector>');
	console.error('       node click.js <x> <y>');
	process.exit(1);
}

async function clickAt(ws, x, y) {
	await send(ws, 'Input.dispatchMouseEvent', {
		type: 'mousePressed', x, y, button: 'left', clickCount: 1,
	});
	await send(ws, 'Input.dispatchMouseEvent', {
		type: 'mouseReleased', x, y, button: 'left', clickCount: 1,
	});
}

async function main() {
	const ws = await connect();

	if (arg2 !== undefined && !isNaN(Number(arg1)) && !isNaN(Number(arg2))) {
		const x = Number(arg1);
		const y = Number(arg2);
		await clickAt(ws, x, y);
		console.log(`Clicked at (${x}, ${y})`);
	} else {
		const selector = arg1;
		const rect = await evaluate(ws, `
			(() => {
				const el = document.querySelector(${JSON.stringify(selector)});
				if (!el) return null;
				const r = el.getBoundingClientRect();
				return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height };
			})()
		`);
		if (!rect) {
			console.error(`Element not found: ${selector}`);
			process.exit(1);
		}
		await clickAt(ws, rect.x, rect.y);
		console.log(`Clicked "${selector}" at (${rect.x}, ${rect.y}) [${rect.w}x${rect.h}]`);
	}
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
