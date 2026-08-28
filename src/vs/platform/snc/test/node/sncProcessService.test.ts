/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ChildProcess, spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { IProcessOptions } from '../../common/snc.js';
import { SNCProcessService } from '../../node/sncProcessService.js';

/**
 * Which worker a run is given, when a pool refills, and what a waiter can reach
 * are policy decisions with no Python in them, so they are tested here against
 * fake worker processes rather than real ones.
 */

/** A worker process that says only what the test tells it to. */
class FakeChild extends EventEmitter {
	readonly stdout = new EventEmitter();
	readonly stderr = new EventEmitter();
	readonly writes: string[] = [];
	killed = false;

	/** The last checkpoint this worker has reported, so `pump` knows its rung. */
	reported = 0;
	/** What it reports at checkpoint 3. */
	pauseStep = 10;

	readonly stdin = { write: (text: string) => { this.writes.push(text); return true; } };

	kill(): boolean {
		if (!this.killed) {
			this.killed = true;
			this.emit('close', 0, null);
		}
		return true;
	}

	/** Everything the service has said to this worker, parsed. */
	sent(): any[] {
		return this.writes.map(text => JSON.parse(text));
	}

	says(msg: object): void {
		this.stdout.emit('data', Buffer.from(JSON.stringify(msg) + '\n'));
	}
}

interface Harness {
	service: SNCProcessService;
	children: FakeChild[];
	pools(): { cp1: number; cp2: number; cp3: number };
}

const WD = 'wd'; // relative, so clearUrlCacheOnce never touches the disk

function createHarness(): Harness {
	const children: FakeChild[] = [];
	const spawnFake = ((..._args: unknown[]) => {
		const child = new FakeChild();
		children.push(child);
		return child as unknown as ChildProcess;
	}) as unknown as typeof spawn;

	const service = new SNCProcessService(spawnFake);
	const pools = () => ({
		cp1: (service as any).checkpoint1Pool.length,
		cp2: (service as any).checkpoint2Pool.length,
		cp3: (service as any).checkpoint3Pool.length,
	});
	return { service, children, pools };
}

function options(over: Partial<IProcessOptions> = {}): IProcessOptions {
	return { workingDirectory: WD, ...over };
}

/** Let promises and 0ms timers run. */
function settle(): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, 0));
}

/** Advance every live worker one rung, exactly as a real one would. */
function pump(h: Harness): void {
	for (const child of [...h.children]) {
		if (child.killed) { continue; }
		const sent = child.sent();
		if (child.reported === 0) {
			child.reported = 1;
			child.says({ type: 'checkpoint_ready', checkpoint: 1, pid: 1 });
		} else if (child.reported === 1 && sent.some(m => m.type === 'init_imports')) {
			child.reported = 2;
			child.says({ type: 'checkpoint_ready', checkpoint: 2, pid: 1 });
		} else if (child.reported === 2 && sent.some(m => m.type === 'init_run')) {
			const target = sent.find(m => m.type === 'init_run').checkpoint3;
			child.reported = 3;
			child.says({
				type: 'checkpoint_ready', checkpoint: 3, pid: 1,
				line: target.line, visIndex: target.visIndex, step: child.pauseStep
			});
		}
	}
}

/**
 * Dispatch a run and drive the pool until it settles, as the worker processes
 * would. Returns the worker the run was written to, if any.
 */
async function dispatch(h: Harness, content: string, opts: IProcessOptions, runId: string): Promise<FakeChild | undefined> {
	const before = new Set(h.children.filter(c => c.sent().some(m => m.type === 'run')));
	const started = h.service.startProgram(content, opts, runId);
	// Enough rounds for a cold worker to climb the whole ladder.
	for (let i = 0; i < 5; i++) {
		await settle();
		pump(h);
	}
	await started;
	await settle();
	pump(h);
	await settle();
	return h.children.find(c => !before.has(c) && c.sent().some(m => m.type === 'run'));
}

/**
 * Kill the paused workers and let the pool refill, returning one of the fresh
 * replacements -- a worker at the bottom of the checkpoint 3 ladder.
 */
function respawnCheckpoint3Pool(h: Harness): FakeChild {
	for (const worker of [...(h.service as any).checkpoint3Pool]) {
		(worker.child as unknown as FakeChild).kill();
	}
	(h.service as any).ensurePoolFilled(WD);
	const fresh = h.children.find(c => !c.killed && c.reported === 0);
	assert.ok(fresh, 'the checkpoint 3 pool did not refill');
	return fresh;
}

/** Leave the other pools with nothing to hand out, so a run has to wait. */
function makeNothingElseReady(h: Harness): void {
	for (const worker of [...(h.service as any).checkpoint1Pool, ...(h.service as any).checkpoint2Pool]) {
		worker.ready = false;
	}
}

/** The widget checkpoint 3 warms towards in most of these tests. */
const WARM_AT = { line: 12, visIndex: 0 };

/** A run that has already interacted with WARM_AT, so checkpoint 3 applies. */
function warmedOptions(over: Partial<IProcessOptions> = {}): IProcessOptions {
	return options({ checkpoint3WarmAt: WARM_AT, checkpoint3ResumeAtStep: 10, ...over });
}

suite('SNCProcessService checkpoint 3', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	function harness(): Harness {
		const h = createHarness();
		store.add(h.service);
		return h;
	}

	// ---- the warm ladder ----------------------------------------------

	test('a checkpoint 3 worker climbs checkpoint 1, then 2, then pauses', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const pool: any[] = (h.service as any).checkpoint3Pool;
		assert.strictEqual(pool.length, 5, 'the checkpoint 3 pool should be full');
		for (const worker of pool) {
			const sent = (worker.child as unknown as FakeChild).sent();
			assert.ok(sent.some(m => m.type === 'init_imports'), 'never told to load imports');
			const init = sent.find(m => m.type === 'init_run');
			assert.ok(init, 'never told which widget to pause before');
			assert.deepStrictEqual(init.checkpoint3, WARM_AT);
			assert.strictEqual(worker.ready, true);
			assert.strictEqual(worker.checkpoint, 3);
			assert.strictEqual(worker.pauseStep, 10);
		}
	});

	test('a waiting run preempts the last rung of the climb', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		// A worker part way up the ladder: it has loaded the imports but not
		// yet reported checkpoint 2.
		const climbing = respawnCheckpoint3Pool(h);
		climbing.says({ type: 'checkpoint_ready', checkpoint: 1, pid: 1 });
		await settle();
		assert.ok(climbing.sent().some(m => m.type === 'init_imports'));

		// Now a run needs a worker, and nothing else is ready. A waiting run
		// outranks warming for a future one.
		makeNothingElseReady(h);
		const started = h.service.startProgram('x = 1\n', warmedOptions(), 'r3');
		await settle();
		climbing.says({ type: 'checkpoint_ready', checkpoint: 2, pid: 1 });
		await settle();

		assert.ok(!climbing.sent().some(m => m.type === 'init_run'), 'warmed instead of serving the waiting run');
		assert.ok(!(h.service as any).checkpoint3Pool.some((w: any) => w.child === climbing),
			'a preempted worker must leave the checkpoint 3 pool, or it is stranded there');
		assert.ok(climbing.sent().some(m => m.type === 'run'), 'the waiting run never got it');
		await started;
	});

	test('a paused worker is never handed to a waiter', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		// A waiter carries no resume step, so resuming one of these from
		// someone else's pause point would be wrong.
		makeNothingElseReady(h);
		let resolved = false;
		const waiting = (h.service as any).takeReadyWorker('') as Promise<unknown>;
		waiting.then(() => { resolved = true; }, () => { /* abandoned below */ });

		const paused: any = (h.service as any).checkpoint3Pool[0];
		assert.strictEqual(paused.checkpoint, 3);
		(h.service as any).resolveNextWaiter(paused);
		await settle();

		assert.strictEqual(resolved, false, 'a waiter was given a paused worker');
		assert.ok((h.service as any).checkpoint3Pool.includes(paused), 'it left the pool anyway');
		(h.service as any).abandonQueuedRuns();
		await settle();
	});

	// ---- matching ------------------------------------------------------

	test('a run that need not render anything before the pause takes a paused worker', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const before = (h.service as any).checkpoint3Pool.length;
		const served = await dispatch(h, 'x = 1\n', warmedOptions({ checkpoint3ResumeAtStep: 12 }), 'r3');
		assert.ok(served, 'no worker was given the run');
		assert.strictEqual(served.reported, 3, 'the run went to a worker that had not paused');
		assert.strictEqual((h.service as any).checkpoint3Pool.length, before, 'the pool did not refill');
	});

	test('a run that must render something before the pause does not', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const served = await dispatch(h, 'x = 1\n', warmedOptions({ checkpoint3ResumeAtStep: 3 }), 'r3');
		assert.ok(served, 'no worker was given the run');
		assert.notStrictEqual(served.reported, 3, 'a paused worker served a run that starts before its pause');
	});

	test('a run with no resume step never takes a paused worker', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const served = await dispatch(h, 'x = 1\n', options({ checkpoint3WarmAt: WARM_AT }), 'r3');
		assert.ok(served);
		assert.notStrictEqual(served.reported, 3);
	});

	// ---- the key -------------------------------------------------------

	test('an edit kills the paused workers and spawns no replacements', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
		const paused = (h.service as any).checkpoint3Pool.map((w: any) => w.child as unknown as FakeChild);
		assert.strictEqual(paused.length, 5);

		const spawnedBefore = h.children.length;
		const started = h.service.startProgram('x = 2\n', warmedOptions(), 'r3');
		await settle();

		assert.ok(paused.every((c: FakeChild) => c.killed), 'a worker paused in the old program survived');
		assert.strictEqual((h.service as any).checkpoint3Pool.length, 0);
		// Re-running a prefix we are about to discard once per keystroke is
		// exactly the churn the deferral exists to avoid.
		const initRuns = h.children.slice(spawnedBefore).filter(c => c.sent().some(m => m.type === 'init_run'));
		assert.strictEqual(initRuns.length, 0, 'respawned checkpoint 3 workers mid-edit');
		for (let i = 0; i < 5; i++) { pump(h); await settle(); }
		await started;
	});

	test('moving the cursor invalidates, because focus changes what every widget renders', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions({ focusedLine: 3 }), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions({ focusedLine: 3 }), 'r2');
		const paused = (h.service as any).checkpoint3Pool.map((w: any) => w.child as unknown as FakeChild);
		assert.strictEqual(paused.length, 5);

		await dispatch(h, 'x = 1\n', warmedOptions({ focusedLine: 4 }), 'r3');
		assert.ok(paused.every((c: FakeChild) => c.killed), 'a worker warmed under the old focus survived');
	});

	test('moving to another widget invalidates, and the next warm targets it', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
		const paused = (h.service as any).checkpoint3Pool.map((w: any) => w.child as unknown as FakeChild);

		const elsewhere = { line: 20, visIndex: 1 };
		await dispatch(h, 'x = 1\n', warmedOptions({ checkpoint3WarmAt: elsewhere, checkpoint3ResumeAtStep: 30 }), 'r3');
		assert.ok(paused.every((c: FakeChild) => c.killed), 'a worker warmed at the old widget survived');

		// The next run's refill warms at the new widget.
		await dispatch(h, 'x = 1\n', warmedOptions({ checkpoint3WarmAt: elsewhere, checkpoint3ResumeAtStep: 30 }), 'r4');
		const pool: any[] = (h.service as any).checkpoint3Pool;
		assert.ok(pool.length > 0, 'the pool never refilled at the new widget');
		for (const worker of pool) {
			const init = (worker.child as unknown as FakeChild).sent().find(m => m.type === 'init_run');
			assert.deepStrictEqual(init.checkpoint3, elsewhere);
		}
	});

	// ---- refilling -----------------------------------------------------

	test('a drag refills the pool at every dispatch, not only at run end', async () => {
		// Each event supersedes the run before it, so none reaches `end`.
		// Refilling only at run end would give five fast events and then
		// today's speed for the rest of the gesture.
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
		assert.strictEqual(h.pools().cp3, 5);

		for (let i = 0; i < 5; i++) {
			await dispatch(h, 'x = 1\n', warmedOptions(), `drag-${i}`);
			assert.strictEqual(h.pools().cp3, 5, `pool drained after ${i + 1} drag events`);
		}
	});

	test('typing spawns no checkpoint 3 workers at all', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const spawnedBefore = h.children.length;
		for (let i = 0; i < 5; i++) {
			await dispatch(h, `x = ${i}\n`, warmedOptions(), `type-${i}`);
		}
		const initRuns = h.children.slice(spawnedBefore).filter(c => c.sent().some(m => m.type === 'init_run'));
		assert.strictEqual(initRuns.length, 0, 'warmed a worker on code the user was still editing');
	});

	test('handing a worker to a waiter does not spawn checkpoint 3 workers', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');

		const spawnedBefore = h.children.length;
		const idle = (h.service as any).checkpoint1Pool[0];
		assert.ok(idle, 'expected a checkpoint 1 worker to hand out');
		(h.service as any).workerWaiters.push({ resolve: () => { }, reject: () => { } });
		(h.service as any).resolveNextWaiter(idle);
		await settle();

		const initRuns = h.children.slice(spawnedBefore).filter(c => c.sent().some(m => m.type === 'init_run'));
		assert.strictEqual(initRuns.length, 0);
	});

	// ---- lifecycle -----------------------------------------------------

	test('a warm that never reaches its pause is killed and not retried', async () => {
		const h = harness();
		const clock: Array<() => void> = [];
		const realSetTimeout = global.setTimeout;
		(global as any).setTimeout = ((fn: () => void, ms: number) => {
			if (ms >= 1000) { clock.push(fn); return { unref() { } }; }
			return realSetTimeout(fn, ms);
		});
		try {
			await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
			await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
			const warming = h.children.filter(c => !c.killed && c.sent().some(m => m.type === 'init_run'));
			assert.ok(warming.length > 0);

			clock.forEach(fire => fire()); // every warm deadline expires
			assert.ok(warming.every(c => c.killed), 'a wedged warm was left spinning');

			const spawnedBefore = h.children.length;
			await dispatch(h, 'x = 1\n', warmedOptions(), 'r3');
			const retried = h.children.slice(spawnedBefore).filter(c => c.sent().some(m => m.type === 'init_run'));
			assert.strictEqual(retried.length, 0, 'kept respawning into the same wall');
		} finally {
			(global as any).setTimeout = realSetTimeout;
		}
	});

	test('a worker that exits leaves the checkpoint 3 pool', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
		const before = h.pools().cp3;
		const paused = (h.service as any).checkpoint3Pool[0].child as unknown as FakeChild;

		paused.emit('close', 0, null);
		assert.strictEqual(h.pools().cp3, before - 1);
	});

	test('changing the working directory drains the checkpoint 3 pool too', async () => {
		const h = harness();
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		await dispatch(h, 'x = 1\n', warmedOptions(), 'r2');
		const paused = (h.service as any).checkpoint3Pool.map((w: any) => w.child as unknown as FakeChild);
		assert.ok(paused.length > 0);

		const started = h.service.startProgram('x = 1\n', warmedOptions({ workingDirectory: 'other' }), 'r3');
		await settle();
		assert.ok(paused.every((c: FakeChild) => c.killed), 'a worker for the old directory survived');
		for (let i = 0; i < 5; i++) { pump(h); await settle(); }
		await started;
	});

	test('resumed is forwarded to the editor, and only with a run id', async () => {
		const h = harness();
		const seen: any[] = [];
		store.add(h.service.onStream(msg => { if (msg.type === 'resumed') { seen.push(msg); } }));

		const served = await dispatch(h, 'x = 1\n', warmedOptions(), 'r1');
		assert.ok(served);
		served.says({ type: 'resumed', line: 12, visIndex: 0, step: 10 }); // no run id
		served.says({ type: 'resumed', run_id: 'r1', line: 12, visIndex: 0, step: 10 });

		assert.deepStrictEqual(seen.map(m => [m.runId, m.line, m.visIndex, m.step]), [['r1', 12, 0, 10]]);
	});
});
