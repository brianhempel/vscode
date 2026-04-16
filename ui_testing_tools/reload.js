// Usage: node reload.js

import { connect, evaluate } from './cdp.js';

async function main() {
	const ws = await connect();
	await evaluate(ws, 'window.vscode.ipcRenderer.send("vscode:reloadWindow")');
	console.log('Reloaded');
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
