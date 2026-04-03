// Usage: node eval.js 'document.title'

import { connect, evaluate } from './cdp.js';

const expression = process.argv[2];
if (!expression) {
	console.error('Usage: node eval.js <javascript-expression>');
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const value = await evaluate(ws, expression);
	console.log(JSON.stringify(value, null, 2));
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
