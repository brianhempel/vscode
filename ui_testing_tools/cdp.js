const CDP_PORT = process.env.CDP_PORT || 9222;

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
	const targets = await fetch(`http://localhost:${CDP_PORT}/json`).then(r => r.json());
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
