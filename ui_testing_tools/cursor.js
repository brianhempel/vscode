// Usage: node cursor.js <line-number>
// Moves the editor cursor to the given line using Ctrl+G (Go to Line).

import { connect, send, waitForPython } from './cdp.js';

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

	// Long enough for Go to Line to close and move the cursor, which is what
	// arms the re-run below. Without it the first status read can land before
	// anything has been set off and find nothing to wait for.
	await new Promise(r => setTimeout(r, 100));

	// Landing on a new line changes which visualizer is focused, which re-runs
	// the program 150ms later so the new one draws full-size and the old one
	// small. That is the render worth waiting for, not the cursor move.
	await waitForPython(ws);

	console.log(`Cursor moved to line ${line}`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
