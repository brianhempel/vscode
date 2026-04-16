// Usage: node cdp_send.js Domain.method '{"param": "value"}'
// Example: node cdp_send.js Input.dispatchMouseEvent '{"type":"mouseMoved","x":100,"y":200}'

import { connect, send } from './cdp.js';

const method = process.argv[2];
const paramsJson = process.argv[3] || '{}';

if (!method) {
	console.error('Usage: node cdp_send.js <Domain.method> [paramsJSON]');
	process.exit(1);
}

let params;
try {
	params = JSON.parse(paramsJson);
} catch {
	console.error('Invalid JSON params:', paramsJson);
	process.exit(1);
}

async function main() {
	const ws = await connect();
	const result = await send(ws, method, params);
	if (result !== undefined) {
		console.log(JSON.stringify(result, null, 2));
	}
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
