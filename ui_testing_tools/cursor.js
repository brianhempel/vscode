// Usage: node cursor.js <line-number>
// Moves the editor cursor to the given line using Ctrl+G (Go to Line).

import { connect, send } from './cdp.js';

const line = process.argv[2];
if (!line || isNaN(Number(line))) {
	console.error('Usage: node cursor.js <line-number>');
	process.exit(1);
}

async function dispatchKey(ws, key, code, keyCode, modifiers) {
	await send(ws, 'Input.dispatchKeyEvent', {
		type: 'keyDown', key, code, keyCode,
		windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode,
		...modifiers,
	});
	await send(ws, 'Input.dispatchKeyEvent', {
		type: 'keyUp', key, code, keyCode,
		windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode,
		...modifiers,
	});
}

async function main() {
	const ws = await connect();

	// Ctrl+G opens "Go to Line"
	await send(ws, 'Input.dispatchKeyEvent', {
		type: 'keyDown', key: 'g', code: 'KeyG', keyCode: 71,
		windowsVirtualKeyCode: 71, nativeVirtualKeyCode: 71,
		modifiers: 2,
	});
	await send(ws, 'Input.dispatchKeyEvent', {
		type: 'keyUp', key: 'g', code: 'KeyG', keyCode: 71,
		windowsVirtualKeyCode: 71, nativeVirtualKeyCode: 71,
		modifiers: 2,
	});

	await new Promise(r => setTimeout(r, 300));

	// Type the line number
	await send(ws, 'Input.insertText', { text: line });

	await new Promise(r => setTimeout(r, 100));

	// Press Enter to go
	await dispatchKey(ws, 'Enter', 'Enter', 13, {});

	await new Promise(r => setTimeout(r, 100));

	console.log(`Cursor moved to line ${line}`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
