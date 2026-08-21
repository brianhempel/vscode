// Usage: node type.js 'hello world'
//    or: node type.js --key Enter
//    or: node type.js --key ArrowDown
//    or: node type.js --key cmd+z          (modifiers: cmd/meta, ctrl, alt/opt, shift)
//    or: node type.js --key cmd+shift+p

import { connect, send, waitForPython } from './cdp.js';

// The bitmask CDP wants. Getting this wrong is silent: `modifiers: 2` for what
// you meant as Cmd sends Ctrl instead, the app ignores a chord it has no
// binding for, and it reads as "synthetic keys don't work here".
const MODIFIERS = { alt: 1, ctrl: 2, meta: 4, shift: 8 };
const MODIFIER_ALIASES = {
	cmd: 'meta', command: 'meta', super: 'meta', win: 'meta',
	control: 'ctrl', opt: 'alt', option: 'alt',
};

// *text* is what makes a key INSERT something. Without it Chromium raises the
// key event but generates no character, which is why `--key Enter` used to move
// nothing in the editor: the editor was hearing the keystroke and being handed
// nothing to write.
const KEY_MAP = {
	Enter:      { key: 'Enter',      code: 'Enter',      vk: 13, text: '\r' },
	Tab:        { key: 'Tab',        code: 'Tab',        vk: 9,  text: '\t' },
	Space:      { key: ' ',          code: 'Space',      vk: 32, text: ' '  },
	Escape:     { key: 'Escape',     code: 'Escape',     vk: 27 },
	Backspace:  { key: 'Backspace',  code: 'Backspace',  vk: 8  },
	Delete:     { key: 'Delete',     code: 'Delete',     vk: 46 },
	ArrowUp:    { key: 'ArrowUp',    code: 'ArrowUp',    vk: 38 },
	ArrowDown:  { key: 'ArrowDown',  code: 'ArrowDown',  vk: 40 },
	ArrowLeft:  { key: 'ArrowLeft',  code: 'ArrowLeft',  vk: 37 },
	ArrowRight: { key: 'ArrowRight', code: 'ArrowRight', vk: 39 },
	Home:       { key: 'Home',       code: 'Home',       vk: 36 },
	End:        { key: 'End',        code: 'End',        vk: 35 },
	PageUp:     { key: 'PageUp',     code: 'PageUp',     vk: 33 },
	PageDown:   { key: 'PageDown',   code: 'PageDown',   vk: 34 },
};
for (let n = 1; n <= 12; n++) {
	KEY_MAP[`F${n}`] = { key: `F${n}`, code: `F${n}`, vk: 111 + n };
}

// On macOS the editing shortcuts don't reach the page as chords at all: the OS
// turns them into NSResponder commands, and CDP goes in below that. So the
// command is named explicitly, which is the only way Cmd+Z undoes anything.
const MAC_COMMANDS = {
	'meta+z': ['undo'], 'meta+shift+z': ['redo'], 'meta+y': ['redo'],
	'meta+a': ['selectAll'], 'meta+x': ['cut'], 'meta+c': ['copy'],
	'meta+v': ['paste'],
};

const CANONICAL_ORDER = ['meta', 'ctrl', 'alt', 'shift'];

function describeKey(name) {
	if (KEY_MAP[name]) return KEY_MAP[name];
	if (name.length === 1) {
		const upper = name.toUpperCase();
		const code = /[A-Z]/.test(upper) ? `Key${upper}`
			: /[0-9]/.test(upper) ? `Digit${upper}` : undefined;
		return { key: name, code, vk: upper.charCodeAt(0), text: name };
	}
	return null;
}

function parseChord(chord) {
	const parts = chord.split('+');
	const name = parts.pop();
	let modifiers = 0;
	const held = [];
	for (const raw of parts) {
		const which = MODIFIER_ALIASES[raw.toLowerCase()] || raw.toLowerCase();
		if (!(which in MODIFIERS)) return { error: `Unknown modifier: ${raw}` };
		modifiers |= MODIFIERS[which];
		held.push(which);
	}
	const described = describeKey(name);
	if (!described) return { error: `Unknown key: ${name}` };
	return { described, modifiers, held, name };
}

async function main() {
	const args = process.argv.slice(2);
	if (args.length === 0) {
		console.error('Usage: node type.js <text>');
		console.error('       node type.js --key <Key or chord, e.g. Enter, cmd+z>');
		process.exit(1);
	}

	const ws = await connect();

	if (args[0] === '--key') {
		const chord = args[1];
		if (!chord) {
			console.error('Usage: node type.js --key <Key or chord>');
			process.exit(1);
		}
		const parsed = parseChord(chord);
		if (parsed.error) {
			console.error(parsed.error);
			console.error('Known keys: ' + Object.keys(KEY_MAP).join(', ')
				+ ', or any single character');
			process.exit(1);
		}
		const { described, modifiers, held, name } = parsed;

		// A chord is a shortcut rather than something to write, so the text is
		// dropped: Ctrl or Cmd held with `text` set types the character AND
		// fires the shortcut.
		const commanding = (modifiers & (MODIFIERS.ctrl | MODIFIERS.meta)) !== 0;
		const text = commanding ? undefined : described.text;
		// Named in one fixed order however the chord was typed, so `cmd+shift+z`
		// and `shift+cmd+z` are looked up as the same shortcut.
		const canonical = [...CANONICAL_ORDER.filter(m => held.includes(m)),
			name.toLowerCase()].join('+');
		const commands = process.platform === 'darwin'
			? MAC_COMMANDS[canonical] : undefined;

		const base = {
			key: described.key,
			code: described.code,
			windowsVirtualKeyCode: described.vk,
			nativeVirtualKeyCode: described.vk,
			modifiers,
		};
		await send(ws, 'Input.dispatchKeyEvent', {
			// rawKeyDown when nothing is being written, the way a browser
			// distinguishes a keystroke from a character.
			type: text ? 'keyDown' : 'rawKeyDown',
			...base,
			...(text ? { text, unmodifiedText: text } : {}),
			...(commands ? { commands } : {}),
		});
		await send(ws, 'Input.dispatchKeyEvent', { type: 'keyUp', ...base });
		console.log(`Pressed key: ${chord}`);
	} else {
		const text = args.join(' ');
		await send(ws, 'Input.insertText', { text });
		console.log(`Typed: ${text}`);
	}

	// Typing into the editor re-runs the program after a 100ms debounce, and a
	// key can be a shortcut that does anything at all. Wait for whatever it set
	// off to be finished and on screen before handing back.
	await waitForPython(ws);

	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
