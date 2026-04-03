// Usage: node visible.js '.my-selector'
// Checks if an element is in the viewport. Prints its bounding rect and visibility status.

import { connect, evaluate } from './cdp.js';

const selector = process.argv[2];
if (!selector) {
	console.error('Usage: node visible.js <css-selector>');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const info = await evaluate(ws, `
		(() => {
			const el = document.querySelector(${JSON.stringify(selector)});
			if (!el) return { found: false };
			const r = el.getBoundingClientRect();
			const vw = window.innerWidth;
			const vh = window.innerHeight;
			const inViewport = r.top < vh && r.bottom > 0 && r.left < vw && r.right > 0;
			return {
				found: true,
				inViewport,
				rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
				viewport: { w: vw, h: vh },
			};
		})()
	`);
	if (!info.found) {
		console.error(`Element not found: ${selector}`);
		process.exit(1);
	}
	console.log(JSON.stringify(info, null, 2));
	process.exit(info.inViewport ? 0 : 2);
}

main().catch(e => { console.error(e.message); process.exit(1); });
