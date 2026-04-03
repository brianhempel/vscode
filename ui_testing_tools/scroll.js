// Usage: node scroll.js '.my-selector'          -- scroll element into view
//    or: node scroll.js down [pixels]            -- scroll the editor down (default 300px)
//    or: node scroll.js up [pixels]              -- scroll the editor up (default 300px)
// Requires the SNC controller's _sncEditor global (set in snc.ts).

import { connect, evaluate } from './cdp.js';

const arg1 = process.argv[2];
const arg2 = process.argv[3];

if (!arg1) {
	console.error('Usage: node scroll.js <css-selector>');
	console.error('       node scroll.js down|up [pixels]');
	process.exit(1);
}

async function main() {
	const ws = await connect();

	if (arg1 === 'down' || arg1 === 'up') {
		const px = Number(arg2) || 300;
		const delta = arg1 === 'down' ? px : -px;
		const result = await evaluate(ws, `
			(() => {
				const editor = globalThis._sncEditor;
				if (!editor) return 'no editor';
				const current = editor.getScrollTop();
				editor.setScrollTop(current + (${delta}));
				return { before: current, after: editor.getScrollTop() };
			})()
		`);
		if (result === 'no editor') {
			console.error('No editor found (_sncEditor not set)');
			process.exit(1);
		}
		console.log(`Scrolled ${arg1} ${px}px (scrollTop: ${result.before} -> ${result.after})`);
	} else {
		const selector = arg1;
		const result = await evaluate(ws, `
			(() => {
				const el = document.querySelector(${JSON.stringify(selector)});
				if (!el) return 'not found';
				el.scrollIntoView({ behavior: 'instant', block: 'center' });
				const r = el.getBoundingClientRect();
				return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
			})()
		`);
		if (result === 'not found') {
			console.error(`Element not found: ${selector}`);
			process.exit(1);
		}
		console.log(`Scrolled "${selector}" into view at (${result.x}, ${result.y}) [${result.w}x${result.h}]`);
	}
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
