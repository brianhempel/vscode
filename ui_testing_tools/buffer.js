// Usage: node buffer.js
// Prints the current editor's text buffer (unsaved content).
// Requires the SNC controller's _sncEditor global (set in snc.ts).

import { connect, evaluate } from './cdp.js';

async function main() {
	const ws = await connect();
	const text = await evaluate(ws, `
		(() => {
			const editor = globalThis._sncEditor;
			if (!editor) return null;
			const model = editor.getModel();
			if (!model) return null;
			return model.getLinesContent().join('\\n');
		})()
	`);
	if (text === null) {
		console.error('No editor buffer found (is a Python file open?)');
		process.exit(1);
	}
	process.stdout.write(text);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
