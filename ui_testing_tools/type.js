// Usage: node type.js 'hello world'
//    or: node type.js --key Enter
//    or: node type.js --key ArrowDown

import { connect, send } from './cdp.js';

const KEY_MAP = {
	Enter:      { key: 'Enter',     code: 'Enter',      keyCode: 13 },
	Escape:     { key: 'Escape',    code: 'Escape',     keyCode: 27 },
	Tab:        { key: 'Tab',       code: 'Tab',        keyCode: 9  },
	Backspace:  { key: 'Backspace', code: 'Backspace',  keyCode: 8  },
	Delete:     { key: 'Delete',    code: 'Delete',     keyCode: 46 },
	ArrowUp:    { key: 'ArrowUp',   code: 'ArrowUp',    keyCode: 38 },
	ArrowDown:  { key: 'ArrowDown', code: 'ArrowDown',  keyCode: 40 },
	ArrowLeft:  { key: 'ArrowLeft', code: 'ArrowLeft',  keyCode: 37 },
	ArrowRight: { key: 'ArrowRight',code: 'ArrowRight', keyCode: 39 },
	Space:      { key: ' ',         code: 'Space',      keyCode: 32 },
};

async function main() {
	const args = process.argv.slice(2);
	if (args.length === 0) {
		console.error('Usage: node type.js <text>');
		console.error('       node type.js --key <KeyName>');
		process.exit(1);
	}

	const ws = await connect();

	if (args[0] === '--key') {
		const keyName = args[1];
		const mapped = KEY_MAP[keyName];
		if (!mapped) {
			console.error(`Unknown key: ${keyName}`);
			console.error('Known keys: ' + Object.keys(KEY_MAP).join(', '));
			process.exit(1);
		}
		await send(ws, 'Input.dispatchKeyEvent', {
			type: 'keyDown', ...mapped, windowsVirtualKeyCode: mapped.keyCode, nativeVirtualKeyCode: mapped.keyCode,
		});
		await send(ws, 'Input.dispatchKeyEvent', {
			type: 'keyUp', ...mapped, windowsVirtualKeyCode: mapped.keyCode, nativeVirtualKeyCode: mapped.keyCode,
		});
		console.log(`Pressed key: ${keyName}`);
	} else {
		const text = args.join(' ');
		await send(ws, 'Input.insertText', { text });
		console.log(`Typed: ${text}`);
	}

	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
