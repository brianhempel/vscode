// Usage: node screenshot.js [OUT_PATH.png]

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { connect, send, waitForPython } from './cdp.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outFile = process.argv[2] || path.join(__dirname, '..', 'cdp_screenshot.png');

async function main() {
	const ws = await connect();
	// A capture is a picture of the last painted frame, so this is the tool the
	// render half of the wait exists for: without it a screenshot taken right
	// after a click shows the screen as it was before the click.
	await waitForPython(ws);
	const result = await send(ws, 'Page.captureScreenshot', { format: 'png' });
	const buf = Buffer.from(result.data, 'base64');
	fs.writeFileSync(outFile, buf);
	console.log(`Screenshot saved: ${outFile} (${buf.length} bytes)`);
	process.exit(0);
}

main().catch(e => { console.error(e.message); process.exit(1); });
