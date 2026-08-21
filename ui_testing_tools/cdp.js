const CDP_PORT = process.env.CDP_PORT || 9222;

export const POLL_MS = 100;

export const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let nextId = 1;

export function send(ws, method, params = {}) {
	return new Promise((resolve, reject) => {
		const id = nextId++;
		const timeout = setTimeout(() => reject(new Error(`${method} timed out`)), 30000);
		const handler = (e) => {
			const msg = JSON.parse(typeof e.data === 'string' ? e.data : e.data.toString());
			if (msg.id === id) {
				clearTimeout(timeout);
				ws.removeEventListener('message', handler);
				if (msg.error) reject(new Error(msg.error.message));
				else resolve(msg.result);
			}
		};
		ws.addEventListener('message', handler);
		ws.send(JSON.stringify({ id, method, params }));
	});
}

export async function connect() {
	let targets;
	try {
		targets = await fetch(`http://localhost:${CDP_PORT}/json`).then(r => r.json());
	} catch {
		// Otherwise this is a bare "fetch failed", which reads like a bug in the
		// tool rather than an app that is not running.
		throw new Error('Nothing listening on port ' + CDP_PORT + '. Is the app running with --remote-debugging-port=' + CDP_PORT + '?');
	}
	const page = targets.find(t => t.type === 'page');
	if (!page) {
		throw new Error('No page target found. Is the app running with --remote-debugging-port=' + CDP_PORT + '?');
	}
	const ws = new WebSocket(page.webSocketDebuggerUrl);
	await new Promise((resolve, reject) => {
		ws.onopen = resolve;
		ws.onerror = () => reject(new Error('WebSocket connection failed'));
		setTimeout(() => reject(new Error('Connection timeout')), 10000);
	});
	return ws;
}

export async function evaluate(ws, expression) {
	const { result, exceptionDetails } = await send(ws, 'Runtime.evaluate', {
		expression,
		returnByValue: true,
		awaitPromise: true,
	});
	if (exceptionDetails) {
		const text = exceptionDetails.exception?.description || exceptionDetails.text || 'Evaluation failed';
		throw new Error(text);
	}
	return result.value;
}

// The centre of an element, plus whether it is actually showing. Being in the
// DOM and being visible are different questions here: much of the table's
// furniture -- the column ▾, the drag handles, the aggregation ✕ -- is
// `.snc-hover-hidden`, which is present but `visibility: hidden` until an
// ancestor is hovered. Waiting to *click* one means waiting for it to appear;
// waiting for the window to have finished drawing means waiting for visible.
export async function measure(ws, selector) {
	const found = await evaluate(ws, `
		(() => {
			let el;
			try { el = document.querySelector(${JSON.stringify(selector)}); }
			catch { return 'bad-selector'; }
			if (!el) return null;
			const r = el.getBoundingClientRect();
			const style = getComputedStyle(el);
			return {
				x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height,
				visible: r.width > 0 && r.height > 0 && style.visibility !== 'hidden'
					&& style.display !== 'none' && style.opacity !== '0',
			};
		})()
	`);
	if (found === 'bad-selector') {
		throw Object.assign(new Error(`Invalid CSS selector: ${selector}`), { fatal: true });
	}
	return found;
}

export async function waitFor(ws, selector, { visible = false, timeout = 10000 } = {}) {
	const deadline = Date.now() + timeout;
	for (;;) {
		const rect = await measure(ws, selector);
		if (rect && (!visible || rect.visible)) {
			return rect;
		}
		if (Date.now() >= deadline) {
			throw new Error(`Timed out after ${timeout}ms waiting for `
				+ `${visible ? 'visible ' : ''}${selector}`);
		}
		await sleep(POLL_MS);
	}
}

// Retried whole, socket and all, because a window that is still starting up --
// or has just been told to reload -- drops the connection out from under a
// plain poll loop. `check` is handed a live socket and returns what it was
// waiting for, or a falsy value to be asked again.
export async function waitReconnecting(check, description, timeout = 20000) {
	const deadline = Date.now() + timeout;
	let ws = null;
	let last = null;
	for (;;) {
		try {
			if (!ws || ws.readyState !== WebSocket.OPEN) {
				ws = await connect();
			}
			const got = await check(ws);
			if (got) {
				return got;
			}
		} catch (e) {
			if (e.fatal) {
				throw e;
			}
			last = e;
			ws = null;
		}
		if (Date.now() >= deadline) {
			throw new Error(`Timed out after ${timeout}ms waiting for ${description}`
				+ (last ? ` (last error: ${last.message})` : ''));
		}
		await sleep(POLL_MS);
	}
}

// Whether Python has anything left to do, and whether what it has already said
// is on screen. Defined by SNCController in snc.ts, which is the only thing
// that knows: nothing in the DOM distinguishes a half-rendered visualizer from
// a finished one.
//
// The two frames are what makes this a render wait and not just a Python wait.
// The renderer's own work -- innerHTML, view zones, widget positions -- is
// finished synchronously before the status goes quiet, but the paint that shows
// it is not, and a screenshot taken in between catches the previous frame. They
// are raced against a timer because a window that is covered or minimised stops
// being handed frames at all, and a wait that can hang is worse than one that
// is occasionally early.
const PYTHON_SETTLED = `(async () => {
	const read = () => globalThis._sncPythonStatus ? _sncPythonStatus() : null;
	const status = read();
	if (!status || !status.python) { return status; }
	if (status.busy || status.runsSettled === 0) { return status; }
	await Promise.race([
		new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))),
		new Promise(r => setTimeout(r, 250)),
	]);
	return read();
})()`;

export function pythonStatus(ws) {
	return evaluate(ws, PYTHON_SETTLED);
}

// A status with nothing left to wait for. `python: false` counts: no run is
// coming, so every tool but wait_for_python.js should carry on rather than sit
// there until its timeout. `python: null` does not -- that is a window whose
// editor has no file in it yet, which is what a reloading one looks like on the
// way back, and calling it settled is how you end up reading a blank screen.
// `runsSettled` matters as much as `busy` does: a window that has not started
// its first run yet is idle in exactly the way a finished one is.
export function pythonReady(status) {
	if (!status || status.python === null) {
		return false;
	}
	return !status.python || (!status.busy && status.runsSettled > 0);
}

function describePython(status) {
	if (!status) {
		return 'no status in the renderer (built and reloaded?)';
	}
	if (status.python === null) {
		return 'no file open in the editor yet';
	}
	if (!status.busy && status.runsSettled === 0) {
		return 'no run has started yet';
	}
	return `still ${status.reasons.join(', ')}`;
}

export async function waitForPython(ws, timeout = 10000) {
	const deadline = Date.now() + timeout;
	let last = null;
	for (;;) {
		last = await pythonStatus(ws);
		if (pythonReady(last)) {
			return last;
		}
		if (Date.now() >= deadline) {
			throw new Error(`Timed out after ${timeout}ms waiting for Python `
				+ `-- ${describePython(last)}`);
		}
		await sleep(POLL_MS);
	}
}

// For a window that may still be coming up or going down -- see
// waitReconnecting. `check` runs after Python is settled, so a caller can wait
// for something that only exists once the visualizers have been drawn.
export async function waitForPythonReconnecting(timeout = 20000, check = null) {
	let last = null;
	try {
		return await waitReconnecting(async (ws) => {
			last = await pythonStatus(ws);
			if (!pythonReady(last)) {
				return null;
			}
			return check ? await check(ws, last) : last;
		}, 'Python', timeout);
	} catch (e) {
		if (e.fatal) {
			throw e;
		}
		throw new Error(`${e.message} -- ${describePython(last)}`);
	}
}
