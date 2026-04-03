// Usage: node ready.js
// Polls CDP until the app is reachable (up to 20s), then prints target info.

const CDP_PORT = process.env.CDP_PORT || 9222;
const timeout = 20000;
const poll = 500;

async function main() {
	const deadline = Date.now() + timeout;

	while (Date.now() < deadline) {
		try {
			const res = await fetch(`http://localhost:${CDP_PORT}/json`);
			const targets = await res.json();
			const page = targets.find(t => t.type === 'page');
			if (page) {
				console.log(JSON.stringify(targets, null, 2));
				process.exit(0);
			}
		} catch {
			// not ready yet
		}
		await new Promise(r => setTimeout(r, poll));
	}

	console.error(`CDP not ready after ${timeout}ms on port ${CDP_PORT}`);
	process.exit(1);
}

main();
